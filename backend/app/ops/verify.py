"""Verifier for Run claims. Called from app.verify.verify_claim for any claim whose source is ``ops/...``.

* engine claims: the metric is recomputed from the ops data (app.ops.claims) and compared within the playbook tolerance.
* model_extraction claims (vendor email replies): the quote must appear verbatim in the reply the claim cites; a quantity
  must be one of the numbers in the quote; an ETA must be the date the quote resolves to (app.ops.dates), not the
  model's own arithmetic."""

import re

from app import policy
from app.errors import CategoryOSError
from app.ops import claims as oc
from app.ops.data import allowed_files, file_sha256, load
from app.ops.dates import resolve_eta
from app.schemas import Claim
from app.verify import _finish, numbers_in

_REPLIES_FILE = "ops/vendor_replies.json"


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def _verify_reply(claim: Claim) -> Claim:
    ev = claim.evidence
    if ev is None or ev.row is None or not ev.raw_value:
        return _finish(claim, "rejected", "no evidence: a reply and a verbatim quote are required")
    if claim.source_ref.file != _REPLIES_FILE:
        return _finish(claim, "unverifiable", "reply claims are only checked against ops/vendor_replies.json")
    if ev.sha256 != file_sha256(_REPLIES_FILE):
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    replies = load().replies
    if not 1 <= ev.row <= len(replies) or replies[ev.row - 1].id != claim.source_ref.key:
        return _finish(claim, "rejected", f"the reply file has no reply {claim.source_ref.key!r} at position {ev.row}")
    reply = replies[ev.row - 1]
    quote = _squash(ev.raw_value)
    if quote not in _squash(reply.body):
        return _finish(claim, "rejected", f"the quote does not appear verbatim in reply {reply.id}")
    if claim.metric == "reply_qty":
        stated = numbers_in(ev.raw_value)
        if not any(abs(n - claim.value) <= max(policy.tol("qty"), 1e-9) for n in stated):
            shown = ", ".join(f"{n:g}" for n in stated) or "none"
            return _finish(claim, "rejected", f"the quote states {shown}; the claim says {claim.value:g}", stated[0] if stated else None)
        return _finish(claim, "verified", None, claim.value)
    if claim.metric == "reply_eta_days":
        eta = resolve_eta(ev.raw_value, reply.received_at.date())
        if eta is None:
            return _finish(claim, "rejected", "the quote promises no date (no day, date or number of days in it)")
        days = float((eta - reply.received_at.date()).days)
        if abs(days - claim.value) <= policy.tol("units"):
            return _finish(claim, "verified", None, days)
        return _finish(
            claim, "rejected",
            f"the quote resolves to {eta.isoformat()}, {days:g} days after the reply (the later end of a range); the claim says {claim.value:g}",
            days,
        )
    return _finish(claim, "unverifiable", f"unknown reply metric {claim.metric!r}")


def verify_ops_claim(claim: Claim) -> Claim:
    from app.ops.catalog_qc import (
        verify as catalog_verify,  # the live-catalog fix queue owns its claims
    )

    if catalog_verify.handles(claim):
        return catalog_verify.verify_catalog_claim(claim)
    rel = claim.source_ref.file
    if rel not in allowed_files():
        return _finish(claim, "rejected", f"unknown source: {rel!r} is not an allowlisted ops data file")
    if claim.origin == "model_extraction":
        return _verify_reply(claim)
    if claim.metric not in oc.METRICS:
        return _finish(claim, "unverifiable", f"unknown metric {claim.metric!r}")
    if claim.evidence is not None and claim.evidence.sha256 != oc.data_sha():
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the ops data")
    unit = oc.METRICS[claim.metric].unit
    try:
        recomputed = oc.compute(claim.metric, claim.source_ref.key)
    except (CategoryOSError, ValueError) as exc:
        return _finish(claim, "rejected", f"cannot recompute: {getattr(exc, 'problem', str(exc))}")
    if abs(recomputed - claim.value) <= policy.tol(unit):
        return _finish(claim, "verified", None, recomputed)
    return _finish(claim, "rejected", f"engine recomputed {recomputed:g}, claim says {claim.value:g}", recomputed)


# ---------- numbers the agent writes in prose ----------

_ID = re.compile(r"\b(?:PO-)?[A-Z]{1,3}\d{3}(?:-\d{4})?\b|\b[A-Z]{2}-\d{2}\b|\bPO-E\d{3}-\d{4}\b")
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DAY_MONTH = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b", re.IGNORECASE)
_WEEK_REF = re.compile(r"\b(?:week|weeks|weekly)\s+\d+\b|\b\d+\s*[- ]?weeks?\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])[₹]?\d[\d,]*(?:\.\d+)?(?:\s?%|\s?(?:lakh|crore|k)\b)?", re.IGNORECASE)
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")


def unclaimed_numbers(text: str, shown: list[str], ignore: list[str] | None = None) -> list[str]:
    """Numbers in ``text`` that are not covered by a figure's ``shown`` string. Identifiers, dates and list markers are
    not figures. The agent has to attach a claim to every number it writes."""
    rest = text
    for name in sorted(ignore or [], key=len, reverse=True):  # product names carry sizes ("Litter 10 kg"): not figures
        rest = rest.replace(name, " ")
    for s in sorted(set(shown), key=len, reverse=True):
        if s:
            rest = rest.replace(s, " ")
    for pat in (_ISO, _DAY_MONTH, _ID, _LIST_MARKER, _WEEK_REF):
        rest = pat.sub(" ", rest)
    return [t.strip() for t in _NUMBER.findall(rest) if t.strip()]
