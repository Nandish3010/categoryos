"""Screen agent (stage "intake"): deterministic document check first, then a tool-calling model pass.
Vendor text is data. A deterministic guard backs the model: blocking documents or an injection attempt fail the vendor."""

import re
from typing import Any

from app import docs, llm, policy, prompts, tools
from app.agents.context import RunContext
from app.data_loader import load_application, load_sheet
from app.metrics import build_base
from app.schemas import RiskFlag, ScreenFinal, StageResult

STAGE = "intake"


def _injection() -> re.Pattern[str]:
    return re.compile("|".join(policy.get().screening.injection_patterns), re.IGNORECASE)


def scan_injection(vendor_id: str) -> list[str]:
    """Defence in depth: sentences in vendor-supplied text that look like instructions to an AI reviewer."""
    texts = [str(v) for v in load_application(vendor_id).values() if isinstance(v, str)]
    _, rows = load_sheet(vendor_id)
    texts += [cell for r in rows for cell in r.cells.values()]
    pattern = _injection()
    hits: list[str] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if pattern.search(sentence) and sentence.strip() not in hits:
                hits.append(sentence.strip())
    return hits


def scan_claims(vendor_id: str, rule_types: set[str]) -> list[tuple[str, str, str]]:
    """(rule type, severity, quote) for vendor text that matches a playbook claim rule of one of ``rule_types``."""
    rules = [r for r in policy.get().screening.claim_rules if r.type in rule_types]
    if not rules:
        return []
    application = load_application(vendor_id)
    vendor_categories = list(application.get("categories", []))
    sources: list[tuple[str, list[str]]] = [(str(v), vendor_categories) for v in application.values() if isinstance(v, str)]
    for sku in build_base(vendor_id).skus:
        sources += [(cell, [sku.category]) for cell in sku.raw.values()]
    hits: list[tuple[str, str, str]] = []
    for rule in rules:
        rx = policy.claim_regex(rule)
        for text, cats in sources:
            if not policy.in_scope(rule.categories, cats):
                continue
            for m in rx.finditer(text):
                hit = (rule.type, rule.severity, m.group(0))
                if hit not in hits:
                    hits.append(hit)
    return hits


def missing_application_fields(vendor_id: str) -> list[str]:
    application = load_application(vendor_id)
    return [f for f in policy.get().onboarding.required_application_fields if application.get(f) in (None, "", [], {})]


def scan_flags(scan: docs.DocScan | None, doc_check: dict[str, Any]) -> tuple[list[RiskFlag], list[str]]:
    """Risk flags and follow-up questions from the scanned documents: cross-document mismatches, and a certificate whose
    scan (the ground truth) says it is expiring or expired."""
    if scan is None:
        return [], []
    flags: list[RiskFlag] = []
    followups: list[str] = []
    for f in scan.findings:
        if f["status"] == "mismatch":
            flags.append(RiskFlag(type="document_mismatch", quote=f["message"], severity=f["severity"]))
            followups.append(f"Please explain or correct: {f['message']}.")
        elif f["status"] == "unreliable":
            flags.append(RiskFlag(type="document_unreadable", quote=f["message"], severity="low"))
            followups.append(f"Please send a clearer scan: {f['doc_label']} ({f['field_label']}).")
    for d in scan.documents:
        if d.error:
            flags.append(RiskFlag(type="document_unreadable", quote=f"{d.entry.get('title') or d.label}: {d.error}", severity="low"))
    for entry in doc_check["documents"]:
        if entry.get("source") == "scan" and entry["state"] in {"expired", "expiring_soon"}:
            word = entry["state"].replace("_", " ")
            flags.append(
                RiskFlag(
                    type=f"document_{entry['state']}",
                    quote=f"{entry['type']} scan: valid until {entry['valid_until']} ({word})"
                    + (f"; the application says {entry['declared_valid_until']} ({entry['declared_status']})" if entry["declared_valid_until"] != entry["valid_until"] else ""),
                    severity="high" if entry["state"] == "expired" else "medium",
                )
            )
            if entry["state"] == "expiring_soon":
                followups.append(f"Your {entry['type']} scan shows validity ending {entry['valid_until']}. Please send the renewal as soon as it is issued.")
    return flags, followups


async def run(ctx: RunContext) -> StageResult:
    scan = await docs.run(ctx, ctx.vendor_id, STAGE)
    doc_check = tools.check_documents(ctx.vendor_id, ctx.today, scan.scans() if scan else None)
    ctx.emit(
        "tool_call",
        STAGE,
        {
            "tool": "check_documents",
            "args": {"vendor_id": ctx.vendor_id, "today": ctx.today},
            "result_summary": f"{len(doc_check['documents'])} documents, {len(doc_check['problems'])} problems, blocking={doc_check['blocking']}"
            + (" (scanned certificates override declared dates)" if scan and scan.scans() else ""),
            "deterministic": True,
        },
    )
    scan_notes = [f["message"] for f in scan.mismatches()] if scan else []
    res = await llm.run_tools(
        STAGE,
        f"screen_{ctx.vendor_id}",
        prompts.screen_messages(ctx.vendor_id, doc_check["today"], {**doc_check, **({"scan_findings": scan_notes} if scan_notes else {})}),
        tools.select(tools.SCREEN_TOOLS),
        max_steps=6,
        schema=ScreenFinal,
        on_step=ctx.step_emitter(STAGE),
    )
    ctx.emit(
        "model_call",
        STAGE,
        {
            "task": "screen",
            "mode": res.mode,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "tool_steps": len(res.steps),
        },
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    if res.degraded:
        ctx.emit("degraded", STAGE, {"reason": "no recorded run for this vendor; served the mock fixture"})

    final = res.parsed
    assert isinstance(final, ScreenFinal)
    flags = list(final.risk_flags)
    reasons = list(final.reasons)
    guards: list[str] = []

    injection = final.injection_detected
    hits = scan_injection(ctx.vendor_id) + [h for d in (scan.documents if scan else []) for h in d.injection]
    if hits and not injection:
        injection = True
        guards.append("injection_detected set by deterministic scan")
    if injection and not any(f.type == "prompt_injection" for f in flags):
        flags.append(RiskFlag(type="prompt_injection", quote=hits[0] if hits else "", severity="high"))
        guards.append("prompt_injection flag added")

    fail_on = set(policy.get().screening.fail_on)
    fail = final.decision == "fail"
    if "blocking_document" in fail_on:
        for problem in doc_check["problems"]:
            if problem["severity"] == "blocking":
                if not any(problem["type"].lower() in r.lower() and problem["state"] in r.lower() for r in reasons):
                    reasons.append(problem["detail"])
                fail = True
    if injection and "prompt_injection" in fail_on:
        if not any("inject" in r.lower() for r in reasons):
            reasons.append("The application contains text addressed to an AI reviewer (prompt injection), which was ignored")
        fail = True
    for rule_type, severity, quote in scan_claims(ctx.vendor_id, fail_on - {"blocking_document", "prompt_injection"}):
        if not any(f.type == rule_type and quote.lower() in f.quote.lower() for f in flags):
            flags.append(RiskFlag(type=rule_type, quote=quote, severity=severity))  # type: ignore[arg-type]
            guards.append(f"{rule_type} flag added by deterministic scan")
        label = rule_type.replace("_", " ")
        if not any(label in r.lower() or quote.lower() in r.lower() for r in reasons):
            reasons.append(f"Listing text makes a {label}: \"{quote}\"")
        fail = True
    doc_flags, doc_followups = scan_flags(scan, doc_check)
    flags += doc_flags
    missing = missing_application_fields(ctx.vendor_id)
    if missing:
        flags.append(RiskFlag(type="missing_data", quote=", ".join(missing), severity="low"))
        guards.append("required application field(s) missing: " + ", ".join(missing))
        followups = [*final.followup_questions, *(f"Please provide: {f.replace('_', ' ')}" for f in missing)]
    else:
        followups = list(final.followup_questions)
    followups += [q for q in doc_followups if q not in followups]
    if fail and final.decision == "pass":
        guards.append("decision forced to fail by deterministic guard")
    decision = "fail" if fail else "pass"

    data: dict[str, Any] = {
        "decision": decision,
        "reasons": reasons,
        "risk_flags": [f.model_dump() for f in flags],
        "injection_detected": injection,
        "followup_questions": followups,
        "documents": doc_check,
        "scanned_documents": scan.to_data() if scan else docs.disabled_data(),
        "guards": guards,
        "mode": res.mode,
    }
    claims = scan.claims if scan else []
    if decision == "fail":
        return StageResult(
            stage=STAGE,
            status="failed",
            summary="Screening failed: " + "; ".join(reasons[:3]),
            data=data,
            locked_reason="; ".join(reasons[:3]),
            claims=claims,
        )
    return StageResult(
        stage=STAGE,
        status="done",
        summary=f"Screening passed with {len(flags)} flag(s) to follow up",
        data=data,
        claims=claims,
    )
