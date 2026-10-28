"""Who may change which playbook rule. Pure functions over the playbook's ``governance`` section (members, roles, limits):
no I/O, no model. The acting member comes from the X-Acting-As header, a DEMO identity picker and not authentication.

``decide`` turns a list of changed settings into one of three outcomes for the acting member: apply now, ask for approval
(a numeric limit is exceeded), or refuse (the role may not apply, or not touch that section). Changing ``governance`` itself
is head-only whatever the roles say, so a manager cannot grant themselves more."""

from dataclasses import dataclass
from typing import Any, Literal

from app.errors import UnknownActor
from app.policy import Policy

HEAD = "head"
PERCENT_LIKE = {"pp", "%"}  # a limit written in percentage points also covers settings shown in %
Action = Literal["apply", "request_approval", "refuse"]


@dataclass(frozen=True)
class Actor:
    id: str
    name: str
    role: str
    role_label: str
    can_apply: bool
    can_approve: bool

    def ref(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "role": self.role}


@dataclass(frozen=True)
class Outcome:
    action: Action
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason}


def default_member_id(pol: Policy) -> str:
    """The playbook owner: the first head. Callers that send no X-Acting-As (scripts, older clients) act as this member."""
    for mid, m in pol.governance.members.items():
        if m.role == HEAD:
            return mid
    return next(iter(pol.governance.members))


def actor_for(pol: Policy, member_id: str | None, *, lenient: bool = False) -> Actor:
    """The acting member. Unknown ids raise UnknownActor, or with ``lenient`` (read-only views) fall back to the owner."""
    gov = pol.governance
    mid = member_id or default_member_id(pol)
    member = gov.members.get(mid)
    if member is None:
        if not lenient:
            raise UnknownActor(mid)
        mid = default_member_id(pol)
        member = gov.members[mid]
    rule = gov.roles[member.role]
    return Actor(mid, member.name, member.role, rule.label, rule.can_apply, rule.can_approve)


def covers(sections: list[str], keys: list[str]) -> bool:
    """True when ``*`` or one of the section paths contains the setting."""
    for sec in sections:
        if sec == "*":
            return True
        parts = sec.split(".")
        if keys[: len(parts)] == parts:
            return True
    return False


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: float) -> str:
    return f"{v:g}"


def decide(pol: Policy, actor: Actor, diff: list[dict[str, Any]]) -> Outcome:
    """What happens if ``actor`` applies this diff (lines carry keys, label, unit, before, after)."""
    gov = pol.governance
    rule = gov.roles[actor.role]
    if not rule.can_apply:
        return Outcome("refuse", f"{rule.label} can write a rule and see its preview but cannot apply it; ask a category manager or the head")
    for line in diff:
        if line["keys"][0] == "governance" and actor.role != HEAD:
            return Outcome("refuse", f"Only the head can change team members, roles and limits; {rule.label} cannot ({line['label']})")
        if not covers(rule.sections, line["keys"]):
            sections = ", ".join(rule.sections) or "none"
            return Outcome("refuse", f"{rule.label} may not change {line['keys'][0]} ({line['label']}); this role covers: {sections}")
    over: list[str] = []
    for lim in gov.limits.values():
        if lim.role != actor.role:
            continue
        prefix = lim.path.split(".")
        for line in diff:
            if line["keys"][: len(prefix)] != prefix:
                continue
            unit = line.get("unit") or ""
            if lim.unit and not (unit == lim.unit or (unit in PERCENT_LIKE and lim.unit in PERCENT_LIKE)):
                continue
            before, after = line["before"], line["after"]
            if _is_number(before) and _is_number(after):
                delta = abs(after - before)
                if delta > lim.max_abs_change + 1e-9:
                    u = f" {lim.unit}" if lim.unit else ""
                    over.append(f"{line['label']}: {rule.label.lower()} limit is {_num(lim.max_abs_change)}{u} per change; this change is {_num(round(delta, 6))}{u}")
            else:
                over.append(f"{line['label']}: adding, removing or replacing a whole row is beyond the {rule.label.lower()} limit on {lim.path}")
    if over:
        return Outcome("request_approval", "; ".join(over))
    return Outcome("apply")


def may_touch(pol: Policy, actor: Actor, diff: list[dict[str, Any]]) -> bool:
    """Cheap check (no limits) used to show an Undo button: can this role change these settings at all?"""
    rule = pol.governance.roles[actor.role]
    if not rule.can_apply:
        return False
    return all(covers(rule.sections, line["keys"]) and (line["keys"][0] != "governance" or actor.role == HEAD) for line in diff)
