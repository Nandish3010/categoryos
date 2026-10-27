"""Per-IP model-spend budget for sandbox vendors that run without the demo key (UPLOAD_LIVE_BUDGET_USD_PER_IP per UTC day).
The global MAX_SPEND_USD cap is enforced separately by ledger.check_budget and always applies."""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.errors import SpendCapExceeded

_lock = threading.Lock()


def _path() -> Path:
    return Path(settings.state_dir) / "ip_spend.json"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _read() -> dict[str, dict[str, float]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def spent(ip_key: str) -> float:
    return float(_read().get(_today(), {}).get(ip_key, 0.0))


def remaining(ip_key: str) -> float:
    return max(settings.upload_live_budget_usd_per_ip - spent(ip_key), 0.0)


def charge(ip_key: str, usd: float) -> None:
    if not ip_key or usd <= 0:
        return
    with _lock:
        data = _read()
        day = _today()
        data = {day: data.get(day, {})}  # older days are dropped
        data[day][ip_key] = round(data[day].get(ip_key, 0.0) + usd, 8)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)


def check(ip_key: str) -> None:
    if remaining(ip_key) <= 0:
        raise SpendCapExceeded(
            "Your free model budget for sandbox vendors is used up",
            cause=f"This address has spent its ${settings.upload_live_budget_usd_per_ip:.2f} share today",
            fix="Rules-only runs are free and unlimited; a demo key lifts the budget",
        )
