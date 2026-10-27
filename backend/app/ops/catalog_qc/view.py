"""The queue as the UI sees it: the generated result plus each fix's decision, the listing after the pending/approved fixes, and
the counter ("N fixes ready, est. X minutes saved") from the playbook's impact baselines."""

from typing import Any

from app import policy
from app.ops.catalog_qc import outbox
from app.ops.catalog_qc.fixes import ORDER, apply_changes


def build_view(result: dict[str, Any]) -> dict[str, Any]:
    fixes = {}
    for fid, f in result["fixes"].items():
        d = outbox.decision(fid)
        fixes[fid] = {**f, "decision": outbox.status_of(f), "decided_at": d["decided_at"] if d else None}
    rows = [{**r, "decision": fixes[r["fix_id"]]["decision"] if r["fix_id"] else "none"} for r in result["rows"]]
    listings = []
    for lst in result["listings"]:
        mine = sorted((fixes[i] for i in lst["fix_ids"]), key=lambda f: ORDER.index(f["kind"]))
        live = [f for f in mine if f["status"] == "ready" and f["decision"] in ("pending", "approved")]
        after = lst["before"]
        for f in live:
            after = apply_changes(after, f["changes"])
        listings.append({**lst, "after": after, "fixes": [f["id"] for f in mine]})
    minutes = float(policy.get().impact.recurring_minutes.catalog_fix_per_sku)
    ready = [f for f in fixes.values() if f["status"] == "ready" and f["decision"] == "pending"]
    approved = [f for f in fixes.values() if f["decision"] == "approved"]
    ready_listings = {f["listing_id"] for f in ready}
    approved_listings = {f["listing_id"] for f in approved}
    summary = {
        "issues": len(rows),
        "fixes_total": len(fixes),
        "fixes_ready": len(ready),
        "fixes_blocked": sum(1 for f in fixes.values() if f["decision"] == "blocked"),
        "fixes_approved": len(approved),
        "fixes_rejected": sum(1 for f in fixes.values() if f["decision"] == "rejected"),
        "listings_ready": len(ready_listings),
        "minutes_per_listing": minutes,
        "minutes_saved": round(len(ready_listings) * minutes, 1),
        "minutes_saved_approved": round(len(approved_listings) * minutes, 1),
        "baseline_status": policy.get().impact.baseline_status,
    }
    return {**result, "rows": rows, "listings": listings, "fixes": fixes, "summary": summary, "updates": outbox.updates(), "simulated": True}
