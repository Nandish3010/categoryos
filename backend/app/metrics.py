import hashlib
import json
import re
import time
from functools import cache, lru_cache
from statistics import median
from typing import Any

from app.constants import (
    DEMAND_MIN,
    FREIGHT_PCT,
    METRIC_WEIGHTS,
    MOQ_FACTOR,
    OVERLAP_MAX,
    ROUND_DP,
)
from app.data_loader import (
    check_vendor,
    load_application,
    load_benchmarks,
    load_catalog,
    load_keywords,
    load_listings,
    load_reviews,
    load_sheet,
)
from app.errors import MissingInput, UnknownMetric
from app.parsing import PARSER_VERSION, map_columns, parse_pack, parse_price
from app.schemas import BaseSku, DecideSummary, LeverResponse, SkuMetrics, VendorBase
from app.taxonomy import classify, species

NEUTRAL_REVIEW = 0.6
MATCH_MIN_COVERAGE = 0.7
GENERIC_TOKENS = frozenset({"food", "dog", "cat", "pet", "treat", "for", "under", "and", "with", "the", "of"})
STOP_TOKENS = frozenset({"and", "for", "with", "the", "of", "a", "set", "x", "pack", "pc", "pcs"})
_SIZE_TOKEN = re.compile(r"^\d+(?:\.\d+)?(?:g|kg|ml|l|ltr|pc|pcs|m)?$")

METRIC_UNITS = {
    "margin_pct": "pct",
    "price_gap_pct": "pct",
    "target_pct": "pct",
    "demand_score": "ratio",
    "overlap": "ratio",
    "review_score": "score",
    "fit_score": "score",
    "est_monthly_units": "units",
    "est_gmv": "inr",
    "landed_cost": "inr",
    "cost": "inr",
    "selling_price": "inr",
    "mrp": "inr",
    "required_cost": "inr",
}


def r4(value: float) -> float:
    return round(value, ROUND_DP)


def tokens(text: str) -> list[str]:
    out = []
    for raw in re.split(r"[^a-z0-9.]+", text.lower()):
        raw = raw.strip(".")
        if not raw:
            continue
        if raw.endswith("ies") and len(raw) > 4:
            raw = raw[:-3] + "y"
        elif raw.endswith("ing") and len(raw) > 6:
            raw = raw[:-3]
        elif raw.endswith("s") and not raw.endswith("ss") and len(raw) > 3:
            raw = raw[:-1]
        out.append(raw)
    return out


def _name_tokens(name: str, brand_words: frozenset[str]) -> set[str]:
    return {
        t
        for t in tokens(name)
        if t not in brand_words and t not in STOP_TOKENS and not _SIZE_TOKEN.match(t)
    }


def _brand_words(vendor_brand: str) -> frozenset[str]:
    words: set[str] = set(tokens(vendor_brand))
    for sku in load_catalog():
        words.update(tokens(sku.brand))
    return frozenset(words)


def _sim_tokens(name: str, pack_normalized: str | None, brand_words: frozenset[str]) -> set[str]:
    toks = _name_tokens(name, brand_words)
    if pack_normalized:
        toks.add(f"pk:{pack_normalized}")
    return toks


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@lru_cache(maxsize=1)
def _demand_table() -> tuple[tuple[str, set[str], float, float], ...]:
    keywords = load_keywords()
    raw = [k.monthly_searches * (1 + k.trend_3m_pct / 100) for k in keywords]
    n = len(raw)
    rows = []
    for kw, score in zip(keywords, raw):
        below = sum(1 for other in raw if other < score)
        percentile = below / (n - 1) if n > 1 else 0.0
        rows.append((kw.keyword, set(tokens(kw.keyword)), score, r4(percentile)))
    return tuple(rows)


def match_keyword(name_toks: set[str], other_toks: set[str]) -> tuple[str | None, float]:
    """Deterministic token-overlap match; returns (keyword, demand percentile) or (None, 0)."""
    best_key: tuple[float, int, int, float] | None = None
    best: tuple[str, float] | None = None
    all_toks = name_toks | other_toks
    for keyword, ktoks, raw, percentile in _demand_table():
        weights = {t: 0.5 if t in GENERIC_TOKENS else 1.0 for t in ktoks}
        total = sum(weights.values())
        covered = sum(w for t, w in weights.items() if t in all_toks)
        coverage = covered / total if total else 0.0
        specific = [t for t in ktoks if t not in GENERIC_TOKENS]
        if coverage < MATCH_MIN_COVERAGE:
            continue
        if specific and not any(t in all_toks for t in specific):
            continue
        key = (
            round(coverage, 6),
            sum(1 for t in specific if t in name_toks),
            sum(1 for t in specific if t in all_toks),
            raw,
        )
        if best_key is None or key > best_key:
            best_key, best = key, (keyword, percentile)
    return best if best else (None, 0.0)


def decide_verdict(
    margin: float | None,
    target: float,
    demand: float,
    overlap: float,
    has_inputs: bool = True,
) -> tuple[str, list[str]]:
    if not has_inputs or margin is None:
        return "needs_data", ["missing price or cost"]
    reasons: list[str] = []
    if round(demand, ROUND_DP) < DEMAND_MIN:
        reasons.append(f"demand {demand:.2f} below minimum {DEMAND_MIN:.2f}")
    if round(overlap, ROUND_DP) >= OVERLAP_MAX:
        reasons.append(f"overlap {overlap:.2f} at or above maximum {OVERLAP_MAX:.2f}")
    if reasons:
        return "reject", reasons
    if round(margin, ROUND_DP) >= round(target, ROUND_DP):
        return "list", [f"margin {margin:.1%} meets target {target:.1%}"]
    return "negotiate", [f"margin {margin:.1%} below target {target:.1%}"]


@cache
def build_base(vendor_id: str) -> VendorBase:
    check_vendor(vendor_id)
    app = load_application(vendor_id)
    brand = app["brand_name"]
    terms = app["proposed_terms"]
    headers, rows = load_sheet(vendor_id)
    cols = map_columns(headers)
    benchmarks = load_benchmarks()
    catalog = load_catalog()
    listings = load_listings()
    brand_words = _brand_words(brand)
    reviews = load_reviews().get(brand) or []
    review_score = r4(sum(r["rating"] for r in reviews) / len(reviews)) if reviews else None
    hint = species(f"{app.get('company_name', '')} {app.get('pitch', '')}")
    offered = terms.get("margin_offered_pct")

    def cell(cells: dict[str, str], field: str) -> str:
        return cells.get(cols[field], "") if field in cols else ""

    skus: list[BaseSku] = []
    for row in rows:
        cells = row.cells
        code = cell(cells, "code").strip()
        name = cell(cells, "name").strip()
        desc = cell(cells, "description").strip()
        cls = classify(name, desc, hint)
        flags: list[str] = list(cls.flags)
        bench = benchmarks[cls.category]

        mrp = parse_price(cell(cells, "mrp"))
        if mrp is None:
            flags.append("mrp_missing")
        pack = cell(cells, "pack").strip() or None
        pack_norm = parse_pack(pack)["normalized"]
        if pack_norm is None:
            flags.append("pack_missing")

        sku_key = f"{vendor_id}:{code}"
        comps = listings.get(sku_key, ())
        selling: float | None
        gap: float | None = None
        if comps:
            selling = float(median(c.price for c in comps))
            if mrp is not None:
                gap = r4((mrp - selling) / selling)
        else:
            flags.append("no_competitors")
            selling = mrp

        cost = parse_price(cell(cells, "cost"))
        cost_source = "sheet"
        if cost is None:
            if selling is not None and offered is not None:
                cost, cost_source = r4(selling * (1 - offered / 100)), "inferred"
            else:
                cost_source = "missing"
        if cost_source != "sheet":
            flags.append(f"cost_{cost_source}")

        keyword, demand = match_keyword(
            set(tokens(name)), set(tokens(f"{desc} {cls.category} {cls.subcategory}"))
        )
        if keyword is None:
            flags.append("no_keyword_match")
        if review_score is None:
            flags.append("no_review")

        mine = _sim_tokens(name, pack_norm, brand_words)
        overlap, nearest = 0.0, None
        for other in catalog:
            if other.category != cls.category or other.subcategory != cls.subcategory:
                continue
            other_pack = parse_pack(other.pack_size)["normalized"]
            sim = _jaccard(mine, _sim_tokens(other.name, other_pack, brand_words))
            if nearest is None or sim > overlap:
                overlap, nearest = sim, other.sku_id
        overlap = r4(overlap)

        avg_units = float(bench["avg_monthly_units_per_sku"])
        skus.append(
            BaseSku(
                sku_key=sku_key,
                code=code,
                name=name,
                sheet_row=row.row,
                raw=dict(cells),
                columns=cols,
                category=cls.category,
                subcategory=cls.subcategory,
                pack=pack,
                pack_normalized=pack_norm,
                mrp=mrp,
                cost=cost,
                cost_source=cost_source,
                selling_price=selling,
                competitor_count=len(comps),
                price_gap_pct=gap,
                matched_keyword=keyword,
                demand_score=demand,
                overlap=overlap,
                nearest_sku_id=nearest,
                review_score=review_score,
                avg_monthly_units=avg_units,
                est_monthly_units=r4(avg_units * demand * (1 - overlap)),
                category_target_pct=bench["target_margin_pct"] / 100,
                category_min_pct=bench["min_margin_pct"] / 100,
                flags=flags,
            )
        )
    return VendorBase(
        vendor_id=vendor_id,
        brand=brand,
        company_name=app["company_name"],
        categories=list(app.get("categories", [])),
        proposed_terms=terms,
        parser_version=PARSER_VERSION,
        skus=skus,
    )


def _allocate(total: int, weights: list[float]) -> list[int]:
    s = sum(weights)
    if total <= 0 or s <= 0:
        return [0] * len(weights)
    exact = [total * w / s for w in weights]
    floors = [int(x) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: (floors[i] - exact[i], i))
    for i in order[: total - sum(floors)]:
        floors[i] += 1
    return floors


def _round_floats(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, ROUND_DP)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def _lever_sku(base: BaseSku, offset: float) -> SkuMetrics:
    target = r4(min(max(base.category_target_pct + offset, 0.0), 0.95))
    selling, cost = base.selling_price, base.cost
    landed = r4(cost * (1 + FREIGHT_PCT)) if cost is not None else None
    margin = r4((selling - landed) / selling) if selling and landed is not None else None
    verdict, reasons = decide_verdict(
        margin, target, base.demand_score, base.overlap, selling is not None and cost is not None
    )
    flags = list(base.flags)
    required = None
    fit = None
    if margin is not None:
        margin_norm = min(max(margin / target, 0.0), 1.0) if target > 0 else 1.0
        review_norm = base.review_score / 5 if base.review_score is not None else NEUTRAL_REVIEW
        w = METRIC_WEIGHTS
        fit = r4(
            100
            * (
                w["margin"] * margin_norm
                + w["demand"] * base.demand_score
                + w["overlap"] * (1 - base.overlap)
                + w["review"] * review_norm
            )
        )
        if verdict in {"list", "negotiate"} and margin < base.category_min_pct:
            flags.append("below_min")
        if verdict == "negotiate" and selling is not None:
            required = r4(selling * (1 - target) / (1 + FREIGHT_PCT))
    return SkuMetrics(
        **base.model_dump(exclude={"flags"}),
        flags=flags,
        target_pct=target,
        landed_cost=landed,
        margin_pct=margin,
        est_gmv=r4(base.est_monthly_units * selling) if selling else 0.0,
        fit_score=fit,
        verdict=verdict,
        reasons=reasons,
        required_cost=required,
    )


def apply_levers(base: VendorBase, target_offset_pp: float = 0, moq: int | None = None) -> LeverResponse:
    """Pure function of (base, offset, moq); it never mutates base.

    Assumption: proposed_terms.moq_units is the vendor's total first-order MOQ across the
    whole range, not a per-SKU minimum. It is allocated across shortlisted (list + negotiate)
    SKUs in proportion to their estimated monthly units, and moq_flag compares it with the
    shortlisted forecast (MOQ > MOQ_FACTOR x summed monthly units).
    """
    started = time.perf_counter()
    if moq is None:
        moq = int(base.proposed_terms.get("moq_units") or 0)
    skus = [_lever_sku(s, target_offset_pp / 100) for s in base.skus]
    short = [s for s in skus if s.verdict in {"list", "negotiate"}]
    alloc = _allocate(moq, [s.est_monthly_units for s in short])
    capital = 0.0
    for s, units in zip(short, alloc):
        s.alloc_units = units
        s.capital_at_risk_inr = r4(units * (s.landed_cost or 0.0))
        capital += units * (s.landed_cost or 0.0)
    monthly = sum(s.est_monthly_units for s in short)
    counts = {v: 0 for v in ("list", "negotiate", "reject", "needs_data")}
    for s in skus:
        counts[s.verdict] += 1
    summary = DecideSummary(
        counts=counts,
        moq=moq,
        shortlisted=len(short),
        capital_at_risk_inr=r4(capital),
        days_of_cover=r4(moq / (monthly / 30)) if monthly > 0 else None,
        est_monthly_gmv=r4(sum(s.est_gmv for s in short)),
        moq_flag=moq > MOQ_FACTOR * monthly,
    )
    payload = _round_floats(
        {
            "vendor": base.vendor_id,
            "parser": base.parser_version,
            "offset_pp": target_offset_pp,
            "moq": moq,
            "skus": [s.model_dump() for s in skus],
            "summary": summary.model_dump(),
        }
    )
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return LeverResponse(
        vendor_id=base.vendor_id,
        target_margin_pct_offset=target_offset_pp,
        skus=skus,
        summary=summary,
        metrics_hash=digest,
        computed_ms=round((time.perf_counter() - started) * 1000, 3),
    )


def compute_metric(vendor_id: str, metric_name: str, sku_key: str) -> float:
    if metric_name not in METRIC_UNITS:
        raise UnknownMetric(metric_name)
    base = build_base(vendor_id)
    key = sku_key if ":" in sku_key else f"{vendor_id}:{sku_key}"
    sku = next((s for s in apply_levers(base).skus if s.sku_key == key), None)
    if sku is None:
        raise MissingInput(f"unknown sku {sku_key!r} for {vendor_id}")
    value = getattr(sku, metric_name)
    if value is None:
        raise MissingInput(f"{metric_name} unavailable for {key}")
    return float(value)
