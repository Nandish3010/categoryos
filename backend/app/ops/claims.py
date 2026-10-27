"""Claims for the Run modules. Every number the agent writes (and every headline number on a scorecard) is a Claim whose
metric is recomputed here from the ops data. Key grammar: ``<subject>[?name=value&...]`` where subject is ``category``,
a vendor ``E001``, a SKU ``E001:BK-01``, a PO ``PO-E001-0009`` or a PO line ``PO-E001-0009:BK-01``."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cache
from typing import Any

from app import policy
from app.config import settings
from app.errors import MissingInput, UnknownOpsMetric, UnknownOpsVendor
from app.ops import metrics as m
from app.ops import pos
from app.ops.data import OpsData, allowed_files, file_sha256, load
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Evidence, SourceRef

SALES = "ops/sales_daily.csv"
PURCHASE_ORDERS = "ops/purchase_orders.csv"
INVENTORY = "ops/inventory_batches.csv"
RETURNS = "ops/returns.csv"
RATINGS = "ops/ratings.csv"
REPLIES = "ops/vendor_replies.json"

_VENDOR = re.compile(r"^E\d{3}$")
_SKU = re.compile(r"^(E\d{3}):([A-Z]{2}-\d{2})$")
_PO = re.compile(r"^PO-E\d{3}-\d{4}$")
_LINE = re.compile(r"^(PO-E\d{3}-\d{4}):([A-Z]{2}-\d{2})$")


@dataclass(frozen=True)
class Subject:
    kind: str  # category | vendor | sku | po | line
    vendor_id: str | None = None
    sku_code: str | None = None
    po_id: str | None = None
    params: tuple[tuple[str, str], ...] = ()

    def param(self, name: str) -> str | None:
        return dict(self.params).get(name)


def parse_key(key: str) -> Subject:
    subject, _, query = key.partition("?")
    params = tuple(tuple(p.split("=", 1)) for p in query.split("&") if "=" in p)  # type: ignore[misc]
    if subject == "category":
        return Subject("category", params=params)
    if _VENDOR.match(subject):
        return Subject("vendor", vendor_id=subject, params=params)
    if (mt := _SKU.match(subject)):
        return Subject("sku", vendor_id=mt.group(1), sku_code=mt.group(2), params=params)
    if _PO.match(subject):
        return Subject("po", po_id=subject, vendor_id=subject.split("-")[1], params=params)
    if (mt := _LINE.match(subject)):
        return Subject("line", po_id=mt.group(1), vendor_id=mt.group(1).split("-")[1], sku_code=mt.group(2), params=params)
    raise MissingInput(f"malformed ops key {key!r}", fix="Use E001, E001:BK-01, PO-E001-0009, PO-E001-0009:BK-01 or category")


def build_key(subject: str, **params: Any) -> str:
    return subject + ("?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None) if any(v is not None for v in params.values()) else "")


def data_sha() -> str:
    """One hash over every ops data file: an engine claim's evidence says which data it was computed from."""
    h = hashlib.sha256()
    for rel in sorted(allowed_files()):
        h.update(file_sha256(rel).encode())
    return h.hexdigest()


@cache
def _card_cached(data_dir: str, policy_hash: str, vendor_id: str) -> dict[str, Any]:
    return m.vendor_scorecard(load(), policy.get().operations, vendor_id)


def card(vendor_id: str) -> dict[str, Any]:
    if vendor_id not in load().vendors:
        raise UnknownOpsVendor(vendor_id)
    return _card_cached(str(settings.data_dir), policy.policy_hash(), vendor_id)


def sku_card(vendor_id: str, sku_code: str) -> dict[str, Any]:
    row = next((s for s in card(vendor_id)["skus"] if s["sku_code"] == sku_code), None)
    if row is None:
        raise MissingInput(f"unknown SKU {sku_code!r} for {vendor_id}", fix="Take SKU codes from the vendor scorecard")
    return row


@cache
def _category_cached(data_dir: str, policy_hash: str) -> dict[str, Any]:
    return m.category_summary(load(), policy.get().operations)


def category() -> dict[str, Any]:
    return _category_cached(str(settings.data_dir), policy.policy_hash())


def _eta(sub: Subject) -> date | None:
    raw = sub.param("eta")
    return date.fromisoformat(raw) if raw else None


def _line(d: OpsData, sub: Subject):
    line = next((ln for ln in d.po_lines if ln.po_id == sub.po_id and ln.sku_code == sub.sku_code), None)
    if line is None:
        raise MissingInput(f"{sub.po_id} has no line for {sub.sku_code}", fix="Take PO lines from GET /api/ops/pos")
    return line


@dataclass(frozen=True)
class MetricDef:
    unit: str
    file: str
    scope: str  # category | vendor | sku | po | line
    fn: Callable[[Subject], float | None]
    label: str


def _vendor(field: str) -> Callable[[Subject], float | None]:
    return lambda s: card(s.vendor_id or "")[field]


def _sku(field: str) -> Callable[[Subject], float | None]:
    return lambda s: sku_card(s.vendor_id or "", s.sku_code or "")[field]


def _po_overdue(s: Subject) -> float:
    d = load()
    if not pos.po_lines(d, s.po_id or ""):
        from app.errors import UnknownPo

        raise UnknownPo(s.po_id or "")
    return float(pos.days_overdue(d, s.po_id or ""))


def _risk(field: str) -> Callable[[Subject], float | None]:
    def fn(s: Subject) -> float | None:
        d = load()
        return float(pos.line_risk(d, policy.get().operations, _line(d, s), _eta(s))[field])

    return fn


METRICS: dict[str, MetricDef] = {
    # category
    "ops_cat_gmv": MetricDef("inr", SALES, "category", lambda s: category()["gmv"], "Category GMV, review week"),
    "ops_cat_gmv_growth_wow": MetricDef("pct", SALES, "category", lambda s: category()["gmv_growth_wow"], "Category GMV growth, week on week"),
    "ops_cat_fill_rate_recent": MetricDef("pct", PURCHASE_ORDERS, "category", lambda s: category()["fill_rate_recent"], "Category fill rate, recent weeks"),
    "ops_cat_otif": MetricDef("pct", PURCHASE_ORDERS, "category", lambda s: category()["otif"], "Category OTIF"),
    # vendor
    "ops_gmv": MetricDef("inr", SALES, "vendor", _vendor("gmv"), "Vendor GMV, review week"),
    "ops_units": MetricDef("units", SALES, "vendor", _vendor("units"), "Vendor units, review week"),
    "ops_gmv_growth_wow": MetricDef("pct", SALES, "vendor", _vendor("gmv_growth_wow"), "Vendor GMV growth, week on week"),
    "ops_gmv_z": MetricDef("ratio", SALES, "vendor", _vendor("gmv_z"), "Vendor weekly GMV z-score"),
    "ops_margin_pct": MetricDef("pct", SALES, "vendor", _vendor("margin_pct"), "Vendor gross margin"),
    "ops_fill_rate": MetricDef("pct", PURCHASE_ORDERS, "vendor", _vendor("fill_rate"), "Vendor fill rate, 13 weeks"),
    "ops_fill_rate_recent": MetricDef("pct", PURCHASE_ORDERS, "vendor", _vendor("fill_rate_recent"), "Vendor fill rate, recent weeks"),
    "ops_fill_rate_prior": MetricDef("pct", PURCHASE_ORDERS, "vendor", _vendor("fill_rate_prior"), "Vendor fill rate, earlier weeks"),
    "ops_otif": MetricDef("pct", PURCHASE_ORDERS, "vendor", _vendor("otif"), "Vendor on-time-in-full"),
    "ops_min_cover_days": MetricDef("units", INVENTORY, "vendor", lambda s: _round_int(card(s.vendor_id or "")["min_cover_days"]), "Lowest SKU stock cover (days)"),
    "ops_aged_pct": MetricDef("pct", INVENTORY, "vendor", _vendor("aged_pct"), "Share of stock value in the oldest bucket"),
    "ops_return_rate": MetricDef("pct", RETURNS, "vendor", _vendor("return_rate"), "Vendor return rate, 4 weeks"),
    "ops_rating": MetricDef("ratio", RATINGS, "vendor", _vendor("rating"), "Vendor rating"),
    "ops_rating_change": MetricDef("ratio", RATINGS, "vendor", _vendor("rating_change"), "Vendor rating change, 4 weeks"),
    # sku
    "ops_sku_gmv": MetricDef("inr", SALES, "sku", _sku("gmv"), "SKU GMV, review week"),
    "ops_sku_units": MetricDef("units", SALES, "sku", _sku("units"), "SKU units, review week"),
    "ops_sku_units_prev": MetricDef("units", SALES, "sku", _sku("units_prev"), "SKU units, previous week"),
    "ops_sku_growth_wow": MetricDef("pct", SALES, "sku", _sku("growth_wow"), "SKU growth, week on week"),
    "ops_sku_units_z": MetricDef("ratio", SALES, "sku", _sku("units_z"), "SKU weekly units z-score"),
    "ops_sku_cover_days": MetricDef("units", INVENTORY, "sku", lambda s: _round_int(sku_card(s.vendor_id or "", s.sku_code or "")["cover_days"]), "SKU stock cover (days)"),
    "ops_sku_on_hand": MetricDef("qty", INVENTORY, "sku", _sku("on_hand"), "SKU units on hand"),
    "ops_sku_return_rate": MetricDef("pct", RETURNS, "sku", _sku("return_rate"), "SKU return rate, 4 weeks"),
    "ops_sku_rating": MetricDef("ratio", RATINGS, "sku", _sku("rating"), "SKU rating"),
    "ops_sku_rating_change": MetricDef("ratio", RATINGS, "sku", _sku("rating_change"), "SKU rating change, 4 weeks"),
    # po / line
    "ops_days_overdue": MetricDef("units", PURCHASE_ORDERS, "po", _po_overdue, "PO days past promised date"),
    "ops_open_qty": MetricDef("qty", PURCHASE_ORDERS, "line", lambda s: float(pos.open_qty(_line(load(), s))), "PO line quantity still to arrive"),
    "ops_line_cover_days": MetricDef("units", INVENTORY, "line", _risk("cover_days"), "Stock cover of the PO line's SKU (days)"),
    "ops_stockout_days": MetricDef("units", INVENTORY, "line", _risk("stockout_days"), "Days the SKU is out of stock before the PO lands"),
    "ops_lost_gmv": MetricDef("inr", INVENTORY, "line", _risk("lost_gmv"), "GMV lost while out of stock"),
}

# extraction metrics (checked against the vendor reply text, see ops/verify.py)
EXTRACTION_METRICS = {"reply_eta_days": "units", "reply_qty": "qty"}


def _round_int(value: float | None) -> float | None:
    return None if value is None else float(round(value))


def unit_of(metric: str) -> str:
    if metric in METRICS:
        return METRICS[metric].unit
    if metric in EXTRACTION_METRICS:
        return EXTRACTION_METRICS[metric]
    raise UnknownOpsMetric(metric)


def rounded(value: float, unit: str) -> float:
    if unit == "pct":
        return round(value, 4)
    if unit == "inr":
        return round(value, 2)
    if unit == "ratio":
        return round(value, 2)
    return float(round(value))


def compute(metric: str, key: str) -> float:
    """Recompute a metric from the data. Raises a typed error when the subject or metric is unknown or empty."""
    if metric not in METRICS:
        raise UnknownOpsMetric(metric)
    mdef = METRICS[metric]
    sub = parse_key(key)
    if sub.kind != mdef.scope:
        raise MissingInput(f"{metric} needs a {mdef.scope} key, got {key!r}", fix="Use the key form for this metric")
    value = mdef.fn(sub)
    if value is None:
        raise MissingInput(f"{metric} has no value for {key!r}", fix="The data has too few rows for this subject")
    return rounded(float(value), mdef.unit)


def engine_claim(metric: str, key: str, text: str, *, value: float | None = None, claim_id: str | None = None) -> Claim:
    """A claim for ``metric`` at ``key``. With ``value`` omitted the engine value is used (a headline number);
    with it set, the value is what the agent wrote and the verifier will recompute and compare."""
    mdef = METRICS[metric]
    shown = compute(metric, key) if value is None else rounded(float(value), mdef.unit)
    return Claim(
        id=claim_id or f"{key}:{metric}",
        text=text,
        value=shown,
        metric=metric,
        unit=mdef.unit,  # type: ignore[arg-type]
        sku_key=f"{parse_key(key).vendor_id}:{parse_key(key).sku_code}" if parse_key(key).sku_code and parse_key(key).kind == "sku" else None,
        source_ref=SourceRef(file=mdef.file, key=key, column=metric),
        evidence=Evidence(normalized_value=shown, parser_version=PARSER_VERSION, sha256=data_sha()),
        origin="engine",
    )
