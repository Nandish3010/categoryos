"""The promotions planner around its engine. Python (``engine``) decides which SKUs go on promo, at what depth, with what stock and what
funding ask. The model does three things from the engine's numbers and the vendors' own words only:

1. READS the vendors' funding replies into structured offers. Every share, sales target, banner position and lead time is a
   ``model_extraction`` claim checked against the reply text and self-corrected (``selfcorrect.self_correct``); an offer with a number
   that is still wrong is dropped, never valued;
2. WRITES the event brief, 3. the vendor funding emails. Every number in the prose is a figure whose claim the verifier recomputes; a
   sentence with a number that fails (or that has no figure) is struck.

A vendor's verified conditional offer is valued by the deal evaluator (``engine.value_offer``). Emails wait in the outbox for a person;
approving the plan queues the stock-up POs, all SIMULATED."""

from datetime import date
from typing import Any

from app import llm
from app.agents.context import RunContext
from app.errors import CategoryOSError
from app.ops import figures as fg
from app.ops import outbox
from app.ops.chaser import draft_record
from app.ops.data import load as load_ops
from app.ops.promotions import claims as pc
from app.ops.promotions import data as pdata
from app.ops.promotions import engine
from app.ops.promotions import prompts as pr
from app.ops.promotions import tools as pt
from app.ops.promotions.schemas import (
    FundingReading,
    FundingRepliesFinal,
    FundingTerm,
    PromoBriefFinal,
)
from app.ops.review import impact_for
from app.ops.runclaims import compact, fmt_shown, strike
from app.ops.schemas import EmailDraft, EmailsFinal, Figure
from app.parsing import PARSER_VERSION
from app.schemas import Claim, ClaimFix, Evidence, SourceRef
from app.selfcorrect import self_correct
from app.verify import inject_fault, verify_all

STAGE = fg.STAGE


# ---------- reading the replies ----------


class Where:
    def __init__(self, reading: FundingReading, term: int | None, field: str) -> None:
        self.reading, self.term, self.field = reading, term, field


def _claim(reply: pdata.FundingReply, position: int, cid: str, text: str, metric: str, unit: str, value: float, quote: str, sha: str) -> Claim:
    return Claim(
        id=f"promo:{reply.id}:{cid}", text=text, value=value, metric=metric, unit=unit,  # type: ignore[arg-type]
        source_ref=SourceRef(file=pdata.REPLIES, key=reply.id, column="body"),
        evidence=Evidence(row=position, header="body", raw_value=quote, normalized_value=value, parser_version=PARSER_VERSION, sha256=sha),
        origin="model_extraction",
    )


def build_claims(readings: list[FundingReading], replies: dict[str, tuple[int, pdata.FundingReply]]) -> list[tuple[Claim, Where]]:
    out: list[tuple[Claim, Where]] = []
    sha = pdata.file_sha256()
    for rd in readings:
        if rd.reply_id not in replies:
            continue
        position, reply = replies[rd.reply_id]
        for i, t in enumerate(rd.terms):
            if t.share_pct is not None:
                out.append((_claim(reply, position, f"t{i}:share", f"{reply.vendor_id} funds {t.share_pct:g}% of the markdown", "promo_ext_share_pct", "pct", t.share_pct / 100, t.quote, sha), Where(rd, i, "share_pct")))
            if t.threshold_units is not None:
                out.append((_claim(reply, position, f"t{i}:threshold", f"{reply.vendor_id} wants {t.threshold_units:g} units sold", "promo_ext_threshold_units", "units", float(t.threshold_units), t.quote, sha), Where(rd, i, "threshold_units")))
            if t.banner_top_n is not None:
                out.append((_claim(reply, position, f"t{i}:banner", f"{reply.vendor_id} asks for a top-{t.banner_top_n} banner", "promo_ext_banner_top_n", "units", float(t.banner_top_n), t.quote, sha), Where(rd, i, "banner_top_n")))
        if rd.lead_time_days is not None and rd.lead_time_quote:
            out.append((_claim(reply, position, "lead", f"{reply.vendor_id} states a lead time of {rd.lead_time_days} days", "promo_ext_lead_days", "units", float(rd.lead_time_days), rd.lead_time_quote, sha), Where(rd, None, "lead_time_days")))
    return out


def apply_fix(where: Where, fix: ClaimFix) -> None:
    rd = where.reading
    if where.term is None:
        rd.lead_time_days = int(fix.value)
        if fix.transcript_quote:
            rd.lead_time_quote = fix.transcript_quote
        return
    t: FundingTerm = rd.terms[where.term]
    if fix.transcript_quote:
        t.quote = fix.transcript_quote
    if where.field == "share_pct":
        t.share_pct = float(fix.value)  # the percent number, as the model wrote it ("30" for 30%)
    elif where.field == "threshold_units":
        t.threshold_units = float(fix.value)
    elif where.field == "banner_top_n":
        t.banner_top_n = int(fix.value)


def offers_from(readings: list[FundingReading], claims: dict[str, Claim], replies: dict[str, tuple[int, pdata.FundingReply]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """(vendor id -> verified offer, vendor id -> note). A term whose number the verifier rejected is dropped; a decline is noted."""
    offers: dict[str, dict[str, Any]] = {}
    notes: dict[str, str] = {}
    for rd in readings:
        if rd.reply_id not in replies:
            continue
        reply = replies[rd.reply_id][1]
        if rd.stance == "decline":
            notes[reply.vendor_id] = "declined"
            continue
        for i, t in enumerate(rd.terms):
            ids = [f"promo:{reply.id}:t{i}:{k}" for k, v in (("share", t.share_pct), ("threshold", t.threshold_units), ("banner", t.banner_top_n)) if v is not None]
            if t.share_pct is None or any(claims[c].status != "verified" for c in ids if c in claims):
                notes.setdefault(reply.vendor_id, "unreadable")
                continue
            if reply.vendor_id not in offers:
                offers[reply.vendor_id] = {
                    "share_pct": float(t.share_pct), "threshold_units": t.threshold_units, "banner_top_n": t.banner_top_n, "scope": list(t.scope),
                    "reply_id": reply.id, "quote": t.quote, "window_days": t.window_days,
                }
    return offers, notes


async def read_replies(ctx: RunContext, ev_id: str, ev_name: str) -> tuple[list[FundingReading], list[Claim], dict[str, tuple[int, pdata.FundingReply]], Any]:
    replies = {r.id: (pdata.position(r.id), r) for r in pdata.replies_for(ev_id)}
    if not replies:
        return [], [], replies, None
    msgs = pr.messages(pr.READ_SYSTEM, pr.READ_USER, event_name=ev_name, event_id=ev_id)
    res = await llm.run_tools(STAGE, f"promo_funding_replies_{ev_id}", msgs, pt.select(pt.READ_TOOLS), max_steps=2, schema=FundingRepliesFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, f"promo_funding_replies_{ev_id}", res)
    final = res.parsed
    assert isinstance(final, FundingRepliesFinal)
    readings = list(final.readings)
    built = build_claims(readings, replies)
    where = {c.id: w for c, w in built}
    first = verify_all([c for c, _ in built]).claims
    for c in first:
        ctx.emit("claim_checked", STAGE, {"claim": c.model_dump(mode="json")})

    def rebuild(claim: Claim, fix: ClaimFix) -> Claim | None:
        apply_fix(where[claim.id], fix)
        return next((c for c, _ in build_claims(readings, replies) if c.id == claim.id), None)

    fixed = await self_correct(
        ctx, STAGE, first, task=f"promo_funding_replies_{ev_id}", messages=msgs, previous=res.content, rebuild=rebuild,
        check=lambda batch: verify_all(batch).claims,
    )
    return readings, fixed, replies, res


# ---------- figures and drafts ----------


def _figures_for(claims: list[Claim]) -> list[Figure]:
    return [Figure(metric=c.metric, key=c.source_ref.key, value=c.value, shown=fmt_shown(c.unit, c.value), text=c.text) for c in claims]


def template_email(ev_id: str, block: dict[str, Any], valued: dict[str, Any] | None) -> EmailDraft:
    """The deterministic funding email when the model wrote none: built only from the engine's numbers, with fixed wording per case."""
    contact = next((v for v in load_ops().vendors.values() if v.id == block["vendor_id"]), None)
    name = contact.contact_name.split()[0] if contact else "team"
    by = {c.metric: c for c in pc.vendor_claims(ev_id, block, valued)}
    ask, share = by["promo_vendor_ask_inr"], by["promo_vendor_ask_share_pct"]
    kind = (valued or {}).get("counter", {}).get("kind")
    decision = (valued or {}).get("decision")
    counted, covers, oask = by.get("promo_offer_counted_inr"), by.get("promo_offer_covers_ask_pct"), by.get("promo_offer_ask_inr")
    if valued is None or decision == "declined" or counted is None or oask is None or covers is None:
        take = [share, ask]
        line = (
            f"Thanks for letting us know. Would a smaller share of the markdown be possible? Our ask is {fmt_shown('inr', ask.value)}."
            if decision == "declined"
            else f"For the sale we would like {block['brand']} to fund {fmt_shown('pct', share.value)} of the markdown on the SKUs we are promoting, worth {fmt_shown('inr', ask.value)}."
        )
    else:
        take = [counted, covers, oask]
        head = f"Thank you for the offer. It is worth {fmt_shown('inr', counted.value)} to us, {fmt_shown('pct', covers.value)} of the {fmt_shown('inr', oask.value)} we asked for on those SKUs."
        if kind == "accept":
            line = head.replace("Thank you for the offer.", "Thank you, we accept.")
        elif kind == "top_up":
            take.append(share)
            line = f"{head} Could you raise the share to {fmt_shown('pct', share.value)} of the markdown?"
        elif kind == "counter":
            prob = by.get("promo_offer_probability_pct")
            if prob is not None:
                take.append(prob)
                head = (
                    f"Thank you for the offer. On our forecast the range reaching its sales target in the event is only {fmt_shown('pct', prob.value)} likely, so it counts as "
                    f"{fmt_shown('inr', counted.value)} against the {fmt_shown('inr', oask.value)} we asked for on those SKUs."
                )
                take = [x for x in take if x is not covers]
            line = f"{head} Could you give the target a longer window, or turn the bonus into a guaranteed share?"
        else:
            line = f"{head} Could you lower the sales target or make the share unconditional, so that it counts in full?"
    lines = [f"Hi {name},", "", line, "", "Could you confirm by Friday?", "", "Thanks"]
    return EmailDraft(vendor_id=block["vendor_id"], subject=f"Funding for the sale: {block['brand']}", body="\n".join(lines), figures=_figures_for(take))


# ---------- the whole event ----------


def _ev(ev_id: str):
    return engine.event(ev_id)


def value_vendors(event_id: str, plan: dict[str, Any], offers: dict[str, dict[str, Any]], notes: dict[str, str]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """For every vendor on the plan: the vendor block and the engine's value of its verified offer (None: no reply; declined: noted)."""
    out: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for block in plan["vendors"]:
        vid = block["vendor_id"]
        valued: dict[str, Any] | None = None
        if vid in offers:
            o = offers[vid]
            key = pc.offer_key(event_id, vid, o)
            valued = {**pc.valued_offer(key), "offer_key": key}
            valued["counter"] = engine.counter_for(block, valued)
            valued["reply_id"], valued["quote"] = o["reply_id"], o["quote"]
        elif notes.get(vid) == "declined":
            valued = {
                "decision": "declined", "call": f"{block['brand']} declined to fund the event.", "face_inr": 0.0, "counted_inr": 0.0, "ask_inr": block["ask_inr"],
                "covers_ask_pct": 0.0, "probability": None, "assessment": None, "offer_key": None,
                "counter": {"kind": "ask", "text": f"Ask {block['brand']} whether a smaller share is possible."},
            }
        out.append((block, valued))
    return out


async def generate(event_id: str, inject: bool = False) -> dict[str, Any]:
    ev = _ev(event_id)
    plan = engine.plan(event_id)
    ctx = fg.new_ctx(f"promo-{event_id}", date.fromisoformat(plan["as_of"]))
    ctx.emit("stage_started", STAGE, {"task": "promotions", "event": event_id, "planned_skus": plan["totals"]["planned_skus"]})

    # 1. read the vendors' funding replies; only verified numbers become offers
    readings, rclaims, replies, read_res = await read_replies(ctx, event_id, ev.name)
    rby = {c.id: c for c in rclaims}
    offers, notes = offers_from(readings, rby, replies)

    # 2. value each vendor's offer with the engine (the deal evaluator) and decide what to say back
    vendors_out = value_vendors(event_id, plan, offers, notes)
    valued_by_vendor = {b["vendor_id"]: v for b, v in vendors_out if v is not None}

    token = pt.OFFERS.set(valued_by_vendor)
    try:
        msgs = pr.messages(pr.BRIEF_SYSTEM, pr.BRIEF_USER, event_name=ev.name, event_id=event_id, start=ev.start, end=ev.end)
        brief_res = await llm.run_tools(STAGE, f"promo_brief_{event_id}", msgs, pt.select(pt.BRIEF_TOOLS), max_steps=5, schema=PromoBriefFinal, on_step=ctx.step_emitter(STAGE))
        fg.emit_model_call(ctx, f"promo_brief_{event_id}", brief_res)
        brief = brief_res.parsed
        assert isinstance(brief, PromoBriefFinal)

        email_msgs = pr.messages(pr.EMAIL_SYSTEM, pr.EMAIL_USER, event_name=ev.name, event_id=event_id, vendors=", ".join(b["vendor_id"] for b, _ in vendors_out) or "none")
        email_res = await llm.run_tools(STAGE, f"promo_funding_emails_{event_id}", email_msgs, pt.select(pt.EMAIL_TOOLS), max_steps=4, schema=EmailsFinal, on_step=ctx.step_emitter(STAGE))
        fg.emit_model_call(ctx, f"promo_funding_emails_{event_id}", email_res)
        efinal = email_res.parsed
        assert isinstance(efinal, EmailsFinal)
    finally:
        pt.OFFERS.reset(token)

    wanted = {b["vendor_id"] for b, _ in vendors_out}
    written = {e.vendor_id: e for e in efinal.emails if e.vendor_id in wanted}
    emails: list[tuple[EmailDraft, str, dict[str, Any], dict[str, Any] | None]] = []
    for block, valued in vendors_out:
        vid = block["vendor_id"]
        emails.append((written[vid], "agent", block, valued) if vid in written else (template_email(event_id, block, valued), "template", block, valued))

    # 3. claims: the plan table (engine), vendor asks and offers, then every figure the model wrote
    table: list[Claim] = [*pc.event_claims(event_id)]
    for r in plan["rows"]:
        if r["status"] == "planned":
            table += pc.row_claims(event_id, r)
        elif r.get("deep_option"):
            table += [c for c in pc.row_claims(event_id, {**r, "stock_up": None, "cannibalisation": None}) if c.source_ref.key.endswith("view=deep")]
    for block, valued in vendors_out:
        table += pc.vendor_claims(event_id, block, valued)
    brief_claims = [pc.REGISTRY.figure_claim(f, f"fig:brief:{i}") for i, f in enumerate(brief.figures)]
    email_claims = [[pc.REGISTRY.figure_claim(f, f"fig:email:{e.vendor_id}:{i}") for i, f in enumerate(e.figures)] for e, _, _, _ in emails]
    pool = [*table, *brief_claims, *[c for cl in email_claims for c in cl]]
    if inject:
        pool = inject_fault(pool)
    checked = verify_all(pool).claims
    for c in checked:
        if c.id.startswith("fig:"):  # the numbers the model wrote; the table's engine claims are summarised, not traced one by one
            ctx.emit("claim_checked", STAGE, {"claim": compact(c)})
    ctx.emit("stage_result", STAGE, {"engine_claims": len(table), "verified": sum(1 for c in checked if c.status == "verified"), "total": len(checked)})
    by_id = {c.id: c for c in checked}

    def good(claims: list[Claim]) -> list[bool]:
        return [by_id[c.id].status == "verified" for c in claims]

    brief_text, struck_brief = strike(brief.brief, brief.figures, good(brief_claims))
    headline, struck_head = strike(brief.headline, brief.figures, good(brief_claims))
    queued = []
    for (e, src, block, valued), cl in zip(emails, email_claims):
        ok = good(cl)
        body, struck = strike(e.body, e.figures, ok)
        subject, struck_s = strike(e.subject, e.figures, ok)
        if len(body) < 40:  # the model's text did not survive the verifier: fall back to the engine-only wording
            tpl = template_email(event_id, block, valued)
            tchecked = verify_all([pc.REGISTRY.figure_claim(f, f"fig:email:{block['vendor_id']}:t{i}") for i, f in enumerate(tpl.figures)]).claims
            e, src, cl, body, subject = tpl, "template", tchecked, tpl.body, tpl.subject
            checked.extend(tchecked)
        d = EmailDraft(vendor_id=e.vendor_id, subject=subject or e.subject, body=body, figures=e.figures)
        cl = [by_id.get(c.id, c) for c in cl]
        contact = next(v for v in load_ops().vendors.values() if v.id == e.vendor_id)
        rec = draft_record(
            f"DR-PROMO-{event_id}-{e.vendor_id}", "promo_funding", d, cl, src,
            {"vendor_id": e.vendor_id, "po_id": None, "event_id": event_id, "to": contact.contact_email, "channel": "email", "unclaimed_numbers": [], "struck": [*struck, *struck_s]},
        )
        queued.append(outbox.put(rec))

    summary = fg.counts([*checked, *rclaims])
    # attach the verified/rejected counts of each row's own claims
    rows_out = []
    for r in plan["rows"]:
        mine = [c for c in checked if c.id.startswith(f"{event_id}:{r['vendor_id']}:{r['sku_code']}")]
        rows_out.append({**r, "verification": {"total": len(mine), "verified": sum(1 for c in mine if c.status == "verified"), "rejected": sum(1 for c in mine if c.status == "rejected")}})
    vendors_json = []
    for block, valued in vendors_out:
        vid = block["vendor_id"]
        stated = next((rd.lead_time_days for rd in readings if rd.lead_time_days and replies.get(rd.reply_id, (0, None))[1] and replies[rd.reply_id][1].vendor_id == vid and rby.get(f"promo:{rd.reply_id}:lead") and rby[f"promo:{rd.reply_id}:lead"].status == "verified"), None)
        vendors_json.append({**block, "offer": None if valued is None else {k: v for k, v in valued.items() if k != "assessment"}, "assessment": None if valued is None else valued.get("assessment"), "stated_lead_time_days": stated, "reading_note": notes.get(vid)})
    reading_rows = _reading_rows(readings, rclaims, replies)
    return {
        "event": plan["event"],
        "as_of": plan["as_of"],
        "mode": brief_res.mode,
        "degraded": brief_res.degraded or email_res.degraded or bool(read_res and read_res.degraded),
        "totals": plan["totals"],
        "rows": rows_out,
        "vendors": vendors_json,
        "pos": plan["pos"],
        "headline": headline,
        "brief": brief_text,
        "struck": [*struck_head, *struck_brief],
        "readings": reading_rows,
        "drafts": [outbox.get(q["id"]) for q in queued],
        "claims": [compact(c) for c in [*rclaims, *(c for c in checked if c.id.startswith("fig:") or c.status != "verified")]],  # extractions, the numbers the model wrote, and anything that failed
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "corrected": [c.id for c in rclaims if c.status == "verified" and len(c.attempts) > 1],
        "unresolved": [c.id for c in rclaims if c.origin == "model_extraction" and c.status == "rejected"],
        "trace": fg.drain(ctx),
        "assumptions": _assumptions(),
        "impact_coverage": impact_for("promotions_planner", {"promotion_event_plan": 1}),
    }


def _reading_rows(readings: list[FundingReading], claims: list[Claim], replies: dict[str, tuple[int, pdata.FundingReply]]) -> list[dict[str, Any]]:
    by = {c.id: c for c in claims}
    rows = []
    for rd in readings:
        if rd.reply_id not in replies:
            continue
        reply = replies[rd.reply_id][1]
        terms = []
        for i, t in enumerate(rd.terms):
            cl = [by[c] for c in (f"promo:{reply.id}:t{i}:share", f"promo:{reply.id}:t{i}:threshold", f"promo:{reply.id}:t{i}:banner") if c in by]
            terms.append(
                {
                    **t.model_dump(), "claims": [
                        {"id": c.id, "metric": c.metric, "value": c.value, "status": c.status, "reason": c.reason, "first_value": c.attempts[0].value if c.attempts else None,
                         "corrected": c.status == "verified" and len(c.attempts) > 1}
                        for c in cl
                    ],
                }
            )
        rows.append(
            {"reply_id": reply.id, "vendor_id": reply.vendor_id, "received_at": reply.received_at.isoformat(), "from": reply.sender, "subject": reply.subject, "body": reply.body,
             "stance": rd.stance, "summary": rd.summary, "lead_time_days": rd.lead_time_days, "terms": terms}
        )
    return rows


def _assumptions() -> dict[str, Any]:
    from app import deals, policy

    p = policy.get().promotions
    return {
        "elasticity_default": p.uplift.default_elasticity, "max_uplift": p.uplift.max_multiplier, "pull_forward_pct": p.uplift.pull_forward_pct,
        "max_discount_pct": p.discount.max_pct, "promo_floor_below_regular_pp": p.discount.floor_below_regular_pp, "safety_buffer_pct": p.stock.safety_buffer_pct,
        "baseline_cover_days": p.stock.baseline_cover_days, "funding_target_pct": p.funding.target_share_pct, "funding_max_ask_pct": p.funding.max_ask_share_pct,
        "banner_slot_cost_inr": p.funding.banner_slot_cost_inr, "cannibalised_share_pct": p.cannibalisation.cannibalised_share_pct,
        "deal_evaluator": deals.assumptions(),
    }


def error_note(exc: CategoryOSError) -> str:
    return f"{exc.code}: {exc.problem}"
