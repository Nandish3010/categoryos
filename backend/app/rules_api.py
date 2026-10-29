"""HTTP routes of the Rules page: GET/PUT /api/policy and /api/policy/reset (the form), POST /api/policy/propose (a prompt becomes a
preview), the change log and the apply / approve / reject / undo / discard actions. Logic lives in app.rules and app.governance.

The acting team member is the X-Acting-As header, a DEMO identity picker and not authentication; a request without it acts as the
least-privileged role (analyst), so a missing header fails closed. On a replay deploy the X-Visitor-Id header, with the caller's address, picks a private sandbox (see rules.visitor_key)."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app import governance, llm, public_live, rules, sandbox
from app.auth import check_rate, require_demo_key
from app.config import settings
from app.schemas import PolicyResetBody, ProposeBody

router = APIRouter()

ActingAs = Annotated[str | None, Header(alias="X-Acting-As")]


async def require_policy_write(request: Request, x_demo_key: str | None = Header(default=None)) -> None:
    """Who may write the playbook at all. On a replay deploy anyone may, into their own sandbox (rate limited per address); elsewhere a
    demo key is required only when one is configured. What a given team member may change is decided later, by governance."""
    if settings.effective_mode == "replay":
        check_rate(sandbox.client_ip(request))
        return
    if settings.demo_key:
        await require_demo_key(request, x_demo_key)


def _visitor(request: Request) -> str:
    return rules.visitor_key(request)


async def _model_access(request: Request, prompt: str, x_demo_key: str | None) -> str | None:
    """Gate the translator call. Returns the address bucket to charge when it runs on the public live budget, else None. A call that
    will not reach a model (a recorded example, mock mode) needs nothing."""
    mode = llm.resolve_mode(rules.STAGE)
    if not (mode == "live" or (mode == "replay" and not rules.has_fixture(prompt))):
        return None
    ip = sandbox.client_ip(request)
    if mode == "live" and sandbox.demo_key_ok(x_demo_key):
        return None
    if public_live.enabled("rules"):
        key = sandbox.ip_key(ip)
        public_live.check(key)
        return key
    if mode == "live":
        await require_demo_key(request, x_demo_key)  # raises: no key, or a wrong one
    return None  # replay without a public budget: rules.translate refuses with a cause and fix


# ---------- the form ----------


@router.get("/api/policy")
async def get_policy(request: Request, x_acting_as: ActingAs = None) -> dict[str, Any]:
    return await asyncio.to_thread(rules.snapshot_for, _visitor(request), x_acting_as)


@router.put("/api/policy", dependencies=[Depends(require_policy_write)])
async def put_policy(body: dict[str, Any], request: Request, x_acting_as: ActingAs = None) -> JSONResponse:
    """The form's Save. Checked against the acting member's role like any other change, and logged (source "form"). A change over the
    role's limit is parked for approval (202); one the role may not make is refused (403)."""
    visitor = _visitor(request)
    ch = await asyncio.to_thread(rules.submit_form, visitor, x_acting_as, body)
    return await _respond(visitor, x_acting_as, ch)


@router.post("/api/policy/reset", dependencies=[Depends(require_policy_write)])
async def reset_policy(request: Request, body: PolicyResetBody | None = None, x_acting_as: ActingAs = None) -> JSONResponse:
    visitor = _visitor(request)
    ch = await asyncio.to_thread(rules.submit_reset, visitor, x_acting_as, body.section if body else None)
    return await _respond(visitor, x_acting_as, ch)


async def _respond(visitor: str, member: str | None, ch: rules.Change | None) -> JSONResponse:
    snap = await asyncio.to_thread(rules.snapshot_for, visitor, member)
    if ch is not None:
        snap["change"] = ch.model_dump()
    return JSONResponse(snap, status_code=202 if ch is not None and ch.status == "pending_approval" else 200)


# ---------- prompts ----------


@router.get("/api/policy/examples")
async def get_examples() -> dict[str, Any]:
    return {"examples": rules.EXAMPLES}


@router.post("/api/policy/propose")
async def propose(body: ProposeBody, request: Request, x_acting_as: ActingAs = None, x_demo_key: str | None = Header(default=None)) -> dict[str, Any]:
    """Turn a plain-English rule into a preview. The model only picks existing settings and numbers; Python dry-runs the result
    through the playbook's validation and the acting member's permissions. Nothing is written to the playbook."""
    check_rate(sandbox.client_ip(request))  # every preview, recorded example or not, costs a draft row and a validation
    visitor = _visitor(request)
    prompt = " ".join(body.prompt.split())
    pol = await asyncio.to_thread(rules.current_policy, visitor)
    governance.actor_for(pol, x_acting_as)  # an unknown member fails before any model is called
    public_ip = await _model_access(request, prompt, x_demo_key)
    proposal, via = await rules.translate(prompt, pol, public_ip=public_ip)
    return await asyncio.to_thread(rules.build_preview, visitor, x_acting_as, prompt, proposal, via)


# ---------- change log and actions ----------


@router.get("/api/policy/changes")
async def list_changes(request: Request, x_acting_as: ActingAs = None, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> dict[str, Any]:
    return await asyncio.to_thread(rules.list_log, _visitor(request), x_acting_as, limit)


async def _act(request: Request, member: str | None, fn: Any, change_id: str) -> JSONResponse:
    visitor = _visitor(request)
    ch = await asyncio.to_thread(fn, visitor, member, change_id)
    return await _respond(visitor, member, ch)


@router.post("/api/policy/changes/{change_id}/apply", dependencies=[Depends(require_policy_write)])
async def apply_change(change_id: str, request: Request, x_acting_as: ActingAs = None) -> JSONResponse:
    return await _act(request, x_acting_as, rules.apply_change, change_id)


@router.post("/api/policy/changes/{change_id}/approve", dependencies=[Depends(require_policy_write)])
async def approve_change(change_id: str, request: Request, x_acting_as: ActingAs = None) -> JSONResponse:
    return await _act(request, x_acting_as, rules.approve_change, change_id)


@router.post("/api/policy/changes/{change_id}/reject", dependencies=[Depends(require_policy_write)])
async def reject_change(change_id: str, request: Request, x_acting_as: ActingAs = None) -> JSONResponse:
    return await _act(request, x_acting_as, rules.reject_change, change_id)


@router.post("/api/policy/changes/{change_id}/undo", dependencies=[Depends(require_policy_write)])
async def undo_change(change_id: str, request: Request, x_acting_as: ActingAs = None) -> JSONResponse:
    return await _act(request, x_acting_as, rules.undo_change, change_id)


@router.post("/api/policy/changes/{change_id}/discard", dependencies=[Depends(require_policy_write)])
async def discard_change(change_id: str, request: Request) -> dict[str, bool]:
    await asyncio.to_thread(rules.discard_change, _visitor(request), change_id)
    return {"ok": True}
