import asyncio

import pytest

from app import tools
from app.agents import decide, screen
from app.agents.context import RunContext, Sequencer
from app.metrics import apply_levers, build_base

TODAY = "2026-10-27"


def run_agent(fn, vendor_id, **kw):
    ctx = RunContext("run_test", vendor_id, TODAY, Sequencer())
    result = asyncio.run(fn(ctx, **kw))
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait())
    return result, events


# ---------- Screen ----------


@pytest.mark.parametrize("vendor_id", ["V001", "V002", "V003"])
def test_screen_passes_clean_vendors(vendor_id):
    result, events = run_agent(screen.run, vendor_id)
    assert result.stage == "intake" and result.status == "done" and result.locked_reason is None
    assert result.data["decision"] == "pass" and result.data["injection_detected"] is False
    assert result.data["guards"] == []
    assert not result.needs_approval
    # deterministic doc check comes first, then the tool steps, then the model call
    kinds = [(e.type, e.payload.get("tool")) for e in events]
    assert kinds[0] == ("tool_call", "check_documents") and events[0].payload["deterministic"] is True
    assert ("tool_call", "get_application") in kinds and kinds[-1][0] == "model_call"


def test_screen_fails_v004_with_injection_and_expired_fssai():
    result, _ = run_agent(screen.run, "V004")
    assert result.status == "failed" and result.locked_reason
    assert result.data["decision"] == "fail" and result.data["injection_detected"] is True
    flag_types = {f["type"] for f in result.data["risk_flags"]}
    assert {"prompt_injection", "medical_claim", "expired_document"} <= flag_types
    assert any("FSSAI" in r for r in result.data["reasons"])
    assert result.data["documents"]["blocking"] is True


def test_screen_guard_overrides_a_model_that_passes_a_bad_vendor(monkeypatch):
    """Deterministic backstop: even if the model said pass, blocking documents and injection text fail the vendor."""
    from app import llm
    from app.schemas import ScreenFinal

    real = llm.run_tools

    async def lenient(*a, **k):
        res = await real(*a, **k)
        res.parsed = ScreenFinal(injection_detected=False, decision="pass")
        return res

    monkeypatch.setattr(llm, "run_tools", lenient)
    result, _ = run_agent(screen.run, "V004")
    assert result.status == "failed" and result.data["injection_detected"] is True
    assert "decision forced to fail by deterministic guard" in result.data["guards"]
    assert "injection_detected set by deterministic scan" in result.data["guards"]


def test_injection_scan_finds_only_v004():
    assert screen.scan_injection("V004")
    for vendor_id in ("V001", "V002", "V003"):
        assert screen.scan_injection(vendor_id) == []


# ---------- Decide ----------


def rejected_extractions(result):
    return [c for c in result.claims if c.origin == "model_extraction" and c.status == "rejected"]


def test_decide_v001_catches_the_transposed_cost_and_the_agent_corrects_it():
    """The planted mistake (₹965.50 for a cell that says Rs. 956.50) is caught, the agent is told, and the corrected value
    replaces it in the narrative. Nothing is struck."""
    result, events = run_agent(decide.run, "V001")
    assert result.stage == "research" and result.status == "review" and result.needs_approval
    assert rejected_extractions(result) == []
    claim = next(c for c in result.claims if c.id == "V001:HP-D01:cost:extracted")
    assert claim.status == "verified" and claim.value == 956.5 and claim.recomputed == 956.5
    assert [(a.attempt, a.value, a.status) for a in claim.attempts] == [(0, 965.5, "rejected"), (1, 956.5, "verified")]
    assert "Rs. 956.50" in claim.attempts[0].reason
    why = next(r["why"] for r in result.data["rationale_per_sku"] if r["code"] == "HP-D01")
    assert "₹956.50" in why and "965.5" not in why and "Margin 35.8%" in why
    assert result.data["struck"] == []
    assert result.data["self_correction"] == {"max": 2, "corrected": [claim.id], "unresolved": []}
    ex = next(e for e in result.data["extractions"] if e["claim_id"] == claim.id)
    assert ex["value"] == 956.5 and ex["original_value"] == 965.5 and ex["status"] == "verified"
    assert result.data["verification"]["rejected"] == 0
    assert result.data["verification"]["verified"] == result.data["verification"]["total"]
    # the trace tells the story in order
    story = [e.type for e in events if e.type in {"claim_rejected", "self_correction", "claim_verified", "claim_unresolved"}]
    assert story == ["claim_rejected", "self_correction", "claim_verified"]
    fb = next(e for e in events if e.type == "self_correction").payload["feedback"][0]
    assert fb.startswith("Claim V001:HP-D01:cost:extracted rejected: you said ₹965.50") and fb.endswith("Re-read and correct.")
    checked = [e for e in events if e.type == "claim_checked"]
    assert len(checked) == len(result.claims)


def test_decide_with_self_correction_off_keeps_the_old_strike_behaviour():
    from app import policy

    policy.save_overrides({"verifier": {"max_self_corrections": 0}})
    try:
        result, events = run_agent(decide.run, "V001")
    finally:
        policy.reset()
    bad = rejected_extractions(result)
    assert len(bad) == 1 and bad[0].value == 965.5 and bad[0].recomputed == 956.5
    why = next(r["why"] for r in result.data["rationale_per_sku"] if r["code"] == "HP-D01")
    assert "965.5" not in why and "Margin 35.8%" in why
    struck = result.data["struck"]
    assert len(struck) == 1 and "₹965.50" in struck[0]["sentence"] and struck[0]["where"] == "rationale:HP-D01"
    assert struck[0]["claimed_value"] == 965.5 and struck[0]["sheet_value"] == 956.5
    assert [e.type for e in events if e.type in {"claim_rejected", "self_correction", "claim_verified", "claim_unresolved"}] == [
        "claim_rejected",
        "claim_unresolved",
    ]
    assert result.data["verification"]["rejected"] == 1


@pytest.mark.parametrize("vendor_id", ["V002", "V003", "V004"])
def test_decide_other_vendors_have_no_rejected_claims(vendor_id):
    result, _ = run_agent(decide.run, vendor_id)
    assert rejected_extractions(result) == [] and result.data["struck"] == []
    assert result.data["verification"]["rejected"] == 0


def test_decide_v002_counter_offer_terms_from_the_call():
    result, _ = run_agent(decide.run, "V002")
    terms = {(t["term"], t.get("sku_code")): t for t in result.data["counter_offer"]["terms"]}
    assert terms[("payment_terms_days", None)]["fallback"] == "30"
    assert terms[("moq_units", None)]["ask"] == "500"
    assert terms[("marketing_support_inr", None)]["ask"] == "50,000"
    required = {s.code: s.required_cost for s in apply_levers(build_base("V002")).skus if s.verdict == "negotiate"}
    for code in required:
        assert ("cost_price", code) in terms
    assert result.data["counter_offer"]["email_draft"].startswith("Hi Priya")
    assert {"payment_terms_days", "moq_units", "margin_pct"} <= {t for t, _ in terms}


def test_decide_carries_hashes_and_engine_claims():
    result, events = run_agent(decide.run, "V001")
    lever = apply_levers(build_base("V001"))
    assert result.metrics_hash == result.narrative_hash == lever.metrics_hash
    assert any(c.origin == "engine" and c.metric == "margin_pct" for c in result.claims)
    assert [e.seq for e in events] == sorted(e.seq for e in events) and len({e.seq for e in events}) == len(events)
    assert result.data["lever"] == {"target_margin_pct_offset": 0.0, "moq": 150}


def test_decide_replan_recomputes_verdict_dependent_content_from_metrics():
    result, _ = run_agent(decide.run, "V002", offset=-20.0, moq=300, replan=True)
    lever = apply_levers(build_base("V002"), -20.0, 300)
    assert lever.metrics_hash != apply_levers(build_base("V002")).metrics_hash
    assert result.narrative_hash == lever.metrics_hash and result.data["replanned"] is True
    assert {r["code"]: r["verdict"] for r in result.data["rationale_per_sku"]} == {s.code: s.verdict for s in lever.skus}
    assert result.data["verdict_corrections"], "lowering the target must flip at least one fixture verdict"
    assert "-20 pp" in result.data["headline"] and "MOQ 300" in result.data["headline"]
    negotiable = {s.code for s in lever.skus if s.verdict == "negotiate"}
    assert {t["sku_code"] for t in result.data["counter_offer"]["terms"] if t.get("sku_code")} <= negotiable


def test_reconcile_corrects_a_model_verdict_that_disagrees_with_the_engine():
    lever = apply_levers(build_base("V001"))
    narrative = {
        "headline": "h",
        "rationale_per_sku": [{"code": "HP-D03", "verdict": "list", "why": "Looks great."}],
        "counter_offer": {"terms": [{"term": "cost_price", "sku_code": "HP-D01"}, {"term": "moq_units"}], "email_draft": ""},
    }
    corrections = decide.reconcile(narrative, lever, regenerate_headline=False)
    row = next(r for r in narrative["rationale_per_sku"] if r["code"] == "HP-D03")
    assert row["verdict"] == "reject" and "Demand" in row["why"]
    assert len(narrative["rationale_per_sku"]) == 12
    assert {"code": "HP-D03", "kind": "verdict", "model_verdict": "list", "engine_verdict": "reject"} in corrections
    assert [t["term"] for t in narrative["counter_offer"]["terms"]] == ["moq_units"]  # HP-D01 is not negotiable


def test_extraction_citing_another_skus_row_is_rejected(monkeypatch):
    """The cell exists and parses, but it belongs to a different SKU: still wrong."""
    from app import llm

    real = llm.run_tools

    async def wrong_row(*a, **k):
        res = await real(*a, **k)
        res.parsed.extractions[1] = res.parsed.extractions[1].model_copy(update={"row": 2, "value": 956.5})  # HP-D02 -> HP-D01's cell
        return res

    monkeypatch.setattr(llm, "run_tools", wrong_row)
    result, _ = run_agent(decide.run, "V001")
    reasons = {c.sku_key: c.reason for c in rejected_extractions(result)}
    assert "row 2 is not HP-D02's row" in reasons["V001:HP-D02"]


def test_tools_offered_to_decide_include_metrics():
    assert "get_metrics" in tools.DECIDE_TOOLS and "get_metrics" not in tools.SCREEN_TOOLS
