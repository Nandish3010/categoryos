"""Issue detectors: one pure function per issue type over the live listings. Thresholds and severities come from the
playbook (catalog_qc, catalog.title_max_chars, catalog.required_attributes, screening.claim_rules). No model involved.

An issue is a plain dict: {id, listing_id, vendor_id, sku_code, type, severity, message, detail}. ``detail`` carries the
evidence the fix and the verifier need (the price-list row, the classifier's answer, the licence record, ...)."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app import policy
from app.ops.catalog_qc import calc
from app.ops.catalog_qc.data import CatalogData, Listing
from app.ops.data import OpsData

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Ctx:
    data: CatalogData
    ops: OpsData
    as_of: date
    labels: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # listing_id -> comparison findings (see labels.py)

    @property
    def qc(self) -> policy.CatalogQc:
        return policy.get().catalog_qc

    def brand(self, vendor_id: str) -> str:
        return self.ops.vendors[vendor_id].brand

    def active(self) -> list[Listing]:
        return [x for x in self.data.listings if x.status == "active"]


def _issue(x: Listing, kind: str, message: str, ctx: Ctx, severity: str | None = None, **detail: Any) -> dict[str, Any]:
    sev = severity or getattr(ctx.qc.severities, kind)
    return {
        "id": f"{x.listing_id}:{kind}", "listing_id": x.listing_id, "vendor_id": x.vendor_id, "sku_code": x.sku_code, "type": kind,
        "severity": sev, "message": message, "detail": detail,
    }


def title_too_long(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    limit = policy.get().catalog.title_max_chars
    if len(x.title) <= limit:
        return []
    return [_issue(x, "title_too_long", f"Title is {len(x.title)} characters; the limit is {limit}", ctx, chars=len(x.title), limit=limit)]


def title_missing_attributes(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    missing = calc.title_missing(x.title, x.pack_size, ctx.brand(x.vendor_id), ctx.qc.title_required)
    if not missing:
        return []
    return [_issue(x, "title_missing_attributes", f"Title does not contain the {' and '.join(missing)}", ctx, missing=missing, brand=ctx.brand(x.vendor_id), pack_size=x.pack_size)]


def missing_attribute(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    missing = [a for a in policy.required_attributes(x.category) if not calc.has_attribute(a, x.attributes, x.mrp, x.pack_size)]
    if not missing:
        return []
    return [_issue(x, "missing_attribute", f"Required attribute(s) missing for {x.category}: {', '.join(missing)}", ctx, missing=missing, category=x.category)]


def banned_claim(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    hits: list[dict[str, str]] = []
    for where, text in (("title", x.title), *((f"bullet {i}", b) for i, b in enumerate(x.bullets, 1)), ("description", x.description)):
        hits += calc.claim_hits(text, x.category, where)
    if not hits:
        return []
    top = max((h["severity"] for h in hits), key=SEVERITY_RANK.__getitem__)
    sev = max((top, ctx.qc.severities.banned_claim), key=SEVERITY_RANK.__getitem__)
    shown = ", ".join(sorted({f"'{h['text']}'" for h in hits}))
    return [_issue(x, "banned_claim", f"Claim(s) the playbook bans or does not allow without proof: {shown}", ctx, severity=sev, hits=hits)]


def _label_value(ctx: Ctx, x: Listing, field_name: str) -> dict[str, Any] | None:
    return next((f for f in ctx.labels.get(x.listing_id, []) if f["field"] == field_name and f["status"] != "unreliable"), None)


def mrp_mismatch(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    price = ctx.data.latest_price(x.sku_code, ctx.as_of)
    label = _label_value(ctx, x, "mrp")
    tol = policy.tol("inr")
    detail: dict[str, Any] = {"listing_mrp": x.mrp}
    if price is not None:
        detail.update(price_list_mrp=price.mrp, effective_date=price.effective_date.isoformat(), price_list_row=price.row)
        bad = abs(price.mrp - x.mrp) > tol
    elif label is not None and label["label_number"] is not None:
        detail.update(label_mrp=label["label_number"], label_claim_id=label["claim_id"])
        bad = abs(label["label_number"] - x.mrp) > tol
    else:
        return []
    if label is not None and label["label_number"] is not None:
        detail["label_mrp"] = label["label_number"]
        detail["label_claim_id"] = label["claim_id"]
    if not bad:
        return []
    truth = detail.get("price_list_mrp", detail.get("label_mrp"))
    src = "latest price list" if price is not None else "pack label"
    return [_issue(x, "mrp_mismatch", f"MRP on the listing is ₹{x.mrp:g}; the {src} says ₹{truth:g}", ctx, **detail)]


def pack_mismatch(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    price = ctx.data.latest_price(x.sku_code, ctx.as_of)
    if price is None or calc.same_pack(x.pack_size, price.pack_size):
        return []
    label = _label_value(ctx, x, "net_quantity")
    detail = {"listing_pack": x.pack_size, "price_list_pack": price.pack_size, "effective_date": price.effective_date.isoformat(), "price_list_row": price.row}
    if label is not None:
        detail["label_net_quantity"] = label["label_value"]
    return [_issue(x, "pack_mismatch", f"Pack size on the listing is {x.pack_size}; the latest price list says {price.pack_size}", ctx, **detail)]


def duplicate_listing(ctx: Ctx) -> list[dict[str, Any]]:
    """Pairs of active listings in the same category and subcategory whose names overlap at or above the threshold. The issue goes
    on the listing that sells less (ties: the newer one); the other is the one to keep."""
    threshold = ctx.qc.near_duplicate_threshold
    days = ctx.qc.gmv_window_days
    active = ctx.active()
    out, seen = [], set()
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if (a.category, a.subcategory) != (b.category, b.subcategory):
                continue
            sim = calc.similarity(a, b, ctx.brand(a.vendor_id))
            if sim < threshold:
                continue
            gm = {x.listing_id: calc.listing_gmv(ctx.ops, x.sku_code, x.gmv_share, days) for x in (a, b)}
            drop, keep = sorted((a, b), key=lambda x: (gm[x.listing_id], x.listed_on, x.listing_id))
            if drop.listing_id in seen:
                continue
            seen.add(drop.listing_id)
            out.append(_issue(drop, "duplicate_listing", f"Near-duplicate of {keep.listing_id} (name overlap {sim:.2f})", ctx, duplicate_of=keep.listing_id, similarity=sim, threshold=threshold))
    return out


def wrong_category(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    c = calc.classify(ctx.ops, x)
    if c.category != x.category:
        sub = c.subcategory if calc.valid_subcategory(c) else x.subcategory
        return [_issue(x, "wrong_category", f"Filed under {x.category} / {x.subcategory}; the taxonomy classifies it as {c.category} / {sub}", ctx,
                       listed=[x.category, x.subcategory], classified=[c.category, sub], level="category")]
    if calc.valid_subcategory(c) and c.subcategory != x.subcategory:
        return [_issue(x, "wrong_category", f"Subcategory is {x.subcategory}; the taxonomy classifies it as {c.subcategory}", ctx,
                       listed=[x.category, x.subcategory], classified=[c.category, c.subcategory], level="subcategory")]
    return []


def missing_image(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    if x.image_count >= ctx.qc.images.min_count and x.image_count > 0:
        return []
    return [_issue(x, "missing_image", f"The listing has {x.image_count} image(s); at least {max(ctx.qc.images.min_count, 1)} is required", ctx, image_count=x.image_count)]


def low_res_image(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    side = min(x.image_width, x.image_height)
    if x.image_count == 0 or side >= ctx.qc.images.min_resolution_px:
        return []
    return [_issue(x, "low_res_image", f"Main image is {x.image_width}x{x.image_height} px; the minimum is {ctx.qc.images.min_resolution_px} px on the short side", ctx,
                   width=x.image_width, height=x.image_height, min_px=ctx.qc.images.min_resolution_px)]


def high_returns(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    """Returns citing 'not as described' as a share of units sold. Reported on the main listing of a SKU (a duplicate listing
    of the same SKU shares the SKU's returns)."""
    twins = [y for y in ctx.data.listings if y.sku_code == x.sku_code]
    if x is not max(twins, key=lambda y: (y.gmv_share, y.listing_id)):
        return []
    r = ctx.qc.returns
    returned, sold = calc.nad_stats(ctx.ops, x.sku_code, r.reasons, r.window_days)
    if sold <= 0 or returned < r.min_returned_units:
        return []
    rate = 100 * returned / sold
    if rate < r.threshold_pct:
        return []
    return [_issue(x, "high_returns_not_as_described", f"{returned} of {sold} units sold came back citing 'not as described' ({rate:.2f}%, threshold {r.threshold_pct:g}%)", ctx,
                   returned=returned, sold=sold, rate_pct=round(rate, 3), window_days=r.window_days, threshold_pct=r.threshold_pct)]


def expired_licence(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    if not x.fssai_number:
        return []
    lic = ctx.data.licence(x.fssai_number)
    if lic is None or lic.valid_until >= ctx.as_of:
        return []
    repl = ctx.data.valid_licence(x.vendor_id, lic.type, ctx.as_of)
    days = (lic.valid_until - ctx.as_of).days
    return [_issue(x, "expired_licence", f"{lic.type} licence {lic.number} expired on {lic.valid_until.isoformat()} ({-days} days ago)"
                   + (f"; a renewed licence {repl.number} is on file" if repl else "; nothing newer is on file"), ctx,
                   number=lic.number, valid_until=lic.valid_until.isoformat(), days_left=days, replacement=repl.number if repl else None,
                   replacement_valid_until=repl.valid_until.isoformat() if repl else None)]


def label_mismatch(ctx: Ctx, x: Listing) -> list[dict[str, Any]]:
    """The pack label disagrees with the listing on a field the price list does not cover (protein, licence number)."""
    out = []
    for f in ctx.labels.get(x.listing_id, []):
        if f["status"] != "mismatch" or f["field"] in ("mrp", "net_quantity"):
            continue
        out.append(_issue(x, "label_mismatch", f"{f['field_label']} on the pack label is {f['label_value']}; the listing says {f['listing_value']}", ctx,
                          field=f["field"], label_value=f["label_value"], listing_value=f["listing_value"], claim_id=f["claim_id"], doc=f["doc"]))
    return out


PER_LISTING = (title_too_long, title_missing_attributes, missing_attribute, banned_claim, mrp_mismatch, pack_mismatch, wrong_category,
               missing_image, low_res_image, high_returns, expired_licence, label_mismatch)


def scan(ctx: Ctx) -> list[dict[str, Any]]:
    """Every issue on every listing that is live (a retired or held listing is not scanned)."""
    issues: list[dict[str, Any]] = []
    for x in ctx.active():
        for fn in PER_LISTING:
            issues += fn(ctx, x)
    issues += duplicate_listing(ctx)
    return issues
