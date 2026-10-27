"""Verifier for promotions claims. Called from app.ops.verify.verify_ops_claim for any claim whose metric starts with ``promo_``.

* engine claims (the plan table, vendor asks, the value of a funding offer, the deep option) are recomputed by the engine
  (``claims.REGISTRY``) and compared within the playbook tolerance;
* model_extraction claims (what a vendor's funding reply offers: a share, a sales target, a banner commitment, a lead time): the
  quote must appear verbatim in the reply the claim cites, and the number must be one of the numbers the quote states.

Never imports llm."""

from app import policy
from app.ops.promotions import claims as pc
from app.ops.promotions import data as pdata
from app.schemas import Claim
from app.verify import _finish, numbers_in


def handles(claim: Claim) -> bool:
    return claim.metric.startswith("promo_")


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def _verify_extraction(claim: Claim) -> Claim:
    ev = claim.evidence
    if ev is None or ev.row is None or not ev.raw_value:
        return _finish(claim, "rejected", "no evidence: a reply and a verbatim quote are required")
    if claim.source_ref.file != pdata.REPLIES or claim.metric not in pc.EXTRACTION_METRICS:
        return _finish(claim, "unverifiable", "funding readings are only checked against ops/promo_vendor_replies.json")
    if ev.sha256 != pdata.file_sha256():
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    replies = pdata.replies()
    if not 1 <= ev.row <= len(replies) or replies[ev.row - 1].id != claim.source_ref.key:
        return _finish(claim, "rejected", f"the reply file has no reply {claim.source_ref.key!r} at position {ev.row}")
    reply = replies[ev.row - 1]
    if _squash(ev.raw_value) not in _squash(reply.body):
        return _finish(claim, "rejected", f"the quote does not appear verbatim in reply {reply.id}")
    stated = numbers_in(ev.raw_value)
    value = claim.value * 100 if claim.unit == "pct" else claim.value
    tol = policy.tol("pct") * 100 if claim.unit == "pct" else policy.tol(claim.unit)
    if not any(abs(n - value) <= max(tol, 1e-9) for n in stated):
        shown = ", ".join(f"{n:g}" for n in stated) or "none"
        return _finish(claim, "rejected", f"the quote states {shown}; the reading says {value:g}", (stated[0] / 100 if claim.unit == "pct" else stated[0]) if stated else None)
    return _finish(claim, "verified", None, claim.value)


def verify_promo_claim(claim: Claim) -> Claim:
    if claim.origin == "model_extraction":
        return _verify_extraction(claim)
    return pc.REGISTRY.verify(claim)
