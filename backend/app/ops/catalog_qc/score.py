"""Priority score of a catalog issue: GMV at risk, severity and the 'not as described' return signal, weighted by the playbook
(catalog_qc.priority_weights). Pure arithmetic over numbers the detectors and the ops data already gave."""

from typing import Any

from app import policy


def signals(gmv_at_risk: float, max_gmv: float, severity: str, nad_rate_pct: float | None) -> dict[str, float]:
    """The three 0-100 signals. GMV is scaled to the biggest listing, severity to the highest severity point, the return rate to
    twice the playbook threshold (so a listing at the threshold scores 50 and one at double or more scores 100)."""
    qc = policy.get().catalog_qc
    points = qc.severity_points.model_dump()
    top = max(points.values()) or 1.0
    ret = 0.0
    if nad_rate_pct and qc.returns.threshold_pct > 0:
        ret = min(nad_rate_pct / (2 * qc.returns.threshold_pct), 1.0) * 100
    return {
        "gmv": round(100 * gmv_at_risk / max_gmv, 2) if max_gmv > 0 else 0.0,
        "severity": round(100 * points[severity] / top, 2),
        "return_rate": round(ret, 2),
    }


def priority(sig: dict[str, float]) -> float:
    w = policy.get().catalog_qc.priority_weights
    total = w.gmv_at_risk + w.severity + w.return_rate
    if total <= 0:
        return 0.0
    return round((w.gmv_at_risk * sig["gmv"] + w.severity * sig["severity"] + w.return_rate * sig["return_rate"]) / total, 2)


def rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Highest score first; ties by id so the order is stable. Adds ``rank`` (1-based)."""
    out = sorted(rows, key=lambda r: (-r["score"], r["id"]))
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    return out
