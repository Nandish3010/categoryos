"""Replay the raw provider responses recorded by scripts/contract_smoke.py (fixtures/contract/) through the parsers.
No network. If a fixture is re-recorded and the shape changed, these fail and show which parser to touch."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from app import llm, media
from app.config import settings
from app.media import SegmentationUnusable
from app.schemas import VisionExtraction

DIR = Path(__file__).resolve().parent.parent / "fixtures" / "contract"


def raw(name: str) -> dict:
    return json.loads((DIR / f"{name}.json").read_text())["raw"]


def completions(name: str) -> list[dict]:
    return raw(name)["client.chat.completions.create"]


def chat(entry: dict) -> ChatCompletion:
    return ChatCompletion.model_validate(entry["response"])


class Mini(BaseModel):
    animal: str
    legs: int


# ---------- chat / reasoning tokens (assumption 7) ----------


def test_chat_response_parses_and_reasoning_tokens_are_counted_in_output():
    resp = chat(completions("chat")[0])
    text, finish = llm._text(resp)
    assert text.strip() == "pong" and finish == "stop"
    i, o, _c = llm._usage(resp)
    assert (i, o) == (resp.usage.prompt_tokens, resp.usage.completion_tokens) and o > resp.usage.completion_tokens_details.reasoning_tokens


def test_length_with_null_content_then_retry_with_doubled_tokens():
    entries = completions("reasoning_length")
    first = chat(entries[0])
    assert first.choices[0].finish_reason == "length" and first.choices[0].message.content is None
    assert llm._text(first) == ("", "length")
    done = next(chat(e) for e in entries if e["response"]["choices"][0]["finish_reason"] == "stop")

    class Client:
        def __init__(self):
            self.script, self.calls = [first, done], []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kw):
            self.calls.append(kw)
            return self.script.pop(0)

    client = Client()
    text = asyncio.run(llm._complete(client, {"model": "m", "messages": [], "max_tokens": 100}, llm._Meter(settings.model_text_dev)))
    assert text.strip() and [c["max_tokens"] for c in client.calls] == [100, 200]


# ---------- structured output (assumption 5) ----------


def test_structured_request_schema_is_strict_and_matches_what_the_endpoint_accepted():
    sent = completions("structured")[0]["request_params"]["response_format"]["json_schema"]
    assert sent["strict"] is True
    assert sent["schema"] == llm.strict_schema(Mini.model_json_schema())
    assert sent["schema"]["additionalProperties"] is False and sent["schema"]["required"] == ["animal", "legs"]
    parsed = Mini.model_validate(llm.lenient_json(chat(completions("structured")[0]).choices[0].message.content))
    assert parsed.legs == 4


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_strict_schema_closes_every_object_and_requires_every_property():
    schema = llm.strict_schema(VisionExtraction.model_json_schema())
    objs = list(_objects(schema))
    assert len(objs) >= 2
    for o in objs:
        assert o["additionalProperties"] is False and o["required"] == list(o.get("properties", {}))
    assert "default" not in json.dumps(schema)


def test_rejected_response_format_falls_back_to_a_prompt_instruction(monkeypatch):
    bad = openai.BadRequestError(
        "'additionalProperties' is required to be supplied and to be false.",
        response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        body={"param": "schema"},
    )
    good = chat(completions("structured")[0])

    class Client:
        def __init__(self):
            self.script, self.calls = [bad, good], []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kw):
            self.calls.append(kw)
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    client = Client()
    monkeypatch.setattr(llm, "_make_client", lambda provider: client)
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "model_mode", "live")
    res = asyncio.run(llm.call("smoke", [{"role": "user", "content": "x"}], task="t", schema=Mini))
    assert res.parsed == Mini(animal="dog", legs=4)
    assert "response_format" in client.calls[0] and "response_format" not in client.calls[1]
    assert "JSON schema" in client.calls[1]["messages"][-1]["content"]


# ---------- tool calling ----------


def test_tool_call_response_shape():
    entries = completions("tools")
    msg = chat(entries[0]).choices[0].message
    assert msg.tool_calls and msg.tool_calls[0].function.name == "get_application"
    assert json.loads(msg.tool_calls[0].function.arguments) == {"vendor_id": "V001"}
    assert llm._assistant_tool_message(msg)["tool_calls"][0]["type"] == "function"
    final = llm._text(chat(entries[-1]))[0]
    assert "brand" in llm.lenient_json(final)


# ---------- vision ----------


def test_vision_output_validates_against_the_extraction_schema():
    content = chat(completions("vision")[0]).choices[0].message.content
    ext = VisionExtraction.model_validate(llm.lenient_json(content))
    assert ext.kind == "licence_certificate" and ext.legible and ext.fields
    assert all(0 <= v <= 1 for f in ext.fields for v in f.bbox)


# ---------- Baseten (no structured output: prompted JSON) ----------


def test_baseten_prompted_json_parses():
    content = chat(completions("baseten")[0]).choices[0].message.content
    assert Mini.model_validate(llm.lenient_json(content)).animal == "bird"


# ---------- SAM (assumptions 1-2) ----------


def sam_text() -> str:
    return raw("sam")["parsed_text"][0]


def test_sam_text_parses_box_and_mask_header_and_stops_before_the_closing_delimiter():
    (rec,) = media.parse_sam_text(sam_text())
    assert rec.box == (2.0, 0.0, 113.0, 159.0)  # pixels of the image that was sent (114x160)
    assert (rec.mask_h, rec.mask_w, rec.enc) == (160, 112, "!")
    assert "|" not in rec.payload and not rec.payload.endswith(">")


def test_sam_payload_is_meta_base85_with_a_length_prefix():
    (rec,) = media.parse_sam_text(sam_text())
    body = media.meta_unpack(rec.payload)
    assert int.from_bytes(body[:4], "big") == len(body) - 4


def test_sam_arithmetic_coded_mask_degrades_to_the_box_when_the_vendor_decoder_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "meta_sam_parser", None)  # import fails
    (rec,) = media.parse_sam_text(sam_text())
    with pytest.raises(SegmentationUnusable):
        media.decode_mask(rec)
    region = media.region_from_record(rec, 114, 160)
    assert region == pytest.approx([0.0175, 0.0, 0.9912, 0.9938], abs=1e-3)


def test_sam_request_asks_for_one_bit_masks_and_sends_a_data_url(monkeypatch):
    calls = []
    text = sam_text()

    async def create(**kw):
        calls.append(kw)

        async def events():
            yield SimpleNamespace(type="response.output_text.delta", delta=text)

        return events()

    monkeypatch.setattr(media, "_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    monkeypatch.setattr(settings, "model_api_key", "k")
    got, _ = asyncio.run(media._sam_text(b"\x89PNG....", "certificate"))
    assert got == text
    kw = calls[0]
    assert kw["extra_body"] == {"metadata": {"mask_encoding": "one_bit"}} and kw["stream"] is True
    assert kw["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")


# ---------- ASR (assumption 4) ----------


def test_asr_body_uses_transcript_and_empty_transcript_is_not_an_error():
    body = raw("asr")["asr"][0]["body"]
    assert media._asr_text(body) == "price is 45 rupees per kilo."
    assert media._asr_text({"sessionId": "s", "transcript": "", "audioDurationMs": 2000, "turns": []}) == ""


# ---------- image (assumption 3) ----------


def test_image_request_shape_and_response_field():
    entry = raw("image")["client.images.generate"][0]
    p = entry["request_params"]
    assert p["extra_body"] == {"output_format": "png"} and p["response_format"] == "b64_json" and p["size"] == "1024x1024"
    assert entry["response"]["data"][0]["b64_json"]  # the field generate_image reads (blob truncated in the fixture)

