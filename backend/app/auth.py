"""Demo-key auth and a small in-memory per-IP rate limiter for keyed routes."""

import secrets
import time
from collections import defaultdict, deque

from fastapi import Header, Request

from app.config import settings
from app.errors import DemoKeyRequired, RateLimited

WINDOW_S = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    _hits.clear()


def check_rate(ip: str) -> None:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= settings.rate_limit_per_min:
        raise RateLimited()
    q.append(now)


async def require_demo_key(request: Request, x_demo_key: str | None = Header(default=None)) -> None:
    if not settings.demo_key:
        raise DemoKeyRequired(
            cause="DEMO_KEY is not set on the server, so keyed routes are disabled",
            fix="Set DEMO_KEY in the root .env (or the Modal secret) and restart the backend",
        )
    if not x_demo_key or not secrets.compare_digest(x_demo_key.encode(), settings.demo_key.encode()):
        raise DemoKeyRequired()
    check_rate(request.client.host if request.client else "unknown")
