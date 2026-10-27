"""The deterministic base of the weekly review: scorecards, anomalies and the candidate action list. No model involved."""

from dataclasses import dataclass
from functools import cache
from typing import Any

from app import policy
from app.config import settings
from app.ops import claims as oc
from app.ops import metrics as m
from app.ops.data import OpsData, load
from app.policy import Operations

ACTION_TITLE = {
    "stockout": "Expedite replenishment of {name}",
    "fill_rate": "Agree a fill-rate recovery plan with {brand}",
    "otif": "Raise on-time-in-full with {brand}",
    "ageing": "Plan a markdown, bundle or return for {brand}'s aged stock",
    "overstock": "Pause reorders on {name}",
    "returns": "Investigate returns on {name}",
    "rating": "Find out why {name} is rated lower",
    "sales_drop": "Find out why {name} sales fell",
    "sales_spike": "Check stock for {name} before the spike runs it out",
}
VENDOR_FACING = ("stockout", "fill_rate", "otif", "ageing", "overstock", "returns", "rating", "sales_drop")


@dataclass(frozen=True)
class Base:
    data: OpsData
    ops: Operations
    cards: dict[str, dict[str, Any]]
    category: dict[str, Any]
    anomalies: list[dict[str, Any]]
    actions: list[dict[str, Any]]


def build_actions(d: OpsData, ops: Operations, anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weights = ops.actions.priority_weights
    ageing_vendors = {a["vendor_id"] for a in anomalies if a["type"] == "ageing"}
    out = []
    for a in anomalies:
        if a["type"] == "overstock" and a["vendor_id"] in ageing_vendors:
            continue  # the ageing action covers the overstocked SKUs of that vendor
        if a["type"] == "sales_spike" and not any(x["type"] == "stockout" and x["sku_code"] == a["sku_code"] for x in anomalies):
            weight = weights.get("sales_spike", 0) * 0.4
        else:
            weight = weights.get(a["type"], 0)
        brand = d.vendors[a["vendor_id"]].brand
        name = d.skus[a["sku_code"]].name if a["sku_code"] else brand
        score = weight * a["severity"] + min(a["exposure_inr"] / 10000, 20)
        out.append(
            {
                "id": f"act:{a['id']}",
                "anomaly_id": a["id"],
                "vendor_id": a["vendor_id"],
                "sku_code": a["sku_code"],
                "type": a["type"],
                "title": ACTION_TITLE[a["type"]].format(name=name, brand=brand),
                "severity": a["severity"],
                "exposure_inr": a["exposure_inr"],
                "score": round(score, 1),
            }
        )
    out.sort(key=lambda x: (-x["score"], x["id"]))
    for i, row in enumerate(out, start=1):
        row["deterministic_rank"] = i
    return out


@cache
def _base(data_dir: str, policy_hash: str) -> Base:
    d, ops = load(), policy.get().operations
    cards = {vid: oc.card(vid) for vid in d.vendors}
    anomalies = m.detect_anomalies(d, ops, cards)
    return Base(d, ops, cards, oc.category(), anomalies, build_actions(d, ops, anomalies))


def base() -> Base:
    return _base(str(settings.data_dir), policy.policy_hash())


def flagged_vendors(b: Base) -> list[str]:
    return [vid for vid in b.cards if any(a["vendor_id"] == vid and a["type"] in VENDOR_FACING for a in b.anomalies)]
