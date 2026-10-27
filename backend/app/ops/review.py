"""Module A: weekly vendor performance review and MIS pack.

Python computes every number (app.ops.metrics) and the candidate action list. The agent reads the scorecards, explains
the anomalies, prioritises the actions and drafts vendor emails; every number it writes is a figure whose Claim the
verifier recomputes. The MIS pack is assembled here from deterministic tables plus the agent's commentary. Vendor emails
wait in the outbox for a person to approve (sending is simulated)."""

from typing import Any

from app import llm, policy
from app.ops import base as ob
from app.ops import claims as oc
from app.ops import figures as fg
from app.ops import outbox
from app.ops import prompts as pr
from app.ops import tools as ot
from app.ops.chaser import draft_record
from app.ops.schemas import EmailDraft, EmailsFinal, Figure, ReviewFinal
from app.schemas import Claim
from app.util import fmt_inr, fmt_pct
from app.verify import inject_fault, verify_all

STAGE = fg.STAGE

HEADLINE_METRICS = (
    ("ops_gmv", "gmv", "{brand} GMV for the week is {v}"),
    ("ops_fill_rate_recent", "fill_rate_recent", "{brand} recent fill rate is {v}"),
    ("ops_otif", "otif", "{brand} on-time-in-full is {v}"),
    ("ops_aged_pct", "aged_pct", "{brand} aged stock share is {v}"),
    ("ops_return_rate", "return_rate", "{brand} return rate is {v}"),
    ("ops_rating", "rating", "{brand} rating is {v}"),
)


def impact_for(module: str, units: dict[str, int]) -> dict[str, Any]:
    """What the impact meter needs from this module: the playbook's registration (status, task shares) and the manual
    minutes this run replaced, from impact.recurring_minutes (research estimates, not measured)."""
    imp = policy.get().impact
    mins = imp.recurring_minutes
    baseline = {k: float(getattr(mins, k)) for k in units if hasattr(mins, k)}
    return {
        "module": module,
        "registered": module in imp.modules,
        "status": imp.modules[module].status if module in imp.modules else "unregistered",
        "tasks": [{"task": c.task, "in_scope_pct": c.in_scope_pct} for c in imp.coverage if c.module == module],
        "units": units,
        "baseline_minutes": baseline,
        "manual_minutes_replaced": round(sum(baseline[k] * n for k, n in units.items() if k in baseline), 1),
        "baseline_status": imp.baseline_status,
    }


# ---------- MIS markdown ----------


def _p(v: float | None, dp: int = 0) -> str:
    return "-" if v is None else fmt_pct(v, dp)


def mis_markdown(b: ob.Base, final: ReviewFinal | None, actions: list[dict[str, Any]]) -> str:
    cat = b.category
    lines = [f"# Category MIS: {cat['week_start']} to {cat['week_end']}", ""]
    if final:
        lines += [f"**{final.headline}**", ""]
    lines += [
        "## Category summary",
        "",
        "| Measure | This week | Last week / reference |",
        "| --- | --- | --- |",
        f"| GMV | {fmt_inr(cat['gmv'])} | {fmt_inr(cat['gmv_prev'])} ({_p(cat['gmv_growth_wow'], 1)} week on week) |",
        f"| Units | {cat['units']:,} | |",
        f"| Gross margin | {_p(cat['margin_pct'], 1)} | |",
        f"| Fill rate, recent weeks | {_p(cat['fill_rate_recent'])} | {_p(cat['fill_rate'])} over 13 weeks |",
        f"| On-time-in-full | {_p(cat['otif'])} | target {b.ops.scorecard.otif_target_pct:g}% |",
        "",
        "## What to do this week",
        "",
    ]
    for a in actions:
        who = b.data.vendors[a["vendor_id"]].brand
        why = f" {a['rationale']}" if a.get("rationale") else ""
        lines.append(f"- **#{a['rank']}** {a['title']} ({who}).{why}")
    lines += [
        "",
        "## Vendor scorecard",
        "",
        "| Vendor | GMV | Week on week | Fill rate (recent) | OTIF | Lowest cover | Aged stock | Returns | Rating |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in b.cards.values():
        cover = "-" if c["min_cover_days"] is None else f"{round(c['min_cover_days'])} days"
        lines.append(
            f"| {c['brand']} | {fmt_inr(c['gmv'])} | {_p(c['gmv_growth_wow'], 1)} | {_p(c['fill_rate_recent'])} | {_p(c['otif'])} | {cover} | {_p(c['aged_pct'])} | {_p(c['return_rate'], 1)} | {c['rating']:.2f} |"
        )
    if final:
        lines += ["", "## Commentary", ""]
        for para in final.narrative.split("\n\n"):
            if para.strip():
                lines += [para.strip(), ""]
        lines.pop()
    lines += ["", "## Anomalies", "", "| Vendor | Item | Issue | Why |", "| --- | --- | --- | --- |"]
    notes = {n.anomaly_id: n.explanation for n in final.anomaly_notes} if final else {}
    for a in b.anomalies:
        item = b.data.skus[a["sku_code"]].name if a["sku_code"] else "Vendor"
        why = notes.get(a["id"], a["reason"])
        lines.append(f"| {b.data.vendors[a['vendor_id']].brand} | {item} | {a['type'].replace('_', ' ')} | {why.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


# ---------- emails ----------


def template_email(b: ob.Base, vendor_id: str) -> EmailDraft:
    v = b.data.vendors[vendor_id]
    mine = [a for a in b.anomalies if a["vendor_id"] == vendor_id and a["type"] in ob.VENDOR_FACING]
    figs = [Figure(metric=a["metric"], key=a["key"], value=a["value"], shown="", text=a["reason"]) for a in mine]
    lines = [f"Hi {v.contact_name},", "", "Our weekly review of your range showed these points:", ""] + [f"- {a['reason']}" for a in mine]
    lines += ["", "Could you share your plan and a date for each by Friday?", "", "Thanks"]
    return EmailDraft(vendor_id=vendor_id, subject=f"Weekly review: {v.brand}", body="\n".join(lines), figures=figs)


def _figure_claims(prefix: str, figs: list[Figure]) -> list[Claim]:
    return [fg.figure_claim(f, f"{prefix}:{i}") for i, f in enumerate(figs)]


def _inject(claims: list[Claim]) -> list[Claim]:
    return inject_fault(claims)


async def generate(inject: bool = False) -> dict[str, Any]:
    b = ob.base()
    ops = b.ops
    cat = b.category
    ctx = fg.new_ctx("review", b.data.as_of)
    ctx.emit("stage_started", STAGE, {"task": "weekly_review", "week": f"{cat['week_start']} to {cat['week_end']}"})
    msgs = pr.messages(pr.REVIEW_SYSTEM, pr.REVIEW_USER, week_start=cat["week_start"], week_end=cat["week_end"])
    res = await llm.run_tools(STAGE, "review_mis", msgs, ot.select(ot.REVIEW_TOOLS), max_steps=6, schema=ReviewFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, "review_mis", res)
    final = res.parsed
    assert isinstance(final, ReviewFinal)

    flagged = ob.flagged_vendors(b)
    emsgs = pr.messages(pr.EMAILS_SYSTEM, pr.EMAILS_USER, week_start=cat["week_start"], week_end=cat["week_end"], vendors=", ".join(flagged))
    eres = await llm.run_tools(STAGE, "review_emails", emsgs, ot.select(ot.EMAIL_TOOLS), max_steps=8, schema=EmailsFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, "review_emails", eres)
    efinal = eres.parsed
    assert isinstance(efinal, EmailsFinal)
    written = {e.vendor_id: e for e in efinal.emails if e.vendor_id in flagged}
    emails: list[tuple[EmailDraft, str]] = [(written[v], "agent") if v in written else (template_email(b, v), "template") for v in flagged]

    # claims: headline scorecard numbers (engine), then every figure the agent wrote
    headline: list[Claim] = []
    for vid, card in b.cards.items():
        for metric, field, tmpl in HEADLINE_METRICS:
            if card.get(field) is not None:
                headline.append(oc.engine_claim(metric, vid, tmpl.format(brand=card["brand"], v=_headline_value(metric, card))))
    headline.append(oc.engine_claim("ops_cat_gmv", "category", f"Category GMV for the week is {fmt_inr(cat['gmv'])}"))
    headline.append(oc.engine_claim("ops_cat_fill_rate_recent", "category", f"Category recent fill rate is {_p(cat['fill_rate_recent'])}"))

    text_figs: list[Figure] = [*final.figures, *[f for n in final.anomaly_notes for f in n.figures], *[f for p in final.priority for f in p.figures]]
    agent = _figure_claims("fig:review", text_figs)
    email_claims = [_figure_claims(f"fig:email:{e.vendor_id}", e.figures) for e, _ in emails]
    pool = [*headline, *agent, *[c for cl in email_claims for c in cl]]
    if inject:
        pool = _inject(pool)
    checked = verify_all(pool).claims
    for c in checked:
        ctx.emit("claim_checked", STAGE, {"claim": c.model_dump(mode="json")})
    by_id = {c.id: c for c in checked}

    unclaimed = fg.check_text([final.headline, final.narrative], text_figs)
    unclaimed += [x for n in final.anomaly_notes for x in fg.check_text([n.explanation], text_figs)]
    unclaimed += [x for p in final.priority for x in fg.check_text([p.rationale], text_figs)]
    email_unclaimed = {e.vendor_id: fg.check_text([e.subject, e.body], e.figures) for e, src in emails if src == "agent"}

    # action ranking: the agent's order where it is valid, otherwise the deterministic score
    known = {a["id"]: a for a in b.actions}
    ordered: list[dict[str, Any]] = []
    llm_rank = {}
    for i, note in enumerate(final.priority, start=1):
        if note.action_id in known and note.action_id not in llm_rank:
            llm_rank[note.action_id] = i
            ordered.append({**known[note.action_id], "rationale": note.rationale, "llm_rank": i})
    ordered += [{**a, "rationale": None, "llm_rank": None} for a in b.actions if a["id"] not in llm_rank]
    actions = [{**a, "rank": i} for i, a in enumerate(ordered[: ops.actions.max_actions], start=1)]

    anomalies = [{**a, "explanation": next((n.explanation for n in final.anomaly_notes if n.anomaly_id == a["id"]), None)} for a in b.anomalies]
    queued = []
    for (e, src), cl in zip(emails, email_claims):
        cl = [by_id.get(c.id, c) for c in cl]
        rec = draft_record(
            f"DR-REVIEW-{e.vendor_id}", "vendor_review", e, cl, src,
            {"vendor_id": e.vendor_id, "po_id": None, "to": b.data.vendors[e.vendor_id].contact_email, "channel": "email", "unclaimed_numbers": email_unclaimed.get(e.vendor_id, [])},
        )
        queued.append(outbox.put(rec))

    summary = fg.counts(checked)
    markdown = mis_markdown(b, final, actions)
    return {
        "as_of": b.data.as_of.isoformat(),
        "week_start": cat["week_start"],
        "week_end": cat["week_end"],
        "mode": res.mode,
        "degraded": res.degraded or eres.degraded,
        "category": cat,
        "vendors": [{k: v for k, v in c.items() if k != "skus"} for c in b.cards.values()],
        "anomalies": anomalies,
        "actions": actions,
        "headline": final.headline,
        "narrative": final.narrative,
        "mis_markdown": markdown,
        "flagged_vendors": flagged,
        "drafts": [outbox.get(q["id"]) for q in queued],
        "claims": [c.model_dump(mode="json") for c in checked],
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "unclaimed_numbers": unclaimed,
        "trace": fg.drain(ctx),
        "thresholds": {
            "fill_rate_floor_pct": ops.scorecard.fill_rate_floor_pct,
            "otif_target_pct": ops.scorecard.otif_target_pct,
            "stock_cover_alert_days": ops.scorecard.stock_cover_alert_days,
            "growth_z_threshold": ops.anomaly.growth_z_threshold,
        },
        "impact_coverage": impact_for("weekly_review_mis", {"weekly_review_pack": 1, "vendor_scorecard": len(b.cards)}),
    }


def _headline_value(metric: str, card: dict[str, Any]) -> str:
    if metric == "ops_gmv":
        return fmt_inr(card["gmv"])
    if metric == "ops_rating":
        return f"{card['rating']:.2f}"
    key = {"ops_fill_rate_recent": "fill_rate_recent", "ops_otif": "otif", "ops_aged_pct": "aged_pct", "ops_return_rate": "return_rate"}[metric]
    return fmt_pct(card[key], 1)
