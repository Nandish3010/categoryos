"""Deterministic PO tracking: status, days overdue, stock-out risk (days of cover against the remaining lead time) and
the escalation rung. The agent's reading of vendor replies feeds in only as a ``PoSignal`` built from VERIFIED claims.
Never imports llm."""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.ops import metrics as m
from app.ops.data import OpsData, PoLine
from app.policy import Operations


@dataclass
class PoSignal:
    """What the verified replies say about a PO. ``eta`` is the latest dated commitment; ``vague`` is true when the most
    recent reply promised no date."""

    eta: date | None = None
    vague: bool = False
    reply_ids: list[str] = field(default_factory=list)


def open_po_ids(d: OpsData) -> list[str]:
    seen: list[str] = []
    for ln in d.po_lines:
        if ln.status == "open" and ln.po_id not in seen:
            seen.append(ln.po_id)
    return seen


def po_lines(d: OpsData, po_id: str) -> list[PoLine]:
    return [ln for ln in d.po_lines if ln.po_id == po_id]


def promised_date(lines: list[PoLine]) -> date:
    return max(ln.promised for ln in lines)


def days_overdue(d: OpsData, po_id: str) -> int:
    return (d.as_of - promised_date(po_lines(d, po_id))).days


def open_qty(line: PoLine) -> int:
    return max(0, line.ordered - line.received) if line.status == "open" else 0


def line_risk(d: OpsData, ops: Operations, line: PoLine, eta: date | None = None) -> dict[str, Any]:
    """Will this SKU run out before the PO lands? ``eta`` is a verified vendor commitment, else the promised date, else a
    pessimistic assumption for an overdue PO that has no dated commitment."""
    pf = ops.po_followup
    rate = m.daily_rate(d, ops, line.sku_code)
    hand = m.on_hand(d, line.sku_code)
    cover = hand / rate if rate > 0 else None
    if eta is not None:
        arrival, basis = eta, "vendor_reply"
    elif line.promised >= d.as_of:
        arrival, basis = line.promised, "promised_date"
    else:
        arrival, basis = d.as_of + timedelta(days=pf.default_lead_days), "assumed"
    remaining = max(0, (arrival - d.as_of).days)
    if cover is None:
        stockout_days, margin = 0, None
    else:
        stockout_days = max(0, math.ceil(remaining - cover)) if remaining > cover else 0
        margin = cover - remaining
    price = d.skus[line.sku_code].selling_price
    if stockout_days >= 3:
        level = "critical"
    elif stockout_days > 0:
        level = "high"
    elif margin is not None and margin < pf.stockout_buffer_days:
        level = "medium"
    else:
        level = "low"
    return {
        "sku_code": line.sku_code,
        "name": d.skus[line.sku_code].name,
        "ordered": line.ordered,
        "received": line.received,
        "open_qty": open_qty(line),
        "on_hand": hand,
        "daily_rate": round(rate, 2),
        "cover_days": round(cover) if cover is not None else None,
        "arrival": arrival.isoformat(),
        "arrival_basis": basis,
        "remaining_lead_days": remaining,
        "stockout_days": stockout_days,
        "lost_gmv": round(stockout_days * rate * price, 2),
        "risk": level,
    }


def rung_for(ops: Operations, overdue: int, vague: bool) -> dict[str, Any] | None:
    """The highest ladder rung the PO has reached; a vague reply on a late PO moves it up one."""
    ladder = ops.po_followup.ladder
    idx = None
    for i, rung in enumerate(ladder):
        if rung.days_overdue <= overdue:
            idx = i
    if idx is None:
        return None
    bumped = bool(ops.po_followup.vague_reply_bumps_rung and vague and overdue >= 1 and idx < len(ladder) - 1)
    if bumped:
        idx += 1
    r = ladder[idx]
    return {"index": idx, "name": r.name, "channel": r.channel, "owner": r.owner, "tone": r.tone, "bumped_by_vague_reply": bumped, "of": len(ladder)}


_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def po_row(d: OpsData, ops: Operations, po_id: str, signal: PoSignal | None = None) -> dict[str, Any]:
    signal = signal or PoSignal()
    lines = po_lines(d, po_id)
    vendor_id = lines[0].vendor_id
    overdue = days_overdue(d, po_id)
    open_lines = [ln for ln in lines if ln.status == "open"]
    risks = [line_risk(d, ops, ln, signal.eta) for ln in open_lines]
    rung = rung_for(ops, overdue, signal.vague)
    worst = min((r["risk"] for r in risks), key=lambda x: _RISK_ORDER[x], default="low")
    ordered = sum(ln.ordered for ln in lines)
    received = sum(ln.received for ln in lines)
    status = "overdue" if overdue > 0 else "due_soon" if rung is not None else "on_track"
    return {
        "po_id": po_id,
        "vendor_id": vendor_id,
        "brand": d.vendors[vendor_id].brand,
        "po_date": min(ln.po_date for ln in lines).isoformat(),
        "promised_date": promised_date(lines).isoformat(),
        "days_overdue": overdue,
        "status": status,
        "partial": any(0 < ln.received < ln.ordered for ln in open_lines) or (received > 0 and received < ordered),
        "ordered_qty": ordered,
        "received_qty": received,
        "fill_so_far": round(received / ordered, 4) if ordered else None,
        "eta": signal.eta.isoformat() if signal.eta else None,
        "vague_reply": signal.vague,
        "reply_ids": signal.reply_ids,
        "risk": worst,
        "stockout_days": max((r["stockout_days"] for r in risks), default=0),
        "lost_gmv": round(sum(r["lost_gmv"] for r in risks), 2),
        "rung": rung,
        "needs_chase": rung is not None,
        "lines": risks,
    }


def tracker(d: OpsData, ops: Operations, signals: dict[str, PoSignal] | None = None) -> list[dict[str, Any]]:
    signals = signals or {}
    rows = [po_row(d, ops, pid, signals.get(pid)) for pid in open_po_ids(d)]
    rows.sort(key=lambda r: (_RISK_ORDER[r["risk"]], -r["days_overdue"], r["po_id"]))
    return rows
