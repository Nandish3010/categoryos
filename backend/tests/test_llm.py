import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from app import ledger, llm
from app.config import settings
from app.errors import (
    CreditsUnavailable,
    FixtureMissing,
    LlmBadOutput,
    LlmUnavailable,
    MissingKey,
    SpendCapExceeded,
)


class Out(BaseModel):
    vendor: str
    sku_count: int


MSGS = [{"role": "user", "content": "hi"}]


def run(coro):
    return asyncio.run(coro)


def call(stage="intake", task="extract_demo", **kw):
    return run(llm.call(stage, MSGS, task=task, **kw))


# ---------- fake provider ----------


def resp(content, finish="stop", prompt=100, completion=50, refusal=None):
    msg = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, prompt_tokens_details=None),
    )


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def api_error(cls, status):
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "model_api_key", "test-not-a-real-key")

    def install(script, provider_seen=None):
        client = FakeClient(script)

        def make(provider):
            if provider_seen is not None:
                provider_seen.append(provider)
            return client

        monkeypatch.setattr(llm, "_make_client", make)
        return client

    return install


GOOD = json.dumps({"vendor": "V001", "sku_count": 3})


# ---------- mock / replay ----------


def test_mock_loads_repo_fixture():
    r = call(schema=Out)
    assert r.mode == "mock" and not r.degraded and r.cost_usd == 0
    assert r.parsed == Out(vendor="V001", sku_count=3)


def test_mock_fixture_missing_has_fix_text():
    with pytest.raises(FixtureMissing) as exc:
        call(task="does_not_exist")
    err = exc.value
    assert err.code == "fixture_missing"
    assert "make record" in err.fix and "fixtures" in err.fix
    assert "does_not_exist" in err.cause


def test_replay_prefers_golden(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_mode", "replay")
    monkeypatch.setattr(settings, "fixtures_dir", tmp_path)
    g = tmp_path / "golden" / "intake"
    g.mkdir(parents=True)
    (g / "t.json").write_text(json.dumps({"content": GOOD, "model": "muse-spark-1.3"}))
    r = call(task="t", schema=Out)
    assert r.mode == "replay" and not r.degraded and r.model == "muse-spark-1.3"


def test_replay_falls_back_to_mock_degraded(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    r = call(schema=Out)  # no golden for this task in the repo
    assert r.mode == "replay" and r.degraded and r.parsed.sku_count == 3


def test_replay_checksum_mismatch_degrades(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_mode", "replay")
    monkeypatch.setattr(settings, "fixtures_dir", tmp_path)
    for kind in ("golden", "mock"):
        d = tmp_path / kind / "intake"
        d.mkdir(parents=True)
    (tmp_path / "golden/intake/t.json").write_text(json.dumps({"content": GOOD, "checksum": "bad"}))
    (tmp_path / "mock/intake/t.json").write_text(json.dumps({"content": GOOD}))
    assert call(task="t").degraded


# ---------- live ----------


def test_live_success_records_cost_and_sends_schema(live):
    client = live([resp(GOOD, prompt=1_000_000, completion=1_000_000)])
    r = call(schema=Out, effort="medium", max_tokens=900)
    assert r.mode == "live" and r.parsed == Out(vendor="V001", sku_count=3)
    assert r.cost_usd == pytest.approx(1.25 + 4.25)
    assert ledger.total_usd() == pytest.approx(5.5)
    kw = client.calls[0]
    assert kw["reasoning_effort"] == "medium" and kw["max_tokens"] == 900
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["model"] == settings.model_text


def test_live_length_then_retry_doubles_max_tokens(live):
    client = live([resp(None, finish="length"), resp(GOOD)])
    r = call(schema=Out, max_tokens=500)
    assert r.parsed.vendor == "V001"
    assert [c["max_tokens"] for c in client.calls] == [500, 1000]


def test_live_lenient_parse_strips_fences_and_prose(live):
    live([resp(f"Sure!\n```json\n{GOOD}\n```\nHope that helps")])
    assert call(schema=Out).parsed.sku_count == 3


def test_live_repair_prompt_then_success(live):
    client = live([resp("not json at all"), resp(GOOD)])
    r = call(schema=Out)
    assert r.parsed.sku_count == 3 and len(client.calls) == 2
    assert "corrected JSON" in client.calls[1]["messages"][-1]["content"]


def test_live_bad_output_after_repair(live):
    live([resp("nope"), resp("still nope")])
    with pytest.raises(LlmBadOutput):
        call(schema=Out)


def test_live_empty_retry_once_then_bad_output(live):
    client = live([resp(""), resp("", refusal="no")])
    with pytest.raises(LlmBadOutput):
        call()
    assert len(client.calls) == 2


def test_live_429_retries_twice_then_unavailable(live):
    client = live([api_error(openai.RateLimitError, 429)] * 3)
    with pytest.raises(LlmUnavailable):
        call()
    assert len(client.calls) == 3


def test_live_429_then_success(live):
    client = live([api_error(openai.RateLimitError, 429), resp(GOOD)])
    assert call(schema=Out).parsed.sku_count == 3
    assert len(client.calls) == 2


def test_live_timeout_then_unavailable(live):
    live([openai.APITimeoutError(httpx.Request("POST", "https://example.invalid"))] * 3)
    with pytest.raises(LlmUnavailable):
        call()


def test_live_402_maps_to_credits_unavailable(live):
    client = live([api_error(openai.APIStatusError, 402)])
    with pytest.raises(CreditsUnavailable):
        call()
    assert len(client.calls) == 1


def test_spend_cap_refuses_before_calling(live, monkeypatch):
    client = live([resp(GOOD)])
    monkeypatch.setattr(settings, "max_spend_usd", 1.0)
    ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})  # $1.25
    with pytest.raises(SpendCapExceeded) as exc:
        call()
    assert exc.value.status == 429 and client.calls == []


def test_warn_threshold_logs(live, monkeypatch, caplog):
    live([resp(GOOD)])
    monkeypatch.setattr(settings, "warn_spend_usd", 1.0)
    ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})
    with caplog.at_level(logging.WARNING, logger="categoryos.ledger"):
        call()
    assert "warning threshold" in caplog.text


def test_one_json_log_line_per_call(live, caplog):
    live([resp(GOOD)])
    with caplog.at_level(logging.INFO, logger="categoryos.llm"):
        call(schema=Out)
    lines = [json.loads(r.message) for r in caplog.records if r.name == "categoryos.llm"]
    assert len(lines) == 1
    assert {"stage", "task", "model", "provider", "mode", "usd", "latency_ms", "degraded"} <= lines[0].keys()


def test_live_stages_routing(live, monkeypatch):
    client = live([resp(GOOD)])
    monkeypatch.setattr(settings, "live_stages", "decide, negotiate")
    assert call(stage="intake").mode == "mock"  # not listed: mock
    assert client.calls == []
    assert llm.resolve_mode("negotiate") == "live"


def test_live_without_key_for_provider_raises_missing_key(live):
    live([])
    with pytest.raises(MissingKey):
        call(provider="baseten")  # only MODEL_API_KEY is set


def test_meta_key_removed_raises_missing_key(live, monkeypatch):
    live([])
    monkeypatch.setattr(llm, "_api_key", lambda provider: None)
    with pytest.raises(MissingKey):
        call()


def test_no_key_at_all_degrades_to_mock(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "live")
    assert call().mode == "mock"


def test_baseten_prompts_for_json_and_costs_zero(live):
    seen: list[str] = []
    client = live([resp(GOOD, prompt=5000, completion=5000)], provider_seen=seen)
    settings.baseten_api_key = "test-not-a-real-key"
    r = call(schema=Out, provider="baseten")
    kw = client.calls[0]
    assert seen == ["baseten"] and "response_format" not in kw and "reasoning_effort" not in kw
    assert "JSON schema" in kw["messages"][-1]["content"]
    assert r.cost_usd == 0 and r.model == settings.baseten_model


def test_record_writes_golden(live, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "fixtures_dir", tmp_path)
    monkeypatch.setattr(settings, "record", True)
    live([resp(GOOD)])
    call(task="rec", schema=Out)
    saved = json.loads((tmp_path / "golden/intake/rec.json").read_text())
    assert saved["content"] == GOOD and saved["schema_version"] == 1 and saved["checksum"]


def test_ledger_prices_and_atomic_file():
    assert ledger.price("muse-image-1.0", {"images": 3}) == pytest.approx(0.03)
    assert ledger.price("sam-3.1", {"images": 1000}) == pytest.approx(2.5)
    assert ledger.price("muse-voice-transcribe-1.0", {"hours": 2}) == pytest.approx(0.36)
    assert ledger.price("muse-spark-1.3-contributor", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(0.30)
    ledger.record("muse-wonder-1.0", {"input_tokens": 1_000_000})
    data = ledger.read()
    assert data["total_usd"] == pytest.approx(4.0) and data["calls"] == 1
    assert not settings.ledger_path.with_suffix(".json.tmp").exists()


def test_lenient_json_edge_cases():
    assert llm.lenient_json('prefix {"a": {"b": "}"}} suffix') == {"a": {"b": "}"}}
    with pytest.raises(ValueError):
        llm.lenient_json("nothing here")
