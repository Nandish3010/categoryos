"""The inventory health review around its engine. Python (``engine``) decides what to do with every SKU; the model writes the weekly
summary, a plain-English note per action and the vendor messages from the engine's numbers only. Every number in the tables is an engine
claim; every number the model writes is a figure whose claim the verifier recomputes, and a sentence with a figure that fails is struck.
Vendor messages wait in the outbox for a person (sending is simulated)."""

from datetime import date
from typing import Any

from app import llm, policy
from app.errors import CategoryOSError
from app.ops import figures as fg
from app.ops import outbox
from app.ops.chaser import draft_record
from app.ops.inventory_health import claims as ic
from app.ops.inventory_health import engine
from app.ops.inventory_health import outbox as ih_outbox
from app.ops.inventory_health import prompts as pr
from app.ops.inventory_health import tools as pt
from app.ops.inventory_health.schemas import BriefFinal
from app.ops.review import impact_for
from app.ops.runclaims import compact, fmt_shown, strike
from app.ops.schemas import EmailDraft, EmailsFinal, Figure
from app.schemas import Claim
from app.verify import inject_fault, verify_all

STAGE = fg.STAGE
VENDOR_KINDS = ih_outbox.VENDOR_KINDS
KIND = "inventory_health"


def show(unit: str, value: float) -> str:
    """A claim value as it is written in prose. Day counts with a decimal read as 6.0 (one place); everything else as fmt_shown."""
    return f"{value:.1f}" if unit == "ratio" else fmt_shown(unit, value)


def vendors_to_message(actions: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for a in actions:
        if a["recommendation"] in VENDOR_KINDS and a["vendor_id"] not in seen:
            seen.append(a["vendor_id"])
    return seen


def figure_of(c: Claim) -> Figure:
    return Figure(metric=c.metric, key=c.source_ref.key, value=c.value, shown=show(c.unit, c.value), text=c.text)


def template_email(vendor_id: str, actions: list[dict[str, Any]]) -> EmailDraft:
    """The deterministic message when the model wrote none for a vendor: built only from the engine's numbers."""
    from app.ops.data import load

    v = load().vendors[vendor_id]
    mine = [a for a in actions if a["vendor_id"] == vendor_id and a["recommendation"] in VENDOR_KINDS]
    figs: list[Figure] = []
    lines = [f"Hi {v.contact_name.split()[0]},", ""]
    for a in mine:
        by = {c.metric: c for c in ic.action_claims(a)}

        def take(*metrics: str, by: dict[str, Claim] = by) -> dict[str, str]:
            figs.extend(figure_of(by[m]) for m in metrics)
            return {m: show(by[m].unit, by[m].value) for m in metrics}

        if a["recommendation"] == "expedite_po":
            n = take("ih_run_out_day", "ih_short_days", "ih_inbound_units")
            lines.append(
                f"{a['name']} runs out in {n['ih_run_out_day']} days, and its open PO ({n['ih_inbound_units']} units) is past its promised date, so we expect about {n['ih_short_days']} days out of stock. "
                "Please confirm dispatch and ship it by Friday."
            )
        elif a["recommendation"] == "pause_po":
            n = take("ih_pause_units", "ih_pause_cover_without_days", "ih_moq_units")
            lines.append(
                f"Please hold PO {a['pause']['po_id']} for {a['name']} ({n['ih_pause_units']} units). We already hold {n['ih_pause_cover_without_days']} days of cover without it, and the minimum order quantity of "
                f"{n['ih_moq_units']} made the PO larger than we need. We will take it in the next cycle."
            )
        else:
            n = take("ih_clear_units", "ih_rtv_credit_inr", "ih_rtv_days_left")
            lines.append(
                f"Under our sell-or-return terms we would like to return {n['ih_clear_units']} units of {a['name']} for {n['ih_rtv_credit_inr']} of credit. The window closes in {n['ih_rtv_days_left']} days; "
                "please send a return authorisation."
            )
    lines += ["", "Please let us know by Friday.", "", "Thanks"]
    return EmailDraft(vendor_id=vendor_id, subject=f"Inventory review: {v.brand}", body="\n".join(lines), figures=figs)


def _stock_block(res: dict[str, Any]) -> dict[str, Any]:
    keys = ("on_hand", "daily_demand", "cover_days", "inbound_units", "cover_inbound_days", "run_out_day", "short_days", "lead_time_days", "moq_units", "band", "landings", "stock_value_inr", "days_since_sale", "oldest_age_days", "aged_units", "terms", "legacy", "band_state")
    return {k: res[k] for k in keys}


def _as_of(r: dict[str, Any]) -> date:
    return date.fromisoformat(r["as_of"])


def _vendor_row(vendor_id: str) -> dict[str, str]:
    from app.ops.data import load

    v = load().vendors.get(vendor_id)
    if v is None:
        raise CategoryOSError(f"unknown vendor {vendor_id!r}")
    return {"brand": v.brand, "contact_email": v.contact_email, "contact_name": v.contact_name}


async def generate(inject: bool = False) -> dict[str, Any]:
    r = engine.analyse()
    actions: list[dict[str, Any]] = r["actions"]
    w = policy.get().inventory_health
    ctx = fg.new_ctx("inventory", _as_of(r))
    ctx.emit("stage_started", STAGE, {"task": "inventory_health", "as_of": r["as_of"], "skus": r["counts"]["skus"]})

    brief_res = await llm.run_tools(STAGE, "ih_brief", pr.messages(pr.BRIEF_SYSTEM, pr.BRIEF_USER, as_of=r["as_of"]), pt.select(pt.BRIEF_TOOLS), max_steps=3, schema=BriefFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, "ih_brief", brief_res)
    brief = brief_res.parsed
    assert isinstance(brief, BriefFinal)

    wanted = vendors_to_message(actions)
    email_res = await llm.run_tools(
        STAGE, "ih_vendor_emails", pr.messages(pr.EMAIL_SYSTEM, pr.EMAIL_USER, as_of=r["as_of"], vendors=", ".join(wanted) or "none"),
        pt.select(pt.EMAIL_TOOLS), max_steps=6, schema=EmailsFinal, on_step=ctx.step_emitter(STAGE),
    )
    fg.emit_model_call(ctx, "ih_vendor_emails", email_res)
    efinal = email_res.parsed
    assert isinstance(efinal, EmailsFinal)
    written = {e.vendor_id: e for e in efinal.emails if e.vendor_id in wanted}
    emails: list[tuple[EmailDraft, str]] = [(written[v], "agent") if v in written else (template_email(v, actions), "template") for v in wanted]

    # claims: every number in the tables (engine), then every figure the model wrote
    action_ids = {a["id"] for a in actions}
    notes = [n for n in brief.notes if n.action_id in action_ids]
    table: list[Claim] = [c for a in actions for c in ic.action_claims(a)] + [c for v in r["vendors"] for c in ic.vendor_claims(v)]
    brief_claims = [ic.REGISTRY.figure_claim(f, f"fig:brief:{i}") for i, f in enumerate(brief.figures)]
    note_claims = [[ic.REGISTRY.figure_claim(f, f"fig:note:{n.action_id}:{i}") for i, f in enumerate(n.figures)] for n in notes]
    email_claims = [[ic.REGISTRY.figure_claim(f, f"fig:email:{e.vendor_id}:{i}") for i, f in enumerate(e.figures)] for e, _ in emails]
    pool = [*table, *brief_claims, *[c for cl in note_claims for c in cl], *[c for cl in email_claims for c in cl]]
    if inject:
        pool = inject_fault(pool)
    checked = verify_all(pool).claims
    for c in checked:
        if c.id.startswith("fig:"):  # the numbers the model wrote; the tables' engine claims are summarised, not traced one by one
            ctx.emit("claim_checked", STAGE, {"claim": compact(c)})
    ctx.emit("stage_result", STAGE, {"engine_claims": len(table), "verified": sum(1 for c in checked if c.status == "verified"), "total": len(checked)})
    by_id = {c.id: c for c in checked}

    def good(claims: list[Claim]) -> list[bool]:
        return [by_id[c.id].status == "verified" for c in claims]

    narrative, struck_brief = strike(brief.narrative, brief.figures, good(brief_claims))
    headline, struck_head = strike(brief.headline, brief.figures, good(brief_claims))
    note_by_action: dict[str, str] = {}
    struck_notes: list[str] = []
    for n, cl in zip(notes, note_claims):
        text, struck = strike(n.rationale, n.figures, good(cl))
        struck_notes += struck
        if text:
            note_by_action[n.action_id] = text

    queued = []
    struck_by_vendor: dict[str, list[str]] = {}
    for (e, src), cl in zip(emails, email_claims):
        ok = good(cl)
        body, struck = strike(e.body, e.figures, ok)
        subject, struck_s = strike(e.subject, e.figures, ok)
        struck_by_vendor[e.vendor_id] = [*struck, *struck_s]
        if len(body) < 40:  # the model's text did not survive the verifier: fall back to the engine-only wording
            tpl = template_email(e.vendor_id, actions)
            tcl = [ic.REGISTRY.figure_claim(f, f"fig:email:{e.vendor_id}:t{i}") for i, f in enumerate(tpl.figures)]
            tchecked = verify_all(tcl).claims
            e, src, cl = tpl, "template", tchecked
            body, subject = tpl.body, tpl.subject
            checked.extend(tchecked)
        d = EmailDraft(vendor_id=e.vendor_id, subject=subject or e.subject, body=body, figures=e.figures)
        cl = [by_id.get(c.id, c) for c in cl]
        v = _vendor_row(e.vendor_id)
        rec = draft_record(
            ih_outbox.draft_id(e.vendor_id), KIND, d, cl, src,
            {"vendor_id": e.vendor_id, "po_id": None, "to": v["contact_email"], "channel": "email", "unclaimed_numbers": [], "struck": struck_by_vendor[e.vendor_id]},
        )
        queued.append(outbox.put(rec))

    summary = fg.counts(checked)
    out_actions = []
    for a in actions:
        mine = [compact(c) for c in checked if c.id.startswith(f"{a['id']}:")]
        out_actions.append({**a, "claims": mine, "stock": _stock_block(r["skus"][a["sku_code"]]), "note": note_by_action.get(a["id"]), "email_id": ih_outbox.draft_id(a["vendor_id"]) if a["recommendation"] in VENDOR_KINDS else None})
    vendors = [{**v, "claims": [compact(c) for c in checked if c.id.startswith(f"ihv:{v['vendor_id']}:")]} for v in r["vendors"]]
    return {
        "as_of": r["as_of"],
        "mode": brief_res.mode,
        "degraded": brief_res.degraded or email_res.degraded,
        "counts": r["counts"],
        "headline": headline,
        "narrative": narrative,
        "struck": [*struck_head, *struck_brief, *struck_notes],
        "actions": out_actions,
        "vendors": vendors,
        "skus": r["rows"],
        "drafts": [outbox.get(q["id"]) for q in queued],
        "claims": [compact(c) for c in checked if c.id.startswith("fig:") or c.status != "verified"],  # the numbers the model wrote, and anything that failed; each action carries its own
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "trace": fg.drain(ctx),
        "thresholds": {
            "cover_min_days": w.cover.min_days, "cover_target_days": w.cover.target_days, "cover_max_days": w.cover.max_days,
            "aged_days": w.ageing.aged_days, "dead_no_sale_days": w.ageing.dead_no_sale_days, "critical_days": w.stock_out.critical_days,
            "safety_days": w.stock_out.safety_days, "review_days": w.stock_out.review_days, "overdue_assumed_days": w.stock_out.overdue_assumed_days,
            "overbuy_ratio": w.moq.overbuy_ratio, "rtv_urgent_window_days": w.rtv.urgent_window_days, "max_clear_days": w.liquidate.max_clear_days,
            "forecast_window_days": w.forecast.window_days,
        },
        "impact_coverage": impact_for("inventory_health_module", {"inventory_ageing_review": 1}),
    }
