"""Document vision: vendor documents arrive as scans, photos and PDFs, and the vision model reads them.

Per document page:
  1. muse-spark-1.3 (vision) extracts the playbook's fields, each with a bounding box.
  2. For a label, SAM 3.1 segments the nutrition / claims panel (``catalog.label_panel_prompt``); for the other kinds the
     critical fields are cropped by their own boxes. Either way the cropped pixels are read a second time.
  3. Every numeric or date field becomes a ``vision_extraction`` claim with evidence {doc, page, bbox, crop_sha256, the
     second read}; the verifier checks the evidence, never the model's say-so.
  4. Cross-document checks (certificate vs application, label vs sheet vs listing copy, price list vs sheet) compare
     the verified readings. Which kinds are read, which fields, which pairs and tolerances: the playbook (documents).

Live shapes (ASSUMED, to check against a real response once credits land):
  * Vision input: chat completions with a user message whose content is a list of {type: text} and
    {type: image_url, image_url: {url: data:image/png;base64,...}} parts, JSON-schema response_format.
  * Bounding boxes come back as [x0, y0, x1, y1] fractions of the page (origin top left).
  * SAM returns the panel as a box and mask token (see app.media); the mask extent is preferred.
  * PDFs are read page by page from rasterised page images listed in the vendor's manifest; the server does not render PDFs.
In mock and replay mode the gateway serves fixtures with the same shapes (backend/fixtures/mock/{intake,catalog}/docs_*)."""

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app import docparse, llm, media, policy, prompts_docs
from app.agents.context import RunContext
from app.config import settings
from app.data_loader import doc_path, load_application, load_doc_manifest, load_sheet
from app.errors import CategoryOSError
from app.parsing import PARSER_VERSION, map_columns, parse_pack, parse_price
from app.schemas import (
    Claim,
    Evidence,
    SourceRef,
    VisionExtraction,
    VisionReread,
)
from app.verify import verify_all

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}
_FIELD_TOL_UNIT = {"pct": "pct", "inr": "inr", "qty": "qty", "number": "units", "date": "units"}


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", Path(name).stem).strip("_")


def doc_url(vendor_id: str, name: str) -> str:
    return f"/api/docs/{vendor_id}/{name}"


def _inr(value: float) -> str:
    return f"₹{value:,.2f}"


# ---------- reading ----------


@dataclass
class FieldRead:
    name: str
    label: str
    type: str
    raw: str
    bbox: list[float]
    confidence: float
    page: int
    page_file: str
    sku_code: str | None = None
    reread: str | None = None
    crop_sha256: str = ""
    status: str = "read"  # read | verified | rejected | unverifiable | low_confidence | unreadable | conflict
    reason: str | None = None
    claim_id: str | None = None

    @property
    def parsed(self) -> float | date | str | None:
        return docparse.parse_value(self.type, self.raw)

    @property
    def trusted(self) -> bool:
        return self.status not in {"low_confidence", "unreadable"}

    def display(self) -> str:
        v = self.parsed
        if v is None:
            return self.raw
        return _fmt(self.type, v, self.raw)

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "raw": self.raw,
            "value": self.display(),
            "reread": self.reread,
            "page": self.page,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "sku_code": self.sku_code,
            "status": self.status,
            "reason": self.reason,
            "claim_id": self.claim_id,
        }


def _fmt(kind: str, value: float | date | str, raw: str = "") -> str:
    if isinstance(value, date):
        return value.isoformat()
    if kind == "pct" and isinstance(value, float):
        return f"{value * 100:g}%"
    if kind == "inr" and isinstance(value, float):
        return _inr(value)
    if kind == "qty" and isinstance(value, float):
        return raw or f"{value:g}"
    return raw if isinstance(value, str) else f"{value:g}"


@dataclass
class DocRead:
    entry: dict[str, Any]
    label: str
    pages: list[dict[str, Any]] = field(default_factory=list)
    fields: list[FieldRead] = field(default_factory=list)
    legible: bool = True
    error: str | None = None
    notes: str = ""
    mode: str = ""
    panel: dict[str, Any] | None = None
    injection: list[str] = field(default_factory=list)

    @property
    def file(self) -> str:
        return str(self.entry["file"])

    @property
    def kind(self) -> str:
        return str(self.entry["kind"])

    @property
    def sku_code(self) -> str | None:
        return self.entry.get("sku_code")

    def get(self, name: str, sku: str | None = None) -> FieldRead | None:
        for f in self.fields:
            if f.name == name and (sku is None or f.sku_code == sku):
                return f
        return None

    def expiry(self, today: date) -> dict[str, Any] | None:
        f = self.get("valid_until")
        end = f.parsed if f and f.trusted and f.status not in {"rejected", "conflict"} else None
        if not isinstance(end, date):
            return None
        warn = policy.get().screening.expiry_warning_days
        state = "expired" if end < today else "expiring_soon" if end <= today + timedelta(days=warn) else "valid"
        return {"valid_until": end.isoformat(), "days": (end - today).days, "state": state, "as_of": today.isoformat()}

    def public(self, vendor_id: str, today: date) -> dict[str, Any]:
        return {
            "file": self.file,
            "kind": self.kind,
            "label": self.label,
            "title": self.entry.get("title") or self.label,
            "declares": self.entry.get("declares"),
            "sku_code": self.sku_code,
            "url": doc_url(vendor_id, self.file),
            "pages": self.pages,
            "legible": self.legible,
            "error": self.error,
            "notes": self.notes,
            "mode": self.mode,
            "panel": self.panel,
            "expiry": self.expiry(today),
            "injection": self.injection,
            "fields": [f.public() for f in self.fields],
        }


@dataclass
class DocScan:
    """Everything the vision pipeline produced for one stage."""

    vendor_id: str
    today: date
    documents: list[DocRead] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)  # already verified

    def scans(self) -> dict[str, dict[str, Any]]:
        """Application document type -> what its scanned certificate says (ground truth for Screen)."""
        out: dict[str, dict[str, Any]] = {}
        for d in self.documents:
            exp = d.expiry(self.today)
            declares = d.entry.get("declares")
            if declares and exp:
                out[str(declares)] = {"valid_until": exp["valid_until"], "file": d.file}
        return out

    def mismatches(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f["status"] in {"mismatch", "unreliable", "injection"}]

    def summary(self) -> dict[str, Any]:
        counts = {s: sum(1 for c in self.claims if c.status == s) for s in ("verified", "rejected", "unverifiable")}
        return {
            "documents": len(self.documents),
            "fields": sum(len(d.fields) for d in self.documents),
            "claims": len(self.claims),
            **counts,
            "mismatches": len(self.mismatches()),
        }

    def to_data(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "documents": [d.public(self.vendor_id, self.today) for d in self.documents],
            "findings": self.findings,
            "summary": self.summary(),
        }


def disabled_data() -> dict[str, Any]:
    return {"enabled": False, "documents": [], "findings": [], "summary": {"documents": 0, "fields": 0, "claims": 0, "verified": 0, "rejected": 0, "unverifiable": 0, "mismatches": 0}}


def _emit_model_call(ctx: RunContext, stage: str, task: str, res: Any, doc: str) -> None:
    ctx.emit(
        "model_call",
        stage,
        {"task": task, "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0, "document": doc},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )


def _mock_panel_box(stage: str, task: str) -> list[float] | None:
    path = Path(settings.fixtures_dir) / "mock" / stage / f"{task}_panel.json"
    if not path.exists():
        return None
    box = json.loads(path.read_text()).get("bbox")
    return docparse.clamp_bbox(box) if isinstance(box, list) and len(box) == 4 else None


async def _find_panel(ctx: RunContext, stage: str, task: str, page_png: bytes, doc: str) -> tuple[list[float] | None, str]:
    """(box, source). Live: SAM 3.1. Mock and replay: the recorded box. None when unavailable."""
    phrase = policy.get().catalog.label_panel_prompt
    if not settings.sam_enabled:
        return None, "SAM disabled (go/no-go fallback)"
    if llm.resolve_mode(stage) != "live":
        box = _mock_panel_box(stage, task)
        if box is None:
            return None, "no recorded panel for this page"
        ctx.emit("model_call", stage, {"task": "segment_panel", "mode": "mock", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "document": doc}, model=settings.model_seg, cost_usd=0.0)
        return box, "sam-3.1 (mock fixture)"
    try:
        box, spend = await media.segment_region(page_png, phrase)
    except CategoryOSError as exc:
        return None, f"SAM unusable: {exc.code}"
    ctx.emit("model_call", stage, {"task": "segment_panel", "mode": "live", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "document": doc}, model=spend.model, cost_usd=spend.cost_usd)
    return box, "sam-3.1"


def _inside(inner: list[float], outer: list[float]) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _apply_reads(targets: list[FieldRead], reads: list[Any]) -> None:
    """Match the model's reads to the fields it was asked about: by position when the counts agree, else by name."""
    if len(reads) == len(targets) and all(r.name == t.name for r, t in zip(reads, targets)):
        for t, r in zip(targets, reads):
            t.reread = r.value.strip() or None
        return
    pool = list(reads)
    for t in targets:
        hit = next((r for r in pool if r.name == t.name and (r.sku_code or None) == (t.sku_code or None)), None)
        if hit is not None:
            pool.remove(hit)
            t.reread = hit.value.strip() or None


async def _read_page(
    ctx: RunContext, vendor_id: str, stage: str, doc: DocRead, page_no: int, page_file: str, cfg: Any, today: date
) -> None:
    pol = policy.get().documents
    path = doc_path(vendor_id, page_file)
    if path is None:
        doc.error = f"page {page_file!r} is not in the vendor's document manifest"
        return
    png = path.read_bytes()
    img = docparse.open_image(png)
    doc.pages.append({"page": page_no, "file": page_file, "url": doc_url(vendor_id, page_file), "width": img.width, "height": img.height})
    task = f"docs_{vendor_id}_{slug(page_file)}"
    res = await llm.call(stage, prompts_docs.extract_messages(doc.kind, png, page_no, "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"), task=task, schema=VisionExtraction, max_tokens=3000)
    _emit_model_call(ctx, stage, "doc_extract", res, doc.file)
    doc.mode = res.mode
    ext = res.parsed
    assert isinstance(ext, VisionExtraction)
    doc.notes = ext.notes
    if ext.kind != doc.kind or not ext.legible:
        doc.legible = False
        doc.error = f"the page reads as a {ext.kind!r} and the vendor filed it as {doc.kind!r}" if ext.kind != doc.kind else (ext.notes or "the page is not legible")
        return
    wanted = {f.name: f for f in pol.fields if f.kind == doc.kind}
    for item in ext.fields:
        spec = wanted.get(item.name)
        if spec is None or not item.value.strip():
            continue
        bbox = docparse.clamp_bbox(item.bbox)
        fr = FieldRead(
            name=spec.name, label=spec.label, type=spec.type, raw=item.value.strip(), bbox=bbox, confidence=float(item.confidence),
            page=page_no, page_file=page_file, sku_code=item.sku_code or doc.sku_code,
        )
        if not docparse.valid_bbox(bbox):
            fr.status, fr.reason = "unreadable", "the model returned a box outside the page"
        elif fr.confidence < pol.min_confidence:
            fr.status, fr.reason = "low_confidence", f"read at {fr.confidence:.2f}, below the playbook minimum {pol.min_confidence:g}"
        elif spec.type != "text" and fr.parsed is None:
            fr.status, fr.reason = "unreadable", f"{fr.raw!r} cannot be read as a {spec.type}"
        else:
            fr.crop_sha256 = docparse.crop_digest(docparse.crop(img, bbox))
        doc.fields.append(fr)
    page_fields = [f for f in doc.fields if f.page == page_no and f.trusted]

    # second read: the SAM panel for labels, else the critical fields by their own boxes
    done: set[int] = set()
    if cfg.panel:
        box, source = await _find_panel(ctx, stage, task, png, doc.file)
        doc.panel = {"page": page_no, "bbox": box, "prompt": policy.get().catalog.label_panel_prompt, "source": source, "crop_sha256": None}
        if box is not None and docparse.valid_bbox(box):
            doc.panel["crop_sha256"] = docparse.crop_digest(docparse.crop(img, box))
            inside = [f for f in page_fields if _inside(f.bbox, box)]
            if inside:
                panel_png = docparse.crop_png(docparse.crop(img, box, pol.crop_padding))
                rr = await llm.call(
                    stage, prompts_docs.reread_messages(doc.kind, [(f.name, f.sku_code) for f in inside], [panel_png], panel=True),
                    task=f"{task}_reread", schema=VisionReread, max_tokens=1500,
                )
                _emit_model_call(ctx, stage, "doc_reread_panel", rr, doc.file)
                assert isinstance(rr.parsed, VisionReread)
                _apply_reads(inside, rr.parsed.reads)
                done = {id(f) for f in inside}
    crit = {f.name for f in pol.fields if f.kind == doc.kind and f.critical}
    fallback = cfg.panel and not done
    todo = [f for f in page_fields if id(f) not in done and (f.name in crit or (fallback and f.type != "text"))]
    if todo:
        crops = [docparse.crop_png(docparse.crop(img, f.bbox, pol.crop_padding)) for f in todo]
        rr = await llm.call(
            stage, prompts_docs.reread_messages(doc.kind, [(f.name, f.sku_code) for f in todo], crops, panel=False),
            task=f"{task}_reread" + ("_fields" if done else ""), schema=VisionReread, max_tokens=1500,
        )
        _emit_model_call(ctx, stage, "doc_reread_fields", rr, doc.file)
        assert isinstance(rr.parsed, VisionReread)
        _apply_reads(todo, rr.parsed.reads)


# ---------- claims ----------


def _claim_for(vendor_id: str, doc: DocRead, f: FieldRead, today: date) -> Claim | None:
    if f.type == "text" or not f.trusted:
        return None
    parsed = f.parsed
    value = docparse.claim_number(f.type, parsed, today)
    if value is None:
        return None
    sku = f.sku_code
    rel = f"vendors/{vendor_id}/docs/{f.page_file}"
    is_date = f.type == "date"
    metric = f"{'doc_date' if is_date else 'doc_value'}:{doc.kind}.{f.name}"
    unit = {"pct": "pct", "inr": "inr", "qty": "qty"}.get(f.type, "units")
    if is_date:
        text = f"{f.label} on {doc.entry.get('title') or doc.label} reads {parsed.isoformat()} ({int(value)} days from {today.isoformat()})"  # type: ignore[union-attr]
    else:
        text = f"{f.label} on {doc.entry.get('title') or doc.label} reads {f.raw}" + (f" ({sku})" if sku else "")
    cid = re.sub(r"[^A-Za-z0-9_.:-]+", "_", f"{vendor_id}:{slug(doc.file)}:p{f.page}:{f.name}:{sku or '-'}:vision")
    f.claim_id = cid
    return Claim(
        id=cid,
        text=text,
        value=value,
        metric=metric,
        unit=unit,  # type: ignore[arg-type]
        sku_key=f"{vendor_id}:{sku}" if sku else None,
        source_ref=SourceRef(file=rel, key=f"p{f.page}:{f.name}" + (f":{sku}" if sku else ""), column=f.name),
        evidence=Evidence(
            raw_value=f.raw,
            normalized_value=parsed.isoformat() if isinstance(parsed, date) else value,
            parser_version=PARSER_VERSION,
            sha256=docparse.sha256_bytes((doc_path(vendor_id, f.page_file) or Path()).read_bytes()),
            doc=doc.file,
            page=f.page,
            bbox=f.bbox,
            crop_sha256=f.crop_sha256,
            reread_value=f.reread,
            as_of=today.isoformat(),
        ),
        origin="vision_extraction",
    )


def _verify(ctx: RunContext, stage: str, vendor_id: str, docs: list[DocRead], today: date) -> list[Claim]:
    claims = [c for d in docs for f in d.fields if (c := _claim_for(vendor_id, d, f, today)) is not None]
    checked = verify_all(claims)
    by_id = {c.id: c for c in checked.claims}
    for d in docs:
        for f in d.fields:
            c = by_id.get(f.claim_id or "")
            if c is not None:
                f.status, f.reason = c.status, c.reason
            elif f.type == "text" and f.trusted and f.reread is not None and docparse.norm_text(f.reread) != docparse.norm_text(f.raw):
                f.status, f.reason = "conflict", f"the page read says {f.raw!r} but the re-read says {f.reread!r}"
            elif f.type == "text" and f.trusted and f.reread is not None:
                f.status = "verified"
    for c in checked.claims:
        ctx.emit("claim_checked", stage, {"claim": c.model_dump(mode="json")})
    return checked.claims


# ---------- cross-document checks ----------


def _tolerance(check: Any, ftype: str) -> float:
    return float(check.tolerance) if check.tolerance is not None else policy.tol(_FIELD_TOL_UNIT.get(ftype, "units"))


def _sheet_rows(vendor_id: str) -> tuple[dict[str, str], dict[str, Any]]:
    headers, rows = load_sheet(vendor_id)
    columns = map_columns(list(headers))
    code_col = columns.get("code")
    return columns, {r.cells.get(code_col, ""): r for r in rows} if code_col else {}


def _sheet_value(check: Any, ftype: str, row: Any, columns: dict[str, str]) -> tuple[float | None, str | None, str | None]:
    """(value, header, raw cell) from the SKU sheet row, by sheet column or by pattern over the whole row."""
    if check.pattern:
        m = re.search(check.pattern, " | ".join(row.cells.values()), re.IGNORECASE)
        if not m:
            return None, None, None
        num = float(m.group(1).replace(",", ""))
        return (num / 100 if ftype == "pct" else num), None, m.group(0)
    header = columns.get(check.target)
    raw = row.cells.get(header, "") if header else ""
    if check.target == "pack":
        pack = parse_pack(raw)
        for key in ("grams", "ml", "units"):
            if isinstance(pack.get(key), int | float):
                return float(pack[key]), header, raw  # type: ignore[arg-type]
        return None, header, raw
    return parse_price(raw), header, raw


def _finding(check: Any, doc: DocRead, f: FieldRead, status: str, *, other_label: str, other_value: str, other_source: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "id": f"{check.id}:{doc.file}:{f.sku_code or '-'}",
        "check": check.id,
        "label": check.label,
        "severity": check.severity,
        "status": status,
        "doc": doc.file,
        "doc_label": doc.entry.get("title") or doc.label,
        "page": f.page,
        "bbox": f.bbox,
        "field": f.name,
        "field_label": f.label,
        "sku_code": f.sku_code,
        "document_value": f.display(),
        "other_label": other_label,
        "other_value": other_value,
        "other_source": other_source,
        "claim_id": f.claim_id,
        "claim_status": f.status,
        "message": message,
    }


def cross_check(
    vendor_id: str, docs: list[DocRead], stage: str, copies: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Compare each verified reading with its counterpart. A reading whose two reads disagree is reported as unreliable
    instead of compared. Skips pairs where the counterpart or the reading is absent."""
    pol = policy.get().documents
    kinds = {k.kind: k for k in pol.kinds if k.stage == stage}
    application = load_application(vendor_id)
    app_docs = {d["type"]: d for d in application.get("documents", [])}
    columns, rows = _sheet_rows(vendor_id)
    out: list[dict[str, Any]] = []
    for check in pol.cross_checks:
        if check.kind not in kinds:
            continue
        for doc in (d for d in docs if d.kind == check.kind and d.legible and not d.error):
            for f in (x for x in doc.fields if x.name == check.field and x.trusted):
                if f.status in {"rejected", "conflict"}:
                    out.append(
                        _finding(check, doc, f, "unreliable", other_label="", other_value="", other_source={},
                                 message=f"{doc.entry.get('title') or doc.label}: {f.label} could not be read reliably ({f.reason}); not compared")
                    )
                    continue
                other = _counterpart(check, f, doc, app_docs, application, rows, columns, copies)
                if other is None:
                    continue
                label, shown, source, equal = other
                same = equal(f)
                word = {"application_document": "the application", "sku_sheet": "the SKU sheet", "listing_copy": "the listing copy"}[check.against]
                code = f" ({f.sku_code})" if f.sku_code else ""
                msg = (
                    f"{doc.entry.get('title') or doc.label}: {f.label} reads {f.display()}{code}; {word} says {shown}"
                    if not same
                    else f"{doc.entry.get('title') or doc.label}: {f.label} {f.display()}{code} matches {word}"
                )
                out.append(_finding(check, doc, f, "match" if same else "mismatch", other_label=label or word, other_value=shown, other_source=source, message=msg))
    return out


def _counterpart(check: Any, f: FieldRead, doc: DocRead, app_docs: dict[str, Any], application: dict[str, Any], rows: dict[str, Any], columns: dict[str, str], copies: dict[str, dict[str, Any]] | None):
    """(label, display, source, equal(field) -> bool) or None when there is nothing to compare with."""
    if check.against == "application_document":
        declares = doc.entry.get("declares")
        app_doc = app_docs.get(str(declares)) if declares else None
        if check.target == "company_name":
            theirs = application.get("company_name")
            if not theirs:
                return None
            a, b = docparse.norm_text(f.raw), docparse.norm_text(str(theirs))
            return "applicant", str(theirs), {"file": "application.json", "key": "company_name"}, lambda _f: bool(a) and (a in b or b in a)
        if app_doc is None:
            return None
        theirs = app_doc.get(check.target) or ""
        if not theirs:
            return None
        src = {"file": "application.json", "key": f"documents[{declares}].{check.target}"}
        if f.type == "date":
            d = docparse.parse_date(str(theirs))
            return "application", str(theirs), src, lambda _f: _f.parsed == d
        return "application", str(theirs), src, lambda _f: docparse.norm_text(_f.raw) == docparse.norm_text(str(theirs))
    if f.type == "text":
        return None
    sku = f.sku_code
    if check.against == "sku_sheet":
        row = rows.get(sku or "")
        if row is None:
            return None
        value, header, raw = _sheet_value(check, f.type, row, columns)
        if value is None:
            return None
        tol = _tolerance(check, f.type)
        parsed = f.parsed
        if not isinstance(parsed, int | float):
            return None
        src = {"file": "sku_sheet.csv", "row": row.row, "header": header, "raw": raw}
        return "SKU sheet", (raw if check.target == "pack" and raw else _fmt(f.type, value)), src, lambda _f: abs(float(_f.parsed) - value) <= tol  # type: ignore[arg-type]
    # listing_copy
    copy = (copies or {}).get(sku or "")
    if copy is None:
        return None
    text = " | ".join([copy.get("title", ""), *copy.get("bullets", []), copy.get("description", "")])
    m = re.search(check.pattern, text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    value = value / 100 if f.type == "pct" else value
    tol = _tolerance(check, f.type)
    return "listing copy", _fmt(f.type, value), {"file": "listing", "sku_code": sku, "raw": m.group(0)}, lambda _f: abs(float(_f.parsed) - value) <= tol  # type: ignore[arg-type]


# ---------- injection ----------


def _injection(docs: list[DocRead]) -> list[dict[str, Any]]:
    pattern = re.compile("|".join(policy.get().screening.injection_patterns), re.IGNORECASE)
    findings = []
    for d in docs:
        texts = [d.notes, *(f.raw for f in d.fields)]
        hits = [t for t in texts if t and pattern.search(t)]
        if hits:
            d.injection = hits
            findings.append(
                {
                    "id": f"injection:{d.file}", "check": "document_injection", "label": "Text addressed to an AI reviewer inside a document",
                    "severity": "high", "status": "injection", "doc": d.file, "doc_label": d.entry.get("title") or d.label, "page": 1,
                    "bbox": None, "field": None, "field_label": None, "sku_code": d.sku_code, "document_value": hits[0], "other_label": "",
                    "other_value": "", "other_source": {}, "claim_id": None, "claim_status": None,
                    "message": f"{d.entry.get('title') or d.label} contains text addressed to an AI reviewer, which was ignored: {hits[0][:120]}",
                }
            )
    return findings


# ---------- entry point ----------


async def run(
    ctx: RunContext,
    vendor_id: str,
    stage: str,
    *,
    sku_codes: set[str] | None = None,
    copies: dict[str, dict[str, Any]] | None = None,
) -> DocScan | None:
    """Read this vendor's documents of the given stage ("intake" or "catalog"). None when the playbook turns documents
    off or the vendor uploaded none. Never raises for a bad document: it is reported on the document."""
    pol = policy.get().documents
    if not pol.enabled:
        return None
    kinds = {k.kind: k for k in pol.kinds if k.stage == stage}
    entries = [
        e for e in load_doc_manifest(vendor_id)
        if e["kind"] in kinds and (not e.get("sku_code") or sku_codes is None or e["sku_code"] in sku_codes)
    ]
    if not entries:
        return None
    today = date.fromisoformat(ctx.today)
    ctx.emit(
        "tool_call", stage,
        {"tool": "read_documents", "args": {"vendor_id": vendor_id, "files": [e["file"] for e in entries]},
         "result_summary": f"{len(entries)} scanned document(s) to read with vision", "deterministic": True},
    )
    scan = DocScan(vendor_id, today)
    for entry in entries:
        cfg = kinds[entry["kind"]]
        doc = DocRead(entry={**entry, "vendor": vendor_id}, label=cfg.label)
        pages = [str(p) for p in entry.get("pages") or [entry["file"]]][: pol.max_pages]
        try:
            for n, page_file in enumerate(pages, 1):
                await _read_page(ctx, vendor_id, stage, doc, n, page_file, cfg, today)
        except CategoryOSError as exc:
            doc.error = f"{exc.code}: {exc.problem}"
            ctx.emit("degraded", stage, {"reason": f"{doc.file} could not be read ({exc.code}); its declared values are used instead"})
        scan.documents.append(doc)
    readable = [d for d in scan.documents if d.legible and not d.error]
    scan.claims = _verify(ctx, stage, vendor_id, readable, today)
    scan.findings = _injection(scan.documents) + cross_check(vendor_id, readable, stage, copies)
    ctx.emit(
        "tool_call", stage,
        {"tool": "cross_check_documents", "args": {"vendor_id": vendor_id, "checks": [c.id for c in pol.cross_checks if c.kind in kinds]},
         "result_summary": f"{len(scan.findings)} comparison(s), {len(scan.mismatches())} to follow up", "deterministic": True},
    )
    return scan
