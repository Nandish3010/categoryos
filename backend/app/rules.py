"""Playbook rules written as prompts, stored as structured data, with roles and a change log.

The playbook stays structured data. A plain-English prompt only FILLS it: the model (or, in mock, a deterministic translator)
turns the prompt into edits of settings that already exist, Python builds the partial override from them, dry-runs it through
the playbook's own validation and shows a before/after preview whose numbers come from the validated playbook, never from model
text. Applying goes through the same permission check as the form (``governance.decide``) and every attempt, refused ones
included, is logged in the ``policy_changes`` table.

Whose playbook: locally (mock or live) a change writes config/policy.local.yaml as before. On a replay deploy it writes the
visitor's own overrides (``visitor_playbooks``) so nobody else, and no recorded run, is affected; see ``visitor_key``.

The sync half (everything under "service") runs in a worker thread under one lock, so a plan, its permission check and its
write cannot interleave with another request's."""

import difflib
import hashlib
import math
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import governance, llm, policy, public_live, store
from app.config import settings
from app.errors import (
    ChangeNotFound,
    ChangeNotPending,
    ChangeRefused,
    ChangeStale,
    PolicyInvalid,
    RulePathUnknown,
    RulesQuota,
    RuleUnavailable,
    UndoConflict,
)
from app.governance import Actor
from app.policy import Policy

STAGE = "rules"
MAX_EDITS = 8
MAX_REFUSED_EVENTS = 5
DRAFT_TTL = timedelta(hours=1)
Source = Literal["prompt", "form", "undo", "reset"]

# Example prompts shown as clickable suggestions. Each has a recorded translation in fixtures/mock/rules, so it works with no model.
EXAMPLES: list[dict[str, str]] = [
    {"prompt": "Raise the target margin on treats by 2 points", "note": "Within a manager's 2 pp limit: applies"},
    {"prompt": "Cut the target margin on toys by 5 points", "note": "Over a manager's limit: waits for the head"},
    {"prompt": "Never sell liquidation stock below 70% of cost", "note": "Inventory health, no limit"},
    {"prompt": "Let managers change margins by up to 3 points at a time", "note": "Governance: head only"},
    {"prompt": "Set the target margin on treats to 120%", "note": "Out of range: the playbook says no"},
]


# ---------- what a model may say ----------


class RuleEdit(BaseModel):
    path: str = Field(description="Dotted path of an existing playbook setting, copied from the list")
    op: Literal["set", "add"] = Field(default="set", description="set: number is the new value. add: number is a signed amount added to the current value (use for 'by N')")
    number: float | None = None
    boolean: bool | None = None
    choice: str | None = None


class RuleProposal(BaseModel):
    edits: list[RuleEdit]
    unmapped_reason: str | None = None


# ---------- vocabulary: which settings exist and what they mean ----------


def describe(keys: list[str]) -> dict[str, Any]:
    """Label, unit, kind and the stages that read the setting at ``keys``, from the playbook's schema hints. Dict-table cells
    (``margins.categories.treats.target_pct``) borrow the table's column."""
    hints = policy.schema_hints()
    for n in range(len(keys), 0, -1):
        h = hints.get(".".join(keys[:n]))
        if h is not None:
            break
    else:
        return {"label": ".".join(keys), "unit": None, "used_in": [], "kind": None}
    rest = keys[n:]
    base = {"unit": h.get("unit"), "used_in": h.get("used_in") or [], "kind": h.get("kind"), "min": h.get("min"), "max": h.get("max"), "options": h.get("options")}
    if not rest:
        return {"label": h["label"], **base}
    if h.get("kind") == "table" and h.get("shape") == "dict":
        cols = {c["key"]: c for c in h.get("columns", [])}
        row = rest[0]
        col = cols.get(rest[1]) if len(rest) > 1 else cols.get("value")
        if col is not None and len(rest) <= 2:
            name = col.get("label") or policy_humanize(rest[-1])
            label = f"{h['label']}: {row}" + (f" / {name}" if len(rest) > 1 else "")
            return {"label": label, "unit": col.get("unit"), "used_in": col.get("used_in") or base["used_in"], "kind": col.get("kind"),
                    "min": col.get("min"), "max": col.get("max"), "options": col.get("options")}
        return {"label": f"{h['label']}: {' / '.join(rest)}", **base, "kind": "table", "unit": None}
    return {"label": f"{h['label']}: {' / '.join(rest)}", **base}


def policy_humanize(key: str) -> str:
    s = key.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def settable_leaves(dump: dict[str, Any]) -> list[dict[str, Any]]:
    """Every single setting a rule may set: a number, a switch or a choice, including cells of existing rows in tables.
    Free text, lists and whole rows are not on this list, so a prompt can never write them."""
    out: list[dict[str, Any]] = []

    def walk(node: Any, keys: list[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, [*keys, k])
            return
        if not keys or keys == ["version"]:
            return
        kind = "bool" if isinstance(node, bool) else "number" if isinstance(node, (int, float)) else None
        meta = describe(keys)
        if kind is None and isinstance(node, str) and meta["kind"] == "enum":
            kind = "enum"
        if kind is None:
            return
        out.append({"keys": keys, "path": ".".join(keys), "kind": kind, "current": node, "label": meta["label"], "unit": meta["unit"],
                    "min": meta.get("min"), "max": meta.get("max"), "options": meta.get("options"), "used_in": meta["used_in"]})

    walk(dump, [])
    return out


def resolve_keys(dump: dict[str, Any], path: str) -> list[str]:
    """Walk a dotted path through the playbook as it is now. Row names may contain dots, so the longest matching key wins.
    Only a path that ends on one existing setting resolves; anything else raises RulePathUnknown."""
    node: Any = dump
    keys: list[str] = []
    rest = path.strip()
    while rest:
        if not isinstance(node, dict):
            break
        cands = [k for k in node if rest == k or rest.startswith(k + ".")]
        if not cands:
            break
        k = max(cands, key=len)
        keys.append(k)
        node = node[k]
        rest = rest[len(k) + 1 :]
    else:
        if keys and not isinstance(node, (dict, list)) and keys != ["version"]:
            return keys
        whole = "names a whole section or list, not one setting" if keys else "is empty"
        raise RulePathUnknown(path, cause=f"The path {whole}; a rule sets a single number, switch or choice", fix="Name one setting, for example margins.categories.treats.target_pct")
    near = difflib.get_close_matches(path, [x["path"] for x in settable_leaves(dump)], n=3, cutoff=0.6)
    raise RulePathUnknown(path, cause="No such setting exists in the playbook", fix=("Did you mean " + ", ".join(near) + "?") if near else "Pick a setting shown in the playbook")


def _set_nested(target: dict[str, Any], keys: list[str], value: Any) -> None:
    node = target
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def edits_to_partial(dump: dict[str, Any], edits: list[RuleEdit]) -> dict[str, Any]:
    """The partial override the edits mean, in the shape ``save_overrides`` takes. Unknown paths and wrongly typed values raise."""
    if len(edits) > MAX_EDITS:
        raise PolicyInvalid(f"{len(edits)} edits in one rule is too many", cause=f"A rule changes at most {MAX_EDITS} settings", fix="Split it into smaller rules")
    partial: dict[str, Any] = {}
    for e in edits:
        keys = resolve_keys(dump, e.path)
        cur: Any = dump
        for k in keys:
            cur = cur[k]
        meta = describe(keys)
        given = {"number": e.number, "boolean": e.boolean, "choice": e.choice}
        used = [n for n, v in given.items() if v is not None]
        if e.number is not None and not math.isfinite(e.number):
            raise PolicyInvalid(f"{e.path}: not a finite number", cause="NaN and infinity are not valid playbook values", fix="Rephrase the rule with an ordinary number", errors=[{"path": e.path, "message": "not a finite number"}])
        want = "boolean" if isinstance(cur, bool) else "number" if isinstance(cur, (int, float)) else "choice" if isinstance(cur, str) and meta["kind"] == "enum" else None
        if want is None:
            raise RulePathUnknown(e.path, cause="This setting is free text or a list; a rule can only set a number, a switch or a choice", fix="Edit it in the form below")
        if used != [want]:
            msg = f"{meta['label']} needs a {want}"
            raise PolicyInvalid(f"{e.path}: {msg}", cause="The translation gave a value of the wrong type for this setting", fix="Rephrase the rule with the value you mean", errors=[{"path": e.path, "message": msg}])
        value = given[want]
        if e.op == "add":
            if want != "number":
                raise PolicyInvalid(f"{e.path}: {meta['label']} cannot be changed by an amount", cause="Only numbers can be raised or lowered by an amount", fix="Say the value you want instead", errors=[{"path": e.path, "message": "not a number"}])
            value = round(cur + value, 6)  # relative edits are resolved here, against the playbook as it is when the preview is built
        _set_nested(partial, keys, value)
    return partial


# ---------- diff and the log record ----------


def diff_dumps(before: Any, after: Any, keys: list[str] | None = None) -> list[dict[str, Any]]:
    """Changed settings, one line each. Dicts recurse (so a table cell is its own line); lists and scalars are compared whole; a row
    that appears or disappears is one line with the whole row as its value."""
    keys = keys or []
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[dict[str, Any]] = []
        for k in [*before, *[k for k in after if k not in before]]:
            if k not in before:
                out.extend(diff_dumps(None, after[k], [*keys, k]))
            elif k not in after:
                out.extend(diff_dumps(before[k], None, [*keys, k]))
            else:
                out.extend(diff_dumps(before[k], after[k], [*keys, k]))
        return out
    if before == after:
        return []
    meta = describe(keys)
    return [{"keys": keys, "path": ".".join(keys), "label": meta["label"], "unit": meta["unit"], "used_in": meta["used_in"], "before": before, "after": after}]


def reverse_partial(diff: list[dict[str, Any]]) -> dict[str, Any]:
    """The partial that puts every changed setting back to its previous value (a row that was added is removed)."""
    partial: dict[str, Any] = {}
    for line in diff:
        _set_nested(partial, line["keys"], line["before"])
    return partial


class Change(BaseModel):
    id: str
    at: str
    decided_at: str | None = None
    actor: dict[str, str]
    source: Source
    prompt: str | None = None
    translator: str | None = None
    partial: dict[str, Any] | None = None
    reset_section: str | None = None
    diff: list[dict[str, Any]] = []
    status: Literal["proposed", "applied", "pending_approval", "refused", "rejected", "undone"]
    reason: str | None = None
    approver: dict[str, str] | None = None
    hash_before: str | None = None
    hash_after: str | None = None
    undo_of: str | None = None
    undone_by: str | None = None
    events: list[dict[str, Any]] = []


def _now() -> str:
    return store.now_iso()


def _new_id() -> str:
    return "chg_" + secrets.token_hex(5)


# ---------- translator: prompt -> RuleProposal ----------


def _norm(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def task_for(prompt: str) -> str:
    return "propose_" + hashlib.sha1(_norm(prompt).encode()).hexdigest()[:10]


def has_fixture(prompt: str) -> bool:
    task = task_for(prompt)
    return any(llm.fixture_path(kind, STAGE, task).exists() for kind in ("mock", "golden"))


_STOP = {"the", "and", "for", "set", "per", "with", "that", "this", "from", "into", "than", "not", "any", "all", "are", "can"}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def mock_translate(prompt: str, leaves: list[dict[str, Any]]) -> RuleProposal:
    """Deterministic stand-in for the model (mock mode and tests): finds the one numeric setting whose label words, and row name
    for a table cell, all appear in the prompt, and reads the number. Understands "by N" (raise adds, cut/lower/reduce subtract)."""
    text = prompt.lower()
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    words = {_stem(w) for w in re.findall(r"[a-z]+", text)}
    best: tuple[int, dict[str, Any]] | None = None
    for leaf in leaves:
        if leaf["kind"] != "number":
            continue
        label = leaf["label"].split(": ", 1)[-1]  # a table cell: "<row> / <column>"
        need = {_stem(w) for w in re.findall(r"[a-z]+", label.lower().replace("/", " ")) if len(w) > 2 and w not in _STOP}
        if need and need <= words and (best is None or len(need) > best[0]):
            best = (len(need), leaf)
    if not nums or best is None:
        return RuleProposal(edits=[], unmapped_reason="I could not match that to a playbook setting and a number")
    leaf, value = best[1], float(nums[0])
    if re.search(r"\bby\b", text):
        down = bool(words & {"cut", "lower", "reduce", "decrease", "drop", "less", "trim"})
        return RuleProposal(edits=[RuleEdit(path=leaf["path"], op="add", number=-value if down else value)])
    return RuleProposal(edits=[RuleEdit(path=leaf["path"], number=round(value, 6))])


async def translate(prompt: str, pol: Policy, *, public_ip: str | None = None) -> tuple[RuleProposal, str]:
    """(proposal, where it came from). A recorded example is served from its fixture in mock and replay (free). Anything else: the
    deterministic translator in mock; in replay only through the public live budget (``public_ip``); in live the model."""
    from app import prompts_rules  # late: prompts reads the playbook

    leaves = settable_leaves(pol.model_dump(mode="json"))
    msgs = prompts_rules.messages(leaves, prompt)
    mode = llm.resolve_mode(STAGE)
    task = task_for(prompt)
    if mode in ("mock", "replay") and has_fixture(prompt):
        res = await llm.call(STAGE, msgs, task=task, schema=RuleProposal)
        assert isinstance(res.parsed, RuleProposal)
        return res.parsed, "recorded example"
    if mode == "mock":
        return mock_translate(prompt, leaves), "mock translator"
    if mode == "replay" and not public_ip:
        raise RuleUnavailable()
    ctx = public_live.use(public_live.PublicCtx("rules", public_ip)) if public_ip else public_live.use(None)
    with ctx:
        res = await llm.call(STAGE, msgs, task=task, schema=RuleProposal, max_tokens=1200)
    assert isinstance(res.parsed, RuleProposal)
    return res.parsed, "model"


# ---------- service (sync, one lock) ----------

_lock = threading.RLock()


def _base(visitor: str) -> dict[str, Any]:
    return policy.load().overrides if not visitor else store.get_visitor_overrides(visitor)


def current_policy(visitor: str) -> Policy:
    return policy.load().policy if not visitor else policy.effective_with(store.get_visitor_overrides(visitor))


def _commit(visitor: str, over: dict[str, Any]) -> None:
    if not visitor:
        policy.commit_overrides(over)
        return
    store.set_visitor_overrides(visitor, over)
    _expire(visitor)


def _plan(ch: Change, base: dict[str, Any]) -> tuple[Policy, dict[str, Any]]:
    if ch.source == "reset":
        return policy.plan_reset(ch.reset_section, base)
    return policy.plan_partial(ch.partial or {}, base)


def _save(visitor: str, ch: Change, *, bump: bool = False) -> Change:
    store.save_change(visitor, ch.id, ch.at, ch.status, ch.model_dump(), bump=bump)
    draft_cutoff = (datetime.now(UTC) - DRAFT_TTL).isoformat(timespec="milliseconds")
    store.trim_changes(visitor, settings.rules_max_changes_per_visitor if visitor else settings.rules_max_local_changes, draft_cutoff, settings.rules_max_drafts)
    if visitor:
        _expire(visitor)
    return ch


def _expire(visitor: str) -> None:
    cutoff = (datetime.now(UTC) - timedelta(hours=settings.upload_ttl_hours)).isoformat(timespec="milliseconds")
    store.expire_visitors(cutoff, settings.rules_max_visitors)


def _event(ch: Change, actor: Actor, action: str, reason: str | None = None) -> None:
    ch.events.append({"at": _now(), "actor": actor.ref(), "action": action, "reason": reason})
    refused = [i for i, e in enumerate(ch.events) if e["action"].endswith("_refused")]
    for i in reversed(refused[:-MAX_REFUSED_EVENTS]):  # a hammered request keeps only its latest few refused attempts
        del ch.events[i]


def _finish(visitor: str, ch: Change, actor: Actor, status: str, reason: str | None) -> Change:
    ch.status = status  # type: ignore[assignment]
    ch.reason = reason
    ch.decided_at = _now()
    _event(ch, actor, status, reason)
    return _save(visitor, ch, bump=True)  # the log is ordered by when things were decided


def _refuse(ch: Change) -> ChangeRefused:
    return ChangeRefused("This change was refused", cause=ch.reason, change=ch.model_dump())


def _value_at(dump: Any, keys: list[str]) -> Any:
    for k in keys:
        if not isinstance(dump, dict) or k not in dump:
            return None
        dump = dump[k]
    return dump


def _anchors(visitor: str, diff: list[dict[str, Any]]) -> dict[str, Any]:
    """Baselines for the limited roles' cumulative drift: the last value set without a limit applying, else the committed default."""
    stored = store.get_anchors(visitor)
    defaults = policy.load().defaults.model_dump(mode="json")
    return {line["path"]: stored.get(line["path"], _value_at(defaults, line["keys"])) for line in diff}


def _move_anchors(visitor: str, pol: Policy, actor: Actor, diff: list[dict[str, Any]], *, approved: bool) -> None:
    """After a change is applied, every number set without a limit applying (by someone unlimited, or approved by one) becomes the
    new baseline."""
    fresh = {
        line["path"]: line["after"]
        for line in diff
        if isinstance(line["after"], (int, float)) and not isinstance(line["after"], bool) and (approved or not governance.limits_for(pol, actor, line))
    }
    store.set_anchors(visitor, fresh)


def _same_befores(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> bool:
    return {x["path"]: x["before"] for x in old} == {x["path"]: x["before"] for x in new}


def _settle(visitor: str, ch: Change, actor: Actor) -> Change:
    """Plan ``ch`` on the playbook as it is now, check what ``actor`` may do, then apply it, park it for approval or refuse it.
    The result is always logged."""
    ch.actor = actor.ref()
    base = _base(visitor)
    before = policy.effective_with(base)
    ch.hash_before = policy.full_digest(before)
    try:
        after, over = _plan(ch, base)
    except PolicyInvalid as exc:
        return _finish(visitor, ch, actor, "refused", f"No longer valid on the current playbook: {exc.problem}")
    draft = ch.diff if ch.source == "prompt" else []  # a preview's values were worked out against the playbook of that moment
    ch.diff = diff_dumps(before.model_dump(mode="json"), after.model_dump(mode="json"))
    if draft and not _same_befores(draft, ch.diff):
        store.delete_change(visitor, ch.id)
        raise ChangeStale(cause="A setting this rule changes has a different value now than when it was previewed")
    if not ch.diff:
        return _finish(visitor, ch, actor, "refused", "Nothing to change: the playbook already has these values")
    out = governance.decide(before, actor, ch.diff, _anchors(visitor, ch.diff))
    if out.action == "refuse":
        return _finish(visitor, ch, actor, "refused", out.reason)
    if out.action == "request_approval":
        if store.count_changes(visitor, "pending_approval") >= settings.rules_max_pending:
            raise RulesQuota(cause=f"{settings.rules_max_pending} requests are already waiting for approval")
        return _finish(visitor, ch, actor, "pending_approval", out.reason)
    _commit(visitor, over)
    _move_anchors(visitor, before, actor, ch.diff, approved=False)
    ch.hash_after = policy.full_digest(after)
    return _finish(visitor, ch, actor, "applied", None)


def _load(visitor: str, change_id: str) -> Change:
    raw = store.get_change(visitor, change_id)
    if raw is None:
        raise ChangeNotFound(change_id)
    return Change.model_validate(raw)


def _actor(visitor: str, member_id: str | None) -> Actor:
    return governance.actor_for(current_policy(visitor), member_id)


def build_preview(visitor: str, member_id: str | None, prompt: str, proposal: RuleProposal, translator: str) -> dict[str, Any]:
    """Dry run of a translated prompt: nothing is written to the playbook. A good preview is kept as a draft (status "proposed",
    not shown in the log) that Apply, Request approval or Discard then acts on, so the client cannot swap the change at apply time."""
    with _lock:
        pol = current_policy(visitor)
        actor = governance.actor_for(pol, member_id)
        base = {"prompt": prompt, "translator": translator, "actor": {**actor.ref(), "can_apply": actor.can_apply}, "changes": [], "outcome": None, "error": None, "id": None}
        if not proposal.edits:
            reason = (proposal.unmapped_reason or "").strip()[:200]
            msg = "I couldn't map this to a playbook setting." + (f" {reason}" if reason else "")
            return {**base, "status": "unmapped", "message": msg}
        dump = pol.model_dump(mode="json")
        try:
            partial = edits_to_partial(dump, proposal.edits)
            after, _ = policy.plan_partial(partial, _base(visitor))
        except (PolicyInvalid, RulePathUnknown) as exc:
            return {**base, "status": "invalid", "error": exc.to_dict(), "message": exc.problem}
        diff = diff_dumps(dump, after.model_dump(mode="json"))
        if not diff:
            return {**base, "status": "unchanged", "message": "The playbook already has these values; nothing to change."}
        outcome = governance.decide(pol, actor, diff, _anchors(visitor, diff))
        ch = Change(id=_new_id(), at=_now(), actor=actor.ref(), source="prompt", prompt=prompt, translator=translator, partial=partial, diff=diff,
                    status="proposed", hash_before=policy.full_digest(pol))
        _save(visitor, ch)
        return {**base, "status": "ready", "id": ch.id, "changes": diff, "outcome": outcome.to_dict()}


def apply_change(visitor: str, member_id: str | None, change_id: str) -> Change:
    with _lock:
        ch = _load(visitor, change_id)
        if ch.status != "proposed":
            raise ChangeNotPending(cause=f"This change is {ch.status.replace('_', ' ')}, not a preview waiting to be applied")
        out = _settle(visitor, ch, _actor(visitor, member_id))
        if out.status == "refused":
            raise _refuse(out)
        return out


def submit_form(visitor: str, member_id: str | None, partial: dict[str, Any]) -> Change | None:
    """A direct edit through the form (PUT /api/policy). Validation errors raise before anything is logged; a no-op returns None."""
    return _submit_direct(visitor, member_id, "form", partial, None)


def submit_reset(visitor: str, member_id: str | None, section: str | None) -> Change | None:
    return _submit_direct(visitor, member_id, "reset", None, section)


def _submit_direct(visitor: str, member_id: str | None, source: Source, partial: dict[str, Any] | None, section: str | None) -> Change | None:
    with _lock:
        actor = _actor(visitor, member_id)
        ch = Change(id=_new_id(), at=_now(), actor=actor.ref(), source=source, partial=partial, reset_section=section, status="proposed", translator="form")
        base = _base(visitor)
        before = policy.effective_with(base)
        after, _ = _plan(ch, base)  # PolicyInvalid here is a form validation error: 422, nothing written, nothing logged
        if not diff_dumps(before.model_dump(mode="json"), after.model_dump(mode="json")):
            return None
        out = _settle(visitor, ch, actor)
        if out.status == "refused":
            raise _refuse(out)
        return out


def _note_refused(visitor: str, ch: Change, actor: Actor, action: str, reason: str) -> ChangeRefused:
    """A refused approve/reject/undo of an existing change is recorded on that change; it keeps its status."""
    _event(ch, actor, f"{action}_refused", reason)
    _save(visitor, ch)
    return ChangeRefused(f"{actor.role_label} cannot {action} this change", cause=reason, change=ch.model_dump())


def approve_change(visitor: str, member_id: str | None, change_id: str) -> Change:
    with _lock:
        ch = _load(visitor, change_id)
        if ch.status != "pending_approval":
            raise ChangeNotPending(cause=f"This change is {ch.status.replace('_', ' ')}, not waiting for approval")
        actor = _actor(visitor, member_id)
        if not actor.can_approve:
            raise _note_refused(visitor, ch, actor, "approve", f"{actor.role_label} cannot approve changes; only a role with approval rights can")
        if actor.id == ch.actor["id"]:
            raise _note_refused(visitor, ch, actor, "approve", "Nobody can approve their own request")
        base = _base(visitor)
        before = policy.effective_with(base)
        try:
            after, over = _plan(ch, base)
        except PolicyInvalid as exc:
            raise _refuse(_finish(visitor, ch, actor, "refused", f"No longer valid when approved: {exc.problem}")) from exc
        diff = diff_dumps(before.model_dump(mode="json"), after.model_dump(mode="json"))
        if not _same_befores(ch.diff, diff):
            # closed, not left pending: its numbers were worked out against a playbook that no longer exists
            _finish(visitor, ch, actor, "rejected", "Stale: the playbook changed since this request was made")
            raise ChangeStale(cause="The playbook changed since this request was made, so it was closed", fix="Ask for the change again to get a fresh request")
        out = governance.decide(before, actor, diff, _anchors(visitor, diff))  # the approver must themselves be allowed to make this change
        if out.action != "apply":
            raise _note_refused(visitor, ch, actor, "approve", out.reason or "The approver may not make this change either")
        _commit(visitor, over)
        _move_anchors(visitor, before, actor, diff, approved=True)
        ch.diff, ch.hash_before, ch.hash_after, ch.approver = diff, policy.full_digest(before), policy.full_digest(after), actor.ref()
        done = _finish(visitor, ch, actor, "applied", ch.reason)
        if ch.undo_of:
            _mark_undone(visitor, ch.undo_of, ch.id, actor)
        return done


def reject_change(visitor: str, member_id: str | None, change_id: str) -> Change:
    with _lock:
        ch = _load(visitor, change_id)
        if ch.status != "pending_approval":
            raise ChangeNotPending(cause=f"This change is {ch.status.replace('_', ' ')}, not waiting for approval")
        actor = _actor(visitor, member_id)
        withdrawn = actor.id == ch.actor["id"]
        if not actor.can_approve and not withdrawn:
            raise _note_refused(visitor, ch, actor, "reject", f"{actor.role_label} cannot reject changes; only a role with approval rights or the requester can")
        ch.approver = actor.ref()
        return _finish(visitor, ch, actor, "rejected", "Withdrawn by the requester" if withdrawn else f"Rejected by {actor.name}")


def discard_change(visitor: str, change_id: str) -> None:
    with _lock:
        ch = _load(visitor, change_id)
        if ch.status != "proposed":
            raise ChangeNotPending(cause=f"This change is {ch.status.replace('_', ' ')}; only an unapplied preview can be discarded")
        store.delete_change(visitor, change_id)


def _mark_undone(visitor: str, original_id: str, by: str, actor: Actor) -> None:
    raw = store.get_change(visitor, original_id)
    if raw is None:
        return
    orig = Change.model_validate(raw)
    orig.status, orig.undone_by = "undone", by
    _event(orig, actor, "undone", None)
    _save(visitor, orig)


def _check_undo_conflicts(visitor: str, orig: Change) -> None:
    """Undo restores the old values, so it must not trample a later change: every setting has to still hold what ``orig`` set."""
    dump = current_policy(visitor).model_dump(mode="json")
    stale = [line for line in orig.diff if _value_at(dump, line["keys"]) != line["after"]]
    if not stale:
        return
    later = None
    for e in store.list_changes(visitor, 200):  # newest first
        if e["id"] == orig.id:
            break
        if e["status"] == "applied" and any(a["keys"][: len(b["keys"])] == b["keys"] or b["keys"][: len(a["keys"])] == a["keys"] for a in e["diff"] for b in stale):
            later = e
            break
    who = f"{later['id']} by {later['actor']['name']}" if later else "a later change"
    raise UndoConflict(cause=f"{stale[0]['label']} no longer holds the value this change set; {who} touched it", fix="Undo the later change first, or edit the setting in the form")


def undo_change(visitor: str, member_id: str | None, change_id: str) -> Change:
    """Put the previous values back. It is a new change (source "undo") that goes through the same permission check, so it can be
    refused or wait for approval like any other; the original becomes "undone" only once the undo has been applied."""
    with _lock:
        orig = _load(visitor, change_id)
        if orig.status != "applied":
            raise ChangeNotPending(cause=f"This change is {orig.status.replace('_', ' ')}; only an applied change can be undone")
        actor = _actor(visitor, member_id)
        for e in store.list_changes(visitor, 200):
            if e.get("undo_of") == orig.id and e["status"] in ("pending_approval", "applied"):
                raise ChangeNotPending(cause=f"{e['id']} already undoes this change ({e['status'].replace('_', ' ')})")
        _check_undo_conflicts(visitor, orig)
        ch = Change(id=_new_id(), at=_now(), actor=actor.ref(), source="undo", partial=reverse_partial(orig.diff), status="proposed", undo_of=orig.id,
                    prompt=f"Undo {orig.id}", translator="undo")
        out = _settle(visitor, ch, actor)
        if out.status == "refused":
            raise _refuse(out)
        if out.status == "applied":
            _mark_undone(visitor, orig.id, out.id, actor)
        return out


def list_log(visitor: str, member_id: str | None, limit: int = 100) -> dict[str, Any]:
    """The change log, newest first, each entry with what the acting member may do to it (the server re-checks on every action)."""
    pol = current_policy(visitor)
    actor = governance.actor_for(pol, member_id, lenient=True)
    rows = store.list_changes(visitor, limit)
    for r in rows:
        status = r["status"]
        pending = status == "pending_approval"
        own = r["actor"]["id"] == actor.id
        r["allowed"] = {
            "approve": pending and actor.can_approve and not own,
            "reject": pending and (actor.can_approve or own),
            "undo": status == "applied" and governance.may_touch(pol, actor, r["diff"]),
        }
    return {"changes": rows, "acting": actor.ref()}


def snapshot_for(visitor: str, member_id: str | None) -> dict[str, Any]:
    """GET /api/policy: the playbook this caller edits (their own sandbox on a replay deploy) and who they are acting as."""
    if visitor:
        snap = policy.snapshot(store.get_visitor_overrides(visitor), editable=True)
    else:
        snap = policy.snapshot()
    pol = current_policy(visitor)
    actor = governance.actor_for(pol, member_id, lenient=True)
    snap["scope"] = "visitor" if visitor else "global"
    snap["acting"] = {**actor.ref(), "role_label": actor.role_label, "can_apply": actor.can_apply, "can_approve": actor.can_approve}
    return snap


def visitor_key(request: Any) -> str:
    """Who owns the playbook edits of this request. Locally ("" ) the single real playbook. On a replay deploy a private sandbox keyed by
    the caller's address (the same hashed address the BYO sandbox and the public live budget use) and the random X-Visitor-Id the
    browser keeps, so two people behind one address do not share, and a made-up id from another address reaches nothing."""
    if settings.effective_mode != "replay":
        return ""
    from app import sandbox  # late: sandbox imports policy

    vid = re.sub(r"[^A-Za-z0-9_-]", "", request.headers.get("x-visitor-id", ""))[:64]
    return hashlib.sha256(f"{sandbox.ip_key(sandbox.client_ip(request))}:{vid}".encode()).hexdigest()[:16]
