"""Deterministic calculations shared by the detectors, the fixes and the verifier: pack sizes, name similarity, GMV, the
'not as described' return signal, classification, title requirements, claim-rule hits. Never imports llm."""

import re
from datetime import timedelta
from typing import Any

from app import policy, taxonomy
from app.metrics import _brand_words, _jaccard, _sim_tokens
from app.ops import metrics as om
from app.ops.catalog_qc.data import Listing
from app.ops.data import OpsData
from app.parsing import parse_pack

_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def pack_norm(text: str) -> str | None:
    """'3 kg' and '3000 g' both normalise to '3000g'; a size word such as 'Large' stays itself (lower case)."""
    n = parse_pack(text).get("normalized")
    if isinstance(n, str):
        return n
    return text.strip().lower() or None


def pack_amount(text: str) -> float | None:
    """Grams, millilitres or pieces, whichever the text states."""
    pack = parse_pack(text)
    for key in ("grams", "ml", "units"):
        if isinstance(pack.get(key), int | float):
            return float(pack[key])  # type: ignore[arg-type]
    return None


def pack_key(text: str) -> str | None:
    """Which attribute family a pack belongs to: pack_g, pack_ml or pack_pc."""
    pack = parse_pack(text)
    for key, attr in (("grams", "pack_g"), ("ml", "pack_ml"), ("units", "pack_pc")):
        if isinstance(pack.get(key), int | float):
            return attr
    return None


def same_pack(a: str, b: str) -> bool:
    return pack_norm(a) == pack_norm(b)


def similarity(a: Listing, b: Listing, brand: str) -> float:
    """Jaccard overlap of the title words (brand, stop words and sizes removed) plus the normalised pack: the same measure the
    onboarding Research stage uses for catalog overlap."""
    words = _brand_words(brand)
    return round(_jaccard(_sim_tokens(a.title, pack_norm(a.pack_size), words), _sim_tokens(b.title, pack_norm(b.pack_size), words)), 4)


def window(d: OpsData, days: int) -> tuple[Any, Any]:
    end = d.data_end
    return end - timedelta(days=days - 1), end


def listing_gmv(d: OpsData, sku_code: str, share: float, days: int) -> float:
    start, end = window(d, days)
    return round(om.gmv_in(d, [sku_code], start, end) * share, 2)


def nad_stats(d: OpsData, sku_code: str, reasons: list[str], days: int) -> tuple[int, int]:
    """(units returned citing a 'not as described' reason, units sold) in the last ``days`` of data."""
    start, end = window(d, days)
    wanted = {r.casefold() for r in reasons}
    returned = sum(r.units for r in d.returns if r.sku_code == sku_code and start <= r.day <= end and r.reason.casefold() in wanted)
    return returned, om.units_in(d, [sku_code], start, end)


def vendor_hint(d: OpsData, vendor_id: str) -> dict[str, str]:
    v = d.vendors[vendor_id]
    return taxonomy.segment_hints(f"{v.category} {v.brand}")


def classify(d: OpsData, listing: Listing) -> taxonomy.Classification:
    return taxonomy.classify(listing.title, listing.description, vendor_hint(d, listing.vendor_id))


def valid_subcategory(c: taxonomy.Classification) -> bool:
    return "subcategory_not_in_catalog" not in c.flags and c.subcategory in taxonomy.catalog_subcategories().get(c.category, frozenset())


def title_missing(title: str, pack_size: str, brand: str, required: list[str]) -> list[str]:
    """Which of the playbook's title requirements (brand, pack) the title does not meet."""
    low = title.lower()
    missing = []
    if "brand" in required and not all(w in low for w in re.findall(r"[a-z0-9]+", brand.lower())):
        missing.append("brand")
    if "pack" in required and pack_size.strip() and pack_norm(pack_size) != "1pc":
        amount = pack_amount(pack_size)
        in_title = pack_amount(title) if parse_pack(title).get("normalized") else None
        ok = (in_title is not None and amount is not None and abs(in_title - amount) < 1e-9) if amount is not None else pack_size.lower() in low
        if not ok:
            missing.append("pack")
    return missing


def claim_hits(text: str, category: str, where: str = "listing") -> list[dict[str, str]]:
    """Playbook claim rules (screening.claim_rules) that match ``text``: [{rule, text, severity, where}]."""
    out = []
    for rule in policy.get().screening.claim_rules:
        if not policy.in_scope(rule.categories, category):
            continue
        for m in policy.claim_regex(rule).finditer(text):
            out.append({"rule": rule.type, "text": m.group(0), "severity": rule.severity, "where": where})
    return out


def numbers_in(text: str) -> list[str]:
    return [m.group(0).replace(",", "") for m in _NUMBER.finditer(text)]


def has_attribute(attr: str, listing_attrs: dict[str, Any], mrp: float | None, pack_size: str) -> bool:
    """Whether a required attribute is filled. 'pack' and any pack_* name are met by a pack attribute or a pack size; 'mrp' by the price."""
    if attr == "mrp":
        return bool(mrp)
    if attr == "pack" or attr.startswith("pack_"):
        return any(k.startswith("pack") and listing_attrs.get(k) not in (None, "") for k in listing_attrs) or bool(pack_norm(pack_size))
    return listing_attrs.get(attr) not in (None, "")
