"""The simulated "catalog update" outbox. Approving a fix queues a catalog update for its listing and marks it applied in the
simulator; NOTHING is pushed to any marketplace or vendor. In memory by design (the demo resets with the server).

Rules: a fix is decided once; a fix with an unverified claim cannot be approved (single approve is refused, bulk approve skips it);
a bulk approve is capped by the playbook (catalog_qc.bulk_approve_limit) and is checked as a whole before anything is applied."""

from datetime import UTC, datetime
from typing import Any

from app import policy
from app.errors import (
    BulkLimitExceeded,
    CatalogFixBlocked,
    CatalogFixNotPending,
    EmptySelection,
    UnknownCatalogFix,
)
from app.ops.catalog_qc.fixes import ORDER

_decisions: dict[str, dict[str, Any]] = {}  # fix id -> {status, decided_at, note}
_updates: dict[str, dict[str, Any]] = {}  # listing id -> the queued catalog update


def reset() -> None:
    _decisions.clear()
    _updates.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def decision(fix_id: str) -> dict[str, Any] | None:
    return _decisions.get(fix_id)


def status_of(fix: dict[str, Any]) -> str:
    """pending | approved | rejected | blocked (blocked: the verifier did not confirm a claim; it can only be rejected)."""
    d = _decisions.get(fix["id"])
    if d is not None:
        return d["status"]
    return "blocked" if fix["status"] == "blocked" else "pending"


def _merge(fixes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The changes of several fixes of one listing in application order: the first 'before' and the last 'after' per field."""
    merged: dict[str, dict[str, Any]] = {}
    for f in sorted(fixes, key=lambda f: ORDER.index(f["kind"])):
        for c in f["changes"]:
            if c["field"] in merged:
                merged[c["field"]] = {**merged[c["field"]], "after": c["after"], "after_text": c["after_text"]}
            else:
                merged[c["field"]] = dict(c)
    return list(merged.values())


def _queue_update(listing_id: str, fixes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    approved = [f for f in fixes.values() if f["listing_id"] == listing_id and _decisions.get(f["id"], {}).get("status") == "approved"]
    first = approved[0]
    update = {
        "id": f"CU-{listing_id}", "listing_id": listing_id, "vendor_id": first["vendor_id"], "sku_code": first["sku_code"],
        "fix_ids": [f["id"] for f in sorted(approved, key=lambda f: ORDER.index(f["kind"]))], "changes": _merge(approved),
        "status": "applied_simulated", "simulated": True, "queued_at": _now(),
        "note": "Nothing was pushed to the marketplace: this is a simulated catalog update.",
    }
    _updates[listing_id] = update
    return update


def _decide(fix: dict[str, Any], status: str, note: str | None) -> None:
    _decisions[fix["id"]] = {"status": status, "decided_at": _now(), "note": note}


def approve(fix: dict[str, Any], fixes: dict[str, dict[str, Any]], note: str | None = None) -> dict[str, Any]:
    if fix["id"] in _decisions:
        raise CatalogFixNotPending()
    if fix["status"] == "blocked":
        raise CatalogFixBlocked(cause=fix.get("reason") or CatalogFixBlocked.cause)
    _decide(fix, "approved", note)
    return _queue_update(fix["listing_id"], fixes)


def reject(fix: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    if fix["id"] in _decisions:
        raise CatalogFixNotPending()
    _decide(fix, "rejected", note)
    return _decisions[fix["id"]]


def select(fixes: dict[str, dict[str, Any]], fix_ids: list[str], *, limit: int | None = None) -> list[str]:
    """Validate a bulk selection as a whole: not empty, within the cap, every id known. Duplicates are dropped."""
    ids = list(dict.fromkeys(fix_ids))
    if not ids:
        raise EmptySelection()
    cap = policy.get().catalog_qc.bulk_approve_limit if limit is None else limit
    if len(ids) > cap:
        raise BulkLimitExceeded(len(ids), cap)
    for i in ids:
        if i not in fixes:
            raise UnknownCatalogFix(i)
    return ids


def bulk_approve(fixes: dict[str, dict[str, Any]], fix_ids: list[str], note: str | None = None) -> dict[str, Any]:
    ids = select(fixes, fix_ids)
    approved, skipped, touched = [], [], []
    for i in ids:
        fix = fixes[i]
        if i in _decisions:
            skipped.append({"fix_id": i, "reason": f"already {_decisions[i]['status']}"})
        elif fix["status"] == "blocked":
            skipped.append({"fix_id": i, "reason": "a claim behind this fix was not verified: " + (fix.get("reason") or "see the claims")})
        else:
            _decide(fix, "approved", note)
            approved.append(i)
            touched.append(fix["listing_id"])
    updates = [_queue_update(lid, fixes) for lid in dict.fromkeys(touched)]
    return {"simulated": True, "approved": approved, "skipped": skipped, "updates": updates}


def bulk_reject(fixes: dict[str, dict[str, Any]], fix_ids: list[str], note: str | None = None) -> dict[str, Any]:
    ids = select(fixes, fix_ids)
    rejected, skipped = [], []
    for i in ids:
        if i in _decisions:
            skipped.append({"fix_id": i, "reason": f"already {_decisions[i]['status']}"})
        else:
            _decide(fixes[i], "rejected", note)
            rejected.append(i)
    return {"rejected": rejected, "skipped": skipped}


def updates() -> list[dict[str, Any]]:
    return sorted(_updates.values(), key=lambda u: u["id"])
