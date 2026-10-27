"""Pack labels of live listings: the doc-vision pipeline of Catalog (app.docs) reused for existing vendors.

Where a listing has a label photo (data/synthetic/ops/catalog_labels/manifest.json), muse-spark reads the label with
bounding boxes, SAM 3.1 finds the claims panel, the cropped pixels are read a second time, and every number becomes a
``vision_extraction`` claim that the verifier binds to the page pixels and the second read (app.verify.vision_check).
The verified readings are then compared with the listing: MRP, net quantity (against the pack), protein and the licence
number printed on the pack. Reading goes through ``docs._read_page`` itself; only the page lookup differs.

Live shapes are the ones documented in app/docs.py (assumed, unverified until credits land). In mock and replay the gateway
serves backend/fixtures/mock/ops/docs_<vendor>_label_<sku>*.json with the same shapes."""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app import docparse, docs, policy
from app.agents.context import RunContext
from app.errors import CategoryOSError
from app.ops.catalog_qc import calc
from app.ops.catalog_qc.data import LABEL_DIR, CatalogData, Listing, file_sha256, label_path
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Evidence, SourceRef
from app.verify import verify_all

STAGE = "ops"
KIND = "product_label"
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_UNIT = {"pct": "pct", "inr": "inr", "qty": "qty"}


@dataclass
class LabelScan:
    documents: list[docs.DocRead] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)  # verified
    findings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # listing_id -> comparison rows
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)  # listing_id -> label card for the UI

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.id == claim_id), None)


def _resolve(_vendor_id: str, name: str) -> Path | None:
    return label_path(name)


def _url(_vendor_id: str, name: str) -> str:
    return f"/api/ops/catalog/labels/{name}"


def _claim(vendor_id: str, doc: docs.DocRead, f: docs.FieldRead, today: date) -> Claim | None:
    if f.type == "text" or not f.trusted:
        return None
    value = docparse.claim_number(f.type, f.parsed, today)
    if value is None:
        return None
    cid = f"label:{vendor_id}:{doc.sku_code}:{f.name}"
    f.claim_id = cid
    return Claim(
        id=cid,
        text=f"{f.label} on the {doc.entry.get('title') or doc.label} reads {f.raw} ({doc.sku_code})",
        value=value,
        metric=f"doc_value:{KIND}.{f.name}",
        unit=_UNIT.get(f.type, "units"),  # type: ignore[arg-type]
        sku_key=f"{vendor_id}:{doc.sku_code}",
        source_ref=SourceRef(file=f"{LABEL_DIR}/{f.page_file}", key=f"p{f.page}:{f.name}:{doc.sku_code}", column=f.name),
        evidence=Evidence(
            raw_value=f.raw, normalized_value=value, parser_version=PARSER_VERSION, sha256=file_sha256(f"{LABEL_DIR}/{f.page_file}"),
            doc=doc.file, page=f.page, bbox=f.bbox, crop_sha256=f.crop_sha256, reread_value=f.reread, as_of=today.isoformat(),
        ),
        origin="vision_extraction",
    )


def _fmt_listing(field_name: str, listing: Listing) -> tuple[str | None, float | None]:
    """(shown, number) of what the listing says for a label field."""
    if field_name == "mrp":
        return f"₹{listing.mrp:g}", listing.mrp
    if field_name == "net_quantity":
        return listing.pack_size, calc.pack_amount(listing.pack_size)
    if field_name == "protein_pct":
        m = _PERCENT.search(str(listing.attributes.get("protein", "")))
        return (f"{float(m.group(1)):g}%", float(m.group(1)) / 100) if m else (None, None)
    if field_name == "fssai_number":
        return listing.fssai_number or None, None
    return None, None


def _compare(f: docs.FieldRead, listing: Listing) -> dict[str, Any] | None:
    shown, number = _fmt_listing(f.name, listing)
    if shown is None:
        return None
    base = {
        "field": f.name, "field_label": f.label, "label_value": f.display(), "label_number": f.parsed if isinstance(f.parsed, int | float) else None,
        "listing_value": shown, "claim_id": f.claim_id, "claim_status": f.status, "page": f.page, "bbox": f.bbox, "doc": f.page_file,
    }
    if f.status in {"rejected", "conflict"}:
        return {**base, "status": "unreliable"}
    if f.type == "text":
        if f.name == "fssai_number" and not f.raw.upper().startswith("FSSAI"):
            return None  # a pack that prints no licence number (not a food) has nothing to compare
        same = docparse.norm_text(f.raw) == docparse.norm_text(shown)
    else:
        unit = {"mrp": "inr", "net_quantity": "qty", "protein_pct": "pct"}[f.name]
        if number is None or not isinstance(f.parsed, int | float):
            return None
        same = abs(float(f.parsed) - number) <= policy.tol(unit)
    return {**base, "status": "match" if same else "mismatch"}


async def read_labels(ctx: RunContext, data: CatalogData, today: date) -> LabelScan:
    """Read every label the manifest lists, verify the readings, compare them with the listings. Never raises for a bad
    scan: the document carries its error and the listing is simply not compared."""
    scan = LabelScan()
    pol = policy.get().documents
    if not pol.enabled:
        return scan
    cfg = next((k for k in pol.kinds if k.kind == KIND), None)
    entries = [e for e in data.labels if e.get("kind") == KIND]
    if cfg is None or not entries:
        return scan
    ctx.emit("tool_call", STAGE, {"tool": "read_documents", "args": {"files": [e["file"] for e in entries]}, "result_summary": f"{len(entries)} pack label(s) to read with vision", "deterministic": True})
    for entry in entries:
        vendor_id = str(entry["vendor_id"])
        doc = docs.DocRead(entry=dict(entry), label=cfg.label)
        try:
            for n, page_file in enumerate([str(p) for p in entry.get("pages") or [entry["file"]]][: pol.max_pages], 1):
                await docs._read_page(ctx, vendor_id, STAGE, doc, n, page_file, cfg, today, resolve=_resolve, url=_url)
        except CategoryOSError as exc:
            doc.error = f"{exc.code}: {exc.problem}"
            ctx.emit("degraded", STAGE, {"reason": f"{doc.file} could not be read ({exc.code}); the listing is not compared with its label"})
        scan.documents.append(doc)
    readable = [d for d in scan.documents if d.legible and not d.error]
    claims = [c for d in readable for f in d.fields if (c := _claim(str(d.entry["vendor_id"]), d, f, today)) is not None]
    checked = verify_all(claims).claims
    by_id = {c.id: c for c in checked}
    for d in readable:
        for f in d.fields:
            c = by_id.get(f.claim_id or "")
            if c is not None:
                f.status, f.reason = c.status, c.reason
            elif f.type == "text" and f.trusted and f.reread is not None:
                same = docparse.norm_text(f.reread) == docparse.norm_text(f.raw)
                f.status, f.reason = ("verified", None) if same else ("conflict", f"the page read says {f.raw!r} but the re-read says {f.reread!r}")
    for c in checked:
        ctx.emit("claim_checked", STAGE, {"claim": c.model_dump(mode="json")})
    scan.claims = checked
    for d in readable:
        sku = d.sku_code
        mine = [x for x in data.listings if x.sku_code == sku]
        if not mine:
            continue
        listing = max(mine, key=lambda x: (x.gmv_share, x.listing_id))  # the SKU's main listing
        rows = [r for f in d.fields if (r := _compare(f, listing)) is not None]
        scan.findings[listing.listing_id] = rows
        scan.cards[listing.listing_id] = {
            "doc": d.file, "title": d.entry.get("title") or d.label, "url": _url(listing.vendor_id, d.file), "panel": d.panel, "rows": rows,
            "mismatches": sum(1 for r in rows if r["status"] == "mismatch"),
        }
    return scan
