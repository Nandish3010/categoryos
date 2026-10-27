"""Run: catalog QC / fix queue for the live listings of existing vendors (E001-E006)."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.main import app
from app.ops import api as ops_api
from app.ops.catalog_qc import data as cdata
from app.ops.catalog_qc import detect, fixes, outbox, queue, score
from app.ops.catalog_qc.detect import Ctx
from app.ops.catalog_qc.verify import verify_catalog_claim
from app.ops.data import load as load_ops
from app.schemas import Claim

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fresh():
    ops_api.reset()
    yield
    ops_api.reset()
    policy.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def gen(inject: bool = False) -> dict:
    return asyncio.run(queue.generate(inject))


def rows_of(result: dict, kind: str) -> dict[str, dict]:
    return {r["listing_id"]: r for r in result["rows"] if r["type"] == kind}


def typed(body: dict) -> None:
    assert all(body.get(k) for k in ("code", "problem", "cause", "fix"))


def ctx_for() -> Ctx:
    ops = load_ops()
    return Ctx(cdata.load(), ops, ops.as_of)


# ---------- data ----------


def test_generator_is_deterministic_and_covers_the_vendors():
    spec = importlib.util.spec_from_file_location("gen_catalog", ROOT / "data" / "generate_catalog_live.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_catalog"] = mod
    spec.loader.exec_module(mod)
    a, _ = mod.build()
    b, _ = mod.build()
    assert a == b and mod.SEED == 42
    assert {x["vendor_id"] for x in a} == {f"E00{i}" for i in range(1, 7)}
    on_disk = cdata.load()
    assert [x.listing_id for x in on_disk.listings] == [x["listing_id"] for x in a]


def test_latest_price_ignores_a_future_dated_list():
    d = cdata.load()
    assert d.latest_price("GW-04", load_ops().as_of).mrp == 199
    assert d.latest_price("BK-02", load_ops().as_of).mrp == 1100  # not the old 1050


# ---------- one test per detector ----------


def test_title_too_long_and_missing_attributes():
    r = gen()
    assert set(rows_of(r, "title_too_long")) == {"L-BK-01"}
    assert rows_of(r, "title_too_long")["L-BK-01"]["detail"]["chars"] > policy.get().catalog.title_max_chars
    miss = rows_of(r, "title_missing_attributes")
    assert miss["L-TW-01"]["detail"]["missing"] == ["brand", "pack"]


def test_missing_required_attributes_come_from_the_playbook():
    r = gen()
    miss = rows_of(r, "missing_attribute")
    assert set(miss["L-BK-04"]["detail"]["missing"]) == {"life_stage", "breed_size", "grain_free"}
    assert miss["L-TW-03"]["detail"]["missing"] == ["material"]
    policy.save_overrides({"catalog": {"required_attributes": {"default": ["pack", "mrp", "brand_origin"]}}})
    assert "L-GW-01" in rows_of(gen(), "missing_attribute")  # grooming falls to the default row


def test_banned_claims_use_the_claim_rules():
    r = gen()
    banned = rows_of(r, "banned_claim")
    assert set(banned) == {"L-BK-01", "L-PL-04", "L-GW-02", "L-GW-05"}
    assert {h["rule"] for h in banned["L-PL-04"]["detail"]["hits"]} >= {"medical_claim", "unverifiable_superlative", "unsubstantiated_claim"}
    assert banned["L-GW-05"]["severity"] == "high"


def test_mrp_and_pack_mismatch_use_the_latest_price_list():
    r = gen()
    mrp = rows_of(r, "mrp_mismatch")
    assert set(mrp) == {"L-BK-02", "L-LT-04"}
    assert mrp["L-BK-02"]["detail"]["price_list_mrp"] == 1100 and mrp["L-LT-04"]["detail"]["label_mrp"] == 449  # the label agrees with the list
    pack = rows_of(r, "pack_mismatch")
    assert set(pack) == {"L-BK-03", "L-LT-02"} and pack["L-BK-03"]["detail"]["price_list_pack"] == "1 kg"


def test_near_duplicates_use_the_overlap_measure_and_the_threshold():
    r = gen()
    dups = rows_of(r, "duplicate_listing")
    assert set(dups) == {"L-BK-06-B", "L-TW-06-B"} and dups["L-BK-06-B"]["detail"]["duplicate_of"] == "L-BK-06"
    policy.save_overrides({"catalog_qc": {"near_duplicate_threshold": 0.95}})
    assert rows_of(gen(), "duplicate_listing") == {}


def test_wrong_category_uses_the_taxonomy_classifier():
    wrong = rows_of(gen(), "wrong_category")
    assert set(wrong) == {"L-PL-03", "L-LT-03"}
    assert wrong["L-PL-03"]["detail"]["classified"] == ["cat dry food", "kitten"] and wrong["L-LT-03"]["detail"]["level"] == "subcategory"


def test_images_missing_and_low_resolution():
    r = gen()
    assert set(rows_of(r, "missing_image")) == {"L-PL-05"}
    assert set(rows_of(r, "low_res_image")) == {"L-PL-06", "L-TW-04"}
    policy.save_overrides({"catalog_qc": {"images": {"min_resolution_px": 1300}}})
    assert len(rows_of(gen(), "low_res_image")) > 2


def test_high_returns_citing_not_as_described_come_from_the_ops_returns():
    r = gen()
    hits = rows_of(r, "high_returns_not_as_described")
    assert {"L-PL-01", "L-LT-03", "L-NP-05"} <= set(hits)
    d = hits["L-PL-01"]["detail"]
    assert d["rate_pct"] >= policy.get().catalog_qc.returns.threshold_pct and d["returned"] >= 5
    policy.save_overrides({"catalog_qc": {"returns": {"threshold_pct": 5}}})
    assert rows_of(gen(), "high_returns_not_as_described") == {}


def test_expired_licence_with_and_without_a_renewal_on_file():
    exp = rows_of(gen(), "expired_licence")
    assert {f"L-NP-0{i}" for i in range(1, 7)} <= set(exp) and {"L-PL-01", "L-PL-02"} <= set(exp)
    assert exp["L-PL-01"]["detail"]["replacement"] == "FSSAI-E002-NEW" and exp["L-NP-03"]["detail"]["replacement"] is None
    assert "L-BK-01" not in exp  # E001's licence is valid


def test_label_vs_listing_comparison_reuses_the_doc_vision_reader():
    r = gen()
    mis = rows_of(r, "label_mismatch")
    assert set(mis) == {"L-BK-01", "L-PL-01"} and mis["L-BK-01"]["detail"]["label_value"] == "26%"
    assert r["labels_read"] == 3
    card = next(x for x in r["listings"] if x["listing_id"] == "L-BK-01")["label"]
    assert card["mismatches"] == 1 and {x["field"] for x in card["rows"]} >= {"protein_pct", "mrp"}
    assert any(c["origin"] == "vision_extraction" and c["status"] == "verified" for c in r["claims"])


def test_a_retired_or_held_listing_is_not_scanned_again():
    import dataclasses

    base = ctx_for()
    data = dataclasses.replace(base.data, listings=[dataclasses.replace(x, status="retired") if x.listing_id == "L-BK-02" else x for x in base.data.listings])
    ctx = Ctx(data, base.ops, base.as_of)
    assert not [i for i in detect.scan(ctx) if i["listing_id"] == "L-BK-02"]


def test_severities_come_from_the_playbook():
    policy.save_overrides({"catalog_qc": {"severities": {"title_too_long": "high"}}})
    assert rows_of(gen(), "title_too_long")["L-BK-01"]["severity"] == "high"


# ---------- priority score ----------


def test_priority_combines_gmv_severity_and_return_signal_with_playbook_weights():
    policy.save_overrides({"catalog_qc": {"priority_weights": {"gmv_at_risk": 1, "severity": 0, "return_rate": 0}}})
    sig = score.signals(500.0, 1000.0, "low", None)
    assert sig == {"gmv": 50.0, "severity": 33.33, "return_rate": 0.0} and score.priority(sig) == 50.0
    policy.save_overrides({"catalog_qc": {"priority_weights": {"gmv_at_risk": 0, "severity": 1, "return_rate": 0}}})
    assert score.priority(sig) == 33.33
    policy.save_overrides({"catalog_qc": {"priority_weights": {"gmv_at_risk": 0, "severity": 0, "return_rate": 1}}})
    at_threshold = score.signals(0, 1, "low", policy.get().catalog_qc.returns.threshold_pct)
    assert score.priority(at_threshold) == 50.0
    assert score.signals(0, 1, "low", 99)["return_rate"] == 100.0


def test_queue_is_sorted_by_score_and_ranked():
    rows = gen()["rows"]
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["id"] == "L-NP-03:expired_licence"  # the biggest listing with a high-severity issue


def test_changing_weights_reorders_the_queue():
    base = [r["id"] for r in gen()["rows"]]
    policy.save_overrides({"catalog_qc": {"priority_weights": {"gmv_at_risk": 0.0, "severity": 1, "return_rate": 0}}})
    other = gen()["rows"]
    assert [r["id"] for r in other] != base and other[0]["severity"] == "high"


def test_all_zero_weights_are_refused():
    with pytest.raises(Exception, match="cannot all be zero"):
        policy.save_overrides({"catalog_qc": {"priority_weights": {"gmv_at_risk": 0, "severity": 0, "return_rate": 0}}})


# ---------- deterministic fixes ----------


def fix(result: dict, listing: str, kind: str) -> dict:
    return result["fixes"][f"fix:{listing}:{kind}"]


def changes(f: dict) -> dict[str, tuple]:
    return {c["field"]: (c["before"], c["after"]) for c in f["changes"]}


def test_price_pack_and_category_come_from_the_sheets_and_the_classifier():
    r = gen()
    assert changes(fix(r, "L-BK-02", "price")) == {"mrp": (1050.0, 1100.0)}
    pack = changes(fix(r, "L-BK-03", "pack"))
    assert pack["pack_size"] == ("2 kg", "1 kg") and pack["attributes.pack_g"] == (2000, 1000) and pack["title"][1].endswith("1 kg")
    assert changes(fix(r, "L-PL-03", "category")) == {"category": ("dog dry food", "cat dry food"), "subcategory": ("adult", "kitten")}
    assert changes(fix(r, "L-LT-03", "category")) == {"subcategory": ("clumping", "tofu")}
    assert all(f["source"] == "deterministic" for f in (fix(r, "L-BK-02", "price"), fix(r, "L-BK-03", "pack")))


def test_licence_is_swapped_when_a_renewal_exists_and_the_listing_held_when_not():
    r = gen()
    assert changes(fix(r, "L-PL-02", "licence")) == {"fssai_number": ("FSSAI-E002-OLD", "FSSAI-E002-NEW")}
    assert changes(fix(r, "L-NP-03", "licence")) == {"status": ("active", "on_hold")}


def test_duplicates_are_retired_and_image_problems_become_vendor_requests():
    r = gen()
    assert changes(fix(r, "L-BK-06-B", "duplicate")) == {"status": ("active", "retired")}
    img = fix(r, "L-PL-05", "images")
    assert "Ask Purrline Foods" in img["title"] and "800" in img["title"]


def test_label_fix_matches_listing_to_label_and_uses_the_vision_claim():
    r = gen()
    f = fix(r, "L-BK-01", "label")
    c = changes(f)
    assert c["attributes.protein"] == ("28%", "26%") and "26% protein" in "".join(c["bullets"][1]) and f["source"] == "label"
    claim = next(x for x in r["claims"] if x["id"] == f["claim_ids"][0])
    assert claim["origin"] == "vision_extraction" and claim["status"] == "verified"


def test_fixes_of_one_listing_build_on_each_other():
    r = gen()
    assert changes(fix(r, "L-PL-01", "copy"))["bullets"][0][1] == "34% protein"  # the copy fix starts from the label fix's bullets


# ---------- model-written fixes ----------


def test_model_written_fixes_use_muse_spark_mock_fixture_and_the_row_only():
    r = gen()
    copy = fix(r, "L-BK-01", "copy")
    t = changes(copy)["title"]
    assert len(t[1]) <= policy.get().catalog.title_max_chars and "BEST" not in t[1] and copy["source"] == "model"
    assert changes(fix(r, "L-BK-04", "attributes"))["attributes.life_stage"] == (None, "senior")
    assert changes(fix(r, "L-TW-03", "attributes"))["attributes.material"] == (None, "feather and plastic")
    assert r["mode"] == "mock" and not r["degraded"]


def test_every_proposed_value_is_a_verified_claim_and_a_misread_pack_was_corrected():
    r = gen()
    assert r["verification"]["rejected"] == 0 and r["verification"]["unverifiable"] == 0
    assert all(f["status"] == "ready" and f["claim_ids"] for f in r["fixes"].values())
    assert r["corrected"] == ["fix:L-BK-01:copy:fact0"] and r["unresolved"] == []
    claim = next(c for c in r["claims"] if c["id"] == "fix:L-BK-01:copy:fact0")
    assert claim["value"] == 3000 and [a["value"] for a in claim["attempts"]] == [3, 3000]
    assert any(t["type"] == "self_correction" for t in r["trace"])


def test_model_rewrites_can_be_switched_off():
    policy.save_overrides({"catalog_qc": {"model_rewrites": False}})
    r = gen()
    assert not [f for f in r["fixes"].values() if f["source"] == "model"]
    stuck = next(x for x in r["rows"] if x["id"] == "L-BK-01:banned_claim")
    assert stuck["fix_id"] is None and "switched off" in stuck["no_fix_reason"]


def test_a_missing_model_fixture_degrades_to_deterministic_fixes(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "fixtures_dir", tmp_path)
    r = gen()
    assert r["degraded"] is True and "unavailable" in r["degraded_reason"]
    assert not [f for f in r["fixes"].values() if f["source"] == "model"] and fix(r, "L-BK-02", "price")["status"] == "ready"


# ---------- verifier checks on proposed fixes ----------


def claim_of(result: dict, cid: str) -> Claim:
    return Claim.model_validate(next(c for c in result["claims"] if c["id"] == cid)).model_copy(update={"status": "pending", "reason": None, "recomputed": None, "attempts": []})


@pytest.mark.parametrize(
    ("cid", "update", "reason"),
    [
        ("fix:L-BK-02:price:mrp", {"value": 1150.0}, "parses to 1100"),
        ("fix:L-BK-03:pack:qty", {"value": 2000.0}, "parses to 1000"),
        ("fix:L-PL-02:licence:days_left", {"value": 30.0}, "recomputed"),
        ("fix:L-BK-06-B:duplicate:similarity", {"value": 0.4}, "recomputed"),
        ("fix:L-PL-05:images:min_px", {"value": 600.0}, "recomputed"),
    ],
)
def test_the_verifier_rejects_a_wrong_deterministic_value(cid, update, reason):
    r = gen()
    bad = verify_catalog_claim(claim_of(r, cid).model_copy(update=update))
    assert bad.status == "rejected" and reason in bad.reason
    assert verify_catalog_claim(claim_of(r, cid)).status == "verified"


def with_text(c: Claim, text: str) -> Claim:
    return c.model_copy(update={"evidence": c.evidence.model_copy(update={"raw_value": text})})


def test_the_verifier_checks_model_written_text():
    r = gen()
    title = with_text(claim_of(r, "fix:L-BK-01:copy:title_chars"), "x" * 120).model_copy(update={"value": 120.0})
    assert "limit is 80" in verify_catalog_claim(title).reason
    banned = with_text(claim_of(r, "fix:L-BK-01:copy:banned"), "Boosts immunity | the best food")
    assert verify_catalog_claim(banned).status == "rejected" and "Boosts immunity" in verify_catalog_claim(banned).reason
    nums = with_text(claim_of(r, "fix:L-BK-01:copy:numbers"), "Barkley & Co Adult Dry Dog Food 7 kg | 99% protein")
    assert "99" in verify_catalog_claim(nums).reason
    req = with_text(claim_of(r, "fix:L-TW-01:copy:title_required"), "Rope Tug Toy")
    assert "brand and pack" in verify_catalog_claim(req).reason


def test_the_verifier_checks_attribute_quotes_against_the_listing():
    r = gen()
    c = claim_of(r, "fix:L-BK-04:attributes:life_stage")
    assert verify_catalog_claim(with_text(c, "a made-up quote")).status == "rejected"
    off = c.model_copy(update={"evidence": c.evidence.model_copy(update={"normalized_value": "puppy"})})
    assert "does not state" in verify_catalog_claim(off).reason


def test_a_label_reading_is_bound_to_the_pixels_and_the_second_read():
    r = gen()
    c = claim_of(r, next(x["claim_ids"][0] for x in r["fixes"].values() if x["id"] == "fix:L-BK-01:label"))
    assert verify_catalog_claim(c).status == "verified"
    moved = c.model_copy(update={"evidence": c.evidence.model_copy(update={"bbox": [0.0, 0.0, 0.2, 0.05]})})
    assert "crop hash differs" in verify_catalog_claim(moved).reason
    flipped = c.model_copy(update={"evidence": c.evidence.model_copy(update={"reread_value": "28.0 %"})})
    assert verify_catalog_claim(flipped).status == "rejected"


def test_a_source_file_changed_after_the_claim_is_rejected():
    r = gen()
    c = claim_of(r, "fix:L-BK-02:price:mrp")
    stale = c.model_copy(update={"evidence": c.evidence.model_copy(update={"sha256": "0" * 64})})
    assert "source changed" in verify_catalog_claim(stale).reason


def test_unknown_catalog_metric_is_unverifiable():
    c = claim_of(gen(), "fix:L-BK-02:price:mrp").model_copy(update={"metric": "qc_made_up"})
    assert verify_catalog_claim(c).status == "unverifiable"


def test_inject_makes_the_verifier_block_a_fix():
    r = gen(inject=True)
    blocked = [f for f in r["fixes"].values() if f["status"] == "blocked"]
    assert len(blocked) == 1 and "Injected test" in blocked[0]["reason"] and r["verification"]["rejected"] == 1


# ---------- outbox: approve, reject, bulk limits ----------


def test_outbox_is_simulated_and_a_fix_is_decided_once():
    r = gen()
    fx = r["fixes"]
    up = outbox.approve(fx["fix:L-BK-02:price"], fx)
    assert up["simulated"] is True and up["status"] == "applied_simulated" and up["changes"][0]["after"] == 1100.0
    with pytest.raises(Exception) as e:
        outbox.approve(fx["fix:L-BK-02:price"], fx)
    assert e.value.code == "catalog_fix_not_pending"


def test_an_unverified_fix_cannot_be_approved_one_by_one():
    fx = gen(inject=True)["fixes"]
    bad = next(f for f in fx.values() if f["status"] == "blocked")
    with pytest.raises(Exception) as e:
        outbox.approve(bad, fx)
    assert e.value.code == "catalog_fix_unverified"
    assert outbox.reject(bad)["status"] == "rejected"


def test_merged_update_applies_fixes_of_a_listing_in_order():
    fx = gen()["fixes"]
    outbox.approve(fx["fix:L-PL-01:licence"], fx)
    up = outbox.approve(fx["fix:L-PL-01:label"], fx)
    assert up["fix_ids"] == ["fix:L-PL-01:licence", "fix:L-PL-01:label"] and {c["field"] for c in up["changes"]} >= {"fssai_number", "attributes.protein"}


def test_bulk_approve_is_capped_by_the_playbook_and_checked_as_a_whole():
    fx = gen()["fixes"]
    ids = list(fx)
    policy.save_overrides({"catalog_qc": {"bulk_approve_limit": 3}})
    with pytest.raises(Exception) as e:
        outbox.bulk_approve(fx, ids[:4])
    assert e.value.code == "bulk_limit_exceeded" and e.value.limit == 3
    assert outbox.updates() == [] and outbox.decision(ids[0]) is None  # nothing was applied
    out = outbox.bulk_approve(fx, ids[:3])
    assert len(out["approved"]) == 3 and out["simulated"] is True


def test_bulk_approve_skips_decided_and_unverified_fixes_and_refuses_bad_selections():
    r = gen(inject=True)
    fx = r["fixes"]
    bad = next(f["id"] for f in fx.values() if f["status"] == "blocked")
    good = next(f["id"] for f in fx.values() if f["status"] == "ready")
    outbox.reject(fx[good])
    out = outbox.bulk_approve(fx, [bad, good, bad])
    assert out["approved"] == [] and {s["fix_id"] for s in out["skipped"]} == {bad, good}
    with pytest.raises(Exception) as e:
        outbox.bulk_approve(fx, [])
    assert e.value.code == "empty_selection"
    with pytest.raises(Exception) as e:
        outbox.bulk_approve(fx, ["fix:nope:price"])
    assert e.value.code == "unknown_catalog_fix"


# ---------- API ----------


def test_queue_endpoint(client):
    out = client.get("/api/ops/catalog").json()
    assert out["mode"] == "mock" and out["simulated"] is True and out["limits"]["bulk_approve"] == 25
    s = out["summary"]
    assert s["fixes_ready"] == len([f for f in out["fixes"].values() if f["decision"] == "pending"]) and s["minutes_per_listing"] == 12.0
    assert s["minutes_saved"] == s["listings_ready"] * 12 and s["baseline_status"] == "research_estimate"
    assert out["impact_coverage"]["module"] == "catalog_qc_queue" and out["impact_coverage"]["status"] == "shipped"
    lst = next(x for x in out["listings"] if x["listing_id"] == "L-BK-02")
    assert lst["before"]["mrp"] == 1050.0 and lst["after"]["mrp"] == 1100.0
    assert {v["id"] for v in out["vendors"]} == {f"E00{i}" for i in range(1, 7)} and "mrp_mismatch" in out["issue_types"]


def test_approve_reject_and_counter_update(client):
    before = client.get("/api/ops/catalog").json()["summary"]
    r = client.post("/api/ops/catalog/fixes/fix:L-BK-02:price/approve", json={})
    assert r.status_code == 200 and r.json()["simulated"] is True and r.json()["update"]["status"] == "applied_simulated"
    assert client.post("/api/ops/catalog/fixes/fix:L-BK-02:price/approve", json={}).status_code == 409
    assert client.post("/api/ops/catalog/fixes/fix:L-LT-04:price/reject", json={"note": "keep"}).json()["status"] == "rejected"
    after = client.get("/api/ops/catalog").json()
    assert after["summary"]["fixes_ready"] == before["fixes_ready"] - 2 and after["summary"]["fixes_approved"] == 1
    assert after["fixes"]["fix:L-BK-02:price"]["decision"] == "approved"
    assert client.get("/api/ops/catalog/outbox").json()["count"] == 1


def test_bulk_endpoints_and_limit(client):
    ids = list(client.get("/api/ops/catalog").json()["fixes"])
    over = client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": ids[:30]})
    assert over.status_code == 409 and over.json()["code"] == "bulk_limit_exceeded"
    typed(over.json())
    ok = client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": ids[:5]}).json()
    assert len(ok["approved"]) == 5 and ok["simulated"] is True
    again = client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": ids[:2]}).json()
    assert again["approved"] == [] and len(again["skipped"]) == 2
    rej = client.post("/api/ops/catalog/bulk-reject", json={"fix_ids": ids[5:7]}).json()
    assert len(rej["rejected"]) == 2
    empty = client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": []})
    assert empty.status_code == 422 and empty.json()["code"] == "empty_selection"


def test_typed_errors(client):
    for method, path, body in [
        ("post", "/api/ops/catalog/fixes/fix:nope:price/approve", {}),
        ("post", "/api/ops/catalog/fixes/fix:nope:price/reject", {}),
        ("post", "/api/ops/catalog/bulk-approve", {"fix_ids": ["fix:nope:price"]}),
        ("get", "/api/ops/catalog/labels/passwd", None),
    ]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, path
        typed(r.json())


def test_label_images_are_served_only_from_the_manifest(client):
    r = client.get("/api/ops/catalog/labels/label_BK-01.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/api/ops/catalog/labels/manifest.json").status_code == 404


def test_inject_endpoint_shows_a_blocked_fix_and_it_cannot_be_approved(client):
    out = client.get("/api/ops/catalog?inject=1").json()
    blocked = [f for f in out["fixes"].values() if f["decision"] == "blocked"]
    assert len(blocked) == 1 and out["summary"]["fixes_blocked"] == 1
    r = client.post(f"/api/ops/catalog/fixes/{blocked[0]['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["code"] == "catalog_fix_unverified"


def test_ops_reset_clears_the_catalog_outbox(client):
    client.post("/api/ops/catalog/fixes/fix:L-BK-02:price/approve", json={})
    assert client.get("/api/ops/catalog/outbox").json()["count"] == 1
    ops_api.reset()
    assert client.get("/api/ops/catalog/outbox").json()["count"] == 0


# ---------- playbook ----------


def test_playbook_section_is_registered_and_renders_in_the_rules_hints():
    qc = policy.get().catalog_qc
    assert qc.bulk_approve_limit == 25 and qc.near_duplicate_threshold == 0.8 and qc.images.min_resolution_px == 800
    assert qc.severities.expired_licence == "high" and qc.title_required == ["brand", "pack"]
    hints = policy.schema_hints()
    for path in ("catalog_qc.severities.banned_claim", "catalog_qc.priority_weights.gmv_at_risk", "catalog_qc.bulk_approve_limit",
                 "catalog_qc.near_duplicate_threshold", "catalog_qc.returns.threshold_pct", "catalog_qc.images.min_resolution_px"):
        assert hints[path]["label"] and hints[path]["used_in"] == ["ops_catalog"]
    mod = policy.get().impact.modules["catalog_qc_queue"]
    assert mod.status == "shipped"
    assert any(c.module == "catalog_qc_queue" and c.task == "catalog_create_qc" and c.in_scope_pct == 70 for c in policy.get().impact.coverage)


def test_title_required_and_bad_values_are_validated():
    policy.save_overrides({"catalog_qc": {"title_required": ["brand"]}})
    assert rows_of(gen(), "title_missing_attributes")["L-TW-01"]["detail"]["missing"] == ["brand"]
    with pytest.raises(Exception, match="unknown title requirement"):
        policy.save_overrides({"catalog_qc": {"title_required": ["colour"]}})


def test_bulk_limit_knob_is_what_the_api_enforces(client):
    policy.save_overrides({"catalog_qc": {"bulk_approve_limit": 1}})
    ids = list(client.get("/api/ops/catalog").json()["fixes"])
    assert client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": ids[:2]}).status_code == 409
    assert client.post("/api/ops/catalog/bulk-approve", json={"fix_ids": ids[:1]}).status_code == 200


def test_apply_changes_sets_attributes_and_fields():
    state = {"title": "a", "attributes": {"x": 1}, "mrp": 1}
    out = fixes.apply_changes(state, [fixes.change("attributes.y", None, 2), fixes.change("mrp", 1, 3)])
    assert out == {"title": "a", "attributes": {"x": 1, "y": 2}, "mrp": 3} and state["mrp"] == 1
