"""Mock end-to-end flow: run -> approve research -> negotiate + catalog -> approve catalog -> launch packet."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import media
from app.config import settings
from app.main import app

SETTLED = {"done", "review", "failed", "locked"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def stages_of(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()["stages"]


def wait_for(client, run_id, wanted, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        stages = stages_of(client, run_id)
        if all(stages[s]["status"] in SETTLED for s in wanted):
            return stages
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {wanted}: { {s: stages_of(client, run_id)[s]['status'] for s in wanted} }")


def start(client, vendor_id):
    run_id = client.post(f"/api/vendors/{vendor_id}/runs").json()["run_id"]
    stages = wait_for(client, run_id, ["intake", "research"])
    return run_id, stages


def approve(client, run_id, stage, stages):
    res = client.post(f"/api/runs/{run_id}/stages/{stage}/approve", json={"metrics_hash": stages[stage]["narrative_hash"]})
    assert res.status_code == 200, res.text
    return res.json()


def run_to_catalog(client, vendor_id):
    run_id, stages = start(client, vendor_id)
    approve(client, run_id, "research", stages)
    return run_id, wait_for(client, run_id, ["negotiate", "catalog"])


@pytest.mark.parametrize("vendor_id", ["V001", "V002", "V003"])
def test_full_mock_flow(client, vendor_id):
    run_id, stages = start(client, vendor_id)
    assert stages["shortlist"]["status"] == "review"
    approve(client, run_id, "research", stages)
    stages = wait_for(client, run_id, ["negotiate", "catalog"])
    assert stages["shortlist"]["status"] == "done"
    assert stages["negotiate"]["status"] == "done"
    assert stages["catalog"]["status"] == "review" and stages["catalog"]["needs_approval"] is True
    assert stages["catalog"]["metrics_hash"] == stages["catalog"]["narrative_hash"] == stages["research"]["metrics_hash"]
    for sid in ("marketing", "jbp", "po"):
        assert stages[sid]["status"] == "pending"
    approve(client, run_id, "catalog", stages)
    stages = wait_for(client, run_id, ["marketing", "jbp", "po"])
    assert stages["catalog"]["status"] == "done"
    assert stages["marketing"]["status"] == "done" and stages["jbp"]["status"] == "done"
    assert stages["po"]["status"] == "review" and stages["po"]["needs_approval"] is True
    approve(client, run_id, "po", stages)
    assert stages_of(client, run_id)["po"]["status"] == "done"
    # the event log carries one `done` per phase, each with its phase name
    events = all_events(client, run_id)
    phases = [e["payload"].get("phase") for e in events if e["type"] == "done"]
    assert phases == [None, "execute", "launch"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def all_events(client, run_id):
    """The stream ends at each `done`; resume with Last-Event-ID until only the synthetic tail is left."""
    events, last = [], 0
    while True:
        with client.stream("GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(last)}) as res:
            chunk = [json.loads(line[6:]) for line in res.iter_lines() if line.startswith("data: ")]
        chunk = [e for e in chunk if not e["payload"].get("interrupted")]
        if not chunk:
            return events
        events += chunk
        last = chunk[-1]["seq"]


def test_v001_negotiation_not_needed(client):
    _, stages = run_to_catalog(client, "V001")
    assert stages["negotiate"]["summary"] == "No negotiation needed"
    assert stages["negotiate"]["data"]["gap_table"] == []
    assert len(stages["catalog"]["data"]["skus"]) == 7


def test_v002_negotiation_gap_table_and_verified_quotes(client):
    _, stages = run_to_catalog(client, "V002")
    neg = stages["negotiate"]
    data = neg["data"]
    assert data["transcript_source"] == "canonical" and len(data["transcript"]["turns"]) == 22
    table = {r["term"]: r for r in data["gap_table"]}
    assert set(table) == {"margin_pct", "payment_days", "moq", "marketing_inr", "launch_discount_pct", "returns"}
    assert table["margin_pct"]["application"] == 17 and table["margin_pct"]["offered"] == 21
    assert table["margin_pct"]["required"] == 35 and table["margin_pct"]["gap"] == -14 and table["margin_pct"]["status"] == "gap"
    assert table["payment_days"]["required"] == 21 and table["payment_days"]["gap"] == 9 and table["payment_days"]["status"] == "met"
    assert table["moq"]["offered"] == 500 and table["moq"]["status"] == "gap"  # 500 > 2 x forecast units
    assert table["marketing_inr"]["offered"] == 50000 and table["marketing_inr"]["status"] == "met"
    assert table["launch_discount_pct"]["status"] == "met" and table["returns"]["status"] == "met"
    assert all(r["verification"] == "verified" for r in data["gap_table"])
    commits = [c for c in neg["claims"] if ":commit:" in c["id"]]
    assert len(commits) == 6 and all(c["status"] == "verified" and c["origin"] == "model_extraction" for c in commits)
    assert all(c["status"] == "verified" for c in neg["claims"])  # the deal evaluator's claims verify too
    assert {r["term"] for r in data["refusals"]} >= {"margin_pct", "sale_or_return"}
    assert all(r["quote_verified"] for r in data["refusals"])
    assert data["counter_offer"]["asks"] and "Priya" in data["counter_offer"]["email_draft"]
    assert data["verification"] == {"total": 6, "verified": 6, "rejected": 0, "unverifiable": 0}


def test_v003_has_no_transcript_so_negotiate_is_a_deterministic_gap_table(client):
    _, stages = run_to_catalog(client, "V003")
    data = stages["negotiate"]["data"]
    assert data["transcript"] is None and stages["negotiate"]["claims"] == []
    assert all(r["status"] == "not_stated" for r in data["gap_table"])
    assert len(stages["catalog"]["data"]["skus"]) == 4  # negotiate-only shortlist still gets a catalog


def test_v004_cannot_proceed(client):
    run_id, stages = start(client, "V004")
    assert stages["research"]["status"] == "locked"
    for stage in ("research", "catalog", "po"):
        res = client.post(f"/api/runs/{run_id}/stages/{stage}/approve", json={"metrics_hash": "x"})
        assert res.status_code == 409, stage
        if stage == "research":
            assert res.json()["code"] == "stage_locked" and res.json()["cause"]
    assert stages_of(client, run_id)["negotiate"]["status"] == "locked"


def test_approve_is_idempotent_and_does_not_rerun_phases(client):
    run_id, stages = start(client, "V002")
    approve(client, run_id, "research", stages)
    after = wait_for(client, run_id, ["negotiate", "catalog"])
    count = len(client.get(f"/api/runs/{run_id}").json()["stages"])
    approve(client, run_id, "research", after)
    time.sleep(0.2)
    again = stages_of(client, run_id)
    assert again["negotiate"] == after["negotiate"] and again["catalog"] == after["catalog"] and count == 8


def test_stale_catalog_approval_is_rejected(client):
    run_id, _ = run_to_catalog(client, "V002")
    res = client.post(f"/api/runs/{run_id}/stages/catalog/approve", json={"metrics_hash": "0" * 64})
    assert res.status_code == 409 and res.json()["code"] == "stale_approval"
    assert stages_of(client, run_id)["marketing"]["status"] == "pending"


def test_replan_after_approval_is_refused(client):
    run_id, stages = start(client, "V002")
    approve(client, run_id, "research", stages)
    wait_for(client, run_id, ["negotiate", "catalog"])
    res = client.post("/api/vendors/V002/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": 0, "moq": 300})
    assert res.status_code == 409


# ---------- catalog ----------


def test_catalog_contract_and_classifier_agreement(client):
    _, stages = run_to_catalog(client, "V001")
    data = stages["catalog"]["data"]
    skus = {s["code"]: s for s in data["skus"]}
    assert set(skus) == {"HP-D01", "HP-D02", "HP-D05", "HP-D06", "HP-D07", "HP-W02", "HP-W03"}
    sku = skus["HP-D01"]
    assert sku["raw_row"]["Cost to Us"] == "Rs. 956.50" and sku["normalized"]["cost"] == 956.5 and sku["normalized"]["pack_normalized"] == "1500g"
    assert len(sku["copy"]["title"]) <= 80 and 3 <= len(sku["copy"]["bullets"]) <= 5
    assert sku["copy"]["attributes"]["grain_free"] is True and sku["copy"]["attributes"]["fssai_license"] == "FSSAI-DEMO-0001"
    # 5 of 7 labels agree; the two that differ keep the taxonomy's label
    assert data["classifier_agreement_pct"] == 71.4
    assert skus["HP-D05"]["classification"]["agreement"] is False and skus["HP-D05"]["normalized"]["subcategory"] == "puppy"
    assert skus["HP-W03"]["classification"]["agreement"] is False and skus["HP-W03"]["normalized"]["subcategory"] == "gravy"
    assert skus["HP-D01"]["classification"]["agreement"] is True
    # compliance: the vendor claim "supports digestion" is caught; a blank shelf life is a label-info flag
    rules = {(f["rule"]) for f in skus["HP-W03"]["copy"]["compliance_flags"]}
    assert "unsubstantiated_claim" in rules
    assert any(f["rule"] == "missing_label_info" and "shelf life" in f["text"] for f in skus["HP-D07"]["copy"]["compliance_flags"])
    # attribute claims (mrp, pack) are verified against the sheet cells
    claims = {c["id"]: c for c in stages["catalog"]["claims"]}
    assert claims["V001:HP-D01:mrp:catalog"]["status"] == "verified" and claims["V001:HP-D01:pack_qty:catalog"]["status"] == "verified"
    assert all(c["origin"] in {"model_extraction", "vision_extraction"} for c in claims.values())
    assert {c["origin"] for c in claims.values() if c["id"].endswith(":catalog")} == {"model_extraction"}
    assert "HP-D07" in skus and "mrp" not in skus["HP-D07"]["copy"]["attributes"]  # the sheet has no MRP for it


def test_hero_skus_get_lifestyle_images_and_placeholders_are_labelled(client):
    _, stages = run_to_catalog(client, "V001")
    data = stages["catalog"]["data"]
    assert len(data["hero_skus"]) == 3 and data["image_mode"] == "placeholder"
    heroes = [s for s in data["skus"] if s["hero"]]
    assert {s["code"] for s in heroes} == set(data["hero_skus"])
    for s in data["skus"]:
        img = s["images"]
        assert img["image_source"] == "placeholder"
        assert img["packshot"] == f"/api/assets/V001/{s['code']}-packshot.png" and img["cutout"].endswith("-cutout.png")
        assert (img["lifestyle"] is not None) == s["hero"]
    for hero in heroes:
        for url in (hero["images"]["packshot"], hero["images"]["cutout"], hero["images"]["lifestyle"]):
            res = client.get(url)
            assert res.status_code == 200 and res.headers["content-type"] == "image/png"
            assert res.content[:8] == b"\x89PNG\r\n\x1a\n" and len(res.content) < 30_000


def test_cutout_unavailable_when_sam_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "sam_enabled", False)
    _, stages = run_to_catalog(client, "V002")
    for s in stages["catalog"]["data"]["skus"]:
        assert s["images"]["cutout"] == "unavailable" and s["images"]["cutout_note"] == "cutout unavailable"
        assert s["images"]["packshot"].endswith("-packshot.png")


def test_assets_route_is_path_safe(client):
    _, _ = run_to_catalog(client, "V001")
    ok = client.get("/api/assets/V001/HP-D01-packshot.png")
    assert ok.status_code == 200
    for bad in (
        "/api/assets/V001/..%2f..%2fetc%2fpasswd",
        "/api/assets/V001/%2e%2e%2fmanifest.json",
        "/api/assets/V001/manifest.json",
        "/api/assets/V001/..",
        "/api/assets/V001/HP-D01-packshot.png%00.txt",
        "/api/assets/V001/NOPE-packshot.png",
        "/api/assets/V001/HP-D01-other.png",
        "/api/assets/..%2fV001/HP-D01-packshot.png",
        "/api/assets/V999/HP-D01-packshot.png",
    ):
        res = client.get(bad)
        assert res.status_code in (404, 422), (bad, res.status_code)
        assert res.headers["content-type"].startswith("application/json") or res.status_code == 404
    assert client.get("/api/assets/V001/HP-D01-packshot.png%2e%2e").status_code == 404


def test_asset_route_makes_a_placeholder_on_demand_in_mock_mode(client):
    res = client.get("/api/assets/V002/MW-T01-packshot.png")
    assert res.status_code == 200 and res.content[:4] == b"\x89PNG"
    assert media.cached_source("V002", "MW-T01-packshot.png") == "placeholder"
    assert client.get("/api/assets/V002/campaign.png").status_code == 200


# ---------- launch ----------


def test_launch_packet_po_totals_are_verified(client):
    run_id, stages = run_to_catalog(client, "V002")
    approve(client, run_id, "catalog", stages)
    stages = wait_for(client, run_id, ["marketing", "jbp", "po"])
    po = stages["po"]["data"]
    assert po["moq_source"] == "negotiation" and sum(line["units"] for line in po["lines"]) == 500
    assert po["subtotal"] == round(sum(line["line_total"] for line in po["lines"]), 2)
    assert po["gst"] == round(po["subtotal"] * 0.18, 2) and po["grand_total"] == round(po["subtotal"] + po["gst"], 2)
    assert po["payment_days"] == 30 and po["terms_source"]["payment_days"] == "negotiation"
    claims = {c["metric"]: c for c in stages["po"]["claims"]}
    assert claims["po_total"]["status"] == "verified" and claims["po_grand_total"]["status"] == "verified"
    assert claims["po_total"]["value"] == po["subtotal"]
    steps = {s["step"]: s for s in po["timeline"]}
    assert [s["step"] for s in po["timeline"]] == ["raised", "confirmed", "shipped", "received"]
    assert steps["raised"]["planned_date"] == "2026-10-27" and steps["shipped"]["planned_date"] == "2026-11-01"
    assert steps["shipped"]["status"] == "delayed" and steps["shipped"]["delay_days"] == 3 and "alert" in steps["shipped"]
    assert sum(1 for s in po["timeline"] if "alert" in s) == 1 and po["alerts"]
    jbp = stages["jbp"]["data"]
    assert "Joint Business Plan" in jbp["markdown"] and jbp["investments"]["brand_funded_marketing_inr"] == 50000
    assert jbp["promo_calendar"] and jbp["targets"]["first_order_units"] == 500
    mk = stages["marketing"]["data"]
    assert mk["discount_ask"]["brand_funded_pct"] == 5 and mk["image"]["image_source"] == "placeholder"
    assert client.get(mk["image"]["url"]).status_code == 200


def test_marketing_discount_is_reconciled_to_the_committed_one(client, monkeypatch):
    from app import llm

    real = llm.call

    async def tampered(stage, messages, **kw):
        res = await real(stage, messages, **kw)
        if stage == "marketing":
            res.parsed.discount_ask.brand_funded_pct = 25
        return res

    monkeypatch.setattr(llm, "call", tampered)
    run_id, stages = run_to_catalog(client, "V002")
    approve(client, run_id, "catalog", stages)
    mk = wait_for(client, run_id, ["marketing"])["marketing"]["data"]
    assert mk["discount_ask"]["brand_funded_pct"] == 5 and mk["corrections"][0]["model"] == 25
