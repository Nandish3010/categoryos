"""Fix proposals for the issues the detectors found.

Deterministic where the answer is in the data: the MRP and the pack from the latest price list, the category from the taxonomy
classifier, the licence from the licence file, the duplicate to retire from the name similarity, the protein from the pack
label. Otherwise model-written (muse-spark through the gateway): a rewritten title or bullets and text attributes, using only
facts from the row and the label. Every proposed value is a Claim; a fix is ``ready`` only when all of its claims verified.

A fix is {id, listing_id, kind, source, issue_ids, changes: [{field, label, before, after}], claim_ids, status, reason}. Fixes of
one listing build on each other (the copy fix sees the corrected pack), so applying them in order gives the final listing."""

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from app import llm, policy, selfcorrect
from app.agents.context import RunContext
from app.errors import CategoryOSError
from app.ops import figures as fg
from app.ops.catalog_qc import calc, prompts
from app.ops.catalog_qc.data import LICENCES, LIVE, PRICES, Listing, file_sha256
from app.ops.catalog_qc.detect import Ctx
from app.ops.catalog_qc.labels import LabelScan
from app.ops.catalog_qc.schemas import ListingRewrite, RewriteFinal
from app.parsing import PARSER_VERSION
from app.schemas import Claim, ClaimFix, Evidence, SourceRef
from app.verify import verify_all

STAGE = "ops"
COPY_ISSUES = ("title_too_long", "title_missing_attributes", "banned_claim", "high_returns_not_as_described")
ORDER = ("price", "pack", "category", "licence", "label", "duplicate", "images", "attributes", "copy")
FIELD_LABEL = {
    "title": "Title", "bullets": "Bullets", "description": "Description", "category": "Category", "subcategory": "Subcategory", "mrp": "MRP",
    "pack_size": "Pack size", "fssai_number": "FSSAI licence number", "status": "Listing status", "images": "Images",
}


@dataclass
class Fix:
    id: str
    listing_id: str
    vendor_id: str
    sku_code: str
    kind: str
    source: str  # deterministic | label | model
    title: str
    issue_ids: list[str]
    issue_types: list[str]
    changes: list[dict[str, Any]]
    claims: list[Claim] = field(default_factory=list)
    status: str = "ready"  # ready | blocked
    reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "listing_id": self.listing_id, "vendor_id": self.vendor_id, "sku_code": self.sku_code, "kind": self.kind,
            "source": self.source, "title": self.title, "issue_ids": self.issue_ids, "issue_types": self.issue_types, "changes": self.changes,
            "claim_ids": [c.id for c in self.claims], "status": self.status, "reason": self.reason, "notes": self.notes,
            "claims_verified": sum(c.status == "verified" for c in self.claims), "claims_total": len(self.claims),
        }


# ---------- helpers ----------


def _show(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(f"• {v}" for v in value)
    if isinstance(value, float) and value == int(value):
        return f"{value:g}"
    return "" if value is None else str(value)


def change(fld: str, before: Any, after: Any, label: str | None = None) -> dict[str, Any]:
    name = fld.split(".", 1)[1].replace("_", " ").capitalize() if fld.startswith("attributes.") else FIELD_LABEL.get(fld, fld)
    return {"field": fld, "label": label or name, "before": before, "after": after, "before_text": _show(before), "after_text": _show(after)}


def apply_changes(state: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """The listing after ``changes`` (a copy)."""
    out = copy.deepcopy(state)
    for c in changes:
        fld = c["field"]
        if fld.startswith("attributes."):
            out["attributes"][fld.split(".", 1)[1]] = c["after"]
        else:
            out[fld] = copy.deepcopy(c["after"])
    return out


def _claim(fix_id: str, name: str, *, text: str, value: float, metric: str, unit: str, x: Listing, file: str, key: str, column: str | None = None,
           raw: str | None = None, normalized: Any = None, row: int | None = None, header: str | None = None, origin: str = "engine") -> Claim:
    return Claim(
        id=f"{fix_id}:{name}", text=text, value=float(value), metric=metric, unit=unit, sku_key=x.sku_key,  # type: ignore[arg-type]
        source_ref=SourceRef(file=file, key=key, column=column),
        evidence=Evidence(row=row, header=header, raw_value=raw, normalized_value=normalized if normalized is not None else float(value),
                          parser_version=PARSER_VERSION, sha256=file_sha256(file)),
        origin=origin,  # type: ignore[arg-type]
    )


def _new(x: Listing, kind: str, source: str, title: str, issues: list[dict[str, Any]], changes: list[dict[str, Any]], claims: list[Claim]) -> Fix:
    return Fix(f"fix:{x.listing_id}:{kind}", x.listing_id, x.vendor_id, x.sku_code, kind, source, title, [i["id"] for i in issues],
               [i["type"] for i in issues], changes, claims)


def _rupees(v: float) -> str:
    return f"₹{v:,.0f}" if v == int(v) else f"₹{v:,.2f}"


# ---------- deterministic fixes ----------


def fix_price(ctx: Ctx, x: Listing, issue: dict[str, Any], scan: LabelScan) -> Fix | None:
    d = issue["detail"]
    if "price_list_mrp" in d:
        new = d["price_list_mrp"]
        claim = _claim(f"fix:{x.listing_id}:price", "mrp", text=f"{x.sku_code} MRP is {_rupees(new)} on the latest price list (effective {d['effective_date']})", value=new,
                       metric="qc_mrp", unit="inr", x=x, file=PRICES, key=x.sku_key, column="mrp", row=d["price_list_row"], header="mrp")
        claims = [claim]
    elif d.get("label_claim_id") and (lab := scan.claim(d["label_claim_id"])) is not None:
        new, claims = d["label_mrp"], [lab]
    else:
        return None
    note = f" The pack label prints {_rupees(d['label_mrp'])} too." if d.get("label_mrp") == new and "price_list_mrp" in d else ""
    fx = _new(x, "price", "deterministic", f"Set MRP to {_rupees(new)}", [issue], [change("mrp", x.mrp, new)], claims)
    if note:
        fx.notes.append(note.strip())
    return fx


def _replace_ci(text: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), new, text, flags=re.IGNORECASE)


def fix_pack(ctx: Ctx, x: Listing, issue: dict[str, Any], rewriting: bool) -> Fix | None:
    d = issue["detail"]
    new = d["price_list_pack"]
    amount = calc.pack_amount(new)
    changes = [change("pack_size", x.pack_size, new)]
    key = calc.pack_key(new)
    if key and amount is not None:
        before = x.attributes.get(key)
        stale = [k for k in x.attributes if k.startswith("pack_") and k != key]
        if before is not None or not stale:
            changes.append(change(f"attributes.{key}", before, int(amount) if amount == int(amount) else amount))
    if not rewriting and x.pack_size.lower() in x.title.lower():
        changes.append(change("title", x.title, _replace_ci(x.title, x.pack_size, new)))
    claims = []
    if amount is not None:
        claims.append(_claim(f"fix:{x.listing_id}:pack", "qty", text=f"{x.sku_code} pack is {amount:g} on the latest price list ({new})", value=amount, metric="qc_pack_qty", unit="qty",
                             x=x, file=PRICES, key=x.sku_key, column="pack_size", row=d["price_list_row"], header="pack_size"))
    fx = _new(x, "pack", "deterministic", f"Set pack size to {new}", [issue], changes, claims)
    if amount is None:
        fx.status, fx.reason = "blocked", f"The price list pack {new!r} is not a measurable quantity, so it cannot be verified; set it by hand"
    if d.get("label_net_quantity"):
        fx.notes.append(f"The pack label prints {d['label_net_quantity']}.")
    return fx


def fix_category(ctx: Ctx, x: Listing, issue: dict[str, Any]) -> Fix:
    cat, sub = issue["detail"]["classified"]
    changes = [change("category", x.category, cat)] if cat != x.category else []
    if sub != x.subcategory:
        changes.append(change("subcategory", x.subcategory, sub))
    claim = _claim(f"fix:{x.listing_id}:category", "agrees", text=f"The taxonomy classifies {x.listing_id} as {cat} / {sub}", value=1.0, metric="qc_category_agrees", unit="ratio",
                   x=x, file=LIVE, key=x.listing_id, column="category", raw=f"{cat}|{sub}", normalized=f"{cat}|{sub}")
    return _new(x, "category", "deterministic", f"Move to {cat} / {sub}", [issue], changes, [claim])


def fix_licence(ctx: Ctx, x: Listing, issue: dict[str, Any]) -> Fix:
    d = issue["detail"]
    fid = f"fix:{x.listing_id}:licence"
    if d["replacement"]:
        days = (ctx.data.licence(d["replacement"]).valid_until - ctx.as_of).days  # type: ignore[union-attr]
        claim = _claim(fid, "days_left", text=f"Licence {d['replacement']} is valid for {days} more days", value=days, metric="qc_licence_days_left", unit="units",
                       x=x, file=LICENCES, key=d["replacement"], column="valid_until")
        return _new(x, "licence", "deterministic", f"Use the renewed licence {d['replacement']}", [issue], [change("fssai_number", x.fssai_number, d["replacement"])], [claim])
    claim = _claim(fid, "days_left", text=f"Licence {d['number']} ran out {-d['days_left']} days ago", value=d["days_left"], metric="qc_licence_days_left", unit="units",
                   x=x, file=LICENCES, key=d["number"], column="valid_until")
    return _new(x, "licence", "deterministic", "Put the listing on hold until a valid licence is on file", [issue], [change("status", x.status, "on_hold")], [claim])


def fix_duplicate(ctx: Ctx, x: Listing, issue: dict[str, Any]) -> Fix:
    d = issue["detail"]
    claim = _claim(f"fix:{x.listing_id}:duplicate", "similarity", text=f"{x.listing_id} and {d['duplicate_of']} overlap {d['similarity']:.2f}", value=d["similarity"],
                   metric="qc_dup_similarity", unit="ratio", x=x, file=LIVE, key=f"{x.listing_id}|{d['duplicate_of']}", column="title")
    return _new(x, "duplicate", "deterministic", f"Retire this listing and keep {d['duplicate_of']}", [issue], [change("status", x.status, "retired")], [claim])


def fix_images(ctx: Ctx, x: Listing, issues: list[dict[str, Any]], brand: str) -> Fix:
    px = ctx.qc.images.min_resolution_px
    low = any(i["type"] == "low_res_image" for i in issues)
    ask = f"Ask {brand} for images of at least {px} px on the short side" if low else f"Ask {brand} for product images (at least {px} px)"
    claim = _claim(f"fix:{x.listing_id}:images", "min_px", text=f"The playbook minimum image size is {px} px", value=px, metric="qc_image_min_px", unit="units",
                   x=x, file=LIVE, key=x.listing_id, column="image_width")
    fx = _new(x, "images", "deterministic", ask, issues, [change("images", x.snapshot()["images"], f"Requested from {brand}: {px} px or more")], [claim])
    fx.notes.append("A person cannot fix this from the sheet: approving files a request to the vendor (simulated).")
    return fx


def fix_label(ctx: Ctx, x: Listing, issues: list[dict[str, Any]], scan: LabelScan) -> Fix | None:
    changes, claims, used = [], [], []
    bullets, desc = list(x.bullets), x.description
    for issue in issues:
        d = issue["detail"]
        lab = scan.claim(d["claim_id"]) if d.get("claim_id") else None
        if d["field"] != "protein_pct" or lab is None:
            continue
        old = re.search(r"(\d+(?:\.\d+)?)\s*%", str(x.attributes.get("protein", "")))
        new = f"{float(lab.value) * 100:g}%"
        changes.append(change("attributes.protein", x.attributes.get("protein"), new))
        if old:
            pat = re.compile(rf"\b{re.escape(old.group(1))}\s*%")
            bullets = [pat.sub(new, b) for b in bullets]
            desc = pat.sub(new, desc)
        claims.append(lab)
        used.append(issue)
    if not used:
        return None
    if bullets != list(x.bullets):
        changes.append(change("bullets", list(x.bullets), bullets))
    if desc != x.description:
        changes.append(change("description", x.description, desc))
    return _new(x, "label", "label", "Match the protein to the pack label (" + ", ".join(c["after"] for c in changes if c["field"] == "attributes.protein") + ")", used, changes, claims)


def fix_pack_attribute(ctx: Ctx, x: Listing, issue: dict[str, Any]) -> Fix | None:
    """A missing pack_* attribute, filled from the latest price list."""
    price = ctx.data.latest_price(x.sku_code, ctx.as_of)
    key = calc.pack_key(price.pack_size) if price else None
    amount = calc.pack_amount(price.pack_size) if price else None
    missing = [m for m in issue["detail"]["missing"] if m == "pack" or m.startswith("pack_")]
    if price is None or key is None or amount is None or not missing:
        return None
    claim = _claim(f"fix:{x.listing_id}:attributes", "pack", text=f"{x.sku_code} pack is {amount:g} on the latest price list", value=amount, metric="qc_pack_qty", unit="qty",
                   x=x, file=PRICES, key=x.sku_key, column="pack_size", row=price.row, header="pack_size")
    return _new(x, "attributes", "deterministic", "Fill the pack attribute from the price list", [issue], [change(f"attributes.{key}", None, int(amount) if amount == int(amount) else amount)], [claim])


# ---------- model-written fixes ----------


def _text_of(title: str, bullets: list[str], description: str) -> str:
    return " | ".join([title, *bullets, description])


def _label_numbers(scan: LabelScan, listing_id: str) -> str:
    nums: set[str] = set()
    for r in scan.findings.get(listing_id, []):
        if r["status"] != "unreliable":
            nums.update(calc.numbers_in(str(r["label_value"])))
    return ",".join(sorted(nums))


def request_for(ctx: Ctx, x: Listing, issues: list[dict[str, Any]], state: dict[str, Any], scan: LabelScan, missing_text_attrs: list[str]) -> dict[str, Any]:
    return {
        "listing_id": x.listing_id,
        "brand": ctx.brand(x.vendor_id),
        "problems": [{"type": i["type"], "what": i["message"]} for i in issues],
        "missing_attributes": missing_text_attrs,
        "listing": {k: state[k] for k in ("title", "bullets", "description", "category", "pack_size", "mrp")} | {"attributes": state["attributes"]},
        "label": [{"field": r["field_label"], "reads": r["label_value"]} for r in scan.findings.get(x.listing_id, []) if r["status"] != "unreliable"],
    }


def copy_fix(ctx: Ctx, x: Listing, issues: list[dict[str, Any]], state: dict[str, Any], item: ListingRewrite, scan: LabelScan) -> Fix | None:
    title = " ".join(item.title.split()) if item.title else state["title"]
    bullets = [b.strip() for b in item.bullets if b.strip()] if item.bullets else list(state["bullets"])
    desc = item.description.strip() if item.description else state["description"]
    changes = []
    if title != state["title"]:
        changes.append(change("title", state["title"], title))
    if bullets != list(state["bullets"]):
        changes.append(change("bullets", list(state["bullets"]), bullets))
    if desc != state["description"]:
        changes.append(change("description", state["description"], desc))
    if not changes:
        return None
    fid = f"fix:{x.listing_id}:copy"
    text = _text_of(title, bullets, desc)
    key = x.listing_id
    claims: list[Claim] = []
    if title != state["title"]:
        claims.append(_claim(fid, "title_chars", text=f"The proposed title is {len(title)} characters", value=len(title), metric="qc_title_chars", unit="units", x=x, file=LIVE, key=key,
                             column="title", raw=title))
        claims.append(_claim(fid, "title_required", text="The proposed title has the brand and pack the playbook requires", value=0, metric="qc_title_required_missing", unit="units", x=x,
                             file=LIVE, key=key, column="title", raw=title))
    claims.append(_claim(fid, "banned", text="The proposed text uses no claim the playbook bans", value=0, metric="qc_banned_claims", unit="units", x=x, file=LIVE, key=key, column="title", raw=text))
    claims.append(_claim(fid, "numbers", text="Every number in the proposed text is in the row, the price list or the label", value=0, metric="qc_unsupported_numbers", unit="units", x=x, file=LIVE,
                         key=key, column="title", raw=text, normalized=_label_numbers(scan, x.listing_id)))
    price = ctx.data.latest_price(x.sku_code, ctx.as_of)
    for n, f in enumerate(item.facts):
        if price is None:
            break
        if f.metric == "pack_qty":
            claims.append(_claim(fid, f"fact{n}", text=f"The rewrite states a pack of {f.value:g} ({f.quote})", value=f.value, metric="qc_stated_pack_qty", unit="qty", x=x, file=PRICES, key=x.sku_key,
                                 column="pack_size", raw=f.quote, row=price.row, header="pack_size", origin="model_extraction"))
        else:
            claims.append(_claim(fid, f"fact{n}", text=f"The rewrite states an MRP of {f.value:g} ({f.quote})", value=f.value, metric="qc_stated_mrp", unit="inr", x=x, file=PRICES, key=x.sku_key,
                                 column="mrp", raw=f.quote, row=price.row, header="mrp", origin="model_extraction"))
    what = " and ".join(c["label"].lower() for c in changes if c["field"] in ("title", "bullets", "description"))
    fx = _new(x, "copy", "model", f"Rewrite the {what}", issues, changes, claims)
    if item.note:
        fx.notes.append(item.note)
    return fx


def attribute_fix(ctx: Ctx, x: Listing, issue: dict[str, Any], item: ListingRewrite, missing: list[str]) -> Fix | None:
    fid = f"fix:{x.listing_id}:attributes"
    changes, claims = [], []
    for a in item.attributes:
        if a.name not in missing or not a.value.strip() or not a.quote.strip():
            continue
        changes.append(change(f"attributes.{a.name}", None, a.value.strip()))
        claims.append(_claim(fid, a.name, text=f"{a.name.replace('_', ' ')} is '{a.value.strip()}' (quoted: \"{a.quote.strip()}\")", value=1.0, metric="qc_attr_quote", unit="ratio", x=x, file=LIVE,
                             key=x.listing_id, column=a.name, raw=a.quote.strip(), normalized=a.value.strip(), origin="model_extraction"))
    if not changes:
        return None
    fx = _new(x, "attributes", "model", "Fill missing attributes: " + ", ".join(c["label"].lower() for c in changes), [issue], changes, claims)
    return fx


async def model_fixes(
    ctx: Ctx, run: RunContext, listings: list[tuple[Listing, list[dict[str, Any]], dict[str, Any], list[str]]], scan: LabelScan
) -> tuple[RewriteFinal | None, list[dict[str, Any]], str, str | None]:
    """One gateway call for every listing that needs written text. Returns (parsed, messages, raw content, degraded reason)."""
    requests = [request_for(ctx, x, issues, state, scan, attrs) for x, issues, state, attrs in listings]
    msgs = prompts.messages(ctx.as_of.isoformat(), requests)
    try:
        res = await llm.call(STAGE, msgs, task="catalog_qc_rewrite", schema=RewriteFinal, max_tokens=6000)
    except CategoryOSError as exc:
        return None, msgs, "", f"model-written fixes unavailable ({exc.code}); only the deterministic fixes are proposed"
    fg.emit_model_call(run, "catalog_qc_rewrite", res)
    assert isinstance(res.parsed, RewriteFinal)
    return res.parsed, msgs, res.content, None


async def verify_fixes(run: RunContext, fixes: list[Fix], msgs: list[dict[str, Any]], previous: str, inject: bool = False) -> list[Claim]:
    """Verify every claim of every fix; model-stated numbers the verifier rejects get the self-correction loop. Sets each fix's
    claims back (verified, or with their attempts) and its status."""
    flat = [c for f in fixes for c in f.claims]
    if inject:  # test hook: make one deterministic value wrong so the verifier has to catch it
        for i, c in enumerate(flat):
            if c.metric in ("qc_mrp", "qc_pack_qty"):
                flat[i] = c.model_copy(update={"value": c.value + 111.0, "origin": "injected_test"})
                break
    checked = verify_all(flat).claims
    if previous:
        checked = await selfcorrect.self_correct(
            run, STAGE, checked, task="catalog_qc_rewrite", messages=msgs, previous=previous,
            rebuild=lambda claim, fix: _rebuild(claim, fix), check=lambda batch: verify_all(batch).claims,
        )
    by_id = {c.id: c for c in checked}
    for f in fixes:
        f.claims = [by_id[c.id] for c in f.claims]
        bad = [c for c in f.claims if c.status != "verified"]
        if f.status != "blocked" and bad:
            f.status = "blocked"
            f.reason = bad[0].reason or f"A claim could not be verified: {bad[0].text}"
        elif f.status == "ready":
            f.reason = None
    for c in checked:
        run.emit("claim_checked", STAGE, {"claim": c.model_dump(mode="json")})
    return checked


def _rebuild(claim: Claim, fix: ClaimFix) -> Claim | None:
    return selfcorrect.revalue(claim, fix.value)
