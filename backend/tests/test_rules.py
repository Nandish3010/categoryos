"""Playbook rules written as prompts: translation to a structured preview, roles and limits from the governance section, apply /
approve / reject / undo, the change log, and per-visitor sandboxes on a replay deploy. The model is never called: examples come
from recorded fixtures, free-form prompts from the deterministic mock translator or a patched gateway."""

import pytest
from fastapi.testclient import TestClient

from app import governance, ledger, llm, policy, public_live, rules, sandbox, store
from app.config import settings
from app.errors import PolicyInvalid
from app.main import app

TREATS_UP = "Raise the target margin on treats by 2 points"  # +2 pp: inside a manager's limit
TOYS_DOWN = "Cut the target margin on toys by 5 points"  # -5 pp: over it
FLOOR = "Never sell liquidation stock below 70% of cost"
LIMIT_UP = "Let managers change margins by up to 3 points at a time"  # governance: head only
OUT_OF_RANGE = "Set the target margin on treats to 120%"

MEERA, ARJUN, PRIYA = {"X-Acting-As": "meera"}, {"X-Acting-As": "arjun"}, {"X-Acting-As": "priya"}


@pytest.fixture(autouse=True)
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "state_dir", tmp_path / "state")
    monkeypatch.setattr(settings, "rate_limit_per_min", 10_000)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def propose(client, prompt, who=MEERA):
    res = client.post("/api/policy/propose", json={"prompt": prompt}, headers=who)
    assert res.status_code == 200, res.text
    return res.json()


def apply(client, prompt, who=MEERA):
    pre = propose(client, prompt, who)
    assert pre["status"] == "ready", pre
    return client.post(f"/api/policy/changes/{pre['id']}/apply", headers=who)


def target(name="treats"):
    return policy.load().policy.margins.categories[name].target_pct


def log(client, who=MEERA):
    return client.get("/api/policy/changes", headers=who).json()["changes"]


# ---------- prompt -> structured preview ----------


def test_example_prompt_becomes_a_preview_from_the_validated_playbook(client):
    before_hash = client.get("/api/policy").json()["hash"]
    pre = propose(client, TREATS_UP, ARJUN)
    assert pre["status"] == "ready" and pre["translator"] == "recorded example" and pre["outcome"] == {"action": "apply", "reason": None}
    (line,) = pre["changes"]
    assert line["path"] == "margins.categories.treats.target_pct" and line["keys"] == ["margins", "categories", "treats", "target_pct"]
    assert line["before"] == 35 and line["after"] == 37 and line["unit"] == "%" and "Target margin" in line["label"]
    assert {"research", "negotiate"} <= set(line["used_in"])
    # a dry run: nothing written, nothing in the log (a preview is only a draft)
    assert client.get("/api/policy").json()["hash"] == before_hash and not policy.local_path().exists()
    assert log(client) == []


def test_every_example_has_a_recorded_translation(client):
    expected = {TREATS_UP: "ready", TOYS_DOWN: "ready", FLOOR: "ready", LIMIT_UP: "ready", OUT_OF_RANGE: "invalid"}
    assert {e["prompt"] for e in rules.EXAMPLES} == set(expected)
    for ex in rules.EXAMPLES:
        assert rules.has_fixture(ex["prompt"])
        assert propose(client, ex["prompt"])["status"] == expected[ex["prompt"]]
    assert client.get("/api/policy/examples").json()["examples"] == rules.EXAMPLES


def test_invalid_value_gives_a_validation_error_and_writes_nothing(client):
    pre = propose(client, OUT_OF_RANGE)
    assert pre["status"] == "invalid" and pre["id"] is None and pre["changes"] == []
    err = pre["error"]
    assert err["code"] == "policy_invalid" and err["path"] == "margins.categories.treats.target_pct" and err["cause"] and err["fix"]
    assert target() == 35 and not policy.local_path().exists() and log(client) == []


def test_unknown_or_unsettable_paths_are_rejected(client, monkeypatch):
    def fake(paths):
        return lambda prompt, leaves: rules.RuleProposal(edits=[rules.RuleEdit(path=p, number=1) for p in paths])

    for bad in ("research.nonsense", "margins", "business.retailer", "screening.claim_rules", "version", "margins.categories.treats"):
        monkeypatch.setattr(rules, "mock_translate", fake([bad]))
        pre = propose(client, "make it so, number one")
        assert pre["status"] == "invalid" and pre["error"]["code"] == "rule_path_unknown" and pre["error"]["cause"], bad
    monkeypatch.setattr(rules, "mock_translate", fake(["research.demand_mn"]))
    assert "research.demand_min" in propose(client, "typo please")["error"]["fix"]  # a near miss is suggested
    # a value of the wrong type for a real setting
    monkeypatch.setattr(rules, "mock_translate", lambda p, leaves: rules.RuleProposal(edits=[rules.RuleEdit(path="research.demand_min", boolean=True)]))
    pre = propose(client, "wrong type please")
    assert pre["status"] == "invalid" and pre["error"]["path"] == "research.demand_min"
    assert log(client) == [] and not policy.local_path().exists()


def test_mock_translator_handles_free_text_and_says_when_it_cannot(client):
    pre = propose(client, "set minimum demand to 0.5")
    assert pre["status"] == "ready" and pre["translator"] == "mock translator" and pre["changes"][0]["path"] == "research.demand_min"
    assert pre["changes"][0]["before"] == 0.4 and pre["changes"][0]["after"] == 0.5
    pre = propose(client, "order me a pizza")
    assert pre["status"] == "unmapped" and "couldn't map this to a playbook setting" in pre["message"] and pre["id"] is None
    assert propose(client, "set minimum demand to 0.4")["status"] == "unchanged"  # already the value


def test_prompt_cannot_replace_free_text_or_lists_even_by_a_confused_model(client, monkeypatch):
    monkeypatch.setattr(rules, "mock_translate", lambda p, leaves: rules.RuleProposal(edits=[rules.RuleEdit(path="business.vertical", choice="beauty")]))
    assert propose(client, "rename the vertical")["error"]["code"] == "rule_path_unknown"


# ---------- roles and limits ----------


def test_manager_within_limit_applies_and_is_logged(client):
    res = apply(client, TREATS_UP, ARJUN)
    assert res.status_code == 200 and res.json()["change"]["status"] == "applied"
    assert target() == 37 and res.json()["policy"]["margins"]["categories"]["treats"]["target_pct"] == 37
    (entry,) = log(client)
    assert entry["actor"] == {"id": "arjun", "name": "Arjun", "role": "manager"} and entry["source"] == "prompt" and entry["prompt"] == TREATS_UP
    assert entry["diff"][0]["before"] == 35 and entry["diff"][0]["after"] == 37 and entry["status"] == "applied"
    assert entry["hash_before"] and entry["hash_after"] and entry["hash_before"] != entry["hash_after"]
    assert client.get("/api/policy").json()["overridden_paths"] == ["margins.categories"]  # tables are stored whole


def test_manager_over_limit_becomes_a_request_and_the_head_approves(client):
    pre = propose(client, TOYS_DOWN, ARJUN)
    assert pre["outcome"]["action"] == "request_approval" and "limit is 2 pp" in pre["outcome"]["reason"] and "5 pp" in pre["outcome"]["reason"]
    res = client.post(f"/api/policy/changes/{pre['id']}/apply", headers=ARJUN)
    assert res.status_code == 202
    change = res.json()["change"]
    assert change["status"] == "pending_approval" and target("toys") == 40  # nothing applied yet
    cid = change["id"]
    # a manager cannot approve (and the attempt is recorded on the request); nor can the requester approve themselves
    denied = client.post(f"/api/policy/changes/{cid}/approve", headers=ARJUN)
    assert denied.status_code == 403 and denied.json()["code"] == "change_refused" and target("toys") == 40
    assert client.post(f"/api/policy/changes/{cid}/approve", headers=PRIYA).status_code == 403
    entry = log(client)[0]
    assert entry["status"] == "pending_approval" and [e["action"] for e in entry["events"]].count("approve_refused") == 2
    # the head sees the buttons, the requester does not
    assert entry["allowed"] == {"approve": True, "reject": True, "undo": False}
    assert log(client, ARJUN)[0]["allowed"] == {"approve": False, "reject": True, "undo": False}  # the requester can only withdraw
    done = client.post(f"/api/policy/changes/{cid}/approve", headers=MEERA)
    assert done.status_code == 200 and done.json()["change"]["status"] == "applied" and target("toys") == 35
    got = log(client)[0]
    assert got["approver"]["id"] == "meera" and got["actor"]["id"] == "arjun" and "limit" in got["reason"]
    assert client.post(f"/api/policy/changes/{cid}/approve", headers=MEERA).status_code == 409  # not pending any more


def test_head_can_reject_a_request(client):
    cid = client.post(f"/api/policy/changes/{propose(client, TOYS_DOWN, ARJUN)['id']}/apply", headers=ARJUN).json()["change"]["id"]
    res = client.post(f"/api/policy/changes/{cid}/reject", headers=MEERA)
    assert res.status_code == 200 and res.json()["change"]["status"] == "rejected" and target("toys") == 40
    assert log(client)[0]["approver"]["id"] == "meera"


def test_requester_can_withdraw_but_an_analyst_cannot_reject_others(client):
    cid = client.post(f"/api/policy/changes/{propose(client, TOYS_DOWN, ARJUN)['id']}/apply", headers=ARJUN).json()["change"]["id"]
    assert client.post(f"/api/policy/changes/{cid}/reject", headers=PRIYA).status_code == 403
    res = client.post(f"/api/policy/changes/{cid}/reject", headers=ARJUN)
    assert res.status_code == 200 and res.json()["change"]["reason"] == "Withdrawn by the requester"


def test_analyst_is_refused_and_the_attempt_is_logged(client):
    pre = propose(client, TREATS_UP, PRIYA)
    assert pre["status"] == "ready" and pre["outcome"]["action"] == "refuse" and "cannot apply" in pre["outcome"]["reason"]
    res = client.post(f"/api/policy/changes/{pre['id']}/apply", headers=PRIYA)
    body = res.json()
    assert res.status_code == 403 and body["code"] == "change_refused" and body["cause"] and body["fix"] and body["change"]["status"] == "refused"
    assert target() == 35 and not policy.local_path().exists()
    (entry,) = log(client)
    assert entry["status"] == "refused" and entry["actor"]["role"] == "analyst" and "cannot apply" in entry["reason"] and entry["prompt"] == TREATS_UP


def test_manager_outside_their_sections_is_refused(client):
    res = apply(client, "set minimum demand to 0.5", ARJUN)  # research is the head's
    assert res.status_code == 403 and "may not change research" in res.json()["cause"]
    assert log(client)[0]["status"] == "refused"


def test_governance_is_head_only(client):
    pre = propose(client, LIMIT_UP, ARJUN)
    assert pre["outcome"]["action"] == "refuse" and "Only the head" in pre["outcome"]["reason"]
    assert apply(client, LIMIT_UP, ARJUN).status_code == 403
    assert policy.load().policy.governance.limits["manager_margins"].max_abs_change == 2
    form = client.put("/api/policy", json={"governance": {"roles": {"manager": {"sections": ["*"]}}}}, headers=ARJUN)  # a manager granting themselves everything
    assert form.status_code == 403 and "Only the head" in form.json()["cause"]
    ok = apply(client, LIMIT_UP, MEERA)
    assert ok.status_code == 200 and policy.load().policy.governance.limits["manager_margins"].max_abs_change == 3
    # the new limit is live: a 3 pp cut by a manager now applies without approval
    assert propose(client, "Cut the target margin on toys by 3 points", ARJUN)["outcome"]["action"] == "apply"


def test_governance_edit_does_not_change_the_engine_hash(client):
    before = client.get("/api/policy").json()["hash"]
    assert apply(client, LIMIT_UP, MEERA).status_code == 200
    assert client.get("/api/policy").json()["hash"] == before  # approvals and recorded runs key on this
    entry = log(client)[0]
    assert entry["hash_before"] != entry["hash_after"]  # the log's own hash does include governance


def test_losing_every_approver_is_invalid():
    with pytest.raises(PolicyInvalid) as exc:  # removing the head and the manager would leave nobody who can approve
        policy.save_overrides({"governance": {"members": {"meera": None, "arjun": None}}})
    assert "approve" in exc.value.problem and not policy.local_path().exists()
    with pytest.raises(PolicyInvalid):  # a limit on a section that does not exist
        policy.save_overrides({"governance": {"limits": {"bad": {"role": "manager", "path": "nope", "max_abs_change": 1}}}})


def test_unknown_actor_is_rejected(client):
    res = client.post("/api/policy/propose", json={"prompt": TREATS_UP}, headers={"X-Acting-As": "mallory"})
    assert res.status_code == 422 and res.json()["code"] == "unknown_actor"
    assert client.get("/api/policy", headers={"X-Acting-As": "mallory"}).json()["acting"]["id"] == "meera"  # reads fall back to the owner


def test_no_header_acts_as_the_head(client):
    res = client.put("/api/policy", json={"research": {"demand_min": 0.5}})
    assert res.status_code == 200 and log(client)[0]["actor"]["id"] == "meera"


# ---------- undo ----------


def test_undo_restores_the_previous_values(client):
    first = apply(client, TREATS_UP, MEERA).json()["change"]
    res = client.post(f"/api/policy/changes/{first['id']}/undo", headers=MEERA)
    assert res.status_code == 200 and res.json()["change"]["source"] == "undo" and target() == 35
    assert not policy.local_path().exists()  # back to the defaults: no override left
    entries = {e["id"]: e for e in log(client)}
    assert entries[first["id"]]["status"] == "undone" and entries[first["id"]]["undone_by"] == res.json()["change"]["id"]
    undo = entries[res.json()["change"]["id"]]
    assert undo["status"] == "applied" and undo["undo_of"] == first["id"] and undo["diff"][0]["before"] == 37 and undo["diff"][0]["after"] == 35
    assert client.post(f"/api/policy/changes/{first['id']}/undo", headers=MEERA).status_code == 409  # already undone


def test_undo_goes_through_permissions(client):
    first = apply(client, "Cut the target margin on toys by 3 points", MEERA).json()["change"]  # 3 pp, by the head
    res = client.post(f"/api/policy/changes/{first['id']}/undo", headers=ARJUN)  # reversing 3 pp is over a manager's limit
    assert res.status_code == 202 and res.json()["change"]["status"] == "pending_approval" and target("toys") == 37
    assert log(client)[-1]["status"] == "applied"  # the original stays applied until the undo is approved
    undo_id = res.json()["change"]["id"]
    assert client.post(f"/api/policy/changes/{undo_id}/approve", headers=MEERA).status_code == 200
    assert target("toys") == 40 and {e["id"]: e for e in log(client)}[first["id"]]["status"] == "undone"
    analyst = apply(client, TREATS_UP, MEERA).json()["change"]
    assert client.post(f"/api/policy/changes/{analyst['id']}/undo", headers=PRIYA).status_code == 403


def test_undo_of_an_added_row_removes_it(client):
    res = client.put("/api/policy", json={"margins": {"categories": {"pet toys": {"target_pct": 41, "min_pct": 30, "payment_terms_days": 30}}}}, headers=MEERA)
    change = res.json()["change"]
    assert "pet toys" in policy.get().margins.categories and change["diff"][0]["before"] is None
    assert client.post(f"/api/policy/changes/{change['id']}/undo", headers=MEERA).status_code == 200
    assert "pet toys" not in policy.get().margins.categories


def test_apply_twice_and_discard(client):
    pre = propose(client, TREATS_UP)
    assert client.post(f"/api/policy/changes/{pre['id']}/discard").json() == {"ok": True}
    assert client.post(f"/api/policy/changes/{pre['id']}/apply", headers=MEERA).status_code == 404
    done = apply(client, TREATS_UP).json()["change"]
    assert client.post(f"/api/policy/changes/{done['id']}/apply", headers=MEERA).status_code == 409
    assert client.post(f"/api/policy/changes/{done['id']}/discard").status_code == 409


def test_a_preview_applied_after_the_playbook_moved_is_planned_again(client):
    pre = propose(client, TREATS_UP)  # 35 -> 37
    client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": 33}}}}, headers=MEERA)
    res = client.post(f"/api/policy/changes/{pre['id']}/apply", headers=MEERA)
    assert res.status_code == 200 and target() == 37  # the stored edit is an absolute value, re-planned on the playbook as it is now
    assert res.json()["change"]["diff"][0]["before"] == 33  # and the log records the value it really replaced


def test_a_preview_that_no_longer_validates_is_refused_and_logged(client):
    pre = propose(client, TREATS_UP)  # 35 -> 37 is fine while min_pct is 28 ...
    client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": 60, "min_pct": 50}}}}, headers=MEERA)
    pre2 = propose(client, "Cut the target margin on treats by 20 points")  # 60 -> 40: below min_pct 50
    assert pre2["status"] == "invalid" and pre2["error"]["code"] == "policy_invalid"
    client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": 60, "min_pct": 28}}}}, headers=MEERA)
    cut = propose(client, "Cut the target margin on treats by 20 points")
    assert cut["status"] == "ready"
    client.put("/api/policy", json={"margins": {"categories": {"treats": {"min_pct": 45}}}}, headers=MEERA)  # the playbook moves under the preview
    res = client.post(f"/api/policy/changes/{cut['id']}/apply", headers=MEERA)
    assert res.status_code == 403 and "No longer valid" in res.json()["cause"] and target() == 60
    assert log(client)[0]["status"] == "refused" and pre["status"] == "ready"


# ---------- the form ----------


def test_form_edits_are_permission_checked_and_logged(client):
    ok = client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": 36}}}}, headers=ARJUN)
    assert ok.status_code == 200 and ok.json()["change"]["source"] == "form" and target() == 36
    over = client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": 40}}}}, headers=ARJUN)  # +4 pp
    assert over.status_code == 202 and over.json()["change"]["status"] == "pending_approval" and target() == 36
    assert over.json()["policy"]["margins"]["categories"]["treats"]["target_pct"] == 36  # the response shows the playbook as it still is
    refused = client.put("/api/policy", json={"research": {"demand_min": 0.5}}, headers=PRIYA)
    assert refused.status_code == 403 and refused.json()["code"] == "change_refused" and policy.get().research.demand_min == 0.4
    entries = log(client)
    assert [(e["source"], e["status"], e["actor"]["id"]) for e in entries] == [("form", "refused", "priya"), ("form", "pending_approval", "arjun"), ("form", "applied", "arjun")]
    assert entries[2]["prompt"] is None and entries[0]["diff"][0]["path"] == "research.demand_min" and "cannot apply" in entries[0]["reason"]


def test_form_validation_errors_are_422_and_not_logged(client):
    res = client.put("/api/policy", json={"research": {"demand_min": 7}}, headers=MEERA)
    assert res.status_code == 422 and res.json()["path"] == "research.demand_min"
    assert log(client) == []


def test_form_noop_is_not_logged(client):
    res = client.put("/api/policy", json={"research": {"demand_min": 0.4}}, headers=MEERA)
    assert res.status_code == 200 and "change" not in res.json() and log(client) == []


def test_reset_is_checked_and_logged(client):
    client.put("/api/policy", json={"research": {"demand_min": 0.5}}, headers=MEERA)
    assert client.post("/api/policy/reset", json={"section": "research"}, headers=ARJUN).status_code == 403  # research is not a manager section
    assert policy.get().research.demand_min == 0.5
    res = client.post("/api/policy/reset", json={"section": "research"}, headers=MEERA)
    assert res.status_code == 200 and res.json()["change"]["source"] == "reset" and policy.get().research.demand_min == 0.4
    assert [e["source"] for e in log(client)][:2] == ["reset", "reset"]  # the refused attempt and the reset


def test_log_is_newest_first_and_durable_in_sqlite(client):
    apply(client, TREATS_UP)
    apply(client, FLOOR)
    prompts = [e["prompt"] for e in log(client)]
    assert prompts == [FLOOR, TREATS_UP]
    assert [r["prompt"] for r in store.list_changes("", 10)] == prompts  # what GET reads is the table, not memory


# ---------- free-form prompts on a replay deploy ----------


def replay(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")


def test_visitors_are_isolated_on_a_replay_deploy(client, monkeypatch):
    replay(monkeypatch)
    a, b = {"X-Visitor-Id": "visitor-aaaaaaaa", **MEERA}, {"X-Visitor-Id": "visitor-bbbbbbbb", **MEERA}
    base_hash = client.get("/api/policy", headers=a).json()["hash"]
    snap = client.get("/api/policy", headers=a).json()
    assert snap["scope"] == "visitor" and snap["editable"] is True

    pre = propose(client, TREATS_UP, a)
    res = client.post(f"/api/policy/changes/{pre['id']}/apply", headers=a)
    assert res.status_code == 200 and res.json()["policy"]["margins"]["categories"]["treats"]["target_pct"] == 37

    assert client.get("/api/policy", headers=a).json()["policy"]["margins"]["categories"]["treats"]["target_pct"] == 37
    assert [e["status"] for e in client.get("/api/policy/changes", headers=a).json()["changes"]] == ["applied"]
    # another visitor, same address: their own untouched playbook and an empty log, and they cannot reach A's change
    other = client.get("/api/policy", headers=b).json()
    assert other["policy"]["margins"]["categories"]["treats"]["target_pct"] == 35 and other["hash"] == base_hash and other["overridden_paths"] == []
    assert client.get("/api/policy/changes", headers=b).json()["changes"] == []
    assert client.post(f"/api/policy/changes/{res.json()['change']['id']}/undo", headers=b).status_code == 404
    # the recorded replay: engine playbook, metrics and the file on disk are untouched
    assert policy.get().margins.categories["treats"].target_pct == 35 and not policy.local_path().exists()
    assert client.get("/api/mode").json()["policy_hash"] == base_hash
    # and a visitor's undo works in their own sandbox
    assert client.post(f"/api/policy/changes/{res.json()['change']['id']}/undo", headers=a).status_code == 200
    assert client.get("/api/policy", headers=a).json()["overridden_paths"] == []


def test_visitor_scope_is_per_address_and_id(monkeypatch):
    replay(monkeypatch)

    class Req:
        def __init__(self, ip, vid):
            self.headers, self.client = ({"x-visitor-id": vid} if vid else {}), type("C", (), {"host": ip})()

    k1, k2, k3, k4 = rules.visitor_key(Req("1.1.1.1", "abc12345")), rules.visitor_key(Req("1.1.1.1", "abc99999")), rules.visitor_key(Req("2.2.2.2", "abc12345")), rules.visitor_key(Req("1.1.1.1", ""))
    assert len({k1, k2, k3, k4}) == 4 and all(len(k) == 16 for k in (k1, k2, k3, k4))
    assert rules.visitor_key(Req("1.1.1.1", "abc12345")) == k1
    monkeypatch.setattr(settings, "model_mode", "mock")
    assert rules.visitor_key(Req("1.1.1.1", "abc12345")) == ""  # locally there is one real playbook


def test_replay_form_edits_are_sandboxed_too(client, monkeypatch):
    replay(monkeypatch)
    a, b = {"X-Visitor-Id": "visitor-aaaaaaaa"}, {"X-Visitor-Id": "visitor-bbbbbbbb"}
    assert client.put("/api/policy", json={"research": {"demand_min": 0.6}}, headers=a).status_code == 200
    assert client.get("/api/policy", headers=a).json()["policy"]["research"]["demand_min"] == 0.6
    assert client.get("/api/policy", headers=b).json()["policy"]["research"]["demand_min"] == 0.4
    assert policy.get().research.demand_min == 0.4
    assert client.post("/api/policy/reset", json={}, headers=a).json()["overridden_paths"] == []


def test_visitor_log_is_capped_and_pending_requests_survive(client, monkeypatch):
    replay(monkeypatch)
    monkeypatch.setattr(settings, "rules_max_changes_per_visitor", 3)
    h = {"X-Visitor-Id": "visitor-aaaaaaaa", **ARJUN}
    pending = client.post(f"/api/policy/changes/{propose(client, TOYS_DOWN, h)['id']}/apply", headers=h).json()["change"]["id"]
    for v in (36, 35, 34, 33, 32):
        assert client.put("/api/policy", json={"margins": {"categories": {"treats": {"target_pct": v}}}}, headers=h).status_code == 200
    entries = client.get("/api/policy/changes", headers=h).json()["changes"]
    assert len(entries) == 4 and entries[-1]["id"] == pending  # three settled entries kept, plus the open request
    assert [e["diff"][0]["after"] for e in entries[:3]] == [32, 33, 34]


def test_visitor_sandboxes_are_capped_and_expire(monkeypatch):
    replay(monkeypatch)
    monkeypatch.setattr(settings, "rules_max_visitors", 2)
    for v in ("v1", "v2", "v3"):
        store.set_visitor_overrides(v, {"research": {"demand_min": 0.5}})
        store.save_change(v, f"chg_{v}", store.now_iso(), "applied", {"id": f"chg_{v}"})
        rules._commit(v, {"research": {"demand_min": 0.5}})
    assert store.get_visitor_overrides("v1") == {} and store.list_changes("v1", 10) == []  # the least recently active went first
    assert store.get_visitor_overrides("v3") and store.list_changes("v3", 10)


def test_free_form_in_replay_needs_the_public_live_budget(client, monkeypatch):
    replay(monkeypatch)
    h = {"X-Visitor-Id": "visitor-aaaaaaaa", **MEERA}
    res = client.post("/api/policy/propose", json={"prompt": "set minimum demand to 0.5"}, headers=h)
    assert res.status_code == 422 and res.json()["code"] == "rule_prompt_unavailable" and res.json()["fix"]
    assert propose(client, TREATS_UP, h)["status"] == "ready"  # examples need nothing


def test_free_form_in_replay_goes_through_the_public_budget(client, monkeypatch):
    replay(monkeypatch)
    monkeypatch.setattr(settings, "model_api_key", "test-key")
    monkeypatch.setattr(settings, "public_live_budget_usd", 5.0)
    monkeypatch.setattr(settings, "public_live_per_ip_usd", 0.5)
    monkeypatch.setattr(settings, "public_live_features", "rules")
    seen = {}

    async def fake_live(stage, messages, *, model, schema, provider, effort, max_tokens):
        seen["mode"], seen["ctx"] = llm.resolve_mode(stage), public_live.current()
        text = messages[-1]["content"]
        assert "margins.categories.treats.target_pct" in text and "set minimum demand to 0.5" in text  # the vocabulary is in the prompt
        cost = ledger.record("muse-spark-1.3", {"input_tokens": 1000, "output_tokens": 50})
        meter = llm._Meter("muse-spark-1.3")
        meter.input, meter.output, meter.cost = 1000, 50, cost
        parsed = schema(edits=[rules.RuleEdit(path="research.demand_min", number=0.5)])
        return parsed.model_dump_json(), parsed, "muse-spark-1.3", meter

    monkeypatch.setattr(llm, "_live", fake_live)
    h = {"X-Visitor-Id": "visitor-aaaaaaaa", **MEERA}
    pre = propose(client, "set minimum demand to 0.5", h)
    assert pre["status"] == "ready" and pre["translator"] == "model" and pre["changes"][0]["after"] == 0.5
    assert seen["mode"] == "live" and seen["ctx"].feature == "rules"
    assert public_live.spent_total() > 0  # charged to the public budget
    assert client.post(f"/api/policy/changes/{pre['id']}/apply", headers=h).status_code == 200
    assert policy.get().research.demand_min == 0.4  # the visitor's sandbox, not the recorded playbook
    # budget gone: a clear 429, and examples still work
    public_live.charge(sandbox.ip_key("testclient"), 10)
    res = client.post("/api/policy/propose", json={"prompt": "set minimum demand to 0.6"}, headers=h)
    assert res.status_code == 429 and res.json()["code"] == "public_budget_exhausted"
    assert propose(client, TREATS_UP, h)["status"] == "ready"


def test_rules_is_a_public_live_feature(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "public_live_budget_usd", 1.0)
    monkeypatch.setattr(settings, "public_live_features", "byo, rules, nonsense")
    assert public_live.features() == {"byo", "rules"} and public_live.enabled("rules") and not public_live.enabled("copilot")


def test_live_mode_free_form_needs_the_demo_key(client, monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "demo_key", "secret")

    async def fake_live(stage, messages, *, model, schema, provider, effort, max_tokens):
        parsed = schema(edits=[rules.RuleEdit(path="research.demand_min", number=0.5)])
        return parsed.model_dump_json(), parsed, "muse-spark-1.3", llm._Meter("muse-spark-1.3")

    monkeypatch.setattr(llm, "_live", fake_live)
    denied = client.post("/api/policy/propose", json={"prompt": "set minimum demand to 0.5"})
    assert denied.status_code == 403 and denied.json()["code"] == "demo_key_required"
    ok = client.post("/api/policy/propose", json={"prompt": "set minimum demand to 0.5"}, headers={"X-Demo-Key": "secret"})
    assert ok.status_code == 200 and ok.json()["translator"] == "model"


# ---------- units ----------


def test_governance_decide_units():
    pol = policy.get()
    meera, arjun = governance.actor_for(pol, "meera"), governance.actor_for(pol, "arjun")

    def line(path, before, after, unit="%"):
        return {"keys": path.split("."), "label": path, "unit": unit, "before": before, "after": after}

    assert governance.decide(pol, arjun, [line("margins.categories.treats.target_pct", 35, 37)]).action == "apply"
    assert governance.decide(pol, arjun, [line("margins.categories.treats.target_pct", 35, 37.5)]).action == "request_approval"
    assert governance.decide(pol, arjun, [line("margins.categories.treats.payment_terms_days", 21, 30, "days")]).action == "apply"  # the limit is in pp
    assert governance.decide(pol, arjun, [line("margins.categories.pet toys", None, {"target_pct": 41})]).action == "request_approval"
    assert governance.decide(pol, arjun, [line("research.demand_min", 0.4, 0.5, "")]).action == "refuse"
    assert governance.decide(pol, meera, [line("research.demand_min", 0.4, 0.5, ""), line("governance.roles.manager.can_approve", False, True, "")]).action == "apply"


def test_diff_and_reverse_round_trip():
    now = policy.get().model_dump(mode="json")
    new = policy.get().model_dump(mode="json")
    new["margins"]["categories"]["treats"]["target_pct"] = 36
    new["margins"]["categories"]["pet toys"] = {"target_pct": 41, "min_pct": 30, "payment_terms_days": 30}
    diff = rules.diff_dumps(now, new)
    assert {d["path"] for d in diff} == {"margins.categories.treats.target_pct", "margins.categories.pet toys"}
    # applying the change and then its reverse partial gives back the original playbook
    changed, over = policy.plan_partial({"margins": {"categories": {"treats": {"target_pct": 36}, "pet toys": new["margins"]["categories"]["pet toys"]}}}, {})
    assert changed.model_dump(mode="json") == new
    back, back_over = policy.plan_partial(rules.reverse_partial(diff), over)
    assert back.model_dump(mode="json") == now and back_over == {}
