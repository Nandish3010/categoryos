"""Public live budget (PUBLIC_LIVE_*): disabled by default, per-IP and shared budgets, the global ledger cap, the BYO and
copilot paths on a replay deploy (fakes only, no network), plus replay provenance (meta.source) and the no-secret-in-the-
browser guarantee."""

import io
import re
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    ledger,
    llm,
    media,
    public_live,
    registry,
    replay,
    sandbox,
    sandbox_budget,
    scope,
)
from app.config import settings
from app.data_loader import load_transcript
from app.errors import PublicBudgetExhausted
from app.main import app
from app.schemas import TurnExtraction

IP = sandbox.ip_key("testclient")  # what TestClient's address hashes to


@pytest.fixture(autouse=True)
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "state_dir", tmp_path / "state")
    monkeypatch.setattr(settings, "upload_rate_per_hour", 1000)
    monkeypatch.setattr(settings, "public_live_budget_usd", 0.0)
    monkeypatch.setattr(settings, "public_live_per_ip_usd", 0.50)
    monkeypatch.setattr(settings, "public_live_features", "")
    sandbox.reset_rate_limits()
    yield
    sandbox.reset_rate_limits()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def enable(monkeypatch, features="byo,copilot", budget=5.0, per_ip=0.5, mode="replay"):
    monkeypatch.setattr(settings, "model_mode", mode)
    monkeypatch.setattr(settings, "model_api_key", "test-key")
    monkeypatch.setattr(settings, "public_live_budget_usd", budget)
    monkeypatch.setattr(settings, "public_live_per_ip_usd", per_ip)
    monkeypatch.setattr(settings, "public_live_features", features)


# ---------- config and accounting ----------


def test_disabled_by_default(monkeypatch):
    from app.config import Settings

    fresh = Settings(_env_file=None)
    assert fresh.public_live_budget_usd == 0 and fresh.public_live_per_ip_usd == 0.50 and fresh.public_live_features == ""
    monkeypatch.setattr(settings, "model_mode", "replay")
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "public_live_features", "byo,copilot")  # features alone are not enough
    assert not public_live.enabled("byo") and not public_live.enabled("copilot")
    assert public_live.status()["enabled"] is False and public_live.status()["remaining_usd"] == 0


def test_needs_a_model_key_and_a_non_mock_mode(monkeypatch):
    enable(monkeypatch)
    assert public_live.enabled("byo")
    monkeypatch.setattr(settings, "model_api_key", None)
    assert not public_live.enabled("byo")
    enable(monkeypatch, mode="mock")
    assert not public_live.enabled("byo")


def test_unknown_features_are_ignored(monkeypatch):
    enable(monkeypatch, features=" Byo , nonsense, runs ")
    assert public_live.features() == {"byo"}
    assert public_live.enabled("byo") and not public_live.enabled("copilot")


def test_per_ip_share_is_enforced_and_independent(monkeypatch):
    enable(monkeypatch, per_ip=0.5)
    public_live.charge("a", 0.4)
    public_live.check("a")
    public_live.charge("a", 0.2)
    with pytest.raises(PublicBudgetExhausted) as exc:
        public_live.check("a")
    assert "share" in exc.value.cause
    public_live.check("b")  # another address is unaffected
    assert public_live.available("copilot", "b") and not public_live.available("copilot", "a")
    assert public_live.status("a")["exhausted"] is True and public_live.status("b")["exhausted"] is False


def test_shared_budget_exhaustion_blocks_everyone(monkeypatch):
    enable(monkeypatch, budget=1.0, per_ip=0.9)
    public_live.charge("a", 0.9)
    public_live.charge("b", 0.2)
    with pytest.raises(PublicBudgetExhausted) as exc:
        public_live.check("c")
    assert "shared" in exc.value.cause
    st = public_live.status("c")
    assert st["remaining_usd"] == 0 and st["exhausted"] is True


def test_global_ledger_cap_wins_over_public_budget(monkeypatch):
    enable(monkeypatch, budget=50.0, per_ip=50.0)
    monkeypatch.setattr(settings, "max_spend_usd", 1.0)
    ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})  # $1.25 of spend
    with pytest.raises(PublicBudgetExhausted) as exc:
        public_live.check("a")
    assert "MAX_SPEND_USD" in exc.value.cause
    assert public_live.status("a")["remaining_usd"] == 0
    with scope.use(scope.Scope("U-aaaaaaaa", "pet", "live", "a", public=True)), pytest.raises(PublicBudgetExhausted):
        ledger.check_budget()
    # and the ledger's own cap still fires for a plain caller
    with pytest.raises(Exception, match="spend cap"):
        ledger.check_budget()


def test_ledger_charges_the_public_budget_not_the_sandbox_bucket(monkeypatch):
    enable(monkeypatch)
    with scope.use(scope.Scope("U-aaaaaaaa", "pet", "live", "ipk", public=True)):
        cost = ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})
    assert cost > 0 and abs(public_live.spent_ip("ipk") - cost) < 1e-6 and abs(public_live.spent_total() - cost) < 1e-6
    assert sandbox_budget.spent("ipk") == 0
    with public_live.use(public_live.PublicCtx("copilot", "ipk2")):
        c2 = ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})
    assert abs(public_live.spent_ip("ipk2") - c2) < 1e-6
    ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})  # keyed / replay callers are not metered
    assert abs(public_live.spent_total() - cost - c2) < 1e-6


def test_per_ip_share_resets_on_a_new_day(monkeypatch):
    enable(monkeypatch)
    public_live.charge("a", 0.5)
    monkeypatch.setattr(public_live, "_today", lambda: "2099-01-01")
    assert public_live.remaining_ip("a") == 0.5  # new UTC day
    assert public_live.spent_total() == 0.5  # the shared budget is not daily


# ---------- bring your own vendor on a replay deploy ----------


def sample(client, headers=None):
    res = client.post("/api/uploads", data={"sample": "beauty"}, headers=headers or {})
    assert res.status_code == 201, res.text
    return res.json()


def test_byo_stays_rules_only_when_public_live_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "public_live_features", "byo")  # budget 0
    assert sample(client)["llm_mode"] == "rules_only"
    opts = client.get("/api/uploads/options").json()
    assert opts["public_live"]["enabled"] is False


def test_byo_goes_live_on_a_replay_deploy_within_budget(client, monkeypatch):
    enable(monkeypatch, features="byo")
    vendor = sample(client)
    assert vendor["llm_mode"] == "live"
    meta = registry.read_meta(vendor["id"])
    assert meta["public_live"] is True and meta["ip_key"] == IP
    assert registry.scope_for(vendor["id"]).public is True
    opts = client.get("/api/uploads/options").json()["public_live"]
    assert opts["enabled"] and opts["ip_remaining_usd"] == 0.5 and opts["per_ip_usd"] == 0.5


def test_byo_copilot_only_config_does_not_make_byo_live(client, monkeypatch):
    enable(monkeypatch, features="copilot")
    assert sample(client)["llm_mode"] == "rules_only"


def test_byo_falls_back_to_rules_only_when_ip_budget_is_spent(client, monkeypatch):
    enable(monkeypatch, features="byo")
    public_live.charge(IP, 0.5)
    vendor = sample(client)
    assert vendor["llm_mode"] == "rules_only"
    st = client.get("/api/uploads/options").json()
    assert st["llm_mode"] == "rules_only" and st["public_live"]["exhausted"] is True


def test_byo_run_start_demotes_when_budget_ran_out_after_upload(client, monkeypatch):
    enable(monkeypatch, features="byo")
    vid = sample(client)["id"]
    public_live.charge("someone-else", 5.0)  # the shared budget is gone
    res = client.post(f"/api/vendors/{vid}/runs")
    assert res.status_code == 202  # never an error: the run is free and rules-only
    assert registry.read_meta(vid)["llm_mode"] == "rules_only"
    assert registry.read_meta(vid)["public_live"] is False


def test_demo_key_still_beats_an_exhausted_public_budget(client, monkeypatch):
    enable(monkeypatch, features="byo")
    monkeypatch.setattr(settings, "demo_key", "secret")
    public_live.charge(IP, 0.5)
    vendor = sample(client, headers={"X-Demo-Key": "secret"})
    assert vendor["llm_mode"] == "live"
    meta = registry.read_meta(vendor["id"])
    assert meta["ip_key"] == "" and meta["public_live"] is False  # unmetered, charged to nobody


def test_mid_run_spend_over_the_ip_share_is_refused(client, monkeypatch):
    enable(monkeypatch, features="byo", per_ip=0.01)
    vid = sample(client)["id"]
    sc = registry.scope_for(vid)
    with scope.use(sc):
        ledger.record("muse-spark-1.3", {"input_tokens": 10_000_000})  # one big call
        with pytest.raises(PublicBudgetExhausted):
            ledger.check_budget()


# ---------- the live copilot on a replay deploy ----------


def wav(seconds=0.2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


@pytest.fixture
def fakes(monkeypatch):
    """Scripted ASR and extraction; records which public context each model call ran under."""
    heard: list[str] = []
    seen: list[tuple[str, object]] = []
    cost = {"asr": 0.02, "llm": 0.01}

    async def fake_transcribe(data):
        pc = public_live.current()
        seen.append(("asr", pc))
        ledger.check_budget()
        c = ledger.record("muse-spark-1.3", {"input_tokens": int(cost["asr"] / 1.25 * 1_000_000)})
        return media.Transcription(heard.pop(0), 0.0001, media.Spend("muse-voice-transcribe-1.0", c))

    async def fake_call(stage, messages, *, task, schema, **kw):
        seen.append(("llm", public_live.current()))
        assert llm.resolve_mode(stage) == "live"  # the context turns Negotiate live even on a replay deploy
        ledger.check_budget()
        c = ledger.record("muse-spark-1.3", {"input_tokens": int(cost["llm"] / 1.25 * 1_000_000)})
        return llm.LlmResult("{}", TurnExtraction(), "muse-spark-1.3", "meta", "live", 100, 50, c, 5.0)

    monkeypatch.setattr(media, "transcribe", fake_transcribe)
    monkeypatch.setattr(llm, "call", fake_call)
    return heard, seen, cost


def start_live(client, headers=None):
    return client.post("/api/vendors/V002/call", json={"mode": "live"}, headers=headers or {})


def say(client, call_id, text, heard, **kw):
    heard.append(text)
    return client.post("/api/vendors/V002/call/chunks", data={"call_id": call_id, "speaker": "auto"}, files={"audio": ("c.wav", wav(), "audio/wav")}, **kw)


def test_live_call_needs_demo_key_when_copilot_is_not_public(client, monkeypatch):
    enable(monkeypatch, features="byo")
    r = start_live(client)
    assert r.status_code == 403 and r.json()["code"] == "demo_key_required"


def test_public_live_call_on_replay_deploy(client, monkeypatch, fakes):
    heard, seen, _ = fakes
    enable(monkeypatch, features="copilot")
    before = [t["text"] for t in load_transcript("V002")]
    r = start_live(client)
    assert r.status_code == 202 and r.json()["public"] is True
    call_id = r.json()["call_id"]
    turn = say(client, call_id, "Where can you get to on margin?", heard)
    assert turn.status_code == 200 and turn.json()["turn"]["source"] == "asr"
    typed = client.post("/api/vendors/V002/call/turns", json={"call_id": call_id, "speaker": "vendor", "text": "22 percent"})
    assert typed.status_code == 200
    assert {k for k, _ in seen} == {"asr", "llm"} and all(pc == public_live.PublicCtx("copilot", IP) for _, pc in seen)
    assert public_live.spent_ip(IP) > 0 and public_live.spent_total() == public_live.spent_ip(IP)
    ended = client.post("/api/vendors/V002/call/end", json={"call_id": call_id})
    assert ended.json()["ended"] is True
    assert [t["text"] for t in load_transcript("V002")] == before  # a public call never rewrites the shared transcript
    assert client.get(f"/api/vendors/V002/call/{call_id}").json()["public"] is True


def test_public_live_call_budget_exhaustion_falls_back_gracefully(client, monkeypatch, fakes):
    heard, _, _ = fakes
    enable(monkeypatch, features="copilot", per_ip=0.05)
    call_id = start_live(client).json()["call_id"]
    assert say(client, call_id, "one", heard).status_code == 200  # $0.03 spent
    assert say(client, call_id, "two", heard).status_code == 200  # $0.06 spent: over the $0.05 share
    r = say(client, call_id, "three", heard)
    assert r.status_code == 429 and r.json()["code"] == "public_budget_exhausted"
    assert "Public live budget used up" in r.json()["problem"]
    r = start_live(client)  # a new live call is refused too ...
    assert r.status_code == 429 and r.json()["code"] == "public_budget_exhausted"
    sim = client.post("/api/vendors/V002/call", json={"mode": "simulate"})  # ... but Simulate stays free
    assert sim.status_code == 202 and sim.json()["public"] is False


def test_public_live_call_shared_budget_and_cap(client, monkeypatch):
    enable(monkeypatch, features="copilot", budget=1.0, per_ip=0.9)
    public_live.charge("other", 1.0)
    assert start_live(client).json()["code"] == "public_budget_exhausted"
    public_live.charge("other", -0)  # no-op
    enable(monkeypatch, features="copilot", budget=50.0, per_ip=50.0)
    monkeypatch.setattr(settings, "max_spend_usd", 0.001)
    ledger.record("muse-spark-1.3", {"input_tokens": 1_000_000})
    r = start_live(client)
    assert r.status_code == 429 and "MAX_SPEND_USD" in r.json()["cause"]


def test_public_live_call_is_rate_limited(client, monkeypatch, fakes):
    enable(monkeypatch, features="copilot")
    monkeypatch.setattr(settings, "rate_limit_per_min", 2)
    assert start_live(client).status_code == 202
    assert start_live(client).status_code == 202
    assert start_live(client).status_code == 429  # existing per-minute limiter


def test_public_call_cannot_be_driven_from_another_address(client, monkeypatch, fakes):
    heard, _, _ = fakes
    enable(monkeypatch, features="copilot")
    call_id = start_live(client).json()["call_id"]
    from app import copilot

    copilot.get(call_id).public_ip = "someone-else"
    r = say(client, call_id, "hi", heard)
    assert r.status_code == 403


def test_demo_key_path_for_the_copilot_is_unchanged(client, monkeypatch, fakes):
    heard, seen, _ = fakes
    enable(monkeypatch, features="copilot")
    monkeypatch.setattr(settings, "demo_key", "secret")
    monkeypatch.setattr(llm, "resolve_mode", lambda stage: "live")
    H = {"X-Demo-Key": "secret"}
    r = start_live(client, H)
    assert r.status_code == 202 and r.json()["public"] is False
    call_id = r.json()["call_id"]
    assert say(client, call_id, "hello", heard, headers=H).status_code == 200
    assert all(pc is None for _, pc in seen)  # unmetered by the public budget
    assert public_live.spent_total() == 0
    r = say(client, call_id, "again", heard)  # no key on a live-mode server: refused as before
    assert r.status_code == 403 and r.json()["code"] == "demo_key_required"


def test_public_live_endpoint_and_mode_report_budget(client, monkeypatch):
    enable(monkeypatch)
    public_live.charge(IP, 0.2)
    body = client.get("/api/public-live").json()
    assert body["enabled"] and body["features"] == ["byo", "copilot"]
    assert body["remaining_usd"] == pytest.approx(4.8) and body["ip_remaining_usd"] == pytest.approx(0.3)
    mode = client.get("/api/mode").json()["public_live"]
    assert mode["enabled"] and "ip_remaining_usd" not in mode  # no per-address data in the shared mode payload


# ---------- provenance ----------


@pytest.fixture
def replay_mode(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    replay.forget()
    yield
    replay.forget()


def test_provenance_reports_the_fixture_source(client, replay_mode):
    mode = client.get("/api/mode").json()
    assert set(mode["provenance"]) == {"V001", "V002", "V003", "V004"}
    # the committed goldens were recorded live on 2026-10-27 (scripted `mock` goldens would report "mock"); either way the
    # source must be one of the two honest labels
    assert {p["source"] for p in mode["provenance"].values()} == {"live"}
    assert all(p["recorded_at"] and p["degraded"] is False for p in mode["provenance"].values())


def test_provenance_live_source_carries_date_and_cost(client, replay_mode):
    replay.load_all()
    golden = replay._goldens["V001"]
    for event in golden.events:
        event.cost_usd = None  # start from a known total: the recorded run's real spend is not what is under test
    golden.meta.source = "live"
    golden.events[0].cost_usd = 0.4
    golden.events[1].cost_usd = 0.125
    p = replay.provenance("V001")
    assert p["source"] == "live" and p["cost_usd"] == pytest.approx(0.525) and p["recorded_at"] == golden.meta.recorded_at
    assert client.get("/api/mode").json()["provenance"]["V001"]["source"] == "live"
    other = replay._goldens["V002"]
    other.meta.source = "mock"  # sources are per vendor: one vendor's label does not leak into another's
    assert client.get("/api/mode").json()["provenance"]["V002"]["source"] == "mock"


def test_degraded_vendor_is_never_labelled_live(client, replay_mode, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "fixtures_dir", tmp_path / "empty")  # no golden runs at all
    replay.forget()
    p = replay.provenance("V001")
    assert p == {"source": "mock", "recorded_at": None, "cost_usd": 0.0, "degraded": True}


def test_run_payload_carries_provenance(client, replay_mode):
    run_id = client.post("/api/vendors/V001/runs").json()["run_id"]
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["mode"] == "replay" and body["provenance"]["source"] == replay.provenance("V001")["source"] == "live"


def test_no_provenance_outside_replay(client):
    assert client.get("/api/mode").json()["provenance"] == {}
    run_id = client.post("/api/vendors/V001/runs").json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["provenance"] is None


# ---------- security ----------


def test_no_secret_is_exposed_to_the_browser():
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"NEXT_PUBLIC_\w*(KEY|SECRET|TOKEN)\w*", re.IGNORECASE)
    hits = []
    for base in (root / "frontend" / "app", root / "frontend" / "components", root / "frontend" / "lib", root / ".env.example", root / "scripts"):
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx", ".md", ".mjs", ".sh", ".example"}]
        for f in files:
            for m in pattern.finditer(f.read_text(errors="ignore")):
                hits.append(f"{f.relative_to(root)}: {m.group(0)}")
    assert hits == []


def test_public_endpoints_never_echo_keys(client, monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "demo_key", "super-secret-demo")
    text = client.get("/api/public-live").text + client.get("/api/mode").text + client.get("/api/uploads/options").text
    assert "super-secret-demo" not in text and "test-key" not in text

