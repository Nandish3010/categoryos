"""Hard-mode extraction eval: the generated set is deterministic and committed, every task's ground truth passes the real
verifier, the predictable wrong readings behave as documented, and the mock run is labelled mock and repeatable."""

import asyncio
import json
from collections import Counter

import pytest
from eval import hard, hard_data, hard_eval, hard_report


@pytest.fixture
def world(tmp_path):
    with hard_data.hard_root(tmp_path, 42) as hs:
        yield hs


def test_the_committed_set_equals_a_fresh_run_of_the_generator():
    fresh = hard_data.committed_files(hard_data.build(42))
    for name, text in fresh.items():
        assert (hard.SET_DIR / name).read_text(encoding="utf-8") == text, f"{name} is stale: run python -m eval.hard --write-set"
    assert hard_data.build(42).tasks == hard_data.build(42).tasks
    assert hard_data.tasks_json(hard_data.build(42)) != hard_data.tasks_json(hard_data.build(7))


def test_the_set_covers_every_category_with_ground_truth_for_every_task(world):
    counts = Counter(t.category for t in world.tasks)
    assert set(counts) == {k for k, _ in hard_data.CATEGORIES} and min(counts.values()) >= 4
    assert len(world.tasks) == 94 and len({t.id for t in world.tasks}) == 94
    for t in world.tasks:
        assert t.truth > 0 and t.ask
        if t.channel == "sheet":
            assert t.row > 1 and t.header in hard_data.HEADERS
            assert world.sheet[t.row - 1][0] == t.code
        else:
            assert t.turn >= 1 and world.turns[t.turn - 1]["turn"] == t.turn
    # the sheet really is messy: dividers, a note line, a re-header line, injections
    flat = [row[0] for row in world.sheet]
    assert sum(1 for c in flat if c.startswith("---")) == 6 and any(c.startswith("NOTE") for c in flat)
    assert hard_data.SWAPPED_HEADERS in world.sheet
    assert sum(1 for t in world.tasks if t.category == "injection_sheet") == 5
    assert any("Note to AI" in x["text"] or "AI" in x["text"] for x in world.turns)


def test_every_ground_truth_answer_is_accepted_by_the_real_verifier(world):
    agent = hard_eval.MockAgent(hard_eval.MODELS[0], world, 42)
    by_id = {hard_eval.claim_id(t): t for t in world.tasks}
    claims = [hard_eval.build_claim(t, agent.truth(t)) for t in world.tasks]
    checked = hard_eval.verify(by_id, claims)
    bad = [(c.id, c.reason) for c in checked if c.status != "verified"]
    assert bad == []
    assert all(hard_eval.is_right(by_id[c.id], c) for c in checked)


def test_predictable_wrong_readings_are_caught_except_where_the_verifier_cannot_tell(world):
    """Decoys: paise, unit, multipack, injection and swapped-column slips are rejected (the row plausibility check catches a
    cost not below its MRP). A figure read from the wrong but real cell (the old cost) or the wrong number inside the right quote passes the verifier: those are the silent errors."""
    agent = hard_eval.MockAgent(hard_eval.MODELS[0], world, 42)
    by_id = {hard_eval.claim_id(t): t for t in world.tasks}
    verdict: dict[str, set[str]] = {}
    for t in world.tasks:
        if t.decoy is None:
            continue
        if t.channel == "sheet":
            ans = hard_eval.Answer(t.decoy, t.row, t.decoy_header or t.header)
        else:
            turn = t.decoy_turn or t.turn
            ans = hard_eval.Answer(hard_eval._model_units(t, t.decoy), turn=turn, quote=agent.turn_text[turn])
        claim = hard_eval.verify(by_id, [hard_eval.build_claim(t, ans)])[0]
        assert not hard_eval.is_right(t, claim) or claim.status != "verified"
        verdict.setdefault(t.category, set()).add(claim.status)
    for caught in ("paise_trap", "unit_mix", "multipack", "injection_sheet", "spelled", "swapped_block"):
        assert verdict[caught] == {"rejected"}, caught
    for silent in ("revised_conflict", "conflict_turns", "injection_call"):
        assert "verified" in verdict[silent], silent


def test_a_wrong_row_is_caught_by_the_row_owner_rule(world):
    t = next(x for x in world.tasks if x.channel == "sheet")
    by_id = {hard_eval.claim_id(x): x for x in world.tasks}
    claim = hard_eval.build_claim(t, hard_eval.Answer(t.truth, t.row + 1, t.header))
    out = hard_eval.verify(by_id, [claim])[0]
    assert out.status == "rejected" or not hard_eval.is_right(t, out)


def test_the_mock_run_is_repeatable_labelled_mock_and_names_no_model(world):
    a = asyncio.run(hard_eval.run(world, "mock", 42))
    b = asyncio.run(hard_eval.run(world, "mock", 42))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["mode"] == "mock" and a["stand_in"] is True and a["spent_usd"] is None
    text = json.dumps(a)
    assert "muse-" not in text and "Baseten" not in text and "baseten" not in text
    for m in a["models"]:
        assert m["stand_in"] and m["cost_usd"] is None and m["latency_ms_per_task"] is None and m["input_tokens"] is None
        assert 0 <= m["first_pass_accuracy"] <= m["final_accuracy"] <= m["final_accuracy_with_escalation"] <= 1
        assert m["escalated"] >= m["fixed_by_escalation"] and (m["escalation"] or m["escalated"] == 0)
        assert m["silent_errors_with_escalation"] >= 0 and sum(c["tasks"] for c in m["categories"]) == m["tasks"]


def test_escalation_changes_only_what_the_retries_left_rejected(world):
    a = asyncio.run(hard_eval.run(world, "mock", 42))
    for m in a["models"]:
        if not m["escalation"]:
            assert m["final_accuracy"] == m["final_accuracy_with_escalation"]
            continue
        # a claim is escalated only when it is still rejected after the retries
        assert m["escalated"] == m["removed"]
        assert m["removed_with_escalation"] == m["removed"] - m["fixed_by_escalation"] - (
            m["silent_errors_with_escalation"] - m["silent_errors"]
        )


def test_the_tables_render_and_inject_between_the_markers(world, tmp_path):
    result = asyncio.run(hard_eval.run(world, "mock", 42))
    block = hard_report.render(result)
    assert block.startswith("**Mode: mock.**") and "scripted stand-in A" in block and "Escalation" in block
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{hard_report.START}\nold\n{hard_report.END}\nafter\n", encoding="utf-8")
    assert hard_report.inject(readme, block)
    text = readme.read_text(encoding="utf-8")
    assert "old" not in text and text.startswith("before\n") and text.endswith("after\n")
    bare = tmp_path / "bare.md"
    bare.write_text("no markers here", encoding="utf-8")
    assert not hard_report.inject(bare, block)


def test_the_swapped_block_truth_verifies_and_the_decoy_is_rejected(world):
    by_id = {hard_eval.claim_id(x): x for x in world.tasks}
    tasks = [t for t in world.tasks if t.category == "swapped_block"]
    assert tasks
    for t in tasks:
        ok = hard_eval.verify(by_id, [hard_eval.build_claim(t, hard_eval.Answer(t.truth, t.row, t.header))])[0]
        assert ok.status == "verified" and hard_eval.is_right(t, ok)
        bad = hard_eval.verify(by_id, [hard_eval.build_claim(t, hard_eval.Answer(t.decoy, t.row, t.decoy_header))])[0]
        assert bad.status == "rejected" and "look swapped" in bad.reason
