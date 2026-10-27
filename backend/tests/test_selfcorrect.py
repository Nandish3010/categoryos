"""Self-correction loop: the verifier rejects, the agent is told what the source says, a corrected answer is
re-verified, and a claim that never gets right stays rejected."""

import asyncio
import json

import pytest

from app import llm, policy, selfcorrect
from app.agents import catalog, decide, negotiate
from app.agents.context import RunContext, Sequencer
from app.errors import FixtureMissing
from app.metrics import apply_levers, build_base
from app.schemas import (
    Claim,
    Commitment,
    Evidence,
    FixFinal,
    NegotiateFinal,
    SourceRef,
    StageResult,
)
from app.verify import file_sha256, verify_claim

STORY = {"claim_rejected", "self_correction", "claim_verified", "claim_unresolved"}
HP_D01 = "V001:HP-D01:cost:extracted"


def drive(coro_fn, vendor_id, *args, **kw):
    ctx = RunContext("run_test", vendor_id, "2026-10-27", Sequencer())
    result = asyncio.run(coro_fn(ctx, *args, **kw))
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait())
    return result, events


def story(events):
    return [(e.type, e.payload.get("attempt")) for e in events if e.type in STORY]


class FakeFixes:
    """Replaces llm.call for the ``__fix<n>`` tasks: scripted answers per attempt, everything else goes through."""

    def __init__(self, monkeypatch, answers):
        self.answers = answers  # attempt -> list of fix dicts, or an exception
        self.calls = []
        self.real = llm.call
        monkeypatch.setattr(llm, "call", self)

    async def __call__(self, stage, messages, **kw):
        task = kw.get("task", "")
        if "__fix" not in task:
            return await self.real(stage, messages, **kw)
        attempt = int(task.rsplit("__fix", 1)[1])
        self.calls.append({"task": task, "messages": messages})
        answer = self.answers.get(attempt)
        if isinstance(answer, Exception):
            raise answer
        parsed = FixFinal.model_validate({"fixes": answer or []})
        return llm.LlmResult(
            content=json.dumps(parsed.model_dump()), parsed=parsed, model="muse-spark-1.3", provider="meta", mode="mock",
            input_tokens=10, output_tokens=5, cost_usd=0.0, latency_ms=1.0,
        )


def fix(value, row=2, header="Cost to Us", claim_id=HP_D01):
    return {"claim_id": claim_id, "value": value, "row": row, "header": header}


# ---------- feedback ----------


def sheet_claim(value=965.5, row=2, reason="sheet cell 'Rs. 956.50' parses to 956.5, claim says 965.5"):
    rel = "vendors/V001/sku_sheet.csv"
    return Claim(
        id=HP_D01, text="x", value=value, metric="cost", unit="inr", sku_key="V001:HP-D01",
        source_ref=SourceRef(file=rel, key="V001:HP-D01", column="Cost to Us"),
        evidence=Evidence(row=row, header="Cost to Us", raw_value="Rs. 956.50", parser_version="1.0", sha256=file_sha256(rel)),
        origin="model_extraction", status="rejected", reason=reason, recomputed=956.5,
    )


def test_feedback_names_the_claim_what_the_agent_said_and_what_the_source_says():
    text = selfcorrect.feedback(sheet_claim())
    assert text == (
        "Claim V001:HP-D01:cost:extracted rejected: you said ₹965.50; the evidence cites sheet row 2 'Cost to Us'. "
        "Verifier: sheet cell 'Rs. 956.50' parses to 956.5, claim says 965.5. Re-read and correct."
    )


def test_feedback_for_a_percentage_commitment_cites_the_turn():
    claim = negotiate.commitment_claims(
        "V002", NegotiateFinal(commitments=[Commitment(term="margin_pct", offered=25, turn=4, transcript_quote="x")])
    )[0].model_copy(update={"status": "rejected", "reason": "the quote states 21; the commitment says 25"})
    text = selfcorrect.feedback(claim)
    assert "you said 25%" in text and "turn 4" in text and "the quote states 21" in text


# ---------- decide ----------


def test_the_agent_gets_the_feedback_as_a_message_and_the_retry_is_one_more_call(monkeypatch):
    fake = FakeFixes(monkeypatch, {1: [fix(956.5)]})
    _result, events = drive(decide.run, "V001")
    assert [c["task"] for c in fake.calls] == ["decide_V001__fix1"]
    msgs = fake.calls[0]["messages"]
    assert msgs[-2]["role"] == "assistant" and msgs[-1]["role"] == "user"
    assert "Claim V001:HP-D01:cost:extracted rejected: you said ₹965.50" in msgs[-1]["content"]
    assert story(events) == [("claim_rejected", 0), ("self_correction", 1), ("claim_verified", 1)]
    model_calls = [e for e in events if e.type == "model_call" and e.payload["task"].endswith("__fix1")]
    assert len(model_calls) == 1


def test_a_second_try_can_succeed_after_a_first_wrong_correction(monkeypatch):
    FakeFixes(monkeypatch, {1: [fix(950.0)], 2: [fix(956.5)]})
    result, events = drive(decide.run, "V001")
    claim = next(c for c in result.claims if c.id == HP_D01)
    assert claim.status == "verified" and [(a.attempt, a.status) for a in claim.attempts] == [(0, "rejected"), (1, "rejected"), (2, "verified")]
    assert story(events) == [
        ("claim_rejected", 0), ("self_correction", 1), ("claim_rejected", 1), ("self_correction", 2), ("claim_verified", 2),
    ]
    assert result.data["struck"] == []


def test_a_claim_that_never_gets_right_is_unresolved_and_the_sentence_is_struck(monkeypatch):
    FakeFixes(monkeypatch, {1: [fix(965.5)], 2: [fix(965.0)]})
    result, events = drive(decide.run, "V001")
    claim = next(c for c in result.claims if c.id == HP_D01)
    assert claim.status == "rejected" and [a.attempt for a in claim.attempts] == [0, 1, 2]
    assert story(events) == [
        ("claim_rejected", 0), ("self_correction", 1), ("claim_rejected", 1),
        ("self_correction", 2), ("claim_rejected", 2), ("claim_unresolved", None),
    ]
    assert len(result.data["struck"]) == 1 and result.data["struck"][0]["claimed_value"] == 965.5
    why = next(r["why"] for r in result.data["rationale_per_sku"] if r["code"] == "HP-D01")
    assert "965.5" not in why
    assert result.data["self_correction"]["unresolved"] == [HP_D01] and result.data["self_correction"]["corrected"] == []


def test_the_retry_limit_comes_from_the_playbook(monkeypatch):
    fake = FakeFixes(monkeypatch, {n: [fix(965.5)] for n in range(1, 6)})
    policy.save_overrides({"verifier": {"max_self_corrections": 1}})
    try:
        result, events = drive(decide.run, "V001")
    finally:
        policy.reset()
    assert len(fake.calls) == 1
    assert [e.payload["of"] for e in events if e.type == "self_correction"] == [1]
    assert next(c for c in result.claims if c.id == HP_D01).status == "rejected"


def test_a_missing_fix_leaves_the_claim_unresolved_without_failing_the_stage(monkeypatch):
    FakeFixes(monkeypatch, {1: FixtureMissing("no fixture", cause="x", fix="y")})
    result, events = drive(decide.run, "V001")
    assert result.status == "review"
    sc = [e for e in events if e.type == "self_correction"]
    assert len(sc) == 1 and sc[0].payload["answered"] is False and "note" in sc[0].payload
    assert story(events)[-1][0] == "claim_unresolved"
    assert len(result.data["struck"]) == 1


def test_a_correction_that_cites_another_skus_row_is_still_rejected(monkeypatch):
    FakeFixes(monkeypatch, {1: [fix(3150, row=3)]})  # 3150 is HP-D02's real cost in row 3
    result, _ = drive(decide.run, "V001")
    claim = next(c for c in result.claims if c.id == HP_D01)
    assert claim.status == "rejected" and "is not HP-D01's row" in claim.attempts[1].reason


def test_a_fix_for_a_claim_that_was_not_rejected_is_ignored(monkeypatch):
    FakeFixes(monkeypatch, {1: [fix(956.5), fix(1.0, row=3, claim_id="V001:HP-D02:cost:extracted")]})
    result, _ = drive(decide.run, "V001")
    other = next(c for c in result.claims if c.id == "V001:HP-D02:cost:extracted")
    assert other.status == "verified" and other.value == 3150 and other.attempts == []


def test_corrected_value_is_written_back_where_the_narrative_quoted_the_wrong_one():
    result, _ = drive(decide.run, "V001")
    narrative = json.dumps([result.data[k] for k in ("headline", "rationale_per_sku", "counter_offer")], ensure_ascii=False)
    assert "₹956.50" in narrative and "965.5" not in narrative


def test_apply_corrections_keeps_commas_and_decimals():
    narrative = {
        "headline": "HP-D02 costs ₹3,150 and HP-D01 ₹965.50.",
        "rationale_per_sku": [{"code": "HP-D02", "verdict": "list", "why": "Vendor cost is ₹3,150 per bag. Margin is fine."}],
        "counter_offer": {"email_draft": "Please confirm HP-D02 at ₹3,150. Thanks.", "terms": [{"term": "cost_price", "sku_code": "HP-D02", "rationale": "Was 3150."}]},
    }
    decide.apply_corrections(narrative, [("HP-D02", 3150.0, 3105.5)])
    assert narrative["rationale_per_sku"][0]["why"] == "Vendor cost is ₹3,105.50 per bag. Margin is fine."
    assert narrative["headline"] == "HP-D02 costs ₹3,105.50 and HP-D01 ₹965.50."
    assert narrative["counter_offer"]["email_draft"] == "Please confirm HP-D02 at ₹3,105.50. Thanks."
    assert narrative["counter_offer"]["terms"][0]["rationale"] == "Was 3105.50."


# ---------- negotiate ----------


def _research():
    lever = apply_levers(build_base("V002"))
    return StageResult(
        stage="research", status="done", data={"lever": {"target_margin_pct_offset": 0, "moq": lever.summary.moq}, "rationale_per_sku": []},
        metrics_hash=lever.metrics_hash, narrative_hash=lever.metrics_hash,
    )


def _lying_margin(monkeypatch):
    real = llm.run_tools

    async def lying(*args, **kwargs):
        res = await real(*args, **kwargs)
        for c in res.parsed.commitments:
            if c.term == "margin_pct":
                c.offered = 30
        return res

    monkeypatch.setattr(llm, "run_tools", lying)


def test_a_wrong_commitment_is_corrected_and_the_gap_table_uses_the_corrected_number(monkeypatch):
    _lying_margin(monkeypatch)
    fake = FakeFixes(monkeypatch, {1: [{"claim_id": "V002:commit:margin_pct:4:0", "value": 21}]})
    result, events = drive(negotiate.run, "V002", _research())
    assert [c["task"] for c in fake.calls] == ["negotiate_V002__fix1"]
    row = next(r for r in result.data["gap_table"] if r["term"] == "margin_pct")
    assert row["status"] == "gap" and row["offered"] == 21 and row["verification"] == "verified"
    claim = next(c for c in result.claims if c.metric == "commit_margin_pct")
    assert claim.status == "verified" and claim.value == 0.21 and [a.status for a in claim.attempts] == ["rejected", "verified"]
    assert result.data["verification"]["rejected"] == 0 and "failed verification" not in result.summary
    commit = next(c for c in result.data["commitments"] if c["term"] == "margin_pct")
    assert commit["offered"] == 21 and commit["status"] == "verified"
    assert story(events) == [("claim_rejected", 0), ("self_correction", 1), ("claim_verified", 1)]


def test_a_commitment_can_be_corrected_to_a_different_turn_and_quote(monkeypatch):
    _lying_margin(monkeypatch)
    quote = "If you take the full treats range, I can move to 21 percent."
    FakeFixes(monkeypatch, {1: [{"claim_id": "V002:commit:margin_pct:4:0", "value": 21, "turn": 4, "transcript_quote": quote}]})
    result, _ = drive(negotiate.run, "V002", _research())
    commit = next(c for c in result.data["commitments"] if c["term"] == "margin_pct")
    assert commit["transcript_quote"] == quote and commit["status"] == "verified"


def test_an_unresolved_commitment_still_drops_out_of_the_gap_table(monkeypatch):
    _lying_margin(monkeypatch)
    FakeFixes(monkeypatch, {1: [{"claim_id": "V002:commit:margin_pct:4:0", "value": 30}], 2: []})
    result, events = drive(negotiate.run, "V002", _research())
    row = next(r for r in result.data["gap_table"] if r["term"] == "margin_pct")
    assert row["status"] == "not_stated" and result.data["verification"]["rejected"] == 1
    assert story(events)[-1][0] == "claim_unresolved"


# ---------- catalog ----------


def _research_v001():
    lever = apply_levers(build_base("V001"))
    return StageResult(
        stage="research", status="done", data={"lever": {"target_margin_pct_offset": 0, "moq": lever.summary.moq}, "rationale_per_sku": []},
        metrics_hash=lever.metrics_hash, narrative_hash=lever.metrics_hash,
    )


def _wrong_mrp(monkeypatch):
    real = llm.call

    async def wrong(stage, messages, **kw):
        res = await real(stage, messages, **kw)
        if kw.get("task", "").startswith("catalog_copy") and "__fix" not in kw["task"]:
            res.parsed.items[0].attributes["mrp"] = 1949  # the sheet says 1499
        return res

    monkeypatch.setattr(llm, "call", wrong)


def test_a_wrong_catalog_attribute_is_corrected_by_the_agent(monkeypatch):
    _wrong_mrp(monkeypatch)
    fake = FakeFixes(monkeypatch, {1: [{"claim_id": "V001:HP-D01:mrp:catalog", "value": 1499}]})
    # FakeFixes wraps the already-patched llm.call, so the wrong-MRP patch stays in front of the real gateway
    result, events = drive(catalog.run, "V001", _research_v001())
    first = result.data["skus"][0]
    assert [c["task"] for c in fake.calls] == ["catalog_copy_V001__fix1"]
    assert first["corrections"] == [] and first["copy"]["attributes"]["mrp"] == 1499
    claim = next(c for c in result.claims if c.id == "V001:HP-D01:mrp:catalog")
    assert claim.status == "verified" and [a.value for a in claim.attempts] == [1949, 1499]
    assert story(events) == [("claim_rejected", 0), ("self_correction", 1), ("claim_verified", 1)]


def test_without_a_fix_the_catalog_still_replaces_the_value_from_the_sheet(monkeypatch):
    _wrong_mrp(monkeypatch)
    result, events = drive(catalog.run, "V001", _research_v001())
    first = result.data["skus"][0]
    assert first["corrections"][0]["claimed"] == 1949 and first["copy"]["attributes"]["mrp"] == 1499
    assert story(events)[-1][0] == "claim_unresolved"


# ---------- the loop on its own ----------


def test_verified_claims_cost_nothing(monkeypatch):
    fake = FakeFixes(monkeypatch, {})
    result, events = drive(decide.run, "V002")
    assert fake.calls == [] and story(events) == []
    assert result.data["self_correction"] == {"max": 2, "corrected": [], "unresolved": []}


def test_attempts_survive_verification(monkeypatch):
    FakeFixes(monkeypatch, {1: [fix(956.5)]})
    result, _ = drive(decide.run, "V001")
    claim = next(c for c in result.claims if c.id == HP_D01)
    again = verify_claim(claim)
    assert again.attempts == claim.attempts and again.status == "verified"


@pytest.mark.parametrize("limit", [0, 3])
def test_the_limit_is_validated(limit):
    policy.save_overrides({"verifier": {"max_self_corrections": limit}})
    try:
        assert policy.get().verifier.max_self_corrections == limit
    finally:
        policy.reset()
    with pytest.raises(Exception, match="max_self_corrections"):
        policy.save_overrides({"verifier": {"max_self_corrections": 9}})
