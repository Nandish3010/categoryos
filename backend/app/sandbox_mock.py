"""The generic mock model for sandbox vendors. Built-in vendors have recorded fixtures; an uploaded vendor has none, so
the Screen and Decide "model" outputs are derived from the deterministic engine and labelled as such.

Two flavours, picked by the vendor's model mode: ``rules_only`` (no model is involved at all; the model name says so) and
``mock`` (a server running MODEL_MODE=mock; the name says mock). Neither reads the vendor's text, so neither can be steered
by it. Only the deterministic guards in the agents (documents, claim rules, injection patterns) decide pass or fail."""

import json
import re
from typing import Any

from app import scope

_TASK = re.compile(r"^(screen|decide)_(U-[a-z0-9]{8})$")
RULES_ONLY_MODEL = "rules-only (no model calls)"
MOCK_MODEL = "mock-generic (canned, not a real model)"


def fixture(stage: str, task: str) -> dict[str, Any] | None:
    match = _TASK.match(task)
    if match is None:
        return None
    kind, vendor_id = match.groups()
    sc = scope.current()
    rules_only = sc is None or sc.llm_mode != "mock"
    model = RULES_ONLY_MODEL if rules_only else MOCK_MODEL
    who = "No model reviewed this vendor (rules-only)" if rules_only else "A canned mock stood in for the model"
    if kind == "screen":
        script: dict[str, Any] = {
            "steps": [
                {"tool": "get_application", "args": {"vendor_id": vendor_id}},
                {"tool": "get_sku_rows", "args": {"vendor_id": vendor_id}},
            ],
            "final": {
                "risk_flags": [],
                "injection_detected": False,
                "followup_questions": [],
                "decision": "pass",
                "reasons": [f"{who}. The deterministic checks (documents, claim rules, injection patterns) decide the outcome."],
            },
        }
    else:
        script = _decide(vendor_id, who)
    return {"model": model, "input_tokens": 0, "output_tokens": 0, "content": json.dumps(script)}


def _decide(vendor_id: str, who: str) -> dict[str, Any]:
    from app.metrics import apply_levers, build_base

    base = build_base(vendor_id)
    lever = apply_levers(base)
    c = lever.summary.counts
    rows = []
    for s in lever.skus:
        why = "; ".join(s.reasons) if s.reasons else s.verdict
        rows.append({"code": s.code, "verdict": s.verdict, "why": why[:1].upper() + why[1:] + "."})
    return {
        "steps": [{"tool": "get_metrics", "args": {"vendor_id": vendor_id, "target_margin_pct_offset": 0}}],
        "final": {
            "headline": (
                f"{c['list']} list, {c['negotiate']} negotiate, {c['reject']} reject and {c['needs_data']} need data "
                f"out of {len(lever.skus)} SKUs. {who}; every verdict is the engine's."
            ),
            "rationale_per_sku": rows,
            "counter_offer": {"terms": [], "email_draft": ""},
            "extractions": [],
        },
    }
