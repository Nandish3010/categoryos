"""Catalog agent (stage "catalog"): per shortlisted SKU a launch-ready listing.

(a) classification: Python rules (taxonomy) are the truth; Muse Spark Open on Baseten classifies independently and is
    validated against the taxonomy. Disagreement keeps the rules' label; an unusable reply means "Classified by rules".
(b) normalisation: deterministic parsing of price, pack and units.
(c) copy: model task catalog_copy, then a deterministic compliance linter on top of the model's own flags.
(d) images: packshot (muse-image) -> cutout (SAM 3.1) and, for the hero SKUs, a lifestyle image. Mock and replay use
    labelled Pillow placeholders. A failed or unusable cutout is "unavailable" and the packshot is shown instead."""

import asyncio
import re
from typing import Any

from app import llm, media, policy, prompts_exec, selfcorrect
from app.agents import shortlist as sl
from app.agents.context import RunContext
from app.config import settings
from app.data_loader import load_application
from app.errors import CategoryOSError, LlmBadOutput, LlmUnavailable
from app.metrics import build_base
from app.parsing import PARSER_VERSION, parse_pack
from app.schemas import (
    CatalogCopy,
    CatalogCopyFinal,
    Claim,
    ClassifyFinal,
    Evidence,
    SkuMetrics,
    SourceRef,
    StageResult,
)
from app.taxonomy import catalog_subcategories, categories, segments_for
from app.verify import VerifySummary, file_sha256, verify_all

STAGE = "catalog"


# ---------- (a) classification ----------


def _valid_label(category: str, sub: str) -> bool:
    return category in categories() and sub in catalog_subcategories().get(category, frozenset())


async def classify(ctx: RunContext, vendor_id: str, skus: list[SkuMetrics]) -> dict[str, dict[str, Any]]:
    """code -> classification record. Never raises for a bad model reply."""
    rules = {s.code: {"category": s.category, "subcategory": s.subcategory} for s in skus}
    out: dict[str, dict[str, Any]] = {
        c: {"rules": r, "model": None, "agreement": None, "final": r, "note": "Classified by rules"} for c, r in rules.items()
    }
    labels = {c: sorted(catalog_subcategories().get(c, frozenset())) for c in categories()}
    rows = [(s.code, s.name, s.raw.get(s.columns.get("description", ""), "")) for s in skus]
    try:
        res = await llm.call(
            STAGE,
            prompts_exec.classify_messages(labels, rows),
            task=f"classify_{vendor_id}",
            schema=ClassifyFinal,
            provider="baseten",
            max_tokens=1500,
        )
    except (LlmBadOutput, LlmUnavailable) as exc:
        ctx.emit("degraded", STAGE, {"reason": f"Baseten classification unusable ({exc.code}); classified by rules"})
        return out
    ctx.emit(
        "model_call",
        STAGE,
        {"task": "classify", "mode": res.mode, "provider": "baseten", "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    assert isinstance(res.parsed, ClassifyFinal)
    by_code = {i.code: i for i in res.parsed.classifications}
    for code, rec in out.items():
        item = by_code.get(code)
        if item is None:
            continue
        valid = _valid_label(item.category, item.subcategory)
        model = {"category": item.category, "subcategory": item.subcategory, "valid": valid}
        agree = valid and (item.category, item.subcategory) == (rec["rules"]["category"], rec["rules"]["subcategory"])
        rec.update(model=model, agreement=agree, note=None if agree else "Model label differs; kept the rules' classification")
    return out


# ---------- (c) copy and compliance ----------


def _fallback_copy(sku: SkuMetrics, brand: str) -> CatalogCopy:
    details = sku.raw.get(sku.columns.get("description", ""), "")
    bullets = [p.strip(" .") for p in re.split(r"[.;]\s+|,\s+(?=[A-Za-z])", details) if len(p.strip()) > 3][: policy.get().catalog.bullets.max]
    return CatalogCopy(
        sku_code=sku.code,
        title=f"{brand} {sku.name}",
        bullets=bullets,
        description=details,
        attributes={},
    )


def _normalise_copy(copy: CatalogCopy, sku: SkuMetrics, brand: str) -> dict[str, Any]:
    title = " ".join(copy.title.split())
    cat = policy.get().catalog
    if len(title) > cat.title_max_chars:
        title = title[: cat.title_max_chars - 1].rstrip() + "…"
    bullets = [b.strip() for b in copy.bullets if b.strip()][: cat.bullets.max]
    for filler in (f"Pack size: {sku.pack}" if sku.pack else "", f"Brand: {brand}", f"Category: {sku.category}"):
        if len(bullets) >= cat.bullets.min:
            break
        if filler:
            bullets.append(filler)
    return {**copy.model_dump(), "title": title, "bullets": bullets}


def _shelf_life(sku: SkuMetrics) -> str:
    for header, value in sku.raw.items():
        if "shelf" in header.lower():
            return value.strip()
    return ""


def _has_attribute(attr: str, sku: SkuMetrics, attributes: dict[str, Any]) -> bool:
    if attr == "pack":
        return any(k.startswith("pack") and attributes.get(k) not in (None, "") for k in attributes) or bool(sku.pack_normalized)
    if attr == "mrp":
        return attributes.get("mrp") not in (None, "") or sku.mrp is not None
    return attributes.get(attr) not in (None, "")


def compliance_flags(sku: SkuMetrics, copy: dict[str, Any], licences: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Playbook-driven compliance: claim rules, label checks, licences and required attributes, on top of the model's flags."""
    pol = policy.get()
    licences = licences or {}
    flags: list[dict[str, Any]] = [{**f, "source": "model"} for f in copy.get("compliance_flags", [])]
    text = " | ".join([copy["title"], *copy["bullets"], copy["description"]])
    vendor_text = sku.raw.get(sku.columns.get("description", ""), "")
    for rule in pol.screening.claim_rules:
        if not policy.in_scope(rule.categories, sku.category):
            continue
        pattern = policy.claim_regex(rule)
        for where, haystack in (("listing", text), ("vendor sheet", vendor_text)):
            for m in pattern.finditer(haystack):
                flags.append({"rule": rule.type, "text": f"{m.group(0)} ({where})", "severity": rule.severity, "source": "rules"})

    def label(text_: str, severity: str = "medium") -> None:
        flags.append({"rule": "missing_label_info", "text": text_, "severity": severity, "source": "rules"})

    for check in pol.catalog.label_checks:
        if not policy.in_scope(check.categories, sku.category):
            continue
        if "shelf_life" in check.require and not _shelf_life(sku):
            label("best-before / shelf life is not in the vendor sheet")
        if "net_quantity" in check.require and not sku.pack_normalized:
            label("net quantity (pack size) is missing")
        if "ingredients" in check.require and not vendor_text.strip():
            label("ingredients / composition not provided")
    for lic in pol.catalog.label_licences:
        if policy.in_scope(lic.categories, sku.category) and lic.document not in licences:
            label(f"no valid {lic.document} licence number on file for this vendor", "high")
    attributes = copy.get("attributes", {})
    for attr in policy.required_attributes(sku.category):
        if not _has_attribute(attr, sku, attributes):
            label(f"required listing attribute '{attr}' is missing")
    seen: set[tuple[str, str]] = set()
    unique = []
    for f in flags:
        key = (f["rule"], re.sub(r"\s*\((?:listing|vendor sheet)\)$", "", f["text"].lower()))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _licences(vendor_id: str) -> dict[str, dict[str, Any]]:
    """Valid, numbered documents of the vendor that a label licence rule may refer to, by document type."""
    wanted = {lic.document for lic in policy.get().catalog.label_licences}
    return {
        d["type"]: d
        for d in load_application(vendor_id).get("documents", [])
        if d["type"] in wanted and d.get("status") == "valid" and d.get("number")
    }


def attribute_claims(vendor_id: str, sku: SkuMetrics, attributes: dict[str, Any]) -> list[Claim]:
    rel = f"vendors/{vendor_id}/sku_sheet.csv"
    sha = file_sha256(rel)
    claims: list[Claim] = []
    pack_value = next((attributes[k] for k in ("pack_g", "pack_ml", "pack_pc") if isinstance(attributes.get(k), int | float)), None)
    specs = [
        ("mrp", "mrp", "inr", attributes.get("mrp"), sku.columns.get("mrp")),
        ("pack_qty", "pack_qty", "qty", pack_value, sku.columns.get("pack")),
    ]
    for field, metric, unit, value, header in specs:
        if not isinstance(value, int | float) or header is None:
            continue
        claims.append(
            Claim(
                id=f"{sku.sku_key}:{field}:catalog",
                text=f"{sku.code} listing {field} is {value:g} (sheet row {sku.sheet_row}, {header})",
                value=float(value),
                metric=metric,
                unit=unit,  # type: ignore[arg-type]
                sku_key=sku.sku_key,
                source_ref=SourceRef(file=rel, key=sku.sku_key, column=header),
                evidence=Evidence(row=sku.sheet_row, header=header, raw_value=sku.raw.get(header), normalized_value=float(value), parser_version=PARSER_VERSION, sha256=sha),
                origin="model_extraction",
            )
        )
    return claims


def _attribute_key(metric: str, attributes: dict[str, Any]) -> str:
    return "mrp" if metric == "mrp" else next(k for k in ("pack_g", "pack_ml", "pack_pc") if k in attributes)


async def _verify_attributes(ctx: RunContext, vendor_id: str, claims: list[Claim], messages: list[dict[str, Any]], previous: str) -> VerifySummary:
    """Verify the listing attributes; a rejected one goes back to the copywriter with the sheet value (self-correction).
    Whatever stays rejected is replaced by the sheet value further down, as before."""
    checked = verify_all(claims).claims
    if previous:
        checked = await selfcorrect.self_correct(
            ctx, STAGE, checked, task=f"catalog_copy_{vendor_id}", messages=messages, previous=previous,
            rebuild=lambda claim, fix: selfcorrect.revalue(claim, fix.value), check=lambda batch: verify_all(batch).claims,
        )
    return selfcorrect.summarize(checked)


# ---------- (d) images ----------


def _prompt_vars(sku: SkuMetrics, brand: str, **extra: str) -> dict[str, str]:
    return {**segments_for(f"{sku.category} {sku.subcategory}"), "brand": brand, "name": sku.name, "pack": sku.pack or "retail pack", "category": sku.category, "subcategory": sku.subcategory, **extra}


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _prompt(template: str, values: dict[str, str]) -> str:
    return template.format_map(_Blank(values))


def _packshot_prompt(sku: SkuMetrics, brand: str) -> str:
    return _prompt(policy.get().catalog.image_prompts.packshot, _prompt_vars(sku, brand))


def _lifestyle_prompt(sku: SkuMetrics, brand: str) -> str:
    return _prompt(policy.get().catalog.image_prompts.lifestyle, _prompt_vars(sku, brand))


def _segmentation_phrase(category: str) -> str:
    seg = policy.get().catalog.image_prompts.segmentation
    return seg.get(category, seg["default"])


async def _image(ctx: RunContext, vendor_id: str, name: str, kind: str, title: str, subtitle: str, prompt: str, size: str, live: bool, errors: list[str]) -> str:
    """Make one image; returns 'live' (fresh or cached) or 'placeholder'."""
    cached = media.cached_source(vendor_id, name)
    if not live:
        media.ensure_placeholder(vendor_id, name, kind, title, subtitle)
        return media.cached_source(vendor_id, name) or "placeholder"
    if cached == "live":
        return "live"
    try:
        data, spend = await media.generate_image(prompt, size=size)
    except CategoryOSError as exc:
        errors.append(f"{name}: {exc.code}")
        media.ensure_placeholder(vendor_id, name, kind, title, subtitle)
        return "placeholder"
    media.write_asset(vendor_id, name, data, "live")
    ctx.emit("model_call", STAGE, {"task": f"image_{kind}", "mode": "live", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "asset": name}, model=spend.model, cost_usd=spend.cost_usd)
    return "live"


async def _images(ctx: RunContext, vendor_id: str, sku: SkuMetrics, brand: str, title: str, hero: bool, live: bool) -> dict[str, Any]:
    errors: list[str] = []
    code = sku.code
    pack_name = media.asset_name(code, "packshot")
    sources = {"packshot": await _image(ctx, vendor_id, pack_name, "packshot", title, sku.pack or "", _packshot_prompt(sku, brand), policy.get().catalog.image_sizes.packshot, live, errors)}
    cut_name = media.asset_name(code, "cutout")
    cutout: str
    if not settings.sam_enabled:
        cutout, sources["cutout"] = "unavailable", "unavailable"
        errors.append(f"{cut_name}: SAM disabled (go/no-go fallback)")
    elif not live:
        media.ensure_placeholder(vendor_id, cut_name, "cutout", title, sku.pack or "")
        cutout, sources["cutout"] = media.asset_url(vendor_id, cut_name), media.cached_source(vendor_id, cut_name) or "placeholder"
    elif media.cached_source(vendor_id, cut_name) == "live":
        cutout, sources["cutout"] = media.asset_url(vendor_id, cut_name), "live"
    elif sources["packshot"] != "live":
        cutout, sources["cutout"] = "unavailable", "unavailable"
        errors.append(f"{cut_name}: no live packshot to segment")
    else:
        try:
            png, spend = await media.segment((media.asset_dir(vendor_id) / pack_name).read_bytes(), _segmentation_phrase(sku.category))
            media.write_asset(vendor_id, cut_name, png, "live")
            ctx.emit("model_call", STAGE, {"task": "segment", "mode": "live", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "asset": cut_name}, model=spend.model, cost_usd=spend.cost_usd)
            cutout, sources["cutout"] = media.asset_url(vendor_id, cut_name), "live"
        except CategoryOSError as exc:
            cutout, sources["cutout"] = "unavailable", "unavailable"
            errors.append(f"{cut_name}: {exc.code}")
    lifestyle = None
    if hero:
        life_name = media.asset_name(code, "lifestyle")
        sources["lifestyle"] = await _image(ctx, vendor_id, life_name, "lifestyle", title, "hero lifestyle", _lifestyle_prompt(sku, brand), policy.get().catalog.image_sizes.lifestyle, live, errors)
        lifestyle = media.asset_url(vendor_id, life_name)
    real = [v for v in sources.values() if v != "unavailable"]
    image_source = "live" if real and all(v == "live" for v in real) else ("placeholder" if "live" not in real else "mixed")
    out: dict[str, Any] = {
        "packshot": media.asset_url(vendor_id, pack_name),
        "cutout": cutout,
        "lifestyle": lifestyle,
        "image_source": image_source,
        "sources": sources,
    }
    if cutout == "unavailable":
        out["cutout_note"] = "cutout unavailable"
    if errors:
        out["errors"] = errors
    return out


# ---------- run ----------


async def run(ctx: RunContext, research: StageResult) -> StageResult:
    vendor_id = ctx.vendor_id
    lever = sl.research_lever(vendor_id, research)
    verdicts = sl.effective_verdicts(research, lever)
    skus = sl.shortlisted(lever, verdicts)
    base = build_base(vendor_id)
    if not skus:
        return StageResult(
            stage=STAGE, status="done", summary="No shortlisted SKUs to catalog",
            data={"skus": [], "classifier_agreement_pct": None, "hero_skus": []}, metrics_hash=lever.metrics_hash,
        )
    brand = base.brand
    live = llm.resolve_mode(STAGE) == "live"
    ctx.emit(
        "tool_call",
        STAGE,
        {"tool": "normalise_rows", "args": {"vendor_id": vendor_id, "skus": [s.code for s in skus]}, "result_summary": f"{len(skus)} sheet rows parsed (price, pack, units)", "deterministic": True},
    )
    classes = await classify(ctx, vendor_id, skus)

    rows = [{"sku_code": s.code, "row": s.raw} for s in skus]
    copies: dict[str, CatalogCopy] = {}
    copy_msgs = prompts_exec.copy_messages(vendor_id, brand, rows, [s.category for s in skus])
    copy_content = ""
    try:
        res = await llm.call(
            STAGE,
            copy_msgs,
            task=f"catalog_copy_{vendor_id}",
            schema=CatalogCopyFinal,
            max_tokens=4000,
        )
        ctx.emit(
            "model_call",
            STAGE,
            {"task": "catalog_copy", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
            model=res.model,
            latency_ms=res.latency_ms,
            cost_usd=res.cost_usd,
        )
        if res.degraded:
            ctx.emit("degraded", STAGE, {"reason": "no recorded run for this vendor; served the mock fixture"})
        assert isinstance(res.parsed, CatalogCopyFinal)
        copy_content = res.content
        copies = {i.sku_code: i for i in res.parsed.items}
    except (LlmBadOutput, LlmUnavailable) as exc:
        ctx.emit("degraded", STAGE, {"reason": f"catalog copy unusable ({exc.code}); wrote rule-based copy"})

    licences = _licences(vendor_id)
    heroes = [s.code for s in sorted(skus, key=lambda s: (-s.est_gmv, s.code))[: policy.get().catalog.hero_sku_count]]
    prepared = []
    all_claims: list[Claim] = []
    for s in skus:
        copy = _normalise_copy(copies.get(s.code) or _fallback_copy(s, brand), s, brand)
        copy["generated_by"] = "model" if s.code in copies else "rules"
        copy["compliance_flags"] = compliance_flags(s, copy, licences)
        for lic in policy.get().catalog.label_licences:
            if lic.document in licences and policy.in_scope(lic.categories, s.category):
                copy["attributes"] = {**copy["attributes"], lic.attribute: licences[lic.document]["number"]}
        claims = attribute_claims(vendor_id, s, copy["attributes"])
        all_claims += claims
        prepared.append((s, copy, claims))

    sem = asyncio.Semaphore(4)

    async def make_images(s: SkuMetrics, title: str) -> dict[str, Any]:
        async with sem:
            return await _images(ctx, vendor_id, s, brand, title, s.code in heroes, live)

    images = await asyncio.gather(*(make_images(s, copy["title"]) for s, copy, _ in prepared))
    summary = await _verify_attributes(ctx, vendor_id, all_claims, copy_msgs, copy_content)
    by_id = {c.id: c for c in summary.claims}
    for claim in summary.claims:
        ctx.emit("claim_checked", STAGE, {"claim": claim.model_dump(mode="json")})

    sku_out = []
    agree = [c["agreement"] for c in classes.values() if c["agreement"] is not None]
    for (s, copy, claims), imgs in zip(prepared, images):
        corrections = []
        for claim in claims:
            checked = by_id[claim.id]
            if checked.status == "verified" and len(checked.attempts) > 1:  # rejected, then corrected by the agent
                copy["attributes"][_attribute_key(checked.metric, copy["attributes"])] = checked.value
            if checked.status == "rejected" and checked.recomputed is not None:
                key = _attribute_key(checked.metric, copy["attributes"])
                corrections.append({"attribute": key, "claimed": claim.value, "sheet": checked.recomputed, "claim_id": claim.id})
                copy["attributes"][key] = checked.recomputed
        cls = classes[s.code]
        sku_out.append(
            {
                "code": s.code,
                "name": s.name,
                "verdict": verdicts[s.code],
                "raw_row": s.raw,
                "normalized": {
                    "mrp": s.mrp,
                    "cost": s.cost,
                    "cost_source": s.cost_source,
                    "selling_price": s.selling_price,
                    "pack": s.pack,
                    "pack_normalized": s.pack_normalized,
                    "pack_detail": parse_pack(s.pack),
                    "category": cls["final"]["category"],
                    "subcategory": cls["final"]["subcategory"],
                    "flags": s.flags,
                },
                "classification": {"rules": cls["rules"], "model": cls["model"], "agreement": cls["agreement"], "note": cls["note"]},
                "copy": copy,
                "attribute_checks": [{"claim_id": c.id, "status": by_id[c.id].status, "reason": by_id[c.id].reason} for c in claims],
                "corrections": corrections,
                "images": imgs,
                "hero": s.code in heroes,
            }
        )
    flag_count = sum(len(i["copy"]["compliance_flags"]) for i in sku_out)
    pct = round(100 * sum(1 for a in agree if a) / len(agree), 1) if agree else None
    text = f"{len(sku_out)} listings drafted, {flag_count} compliance flag(s)"
    text += f", classifier agreement {pct:g}%" if pct is not None else ", classified by rules"
    data = {
        "skus": sku_out,
        "classifier_agreement_pct": pct,
        "hero_skus": heroes,
        "image_mode": "live" if live else "placeholder",
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
    }
    return StageResult(
        stage=STAGE,
        status="review",
        summary=text,
        data=data,
        needs_approval=True,
        claims=summary.claims,
        metrics_hash=lever.metrics_hash,
        narrative_hash=lever.metrics_hash,
    )
