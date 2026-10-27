"""Live negotiation copilot: the simulated call through the real pipeline, the live (mic) path with fakes, verification
against the call's own turns, the next ask, budgets, typed errors and the SSE stream."""

import io
import json
import time
import wave

import pytest
from fastapi.testclient import TestClient

from app import copilot, llm, media
from app.config import settings
from app.data_loader import load_transcript
from app.main import app
from app.schemas import Commitment, DealCondition, DealTerm, TurnExtraction


@pytest.fixture
def client(monkeypatch):
    async def no_sleep(_s):
        return None

    monkeypatch.setattr(copilot, "sleep", no_sleep)
    monkeypatch.setattr(settings, "copilot_sim_speed", 1000.0)
    with TestClient(app) as c:
        yield c


def wait_ended(client, vendor, call_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/vendors/{vendor}/call/{call_id}").json()
        if snap["ended"]:
            return snap
        time.sleep(0.02)
    raise AssertionError("call did not end")


def events(client, vendor, call_id, last=None):
    headers = {"Last-Event-ID": str(last)} if last is not None else {}
    out = []
    with client.stream("GET", f"/api/vendors/{vendor}/call/{call_id}/events", headers=headers) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


# ---------- the simulated call ----------


def test_simulated_call_streams_the_canonical_call_through_the_pipeline(client):
    res = client.post("/api/vendors/V002/call", json={"mode": "simulate"})
    assert res.status_code == 202 and res.json()["mode"] == "simulate"
    call_id = res.json()["call_id"]
    snap = wait_ended(client, "V002", call_id)
    assert [t["text"] for t in snap["turns"]] == [t["text"] for t in load_transcript("V002")]
    assert all(t["source"] == "simulated" for t in snap["turns"])
    state = snap["state"]
    rows = {r["term"]: r for r in state["gap_table"]}
    assert rows["margin_pct"]["offered"] == 21 and rows["margin_pct"]["status"] == "gap" and rows["margin_pct"]["verification"] == "verified"
    assert rows["payment_days"]["offered"] == 30 and rows["returns"]["offered"] == 7
    deal = state["deals"]["assessments"][0]
    assert deal["decision"] == "reject_structure" and deal["probability"] < 0.001 and deal["counters"][0]["threshold"] == 250
    assert state["verification"]["rejected"] == 0 and state["verification"]["total"] > 14
    assert state["next_ask"]["kind"] == "reject_conditional"


def test_events_tell_the_story_turn_by_turn(client):
    call_id = client.post("/api/vendors/V002/call", json={"mode": "simulate"}).json()["call_id"]
    wait_ended(client, "V002", call_id)
    evs = events(client, "V002", call_id)
    types = [e["type"] for e in evs]
    assert types[0] == "started" and types[-1] == "ended" and types.count("turn") == 22
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    states = [e for e in evs if e["type"] == "state"]
    assert len(states) == 22
    by_turn = {e["payload"]["turn"]: e for e in states}
    # margin lands on turn 4 and the row flashes; the conditional offer lands on turn 18
    assert by_turn[4]["payload"]["changed"]["gap_terms"] == ["margin_pct"]
    assert by_turn[4]["payload"]["state"]["next_ask"]["kind"] == "gap"
    assert "margin" in by_turn[4]["payload"]["state"]["next_ask"]["line"].lower()
    assert by_turn[16]["payload"]["state"]["deals"] is None
    assert by_turn[18]["payload"]["changed"]["deal_ids"] and by_turn[18]["payload"]["state"]["next_ask"]["kind"] == "reject_conditional"
    # a late subscriber can resume
    tail = events(client, "V002", call_id, last=evs[-3]["seq"])
    assert [e["seq"] for e in tail] == [evs[-2]["seq"], evs[-1]["seq"]]


def test_the_next_ask_gives_the_reason_with_engine_numbers(client):
    call_id = client.post("/api/vendors/V002/call", json={"mode": "simulate"}).json()["call_id"]
    wait_ended(client, "V002", call_id)
    by_turn = {e["payload"]["turn"]: e["payload"]["state"] for e in events(client, "V002", call_id) if e["type"] == "state"}
    ask = by_turn[4]["next_ask"]
    assert "21%" in ask["line"] and "35%" in ask["line"] and "14 pts short" in ask["reason"]
    assert "15-day payment" in ask["reason"] and "costs us" in ask["reason"]  # they want cash: trade it for margin
    cond = by_turn[18]["next_ask"]
    assert "<0.1%" in cond["reason"] and "15%" in cond["reason"] and "22%" in cond["reason"]
    assert "250 units in 90 days" in cond["line"]


def test_simulation_needs_a_recorded_call_and_cannot_take_audio(client):
    r = client.post("/api/vendors/V001/call", json={"mode": "simulate"})
    assert r.status_code == 422 and r.json()["code"] == "no_call_script"
    call_id = client.post("/api/vendors/V002/call", json={"mode": "simulate"}).json()["call_id"]
    r = client.post("/api/vendors/V002/call/turns", json={"call_id": call_id, "speaker": "buyer", "text": "hi"})
    assert r.status_code == 409 and r.json()["code"] == "call_not_accepting_input"
    assert client.get("/api/vendors/V002/call/nope").json()["code"] == "call_not_found"
    assert client.get(f"/api/vendors/V003/call/{call_id}").status_code == 404  # another vendor's id


def test_live_mic_needs_live_mode_and_the_demo_key(client):
    r = client.post("/api/vendors/V002/call", json={"mode": "live"})
    assert r.status_code == 403 and r.json()["code"] == "demo_key_required"  # no DEMO_KEY configured
    settings.demo_key = "k"
    r = client.post("/api/vendors/V002/call", json={"mode": "live"}, headers={"X-Demo-Key": "k"})
    assert r.status_code == 409 and r.json()["code"] == "live_call_unavailable"  # mock mode has no voice model


def test_ending_a_simulated_call_twice_is_harmless(client):
    call_id = client.post("/api/vendors/V002/call", json={"mode": "simulate"}).json()["call_id"]
    wait_ended(client, "V002", call_id)
    assert client.post("/api/vendors/V002/call/end", json={"call_id": call_id}).json()["ended"] is True


# ---------- the live path, with fakes for the voice and text models ----------


def wav(seconds=0.2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


@pytest.fixture
def live(client, monkeypatch):
    """Live mode with a demo key; transcription and extraction are scripted fakes (no network)."""
    settings.demo_key = "k"
    monkeypatch.setattr(llm, "resolve_mode", lambda stage: "live")
    heard: list[str] = []
    script: dict[int, TurnExtraction] = {}
    costs = {"asr": 0.0, "llm": 0.0}

    async def fake_transcribe(data):
        return media.Transcription(heard.pop(0), 0.0001, media.Spend("muse-voice-transcribe-1.0", costs["asr"]))

    async def fake_call(stage, messages, *, task, schema, **kw):
        n = int(task.rsplit("_t", 1)[1])
        return llm.LlmResult("{}", script.get(n, TurnExtraction()), "muse-spark-1.3", "meta", "live", 100, 50, costs["llm"], 5.0)

    monkeypatch.setattr(media, "transcribe", fake_transcribe)
    monkeypatch.setattr(llm, "call", fake_call)
    H = {"X-Demo-Key": "k"}
    call_id = client.post("/api/vendors/V002/call", json={"mode": "live"}, headers=H).json()["call_id"]

    def say(speaker, text, **kw):
        heard.append(text)
        return client.post("/api/vendors/V002/call/chunks", data={"call_id": call_id, "speaker": speaker}, files={"audio": ("c.wav", wav(), "audio/wav")}, headers=H, **kw)

    return client, call_id, say, script, costs, H


def test_live_chunks_become_turns_and_verified_commitments(live):
    _client, _call_id, say, script, _, _H = live
    assert say("buyer", "Where can you get to on margin?").json()["turn"]["turn"] == 1
    quote = "I can move to 22 percent on everything."
    script[2] = TurnExtraction(commitments=[Commitment(term="margin_pct", offered=22, transcript_quote=quote, turn=2)])
    r = say("vendor", f"Well, {quote}")
    assert r.status_code == 200 and r.json()["turn"] == {"turn": 2, "speaker": "vendor", "text": f"Well, {quote}", "source": "asr"}
    row = next(x for x in r.json()["state"]["gap_table"] if x["term"] == "margin_pct")
    assert row["offered"] == 22 and row["verification"] == "verified" and row["status"] == "gap"
    assert r.json()["state"]["transcript_source"] == "asr"


def test_a_quote_the_vendor_never_said_is_rejected_against_the_live_turns(live):
    _client, _call_id, say, script, _, _H = live
    say("buyer", "Margin?")
    script[2] = TurnExtraction(commitments=[Commitment(term="margin_pct", offered=30, transcript_quote="I will do 30 percent.", turn=2)])
    state = say("vendor", "I can do 22 percent maybe.").json()["state"]
    row = next(x for x in state["gap_table"] if x["term"] == "margin_pct")
    assert row["status"] == "not_stated" and state["verification"]["rejected"] == 1
    assert state["commitments"][0]["status"] == "rejected" and "verbatim" in state["commitments"][0]["reason"]


def test_a_live_conditional_offer_gets_its_probability_as_it_is_said(live):
    _client, _call_id, say, script, _, _H = live
    say("buyer", "Anything on litter?")
    quote = "I will add 10 percent marketing support if you sell 1,500 units in 60 days."
    term = DealTerm(id="t1", kind="conditional", term="marketing_pct", value=10, unit="pct", condition=DealCondition(metric="units", threshold=1500, window_days=60), quote=quote, turn=2)
    script[2] = TurnExtraction(deal_terms=[term])
    state = say("vendor", f"OK. {quote}").json()["state"]
    (a,) = state["deals"]["assessments"]
    assert a["term_id"] == "t1-2" and a["probability"] < 0.001 and a["decision"] in ("reject_structure", "accept")
    assert state["deals"]["verification"]["rejected"] == 0
    # the vendor restating it is not a second offer
    script[4] = TurnExtraction(deal_terms=[term.model_copy(update={"turn": 4})])
    say("buyer", "Say again?")
    state = say("vendor", f"Yes. {quote}").json()["state"]
    assert len(state["deals"]["assessments"]) == 1


def test_speaker_alternates_when_not_told(live):
    _client, _call_id, say, *_ = live
    assert say("auto", "one").json()["turn"]["speaker"] == "buyer"
    assert say("auto", "two").json()["turn"]["speaker"] == "vendor"
    assert say("auto", "three").json()["turn"]["speaker"] == "buyer"


def test_typed_lines_use_the_same_pipeline(live):
    client, call_id, _say, _script, _, H = live
    r = client.post("/api/vendors/V002/call/turns", json={"call_id": call_id, "speaker": "buyer", "text": "Hello"}, headers=H)
    assert r.status_code == 200 and r.json()["turn"]["source"] == "typed"


def test_bad_audio_is_refused_with_typed_errors(live, monkeypatch):
    client, call_id, _say, *_, H = live
    r = client.post("/api/vendors/V002/call/chunks", data={"call_id": call_id}, files={"audio": ("c.wav", b"not a wav", "audio/wav")}, headers=H)
    assert r.status_code == 415 and r.json()["code"] == "unsupported_audio"
    monkeypatch.setattr(settings, "call_chunk_max_bytes", 100)
    r = client.post("/api/vendors/V002/call/chunks", data={"call_id": call_id}, files={"audio": ("c.wav", wav(), "audio/wav")}, headers=H)
    assert r.status_code == 413 and r.json()["code"] == "chunk_too_large"


def test_the_per_call_budget_stops_spending(live, monkeypatch):
    client, call_id, say, _script, costs, _H = live
    monkeypatch.setattr(settings, "call_budget_usd", 0.05)
    costs["asr"] = 0.04
    assert say("buyer", "first").status_code == 200  # 0.04 spent
    assert say("vendor", "second").status_code == 200  # 0.08 spent, now over
    r = say("buyer", "third")
    assert r.status_code == 429 and r.json()["code"] == "call_budget_exceeded"
    snap = client.get(f"/api/vendors/V002/call/{call_id}").json()
    assert len(snap["turns"]) == 2 and snap["spend_usd"] >= 0.08


def test_ending_a_live_call_makes_its_transcript_canonical(live):
    client, call_id, say, _script, _, H = live
    say("buyer", "Margin?")
    say("vendor", "I can do 22 percent.")
    r = client.post("/api/vendors/V002/call/end", json={"call_id": call_id}, headers=H)
    assert r.json()["ended"] is True
    assert [t["text"] for t in load_transcript("V002")] == ["Margin?", "I can do 22 percent."]
    again = say("buyer", "late")
    assert again.status_code == 409 and again.json()["code"] == "call_ended"
    events_ = events(client, "V002", call_id)
    assert events_[-1]["type"] == "ended" and events_[-1]["payload"]["canonical"] is True


def test_extraction_failure_is_an_event_not_a_crash(live, monkeypatch):
    client, call_id, say, *_ = live
    from app.errors import LlmUnavailable

    async def boom(*a, **k):
        raise LlmUnavailable()

    monkeypatch.setattr(llm, "call", boom)
    say("buyer", "hi")
    r = say("vendor", "hello there")
    assert r.status_code == 200
    client.post("/api/vendors/V002/call/end", json={"call_id": call_id}, headers={"X-Demo-Key": "k"})
    errs = [e for e in events(client, "V002", call_id) if e["type"] == "error"]
    assert errs and errs[0]["payload"]["code"] == "llm_unavailable"


# ---------- the next ask, unit level ----------


def test_next_ask_with_nothing_said_listens():
    s = copilot.CallSession("c", "V002", "simulate", 1.0)
    state = copilot.compute_state(s)
    assert state["next_ask"]["kind"] == "ask_term" or state["next_ask"]["kind"] == "listen"
    assert state["gap_table"] and all(r["status"] == "not_stated" for r in state["gap_table"])
