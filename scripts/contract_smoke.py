"""Live contract smoke: one tiny real call per external-API contract the app assumes.

Run from backend/:  uv run python ../scripts/contract_smoke.py [--only name ...]   (or: make contract)

Refuses to run unless MODEL_MODE=live. Each check goes through the app's OWN gateway/helper (so the real code path
is exercised) while a recording proxy captures the raw, unparsed provider response, which is scrubbed and saved to
backend/fixtures/contract/<name>.json. Spend is tracked in a throwaway ledger and printed at the end.
Synthetic inputs only. Keys are read from the environment and never printed or saved.
"""

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import re
import struct
import sys
import tempfile
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if os.environ.get("MODEL_MODE") != "live":
    sys.exit("refusing to run: set MODEL_MODE=live (this script spends real credits; see `make contract`)")

# throwaway ledger so the total printed is this run only
os.environ["LEDGER_PATH"] = str(Path(tempfile.mkdtemp(prefix="contract-ledger-")) / "ledger.json")

import httpx
from pydantic import BaseModel

from app import ledger, llm, media, prompts_docs
from app.config import settings
from app.schemas import VisionExtraction
from app.tools import select

REPO = BACKEND.parent
OUT = BACKEND / "fixtures" / "contract"
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")
CAPTURE: dict[str, Any] = {}  # raw responses of the current check


# ---------- scrubbing ----------


def scrub(obj: Any) -> Any:
    """JSON-safe copy: long strings (base64 blobs) become prefix + length + sha256; secrets removed."""
    if isinstance(obj, dict):
        return {k: ("[scrubbed]" if k.lower() in {"authorization", "api_key", "x-api-key"} else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        obj = SECRET.sub("[scrubbed]", obj)
        if len(obj) > 4000:
            return {"_truncated": True, "prefix": obj[:120], "length": len(obj), "sha256": hashlib.sha256(obj.encode()).hexdigest()}
        return obj
    if isinstance(obj, int | float | bool) or obj is None:
        return obj
    if hasattr(obj, "model_dump"):
        return scrub(obj.model_dump())
    return scrub(repr(obj))


def _dump(obj: Any) -> Any:
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


# ---------- recording proxies ----------


class _Rec:
    """Wraps an SDK resource: the awaited result (or each stream event) is stored under CAPTURE[key] (a list)."""

    def __init__(self, target: Any, key: str) -> None:
        self._t, self._k = target, key

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._t, name)
        if not callable(attr):
            return _Rec(attr, self._k + "." + name) if hasattr(attr, "__dict__") else attr

        async def call(*a: Any, **kw: Any) -> Any:
            res = await attr(*a, **kw)
            bucket = CAPTURE.setdefault(self._k + "." + name, [])
            req = {k: v for k, v in kw.items() if k not in {"messages", "input"}}
            bucket.append({"request_params": scrub(req), "events": None, "response": None})
            if kw.get("stream"):
                return _Stream(res, bucket[-1])
            bucket[-1]["response"] = _dump(res)
            return res

        return call


class _Stream:
    def __init__(self, stream: Any, slot: dict[str, Any]) -> None:
        self._s, self._slot = stream, slot
        slot["events"] = []

    def __aiter__(self) -> "_Stream":
        self._it = self._s.__aiter__()
        return self

    async def __anext__(self) -> Any:
        ev = await self._it.__anext__()
        self._slot["events"].append(_dump(ev))
        return ev


class _RecHttp(httpx.AsyncClient):
    async def post(self, url: Any, **kw: Any) -> httpx.Response:  # type: ignore[override]
        resp = await super().post(url, **kw)
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text[:2000]
        CAPTURE.setdefault("asr", []).append({"status": resp.status_code, "content_type": resp.headers.get("content-type"), "body": body})
        return resp


_orig_make_client = llm._make_client


def _recording_make_client(provider: str) -> Any:
    return _Rec(_orig_make_client(provider), "client")


llm._make_client = _recording_make_client  # media._client() delegates to llm._make_client
media._http = lambda: _RecHttp(timeout=120.0)


# ---------- inputs ----------


def _wav() -> bytes:
    """A short synthetic utterance from macOS `say` (16 kHz mono WAV); elsewhere 2 s of a 440 Hz tone (checks transport only)."""
    import shutil
    import subprocess

    if shutil.which("say"):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "u.wav"
            try:
                subprocess.run(["say", "-o", str(out), "--data-format=LEI16@16000", "Price is forty five rupees per kilo."], check=True, timeout=30)
                return out.read_bytes()
            except (subprocess.SubprocessError, OSError):
                pass
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(32000)))
    return buf.getvalue()


def _doc() -> tuple[Path, bytes]:
    p = REPO / "data" / "synthetic" / "vendors" / "V001" / "docs" / "fssai_certificate.jpg"
    return p, p.read_bytes()


class Mini(BaseModel):
    animal: str
    legs: int


# ---------- checks ----------


@dataclass
class Row:
    name: str
    model: str
    status: str
    cost: float
    note: str


CHECKS: dict[str, Callable[[], Awaitable[tuple[str, str, str]]]] = {}  # name -> () -> (model, status, note)


def check(fn: Callable[[], Awaitable[tuple[str, str, str]]]) -> Callable[[], Awaitable[tuple[str, str, str]]]:
    CHECKS[fn.__name__.removeprefix("c_")] = fn
    return fn


def _chat_shape(raw: dict[str, Any]) -> str:
    c = raw["choices"][0]
    return f"finish={c['finish_reason']} content={'null' if c['message'].get('content') is None else 'str'} usage_keys={sorted((raw.get('usage') or {}).keys())}"


@check
async def c_chat() -> tuple[str, str, str]:
    r = await llm.call("smoke", [{"role": "user", "content": "Reply with the single word: pong"}], task="chat", model=settings.model_text_dev, max_tokens=400)
    raw = CAPTURE["client.chat.completions.create"][-1]["response"]
    ok = "pong" in r.content.lower()
    return settings.model_text_dev, "PASS" if ok else "DIFFERS", f"{_chat_shape(raw)} text={r.content[:30]!r} tokens={r.input_tokens}/{r.output_tokens}"


@check
async def c_reasoning_length() -> tuple[str, str, str]:
    """Assumption 7: a tiny max_tokens is consumed by reasoning -> null content + finish_reason=length. Raw call, then the gateway."""
    client = llm._make_client("meta")
    msgs = [{"role": "user", "content": "Reply with the single word: pong"}]
    base = {"model": settings.model_text_dev, "messages": msgs, "reasoning_effort": "low"}
    resp = await client.chat.completions.create(**base, max_tokens=8)
    c = resp.choices[0]
    note = f"raw max_tokens=8: finish={c.finish_reason} content={'null' if c.message.content is None else repr(c.message.content[:20])}"
    meter = llm._Meter(settings.model_text_dev)
    text = await llm._complete(client, {**base, "max_tokens": 120}, meter)  # 120 -> 240 -> 480 via the gateway's retry
    calls = len(CAPTURE["client.chat.completions.create"])
    held = c.finish_reason == "length" and c.message.content is None
    return settings.model_text_dev, "PASS" if held and text.strip() else "DIFFERS", f"{note}; gateway retry text={text[:20]!r} api_calls={calls - 1} out_tokens={meter.output}"


@check
async def c_structured() -> tuple[str, str, str]:
    r = await llm.call(
        "smoke", [{"role": "user", "content": "Animal: a dog. Fill the JSON."}], task="structured",
        model=settings.model_text_dev, schema=Mini, max_tokens=600,
    )
    raw = CAPTURE["client.chat.completions.create"]
    n = len(raw)
    ok = isinstance(r.parsed, Mini) and r.parsed.legs == 4
    return settings.model_text_dev, "PASS" if ok and n == 1 else "DIFFERS", f"response_format json_schema accepted; api_calls={n} (1 = no repair) parsed={r.parsed}"


@check
async def c_tools() -> tuple[str, str, str]:
    tools = select(("get_application",))
    steps: list[str] = []
    r = await llm.run_tools(
        "smoke", "tools",
        [{"role": "user", "content": "Call get_application for vendor V001, then answer with only a JSON object {\"brand\": <brand_name>}."}],
        tools, max_steps=3, model=settings.model_text_dev, max_tokens=800, on_step=lambda s: steps.append(s["tool"]),
    )
    ok = steps == ["get_application"] and "brand" in r.final
    return settings.model_text_dev, "PASS" if ok else "DIFFERS", f"tool steps={steps} final_keys={sorted(r.final)} calls={len(CAPTURE['client.chat.completions.create'])}"


@check
async def c_vision() -> tuple[str, str, str]:
    _path, data = _doc()
    msgs = prompts_docs.extract_messages("licence_certificate", data, 1, "image/jpeg")
    r = await llm.call("smoke", msgs, task="vision", model=settings.model_text_dev, schema=VisionExtraction, max_tokens=3000)
    ext = r.parsed
    assert isinstance(ext, VisionExtraction)
    got = {f.name: f.value for f in ext.fields}
    return settings.model_text_dev, "PASS" if ext.legible and ext.fields else "DIFFERS", f"kind={ext.kind} legible={ext.legible} fields={sorted(got)} bbox_ok={all(0 <= v <= 1 for f in ext.fields for v in f.bbox)}"


@check
async def c_parity() -> tuple[str, str, str]:
    r = await llm.call("smoke", [{"role": "user", "content": "Reply with the single word: pong"}], task="parity", model=settings.model_text, max_tokens=400)
    return settings.model_text, "PASS" if "pong" in r.content.lower() else "DIFFERS", f"text={r.content[:30]!r} tokens={r.input_tokens}/{r.output_tokens} usd={r.cost_usd:.6f}"


@check
async def c_sam() -> tuple[str, str, str]:
    from PIL import Image

    _, data = _doc()
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((160, 160))  # small input -> small recorded fixture
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    small = buf.getvalue()
    text, _spend = await media._sam_text(small, "certificate")
    recs = media.parse_sam_text(text)
    CAPTURE["parsed_text"] = [text]
    if not recs:
        return settings.model_seg, "DIFFERS", f"no record parsed from {len(text)} chars of text"
    rec = recs[0]
    region = media.region_from_record(rec, im.width, im.height)  # mask extent when decodable, else the box token
    head = f"records={len(recs)} box={rec.box} mask={rec.mask_h}x{rec.mask_w} enc={rec.enc} payload_chars={len(rec.payload)} region={region}"
    try:
        bits = media.decode_mask(rec)
        png = media.cutout_png(small, rec)
        return settings.model_seg, "PASS", f"{head} coverage={sum(bits) / len(bits):.1%} cutout_bytes={len(png)}"
    except Exception as exc:  # noqa: BLE001
        return settings.model_seg, "DIFFERS", f"{head}; mask decode unavailable ({str(exc)[:90]}); box fallback used"


@check
async def c_image() -> tuple[str, str, str]:
    data, _spend = await media.generate_image("A plain white ceramic coffee mug on a white background, product photo", size="1024x1024")
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    return settings.model_image, "PASS", f"decoded {im.format} {im.size} bytes={len(data)}; output_format via extra_body accepted"


@check
async def c_asr() -> tuple[str, str, str]:
    t = await media.transcribe(_wav())
    body = CAPTURE["asr"][-1]["body"]
    keys = sorted(body) if isinstance(body, dict) else type(body).__name__
    return settings.model_voice, "PASS", f"HTTP 200 body keys={keys} text={t.text[:60]!r} diff_vs_spoken={media.diff_transcripts('Price is forty five rupees per kilo.', t.text).similarity_pct}%"


@check
async def c_baseten() -> tuple[str, str, str]:
    if not settings.baseten_api_key:
        return settings.baseten_model, "FAIL", "BASETEN_API_KEY not set"
    r = await llm.call(
        "smoke", [{"role": "user", "content": "Animal: a bird. Fill the JSON."}], task="baseten", provider="baseten", schema=Mini, max_tokens=800,
    )
    n = len(CAPTURE["client.chat.completions.create"])
    ok = isinstance(r.parsed, Mini)
    return settings.baseten_model, "PASS" if ok else "DIFFERS", f"parsed={r.parsed} api_calls={n} raw={r.content[:60]!r} tokens={r.input_tokens}/{r.output_tokens}"


# ---------- runner ----------


def _save(name: str, status: str, model: str, note: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"contract": name, "model": model, "status": status, "note": note, "recorded_at": time.strftime("%Y-%m-%d"), "raw": scrub(CAPTURE)}
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help=f"subset of: {', '.join(CHECKS)}")
    args = ap.parse_args()
    names = args.only or list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        sys.exit(f"unknown check(s): {unknown}")
    if not settings.model_api_key:
        sys.exit("MODEL_API_KEY is not set in the environment")
    rows: list[Row] = []
    for name in names:
        CAPTURE.clear()
        before = ledger.total_usd()
        model, status, note = "-", "FAIL", ""
        try:
            model, status, note = await CHECKS[name]()
        except Exception as exc:  # noqa: BLE001 - report, keep going
            note = f"{type(exc).__name__}: {str(exc)[:220]}"
            body = getattr(exc, "body", None) or getattr(exc, "response", None) and getattr(exc.response, "text", None)
            CAPTURE["error"] = [{"type": type(exc).__name__, "status": getattr(exc, "status_code", None), "body": body}]
        note = SECRET.sub("[scrubbed]", note)
        _save(name, status, model, note)
        rows.append(Row(name, model, status, ledger.total_usd() - before, note))
        print(f"  {name}: {status}", flush=True)
    print()
    print(f"{'contract':<17}{'model':<30}{'result':<9}{'cost':>10}  note")
    for r in rows:
        print(f"{r.name:<17}{r.model:<30}{r.status:<9}{'$' + format(r.cost, '.5f'):>10}  {r.note}")
    led = ledger.read()
    print(f"\nledger total: ${led['total_usd']:.5f} over {led['calls']} recorded calls: " + json.dumps(led["by_model"]))


if __name__ == "__main__":
    asyncio.run(main())
