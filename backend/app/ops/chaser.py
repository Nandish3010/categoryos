"""Module B: PO follow-up and fill-rate chaser.

Python tracks every open PO (status, days overdue, stock-out risk, escalation rung). The agent reads the vendors' messy
email replies; every date and quantity it extracts is a Claim checked against the reply text, and a rejected one goes back
to the agent through the self-correction loop. Only VERIFIED commitments reach the tracker. The agent then drafts the
follow-ups, which wait in the outbox for a person to approve (sending is simulated)."""

import math
from datetime import date, timedelta
from typing import Any

from app import llm
from app.ops import base as ob
from app.ops import claims as oc
from app.ops import figures as fg
from app.ops import outbox, pos
from app.ops import prompts as pr
from app.ops import tools as ot
from app.ops.data import Reply, file_sha256
from app.ops.schemas import (
    Commitment,
    Figure,
    PoDraft,
    PoDraftsFinal,
    PoRepliesFinal,
    ReplyReading,
)
from app.parsing import PARSER_VERSION
from app.schemas import Claim, ClaimFix, Evidence, SourceRef
from app.selfcorrect import self_correct
from app.verify import verify_all

STAGE = fg.STAGE
STANCE_VAGUE = ("vague", "excuse_only")


def _reply_index(replies: list[Reply]) -> dict[str, tuple[int, Reply]]:
    return {r.id: (i + 1, r) for i, r in enumerate(replies)}


def commitment_claim(reply: Reply, position: int, commitment: Commitment, i: int, sha: str) -> Claim:
    received = reply.received_at.date()
    if commitment.kind == "eta_date":
        try:
            days = float((date.fromisoformat(commitment.eta_date or "") - received).days)
        except ValueError:
            days = -9999.0  # an unreadable date: the verifier rejects it with the date the quote resolves to
        metric, unit, value = "reply_eta_days", "units", days
        shown = commitment.eta_date or "no date"
        text = f"{reply.vendor_id} will deliver by {shown} (reply {reply.id})"
    else:
        metric, unit, value = "reply_qty", "qty", float(commitment.qty or 0)
        text = f"{reply.vendor_id} states a quantity of {value:g} units (reply {reply.id})"
    return Claim(
        id=f"reply:{reply.id}:{i}",
        text=text,
        value=value,
        metric=metric,
        unit=unit,  # type: ignore[arg-type]
        source_ref=SourceRef(file=oc.REPLIES, key=reply.id, column="body"),
        evidence=Evidence(row=position, header="body", raw_value=commitment.quote, normalized_value=value, parser_version=PARSER_VERSION, sha256=sha),
        origin="model_extraction",
    )


def reading_claims(readings: list[ReplyReading], replies: list[Reply]) -> tuple[list[Claim], list[tuple[ReplyReading, int]]]:
    """(claims, owners): owners[k] is (reading, commitment index) for claims[k]."""
    index = _reply_index(replies)
    sha = file_sha256(oc.REPLIES)
    claims: list[Claim] = []
    owners: list[tuple[ReplyReading, int]] = []
    for reading in readings:
        if reading.reply_id not in index:
            continue
        position, reply = index[reading.reply_id]
        for i, c in enumerate(reading.commitments):
            claims.append(commitment_claim(reply, position, c, i, sha))
            owners.append((reading, i))
    return claims, owners


def signals_from(readings: list[ReplyReading], claims: list[Claim], replies: list[Reply]) -> dict[str, pos.PoSignal]:
    """The tracker's view of the replies: only verified dates count; a latest reply with no dated commitment is vague."""
    index = _reply_index(replies)
    by_id = {c.id: c for c in claims}
    out: dict[str, pos.PoSignal] = {}
    ordered = sorted((r for r in readings if r.reply_id in index), key=lambda r: index[r.reply_id][1].received_at)
    for reading in ordered:
        reply = index[reading.reply_id][1]
        sig = out.setdefault(reply.po_id, pos.PoSignal())
        sig.reply_ids.append(reply.id)
        etas = []
        for i, c in enumerate(reading.commitments):
            claim = by_id.get(f"reply:{reply.id}:{i}")
            if c.kind == "eta_date" and claim is not None and claim.status == "verified":
                etas.append(reply.received_at.date() + timedelta(days=int(claim.value)))
        if etas:
            sig.eta, sig.vague = max(etas), False
        elif reading.stance in STANCE_VAGUE:
            sig.vague = True
    return out


def suggested_reorder(row: dict[str, Any], lead_days: int, cover_days: int) -> int:
    """Units to order so that cover lasts lead time plus the alert window, net of stock and what is still to arrive."""
    need = row["daily_rate"] * (lead_days + cover_days) - row["on_hand"] - row["open_qty"]
    return max(0, int(math.ceil(need / 10.0) * 10))


def template_draft(b: ob.Base, row: dict[str, Any]) -> PoDraft:
    """Deterministic fallback when the agent wrote no draft for a PO that needs a chase."""
    rung = row["rung"]
    contact = b.data.vendors[row["vendor_id"]].contact_name
    channel = "whatsapp" if "whatsapp" in rung["channel"] else "email"
    overdue = row["days_overdue"]
    figs = [Figure(metric="ops_days_overdue", key=row["po_id"], value=overdue, shown=str(abs(overdue)), text=f"{row['po_id']} is {overdue} days from its promised date")]
    when = f"{overdue} days overdue" if overdue > 0 else f"due in {abs(overdue)} days"
    body = f"Hi {contact}, {row['po_id']} is {abs(overdue)} days {'overdue' if overdue > 0 else 'from its promised date'} (promised {row['promised_date']}). Please confirm a dispatch date and share the tracking details today."
    if row["vague_reply"]:
        body = body.replace("confirm a dispatch date", "give a specific dispatch date (not 'shortly')")
    return PoDraft(po_id=row["po_id"], channel=channel, subject=f"{rung['name']}: {row['po_id']} {when}", body=body, figures=figs)  # type: ignore[arg-type]


async def read_replies(ctx: Any, b: ob.Base) -> tuple[list[ReplyReading], list[Claim], list[Claim], Any]:
    """Run the reading agent, verify its extractions, let it correct rejected ones. Returns (readings, claims_before, claims, result)."""
    msgs = pr.messages(pr.REPLIES_SYSTEM, pr.REPLIES_USER, as_of=b.data.as_of.isoformat())
    res = await llm.run_tools(STAGE, "po_replies", msgs, ot.select(ot.REPLY_TOOLS), max_steps=4, schema=PoRepliesFinal, on_step=ctx.step_emitter(STAGE))
    fg.emit_model_call(ctx, "po_replies", res)
    final = res.parsed
    assert isinstance(final, PoRepliesFinal)
    readings = list(final.readings)
    claims, owners = reading_claims(readings, b.data.replies)
    slot = {c.id: i for i, c in enumerate(claims)}
    checked = verify_all(claims).claims
    for claim in checked:
        ctx.emit("claim_checked", STAGE, {"claim": claim.model_dump(mode="json")})
    replies = _reply_index(b.data.replies)
    sha = file_sha256(oc.REPLIES)

    def rebuild(claim: Claim, fix: ClaimFix) -> Claim | None:
        reading, i = owners[slot[claim.id]]
        c = reading.commitments[i]
        position, reply = replies[reading.reply_id]
        if c.kind == "eta_date":
            c.eta_date = (reply.received_at.date() + timedelta(days=int(fix.value))).isoformat()
        else:
            c.qty = fix.value
        if fix.transcript_quote:
            c.quote = fix.transcript_quote
        return commitment_claim(reply, position, c, i, sha)

    fixed = await self_correct(
        ctx, STAGE, checked, task="po_replies", messages=msgs, previous=res.content, rebuild=rebuild,
        check=lambda batch: verify_all(batch).claims,
    )
    return readings, checked, fixed, res


def reading_rows(readings: list[ReplyReading], claims: list[Claim], replies: list[Reply]) -> list[dict[str, Any]]:
    index = _reply_index(replies)
    by_id = {c.id: c for c in claims}
    rows = []
    for reading in sorted((r for r in readings if r.reply_id in index), key=lambda r: index[r.reply_id][1].received_at, reverse=True):
        reply = index[reading.reply_id][1]
        commits = []
        for i, c in enumerate(reading.commitments):
            claim = by_id.get(f"reply:{reply.id}:{i}")
            commits.append(
                {
                    **c.model_dump(),
                    "claim_id": claim.id if claim else None,
                    "status": claim.status if claim else "unverifiable",
                    "reason": claim.reason if claim else None,
                    "first_value": claim.attempts[0].value if claim and claim.attempts else None,
                    "corrected": bool(claim and claim.status == "verified" and len(claim.attempts) > 1),
                    "resolved_eta": (reply.received_at.date() + timedelta(days=int(claim.value))).isoformat() if claim and c.kind == "eta_date" and claim.status == "verified" else None,
                }
            )
        rows.append(
            {
                "reply_id": reply.id,
                "po_id": reply.po_id,
                "vendor_id": reply.vendor_id,
                "received_at": reply.received_at.isoformat(),
                "from": reply.sender,
                "subject": reply.subject,
                "body": reply.body,
                "stance": reading.stance,
                "summary": reading.summary,
                "excuse": reading.excuse,
                "root_cause": reading.root_cause,
                "commitments": commits,
            }
        )
    return rows


async def write_drafts(ctx: Any, b: ob.Base, signals: dict[str, pos.PoSignal], rows: list[dict[str, Any]]) -> tuple[list[PoDraft], list[str], Any]:
    token = ot.SIGNALS.set(signals)
    try:
        msgs = pr.messages(pr.DRAFTS_SYSTEM, pr.DRAFTS_USER, as_of=b.data.as_of.isoformat())
        res = await llm.run_tools(STAGE, "po_drafts", msgs, ot.select(ot.DRAFT_TOOLS), max_steps=3, schema=PoDraftsFinal, on_step=ctx.step_emitter(STAGE))
    finally:
        ot.SIGNALS.reset(token)
    fg.emit_model_call(ctx, "po_drafts", res)
    final = res.parsed
    assert isinstance(final, PoDraftsFinal)
    wanted = {r["po_id"] for r in rows}
    drafts = {d.po_id: d for d in final.drafts if d.po_id in wanted}
    sources = {pid: "agent" for pid in drafts}
    for r in rows:
        if r["po_id"] not in drafts:
            drafts[r["po_id"]] = template_draft(b, r)
            sources[r["po_id"]] = "template"
    ordered = [drafts[r["po_id"]] for r in rows]
    return ordered, [sources[d.po_id] for d in ordered], res


def draft_record(draft_id: str, kind: str, d: Any, claims: list[Claim], source: str, extra: dict[str, Any]) -> dict[str, Any]:
    by_id = {c.id: c for c in claims}
    figs = [
        {"claim_id": cid, "shown": f.shown, "status": by_id[cid].status if cid in by_id else "pending", "reason": by_id[cid].reason if cid in by_id else None}
        for cid, f in zip([c.id for c in claims], d.figures)
    ]
    return {
        "id": draft_id,
        "kind": kind,
        "channel": getattr(d, "channel", "email"),
        "subject": d.subject,
        "body": d.body,
        "source": source,
        "figures": figs,
        "claim_ids": [c.id for c in claims],
        **extra,
    }


def _inject(claims: list[Claim]) -> list[Claim]:
    """Test hook: make exactly one engine number wrong (a count or quantity off by three) so the verifier has to catch it."""
    out = list(claims)
    for i, c in enumerate(out):
        if c.origin == "engine" and c.unit in ("units", "qty"):
            out[i] = c.model_copy(update={"value": c.value + 3, "origin": "injected_test"})
            break
    return out


async def generate(inject: bool = False) -> dict[str, Any]:
    b = ob.base()
    ops = b.ops
    ctx = fg.new_ctx("chaser", b.data.as_of)
    ctx.emit("stage_started", STAGE, {"task": "po_chaser", "as_of": b.data.as_of.isoformat()})
    readings, _before, claims, _res = await read_replies(ctx, b)
    signals = signals_from(readings, claims, b.data.replies)
    rows = pos.tracker(b.data, ops, signals)
    for r in rows:
        for line in r["lines"]:
            lead = b.data.vendors[r["vendor_id"]].lead_time_days
            line["suggested_reorder"] = suggested_reorder(line, lead, ops.scorecard.stock_cover_alert_days)
    chase = [r for r in rows if r["needs_chase"]]

    drafts, sources, _res2 = await write_drafts(ctx, b, signals, chase)

    # headline engine claims for every row, plus the figures the agent wrote in drafts
    engine: list[Claim] = []
    for r in rows:
        engine.append(oc.engine_claim("ops_days_overdue", r["po_id"], f"{r['po_id']} is {r['days_overdue']} days past its promised date"))
        for line in r["lines"]:
            key = f"{r['po_id']}:{line['sku_code']}"
            engine.append(oc.engine_claim("ops_open_qty", key, f"{line['name']}: {line['open_qty']} units still to arrive on {r['po_id']}"))
            params = {"eta": r["eta"]}
            engine.append(oc.engine_claim("ops_stockout_days", oc.build_key(key, **params), f"{line['name']} is out of stock for {line['stockout_days']} days before {r['po_id']} lands"))
    draft_claims: list[list[Claim]] = []
    unclaimed: list[str] = []
    for n, (d, src) in enumerate(zip(drafts, sources)):
        cl = [fg.figure_claim(f, f"fig:{d.po_id}:{k}") for k, f in enumerate(d.figures)]
        draft_claims.append(cl)
        if src == "agent":
            unclaimed += [f"{d.po_id}: {x}" for x in fg.check_text([d.subject, d.body], d.figures)]
    flat = [c for cl in draft_claims for c in cl]
    verified = verify_all(engine + flat).claims
    if inject:
        verified = verify_all(_inject(engine + flat)).claims
    for c in verified:
        ctx.emit("claim_checked", STAGE, {"claim": c.model_dump(mode="json")})
    all_claims = claims + verified
    status = {c.id: c for c in verified}
    queued = []
    for d, cl, src, row in zip(drafts, draft_claims, sources, chase):
        cl = [status.get(c.id, c) for c in cl]
        rec = draft_record(
            f"DR-{d.po_id}", "po_followup", d, cl, src,
            {"vendor_id": row["vendor_id"], "po_id": d.po_id, "rung": row["rung"]["name"], "owner": row["rung"]["owner"], "to": b.data.vendors[row["vendor_id"]].contact_email},
        )
        queued.append(outbox.put(rec))

    summary = fg.counts(all_claims)
    trace = fg.drain(ctx)
    read_rows = reading_rows(readings, claims, b.data.replies)
    ledger = [
        {
            "po_id": r["po_id"], "vendor_id": r["vendor_id"], "brand": r["brand"], "sku_code": line["sku_code"], "name": line["name"],
            "shortfall_units": line["open_qty"], "days_overdue": r["days_overdue"],
            "root_cause": next((x["root_cause"] for x in read_rows if x["po_id"] == r["po_id"] and x["root_cause"] != "none"), "none"),
        }
        for r in rows for line in r["lines"] if line["open_qty"] > 0 and r["days_overdue"] > 0
    ]
    return {
        "as_of": b.data.as_of.isoformat(),
        "pos": rows,
        "readings": read_rows,
        "ladder": [r.model_dump() for r in ops.po_followup.ladder],
        "ledger": ledger,
        "drafts": [outbox.get(q["id"]) for q in queued],
        "claims": [c.model_dump(mode="json") for c in all_claims],
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "corrected": [c.id for c in all_claims if c.status == "verified" and len(c.attempts) > 1],
        "unresolved": [c.id for c in all_claims if c.origin == "model_extraction" and c.status == "rejected"],
        "unclaimed_numbers": unclaimed,
        "trace": trace,
        "mode": llm.resolve_mode(STAGE),
        "impact_coverage": impact_coverage(len(chase), len({r["vendor_id"] for r in rows})),
    }


def impact_coverage(late_pos: int, vendors: int) -> dict[str, Any]:
    from app.ops.review import impact_for

    return impact_for("po_followup", {"po_chase": late_pos, "fill_rate_reconciliation": vendors})

