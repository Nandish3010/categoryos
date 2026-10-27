"""Verifier for the catalog fix queue. Called from app.ops.verify.verify_ops_claim for any claim whose source is one of the
live-catalog files or a pack label (``handles``). Every value a fix proposes is a claim checked here:

* deterministic fixes (engine claims) are recomputed from the data: the latest price-list row, the taxonomy classifier, the
  licence record, the name similarity of two listings, the returns and sales files, the playbook's image minimum;
* model-written text is checked by rules over the text carried in ``evidence.raw_value``: title length and required words,
  no claim the playbook bans, no number the row, the price list or the label does not support, and an attribute value must
  be quoted verbatim from the listing;
* numbers the model *stated* about the pack or MRP (``qc_stated_*``, origin model_extraction) are compared with the latest
  price list and go through the self-correction loop;
* label readings (vision_extraction) go through the same pixel-and-second-read check as the onboarding Catalog stage.

Never imports llm."""

import re
from collections.abc import Callable

from app import policy
from app.errors import CategoryOSError
from app.ops.catalog_qc import calc
from app.ops.catalog_qc.data import (
    FILES,
    LABEL_DIR,
    LIVE,
    PRICES,
    as_of,
    file_sha256,
    label_path,
    load,
)
from app.ops.data import load as load_ops
from app.parsing import parse_pack
from app.schemas import Claim
from app.verify import _finish, vision_check

PREFIX = "qc_"
_SPACE = re.compile(r"\s+")


def handles(claim: Claim) -> bool:
    rel = claim.source_ref.file
    return rel in (LIVE, PRICES, "ops/catalog_licences.json") or rel.startswith(f"{LABEL_DIR}/") or (rel in FILES and claim.metric.startswith(PREFIX))


def _squash(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


class _Reject(Exception):
    def __init__(self, reason: str, recomputed: float | None = None) -> None:
        super().__init__(reason)
        self.reason, self.recomputed = reason, recomputed


def _sku(claim: Claim) -> tuple[str, str]:
    key = claim.sku_key or claim.source_ref.key
    vendor, _, sku = key.partition(":")
    return vendor, sku


def _listing(claim: Claim):
    x = load().listing(claim.source_ref.key.split("|")[0])
    if x is None:
        raise _Reject(f"no listing {claim.source_ref.key!r} in the live catalog")
    return x


def _price(claim: Claim):
    _, sku = _sku(claim)
    row = load().latest_price(sku, as_of())
    if row is None:
        raise _Reject(f"no price-list row in force for {sku}")
    return row


def _mrp(claim: Claim) -> float:
    return _price(claim).mrp


def _pack_qty(claim: Claim) -> float:
    row = _price(claim)
    amount = calc.pack_amount(row.pack_size)
    if amount is None:
        raise _Reject(f"price list row {row.row} gives no measurable pack ({row.pack_size!r})")
    return amount


def _category(claim: Claim) -> float:
    x = _listing(claim)
    cat, _, sub = (claim.evidence.raw_value if claim.evidence and claim.evidence.raw_value else "").partition("|")
    c = calc.classify(load_ops(), x)
    if c.category != cat:
        raise _Reject(f"the taxonomy classifies {x.listing_id} as {c.category}, not {cat}", 0.0)
    if sub and calc.valid_subcategory(c) and c.subcategory != sub:
        raise _Reject(f"the taxonomy classifies the subcategory as {c.subcategory}, not {sub}", 0.0)
    return 1.0


def _licence_days(claim: Claim) -> float:
    lic = load().licence(claim.source_ref.key)
    if lic is None:
        raise _Reject(f"no licence {claim.source_ref.key!r} on file")
    return float((lic.valid_until - as_of()).days)


def _dup(claim: Claim) -> float:
    a_id, _, b_id = claim.source_ref.key.partition("|")
    a, b = load().listing(a_id), load().listing(b_id)
    if a is None or b is None:
        raise _Reject(f"listing {a_id!r} or {b_id!r} is not in the live catalog")
    return calc.similarity(a, b, load_ops().vendors[a.vendor_id].brand)


def _image_px(claim: Claim) -> float:
    return float(policy.get().catalog_qc.images.min_resolution_px)


def _nad(which: str) -> Callable[[Claim], float]:
    def fn(claim: Claim) -> float:
        _, sku = _sku(claim)
        r = policy.get().catalog_qc.returns
        returned, sold = calc.nad_stats(load_ops(), sku, r.reasons, r.window_days)
        return float(returned if which == "returned" else sold)

    return fn


def _text(claim: Claim) -> str:
    if claim.evidence is None or claim.evidence.raw_value is None:
        raise _Reject("no evidence: the proposed text is required")
    return claim.evidence.raw_value


def _title_chars(claim: Claim) -> float:
    n = len(_text(claim))
    limit = policy.get().catalog.title_max_chars
    if n > limit:
        raise _Reject(f"the proposed title is {n} characters; the limit is {limit}", float(n))
    return float(n)


def _title_required(claim: Claim) -> float:
    x = _listing(claim)
    row = load().latest_price(x.sku_code, as_of())
    pack = row.pack_size if row is not None else x.pack_size
    missing = calc.title_missing(_text(claim), pack, load_ops().vendors[x.vendor_id].brand, policy.get().catalog_qc.title_required)
    if missing:
        raise _Reject(f"the proposed title lacks the {' and '.join(missing)}", float(len(missing)))
    return 0.0


def _banned(claim: Claim) -> float:
    x = _listing(claim)
    hits = calc.claim_hits(_text(claim), x.category)
    if hits:
        raise _Reject("the proposed text still contains " + ", ".join(f"'{h['text']}' ({h['rule']})" for h in hits), float(len(hits)))
    return 0.0


def allowed_numbers(listing_id: str, extra: str = "") -> set[str]:
    """Numbers a rewrite may state: those already in the row (title, bullets, description, attributes), the latest price-list row,
    and ``extra`` (numbers of verified label readings, supplied by the pipeline as comma-separated text)."""
    x = load().listing(listing_id)
    assert x is not None
    texts = [x.text, *(str(v) for v in x.attributes.values())]
    price = load().latest_price(x.sku_code, as_of())
    nums: set[str] = set()
    for t in texts:
        nums.update(calc.numbers_in(t))
    if price is not None:
        nums.update({f"{price.mrp:g}", *calc.numbers_in(price.pack_size)})
        amount = calc.pack_amount(price.pack_size)
        pack = parse_pack(price.pack_size)
        if amount is not None:
            nums.add(f"{amount:g}")
            if isinstance(pack.get("grams"), int | float):
                nums.add(f"{amount / 1000:g}")  # 3000 g is written 3 kg
    nums.update(n.strip() for n in extra.split(",") if n.strip())
    return nums | {n.rstrip("0").rstrip(".") if "." in n else n for n in nums}


def _unsupported(claim: Claim) -> float:
    extra = str(claim.evidence.normalized_value or "") if claim.evidence else ""
    ok = allowed_numbers(claim.source_ref.key.split("|")[0], extra)
    bad = [n for n in calc.numbers_in(_text(claim)) if n not in ok and n.rstrip("0").rstrip(".") not in ok]
    if bad:
        raise _Reject("the proposed text states number(s) the row, the price list and the label do not support: " + ", ".join(bad), float(len(bad)))
    return 0.0


def _attr_quote(claim: Claim) -> float:
    x = _listing(claim)
    quote = _text(claim)
    value = str(claim.evidence.normalized_value or "") if claim.evidence else ""
    if not value or _squash(quote) not in _squash(x.text):
        raise _Reject("the quote does not appear verbatim in the listing", 0.0)
    attr = claim.source_ref.column or ""
    named = re.search(rf"\b{re.escape(value)}\b", quote, re.IGNORECASE)
    boolean = value.casefold() in {"yes", "no"} and all(w in quote.casefold() for w in attr.split("_"))
    if not (named or boolean):
        raise _Reject(f"the quote does not state {attr} = {value!r}", 0.0)
    return 1.0


def _stated(metric: str) -> Callable[[Claim], float]:
    return _pack_qty if metric == "qc_stated_pack_qty" else _mrp


METRICS: dict[str, Callable[[Claim], float]] = {
    "qc_mrp": _mrp,
    "qc_pack_qty": _pack_qty,
    "qc_stated_mrp": _mrp,
    "qc_stated_pack_qty": _pack_qty,
    "qc_category_agrees": _category,
    "qc_licence_days_left": _licence_days,
    "qc_dup_similarity": _dup,
    "qc_image_min_px": _image_px,
    "qc_nad_returned_units": _nad("returned"),
    "qc_nad_sold_units": _nad("sold"),
    "qc_title_chars": _title_chars,
    "qc_title_required_missing": _title_required,
    "qc_banned_claims": _banned,
    "qc_unsupported_numbers": _unsupported,
    "qc_attr_quote": _attr_quote,
}


def _verify_label(claim: Claim) -> Claim:
    ev = claim.evidence
    if claim.origin != "vision_extraction":
        return _finish(claim, "rejected", "label files are only read by vision extraction")
    if ev is None or ev.bbox is None or not ev.crop_sha256 or ev.raw_value is None:
        return _finish(claim, "rejected", "no evidence: the scan, a bounding box, a crop hash and the printed text are required")
    path = label_path(claim.source_ref.file[len(LABEL_DIR) + 1 :])
    if path is None:
        return _finish(claim, "rejected", f"unknown source: {claim.source_ref.file!r} is not a label in the manifest")
    if file_sha256(claim.source_ref.file) != ev.sha256:
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the scan")
    return vision_check(claim, path.read_bytes)


def verify_catalog_claim(claim: Claim) -> Claim:
    if claim.source_ref.file.startswith(f"{LABEL_DIR}/"):
        return _verify_label(claim)
    fn = METRICS.get(claim.metric)
    if fn is None:
        return _finish(claim, "unverifiable", f"unknown catalog metric {claim.metric!r}")
    ev = claim.evidence
    if ev is not None and ev.sha256 and claim.source_ref.file in FILES and ev.sha256 != file_sha256(claim.source_ref.file):
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    try:
        recomputed = fn(claim)
    except _Reject as exc:
        return _finish(claim, "rejected", exc.reason, exc.recomputed)
    except (CategoryOSError, ValueError, KeyError) as exc:
        return _finish(claim, "rejected", f"cannot recompute: {getattr(exc, 'problem', str(exc))}")
    if abs(recomputed - claim.value) <= policy.tol(claim.unit):
        return _finish(claim, "verified", None, recomputed)
    if claim.metric in ("qc_stated_mrp", "qc_stated_pack_qty", "qc_mrp", "qc_pack_qty") and claim.evidence and claim.evidence.row:
        return _finish(claim, "rejected", f"price list row {claim.evidence.row} ({claim.evidence.header}) parses to {recomputed:g}, claim says {claim.value:g}", recomputed)
    return _finish(claim, "rejected", f"recomputed {recomputed:g}, claim says {claim.value:g}", recomputed)
