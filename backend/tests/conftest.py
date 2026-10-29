import pytest

from app import auth, llm, runner
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """No real keys, ledger in tmp, mock mode, no sleeping, clean rate limiter."""
    monkeypatch.setattr(settings, "model_mode", "mock")
    monkeypatch.setattr(settings, "model_api_key", None)
    monkeypatch.setattr(settings, "baseten_api_key", None)
    monkeypatch.setattr(settings, "demo_key", None)
    monkeypatch.setattr(settings, "live_stages", "")
    monkeypatch.setattr(settings, "record", False)
    monkeypatch.setattr(settings, "escalation_model", "")  # tests that exercise escalation switch it on
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "ledger.json")
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets")
    monkeypatch.setattr(settings, "sam_enabled", True)
    monkeypatch.setattr(settings, "policy_local_path", tmp_path / "policy.local.yaml")
    monkeypatch.setattr(settings, "demo_today", "2026-10-27")
    monkeypatch.setattr(settings, "sse_heartbeat_s", 15.0)
    runner.reset_state()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(llm, "_sleep", no_sleep)

    def no_real_client(provider):
        raise AssertionError(f"tests must never build a real {provider} client")

    monkeypatch.setattr(llm, "_make_client", no_real_client)
    auth.reset_rate_limits()
    yield
    runner.reset_state()
