"""The approval queue for drafted vendor messages. Sending is SIMULATED: approving a draft marks it
``sent_simulated`` and nothing leaves the process. In-memory by design (the demo resets with the server)."""

from datetime import UTC, datetime
from typing import Any

from app.errors import CategoryOSError, DraftNotPending, UnknownDraft
from app.ops.verify import unclaimed_numbers


class DraftBlocked(CategoryOSError):
    status = 409
    code = "draft_has_unverified_numbers"
    problem = "This draft states a number the verifier rejected"
    cause = "A figure in the message did not match the data, so it cannot be approved as written"
    fix = "Edit the message to remove or correct the number, then approve again; or reject the draft"


_drafts: dict[str, dict[str, Any]] = {}


def reset() -> None:
    _drafts.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _blocked(draft: dict[str, Any], body: str) -> list[str]:
    """Shown strings of rejected or unverifiable figures that are still in the message."""
    return [f["shown"] for f in draft["figures"] if f["status"] != "verified" and f["shown"] and f["shown"] in body]


def put(draft: dict[str, Any]) -> dict[str, Any]:
    """Queue a draft. A draft a person already decided stays as decided; a pending one is replaced by the fresh draft."""
    current = _drafts.get(draft["id"])
    if current is not None and current["status"] != "pending":
        return current
    draft = {**draft, "status": "pending", "decided_at": None, "simulated": True, "edited": False, "note": None, "warnings": []}
    draft["blocked_by"] = _blocked(draft, draft["body"])
    _drafts[draft["id"]] = draft
    return draft


def get(draft_id: str) -> dict[str, Any]:
    if draft_id not in _drafts:
        raise UnknownDraft(draft_id)
    return _drafts[draft_id]


def listing(kind: str | None = None) -> list[dict[str, Any]]:
    rows = [d for d in _drafts.values() if kind is None or d["kind"] == kind]
    return sorted(rows, key=lambda d: (d["status"] != "pending", d["id"]))


def _pending(draft_id: str) -> dict[str, Any]:
    draft = get(draft_id)
    if draft["status"] != "pending":
        raise DraftNotPending()
    return draft


def approve(draft_id: str, body: str | None = None, note: str | None = None) -> dict[str, Any]:
    draft = _pending(draft_id)
    if body is not None and body != draft["body"]:
        draft["body"], draft["edited"] = body, True
        known = [f["shown"] for f in draft["figures"]]
        draft["warnings"] = [f"number without a claim: {n}" for n in unclaimed_numbers(body, known)]
    blocked = _blocked(draft, draft["body"])
    draft["blocked_by"] = blocked
    if blocked:
        raise DraftBlocked(cause=f"The message still contains {', '.join(blocked)}, which failed verification")
    draft.update(status="sent_simulated", decided_at=_now(), note=note)
    return draft


def reject(draft_id: str, note: str | None = None) -> dict[str, Any]:
    draft = _pending(draft_id)
    draft.update(status="rejected", decided_at=_now(), note=note)
    return draft
