"""Model gateway: mock | replay | live behind one call(). Never imported by metrics or verify."""

import asyncio
import hashlib
import inspect
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import openai
from pydantic import BaseModel, ValidationError

from app import ledger, sandbox_mock, scope
from app.config import settings
from app.constants import STAGE_META
from app.errors import (
    CreditsUnavailable,
    FixtureMissing,
    LlmBadOutput,
    LlmUnavailable,
    MissingKey,
)
from app.parsing import PARSER_VERSION
from app.tools import run_tool, summarize

log = logging.getLogger("categoryos.llm")

FIXTURE_SCHEMA_VERSION = 1
RETRY_DELAYS = (1.0, 3.0)  # two retries for timeouts and 429
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class LlmResult:
    content: str
    parsed: BaseModel | None
    model: str
    provider: str
    mode: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    degraded: bool = False


async def _sleep(seconds: float) -> None:  # patched out in tests
    await asyncio.sleep(seconds)


# ---------- fixtures ----------


def fixture_path(kind: Literal["mock", "golden"], stage: str, task: str) -> Path:
    return Path(settings.fixtures_dir) / kind / stage / f"{task}.json"


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _load_fixture(kind: Literal["mock", "golden"], stage: str, task: str) -> dict[str, Any]:
    if kind == "mock":
        generic = sandbox_mock.fixture(stage, task)  # sandbox vendors have no recorded fixtures: build the generic one
        if generic is not None:
            return generic
    path = fixture_path(kind, stage, task)
    if not path.exists():
        raise FixtureMissing(
            f"no {kind} fixture for stage={stage!r} task={task!r}",
            cause=f"expected file {path}",
            fix=(
                "run make record (needs live credits) or add the fixture: "
                f"{path.relative_to(settings.fixtures_dir.parent) if path.is_relative_to(settings.fixtures_dir.parent) else path}"
            ),
        )
    data = json.loads(path.read_text())
    content = data["content"] if isinstance(data["content"], str) else json.dumps(data["content"])
    if data.get("checksum") and data["checksum"] != _checksum(content):
        raise FixtureMissing(
            f"{kind} fixture {path.name} failed its checksum",
            cause="the file was edited after it was recorded",
            fix="run make record to regenerate it, or remove the stale checksum field",
        )
    data["content"] = content
    return data


def _from_fixture(
    data: dict[str, Any], schema: type[BaseModel] | None, *, stage: str, task: str, mode: str, provider: str, started: float, degraded: bool
) -> LlmResult:
    content = data["content"]
    parsed = None
    if schema is not None:
        try:
            parsed = schema.model_validate(lenient_json(content))
        except (ValueError, ValidationError) as exc:
            raise LlmBadOutput(cause=f"fixture {stage}/{task} does not match {schema.__name__}: {exc}") from exc
    return LlmResult(
        content=content,
        parsed=parsed,
        model=data.get("model", "fixture"),
        provider=provider,
        mode=mode,
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        cost_usd=0.0,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        degraded=degraded,
    )


# ---------- lenient JSON ----------


def lenient_json(text: str) -> Any:
    """Parse JSON from model text: strips code fences, falls back to the first balanced {...} block."""
    stripped = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = stripped.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


# ---------- live ----------


def _api_key(provider: str) -> str | None:
    return settings.baseten_api_key if provider == "baseten" else settings.model_api_key


def _make_client(provider: str) -> Any:
    base = settings.baseten_base_url if provider == "baseten" else settings.model_api_base_url
    return openai.AsyncOpenAI(base_url=base, api_key=_api_key(provider), timeout=60.0, max_retries=0)


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, openai.APITimeoutError | openai.RateLimitError | asyncio.TimeoutError) or _status(exc) in (429, 408)


def _usage(resp: Any) -> tuple[int, int, int]:
    usage = getattr(resp, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
        int(getattr(details, "cached_tokens", 0) or 0),
    )


class _Meter:
    def __init__(self, model: str) -> None:
        self.model, self.input, self.output, self.cost = model, 0, 0, 0.0

    def add(self, resp: Any) -> None:
        i, o, c = _usage(resp)
        self.input += i
        self.output += o
        self.cost += ledger.record(self.model, {"input_tokens": i, "cached_tokens": c, "output_tokens": o})


async def _create(client: Any, kwargs: dict[str, Any], meter: _Meter) -> Any:
    """One API call with transient retries (timeouts, 429) and error mapping."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            status = _status(exc)
            if status in (402, 403):
                raise CreditsUnavailable(cause=f"provider returned HTTP {status}") from exc
            if status == 401:
                raise MissingKey(problem="The provider rejected the API key (401)", cause="the key is invalid or revoked") from exc
            if _is_transient(exc):
                if attempt < len(RETRY_DELAYS):
                    await _sleep(RETRY_DELAYS[attempt])
                    continue
                raise LlmUnavailable(cause=f"{type(exc).__name__} persisted after {attempt + 1} attempts") from exc
            raise
        meter.add(resp)
        return resp
    raise LlmUnavailable()  # pragma: no cover


def _text(resp: Any) -> tuple[str, str | None]:
    choice = resp.choices[0]
    msg = choice.message
    if getattr(msg, "refusal", None):
        return "", choice.finish_reason
    return (msg.content or ""), choice.finish_reason


async def _complete(client: Any, kwargs: dict[str, Any], meter: _Meter) -> str:
    """Returns non-empty text; handles reasoning models that burn max_tokens, and empty/refusal retry."""
    empty_retried = False
    length_retried = False
    while True:
        resp = await _create(client, kwargs, meter)
        text, finish = _text(resp)
        if text.strip():
            return text
        if finish == "length" and not length_retried:
            length_retried = True
            kwargs = {**kwargs, "max_tokens": kwargs["max_tokens"] * 2}
            continue
        if not empty_retried:
            empty_retried = True
            continue
        raise LlmBadOutput(cause="the model returned an empty or refused response twice")


def _schema_instruction(schema: type[BaseModel]) -> str:
    return "Reply with only a JSON object matching this JSON schema, no prose:\n" + json.dumps(schema.model_json_schema())


async def _live(
    stage: str, messages: list[dict[str, Any]], *, model: str | None, schema: type[BaseModel] | None, provider: str, effort: str, max_tokens: int
) -> tuple[str, BaseModel | None, str, _Meter]:
    if not _api_key(provider):
        raise MissingKey(
            cause="BASETEN_API_KEY is empty" if provider == "baseten" else "MODEL_API_KEY is empty",
        )
    ledger.check_budget()
    model = model or (settings.baseten_model if provider == "baseten" else settings.model_text)
    msgs = [dict(m) for m in messages]
    kwargs: dict[str, Any] = {"model": model, "messages": msgs, "max_tokens": max_tokens}
    if provider == "meta":
        kwargs["reasoning_effort"] = effort
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": True},
            }
    elif schema is not None:
        msgs.append({"role": "system", "content": _schema_instruction(schema)})
    client = _make_client(provider)
    meter = _Meter(model)
    content = await _complete(client, kwargs, meter)
    if schema is None:
        return content, None, model, meter
    try:
        return content, schema.model_validate(lenient_json(content)), model, meter
    except (ValueError, ValidationError) as first:
        repair = [
            *msgs,
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"That reply was not valid for the schema ({str(first)[:300]}). Reply with only the corrected JSON object."},
        ]
        content = await _complete(client, {**kwargs, "messages": repair}, meter)
        try:
            return content, schema.model_validate(lenient_json(content)), model, meter
        except (ValueError, ValidationError) as second:
            raise LlmBadOutput(cause=f"output still invalid after one repair prompt: {str(second)[:200]}") from second


def _record_golden(stage: str, task: str, model: str, content: str, meter: _Meter) -> None:
    path = fixture_path("golden", stage, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": FIXTURE_SCHEMA_VERSION,
                "parser_version": PARSER_VERSION,
                "stage": stage,
                "task": task,
                "model": model,
                "input_tokens": meter.input,
                "output_tokens": meter.output,
                "checksum": _checksum(content),
                "content": content,
            },
            indent=2,
        )
    )


# ---------- public ----------


def resolve_mode(stage: str) -> str:
    sc = scope.current()
    if sc is not None:  # a sandbox vendor: rules-only and mock use the generic mock, live only when it was cleared at upload/run
        return "live" if sc.llm_mode == "live" else "mock"
    mode = settings.effective_mode
    if mode == "live" and settings.live_stages.strip():
        live = {s.strip() for s in settings.live_stages.split(",") if s.strip()}
        if stage not in live:
            return "mock"
    return mode


def any_live() -> bool:
    """True when at least one pipeline stage would call a live model."""
    return any(resolve_mode(stage["id"]) == "live" for stage in STAGE_META)


async def call(
    stage: str,
    messages: list[dict[str, Any]],
    *,
    task: str,
    model: str | None = None,
    schema: type[BaseModel] | None = None,
    provider: Literal["meta", "baseten"] = "meta",
    effort: str = "low",
    max_tokens: int = 1500,
) -> LlmResult:
    started = time.perf_counter()
    mode = resolve_mode(stage)
    degraded = False
    shared = {"stage": stage, "task": task, "provider": provider, "started": started}
    if mode == "mock":
        result = _from_fixture(_load_fixture("mock", stage, task), schema, mode="mock", degraded=False, **shared)
    elif mode == "replay":
        try:
            result = _from_fixture(_load_fixture("golden", stage, task), schema, mode="replay", degraded=False, **shared)
        except FixtureMissing:
            degraded = True
            result = _from_fixture(_load_fixture("mock", stage, task), schema, mode="replay", degraded=True, **shared)
    else:
        content, parsed, used_model, meter = await _live(
            stage, messages, model=model, schema=schema, provider=provider, effort=effort, max_tokens=max_tokens
        )
        result = LlmResult(
            content=content,
            parsed=parsed,
            model=used_model,
            provider=provider,
            mode="live",
            input_tokens=meter.input,
            output_tokens=meter.output,
            cost_usd=round(meter.cost, 8),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            degraded=False,
        )
        if settings.record:
            _record_golden(stage, task, used_model, content, meter)
    log.info(
        json.dumps(
            {
                "event": "llm_call",
                "stage": stage,
                "task": task,
                "model": result.model,
                "provider": provider,
                "mode": result.mode,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "usd": result.cost_usd,
                "latency_ms": result.latency_ms,
                "degraded": degraded or result.degraded,
            }
        )
    )
    return result


# ---------- tool-calling runs ----------


@dataclass
class ToolRunResult:
    final: dict[str, Any]
    parsed: BaseModel | None
    steps: list[dict[str, Any]]  # {tool, args, result_summary, result, latency_ms}
    content: str
    model: str
    provider: str
    mode: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    degraded: bool = False


StepCallback = Callable[[dict[str, Any]], Any]  # sync or async; called after every executed tool step


async def _notify(on_step: StepCallback | None, step: dict[str, Any]) -> None:
    if on_step is None:
        return
    out = on_step(step)
    if inspect.isawaitable(out):
        await out


async def _execute_step(tool: Any, name: str, args: dict[str, Any], on_step: StepCallback | None) -> dict[str, Any]:
    """Run one real tool function and record the step. ``tool`` is an app.tools.Tool (duck-typed)."""
    started = time.perf_counter()
    result = run_tool(tool, args) if tool is not None else {"error": f"unknown tool {name!r}"}
    step = {
        "tool": name,
        "args": args,
        "result_summary": summarize(result),
        "result": result,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    await _notify(on_step, step)
    return step


def _final_from_text(content: str, schema: type[BaseModel] | None) -> tuple[dict[str, Any], BaseModel | None]:
    data = lenient_json(content)
    if not isinstance(data, dict):
        raise ValueError("final answer must be a JSON object")  # noqa: TRY004
    return data, (schema.model_validate(data) if schema is not None else None)


async def _tools_from_fixture(
    data: dict[str, Any],
    tools: list[Any],
    schema: type[BaseModel] | None,
    on_step: StepCallback | None,
    *,
    stage: str,
    task: str,
    max_steps: int,
    mode: str,
    provider: str,
    started: float,
    degraded: bool,
) -> ToolRunResult:
    by_name = {t.name: t for t in tools}
    try:
        script = json.loads(data["content"])
        scripted = list(script["steps"])
        final_raw = script["final"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LlmBadOutput(cause=f"fixture {stage}/{task} must be an object with 'steps' and 'final'") from exc
    steps = []
    for item in scripted[:max_steps]:
        if item["tool"] not in by_name:
            raise LlmBadOutput(cause=f"fixture {stage}/{task} calls tool {item['tool']!r} which this stage did not offer")
        steps.append(await _execute_step(by_name[item["tool"]], item["tool"], dict(item.get("args", {})), on_step))
    content = final_raw if isinstance(final_raw, str) else json.dumps(final_raw)
    try:
        final, parsed = _final_from_text(content, schema)
    except (ValueError, ValidationError) as exc:
        raise LlmBadOutput(cause=f"fixture {stage}/{task} final does not match {schema.__name__ if schema else 'an object'}: {exc}") from exc
    return ToolRunResult(
        final=final,
        parsed=parsed,
        steps=steps,
        content=content,
        model=data.get("model", "fixture"),
        provider=provider,
        mode=mode,
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        cost_usd=0.0,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        degraded=degraded,
    )


def _assistant_tool_message(msg: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": msg.content or None,
        "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
            for c in msg.tool_calls
        ],
    }


async def _live_tools(
    stage: str,
    messages: list[dict[str, Any]],
    tools: list[Any],
    *,
    max_steps: int,
    schema: type[BaseModel] | None,
    model: str | None,
    provider: str,
    effort: str,
    max_tokens: int,
    on_step: StepCallback | None,
) -> tuple[str, dict[str, Any], BaseModel | None, list[dict[str, Any]], str, _Meter]:
    if not _api_key(provider):
        raise MissingKey(cause="BASETEN_API_KEY is empty" if provider == "baseten" else "MODEL_API_KEY is empty")
    ledger.check_budget()
    model = model or (settings.baseten_model if provider == "baseten" else settings.model_text)
    msgs = [dict(m) for m in messages]
    if schema is not None:
        msgs.append({"role": "system", "content": _schema_instruction(schema)})
    by_name = {t.name: t for t in tools}
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "tools": [t.spec() for t in tools],
    }
    if provider == "meta":
        kwargs["reasoning_effort"] = effort
    client = _make_client(provider)
    meter = _Meter(model)
    steps: list[dict[str, Any]] = []
    content = ""
    for turn in range(max_steps + 1):
        last_chance = turn == max_steps  # out of steps: force a plain answer
        if last_chance:
            kwargs["tool_choice"] = "none"
        resp = await _create(client, kwargs, meter)
        msg = resp.choices[0].message
        calls = getattr(msg, "tool_calls", None) or []
        if calls and not last_chance:
            msgs.append(_assistant_tool_message(msg))
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                if isinstance(args, dict):
                    step = await _execute_step(by_name.get(call.function.name), call.function.name, args, on_step)
                else:
                    step = await _execute_step(None, call.function.name, {}, on_step)
                    step["result"] = {"error": "arguments were not a JSON object"}
                steps.append(step)
                msgs.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(step["result"])})
            continue
        text, _ = _text(resp)
        if not text.strip():
            raise LlmBadOutput(cause="the model returned an empty or refused final answer")
        content = text
        break
    try:
        final, parsed = _final_from_text(content, schema)
    except (ValueError, ValidationError) as first:
        repair = [
            *msgs,
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"That reply was not valid ({str(first)[:300]}). Reply with only the corrected JSON object."},
        ]
        repaired = await _complete(client, {**kwargs, "messages": repair, "tool_choice": "none"}, meter)
        try:
            final, parsed = _final_from_text(repaired, schema)
        except (ValueError, ValidationError) as second:
            raise LlmBadOutput(cause=f"final answer still invalid after one repair prompt: {str(second)[:200]}") from second
        content = repaired
    return content, final, parsed, steps, model, meter


async def run_tools(
    stage: str,
    task: str,
    messages: list[dict[str, Any]],
    tools: list[Any],
    *,
    max_steps: int = 6,
    schema: type[BaseModel] | None = None,
    model: str | None = None,
    provider: Literal["meta", "baseten"] = "meta",
    effort: str = "low",
    max_tokens: int = 3000,
    on_step: StepCallback | None = None,
) -> ToolRunResult:
    """Tool-calling agent loop. live: chat.completions with tools until a final answer or max_steps.
    mock/replay: the fixture's scripted steps run through the REAL tool functions, then its final is returned."""
    started = time.perf_counter()
    mode = resolve_mode(stage)
    shared = {"stage": stage, "task": task, "provider": provider, "started": started, "max_steps": max_steps}
    if mode == "mock":
        result = await _tools_from_fixture(_load_fixture("mock", stage, task), tools, schema, on_step, mode="mock", degraded=False, **shared)
    elif mode == "replay":
        try:
            golden = _load_fixture("golden", stage, task)
            degraded = False
        except FixtureMissing:
            golden, degraded = _load_fixture("mock", stage, task), True
        result = await _tools_from_fixture(golden, tools, schema, on_step, mode="replay", degraded=degraded, **shared)
    else:
        content, final, parsed, steps, used_model, meter = await _live_tools(
            stage, messages, tools, max_steps=max_steps, schema=schema, model=model, provider=provider,
            effort=effort, max_tokens=max_tokens, on_step=on_step,
        )
        result = ToolRunResult(
            final=final,
            parsed=parsed,
            steps=steps,
            content=content,
            model=used_model,
            provider=provider,
            mode="live",
            input_tokens=meter.input,
            output_tokens=meter.output,
            cost_usd=round(meter.cost, 8),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        if settings.record:
            script = {"steps": [{"tool": s["tool"], "args": s["args"]} for s in steps], "final": final}
            _record_golden(stage, task, used_model, json.dumps(script), meter)
    log.info(
        json.dumps(
            {
                "event": "llm_tool_run",
                "stage": stage,
                "task": task,
                "model": result.model,
                "mode": result.mode,
                "steps": len(result.steps),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "usd": result.cost_usd,
                "latency_ms": result.latency_ms,
                "degraded": result.degraded,
            }
        )
    )
    return result
