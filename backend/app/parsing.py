import re

PARSER_VERSION = "1.0"

_NUM = r"\d[\d,]*(?:\.\d+)?"
_PRICE_RE = re.compile(_NUM)
_PACK_RE = re.compile(
    rf"(?P<num>{_NUM})\s*(?P<unit>kilograms?|kgs?|grams?|gms?|g|millilit(?:er|re)s?|ml|lit(?:er|re)s?|ltrs?|l|"
    r"pcs?|pieces?|units?)\b",
    re.IGNORECASE,
)
_PACK_OF_RE = re.compile(r"pack\s+of\s+(\d+)", re.IGNORECASE)

_COLUMN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cost", re.compile(r"\bcost\b")),
    ("mrp", re.compile(r"\bm\s*r\s*p\b|\bprice\b")),
    ("pack", re.compile(r"\bpack\b|\bsize\b|\bqty\b|\bweight\b|\bvol")),
    ("name", re.compile(r"^(product name|item|sku desc|name|title)$")),
    ("code", re.compile(r"\bcode\b|\bstyle no\b|^sku$")),
    ("description", re.compile(r"ingredients|claims|details|remarks|about|notes")),
)


def parse_price(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    match = _PRICE_RE.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_pack(raw: str | None) -> dict[str, float | int | str | None]:
    empty: dict[str, float | int | str | None] = {"normalized": None}
    if raw is None or not raw.strip():
        return empty
    text = raw.strip()
    of = _PACK_OF_RE.search(text)
    if of:
        units = int(of.group(1))
        return {"units": units, "normalized": f"{units}pc"}
    match = _PACK_RE.search(text)
    if not match:
        return empty
    amount = float(match.group("num").replace(",", ""))
    unit = match.group("unit").lower()
    if unit.startswith("k"):
        grams = round(amount * 1000, 4)
        return {"grams": grams, "normalized": f"{grams:g}g"}
    if unit.startswith("g"):
        return {"grams": amount, "normalized": f"{amount:g}g"}
    if unit.startswith("m"):
        return {"ml": amount, "normalized": f"{amount:g}ml"}
    if unit.startswith("l"):
        ml = round(amount * 1000, 4)
        return {"ml": ml, "normalized": f"{ml:g}ml"}
    units = int(amount)
    return {"units": units, "normalized": f"{units}pc"}


def _norm_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def map_columns(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    weak_description: str | None = None
    for header in headers:
        norm = _norm_header(header)
        if not norm:
            continue
        if norm == "description":
            weak_description = header
            continue
        for field, pattern in _COLUMN_RULES:
            if field not in mapping and pattern.search(norm):
                mapping[field] = header
                break
    if weak_description is not None:
        field = "description" if "name" in mapping else "name"
        mapping.setdefault(field, weak_description)
    return mapping
