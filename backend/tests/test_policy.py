"""The playbook: load/merge/validate/reset, rules driving verdicts, prompts rendered from policy, the API."""

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import policy, prompts, prompts_exec, tools
from app.agents import negotiate, screen
from app.agents.context import RunContext, Sequencer
from app.config import settings
from app.errors import PolicyInvalid
from app.main import app
from app.metrics import apply_levers, build_base
from app.taxonomy import classify

client = TestClient(app)
EXAMPLES = Path(__file__).resolve().parents[2] / "config" / "examples"


def counts(vendor_id: str) -> dict[str, int]:
    return apply_levers(build_base(vendor_id)).summary.counts


# ---------- load / merge / validate / reset ----------


def test_defaults_load_and_hash_is_stable():
    assert policy.get().margins.categories["treats"].target_pct == 35
    assert policy.policy_hash() == policy.policy_hash() and len(policy.policy_hash()) == 16


def test_default_outcomes_for_the_four_vendors_are_unchanged():
    assert counts("V001") == {"list": 7, "negotiate": 0, "reject": 5, "needs_data": 0}
    assert counts("V002") == {"list": 0, "negotiate": 4, "reject": 6, "needs_data": 0}
    assert counts("V003")["list"] == 0


def test_save_merges_into_overrides_and_prunes_defaults():
    policy.save_overrides({"research": {"demand_min": 0.5}})
    assert policy.get().research.demand_min == 0.5 and policy.get().research.overlap_max == 0.6
    assert policy.overridden_paths() == ["research.demand_min"]
    policy.save_overrides({"research": {"demand_min": 0.4}})  # back to the default: nothing left to store
    assert policy.overridden_paths() == [] and not policy.local_path().exists()


def test_invalid_values_are_rejected_before_writing():
    with pytest.raises(PolicyInvalid) as exc:
        policy.save_overrides({"research": {"demand_min": 3}})
    assert exc.value.errors[0]["path"] == "research.demand_min" and exc.value.status == 422
    assert not policy.local_path().exists()
    with pytest.raises(PolicyInvalid):
        policy.save_overrides({"research": {"nonsense": 1}})
    with pytest.raises(PolicyInvalid):  # weights must sum to 1
        policy.save_overrides({"research": {"fit_weights": {"margin": 0.9}}})
    with pytest.raises(PolicyInvalid):  # a taxonomy category that margins does not know
        policy.save_overrides({"margins": {"categories": {"treats": None}}})


def test_tables_merge_by_key_and_null_deletes_a_row():
    policy.save_overrides({"margins": {"categories": {"treats": {"target_pct": 36}, "pet toys": {"target_pct": 41, "min_pct": 30}}}})
    cats = policy.get().margins.categories
    assert cats["treats"].target_pct == 36 and cats["treats"].min_pct == 28 and "pet toys" in cats
    policy.save_overrides({"margins": {"categories": {"pet toys": None}}})
    assert "pet toys" not in policy.get().margins.categories and policy.get().margins.categories["treats"].target_pct == 36
    policy.save_overrides({"onboarding": {"vendor_types": {"franchise": {"label": "Franchise", "target_offset_pp": 2}}}})
    assert "franchise" in policy.get().onboarding.vendor_types and "d2c_brand" in policy.get().onboarding.vendor_types
    policy.save_overrides({"screening": {"fail_on": ["blocking_document"]}})  # lists replace
    assert policy.get().screening.fail_on == ["blocking_document"]


def test_reset_one_path_one_section_and_everything():
    policy.save_overrides({"research": {"demand_min": 0.5, "overlap_max": 0.5}, "negotiation": {"moq_max_factor": 3}})
    policy.reset("research.demand_min")
    assert policy.overridden_paths() == ["negotiation.moq_max_factor", "research.overlap_max"]
    policy.reset("research")
    assert policy.overridden_paths() == ["negotiation.moq_max_factor"]
    policy.reset()
    assert policy.overridden_paths() == [] and policy.get().negotiation.moq_max_factor == 2.0


def test_replay_mode_ignores_local_overrides(monkeypatch):
    policy.save_overrides({"research": {"demand_min": 0.5}})
    monkeypatch.setattr(settings, "model_mode", "replay")
    assert policy.get().research.demand_min == 0.4


def test_schema_hints_cover_every_kind():
    hints = policy.schema_hints()
    assert hints["research.demand_min"] | {} and hints["research.demand_min"]["kind"] == "number"
    assert hints["research.demand_min"]["min"] == 0 and hints["research.demand_min"]["max"] == 1 and hints["research.demand_min"]["step"] == 0.05
    assert hints["screening.absent_document_counts_as_missing"]["kind"] == "bool"
    assert hints["research.below_min_margin_action"]["kind"] == "enum" and hints["research.below_min_margin_action"]["options"] == ["negotiate", "reject"]
    assert hints["onboarding.required_terms"]["kind"] == "string_list"
    assert hints["margins.categories"]["kind"] == "table" and hints["margins.categories"]["shape"] == "dict"
    assert hints["business.retailer"]["kind"] == "text"
    assert all({"label", "help", "kind", "used_in"} <= set(h) for h in hints.values())


# ---------- rules drive verdicts ----------


def test_demand_min_changes_verdicts():
    before = counts("V001")
    policy.save_overrides({"research": {"demand_min": 0.95}})
    after = counts("V001")
    assert after["reject"] > before["reject"] and after["list"] < before["list"]


def test_category_target_and_vendor_type_offset_change_verdicts():
    base = counts("V001")
    policy.save_overrides({"onboarding": {"vendor_types": {"d2c_brand": {"label": "D2C brand", "target_offset_pp": 30}}}})
    assert counts("V001")["list"] < base["list"] and counts("V001")["negotiate"] > 0
    lever = apply_levers(build_base("V001"))
    assert lever.skus[0].target_breakdown.vendor_type_pp == 30
    policy.reset()
    policy.save_overrides({"margins": {"brands": {"Highland Paws": {"target_offset_pp": 30}}}})
    assert apply_levers(build_base("V001")).skus[0].target_breakdown.brand_pp == 30


def test_target_breakdown_sums_to_target():
    sku = apply_levers(build_base("V002"), 2.0).skus[0]
    b = sku.target_breakdown
    assert b.lever_pp == 2 and sku.target_pct == pytest.approx((b.category_pct + b.vendor_type_pp + b.brand_pp + b.lever_pp) / 100, abs=1e-4)


def test_below_min_action_reject_makes_the_floor_bite():
    base = counts("V002")
    policy.save_overrides({"research": {"below_min_margin_action": "reject"}})
    assert counts("V002")["reject"] > base["reject"]


def test_negotiation_required_margin_honours_offsets_and_margin_ask():
    lever = apply_levers(build_base("V002"))
    short = [s for s in lever.skus if s.verdict == "negotiate"]
    assert negotiate.required_terms(lever, short, short, "V002")["margin_pct"] == 35
    policy.save_overrides({"onboarding": {"vendor_types": {"d2c_brand": {"label": "D2C brand", "target_offset_pp": 3}}}})
    lever = apply_levers(build_base("V002"), 2.0)
    short = [s for s in lever.skus if s.verdict == "negotiate"]
    assert negotiate.required_terms(lever, short, short, "V002")["margin_pct"] == 40
    policy.save_overrides({"negotiation": {"margin_ask": "min"}})
    assert negotiate.required_terms(lever, short, short, "V002")["margin_pct"] == 31


def test_returns_parser_accepts_both_styles():
    assert negotiate.return_days("defects reported within 7 days") == 7
    assert negotiate.return_days("Full credit for damaged stock; 60-day sell-through return window") == 60
    assert negotiate.return_days("no returns") is None
    assert negotiate.application_terms("V001")["returns"] == 60 and negotiate.application_terms("V002")["returns"] == 7


def test_absent_blocking_document_counts_as_missing_but_v003_is_unblocked():
    assert tools.check_documents("V003")["blocking"] is False  # FSSAI does not apply to toys and accessories
    policy.save_overrides({"screening": {"documents": [*[d.model_dump() for d in policy.get().screening.documents], {"type": "BIS", "blocking": True, "categories": ["toys"]}]}})
    docs = tools.check_documents("V003")
    assert docs["blocking"] is True and any(p["type"] == "BIS" and p["state"] == "missing" for p in docs["problems"])
    assert tools.check_documents("V001")["blocking"] is False
    policy.save_overrides({"screening": {"absent_document_counts_as_missing": False}})
    assert tools.check_documents("V003")["blocking"] is False


def run_screen(vendor_id):
    ctx = RunContext("run_test", vendor_id, "2026-10-27", Sequencer())
    return asyncio.run(screen.run(ctx))


def test_medical_claim_in_fail_on_fails_a_lenient_model(monkeypatch):
    from app import llm
    from app.schemas import ScreenFinal

    real = llm.run_tools

    async def lenient(*a, **k):
        res = await real(*a, **k)
        res.parsed = ScreenFinal(injection_detected=False, decision="pass")
        return res

    monkeypatch.setattr(llm, "run_tools", lenient)
    # take the other fail reasons away so only the medical-claim guard can fail V004
    policy.save_overrides({"screening": {"fail_on": ["medical_claim"]}})
    result = run_screen("V004")
    assert result.status == "failed" and any("medical claim" in r for r in result.data["reasons"])
    assert any(f["type"] == "medical_claim" for f in result.data["risk_flags"])
    policy.save_overrides({"screening": {"fail_on": ["blocking_document"], "injection_patterns": ["zzzz-never"]}})
    assert any("FSSAI" in r for r in run_screen("V004").data["reasons"])
    policy.save_overrides({"screening": {"fail_on": [], "injection_patterns": ["zzzz-never"]}})
    assert run_screen("V004").status == "done"
    assert run_screen("V001").status == "done"  # clean vendors never trip the claim guard


def test_claim_rules_are_scoped_by_category():
    assert {t for t, _, _ in screen.scan_claims("V004", {"medical_claim"})} == {"medical_claim"}
    rules = [r.model_dump() for r in policy.get().screening.claim_rules]
    rules[0]["categories"] = ["toys"]
    policy.save_overrides({"screening": {"claim_rules": rules}})
    assert screen.scan_claims("V004", {"medical_claim"}) == []


# ---------- prompts render the playbook ----------


def test_prompts_contain_policy_values():
    assert "at most 80 characters" in prompts_exec.copy_system()
    policy.save_overrides({"catalog": {"title_max_chars": 120, "bullets": {"min": 2, "max": 4}}, "business": {"retailer": "an online hardware store", "vertical": "hardware"}})
    text = prompts_exec.copy_system(["treats"])
    assert "at most 120 characters" in text and "2 to 4 short benefit lines" in text and "an online hardware store" in text
    assert "treats: life_stage, protein, pack_g, mrp" in text
    screen_text = prompts.screen_system()
    assert "hardware-category buying team" in screen_text and "cures arthritis" in screen_text and "pet" not in screen_text.lower().replace("competitor", "")
    assert "GST" in screen_text and "FSSAI" in screen_text
    policy.save_overrides({"launch": {"jbp_sections": ["Summary", "Plan"]}})
    assert "Summary, Plan" in prompts_exec.jbp_system()
    assert "pet" not in prompts_exec.classify_system().lower().replace("competitor", "") or "hardware" in prompts_exec.classify_system()


# ---------- verticals other than pet ----------


@pytest.mark.parametrize("name", ["beauty", "electronics"])
def test_example_playbooks_validate(name):
    doc = yaml.safe_load((EXAMPLES / f"{name}.yaml").read_text())
    assert policy.Policy.model_validate(doc).business.vertical == name


def test_non_pet_taxonomy_classifies_a_synthetic_row_set(monkeypatch):
    beauty = policy.Policy.model_validate(yaml.safe_load((EXAMPLES / "beauty.yaml").read_text()))
    monkeypatch.setattr(policy, "get", lambda: beauty)
    rows = {
        "Vitamin C Face Serum 30ml": ("skincare", "serums"),
        "Daily Sunscreen SPF 50": ("skincare", "sun care"),
        "Argan Hair Oil 100ml": ("haircare", "oils and serums"),
        "Anti-dandruff Shampoo": ("haircare", "shampoo"),
        "Matte Lipstick Ruby": ("makeup", "lips"),
        "Waterproof Kajal": ("makeup", "eyes"),
        "Eau de Parfum Noir": ("fragrance", "perfume"),
    }
    for name, (category, sub) in rows.items():
        got = classify(name)
        assert (got.category, got.subcategory) == (category, sub), name
    unknown = classify("Gift voucher")
    assert unknown.category == "skincare" and "unclassified" in unknown.flags
    elec = policy.Policy.model_validate(yaml.safe_load((EXAMPLES / "electronics.yaml").read_text()))
    monkeypatch.setattr(policy, "get", lambda: elec)
    assert classify("20W USB-C Fast Charger").category == "mobile accessories"
    assert classify("Bluetooth Neckband Earphones") .category == "audio"
    assert classify("Mechanical Keyboard").subcategory == "input devices"


def test_pet_segments_still_classify_by_species():
    assert classify("Kitten dry food 400g").category == "cat dry food"
    assert classify("Puppy kibble 1kg").category == "dog dry food"
    assert classify("Chicken gravy pouch", "for cats").category == "cat wet food"
    assert classify("Mystery item", hint={"species": "cat"}).category == "treats"


# ---------- API ----------


def test_get_policy_shape():
    body = client.get("/api/policy").json()
    assert set(body) == {"policy", "defaults", "overridden_paths", "hash", "editable", "schema_hints"}
    assert body["editable"] is True and body["overridden_paths"] == [] and body["policy"] == body["defaults"]
    assert client.get("/api/mode").json()["policy_hash"] == body["hash"]


def test_put_changes_hash_metrics_hash_and_caches():
    before_hash = client.get("/api/policy").json()["hash"]
    metrics_before = client.get("/api/vendors/V001/decide/metrics").json()
    res = client.put("/api/policy", json={"research": {"demand_min": 0.95}})
    assert res.status_code == 200 and res.json()["overridden_paths"] == ["research.demand_min"] and res.json()["hash"] != before_hash
    metrics_after = client.get("/api/vendors/V001/decide/metrics").json()
    assert metrics_after["metrics_hash"] != metrics_before["metrics_hash"]
    assert metrics_after["summary"]["counts"]["reject"] > metrics_before["summary"]["counts"]["reject"]
    reset = client.post("/api/policy/reset", json={"section": "research"})
    assert reset.status_code == 200 and reset.json()["overridden_paths"] == []
    assert client.get("/api/vendors/V001/decide/metrics").json()["metrics_hash"] == metrics_before["metrics_hash"]
    client.put("/api/policy", json={"research": {"demand_min": 0.9}})
    assert client.post("/api/policy/reset").json()["hash"] == before_hash


def test_put_invalid_is_422_with_path():
    res = client.put("/api/policy", json={"research": {"demand_min": 7}})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "policy_invalid" and body["path"] == "research.demand_min" and body["problem"] and body["cause"] and body["fix"]


def test_replay_is_read_only(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    assert client.get("/api/policy").json()["editable"] is False
    for res in (client.put("/api/policy", json={"research": {"demand_min": 0.5}}), client.post("/api/policy/reset", json={})):
        assert res.status_code == 403 and res.json()["code"] == "policy_read_only"


def test_demo_key_required_for_writes_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "demo_key", "k")
    denied = client.put("/api/policy", json={"research": {"demand_min": 0.5}})
    assert denied.status_code == 403 and denied.json()["code"] == "demo_key_required"
    assert client.put("/api/policy", json={"research": {"demand_min": 0.5}}, headers={"X-Demo-Key": "k"}).status_code == 200
    assert client.get("/api/policy").status_code == 200


def test_lever_bounds_come_from_the_playbook():
    assert client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=11").status_code == 422
    assert client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=11").json()["code"] == "lever_out_of_range"
    client.put("/api/policy", json={"levers": {"margin_offset": {"max": 15}}})
    assert client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=11").status_code == 200
    assert client.get("/api/vendors/V001/decide/metrics?moq=301").status_code == 422  # 2 x the proposed 150
