"""Launch packet agent: ONE agent that returns results for the stages "marketing", "jbp" and "po".

PO lines, totals and the status timeline are deterministic (alloc units from apply_levers at the approved metrics hash,
vendor unit cost, 18% GST placeholder shown separately); the totals are Claims the verifier recomputes (po_total,
po_grand_total). The model writes the JBP markdown and the campaign from a facts JSON that holds only numbers Python
computed or the verified negotiation produced."""

from datetime import date, timedelta
from typing import Any

from app import llm, media, prompts_exec
from app.agents import shortlist as sl
from app.agents.context import RunContext
from app.constants import GST_RATE, PO_DELAY_DAYS, PO_LEAD_DAYS
from app.data_loader import load_application
from app.errors import CategoryOSError
from app.metrics import apply_levers, build_base
from app.schemas import (
    Claim,
    JbpFinal,
    MarketingFinal,
    SkuMetrics,
    SourceRef,
    StageResult,
)
from app.util import fmt_inr
from app.verify import verify_all

STAGES = ("marketing", "jbp", "po")
NEGOTIATE_TO_TERMS = ("margin_pct", "payment_days", "moq", "marketing_inr", "launch_discount_pct", "returns")


def effective_terms(vendor_id: str, negotiate: StageResult | None) -> dict[str, dict[str, Any]]:
    """Per term: the verified negotiated value if there is one, else the application's proposal."""
    app_terms = load_application(vendor_id)["proposed_terms"]
    fallback = {
        "margin_pct": app_terms.get("margin_offered_pct"),
        "payment_days": app_terms.get("payment_terms_days"),
        "moq": app_terms.get("moq_units"),
        "marketing_inr": app_terms.get("marketing_support_inr"),
        "launch_discount_pct": app_terms.get("launch_discount_pct"),
        "returns": None,
    }
    out = {t: {"value": fallback[t], "source": "application"} for t in NEGOTIATE_TO_TERMS}
    if negotiate is not None:
        for row in negotiate.data.get("gap_table", []):
            if row.get("offered") is not None and row.get("verification") == "verified":
                out[row["term"]] = {"value": row["offered"], "source": "negotiation", "turn": row.get("turn")}
    return out


def po_timeline(today: str) -> list[dict[str, Any]]:
    """Simulated PO status timeline with deterministic dates and one delay alert at 'shipped'."""
    start = date.fromisoformat(today)
    steps = [{"step": "raised", "planned": start, "status": "done"}]
    for step in ("confirmed", "shipped", "received"):
        steps.append({"step": step, "planned": start + timedelta(days=PO_LEAD_DAYS[step]), "status": "scheduled"})
    out = []
    for item in steps:
        row: dict[str, Any] = {"step": item["step"], "status": item["status"], "planned_date": item["planned"].isoformat(), "expected_date": item["planned"].isoformat(), "delay_days": 0}
        if item["step"] in ("shipped", "received"):
            row["expected_date"] = (item["planned"] + timedelta(days=PO_DELAY_DAYS)).isoformat()
            row["delay_days"] = PO_DELAY_DAYS
        if item["step"] == "shipped":
            row["status"] = "delayed"
            row["alert"] = (
                f"Shipment is expected {PO_DELAY_DAYS} days late ({row['planned_date']} -> {row['expected_date']}); "
                "the receipt date moves with it. Confirm the revised dispatch date with the vendor."
            )
        out.append(row)
    return out


def po_lines(skus: list[SkuMetrics]) -> list[dict[str, Any]]:
    lines = []
    for s in skus:
        if s.alloc_units <= 0 or s.cost is None:
            continue
        lines.append(
            {
                "code": s.code,
                "name": s.name,
                "units": s.alloc_units,
                "unit_cost": round(s.cost, 2),
                "cost_source": s.cost_source,
                "line_total": round(s.alloc_units * s.cost, 2),
            }
        )
    return lines


def build_po(vendor_id: str, offset: float, moq: int, skus: list[SkuMetrics], terms: dict[str, Any], today: str) -> tuple[dict[str, Any], list[Claim]]:
    lines = po_lines(skus)
    subtotal = round(sum(line["line_total"] for line in lines), 2)
    gst = round(subtotal * GST_RATE, 2)
    grand = round(subtotal + gst, 2)
    po: dict[str, Any] = {
        "po_number": f"PO-{vendor_id}-{today.replace('-', '')}",
        "vendor_id": vendor_id,
        "date": today,
        "lines": lines,
        "subtotal": subtotal,
        "gst_rate": GST_RATE,
        "gst": gst,
        "grand_total": grand,
        "gst_note": "GST is a placeholder at 18% shown separately; confirm HSN-level rates before issuing",
        "payment_days": terms["payment_days"]["value"],
        "terms_source": {k: v["source"] for k, v in terms.items()},
        "timeline": po_timeline(today),
        "status": "raised",
    }
    key = f"{vendor_id}?offset={offset:g}&moq={moq}&skus={','.join(line['code'] for line in lines)}"
    ref = SourceRef(file=f"vendors/{vendor_id}/application.json", key=key, column="proposed_terms.moq_units")
    claims = [
        Claim(id=f"{vendor_id}:po_total", text=f"PO subtotal for {vendor_id} is {fmt_inr(subtotal)} before GST", value=subtotal, metric="po_total", unit="inr", source_ref=ref, origin="engine"),
        Claim(id=f"{vendor_id}:po_grand_total", text=f"PO grand total for {vendor_id} is {fmt_inr(grand)} including GST", value=grand, metric="po_grand_total", unit="inr", source_ref=ref, origin="engine"),
    ]
    return po, claims


def promo_calendar(today: str) -> list[dict[str, str]]:
    received = date.fromisoformat(today) + timedelta(days=PO_LEAD_DAYS["received"] + PO_DELAY_DAYS)
    launch = received + timedelta(days=2)
    return [
        {"name": "Listings live", "start": launch.isoformat(), "end": launch.isoformat()},
        {"name": "Launch week: sponsored listings and sampling", "start": launch.isoformat(), "end": (launch + timedelta(days=6)).isoformat()},
        {"name": "Launch-month discount window", "start": launch.isoformat(), "end": (launch + timedelta(days=29)).isoformat()},
        {"name": "First sell-through review", "start": (launch + timedelta(days=30)).isoformat(), "end": (launch + timedelta(days=30)).isoformat()},
    ]


def _emit_call(ctx: RunContext, stage: str, task: str, res: Any) -> None:
    ctx.emit(
        "model_call",
        stage,
        {"task": task, "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    if res.degraded:
        ctx.emit("degraded", stage, {"reason": "no recorded run for this vendor; served the mock fixture"})


async def _campaign_image(ctx: RunContext, vendor_id: str, name: str, brand: str, campaign: str) -> dict[str, Any]:
    asset = "campaign.png"
    live = llm.resolve_mode("marketing") == "live"
    source = media.cached_source(vendor_id, asset)
    if live and source != "live":
        prompt = f"Bright e-commerce launch banner for the pet brand {brand}: '{campaign}'. Happy pets, product-forward, clean layout, no small text."
        try:
            data, spend = await media.generate_image(prompt, size="1792x1024")
            media.write_asset(vendor_id, asset, data, "live")
            ctx.emit("model_call", "marketing", {"task": "image_campaign", "mode": "live", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "asset": asset}, model=spend.model, cost_usd=spend.cost_usd)
        except CategoryOSError as exc:
            ctx.emit("degraded", "marketing", {"reason": f"campaign image failed ({exc.code}); placeholder shown"})
    media.ensure_placeholder(vendor_id, asset, "campaign", campaign, brand)
    return {"url": media.asset_url(vendor_id, asset), "image_source": media.cached_source(vendor_id, asset) or "placeholder"}


async def run(ctx: RunContext, research: StageResult, negotiate: StageResult | None) -> dict[str, StageResult]:
    vendor_id = ctx.vendor_id
    lever = sl.research_lever(vendor_id, research)
    verdicts = sl.effective_verdicts(research, lever)
    skus = sl.shortlisted(lever, verdicts)
    brand = load_application(vendor_id)["brand_name"]
    terms = effective_terms(vendor_id, negotiate)
    approved_moq = lever.summary.moq
    # The PO follows the vendor's verified MOQ commitment when there is one; units are allocated by the same engine.
    moq = int(terms["moq"]["value"]) if terms["moq"]["source"] == "negotiation" else approved_moq
    po_lever = lever if moq == approved_moq else apply_levers(build_base(vendor_id), lever.target_margin_pct_offset, moq)
    codes = {s.code for s in skus}
    po_skus = [s for s in po_lever.skus if s.code in codes]

    po, po_claims = build_po(vendor_id, lever.target_margin_pct_offset, moq, po_skus, terms, ctx.today)
    po["moq_source"] = terms["moq"]["source"]
    po["approved_moq"] = approved_moq
    ctx.emit(
        "tool_call",
        "po",
        {"tool": "build_po", "args": {"vendor_id": vendor_id, "moq": moq}, "result_summary": f"{len(po['lines'])} lines, subtotal {fmt_inr(po['subtotal'])}, grand total {fmt_inr(po['grand_total'])}", "deterministic": True},
    )
    verified = verify_all(po_claims)
    for claim in verified.claims:
        ctx.emit("claim_checked", "po", {"claim": claim.model_dump(mode="json")})

    shortlisted_gmv = round(sum(s.est_gmv for s in skus), 2)
    monthly_units = round(sum(s.est_monthly_units for s in skus), 1)
    avg_margin = round(sum((s.margin_pct or 0) * s.est_gmv for s in skus) / shortlisted_gmv, 4) if shortlisted_gmv else None
    calendar = promo_calendar(ctx.today)
    investments = {
        "brand_funded_marketing_inr": terms["marketing_inr"]["value"],
        "launch_discount_pct": terms["launch_discount_pct"]["value"],
        "launch_discount_days": 30,
        "source": {k: terms[k]["source"] for k in ("marketing_inr", "launch_discount_pct")},
    }
    targets = {
        "shortlisted_skus": len(skus),
        "est_monthly_gmv_inr": shortlisted_gmv,
        "est_monthly_units": monthly_units,
        "blended_margin_pct": avg_margin,
        "first_order_units": moq,
        "first_order_cost_inr": po["subtotal"],
        "payment_days": po["payment_days"],
    }
    facts = {
        "brand": brand,
        "targets": targets,
        "investments": investments,
        "promo_calendar": calendar,
        "brand_funded_pct": investments["launch_discount_pct"],
        "agreed_terms": {k: v["value"] for k, v in terms.items()},
        "skus": [{"code": s.code, "name": s.name, "est_gmv_inr": s.est_gmv} for s in sorted(skus, key=lambda s: -s.est_gmv)[:5]],
    }

    jbp_res = await llm.call("jbp", prompts_exec.jbp_messages(vendor_id, brand, facts), task=f"jbp_{vendor_id}", schema=JbpFinal, max_tokens=2500)
    _emit_call(ctx, "jbp", "jbp", jbp_res)
    assert isinstance(jbp_res.parsed, JbpFinal)
    mk_res = await llm.call("marketing", prompts_exec.marketing_messages(vendor_id, brand, facts), task=f"marketing_{vendor_id}", schema=MarketingFinal, max_tokens=1200)
    _emit_call(ctx, "marketing", "marketing", mk_res)
    mk = mk_res.parsed
    assert isinstance(mk, MarketingFinal)

    corrections = []
    ask = mk.discount_ask.model_dump()
    committed = float(investments["launch_discount_pct"] or 0)
    if abs(ask["brand_funded_pct"] - committed) > 1e-9:
        corrections.append({"field": "discount_ask.brand_funded_pct", "model": ask["brand_funded_pct"], "committed": committed})
        ask["brand_funded_pct"] = committed
    image = await _campaign_image(ctx, vendor_id, "campaign", brand, mk.campaign_name)

    marketing = StageResult(
        stage="marketing",
        status="done",
        summary=f"Campaign '{mk.campaign_name}' with a {ask['brand_funded_pct']:g}% brand-funded launch discount",
        data={"campaign_name": mk.campaign_name, "copy": mk.copy_text, "discount_ask": ask, "image": image, "corrections": corrections, "brand_funded_marketing_inr": investments["brand_funded_marketing_inr"], "mode": mk_res.mode},
        metrics_hash=lever.metrics_hash,
    )
    jbp = StageResult(
        stage="jbp",
        status="done",
        summary=f"JBP drafted: {len(skus)} SKUs, {fmt_inr(shortlisted_gmv)} monthly GMV target",
        data={"markdown": jbp_res.parsed.markdown, "targets": targets, "investments": investments, "promo_calendar": calendar, "mode": jbp_res.mode},
        metrics_hash=lever.metrics_hash,
    )
    alerts = [step["alert"] for step in po["timeline"] if step.get("alert")]
    po_result = StageResult(
        stage="po",
        status="review",
        summary=f"PO {po['po_number']}: {len(po['lines'])} lines, {fmt_inr(po['grand_total'])} including GST",
        data={**po, "alerts": alerts, "verification": {"total": verified.total, "verified": verified.verified, "rejected": verified.rejected, "unverifiable": verified.unverifiable}},
        needs_approval=True,
        claims=verified.claims,
        metrics_hash=lever.metrics_hash,
        narrative_hash=lever.metrics_hash,
    )
    return {"marketing": marketing, "jbp": jbp, "po": po_result}
