"""The price monitor around its engine. Python (``engine``) decides what to do with every flagged SKU; the model writes the daily summary
and the vendor messages for breaches and funding asks from the engine's numbers only. Every number in the table is an engine claim; every
number the model writes is a figure whose claim the verifier recomputes, and a sentence with a figure that fails is struck.
Vendor messages wait in the outbox for a person (sending is simulated)."""

from typing import Any

from app import llm, policy
from app.errors import CategoryOSError
from app.ops import figures as fg
from app.ops import outbox
from app.ops.chaser import draft_record
from app.ops.pricewatch import claims as pc
from app.ops.pricewatch import engine
from app.ops.pricewatch import prompts as pr
from app.ops.pricewatch import tools as pt
from app.ops.pricewatch.schemas import BriefFinal
from app.ops.review import impact_for
from app.ops.runclaims import compact, fmt_shown, strike
from app.ops.schemas import EmailDraft, EmailsFinal, Figure
from app.schemas import Claim
from app.verify import inject_fault, verify_all

STAGE = fg.STAGE
VENDOR_KINDS = ("flag_breach", "ask_vendor_funding")


def vendors_to_message(actions: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for a in actions:
        if a["recommendation"] in VENDOR_KINDS and a["vendor_id"] not in seen:
            seen.append(a["vendor_id"])
    return seen


def _figures_for(claims: list[Claim]) -> list[Figure]:
    return [Figure(metric=c.metric, key=c.source_ref.key, value=c.value, shown=fmt_shown(c.unit, c.value), text=c.text) for c in claims]


def template_email(vendor_id: str, actions: list[dict[str, Any]]) -> EmailDraft:
    """The deterministic message when the model wrote none for a vendor: built only from the engine's numbers."""
    from app.ops.data import load

    v = load().vendors[vendor_id]
    mine = [a for a in actions if a["vendor_id"] == vendor_id and a["recommendation"] in VENDOR_KINDS]
    figs: list[Figure] = []
    lines = [f"Hi {v.contact_name.split()[0]},", ""]
    for a in mine:
        by = {c.metric: c for c in pc.action_claims(a)}
        if a["recommendation"] == "flag_breach":
            take = [by[m] for m in ("pw_vendor_price", "pw_parity_below_pct", "pw_parity_days") if m in by]
            figs += _figures_for(take)
            lines.append(
                f"On {a['vendor']['marketplace']}, {a['name']} is listed at {fmt_shown('inr', by['pw_vendor_price'].value)}, "
                f"{fmt_shown('pct', by['pw_parity_below_pct'].value)} under our price, for {fmt_shown('units', by['pw_parity_days'].value)} days. "
                "That breaks price parity. Please restore it this Friday; we will not follow the lower price."
            )
        else:
            take = [by[m] for m in ("pw_below_pct", "pw_streak_days", "pw_protection_ask_unit_inr") if m in by]
            figs += _figures_for(take)
            lines.append(
                f"A competitor has been {fmt_shown('pct', by['pw_below_pct'].value)} under our price on {a['competitor']['marketplace']} for "
                f"{fmt_shown('units', by['pw_streak_days'].value)} days on {a['name']}. Matching would take our margin under the floor, so please share price "
                f"protection of {fmt_shown('inr', by['pw_protection_ask_unit_inr'].value)} per unit."
            )
    lines += ["", "Please let us know by Friday.", "", "Thanks"]
    return EmailDraft(vendor_id=vendor_id, subject=f"Price check: {v.brand}", body="\n".join(lines), figures=figs)


def _series(res: dict[str, Any]) -> dict[str, Any]:
    mps = res["marketplaces"]
    first = next(iter(mps.values()), None)
    return {
        "dates": first["dates"] if first else [],
        "our_price": res["our_price"],
        "competitors": {mp: row["prices"] for mp, row in mps.items()},
        "vendor": ({"marketplace": res["vendor"]["marketplace"], "prices": res["vendor"]["prices"], "dates": res["vendor"]["dates"], "map_price": res["vendor"]["map_price"]} if res["vendor"] else None),
    }


def sku_rows(r: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for code, res in r["skus"].items():
        worst = min(res["marketplaces"].values(), key=lambda m: m["latest"], default=None)
        states = {m["state"] for m in res["marketplaces"].values()}
        state = "sustained" if "sustained" in states else "blip" if "blip" in states else "trend" if "trend" in states else "ok"
        out.append(
            {
                "sku_code": code, "vendor_id": res["vendor_id"], "brand": res["brand"], "name": res["name"], "our_price": res["our_price"],
                "lowest_competitor": worst["latest"] if worst else None, "lowest_marketplace": worst["marketplace"] if worst else None,
                "gap_pct": worst["gap_pct"] if worst else None, "state": state, "vendor_breach": bool(res["vendor"] and res["vendor"]["breach"]),
            }
        )
    return out


async def generate(inject: bool = False) -> dict[str, Any]:
    r = engine.analyse()
    actions: list[dict[str, Any]] = r["actions"]
    w = policy.get().price_watch
    ctx = fg.new_ctx("pricewatch", _as_of(r))
    ctx.emit("stage_started", STAGE, {"task": "price_watch", "as_of": r["as_of"], "snapshots": r["counts"]["snapshots"]})

    brief_res = await llm.run_tools(STAGE, "pw_brief", pr.messages(pr.BRIEF_SYSTEM, pr.BRIEF_USER, as_of=r["as_of"]), pt.select(pt.BRIEF_TOOLS), max_steps=3, schema=BriefFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, "pw_brief", brief_res)
    brief = brief_res.parsed
    assert isinstance(brief, BriefFinal)

    wanted = vendors_to_message(actions)
    email_res = await llm.run_tools(
        STAGE, "pw_vendor_emails", pr.messages(pr.EMAIL_SYSTEM, pr.EMAIL_USER, as_of=r["as_of"], vendors=", ".join(wanted) or "none"),
        pt.select(pt.EMAIL_TOOLS), max_steps=6, schema=EmailsFinal, on_step=ctx.step_emitter(STAGE),
    )
    fg.emit_model_call(ctx, "pw_vendor_emails", email_res)
    efinal = email_res.parsed
    assert isinstance(efinal, EmailsFinal)
    written = {e.vendor_id: e for e in efinal.emails if e.vendor_id in wanted}
    emails: list[tuple[EmailDraft, str]] = [(written[v], "agent") if v in written else (template_email(v, actions), "template") for v in wanted]

    # claims: every number in the action table (engine), then every figure the model wrote
    table: list[Claim] = [c for a in actions for c in pc.action_claims(a)]
    brief_claims = [pc.REGISTRY.figure_claim(f, f"fig:brief:{i}") for i, f in enumerate(brief.figures)]
    email_claims = [[pc.REGISTRY.figure_claim(f, f"fig:email:{e.vendor_id}:{i}") for i, f in enumerate(e.figures)] for e, _ in emails]
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

    narrative, struck_brief = strike(brief.narrative, brief.figures, good(brief_claims))
    headline, struck_head = strike(brief.headline, brief.figures, good(brief_claims))
    queued = []
    struck_by_vendor: dict[str, list[str]] = {}
    for (e, src), cl in zip(emails, email_claims):
        ok = good(cl)
        body, struck = strike(e.body, e.figures, ok)
        subject, struck_s = strike(e.subject, e.figures, ok)
        struck_by_vendor[e.vendor_id] = [*struck, *struck_s]
        if len(body) < 40:  # the model's text did not survive the verifier: fall back to the engine-only wording
            tpl = template_email(e.vendor_id, actions)
            tcl = [pc.REGISTRY.figure_claim(f, f"fig:email:{e.vendor_id}:t{i}") for i, f in enumerate(tpl.figures)]
            tchecked = verify_all(tcl).claims
            e, src, cl = tpl, "template", tchecked
            body, subject = tpl.body, tpl.subject
            checked.extend(tchecked)
        d = EmailDraft(vendor_id=e.vendor_id, subject=subject or e.subject, body=body, figures=e.figures)
        cl = [by_id.get(c.id, c) for c in cl]
        v = _vendor_row(e.vendor_id)
        rec = draft_record(
            f"DR-PW-{e.vendor_id}", "price_watch", d, cl, src,
            {"vendor_id": e.vendor_id, "po_id": None, "to": v["contact_email"], "channel": "email", "unclaimed_numbers": [], "struck": struck_by_vendor[e.vendor_id]},
        )
        queued.append(outbox.put(rec))

    summary = fg.counts(checked)
    out_actions = []
    for a in actions:
        mine = [compact(c) for c in checked if c.id.startswith(f"{a['id']}:")]
        res = r["skus"][a["sku_code"]]
        out_actions.append({**a, "claims": mine, "series": _series(res), "email_id": f"DR-PW-{a['vendor_id']}" if a["recommendation"] in VENDOR_KINDS else None})
    return {
        "as_of": r["as_of"],
        "window_days": r["window_days"],
        "marketplaces": r["marketplaces"],
        "mode": brief_res.mode,
        "degraded": brief_res.degraded or email_res.degraded,
        "counts": r["counts"],
        "headline": headline,
        "narrative": narrative,
        "struck": [*struck_head, *struck_brief],
        "actions": out_actions,
        "skus": sku_rows(r),
        "drafts": [outbox.get(q["id"]) for q in queued],
        "claims": [compact(c) for c in checked if c.id.startswith("fig:") or c.status != "verified"],  # the numbers the model wrote, and anything that failed; each action carries its own
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "trace": fg.drain(ctx),
        "thresholds": {
            "undercut_threshold_pct": w.undercut.threshold_pct,
            "min_sustained_days": w.undercut.min_sustained_days,
            "parity_tolerance_pct": w.parity.tolerance_pct,
            "parity_min_days": w.parity.min_days,
            "max_cut_pct": w.match.max_cut_pct,
            "horizon_days": w.match.horizon_days,
            "comparison_share_pct": w.match.comparison_share_pct,
        },
        "impact_coverage": impact_for("competitor_monitor", {"competitor_price_sweep": 1}),
    }


def _as_of(r: dict[str, Any]):
    from datetime import date

    return date.fromisoformat(r["as_of"])


def _vendor_row(vendor_id: str) -> dict[str, str]:
    from app.ops.data import load

    v = load().vendors.get(vendor_id)
    if v is None:
        raise CategoryOSError(f"unknown vendor {vendor_id!r}")
    return {"brand": v.brand, "contact_email": v.contact_email, "contact_name": v.contact_name}
