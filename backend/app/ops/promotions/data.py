"""Loaders for the promotions planner: the vendors' funding replies (data/synthetic/ops/promo_vendor_replies.json, written by
data/generate_promotions.py). The sale calendar is the playbook's ``promotions.events``; stock, sales and POs come from the ops data."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

from app.config import settings
from app.errors import PromoDataMissing

REPLIES = "ops/promo_vendor_replies.json"
FILES = (REPLIES,)


@dataclass(frozen=True)
class FundingReply:
    id: str
    event_id: str
    vendor_id: str
    received_at: datetime
    sender: str
    subject: str
    body: str


def path(rel: str = REPLIES) -> Path:
    return Path(settings.data_dir) / rel


def file_sha256(rel: str = REPLIES) -> str:
    if rel not in FILES:
        raise ValueError(f"not a promotions data file: {rel}")
    return hashlib.sha256(path(rel).read_bytes()).hexdigest()


@cache
def _load(data_dir: str) -> tuple[FundingReply, ...]:  # data_dir is only the cache key
    p = path()
    if not p.exists():
        raise PromoDataMissing(cause=f"{p} does not exist")
    rows = json.loads(p.read_text(encoding="utf-8"))
    return tuple(
        FundingReply(r["id"], r["event_id"], r["vendor_id"], datetime.fromisoformat(r["received_at"]), r["from"], r["subject"], r["body"]) for r in rows
    )


def replies() -> tuple[FundingReply, ...]:
    return _load(str(settings.data_dir))


def replies_for(event_id: str) -> list[FundingReply]:
    return [r for r in replies() if r.event_id == event_id]


def position(reply_id: str) -> int:
    """1-based position of a reply in the file: the evidence row of a claim."""
    for i, r in enumerate(replies(), start=1):
        if r.id == reply_id:
            return i
    raise KeyError(reply_id)
