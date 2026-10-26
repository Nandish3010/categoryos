"""Optional durability hook. On Modal, modal_app.py registers ``volume.commit`` so SQLite and ledger writes reach the
Volume; locally nothing is registered and every call is a no-op. Commits are throttled (they are expensive)."""

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger("categoryos.persist")

MIN_INTERVAL_S = 2.0
_hook: Callable[[], None] | None = None
_last = 0.0
_dirty = False
_lock = threading.Lock()


def set_hook(hook: Callable[[], None] | None) -> None:
    global _hook, _last, _dirty
    _hook, _last, _dirty = hook, 0.0, False


def _run() -> None:
    global _last, _dirty
    if _hook is None:
        return
    try:
        _hook()
    except Exception:
        log.exception("persist hook failed")
    _last, _dirty = time.monotonic(), False


def notify() -> None:
    """Call after a state change. Commits at most once per MIN_INTERVAL_S; ``flush`` catches the rest."""
    global _dirty
    if _hook is None:
        return
    with _lock:
        _dirty = True
        if time.monotonic() - _last >= MIN_INTERVAL_S:
            _run()


def flush() -> None:
    """Commit anything still pending (call on shutdown)."""
    with _lock:
        if _dirty:
            _run()
