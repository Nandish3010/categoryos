"""Unit tests for the Negotiate, Catalog and Launch pieces: verifier, gap math, classifier, media with fake live clients."""

import asyncio
import base64
import io
import json
import wave
import zlib
from typing import ClassVar

import pytest
from PIL import Image

from app import ledger, llm, media
from app.agents import catalog, launch, negotiate
from app.agents.context import RunContext, Sequencer
from app.config import settings
from app.data_loader import load_transcript
from app.errors import LlmBadOutput
from app.metrics import apply_levers, build_base
from app.schemas import Commitment, NegotiateFinal, StageResult
from app.verify import numbers_in, verify_all, verify_claim

QUOTE_21 = "If you take the full treats range, I can move to 21 percent."


def final_with(**overrides):
    base = {"term": "margin_pct", "offered": 21, "turn": 4, "transcript_quote": QUOTE_21}
    base.update(overrides)
    return NegotiateFinal(commitments=[Commitment(**base)])


def check(**overrides):
    claim = negotiate.commitment_claims("V002", final_with(**overrides))[0]
    return verify_claim(claim)


# ---------- commitment verification ----------


def test_a_faithful_commitment_is_verified():
    claim = check()
    assert claim.status == "verified" and claim.origin == "model_extraction" and claim.metric == "commit_margin_pct"
    assert claim.value == 0.21 and claim.unit == "pct"


def test_tampered_quote_is_rejected():
    claim = check(transcript_quote="If you take the full treats range, I can move to 23 percent.")
    assert claim.status == "rejected" and "verbatim" in claim.reason
    claim = check(transcript_quote="I can move to 21 percent if you take everything.")
    assert claim.status == "rejected"


def test_wrong_number_is_rejected_even_with_a_genuine_quote():
    claim = check(offered=25)
    assert claim.status == "rejected" and "states 21" in claim.reason and "says 25" in claim.reason


def test_quote_from_the_wrong_turn_or_a_missing_turn_is_rejected():
    assert check(turn=8).status == "rejected"  # the quote is from turn 4
    assert check(turn=99).status == "rejected" and "no turn 99" in check(turn=99).reason


def test_buyer_recap_numbers_do_not_count_for_other_terms():
    # turn 12's quote states 50,000 only; claiming 5,000 or 500 is wrong
    quote = "We can raise that to 50,000 rupees for the launch month, to be used on sponsored listings and sampling."
    ok = check(term="marketing_inr", offered=50000, turn=12, transcript_quote=quote)
    assert ok.status == "verified" and ok.value == 50000
    assert check(term="marketing_inr", offered=5000, turn=12, transcript_quote=quote).status == "rejected"


def test_missing_evidence_and_source_change_are_rejected():
    claim = negotiate.commitment_claims("V002", final_with())[0]
    no_quote = claim.model_copy(update={"evidence": claim.evidence.model_copy(update={"raw_value": ""})})
    assert verify_claim(no_quote).status == "rejected"
    stale = claim.model_copy(update={"evidence": claim.evidence.model_copy(update={"sha256": "0" * 64})})
    assert "source changed" in verify_claim(stale).reason


def test_numbers_in_reads_digits_commas_and_spelled_out_numbers():
    assert numbers_in("Twenty-one is better, 21 or 50,000 or thirty") == [21.0, 21.0, 50000.0, 30.0]
    assert numbers_in("no numbers here") == []


# ---------- gap table math ----------


def test_gap_table_math_and_direction():
    app = {"margin_pct": 17, "payment_days": 15, "moq": 800, "marketing_inr": 20000, "launch_discount_pct": 0, "returns": None}
    required = {"margin_pct": 35.0, "payment_days": 21.0, "moq": 272.0, "marketing_inr": 22000.0, "launch_discount_pct": 5.0, "returns": 7.0}

    def commit(offered, turn=1):
        return {"offered": offered, "turn": turn, "transcript_quote": "q", "claim_id": "c", "status": "verified"}

    table = {r["term"]: r for r in negotiate.gap_table(app, required, {
        "margin_pct": commit(21), "payment_days": commit(30), "moq": commit(250), "marketing_inr": commit(50000),
        "launch_discount_pct": commit(5),
    })}
    assert table["margin_pct"]["gap"] == -14 and table["margin_pct"]["status"] == "gap"
    assert table["payment_days"]["gap"] == 9 and table["payment_days"]["status"] == "met"
    assert table["moq"]["gap"] == -22 and table["moq"]["status"] == "met"  # lower is better: 250 <= 272
    assert negotiate.gap_table(app, required, {"moq": commit(500)})[2]["status"] == "gap"
    assert table["marketing_inr"]["gap"] == 28000 and table["launch_discount_pct"]["gap"] == 0
    assert table["returns"]["status"] == "not_stated" and table["returns"]["gap"] is None and table["returns"]["offered"] is None


def test_required_terms_come_from_the_engine():
    lever = apply_levers(build_base("V002"))
    negotiable = [s for s in lever.skus if s.verdict == "negotiate"]
    short = [s for s in lever.skus if s.verdict in {"list", "negotiate"}]
    req = negotiate.required_terms(lever, negotiable, short)
    assert req["category"] == "treats" and req["margin_pct"] == 35 and req["margin_min_pct"] == 28 and req["payment_days"] == 21
    assert req["moq"] == int(2.0 * sum(s.est_monthly_units for s in short))
    assert req["marketing_inr"] == round(0.10 * sum(s.alloc_units * s.selling_price for s in short))


def test_rejected_commitments_do_not_enter_the_gap_table(monkeypatch):
    """If the model quotes a number the vendor never said, the term falls back to 'not_stated'."""
    real = llm.run_tools

    async def lying(*args, **kwargs):
        res = await real(*args, **kwargs)
        for c in getattr(res.parsed, "commitments", []):
            if c.term == "margin_pct":
                c.offered = 30
        return res

    monkeypatch.setattr(llm, "run_tools", lying)
    research = _research("V002")
    ctx = RunContext("run_t", "V002", "2026-10-27", Sequencer())
    result = asyncio.run(negotiate.run(ctx, research))
    row = next(r for r in result.data["gap_table"] if r["term"] == "margin_pct")
    assert row["status"] == "not_stated" and row["offered"] is None
    assert result.data["verification"]["rejected"] == 1 and "failed verification" in result.summary
    rejected = [c for c in result.claims if c.status == "rejected"]
    assert len(rejected) == 1 and rejected[0].metric == "commit_margin_pct"


def _research(vendor_id):
    lever = apply_levers(build_base(vendor_id))
    return StageResult(
        stage="research", status="done",
        data={"lever": {"target_margin_pct_offset": 0, "moq": lever.summary.moq}, "rationale_per_sku": []},
        metrics_hash=lever.metrics_hash, narrative_hash=lever.metrics_hash,
    )


# ---------- PO ----------


def test_po_totals_are_recomputed_and_a_tampered_total_is_rejected():
    lever = apply_levers(build_base("V001"))
    skus = [s for s in lever.skus if s.verdict in {"list", "negotiate"}]
    terms = launch.effective_terms("V001", None)
    po, claims = launch.build_po("V001", 0, lever.summary.moq, skus, terms, "2026-10-27")
    assert sum(line["units"] for line in po["lines"]) == lever.summary.moq == 150
    assert po["lines"][0]["line_total"] == round(po["lines"][0]["units"] * po["lines"][0]["unit_cost"], 2)
    assert all(c.status == "verified" for c in verify_all(claims).claims)
    bad = [claims[0].model_copy(update={"value": claims[0].value + 1000}), claims[1]]
    out = verify_all(bad).claims
    assert out[0].status == "rejected" and "recomputed" in out[0].reason and out[1].status == "verified"


# ---------- classifier ----------


def _drive(coro):
    return asyncio.run(coro)


def _ctx(vendor="V001"):
    return RunContext("run_t", vendor, "2026-10-27", Sequencer())


def _skus(vendor="V001"):
    lever = apply_levers(build_base(vendor))
    return [s for s in lever.skus if s.verdict in {"list", "negotiate"}]


def test_classifier_agreement_and_disagreement_keep_the_taxonomy():
    out = _drive(catalog.classify(_ctx(), "V001", _skus()))
    assert out["HP-D01"]["agreement"] is True and out["HP-D01"]["note"] is None
    assert out["HP-W03"]["agreement"] is False and out["HP-W03"]["final"]["subcategory"] == "gravy"
    assert out["HP-W03"]["model"]["valid"] is True


def test_invalid_model_label_is_flagged_and_ignored(monkeypatch):
    real = llm.call

    async def bad_label(stage, messages, **kw):
        res = await real(stage, messages, **kw)
        res.parsed.classifications[0].subcategory = "gourmet"
        return res

    monkeypatch.setattr(llm, "call", bad_label)
    out = _drive(catalog.classify(_ctx(), "V001", _skus()))
    first = out["HP-D01"]
    assert first["model"]["valid"] is False and first["agreement"] is False and first["final"]["subcategory"] == "adult"


def test_baseten_parse_failure_means_classified_by_rules(monkeypatch):
    real = llm.call

    async def flaky(stage, messages, **kw):
        if kw.get("provider") == "baseten":
            raise LlmBadOutput(cause="not json")
        return await real(stage, messages, **kw)

    monkeypatch.setattr(llm, "call", flaky)
    ctx = _ctx()
    out = _drive(catalog.classify(ctx, "V001", _skus()))
    assert all(c["model"] is None and c["note"] == "Classified by rules" and c["agreement"] is None for c in out.values())
    research = _research("V001")
    result = _drive(catalog.run(_ctx(), research))
    assert result.data["classifier_agreement_pct"] is None and "classified by rules" in result.summary
    assert all(s["classification"]["note"] == "Classified by rules" for s in result.data["skus"])


def test_copy_failure_falls_back_to_rule_based_copy(monkeypatch):
    real = llm.call

    async def no_copy(stage, messages, **kw):
        if kw.get("task", "").startswith("catalog_copy"):
            raise LlmBadOutput(cause="not json")
        return await real(stage, messages, **kw)

    monkeypatch.setattr(llm, "call", no_copy)
    result = _drive(catalog.run(_ctx("V002"), _research("V002")))
    assert all(s["copy"]["generated_by"] == "rules" and len(s["copy"]["title"]) <= 80 and len(s["copy"]["bullets"]) >= 3 for s in result.data["skus"])


def test_wrong_model_mrp_is_corrected_from_the_sheet(monkeypatch):
    real = llm.call

    async def wrong_mrp(stage, messages, **kw):
        res = await real(stage, messages, **kw)
        if kw.get("task", "").startswith("catalog_copy"):
            res.parsed.items[0].attributes["mrp"] = 1949  # sheet says 1499
        return res

    monkeypatch.setattr(llm, "call", wrong_mrp)
    result = _drive(catalog.run(_ctx(), _research("V001")))
    first = result.data["skus"][0]
    assert first["code"] == "HP-D01" and first["corrections"][0]["claimed"] == 1949 and first["corrections"][0]["sheet"] == 1499
    assert first["copy"]["attributes"]["mrp"] == 1499
    assert next(c for c in result.claims if c.id == "V001:HP-D01:mrp:catalog").status == "rejected"


def test_compliance_linter_catches_medical_claims_and_superlatives():
    sku = _skus("V001")[0]
    copy = {"title": "The best dog food, guaranteed", "bullets": ["Cures arthritis", "Heals dermatitis fast", "Tasty"], "description": "", "compliance_flags": []}
    flags = catalog.compliance_flags(sku, copy, None)
    rules = {f["rule"] for f in flags}
    assert {"medical_claim", "unverifiable_superlative", "missing_label_info"} <= rules
    assert any(f["rule"] == "missing_label_info" and "FSSAI" in f["text"] and f["severity"] == "high" for f in flags)


# ---------- media with fake live clients ----------


def png(size=(64, 64), color=(200, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeImages:
    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        data = type("D", (), {"b64_json": base64.b64encode(png()).decode()})()
        return type("R", (), {"data": [data]})()


class FakeStream:
    def __init__(self, text):
        self.text = text

    def __aiter__(self):
        async def gen():
            yield type("E", (), {"type": "response.created", "delta": ""})()
            half = len(self.text) // 2
            for part in (self.text[:half], self.text[half:]):
                yield type("E", (), {"type": "response.output_text.delta", "delta": part})()

        return gen()


class FakeResponses:
    def __init__(self, text):
        self.text, self.calls = text, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.text)


class FakeClient:
    def __init__(self, sam_text=""):
        self.images, self.responses = FakeImages(), FakeResponses(sam_text)


def sam_text(h=8, w=8, enc="!", box=True, lo=2, hi=6):
    rows = []
    for y in range(h):
        rows.append([1 if lo <= y < hi and lo <= x < hi else 0 for x in range(w)])
    flat = [v for r in rows for v in r]
    if enc == "!":
        packed = bytes(sum(bit << (7 - i) for i, bit in enumerate(flat[k:k + 8])) for k in range(0, len(flat), 8))
    else:
        packed = zlib.compress(bytes(flat))
    payload = base64.b85encode(packed).decode()
    head = f"<0f>1 x1={lo} y1={lo} x2={hi} y2={hi} w={w} h={h} " if box else "<0f>1 "
    return head + f"x=0 y=0 data={h},{w},{enc}{payload}"


def box_sam_text(enc="!", x1=16, y1=16, x2=47, y2=47):
    """Live shape: the mask raster covers the (inclusive) box only. Ones, with a hole so coverage stays under the cut-off."""
    w, h = x2 - x1 + 1, y2 - y1 + 1
    flat = [0 if w // 4 <= x < 3 * w // 4 and h // 4 <= y < 3 * h // 4 else 1 for y in range(h) for x in range(w)]
    if enc == "!":
        packed = bytes(sum(bit << (7 - i) for i, bit in enumerate(flat[k:k + 8])) for k in range(0, len(flat), 8))
    else:
        packed = zlib.compress(bytes(flat))
    return f"<0f>1 <|box;x1={x1};y1={y1};x2={x2};y2={y2};w=64;h=64|><|mask;x=0;y=0;data={h},{w},{enc}{base64.b85encode(packed).decode()}|>"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", "test-key")
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "live_stages", "catalog,marketing")
    fake = FakeClient(sam_text())
    monkeypatch.setattr(llm, "_make_client", lambda provider: fake)
    return fake


def spent(model):
    return ledger.read()["by_model"].get(model, {"calls": 0, "usd": 0.0})


def test_image_request_shape_and_ledger(live):
    data, spend = _drive(media.generate_image("a packshot", size="1024x1024"))
    call = live.images.calls[0]
    assert call["model"] == "muse-image-1.0" and call["prompt"] == "a packshot" and call["n"] == 1
    assert call["response_format"] == "b64_json" and call["extra_body"] == {"output_format": "png"}
    assert data[:4] == b"\x89PNG" and spend.cost_usd == 0.01
    assert spent("muse-image-1.0") == {"calls": 1, "usd": 0.01}


@pytest.mark.parametrize("enc", ["!", "~"])
def test_sam_request_shape_cutout_and_ledger(live, enc):
    live.responses.text = box_sam_text(enc=enc)
    cut, spend = _drive(media.segment(png(), "bag of dog food"))
    call = live.responses.calls[0]
    assert call["model"] == "sam-3.1" and call["stream"] is True
    parts = call["input"][0]["content"]
    assert call["input"][0]["role"] == "user" and parts[0] == {"type": "input_text", "text": "bag of dog food"}
    assert parts[1]["type"] == "input_image" and parts[1]["image_url"].startswith("data:image/png;base64,")
    img = Image.open(io.BytesIO(cut))
    assert img.mode == "RGBA" and img.size == (32, 32)  # the 32x32 box-sized mask placed at the box corner, cropped to its extent
    assert img.getpixel((0, 0))[3] == 255 and img.getpixel((16, 16))[3] == 0
    assert spend.cost_usd == pytest.approx(0.0025) and spent("sam-3.1")["usd"] == pytest.approx(0.0025)


def test_sam_parse_reads_height_first_and_fields_by_key():
    rec = media.parse_sam_text(sam_text(h=8, w=8, enc="!"))[0]
    assert (rec.mask_h, rec.mask_w, rec.enc, rec.box) == (8, 8, "!", (2.0, 2.0, 6.0, 6.0))
    wide = media.parse_sam_text(sam_text(h=4, w=16, enc="!", lo=1, hi=3))[0]
    assert (wide.mask_h, wide.mask_w) == (4, 16) and sum(media.decode_mask(wide)) == 4
    assert media.parse_sam_text(sam_text(box=False))[0].box is None


@pytest.mark.parametrize("text", ["no matches here", "<0f>1 x=0 y=0 data=8,8,!!!!notbase85!!!!", sam_text(lo=0, hi=0)])
def test_unusable_sam_output_raises(live, text):
    live.responses.text = text
    with pytest.raises(media.SegmentationUnusable):
        _drive(media.segment(png(), "x"))


def _sku(code="HP-D01"):
    return next(s for s in _skus() if s.code == code)


def test_live_images_cache_and_sam_fallback_path(live, monkeypatch):
    ctx = _ctx()
    out = _drive(catalog._images(ctx, "V001", _sku(), "Highland Paws", "Title", True, True))
    assert out["image_source"] == "live" and out["sources"] == {"packshot": "live", "cutout": "live", "lifestyle": "live"}
    assert out["cutout"].endswith("HP-D01-cutout.png") and len(live.images.calls) == 2
    assert live.images.calls[1]["size"] == "1792x1024"
    assert spent("muse-image-1.0")["usd"] == pytest.approx(0.02) and spent("sam-3.1")["calls"] == 1
    assert media.cached_source("V001", "HP-D01-packshot.png") == "live"
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait())
    assert sum(e.cost_usd for e in events) == pytest.approx(0.0225)
    # second run: everything is cached, nothing is spent
    _drive(catalog._images(_ctx(), "V001", _sku(), "Highland Paws", "Title", True, True))
    assert len(live.images.calls) == 2 and spent("sam-3.1")["calls"] == 1
    # SAM unusable for another SKU: cutout is "unavailable", the packshot stays
    live.responses.text = "nothing"
    out = _drive(catalog._images(_ctx(), "V001", _sku("HP-D02"), "Highland Paws", "Title", False, True))
    assert out["cutout"] == "unavailable" and out["cutout_note"] == "cutout unavailable" and out["lifestyle"] is None
    assert out["packshot"].endswith("HP-D02-packshot.png") and any("segmentation_unusable" in e for e in out["errors"])


def test_live_image_failure_degrades_to_a_placeholder(live, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(live.images, "generate", boom)
    out = _drive(catalog._images(_ctx(), "V001", _sku(), "Highland Paws", "Title", False, True))
    assert out["image_source"] == "placeholder" and out["cutout"] == "unavailable"
    assert media.cached_source("V001", "HP-D01-packshot.png") == "placeholder"


def wav_bytes(seconds=36, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"\x00\x00" * rate * seconds)
    return buf.getvalue()


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeHttp:
    posts: ClassVar[list] = []

    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        FakeHttp.posts.append((url, kwargs))
        return FakeResp(self.status, self.body)


def test_transcription_request_shape_and_ledger(live, monkeypatch):
    FakeHttp.posts = []
    monkeypatch.setattr(media, "_http", lambda: FakeHttp({"text": "hello there"}))
    result = _drive(media.transcribe(wav_bytes(36)))
    url, kw = FakeHttp.posts[0]
    assert url == "https://api.meta.ai/v1/asr/transcribe"
    assert kw["headers"]["Authorization"] == "Bearer test-key"
    req_name, req_body, req_type = kw["files"]["request"]
    assert req_name is None and req_type == "application/json"
    assert json.loads(req_body) == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    audio_name, audio, audio_type = kw["files"]["audio"]
    assert audio_name == "call.wav" and audio[:4] == b"RIFF" and audio_type == "audio/wav"
    assert result.text == "hello there" and result.hours == pytest.approx(0.01)
    assert spent("muse-voice-transcribe-1.0")["usd"] == pytest.approx(0.0018)


def test_negotiate_layers_asr_on_the_canonical_transcript(live, monkeypatch, tmp_path):
    FakeHttp.posts = []
    canonical = " ".join(t["text"] for t in load_transcript("V002"))
    body = {"text": canonical.replace("500 units", "five hundred units").replace("Priya", "Pria")}
    wav = tmp_path / "call.wav"
    wav.write_bytes(wav_bytes(30))
    monkeypatch.setattr(negotiate, "wav_path", lambda vendor: wav)
    monkeypatch.setattr(settings, "live_stages", "negotiate")
    monkeypatch.setattr(media, "_http", lambda: FakeHttp(body))
    ctx = _ctx("V002")
    asr = _drive(negotiate._asr(ctx, "V002", canonical))
    assert 95 < asr["similarity_pct"] < 100 and asr["changes"] and asr["audio_hours"] > 0
    assert spent("muse-voice-transcribe-1.0")["calls"] == 1
    assert media.diff_transcripts("a b c d", "a b c d").similarity_pct == 100.0
    # no wav, or the voice stage not live: nothing is called
    monkeypatch.setattr(negotiate, "wav_path", lambda vendor: tmp_path / "missing.wav")
    assert _drive(negotiate._asr(ctx, "V002", canonical)) is None
    assert len(FakeHttp.posts) == 1


def test_asr_failure_degrades_without_blocking(live, monkeypatch, tmp_path):
    wav = tmp_path / "call.wav"
    wav.write_bytes(wav_bytes(5))
    monkeypatch.setattr(negotiate, "wav_path", lambda vendor: wav)
    monkeypatch.setattr(settings, "live_stages", "negotiate")

    monkeypatch.setattr(media, "_http", lambda: FakeHttp({}, 402))
    ctx = _ctx("V002")
    assert _drive(negotiate._asr(ctx, "V002", "x")) is None
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait())
    assert events[0].type == "degraded" and "credits_unavailable" in events[0].payload["reason"]


# ---------- placeholders ----------


def test_placeholders_are_small_deterministic_and_labelled():
    for kind in ("packshot", "cutout", "lifestyle", "campaign"):
        a = media.placeholder_png(kind, "Alpine Chicken & Sweet Potato Adult", "1.5kg")
        assert a == media.placeholder_png(kind, "Alpine Chicken & Sweet Potato Adult", "1.5kg")
        assert len(a) < 30_000
        assert Image.open(io.BytesIO(a)).mode == ("RGBA" if kind == "cutout" else "RGB")
    cut = Image.open(io.BytesIO(media.placeholder_png("cutout", "x")))
    assert cut.getpixel((0, 0))[3] == 0  # transparent outside the card


def test_resolve_asset_rejects_unsafe_names():
    assert media.resolve_asset("V001", "HP-D01-packshot.png") is not None
    assert media.resolve_asset("V001", "campaign.png") is not None
    for name in ("../x.png", "..", "a/b.png", "HP-D01-packshot.png/", ".png", "x.txt", "manifest.json", "HP-D01-bogus.png"):
        assert media.resolve_asset("V001", name) is None, name
    assert media.resolve_asset("V009", "HP-D01-packshot.png") is None
