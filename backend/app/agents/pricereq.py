"""Existing-vendor price-increase requests: the agent around the engine in ``app.pricereq``.

The model (muse-spark-1.3 through the gateway) reads the vendor's email and revised price list into a
``PriceRequestExtraction``. Every number and date carries a verbatim quote; each is a ``model_extraction`` Claim that is
checked against the request text (quote present word for word, the number is one the quote states) and goes through the
self-correction loop (``selfcorrect.self_correct``). A line or sweetener that is still wrong after the last retry is dropped
with the reason. Python (``pricereq.evaluate``) then decides; the model finally drafts the reply from the engine's numbers
only and any sentence stating another number is struck. Nothing is ever sent: approval records a simulated send.

State (cached analyses, submitted requests, approvals) lives in memory, like the live-call sessions.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app import deals, llm, pricereq, prompts_price, selfcorrect
from app.agents.context import RunContext, Sequencer
from app.config import settings
from app.errors import (
    ApprovalTierTooLow,
    CategoryOSError,
    PriceRequestDecided,
    PriceRequestInvalid,
    PriceRequestNotFound,
    PriceRequestUnreadable,
    UnknownOpsVendor,
)
from app.parsing import PARSER_VERSION
from app.pricereq import (
    Evaluation,
    PriceReplyDraft,
    PriceRequestExtraction,
)
from app.schemas import Claim, ClaimFix, Evidence, SourceRef
from app.verify import numbers_in

STAGE = "negotiate"
ID_PATTERN = re.compile(r"^PR-(?:\d{3}|S\d{3})$")
MAX_TEXT = 60_000
_FRACTIONS = {"half": 50.0, "quarter": 25.0, "third": 100 / 3, "one-third": 100 / 3, "one-half": 50.0}
_PERIOD_WORDS = {30: ("month", "monthly", "/mo"), 7: ("week", "weekly"), 90: ("quarter", "quarterly"), 365: ("year", "annual", "yearly"), 1: ("day", "daily")}
TOL = 0.005  # exact reads: a cost must match the quote to the paisa


# ---------- requests ----------


@dataclass
class Request:
    id: str
    vendor_id: str
    received: date
    sender: str
    subject: str
    email: str
    price_list: str
    list_name: str
    submitted: bool = False

    def text_for(self, file: str) -> str:
        return self.email if file.endswith("email.txt") else self.price_list

    @property
    def contact(self) -> str:
        name = re.sub(r"<.*?>", "", self.sender).strip()
        return name.split()[0] if name else "Team"


_submitted: dict[str, Request] = {}


def _root() -> Path:
    return Path(settings.data_dir) / "price_requests"


def _builtin() -> list[Request]:
    path = _root() / "index.json"
    if not path.exists():
        return []
    out = []
    for row in json.loads(path.read_text(encoding="utf-8"))["requests"]:
        d = _root() / row["id"]
        out.append(
            Request(
                id=row["id"], vendor_id=row["vendor_id"], received=date.fromisoformat(row["received_at"]), sender=row["sender"], subject=row["subject"],
                email=(d / "email.txt").read_text(encoding="utf-8"), price_list=(d / row["price_list"]).read_text(encoding="utf-8"), list_name=row["price_list"],
            )
        )
    return out


def inbox() -> list[Request]:
    return [*_builtin(), *_submitted.values()]


def get_request(request_id: str) -> Request:
    if not ID_PATTERN.match(request_id):
        raise PriceRequestNotFound(request_id)
    found = next((r for r in inbox() if r.id == request_id), None)
    if found is None:
        raise PriceRequestNotFound(request_id)
    return found


def submit(vendor_id: str, email: str, price_list: str, sender: str, subject: str, received: str | None) -> Request:
    """Add a pasted or uploaded request to the inbox (in memory). Reading it needs the model (mock mode has no fixture for it)."""
    if not pricereq.known_vendor(vendor_id):
        raise UnknownOpsVendor(vendor_id)
    if not email.strip() or len(email) > MAX_TEXT or len(price_list) > MAX_TEXT:
        raise PriceRequestInvalid("The email is empty, or the email or price list is over 60,000 characters")
    try:
        when = date.fromisoformat(received) if received else _today()
    except ValueError as exc:
        raise PriceRequestInvalid("received must be an ISO date such as 2026-10-27") from exc
    rid = f"PR-S{len(_submitted) + 1:03d}"
    req = Request(rid, vendor_id, when, sender.strip()[:200] or "vendor", subject.strip()[:200] or "Price revision", email, price_list, "price_list.txt", submitted=True)
    _submitted[rid] = req
    return req


def _today() -> date:
    return date.fromisoformat(settings.demo_today) if settings.demo_today else date.today()


# ---------- claims ----------


@dataclass
class Where:
    kind: str  # line | sweetener | effective | reason
    target: Any
    field: str


def _squash(text: str) -> str:
    return " ".join(text.split())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _file(req: Request, source: str) -> str:
    return f"price_requests/{req.id}/" + ("email.txt" if source == "email" else "price_list")


def _claim(req: Request, cid: str, text: str, value: float, metric: str, unit: str, source: str, quote: str, key: str, column: str) -> Claim:
    src = req.text_for(_file(req, source))
    return Claim(
        id=f"{req.id}:{cid}", text=text, value=value, metric=metric, unit=unit,  # type: ignore[arg-type]
        source_ref=SourceRef(file=_file(req, source), key=key, column=column),
        evidence=Evidence(raw_value=quote, normalized_value=value, parser_version=PARSER_VERSION, sha256=_sha(src)),
        origin="model_extraction",
    )


def build_claims(req: Request, ex: PriceRequestExtraction) -> list[tuple[Claim, Where]]:
    out: list[tuple[Claim, Where]] = []

    def add(claim: Claim, where: Where) -> None:
        out.append((claim, where))

    if ex.effective_date:
        d = pricereq._iso(ex.effective_date)
        if d is not None:
            add(_claim(req, "effective_date", f"Effective date {ex.effective_date}", pricereq.date_value(d), "price_req_date", "units", "email", ex.effective_quote, "effective_date", "date"), Where("effective", ex, "effective_date"))
    if ex.reason_quote:
        add(_claim(req, "reason", f"Stated reason: {ex.reason}", 1.0, "price_req_quote", "units", "email", ex.reason_quote, "reason", "quote"), Where("reason", ex, "reason"))
    for ln in ex.lines:
        for fld, label in (("old_cost", "old cost"), ("new_cost", "new cost")):
            add(_claim(req, f"line:{ln.sku_code}:{fld}", f"{ln.sku_code} {label} {getattr(ln, fld):g}", float(getattr(ln, fld)), f"price_req_{fld}", "inr", ln.source, ln.quote, ln.sku_code, fld), Where("line", ln, fld))
    for sw in ex.sweeteners:
        nums: list[tuple[str, float | None, str, float]] = []
        if sw.kind == "absorb_if_volume":
            nums = [("share_pct", sw.share_pct, "pct", (sw.share_pct or 0) / 100), ("threshold_units", sw.threshold_units, "units", sw.threshold_units or 0.0), ("window_days", sw.window_days, "units", float(sw.window_days or 0))]
        else:
            nums = [("support_pct", sw.support_pct, "pct", (sw.support_pct or 0) / 100)]
        for fld, raw, unit, value in nums:
            metric = "price_req_period" if fld == "window_days" else f"price_req_{fld}"
            add(_claim(req, f"sweetener:{sw.id}:{fld}", f"Sweetener {sw.id} {fld.replace('_', ' ')} {raw if raw is not None else 'missing'}", value, metric, unit, sw.source, sw.quote, sw.id, fld), Where("sweetener", sw, fld))
    return out


_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _stated(quote: str, unit: str) -> list[float]:
    """Numbers a quote states. A comma is a thousands separator in "1,500" but a cell separator in "118,122.72" (a CSV row), so
    both readings of a comma-joined token are offered."""
    nums = numbers_in(quote)
    for tok in _DIGITS.findall(quote):
        if "," in tok:
            nums.extend(float(piece) for piece in tok.split(",") if piece.strip("."))
    if unit == "pct":
        nums = [*nums, *(v for w, v in _FRACTIONS.items() if re.search(rf"\b{re.escape(w)}\b", quote, re.IGNORECASE))]
    return nums


def check_claim(claim: Claim, req: Request) -> Claim:
    """The quote must appear word for word in the request text, and the claimed number or date must be one the quote states."""
    ev = claim.evidence
    assert ev is not None

    def done(status: str, reason: str | None, recomputed: float | None = None) -> Claim:
        return claim.model_copy(update={"status": status, "reason": reason, "recomputed": recomputed})

    quote = _squash(ev.raw_value or "")
    if not quote:
        return done("rejected", "no quote: a verbatim quote is required")
    text = req.text_for(claim.source_ref.file)
    if ev.sha256 != _sha(text):
        return done("rejected", "source changed: evidence sha256 does not match the request text")
    if quote not in _squash(text):
        return done("rejected", f"the quote does not appear verbatim in the {'email' if claim.source_ref.file.endswith('email.txt') else 'price list'}")
    if claim.metric == "price_req_quote":
        return done("verified", None, claim.value)
    if claim.metric == "price_req_date":
        found = [pricereq.date_value(d) for d in pricereq.parse_dates(quote, req.received)]
        if claim.value in found:
            return done("verified", None, claim.value)
        shown = ", ".join(f"{int(v)}" for v in found) or "none"
        return done("rejected", f"the quote states the date(s) {shown} (as YYYYMMDD); the claim says {int(claim.value)}", found[0] if found else None)
    if claim.metric == "price_req_period":
        if any(abs(n - claim.value) <= TOL for n in numbers_in(quote)) or any(w in quote.lower() for w in _PERIOD_WORDS.get(int(claim.value), ())):
            return done("verified", None, claim.value)
        return done("rejected", f"the quote does not state a period of {int(claim.value)} days (for example 'per month')")
    value = claim.value * 100 if claim.unit == "pct" else claim.value
    stated = _stated(quote, claim.unit)
    tol = TOL if claim.unit == "inr" else 0.01 if claim.unit == "pct" else 0.0
    if any(abs(n - value) <= max(tol, 1e-9) for n in stated):
        return done("verified", None, claim.value)
    shown = ", ".join(f"{n:g}" for n in stated) or "none"
    return done("rejected", f"the quote states {shown}; the extraction says {value:g}", stated[0] / (100 if claim.unit == "pct" else 1) if stated else None)


def apply_fix(where: Where, fix: ClaimFix) -> None:
    t, fld = where.target, where.field
    if fix.transcript_quote:
        if where.kind == "line" or where.kind == "sweetener":
            t.quote = fix.transcript_quote
        elif where.kind == "effective":
            t.effective_quote = fix.transcript_quote
        elif where.kind == "reason":
            t.reason_quote = fix.transcript_quote
    if where.kind == "effective":
        digits = str(int(fix.value))
        if len(digits) == 8:
            t.effective_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    elif where.kind in ("line", "sweetener") and fld != "quote":
        setattr(t, fld, int(fix.value) if fld == "window_days" else float(fix.value))


# ---------- analysis (extraction + verification + self-correction), cached per request ----------


@dataclass
class Analysis:
    extraction: PriceRequestExtraction
    claims: list[Claim]
    rejected: list[dict[str, Any]]
    events: list[dict[str, Any]]
    mode: str
    model: str
    degraded: list[str] = field(default_factory=list)


_analyses: dict[str, Analysis] = {}
_evals: dict[str, tuple[str, Evaluation]] = {}
_replies: dict[str, dict[str, Any]] = {}
_decisions: dict[str, dict[str, Any]] = {}


def reset_state() -> None:
    _analyses.clear()
    _evals.clear()
    _replies.clear()
    _decisions.clear()
    _submitted.clear()


async def analyse(req: Request) -> Analysis:
    if req.id in _analyses:
        return _analyses[req.id]
    brand = pricereq.vendor_info(req.vendor_id)["brand"]
    messages = prompts_price.extract_messages(
        vendor_id=req.vendor_id, brand=brand, received=req.received.isoformat(), sender=req.sender, email=req.email, list_name=req.list_name, price_list=req.price_list
    )
    ctx = RunContext(f"pr_{req.id}", req.vendor_id, _today().isoformat(), Sequencer())
    res = await llm.call(STAGE, messages, task=f"price_request_{req.id}", schema=PriceRequestExtraction, max_tokens=3500)
    ctx.emit(
        "model_call", STAGE, {"task": "price_request_extract", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
        model=res.model, latency_ms=res.latency_ms, cost_usd=res.cost_usd,
    )
    ex = res.parsed
    assert isinstance(ex, PriceRequestExtraction)
    seen: set[str] = set()
    ex.lines = [ln for ln in ex.lines if not (ln.sku_code in seen or seen.add(ln.sku_code))]  # type: ignore[func-returns-value]
    built = build_claims(req, ex)
    where = {c.id: w for c, w in built}
    first = [check_claim(c, req) for c, _ in built]

    def rebuild(claim: Claim, fix: ClaimFix) -> Claim | None:
        apply_fix(where[claim.id], fix)
        return next((c for c, _ in build_claims(req, ex) if c.id == claim.id), None)

    fixed = await selfcorrect.self_correct(
        ctx, STAGE, first, task=f"price_request_{req.id}", messages=messages, previous=res.content, rebuild=rebuild,
        check=lambda batch: [check_claim(c, req) for c in batch],
    )
    final_map = {c.id: c for c in fixed}
    # the extraction object was edited in place by the fixes; drop whatever is still unverified
    ex, rejected = _prune(req, ex, final_map)
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait().model_dump(mode="json"))
    a = Analysis(ex, fixed, rejected, events, res.mode, res.model)
    _analyses[req.id] = a
    return a


def _prune(req: Request, ex: PriceRequestExtraction, claims: dict[str, Claim]) -> tuple[PriceRequestExtraction, list[dict[str, Any]]]:
    rejected: list[dict[str, Any]] = []
    bad: dict[str, list[str]] = {}
    for cid, c in claims.items():
        if c.status != "verified":
            bad.setdefault(cid.rsplit(":", 1)[0] if ":line:" in cid or ":sweetener:" in cid else cid, []).append(f"{c.metric.removeprefix('price_req_')}: {c.reason or c.status}")
    keep_lines = []
    for ln in ex.lines:
        key = f"{req.id}:line:{ln.sku_code}"
        if key in bad:
            rejected.append({"kind": "line", "id": ln.sku_code, "label": f"{ln.sku_code}: {ln.old_cost:g} to {ln.new_cost:g}", "reasons": bad[key]})
        else:
            keep_lines.append(ln)
    keep_sw = []
    for sw in ex.sweeteners:
        key = f"{req.id}:sweetener:{sw.id}"
        if key in bad:
            rejected.append({"kind": "sweetener", "id": sw.id, "label": sw.quote[:100], "reasons": bad[key]})
        else:
            keep_sw.append(sw)
    update: dict[str, Any] = {"lines": keep_lines, "sweeteners": keep_sw}
    if f"{req.id}:effective_date" in bad:
        rejected.append({"kind": "effective_date", "id": "effective_date", "label": ex.effective_date or "", "reasons": bad[f"{req.id}:effective_date"]})
        update.update(effective_date=None, effective_quote="")
    if f"{req.id}:reason" in bad:
        update.update(reason="", reason_quote="")
    return ex.model_copy(update=update), rejected


# ---------- evaluation and reply ----------


async def evaluate(req: Request) -> tuple[Analysis, Evaluation]:
    a = await analyse(req)
    if not a.extraction.lines:
        raise PriceRequestUnreadable(cause="; ".join(r["reasons"][0] for r in a.rejected[:3]) or "the model read no price lines")
    ev = pricereq.evaluate(req.vendor_id, a.extraction, req.received, _today())
    return a, ev


def _facts_hash(ev: Evaluation) -> str:
    return _sha(json.dumps(pricereq.email_facts(ev), sort_keys=True, default=str))


async def reply_for(req: Request, ev: Evaluation) -> dict[str, Any]:
    """The reply draft: model-written from the engine's figures; sentences with any other number are struck."""
    key = f"{req.id}:{_facts_hash(ev)}"
    if key in _replies:
        return _replies[key]
    brand, contact = pricereq.vendor_info(req.vendor_id)["brand"], req.contact
    messages = prompts_price.reply_messages(contact=contact, brand=brand, facts=pricereq.email_facts(ev))
    template = pricereq.template_reply(ev, brand, contact)
    out: dict[str, Any]
    try:
        res = await llm.call(STAGE, messages, task=f"price_request_reply_{req.id}", schema=PriceReplyDraft, max_tokens=1400)
        draft = res.parsed
        assert isinstance(draft, PriceReplyDraft)
        body, struck = pricereq.strike_unsupported(draft.body, ev)
        subject, struck_s = pricereq.strike_unsupported(draft.subject, ev)
        if len(body) < 40:
            out = {"subject": template.subject, "body": template.body, "source": "rules", "struck": [*struck, *struck_s], "model": None}
        else:
            out = {"subject": subject or template.subject, "body": body, "source": "model", "struck": [*struck, *struck_s], "model": res.model}
    except CategoryOSError as exc:
        out = {"subject": template.subject, "body": template.body, "source": "rules", "struck": [], "model": None, "note": f"reply drafting unavailable ({exc.code}); showing standard wording from the engine's figures"}
    _replies[key] = out
    return out


def deals_payload(ev: Evaluation) -> dict[str, Any] | None:
    """The sweeteners valued by the deal evaluator, in the shape the DealEvaluator card already renders."""
    items = [s.assessment for s in ev.sweeteners if s.assessment]
    if not items:
        return None
    ranks = {"reject_structure": 3, "needs_human": 2, "not_assessable": 1, "accept": 0}
    top = max((i["decision"] for i in items), key=lambda d: ranks[d])
    return {
        "decision": top,
        "headline": {"reject_structure": "Reject the conditional structure and counter", "accept": "Offer is acceptable on a risk-adjusted basis"}.get(top, "A human must decide"),
        "assessments": items, "base_terms": [], "rejected_terms": [], "assumptions": deals.assumptions(), "talk": None, "claim_status": {}, "verification": None,
    }


def claim_rows(claims: list[Claim]) -> list[dict[str, Any]]:
    return [
        {"id": c.id, "text": c.text, "metric": c.metric, "value": c.value, "status": c.status, "reason": c.reason, "quote": c.evidence.raw_value if c.evidence else None,
         "attempts": [a.model_dump(mode="json") for a in c.attempts], "sku": c.source_ref.key}
        for c in claims
    ]


async def view(req: Request) -> dict[str, Any]:
    a, ev = await evaluate(req)
    reply = await reply_for(req, ev)
    ok = sum(1 for c in a.claims if c.status == "verified")
    fixed = len(selfcorrect.corrected(a.claims))
    return {
        "request": request_row(req),
        "email": req.email,
        "price_list": req.price_list,
        "price_list_name": req.list_name,
        "reason": a.extraction.reason,
        "reason_quote": a.extraction.reason_quote,
        "effective_date": a.extraction.effective_date,
        "evaluation": ev.model_dump(mode="json"),
        "deals": deals_payload(ev),
        "reply": reply,
        "claims": claim_rows(a.claims),
        "verification": {"total": len(a.claims), "verified": ok, "rejected": sum(1 for c in a.claims if c.status == "rejected"), "self_corrected": fixed},
        "rejected": a.rejected,
        "trace": a.events,
        "mode": a.mode,
        "model": a.model,
        "status": status_row(req.id),
    }


def request_row(req: Request) -> dict[str, Any]:
    return {
        "id": req.id, "vendor_id": req.vendor_id, "brand": pricereq.vendor_info(req.vendor_id)["brand"], "received_at": req.received.isoformat(), "sender": req.sender,
        "subject": req.subject, "submitted": req.submitted, "status": status_row(req.id)["status"],
    }


# ---------- approval (a person decides; sending is simulated) ----------


def status_row(request_id: str) -> dict[str, Any]:
    return _decisions.get(request_id, {"status": "pending"})


async def decide(req: Request, action: str, role: str, body: str | None, note: str | None) -> dict[str, Any]:
    if status_row(req.id)["status"] != "pending":
        raise PriceRequestDecided()
    _a, ev = await evaluate(req)
    needed = ev.approval.tier
    if pricereq.tier_rank(role) < pricereq.tier_rank(needed.role):
        raise ApprovalTierTooLow(
            f"{role.replace('_', ' ')} cannot approve this request: it needs {needed.label}",
            cause="; ".join(ev.approval.reasons),
        )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    if action == "reject":
        rec = {"status": "rejected", "by": role, "at": now, "note": note or "", "tier_required": needed.role}
    else:
        reply = await reply_for(req, ev)
        rec = {
            "status": "approved", "by": role, "at": now, "note": note or "", "tier_required": needed.role,
            "sent": {"simulated": True, "to": req.sender, "subject": reply["subject"], "body": body if body is not None else reply["body"]},
        }
    _decisions[req.id] = rec
    return {**rec, "id": req.id}
