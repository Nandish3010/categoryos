"""Impact meter. Measured, not claimed.

Human time is *recorded*: the clock starts when a stage reaches "review" (a ``review_started`` mark)
and stops when a person approves it (the ``approve`` row). Edits are the verdict overrides and re-plans the person
made while reviewing. Baselines (how long the same work takes by hand) come from the playbook's ``impact`` section and
are research estimates (docs/research/category-manager-workload.md), not measurements, until the team replaces them;
every figure derived from them says so.

The three approval gates cover the work behind them:

* ``research``: screening, market research, shortlist (everything before the first approval)
* ``catalog``:  negotiation prep, calls and offer evaluation, catalog listings, images, compliance (negotiate and catalog are reviewed here)
* ``po``:       marketing and JBP draft, first PO (the launch packet)

Pure arithmetic lives here; reading the run's rows lives in ``runner``.
"""

from datetime import datetime
from typing import Any

from app import policy

TASK_GATE: dict[str, str] = {
    "screening": "research",
    "market_research_per_sku": "research",
    "shortlist": "research",
    "negotiation_prep": "catalog",
    "negotiation_calls": "catalog",
    "conditional_offer_eval": "catalog",
    "catalog_listing_per_sku": "catalog",
    "image_content_per_sku": "catalog",
    "compliance_per_sku": "catalog",
    "marketing_jbp_draft": "po",
    "first_po_draft": "po",
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
        "basis": "measured" if measured else "research_estimate",
        "edits": sum(g["edits"] for g in gates),
        "overrides": sum(g["overrides"] for g in gates),
        "replans": sum(g["replans"] for g in gates),
        "max_review_minutes": pol.max_review_minutes,
    }


FORMULA = (
    "saved % of the week = sum over tasks of (share of the week the task takes x share of the task a shipped module covers "
    "x share of that time saved); the team figure weights category managers and executives by headcount. A module marked "
    "measured-by-runs uses the measured review reduction once runs are fully reviewed, else the table's estimate."
)


def _cover(rows: list[Any], workload: dict[str, Any], modules: dict[str, Any], measured_saved: float | None, role_field: str) -> tuple[float, float]:
    """(in-scope, saved) as % of one role's week for these coverage rows. Rows on one task add up (capped at 100)."""
    by_task: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        task = workload[r.task]
        frac = task.saved_pct / 100
        if modules[r.module].measured_from_runs and measured_saved is not None:
            frac = measured_saved
        by_task.setdefault(r.task, []).append((r.in_scope_pct, frac))
    in_scope = saved = 0.0
    for task_key, parts in by_task.items():
        share = getattr(workload[task_key], role_field)
        cover = min(100.0, sum(c for c, _ in parts))
        weight = sum(c for c, _ in parts)
        frac = sum(c * f for c, f in parts) / weight if weight else 0.0
        in_scope += share * cover / 100
        saved += share * cover / 100 * frac
    return in_scope, saved


def rollup(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Team view. ``blocks`` are the per-run impact blocks of the latest run per vendor (runs that exist)."""
    pol = policy.get().impact
    team = pol.team
    complete = [b for b in blocks if b["complete"]]
    share = sum(b["human_minutes"] for b in complete) / sum(b["baseline_minutes"] for b in complete) if complete else None
    measured_saved = None if share is None else 1 - share
    roles = [
        ("category_manager", "Category managers", team.category_managers, "category_manager_pct"),
        ("category_executive", "Category executives", team.category_executives, "category_executive_pct"),
    ]
    heads = sum(r[2] for r in roles)
    shipped = [r for r in pol.coverage if pol.modules[r.module].status == "shipped"]

    def team_pts(rows: list[Any]) -> tuple[float, float]:
        if not heads:
            return 0.0, 0.0
        parts = [(n, *_cover(rows, pol.workload, pol.modules, measured_saved, field)) for _, _, n, field in roles]
        return sum(n * i for n, i, _ in parts) / heads, sum(n * s for n, _, s in parts) / heads

    in_scope, saved = team_pts(shipped)
    _, potential = team_pts(list(pol.coverage))
    week_h = heads * team.work_hours_per_week
    month_h = week_h * team.weeks_per_month
    typical_h = baseline_minutes(team.typical_skus_per_vendor) / 60
    onboarding_task = pol.workload.get("new_vendor_onboarding")
    task_h = (
        sum(n * team.work_hours_per_week * getattr(onboarding_task, field) / 100 for _, _, n, field in roles) * team.weeks_per_month
        if onboarding_task
        else 0.0
    )
    human_share = share if share is not None else None
    modules = []
    for key, mod in pol.modules.items():
        rows = [r for r in pol.coverage if r.module == key]
        i, sv = team_pts(rows)
        modules.append(
            {
                "key": key,
                "label": mod.label,
                "status": mod.status,
                "in_scope_pct": round(i, 1),
                "saved_pct": round(sv, 1),
                "tasks": [{"task": r.task, "label": pol.workload[r.task].label, "in_scope_pct": r.in_scope_pct} for r in rows],
            }
        )
    return {
        "basis": "measured" if complete else "research_estimate",
        "measured_runs": len(complete),
        "partly_measured_runs": sum(1 for b in blocks if b["measured_gates"] and not b["complete"]),
        "baseline_status": pol.baseline_status,
        "in_scope_pct": round(in_scope, 1),
        "saved_pct": round(saved, 1),
        "potential_saved_pct": round(potential, 1),
        "target_pct": pol.target_reduction_pct,
        "meets_target": saved >= pol.target_reduction_pct,
        "team_hours_per_month": round(month_h, 1),
        "hours_saved_per_month": round(month_h * saved / 100, 1),
        "roles": [
            {"role": k, "label": lbl, "headcount": n, "in_scope_pct": round(_cover(shipped, pol.workload, pol.modules, measured_saved, f)[0], 1),
             "saved_pct": round(_cover(shipped, pol.workload, pol.modules, measured_saved, f)[1], 1)}
            for k, lbl, n, f in roles
        ],
        "modules": modules,
        "onboarding": {
            "typical_skus": team.typical_skus_per_vendor,
            "baseline_hours_per_vendor": round(typical_h, 1),
            "human_share_pct": None if human_share is None else round(human_share * 100, 1),
            "saved_pct_basis": "measured" if complete else "research_estimate",
            "vendors_per_month": team.vendors_onboarded_per_month,
            "demand_hours_per_month": round(team.vendors_onboarded_per_month * typical_h, 1),
            "team_hours_on_task_per_month": round(task_h, 1),
        },
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
