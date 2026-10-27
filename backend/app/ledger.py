"""Spend ledger: price table, atomic JSON persistence, budget checks."""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from app import persist, scope
from app.config import settings
from app.errors import SpendCapExceeded

log = logging.getLogger("categoryos.ledger")

# USD per 1M tokens: (input, cached input, output)
_SPARK = (1.25, 0.15, 4.25)
_CONTRIB = (0.10, 0.002, 0.20)
TOKEN_PRICES: dict[str, tuple[float, float, float]] = {
    "muse-spark-1.1": _SPARK,
    "muse-spark-1.2": _SPARK,
    "muse-spark-1.3": _SPARK,
    "muse-spark-1.1-contributor": _CONTRIB,
    "muse-spark-1.2-contributor": _CONTRIB,
    "muse-spark-1.3-contributor": _CONTRIB,
    "muse-wonder-1.0": (4.00, 0.20, 20.00),
    # TODO: Baseten open-weight pricing is not known yet; counted as $0 until confirmed.
    "muse-spark-open": (0.0, 0.0, 0.0),
    "meta-models/muse-spark-open": (0.0, 0.0, 0.0),
}
PER_IMAGE_USD = {"muse-image-1.0": 0.01, "sam-3.1": 2.50 / 1000}
PER_HOUR_USD = {"muse-voice-transcribe-1.0": 0.18}

_lock = threading.Lock()


def _empty() -> dict[str, Any]:
    return {"total_usd": 0.0, "calls": 0, "by_model": {}}


def price(model: str, usage: dict[str, float]) -> float:
    """Cost in USD for one call. usage keys: input_tokens, cached_tokens, output_tokens, images, hours."""
    if model in PER_IMAGE_USD:
        return PER_IMAGE_USD[model] * usage.get("images", 1)
    if model in PER_HOUR_USD:
        return PER_HOUR_USD[model] * usage.get("hours", 0)
    rates = TOKEN_PRICES.get(model)
    if rates is None:
        log.warning("no price for model %r; charging muse-spark-1.3 rates", model)
        rates = _SPARK
    cached = usage.get("cached_tokens", 0)
    fresh = max(usage.get("input_tokens", 0) - cached, 0)
    return (fresh * rates[0] + cached * rates[1] + usage.get("output_tokens", 0) * rates[2]) / 1_000_000


def read() -> dict[str, Any]:
    path = Path(settings.ledger_path)
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def total_usd() -> float:
    return float(read().get("total_usd", 0.0))


def record(model: str, usage: dict[str, float]) -> float:
    cost = price(model, usage)
    path = Path(settings.ledger_path)
    with _lock:
        data = read()
        data["total_usd"] = round(float(data.get("total_usd", 0.0)) + cost, 8)
        data["calls"] = int(data.get("calls", 0)) + 1
        entry = data["by_model"].setdefault(model, {"calls": 0, "usd": 0.0})
        entry["calls"] += 1
        entry["usd"] = round(entry["usd"] + cost, 8)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)
    persist.notify()
    sc = scope.current()
    if sc is not None and sc.ip_key:
        from app import (
            sandbox_budget,  # sandbox vendors: charge the caller's per-IP bucket too
        )

        sandbox_budget.charge(sc.ip_key, cost)
    return cost


def check_budget() -> None:
    sc = scope.current()
    if sc is not None and sc.ip_key:
        from app import sandbox_budget

        sandbox_budget.check(sc.ip_key)
    spent = total_usd()
    if spent >= settings.max_spend_usd:
        raise SpendCapExceeded(
            cause=f"Recorded spend ${spent:.2f} is at or above MAX_SPEND_USD (${settings.max_spend_usd:.2f})"
        )
    if spent >= settings.warn_spend_usd:
        log.warning("spend $%.2f is at or above the warning threshold $%.2f", spent, settings.warn_spend_usd)
