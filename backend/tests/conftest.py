import pytest

from app import auth, llm
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
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "ledger.json")

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(llm, "_sleep", no_sleep)
    auth.reset_rate_limits()
