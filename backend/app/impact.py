"""Impact meter. Measured, not claimed.

Human time is *recorded*: the clock starts when a stage reaches "review" (a ``review_started`` mark)
and stops when a person approves it (the ``approve`` row). Edits are the verdict overrides and re-plans the person
made while reviewing. Baselines (how long the same work takes by hand) come from the playbook's ``impact`` section and
are placeholders until the team replaces them; every figure derived from them says so.

The three approval gates cover the work behind them:

* ``research``: screening, market research, shortlist (everything before the first approval)
* ``catalog``:  negotiation prep and follow-up, catalog listings, image briefs (negotiate and catalog are reviewed here)
* ``po``:       marketing brief, JBP draft, PO raise and follow-up (the launch packet)

Pure arithmetic lives here; reading the run's rows lives in ``runner``.
"""

from datetime import datetime
from typing import Any

from app import policy

TASK_GATE: dict[str, str] = {
    "screening": "research",
    "market_research": "research",
    "shortlist": "research",
    "negotiation_prep": "catalog",
    "negotiation_followup": "catalog",
    "catalog_listing_per_sku": "catalog",
    "image_brief_per_sku": "catalog",
    "marketing_brief": "po",
    "jbp_draft": "po",
    "po_raise": "po",
    "po_followup": "po",
}
GATES: dict[str, str] = {
    "research": "Decision review",
    "catalog": "Negotiation and catalog review",
    "po": "Launch packet review",
}
PER_SKU_SUFFIX = "_per_sku"


def tasks(n_skus: int) -> list[dict[str, Any]]:
    """Baseline minutes per task for a vendor with ``n_skus`` shortlisted SKUs (per-SKU tasks scale with it)."""
    pol = policy.get().impact
    hints = policy.schema_hints()
    out = []
    for name, gate in TASK_GATE.items():
        minutes = float(getattr(pol.baseline_minutes, name))
        per_sku = name.endswith(PER_SKU_SUFFIX)
        count = n_skus if per_sku else 1
        out.append(
            {
                "task": name,
                "label": hints.get(f"impact.baseline_minutes.{name}", {}).get("label", name),
                "gate": gate,
                "minutes": minutes,
                "per_sku": per_sku,
                "count": count,
                "total_minutes": round(minutes * count, 2),
            }
        )
    return out


def baseline_minutes(n_skus: int) -> float:
    return round(sum(t["total_minutes"] for t in tasks(n_skus)), 2)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def review_seconds(approvals: list[dict[str, Any]], marks: list[dict[str, Any]], stage: str) -> float | None:
    """Seconds from the first time ``stage`` reached review to its first approval; None while nobody has approved it."""
    started = next((m["created_at"] for m in marks if m["stage"] == stage and m["kind"] == "review_started"), None)
    approved = next((a["created_at"] for a in approvals if a["stage"] == stage and a["action"] == "approve"), None)
    if started is None or approved is None:
        return None
    return max((_ts(approved) - _ts(started)).total_seconds(), 0.0)


def for_run(
    run: dict[str, Any], approvals: list[dict[str, Any]], marks: list[dict[str, Any]], overrides: list[dict[str, Any]], n_skus: int
) -> dict[str, Any]:
    """The per-run impact block."""
    pol = policy.get().impact
    cap = pol.max_review_minutes * 60
    task_rows = tasks(n_skus)
    gates = []
    for gate, label in GATES.items():
        base = round(sum(t["total_minutes"] for t in task_rows if t["gate"] == gate), 2)
        secs = review_seconds(approvals, marks, gate)
        counted = None if secs is None else min(secs, cap)
        n_over = sum(1 for o in overrides if o["stage"] == gate)
        n_replan = sum(1 for m in marks if m["stage"] == gate and m["kind"] == "replan")
        gates.append(
            {
                "stage": gate,
                "label": label,
                "status": "pending" if secs is None else "measured",
                "baseline_minutes": base,
                "review_seconds": None if secs is None else round(secs, 1),
                "counted_minutes": None if counted is None else round(counted / 60, 3),
                "capped": secs is not None and secs > cap,
                "overrides": n_over,
                "replans": n_replan,
                "edits": n_over + n_replan,
            }
        )
    measured = [g for g in gates if g["status"] == "measured"]
    base_total = round(sum(g["baseline_minutes"] for g in gates), 2)
    base_measured = round(sum(g["baseline_minutes"] for g in measured), 2)
    human = round(sum(g["counted_minutes"] for g in measured), 3)
    reduction = round(100 * (1 - human / base_measured), 1) if measured and base_measured else None
    return {
        "run_id": run["run_id"],
        "vendor_id": run["vendor_id"],
        "mode": run["mode"],
        "baseline_status": pol.baseline_status,
        "n_skus": n_skus,
        "tasks": task_rows,
        "gates": gates,
        "baseline_minutes": base_total,
        "baseline_measured_minutes": base_measured,
        "human_minutes": human,
        "reduction_pct": reduction,
        "measured_gates": len(measured),
        "total_gates": len(gates),
        "complete": len(measured) == len(gates),
        "basis": "measured" if measured else "baseline_estimate",
        "edits": sum(g["edits"] for g in gates),
        "overrides": sum(g["overrides"] for g in gates),
        "replans": sum(g["replans"] for g in gates),
        "max_review_minutes": pol.max_review_minutes,
    }


FORMULA = (
    "hours saved per month = vendors per month x baseline hours per vendor x (1 - human review share); "
    "% of workload = hours saved / (category managers x hours per week x weeks per month)"
)


def rollup(blocks: list[dict[str, Any]], vendor_baselines: dict[str, float]) -> dict[str, Any]:
    """Team view. ``blocks`` are the per-run impact blocks of the latest run per vendor (runs that exist);
    ``vendor_baselines`` maps every vendor to its baseline minutes (from the engine's shortlist, no run needed)."""
    pol = policy.get().impact
    team = pol.team
    mean_baseline_h = (sum(vendor_baselines.values()) / len(vendor_baselines) / 60) if vendor_baselines else 0.0
    complete = [b for b in blocks if b["complete"]]
    if complete:
        share = sum(b["human_minutes"] for b in complete) / sum(b["baseline_minutes"] for b in complete)
        basis = "measured"
    else:
        share = pol.assumed_review_share_pct / 100
        basis = "baseline_estimate"
    demand_h = team.vendors_onboarded_per_month * mean_baseline_h
    saved_h = demand_h * (1 - share)
    workload_h = team.category_managers * team.work_hours_per_week * team.weeks_per_month
    capacity_h = workload_h * team.share_of_week_on_these_tasks_pct / 100
    return {
        "basis": basis,
        "measured_runs": len(complete),
        "partly_measured_runs": sum(1 for b in blocks if b["measured_gates"] and not b["complete"]),
        "baseline_status": pol.baseline_status,
        "human_share_pct": round(share * 100, 2),
        "baseline_hours_per_vendor": round(mean_baseline_h, 2),
        "human_hours_per_vendor": round(mean_baseline_h * share, 2),
        "vendors_per_month": team.vendors_onboarded_per_month,
        "demand_hours_per_month": round(demand_h, 1),
        "hours_saved_per_month": round(saved_h, 1),
        "workload_hours_per_month": round(workload_h, 1),
        "task_capacity_hours_per_month": round(capacity_h, 1),
        "pct_of_workload": round(100 * saved_h / workload_h, 1) if workload_h else None,
        "pct_of_task_time": round(100 * saved_h / demand_h, 1) if demand_h else None,
        "demand_vs_capacity_pct": round(100 * demand_h / capacity_h, 1) if capacity_h else None,
        "target_pct": pol.target_reduction_pct,
        "meets_target": bool(workload_h) and 100 * saved_h / workload_h >= pol.target_reduction_pct,
        "formula": FORMULA,
        "team": team.model_dump(mode="json"),
        "vendors": [
            {
                "vendor_id": b["vendor_id"],
                "run_id": b["run_id"],
                "baseline_minutes": b["baseline_minutes"],
                "human_minutes": b["human_minutes"],
                "measured_gates": b["measured_gates"],
                "complete": b["complete"],
                "reduction_pct": b["reduction_pct"],
            }
            for b in blocks
        ],
    }
