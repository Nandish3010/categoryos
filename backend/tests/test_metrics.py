import math
import statistics

import pytest
from fastapi.testclient import TestClient

from app.constants import ALLOWED_VENDORS, DEMAND_MIN, OVERLAP_MAX
from app.data_loader import check_vendor, load_sheet
from app.errors import MissingInput, UnknownMetric, UnknownVendor
from app.main import app
from app.metrics import (
    METRIC_UNITS,
    apply_levers,
    build_base,
    compute_metric,
    decide_verdict,
)
from app.parsing import map_columns, parse_pack, parse_price
from app.taxonomy import catalog_subcategories, categories, classify

PRICE_CASES = [
    ("Rs. 1,699.00", 1699.0),
    ("Rs.249/-", 249.0),
    ("INR 299", 299.0),
    ("₹299", 299.0),
    ("1,599.00", 1599.0),
    ("Rs 249", 249.0),
    ("149.00", 149.0),
    ("", None),
    ("  ", None),
    ("n/a", None),
    ("0", None),
]

PACK_CASES = [
    ("1.5kg", {"grams": 1500.0}, "1500g"),
    ("1 KG", {"grams": 1000.0}, "1000g"),
    ("6000 g", {"grams": 6000.0}, "6000g"),
    ("60gm", {"grams": 60.0}, "60g"),
    ("400 grams", {"grams": 400.0}, "400g"),
    ("6L", {"ml": 6000.0}, "6000ml"),
    ("3.8 Ltr", {"ml": 3800.0}, "3800ml"),
    ("6000 ml", {"ml": 6000.0}, "6000ml"),
    ("Pack of 3", {"units": 3}, "3pc"),
    ("1 Pcs", {"units": 1}, "1pc"),
    ("2 pc", {"units": 2}, "2pc"),
    ("", {}, None),
    ("Medium", {}, None),
]


@pytest.mark.parametrize(("raw", "expected"), PRICE_CASES)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize(("raw", "fields", "normalized"), PACK_CASES)
def test_parse_pack(raw, fields, normalized):
    parsed = parse_pack(raw)
    assert parsed["normalized"] == normalized
    for key, value in fields.items():
        assert parsed[key] == value


def test_map_columns_per_vendor():
    expected = {
        "V001": {"code": "Code", "name": "Product Name", "pack": "Pack", "mrp": "MRP"},
        "V002": {"code": "Item Code", "name": "Item", "pack": "Size", "mrp": "M.R.P (INR)", "cost": "Our Cost"},
        "V003": {"code": "Style No", "name": "SKU Desc", "pack": "Qty/Pack", "mrp": "Price"},
        "V004": {"code": "SKU", "name": "Description", "pack": "Weight/Vol", "mrp": "MRP Rs", "description": "About"},
    }
    for vendor_id, want in expected.items():
        headers, _ = load_sheet(vendor_id)
        got = map_columns(headers)
        for field, header in want.items():
            assert got[field] == header, (vendor_id, field)


def _sheet_rows():
    for vendor_id in ALLOWED_VENDORS:
        headers, rows = load_sheet(vendor_id)
        cols = map_columns(headers)
        for row in rows:
            yield vendor_id, cols, row


def test_every_sheet_row_parses():
    count = 0
    for vendor_id, cols, row in _sheet_rows():
        count += 1
        assert row.row >= 2
        price = parse_price(row.cells.get(cols["mrp"], ""))
        assert price is None or price > 0
        if "cost" in cols:
            cost = parse_price(row.cells.get(cols["cost"], ""))
            assert cost is None or cost > 0
        pack = parse_pack(row.cells.get(cols["pack"], ""))
        assert "normalized" in pack
        assert row.cells[cols["code"]].strip()
    assert count >= 40


def test_unparsed_price_is_flagged():
    for vendor_id in ALLOWED_VENDORS:
        for sku in build_base(vendor_id).skus:
            if sku.mrp is None:
                assert "mrp_missing" in sku.flags


def test_taxonomy_covers_every_sku():
    subs = catalog_subcategories()
    for vendor_id in ALLOWED_VENDORS:
        for sku in build_base(vendor_id).skus:
            assert sku.category in categories()
            assert sku.subcategory
            if sku.subcategory not in subs[sku.category]:
                assert "subcategory_not_in_catalog" in sku.flags


def test_classifier_unknown_is_flagged_best_effort():
    result = classify("Zorblax Gadget", "")
    assert result.category in categories()
    assert "unclassified" in result.flags


def test_unknown_vendor():
    with pytest.raises(UnknownVendor):
        check_vendor("V999")
    with pytest.raises(UnknownVendor):
        build_base("../etc")


def test_metrics_never_nan():
    for vendor_id in ALLOWED_VENDORS:
        for resp in (apply_levers(build_base(vendor_id)), apply_levers(build_base(vendor_id), 20, 0)):
            for sku in resp.skus:
                for value in sku.model_dump().values():
                    if isinstance(value, float):
                        assert math.isfinite(value)
            assert math.isfinite(resp.summary.capital_at_risk_inr)


def test_cost_sources():
    v1 = build_base("V001")
    assert all(s.cost_source == "inferred" for s in v1.skus)
    v2 = {s.code: s for s in build_base("V002").skus}
    assert v2["MW-T01"].cost_source == "sheet" and v2["MW-T01"].cost == 148
    assert v2["MW-T03"].cost_source == "inferred"


def test_verdict_boundaries():
    assert decide_verdict(0.5, 0.3, 0.8, 0.6)[0] == "reject"
    assert decide_verdict(0.5, 0.3, 0.8, 0.5999)[0] == "list"
    assert decide_verdict(0.5, 0.3, DEMAND_MIN, 0.1)[0] == "list"
    assert decide_verdict(0.5, 0.3, 0.39996, 0.1)[0] == "list"
    assert decide_verdict(0.5, 0.3, 0.3999, 0.1)[0] == "reject"
    assert decide_verdict(0.3, 0.3, 0.8, 0.1)[0] == "list"
    assert decide_verdict(0.2999, 0.3, 0.8, 0.1)[0] == "negotiate"
    assert decide_verdict(None, 0.3, 0.8, 0.1)[0] == "needs_data"
    assert OVERLAP_MAX == 0.6


def test_overlap_boundary_through_levers():
    base = build_base("V001")
    sku = base.skus[0].model_copy(update={"overlap": 0.6, "demand_score": 0.4})
    reject = apply_levers(base.model_copy(update={"skus": [sku]})).skus[0]
    assert reject.verdict == "reject"
    ok = base.skus[0].model_copy(update={"overlap": 0.5999, "demand_score": 0.4})
    assert apply_levers(base.model_copy(update={"skus": [ok]})).skus[0].verdict == "list"


def test_missing_price_is_needs_data():
    base = build_base("V001")
    sku = base.skus[0].model_copy(update={"cost": None, "cost_source": "missing"})
    out = apply_levers(base.model_copy(update={"skus": [sku]})).skus[0]
    assert out.verdict == "needs_data" and out.fit_score is None


def test_levers_pure_and_hash_sensitive():
    base = build_base("V001")
    before = base.model_dump_json()
    a, b = apply_levers(base), apply_levers(base)
    assert a.metrics_hash == b.metrics_hash
    assert apply_levers(base, 5).metrics_hash != a.metrics_hash
    assert apply_levers(base, 0, 300).metrics_hash != a.metrics_hash
    assert base.model_dump_json() == before


def test_negotiate_required_cost_hits_target():
    for vendor_id in ALLOWED_VENDORS:
        for sku in apply_levers(build_base(vendor_id)).skus:
            if sku.verdict == "negotiate":
                landed = sku.required_cost * 1.04
                assert (sku.selling_price - landed) / sku.selling_price == pytest.approx(sku.target_pct, abs=1e-3)
                assert sku.required_cost < sku.cost


def test_lever_extremes():
    base = build_base("V001")
    low, high = apply_levers(base, -20), apply_levers(base, 20)
    assert low.summary.counts["list"] >= apply_levers(base).summary.counts["list"]
    assert high.summary.counts["list"] <= apply_levers(base).summary.counts["list"]
    zero = apply_levers(base, 0, 0).summary
    assert zero.capital_at_risk_inr == 0 and zero.days_of_cover == 0 and not zero.moq_flag
    big = apply_levers(base, 0, 20000).summary
    assert big.moq_flag


def test_moq_allocation_sums_to_moq():
    resp = apply_levers(build_base("V001"), 0, 150)
    assert sum(s.alloc_units for s in resp.skus) == 150
    assert all(s.alloc_units == 0 for s in resp.skus if s.verdict == "reject")


def test_lever_timing():
    base = build_base("V001")
    apply_levers(base)
    times = []
    import time

    for offset in range(-20, 21):
        start = time.perf_counter()
        apply_levers(base, offset, 150)
        times.append((time.perf_counter() - start) * 1000)
    assert statistics.median(times) < 50
    assert max(times) < 50


def _majority(vendor_id: str, verdict: str) -> bool:
    summary = apply_levers(build_base(vendor_id)).summary
    return summary.counts[verdict] > sum(summary.counts.values()) / 2


def test_outcome_v001_majority_list():
    assert _majority("V001", "list")


def test_outcome_v002_shortlist_is_all_negotiate():
    summary = apply_levers(build_base("V002")).summary
    assert summary.counts["list"] == 0
    assert summary.counts["negotiate"] >= 3
    # every shortlisted (non-reject) SKU is "negotiate"
    assert summary.counts["negotiate"] == summary.shortlisted


def test_outcome_v003_majority_reject():
    assert _majority("V003", "reject")


def test_compute_metric():
    assert compute_metric("V001", "margin_pct", "V001:HP-D01") == pytest.approx(0.3136, abs=1e-4)
    assert compute_metric("V001", "price_gap_pct", "HP-D01") == pytest.approx((1499 - 1549) / 1549, abs=1e-4)
    assert compute_metric("V002", "cost", "V002:MW-T01") == 148
    with pytest.raises(UnknownMetric):
        compute_metric("V001", "nope", "V001:HP-D01")
    with pytest.raises(MissingInput):
        compute_metric("V001", "margin_pct", "V001:NOPE")
    with pytest.raises(MissingInput):
        compute_metric("V001", "required_cost", "V001:HP-D01")
    with pytest.raises(UnknownVendor):
        compute_metric("V009", "margin_pct", "V009:X")
    assert set(METRIC_UNITS) >= {"margin_pct", "price_gap_pct", "est_monthly_units"}


client = TestClient(app)


def test_api_vendors_and_lever():
    vendors = client.get("/api/vendors").json()
    assert [v["id"] for v in vendors] == list(ALLOWED_VENDORS)
    assert vendors[0]["summary"]["counts"]["list"] == 7
    default = client.get("/api/vendors/V001/decide/metrics").json()
    shifted = client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=5&moq=300").json()
    assert default["metrics_hash"] != shifted["metrics_hash"]
    assert shifted["summary"]["moq"] == 300
    assert client.get("/api/vendors/V001").json()["brand_name"] == "Highland Paws"


def test_api_validation():
    assert client.get("/api/vendors/V999").status_code == 404
    assert client.get("/api/vendors/V999/decide/metrics").status_code == 404
    assert client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=21").status_code == 422
    assert client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=-21").status_code == 422
    assert client.get("/api/vendors/V001/decide/metrics?moq=20001").status_code == 422
    assert client.get("/api/vendors/V001/decide/metrics?moq=-1").status_code == 422
    assert client.get("/api/vendors/V001/decide/metrics?moq=0&target_margin_pct_offset=-20").status_code == 200
