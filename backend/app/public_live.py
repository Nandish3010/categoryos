"""Public live budget: lets visitors of the public (replay) deploy try a few live-model features without the demo key.

Ops config (env vars, not the playbook):
  PUBLIC_LIVE_BUDGET_USD   total model spend the public may cause, ever (0 = disabled, the default)
  PUBLIC_LIVE_PER_IP_USD   most one address may cause per UTC day (default 0.50)
  PUBLIC_LIVE_FEATURES     comma list; allowed: ``byo`` (bring-your-own-vendor model stages), ``copilot`` (live call copilot),
                           ``rules`` (free-form playbook rules written as prompts; the examples always work without it)

Everything else stays as it was: the built-in vendor runs keep replaying, the demo key path is untouched, the global
MAX_SPEND_USD ledger cap always applies on top, and the existing rate limits still apply. When any limit is hit the
caller gets ``PublicBudgetExhausted`` (BYO is demoted to rules-only at run start, the copilot to Simulate call).
The per-call limit is CALL_BUDGET_USD for the copilot; a BYO run is bounded by the per-IP share."""

import contextvars
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import ledger
from app.config import settings
from app.errors import PublicBudgetExhausted

ALLOWED_FEATURES = ("byo", "copilot", "rules")

_lock = threading.Lock()


@dataclass(frozen=True)
class PublicCtx:
    feature: str
    ip_key: str


_current: contextvars.ContextVar[PublicCtx | None] = contextvars.ContextVar("categoryos_public_live", default=None)


def current() -> PublicCtx | None:
    return _current.get()


@contextmanager
def use(ctx: PublicCtx | None) -> Iterator[None]:
    token = _current.set(ctx)
    try:
        yield
    finally:
        _current.reset(token)


# ---------- config ----------


def features() -> set[str]:
    return {f for f in (s.strip().lower() for s in settings.public_live_features.split(",")) if f in ALLOWED_FEATURES}


def _configured() -> bool:
    return (
        settings.public_live_budget_usd > 0
        and bool(features())
        and bool(settings.model_api_key)
        and settings.model_mode != "mock"
    )


def enabled(feature: str) -> bool:
    """True when this feature may go live without the demo key: budget set, feature listed, and a model key to spend with."""
    return _configured() and feature in features()


# ---------- state ----------


def _path() -> Path:
    return Path(settings.state_dir) / "public_live.json"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _read() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    ips = data.get("ips", {}) if data.get("day") == _today() else {}  # per-IP shares reset each UTC day
    return {"total_usd": float(data.get("total_usd", 0.0)), "day": _today(), "ips": ips if isinstance(ips, dict) else {}}


def spent_total() -> float:
    return _read()["total_usd"]


def spent_ip(ip_key: str) -> float:
    return float(_read()["ips"].get(ip_key, 0.0))


def remaining_total() -> float:
    return max(settings.public_live_budget_usd - spent_total(), 0.0)


def remaining_ip(ip_key: str) -> float:
    return max(settings.public_live_per_ip_usd - spent_ip(ip_key), 0.0)


def ledger_room() -> float:
    return max(settings.max_spend_usd - ledger.total_usd(), 0.0)


def charge(ip_key: str, usd: float) -> None:
    if not ip_key or usd <= 0:
        return
    with _lock:
        data = _read()
        data["total_usd"] = round(data["total_usd"] + usd, 8)
        data["ips"][ip_key] = round(float(data["ips"].get(ip_key, 0.0)) + usd, 8)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)


def check(ip_key: str) -> None:
    """Raise PublicBudgetExhausted unless the shared budget, this address's share and the global ledger cap all have room."""
    if remaining_total() <= 0:
        raise PublicBudgetExhausted(cause=f"The shared ${settings.public_live_budget_usd:.2f} public live budget is spent")
    if remaining_ip(ip_key) <= 0:
        raise PublicBudgetExhausted(cause=f"This address has used its ${settings.public_live_per_ip_usd:.2f} share today")
    if ledger_room() <= 0:
        raise PublicBudgetExhausted(cause="The global spend cap (MAX_SPEND_USD) was reached")


def available(feature: str, ip_key: str) -> bool:
    if not enabled(feature):
        return False
    try:
        check(ip_key)
    except PublicBudgetExhausted:
        return False
    return True


def status(ip_key: str | None = None, feature: str | None = None) -> dict[str, Any]:
    """What the UI shows. Without an address only the shared numbers are given; with a feature, ``enabled`` is for it."""
    on = enabled(feature) if feature else _configured()
    shared = round(min(remaining_total(), ledger_room()), 4) if on else 0.0
    out: dict[str, Any] = {
        "enabled": on,
        "features": sorted(features()) if on else [],
        "budget_usd": round(settings.public_live_budget_usd, 4) if on else 0.0,
        "remaining_usd": shared,
        "per_ip_usd": round(settings.public_live_per_ip_usd, 4) if on else 0.0,
    }
    if ip_key is not None:
        ip_left = round(min(remaining_ip(ip_key), shared), 4) if on else 0.0
        out["ip_remaining_usd"] = ip_left
        out["exhausted"] = on and ip_left <= 0
    return out
