import pytest

from app import policy
from app.config import settings

TOL = {u: policy.tol(u) for u in ('pct', 'inr', 'units', 'score', 'ratio', 'qty')}
from app.metrics import METRIC_UNITS, apply_levers, build_base, compute_metric
from app.schemas import Claim, Evidence, SourceRef
from app.util import fmt_inr
from app.verify import (
    engine_claims,
    file_sha256,
    inject_fault,
    verify_all,
    verify_claim,
)

SHEET = "vendors/V001/sku_sheet.csv"


def engine_claim(value: float, metric="margin_pct", unit="pct", file=SHEET, **kw) -> Claim:
    return Claim(
        id="c1",
        text="t",
        value=value,
        metric=metric,
        unit=unit,
        sku_key="V001:HP-D01",
        source_ref=SourceRef(file=file, key="V001:HP-D01"),
        **kw,
    )


def mrp_claim(value: float, **kw) -> Claim:
    ev = kw.pop("evidence", None) or Evidence(
        row=2, header="MRP", raw_value="1499", parser_version="1.0", sha256=file_sha256(SHEET)
    )
    return Claim(
        id="m1",
        text="HP-D01 MRP",
        value=value,
        metric="mrp",
        unit="inr",
        sku_key="V001:HP-D01",
        source_ref=SourceRef(file=SHEET, key="V001:HP-D01", column="MRP"),
        evidence=ev,
        origin="model_extraction",
        **kw,
    )


def test_engine_claim_verified():
    out = verify_claim(engine_claim(0.3578))
    assert out.status == "verified"
    assert out.recomputed == pytest.approx(0.3578, abs=1e-4)


@pytest.mark.parametrize(
    ("metric", "unit", "true", "tol"),
    [
        ("margin_pct", "pct", 0.3578, TOL["pct"]),
        ("cost", "inr", 148.0, TOL["inr"]),
        ("demand_score", "ratio", compute_metric("V001", "demand_score", "V001:HP-D01"), TOL["ratio"]),
        ("overlap", "ratio", compute_metric("V001", "overlap", "V001:HP-D01"), TOL["ratio"]),
        ("fit_score", "score", compute_metric("V001", "fit_score", "V001:HP-D01"), TOL["score"]),
    ],
)
def test_tolerance_per_unit(metric, unit, true, tol):
    sku = "V002:MW-T01" if metric == "cost" else "V001:HP-D01"
    vendor = sku.split(":")[0]

    def claim(v):
        return Claim(
            id="x", text="t", value=v, metric=metric, unit=unit, sku_key=sku,
            source_ref=SourceRef(file=f"vendors/{vendor}/sku_sheet.csv", key=sku),
        )  # fmt: skip

    assert verify_claim(claim(true + tol * 0.9)).status == "verified"
    assert verify_claim(claim(true + tol * 2)).status == "rejected"


def test_wrong_value_rejected_with_reason():
    out = verify_claim(engine_claim(0.1336))
    assert out.status == "rejected"
    assert "recomputed" in out.reason


def test_model_extraction_verified_against_raw_cell():
    out = verify_claim(mrp_claim(1499))
    assert out.status == "verified"
    assert out.recomputed == 1499


def test_model_extraction_wrong_value_rejected():
    out = verify_claim(mrp_claim(1949))
    assert out.status == "rejected"
    assert out.recomputed == 1499


def test_tampered_evidence_raw_value_is_ignored():
    ev = Evidence(row=2, header="MRP", raw_value="1949", parser_version="1.0", sha256=file_sha256(SHEET))
    # claim and (forged) raw_value agree, but the real cell says 1499
    out = verify_claim(mrp_claim(1949, evidence=ev))
    assert out.status == "rejected"
    assert out.recomputed == 1499


def test_sha_mismatch_rejected_as_source_changed():
    ev = Evidence(row=2, header="MRP", raw_value="1499", parser_version="1.0", sha256="0" * 64)
    out = verify_claim(mrp_claim(1499, evidence=ev))
    assert out.status == "rejected"
    assert "source changed" in out.reason


def test_extraction_without_evidence_rejected():
    claim = mrp_claim(1499).model_copy(update={"evidence": None})
    assert verify_claim(claim).status == "rejected"


@pytest.mark.parametrize(
    "bad", ["../../../etc/passwd", "/etc/passwd", "vendors/V009/sku_sheet.csv", "vendors/V001/../../x.csv", "backend/.env"]
)
def test_path_outside_allowlist_rejected(bad):
    out = verify_claim(engine_claim(0.3136, file=bad))
    assert out.status == "rejected"
    assert "unknown source" in out.reason


def test_unknown_metric_unverifiable():
    out = verify_claim(engine_claim(1.0, metric="vibes", unit="score"))
    assert out.status == "unverifiable"


def test_unknown_sku_rejected_not_crashing():
    claim = engine_claim(0.3).model_copy(update={"sku_key": "V001:NOPE"})
    assert verify_claim(claim).status == "rejected"


def test_engine_claims_all_verify_and_cover_metrics():
    lever = apply_levers(build_base("V001"))
    claims = engine_claims("V001", lever)
    summary = verify_all(claims)
    assert summary.total == len(claims) > 5
    assert summary.verified == summary.total
    metrics = {c.metric for c in claims}
    assert {"margin_pct", "price_gap_pct", "demand_score", "overlap", "capital_at_risk_inr"} <= metrics
    capital = next(c for c in claims if c.metric == "capital_at_risk_inr")
    assert fmt_inr(capital.value) in capital.text


def test_engine_claims_follow_lever_params():
    lever = apply_levers(build_base("V001"), 3.0, 400)
    summary = verify_all(engine_claims("V001", lever))
    assert summary.rejected == 0
    capital = next(c for c in summary.claims if c.metric == "capital_at_risk_inr")
    assert capital.recomputed == pytest.approx(lever.summary.capital_at_risk_inr)


def test_inject_fault_flips_exactly_one_and_is_rejected():
    claims = engine_claims("V001", apply_levers(build_base("V001")))
    injected = inject_fault(claims)
    assert [c.origin for c in injected].count("injected_test") == 1
    summary = verify_all(injected)
    assert summary.rejected == 1
    bad = next(c for c in summary.claims if c.status == "rejected")
    assert bad.reason.startswith("Injected test:")
    assert claims[0].origin == "engine"  # input not mutated


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "₹0"), (999, "₹999"), (1000, "₹1,000"), (123456, "₹1,23,456"), (1234567, "₹12,34,567"), (199334.4, "₹1,99,334")],
)
def test_fmt_inr_lakh_grouping(value, text):
    assert fmt_inr(value) == text


def test_data_dir_is_real():
    assert (settings.data_dir / SHEET).exists()


@pytest.mark.parametrize("metric", ["demand_score", "overlap"])
def test_ratio_metrics_reject_a_wrong_value_by_0_1(metric):
    true = compute_metric("V001", metric, "V001:HP-D01")
    assert METRIC_UNITS[metric] == "ratio" and TOL["ratio"] == 0.005
    assert verify_claim(engine_claim(true, metric=metric, unit="ratio")).status == "verified"
    out = verify_claim(engine_claim(true + 0.1, metric=metric, unit="ratio"))
    assert out.status == "rejected" and "recomputed" in out.reason


def test_fit_score_keeps_loose_0_100_tolerance():
    assert METRIC_UNITS["fit_score"] == "score" and TOL["score"] == 0.5


def test_inject_fault_can_flip_a_ratio_claim():
    claims = engine_claims("V001", apply_levers(build_base("V001")))
    injected = inject_fault(claims, metric="demand_score")
    flipped = [c for c in injected if c.origin == "injected_test"]
    assert len(flipped) == 1 and flipped[0].metric == "demand_score" and flipped[0].unit == "ratio"
    assert verify_all(injected).rejected == 1
    assert {c.unit for c in claims if c.metric in {"demand_score", "overlap"}} == {"ratio"}


@pytest.mark.parametrize(("row", "sku", "raw", "value"), [(2, "HP-D01", "Rs. 956.50", 956.5), (5, "HP-D04", "INR 874", 874)])
def test_model_extraction_verified_against_messy_cost_cell(row, sku, raw, value):
    ev = Evidence(row=row, header="Cost to Us", raw_value="ignored", parser_version="1.0", sha256=file_sha256(SHEET))

    def claim(v):
        return Claim(
            id="c", text=f"{sku} cost", value=v, metric="cost", unit="inr", sku_key=f"V001:{sku}",
            source_ref=SourceRef(file=SHEET, key=f"V001:{sku}", column="Cost to Us"),
            evidence=ev, origin="model_extraction",
        )  # fmt: skip

    ok = verify_claim(claim(value))
    assert ok.status == "verified" and ok.recomputed == value, raw
    assert verify_claim(claim(value + 50)).status == "rejected"
