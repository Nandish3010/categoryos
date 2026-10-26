from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_claims_endpoint_all_verified():
    res = client.get("/api/vendors/V001/claims")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == body["verified"] > 0
    assert body["rejected"] == 0 and body["unverifiable"] == 0


def test_claims_inject_shows_exactly_one_rejected():
    body = client.get("/api/vendors/V001/claims?inject=1").json()
    assert body["rejected"] == 1
    bad = next(c for c in body["claims"] if c["status"] == "rejected")
    assert bad["origin"] == "injected_test" and bad["reason"].startswith("Injected test:")


def test_claims_respects_lever_params():
    body = client.get("/api/vendors/V001/claims?target_margin_pct_offset=5&moq=300").json()
    assert body["rejected"] == 0


def test_claims_validation_and_unknown_vendor_error_shape():
    assert client.get("/api/vendors/V001/claims?inject=2").status_code == 422
    res = client.get("/api/vendors/V999/claims")
    assert res.status_code == 404
    body = res.json()
    assert set(body) == {"code", "problem", "cause", "fix", "run_id"}
    assert body["code"] == "unknown_vendor" and body["run_id"] is None


def test_error_includes_run_id_header():
    res = client.get("/api/vendors/V999", headers={"X-Run-Id": "run_42"})
    assert res.json()["run_id"] == "run_42"


def test_ledger_requires_demo_key(monkeypatch):
    res = client.get("/api/ledger")
    assert res.status_code == 403
    assert res.json()["code"] == "demo_key_required" and "DEMO_KEY" in res.json()["cause"]
    monkeypatch.setattr(settings, "demo_key", "s3cret")
    assert client.get("/api/ledger").status_code == 403
    assert client.get("/api/ledger", headers={"X-Demo-Key": "wrong"}).status_code == 403
    ok = client.get("/api/ledger", headers={"X-Demo-Key": "s3cret"})
    assert ok.status_code == 200
    assert ok.json()["total_usd"] == 0.0 and ok.json()["max_spend_usd"] == settings.max_spend_usd


def test_keyed_routes_are_rate_limited(monkeypatch):
    monkeypatch.setattr(settings, "demo_key", "s3cret")
    monkeypatch.setattr(settings, "rate_limit_per_min", 3)
    headers = {"X-Demo-Key": "s3cret"}
    codes = [client.get("/api/ledger", headers=headers).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_mode_is_open_and_has_no_secrets(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", "test-not-a-real-key")
    monkeypatch.setattr(settings, "demo_key", "s3cret")
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "live_stages", "decide")
    res = client.get("/api/mode")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "live" and body["live_stages"] == ["decide"]
    assert body["stage_modes"]["intake"] == "mock"
    assert {"spend_usd", "max_spend_usd"} <= body.keys()
    assert "test-not-a-real-key" not in res.text and "s3cret" not in res.text
