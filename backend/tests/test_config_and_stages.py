from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

STAGE_IDS = [
    "intake",
    "research",
    "shortlist",
    "negotiate",
    "catalog",
    "marketing",
    "jbp",
    "po",
]


def test_settings_reads_model_api_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    assert Settings(_env_file=None).model_api_key == "test-key"


def test_effective_mode_mock_when_key_missing(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_MODE", "live")
    s = Settings(_env_file=None)
    assert s.model_mode == "live"
    assert s.effective_mode == "mock"


def test_effective_mode_live_with_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_MODE", "live")
    assert Settings(_env_file=None).effective_mode == "live"


def test_stages_ids_in_order():
    res = TestClient(app).get("/api/stages")
    assert res.status_code == 200
    ids = [s["id"] for s in res.json()]
    assert ids == STAGE_IDS
    assert "marketing" in ids
    assert "followup" not in ids
