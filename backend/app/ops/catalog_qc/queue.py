"""Catalog QC / fix queue for the live listings of existing vendors.

``generate`` scans every live listing, scores each issue, proposes a fix for it (deterministic where the answer is in the data,
model-written otherwise), verifies every proposed value as a claim and returns the queue. Deciding on fixes happens in
``outbox`` (simulated: nothing is pushed anywhere)."""

from typing import Any

from app import llm, policy
from app.ops import figures as fg
from app.ops.catalog_qc import calc, detect, fixes, labels, score
from app.ops.catalog_qc import data as cdata
from app.ops.catalog_qc.detect import Ctx
from app.ops.data import load as load_ops
from app.ops.review import impact_for

STAGE = fg.STAGE
MODULE = "catalog_qc_queue"
TEXT_ISSUES = fixes.COPY_ISSUES


def _missing_text_attrs(issue: dict[str, Any]) -> list[str]:
    return [m for m in issue["detail"]["missing"] if m != "mrp" and m != "pack" and not m.startswith("pack_")]


async def generate(inject: bool = False) -> dict[str, Any]:
    qc = policy.get().catalog_qc
    data, ops = cdata.load(), load_ops()
    run = fg.new_ctx("catalog", ops.as_of)
    run.emit("stage_started", STAGE, {"task": "catalog_qc", "as_of": ops.as_of.isoformat(), "listings": len(data.listings)})
    scan = await labels.read_labels(run, data, ops.as_of)
    ctx = Ctx(data, ops, ops.as_of, scan.findings)
    issues = detect.scan(ctx)
    run.emit("tool_call", STAGE, {"tool": "scan_catalog", "args": {"listings": len(data.listings)}, "result_summary": f"{len(issues)} issue(s) on {len({i['listing_id'] for i in issues})} listing(s)", "deterministic": True})

    by_listing: dict[str, list[dict[str, Any]]] = {}
    for i in issues:
        by_listing.setdefault(i["listing_id"], []).append(i)
    built: list[fixes.Fix] = []
    wants_model: list[tuple[Any, list[dict[str, Any]], dict[str, Any], list[str]]] = []
    states: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}  # issue id -> why there is no fix
    for x in data.listings:
        mine = by_listing.get(x.listing_id)
        if not mine:
            continue
        of = {t: [i for i in mine if i["type"] == t] for t in {i["type"] for i in mine}}
        copy_issues = [i for i in mine if i["type"] in TEXT_ISSUES]
        rewriting = qc.model_rewrites and bool(copy_issues)
        state = x.snapshot()
        got: list[fixes.Fix | None] = []
        if "mrp_mismatch" in of:
            got.append(fixes.fix_price(ctx, x, of["mrp_mismatch"][0], scan))
        if "pack_mismatch" in of:
            got.append(fixes.fix_pack(ctx, x, of["pack_mismatch"][0], rewriting))
        if "wrong_category" in of:
            got.append(fixes.fix_category(ctx, x, of["wrong_category"][0]))
        if "expired_licence" in of:
            got.append(fixes.fix_licence(ctx, x, of["expired_licence"][0]))
        if "label_mismatch" in of:
            got.append(fixes.fix_label(ctx, x, of["label_mismatch"], scan))
        if "duplicate_listing" in of:
            got.append(fixes.fix_duplicate(ctx, x, of["duplicate_listing"][0]))
        pics = of.get("missing_image", []) + of.get("low_res_image", [])
        if pics:
            got.append(fixes.fix_images(ctx, x, pics, ctx.brand(x.vendor_id)))
        attrs: list[str] = []
        if "missing_attribute" in of:
            got.append(fixes.fix_pack_attribute(ctx, x, of["missing_attribute"][0]))
            attrs = _missing_text_attrs(of["missing_attribute"][0])
        for fx in got:
            if fx is not None:
                built.append(fx)
                state = fixes.apply_changes(state, fx.changes)
        states[x.listing_id] = state
        if qc.model_rewrites and (copy_issues or attrs):
            wants_model.append((x, copy_issues + (of.get("missing_attribute", []) if attrs else []), state, attrs))
        else:
            for i in copy_issues + ([i for i in of.get("missing_attribute", []) if attrs]):
                reasons[i["id"]] = "Model-written fixes are switched off in the playbook" if not qc.model_rewrites else "No fix proposed"

    msgs: list[dict[str, Any]] = []
    previous = ""
    degraded: str | None = None
    if wants_model:
        parsed, msgs, previous, degraded = await fixes.model_fixes(ctx, run, wants_model, scan)
        if degraded:
            run.emit("degraded", STAGE, {"reason": degraded})
        items = {it.listing_id: it for it in parsed.items} if parsed else {}
        for x, listing_issues, state, attrs in wants_model:
            item = items.get(x.listing_id)
            if item is None:
                for i in listing_issues:
                    reasons[i["id"]] = degraded or "The model returned no rewrite for this listing"
                continue
            text_issues = [i for i in listing_issues if i["type"] in TEXT_ISSUES]
            if text_issues:
                fx = fixes.copy_fix(ctx, x, text_issues, state, item, scan)
                if fx is not None:
                    built.append(fx)
                else:
                    for i in text_issues:
                        reasons[i["id"]] = "The model left the text unchanged"
            attr_issue = next((i for i in listing_issues if i["type"] == "missing_attribute"), None)
            if attr_issue is not None and attrs:
                ax = fixes.attribute_fix(ctx, x, attr_issue, item, attrs)
                if ax is not None:
                    existing = next((f for f in built if f.id == ax.id), None)
                    if existing is not None:  # a pack attribute was filled deterministically: one attributes fix per listing
                        existing.changes += ax.changes
                        existing.claims += ax.claims
                        existing.source = "model" if existing.source != "model" else existing.source
                        existing.title += "; and " + ax.title[0].lower() + ax.title[1:]
                    else:
                        built.append(ax)
                else:
                    reasons[attr_issue["id"]] = "The listing does not say what these attributes are"

    claims = await fixes.verify_fixes(run, built, msgs, previous, inject)
    built.sort(key=lambda f: (f.listing_id, fixes.ORDER.index(f.kind)))
    fix_of = {iid: f for f in built for iid in f.issue_ids}

    gmv_days = qc.gmv_window_days
    gmv = {x.listing_id: calc.listing_gmv(ops, x.sku_code, x.gmv_share, gmv_days) for x in data.listings}
    top_gmv = max(gmv.values(), default=0.0)
    rows = []
    for i in issues:
        x = data.listing(i["listing_id"])
        assert x is not None
        returned, sold = calc.nad_stats(ops, x.sku_code, qc.returns.reasons, qc.returns.window_days)
        rate = 100 * returned / sold if sold else None
        sig = score.signals(gmv[x.listing_id], top_gmv, i["severity"], rate)
        fx = fix_of.get(i["id"])
        rows.append(
            {
                **i,
                "brand": ctx.brand(x.vendor_id), "listing_title": x.title, "gmv_at_risk_inr": gmv[x.listing_id], "signals": sig, "score": score.priority(sig),
                "nad_rate_pct": round(rate, 3) if rate is not None else None,
                "fix_id": fx.id if fx else None, "fix_status": fx.status if fx else "none", "no_fix_reason": None if fx else reasons.get(i["id"], "This needs a person: no automatic fix"),
            }
        )
    rows = score.rank(rows)

    listings = []
    for x in data.listings:
        mine = [f for f in built if f.listing_id == x.listing_id]
        if not by_listing.get(x.listing_id):
            continue
        listings.append(
            {
                "listing_id": x.listing_id, "vendor_id": x.vendor_id, "brand": ctx.brand(x.vendor_id), "sku_code": x.sku_code, "title": x.title,
                "before": x.snapshot(), "fix_ids": [f.id for f in mine], "issue_ids": [i["id"] for i in by_listing[x.listing_id]],
                "gmv_at_risk_inr": gmv[x.listing_id], "top_score": max(r["score"] for r in rows if r["listing_id"] == x.listing_id),
                "label": scan.cards.get(x.listing_id),
            }
        )
    listings.sort(key=lambda r: (-r["top_score"], r["listing_id"]))

    all_claims = [*scan.claims, *claims]
    n = lambda status: sum(1 for c in all_claims if c.status == status)  # noqa: E731
    mode = llm.resolve_mode(STAGE)
    trace = fg.drain(run)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    return {
        "as_of": ops.as_of.isoformat(),
        "mode": mode,
        "degraded": bool(degraded) or any(t["type"] == "degraded" for t in trace),
        "degraded_reason": degraded,
        "vendors": [{"id": v.id, "brand": v.brand} for v in ops.vendors.values()],
        "issue_types": list(policy.QC_ISSUE_TYPES),
        "rows": rows,
        "listings": listings,
        "fixes": {f.id: f.public() for f in built},
        "claims": [c.model_dump(mode="json") for c in all_claims],
        "verification": {"total": len(all_claims), "verified": n("verified"), "rejected": n("rejected"), "unverifiable": n("unverifiable")},
        "corrected": [c.id for c in all_claims if c.status == "verified" and len(c.attempts) > 1],
        "unresolved": [c.id for c in all_claims if c.origin == "model_extraction" and c.status == "rejected"],
        "counts": {"listings": len(data.listings), "listings_with_issues": len(listings), "issues": len(rows), "by_type": by_type},
        "labels_read": len(scan.documents),
        "trace": trace,
        "limits": {"bulk_approve": qc.bulk_approve_limit},
        "impact_coverage": impact_for(MODULE, {"catalog_fix_per_sku": len(listings)}),
    }
