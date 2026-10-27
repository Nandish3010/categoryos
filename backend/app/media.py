"""Media gateway: images (muse-image), segmentation (SAM 3.1), transcription (muse-voice) and the local image store.

Live paths follow the public Meta docs (dev.meta.ai); shapes were verified against the live API on 2026-10-27
(raw responses in fixtures/contract/, replayed by tests/test_contract_fixtures.py):
- images:  POST {base}/images/generations  {model, prompt, n, size, response_format: b64_json, output_format: png}
           -> data[0].b64_json
- SAM:     POST {base}/responses (stream) {model: sam-3.1, input: [{type: message, role: user, content:
           [input_text <noun phrase>, input_image <data url>]}]} -> output_text deltas holding, per match, an object id,
           one box token (x1,y1,x2,y2,w,h[,c]) and one mask token (x=0,y=0,data=<H>,<W>,<enc><base85 payload>)
- ASR:     POST {base}/asr/transcribe multipart: `request` (JSON: model, audioEncoding, mode) + `audio` (WAV)
           -> {sessionId, transcript, audioDurationMs, turns[]}

In mock and replay mode no network is touched: deterministic Pillow placeholders stand in for every image.
Every spend goes through app.ledger (muse-image per image, sam per call, voice per audio hour)."""

import base64
import difflib
import io
import json
import logging
import re
import wave
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

from app import ledger, llm
from app.config import settings
from app.constants import ALLOWED_VENDORS
from app.errors import (
    CategoryOSError,
    CreditsUnavailable,
    LlmBadOutput,
    LlmUnavailable,
    MissingKey,
)

log = logging.getLogger("categoryos.media")

KINDS = ("packshot", "cutout", "lifestyle")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.png$")
_ASSET_NAME = re.compile(r"^(?:(?P<code>[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*)-(?P<kind>packshot|cutout|lifestyle)|campaign)\.png$")

SAM_MIN_COVERAGE = 0.01
SAM_MAX_COVERAGE = 0.98


class SegmentationUnusable(CategoryOSError):
    status = 502
    code = "segmentation_unusable"
    problem = "SAM returned no usable mask"
    cause = "No match, an undecodable mask, or a mask covering almost nothing or everything"
    fix = "The catalog shows the packshot with a 'cutout unavailable' label"


# ---------- asset store ----------


def asset_dir(vendor_id: str) -> Path:
    return Path(settings.assets_dir) / vendor_id


def asset_url(vendor_id: str, name: str) -> str:
    return f"/api/assets/{vendor_id}/{name}"


def asset_name(code: str, kind: str) -> str:
    return f"{code}-{kind}.png"


def _manifest_path(vendor_id: str) -> Path:
    return asset_dir(vendor_id) / "manifest.json"


def read_manifest(vendor_id: str) -> dict[str, str]:
    try:
        return json.loads(_manifest_path(vendor_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_asset(vendor_id: str, name: str, data: bytes, source: str) -> None:
    folder = asset_dir(vendor_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    manifest = read_manifest(vendor_id)
    manifest[name] = source
    _manifest_path(vendor_id).write_text(json.dumps(manifest, indent=2, sort_keys=True))


def cached_source(vendor_id: str, name: str) -> str | None:
    """'live' or 'placeholder' when the file exists, else None."""
    if not (asset_dir(vendor_id) / name).exists():
        return None
    return read_manifest(vendor_id).get(name, "placeholder")


def resolve_asset(vendor_id: str, name: str) -> Path | None:
    """Path-safe lookup: vendor must be known, the name a plain png filename, and the result inside the vendor folder."""
    if vendor_id not in ALLOWED_VENDORS or not _SAFE_NAME.match(name) or not _ASSET_NAME.match(name):
        return None
    folder = asset_dir(vendor_id).resolve()
    path = (folder / name).resolve()
    if path.parent != folder:
        return None
    return path


def is_known_asset_name(name: str) -> tuple[str, str] | None:
    """(sku code or 'campaign', kind) for a name the pipeline could have produced."""
    match = _ASSET_NAME.match(name)
    if not match:
        return None
    return (match.group("code") or "campaign", match.group("kind") or "campaign")


# ---------- placeholders ----------


def _font(size: int) -> Any:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:4]


def placeholder_png(kind: str, title: str, subtitle: str = "") -> bytes:
    """A small neutral card with the product name and a 'placeholder' label. Deterministic."""
    size = {"lifestyle": (640, 400), "campaign": (640, 360)}.get(kind, (400, 400))
    transparent = kind == "cutout"
    img = Image.new("RGBA" if transparent else "RGB", size, (0, 0, 0, 0) if transparent else (238, 240, 242))
    draw = ImageDraw.Draw(img)
    pad = 28
    draw.rounded_rectangle(
        (pad, pad, size[0] - pad, size[1] - pad), radius=24, fill=(250, 250, 251, 255), outline=(176, 182, 190, 255), width=3
    )
    inner = size[0] - 2 * pad - 32
    y = pad + 24
    draw.text((pad + 16, y), kind.upper(), font=_font(16), fill=(120, 128, 138, 255))
    y += 34
    big = _font(26)
    for line in _wrap(draw, title, big, inner):
        draw.text((pad + 16, y), line, font=big, fill=(32, 36, 44, 255))
        y += 34
    if subtitle:
        y += 4
        small = _font(18)
        for line in _wrap(draw, subtitle, small, inner)[:2]:
            draw.text((pad + 16, y), line, font=small, fill=(88, 96, 108, 255))
            y += 24
    draw.text((pad + 16, size[1] - pad - 36), "placeholder · live image pending", font=_font(16), fill=(168, 92, 24, 255))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def ensure_placeholder(vendor_id: str, name: str, kind: str, title: str, subtitle: str = "") -> None:
    if cached_source(vendor_id, name) is None:
        write_asset(vendor_id, name, placeholder_png(kind, title, subtitle), "placeholder")


# ---------- live clients (patched in tests) ----------


def _client() -> Any:
    return llm._make_client("meta")


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=120.0)


def _guard() -> None:
    if not settings.model_api_key:
        raise MissingKey(cause="MODEL_API_KEY is empty")
    ledger.check_budget()


def _map_error(exc: Exception) -> CategoryOSError:
    status = llm._status(exc)
    if status in (402, 403):
        return CreditsUnavailable(cause=f"provider returned HTTP {status}")
    if status == 401:
        return MissingKey(problem="The provider rejected the API key (401)", cause="the key is invalid or revoked")
    return LlmUnavailable(cause=f"{type(exc).__name__}: {str(exc)[:160]}")


@dataclass
class Spend:
    model: str
    cost_usd: float


async def generate_image(prompt: str, *, size: str = "1024x1024") -> tuple[bytes, Spend]:
    """muse-image-1.0 via /v1/images/generations, b64 PNG. Priced per image."""
    _guard()
    client = _client()
    try:
        resp = await client.images.generate(
            model=settings.model_image,
            prompt=prompt,
            n=1,
            size=size,
            response_format="b64_json",
            extra_body={"output_format": "png"},
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    cost = ledger.record(settings.model_image, {"images": 1})
    try:
        data = base64.b64decode(resp.data[0].b64_json)
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:
        raise LlmBadOutput(cause=f"muse-image returned no decodable image: {exc!r}"[:200]) from exc
    return data, Spend(settings.model_image, cost)


# ---------- SAM ----------

_BOX = re.compile(r"x1=(?P<x1>-?[\d.]+)\D+?y1=(?P<y1>-?[\d.]+)\D+?x2=(?P<x2>-?[\d.]+)\D+?y2=(?P<y2>-?[\d.]+)")
# Live-verified (2026-10-27): the token is `<|mask;x=0;y=0;data=H,W,<enc><payload>|>`; the payload alphabet never holds | < > so the
# closing `|>` ends it (non-greedy, so the delimiter is never swallowed into the payload). H is the mask height, W its width; they differ slightly from the image's own size.
_MASK = re.compile(r"data=(?P<h>\d+),(?P<w>\d+),(?P<enc>[~!])(?P<payload>\S+?)(?:\|>|\s|$)")


@dataclass
class SamRecord:
    box: tuple[float, float, float, float] | None
    mask_h: int
    mask_w: int
    enc: str
    payload: str


def parse_sam_text(text: str) -> list[SamRecord]:
    """One record per match: the box token before its mask token. Fields are read by key, as the docs advise."""
    records: list[SamRecord] = []
    cursor = 0
    for m in _MASK.finditer(text):
        box = None
        b = None
        for b in _BOX.finditer(text, cursor, m.start()):  # keep the last box before this mask
            pass
        if b is not None:
            box = (float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"]))
        records.append(SamRecord(box, int(m["h"]), int(m["w"]), m["enc"], m["payload"]))
        cursor = m.end()
    return records


META_B85 = "!#$%&'()*+-./0123456789:=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{"  # ASCII order, 85 digits
_META_INDEX = {c: i for i, c in enumerate(META_B85)}


def meta_unpack(body: str) -> bytes:
    """Meta's base85 (custom alphabet, 5 chars -> 4 bytes big-endian, a short last group padded with the top digit).
    Live-verified: the result is a 4-byte big-endian length followed by exactly that many arithmetic-coded bytes."""
    out = bytearray()
    for i in range(0, len(body), 5):
        group = body[i : i + 5]
        value = 0
        for ch in group:
            value = value * 85 + _META_INDEX[ch]
        value = value * 85 ** (5 - len(group)) + (85 ** (5 - len(group)) - 1)
        if value >= 1 << 32:
            raise ValueError("base85 group overflows 32 bits")
        out += value.to_bytes(4, "big")[: 4 if len(group) == 5 else len(group) - 1]
    if len(out) < 4 or int.from_bytes(out[:4], "big") != len(out) - 4:
        raise ValueError("length prefix does not match the payload")
    return bytes(out)


def _decode_arithmetic(rec: SamRecord) -> list[int]:
    """The real SAM 3.1 payload (both `~` lossless and `!` one_bit) is arithmetic-coded. Meta ships the decoder as the
    dependency-free `meta-sam-parser` package; it is used when installed, otherwise the cutout is reported unavailable
    and callers fall back to the box token (segment_region) or the packshot (segment)."""
    try:
        from meta_sam_parser import SegmentationMask, decode_mask_to_raster  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SegmentationUnusable(cause="the mask is arithmetic-coded and the optional meta-sam-parser package is not installed") from exc
    mask = SegmentationMask("lossless" if rec.enc == "~" else "one_bit", rec.enc + rec.payload, rec.mask_w, rec.mask_h)
    return list(decode_mask_to_raster(mask))


def decode_mask(rec: SamRecord) -> list[int]:
    """Row-major 0/1 values, length H*W.
    Real payloads (live-verified): marker `~`|`!`, then Meta base85 holding a length prefix + an arithmetic-coded body; those go
    to meta-sam-parser when installed. Legacy fallback (what the fakes in the tests send): plain base85, raw or bit-packed
    (MSB first), optionally zlib-compressed."""
    try:
        meta_unpack(rec.payload)
        is_meta = True
    except (ValueError, KeyError):
        is_meta = False
    if is_meta:
        try:
            bits = _decode_arithmetic(rec)
        except SegmentationUnusable:
            raise
        except Exception as exc:
            raise SegmentationUnusable(cause=f"undecodable mask: {type(exc).__name__}: {str(exc)[:120]}") from exc
        if len(bits) != rec.mask_h * rec.mask_w:
            raise SegmentationUnusable(cause=f"decoded mask has {len(bits)} cells, expected {rec.mask_h * rec.mask_w}")
        return bits
    cells = rec.mask_h * rec.mask_w
    last_error: Exception | None = None
    for payload in (rec.payload, rec.payload[:-1]):  # the closing delimiter of a token may stick to the payload
        try:
            raw = base64.b85decode(payload)
        except ValueError as exc:
            last_error = exc
            continue
        for blob in (raw, _inflate(raw)):
            if blob is None:
                continue
            if len(blob) == cells:
                return [1 if v else 0 for v in blob]
            if len(blob) == (cells + 7) // 8:
                return [(blob[i // 8] >> (7 - i % 8)) & 1 for i in range(cells)]
        last_error = ValueError(f"mask payload of {len(raw)} bytes does not fit {rec.mask_h}x{rec.mask_w}")
    raise SegmentationUnusable(cause=f"undecodable mask: {last_error}")


def _inflate(raw: bytes) -> bytes | None:
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return None


def cutout_png(source_png: bytes, record: SamRecord) -> bytes:
    """Transparent PNG: the packshot with the mask as alpha, cropped to the mask."""
    bits = decode_mask(record)
    mask = Image.new("L", (record.mask_w, record.mask_h))
    mask.putdata([255 if b else 0 for b in bits])
    coverage = sum(bits) / max(len(bits), 1)
    if not (SAM_MIN_COVERAGE <= coverage <= SAM_MAX_COVERAGE):
        raise SegmentationUnusable(cause=f"mask covers {coverage:.1%} of the image")
    img = Image.open(io.BytesIO(source_png)).convert("RGBA")
    mask = mask.resize(img.size, Image.NEAREST)
    img.putalpha(mask)
    bbox = mask.getbbox()
    if bbox:
        img = img.crop(bbox)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def _sam_text(source_png: bytes, phrase: str) -> tuple[str, Spend]:
    """One SAM 3.1 call (Responses API, streamed): the concatenated output text and what it cost."""
    _guard()
    client = _client()
    mime = "image/jpeg" if source_png[:2] == b"\xff\xd8" else "image/png"
    data_url = f"data:{mime};base64," + base64.b64encode(source_png).decode()
    text = ""
    try:
        stream = await client.responses.create(
            model=settings.model_seg,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": phrase}, {"type": "input_image", "image_url": data_url}],
                }
            ],
            stream=True,
            extra_body={"metadata": {"mask_encoding": "one_bit"}},  # live-verified: ~100 bytes instead of ~8 KB for a 160x112 mask
        )
        async for event in stream:
            if getattr(event, "type", "") == "response.output_text.delta":
                text += event.delta
    except Exception as exc:
        raise _map_error(exc) from exc
    return text, Spend(settings.model_seg, ledger.record(settings.model_seg, {"images": 1}))


async def segment(source_png: bytes, phrase: str) -> tuple[bytes, Spend]:
    """SAM 3.1 via the Responses API (streamed). Returns a transparent cutout of the first match."""
    text, spend = await _sam_text(source_png, phrase)
    records = parse_sam_text(text)
    if not records:
        raise SegmentationUnusable(cause="SAM found no match for the prompt")
    return cutout_png(source_png, records[0]), spend


def _normalise_box(box: tuple[float, float, float, float], width: int, height: int) -> list[float] | None:
    """A SAM box as fractions of the image. Live-verified: the box tokens are pixel coordinates of the image that was sent
    (x2/y2 inclusive, w/h its size); values that all lie within 0..1 are taken as already normalised."""
    x0, y0, x1, y1 = box
    if max(abs(v) for v in box) > 1.0:
        x0, x1, y0, y1 = x0 / width, x1 / width, y0 / height, y1 / height
    x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in (x0, y0, x1, y1))
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def region_from_record(record: SamRecord, width: int, height: int) -> list[float]:
    """The matched region as a normalised [x0, y0, x1, y1]: the mask's extent when it decodes (it is what SAM actually
    segmented), else the box token."""
    try:
        bits = decode_mask(record)
        mask = Image.new("L", (record.mask_w, record.mask_h))
        mask.putdata([255 if b else 0 for b in bits])
        extent = mask.getbbox()
        coverage = sum(bits) / max(len(bits), 1)
        if extent and SAM_MIN_COVERAGE <= coverage <= SAM_MAX_COVERAGE:
            return [round(extent[0] / record.mask_w, 4), round(extent[1] / record.mask_h, 4), round(extent[2] / record.mask_w, 4), round(extent[3] / record.mask_h, 4)]
    except SegmentationUnusable:
        pass
    if record.box is not None and (region := _normalise_box(record.box, width, height)):
        return region
    raise SegmentationUnusable(cause="SAM matched the phrase but returned neither a usable mask nor a box")


async def segment_region(source_png: bytes, phrase: str) -> tuple[list[float], Spend]:
    """SAM 3.1 finds a described region of a page (for example a label's nutrition and claims panel). Returns its
    normalised box [x0, y0, x1, y1]; the caller crops the page itself, so the pixels it hashes are its own."""
    text, spend = await _sam_text(source_png, phrase)
    records = parse_sam_text(text)
    if not records:
        raise SegmentationUnusable(cause="SAM found no match for the prompt")
    img = Image.open(io.BytesIO(source_png))
    return region_from_record(records[0], img.width, img.height), spend


# ---------- ASR ----------


@dataclass
class Transcription:
    text: str
    hours: float
    spend: Spend


def wav_hours(wav: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav)) as fh:
            return fh.getnframes() / float(fh.getframerate()) / 3600
    except (wave.Error, EOFError, ZeroDivisionError):
        return len(wav) / (16000 * 2) / 3600  # assume 16 kHz mono 16-bit


def _asr_text(body: Any) -> str:
    """Live-verified body: {sessionId, transcript, audioDurationMs, turns[]}. Silence or non-speech gives transcript "" (not an error)."""
    if isinstance(body, dict):
        if isinstance(body.get("transcript"), str) and not body["transcript"].strip() and not body.get("turns"):
            return ""
        for key in ("text", "transcript", "transcription"):
            if isinstance(body.get(key), str) and body[key].strip():
                return body[key].strip()
        for key in ("turns", "segments", "results"):
            items = body.get(key)
            if isinstance(items, list):
                parts = [str(i.get("text") or i.get("transcript") or "") if isinstance(i, dict) else str(i) for i in items]
                joined = " ".join(p.strip() for p in parts if p.strip())
                if joined:
                    return joined
    raise LlmBadOutput(cause="the transcription response had no text, transcript, turns or segments")


async def transcribe(wav: bytes) -> Transcription:
    """muse-voice-transcribe-1.0 via POST /v1/asr/transcribe: multipart `request` JSON + `audio` WAV. $0.18 per hour."""
    _guard()
    request = {"model": settings.model_voice, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    try:
        async with _http() as http:
            resp = await http.post(
                f"{settings.model_api_base_url.rstrip('/')}/asr/transcribe",
                headers={"Authorization": f"Bearer {settings.model_api_key}", "Accept": "application/json"},
                files={"request": (None, json.dumps(request), "application/json"), "audio": ("call.wav", wav, "audio/wav")},
            )
    except httpx.HTTPError as exc:
        raise LlmUnavailable(cause=f"{type(exc).__name__}: {str(exc)[:160]}") from exc
    if resp.status_code in (402, 403):
        raise CreditsUnavailable(cause=f"provider returned HTTP {resp.status_code}")
    if resp.status_code == 401:
        raise MissingKey(problem="The provider rejected the API key (401)", cause="the key is invalid or revoked")
    if resp.status_code >= 400:
        raise LlmUnavailable(cause=f"transcription returned HTTP {resp.status_code}")
    text = _asr_text(resp.json())
    hours = wav_hours(wav)
    cost = ledger.record(settings.model_voice, {"hours": hours})
    return Transcription(text, hours, Spend(settings.model_voice, cost))


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace(",", ""))


@dataclass
class TranscriptDiff:
    similarity_pct: float
    changes: list[dict[str, str]] = field(default_factory=list)


def diff_transcripts(canonical: str, asr: str) -> TranscriptDiff:
    """Word-level similarity (0-100) between the canonical transcript and the ASR text, plus the differing spans."""
    a, b = words(canonical), words(asr)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changes = [
        {"op": op, "canonical": " ".join(a[i1:i2]), "asr": " ".join(b[j1:j2])}
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
        if op != "equal"
    ]
    return TranscriptDiff(round(matcher.ratio() * 100, 1), changes[:40])
