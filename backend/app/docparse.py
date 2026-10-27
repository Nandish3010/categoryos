"""Pure helpers for scanned documents: parse what a page prints, crop a region and hash its pixels.

No model calls and no I/O beyond the image bytes handed in, so the verifier can import it. The vision pipeline
(app.docs) and the verifier (app.verify) must agree on how a printed string becomes a number and on what a
"crop hash" is, and this module is where both get that from."""

import hashlib
import io
import re
from datetime import date

from PIL import Image

from app.parsing import parse_pack, parse_price

_MONTHS = {
    m: i + 1
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_ISO = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})\.?,?[\s-]+(\d{4})\b")
_MON_D_Y = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _month(name: str) -> int | None:
    return _MONTHS.get(name[:3].lower())


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | None) -> date | None:
    """A date as printed on a certificate: 30 NOV 2026, 30/11/2026 (day first), 2026-11-30, Nov 30, 2026."""
    if not text:
        return None
    if m := _ISO.search(text):
        return _make(int(m[1]), int(m[2]), int(m[3]))
    if m := _D_MON_Y.search(text):
        mon = _month(m[2])
        return _make(int(m[3]), mon, int(m[1])) if mon else None
    if m := _MON_D_Y.search(text):
        mon = _month(m[1])
        return _make(int(m[3]), mon, int(m[2])) if mon else None
    if m := _DMY.search(text):
        return _make(int(m[3]), int(m[2]), int(m[1]))
    return None


def norm_text(text: str | None) -> str:
    """Case-folded, punctuation-free, single-spaced text for comparing names and licence numbers."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def parse_value(kind: str, text: str | None) -> float | date | str | None:
    """Printed text -> a value by field type. pct is a fraction (30% -> 0.30); qty is grams, ml or units."""
    if text is None or not str(text).strip():
        return None
    raw = str(text)
    if kind == "date":
        return parse_date(raw)
    if kind == "text":
        return norm_text(raw)
    if kind == "pct":
        if m := _PCT.search(raw):
            return float(m[1]) / 100
        if m := _NUMBER.search(raw):
            return float(m[0].replace(",", "")) / 100
        return None
    if kind == "inr":
        return parse_price(raw)
    if kind == "qty":
        pack = parse_pack(raw)
        for key in ("grams", "ml", "units"):
            if isinstance(pack.get(key), int | float):
                return float(pack[key])  # type: ignore[arg-type]
        return None
    if kind == "number":
        m = _NUMBER.search(raw)
        return float(m[0].replace(",", "")) if m else None
    return None


def claim_number(kind: str, parsed: float | date | str | None, as_of: date | None) -> float | None:
    """The number a Claim carries: the value itself, or for a date the days from ``as_of`` to it."""
    if isinstance(parsed, date):
        return float((parsed - as_of).days) if as_of else None
    return float(parsed) if isinstance(parsed, int | float) else None


def valid_bbox(bbox: list[float] | None) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    x0, y0, x1, y1 = bbox
    return 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0


def clamp_bbox(bbox: list[float]) -> list[float]:
    """Force a model-supplied box into the page and order its corners."""
    x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in bbox)
    return [round(min(x0, x1), 4), round(min(y0, y1), 4), round(max(x0, x1), 4), round(max(y0, y1), 4)]


def _padded(bbox: list[float], pad: float) -> list[float]:
    x0, y0, x1, y1 = bbox
    return [max(x0 - pad, 0.0), max(y0 - pad, 0.0), min(x1 + pad, 1.0), min(y1 + pad, 1.0)]


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def crop(img: Image.Image, bbox: list[float], pad: float = 0.0) -> Image.Image:
    """The region of a page, padded by ``pad`` of the page. The box must already be valid."""
    w, h = img.size
    x0, y0, x1, y1 = _padded(bbox, pad)
    return img.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)))


def crop_digest(img: Image.Image) -> str:
    """sha256 over the crop's size and raw RGB pixels: independent of any PNG encoder, so a re-crop reproduces it."""
    rgb = img.convert("RGB")
    h = hashlib.sha256()
    h.update(f"{rgb.size[0]}x{rgb.size[1]}:".encode())
    h.update(rgb.tobytes())
    return h.hexdigest()


def crop_png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def region_digest(page_png: bytes, bbox: list[float], pad: float = 0.0) -> str:
    return crop_digest(crop(open_image(page_png), bbox, pad))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
