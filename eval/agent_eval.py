"""Agent eval: the same extraction tasks (read a cost or MRP off a messy vendor sheet) through two models, graded by the
real verifier and then run through the real self-correction loop.

* ``mode == "live"``: each model is called through the gateway (``llm.call``): model A is ``muse-spark-1.3``, model B is
  Muse Spark Open on Baseten. Cost and latency are measured.
* ``mode == "mock"``: scripted stand-ins with a fixed error profile replace the models. The loop, the feedback text, the
  verifier and the scoring are all real; the *error rates are parameters, not measurements of any model*. Cost and
  latency are not reported (``null``). Every result file and table says "mock".

Live shape (assumed, unverified): one chat completion per model with the whole sheet as CSV and the task list, replying
``{"items": [{"code", "field", "value", "row", "header"}]}``; corrections use the self-correction message shape."""

import json
import random
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import llm, selfcorrect
from app.agents.context import RunContext, Sequencer
from app.schemas import Claim, ClaimFix
from app.verify import check_row_owner, verify_claim
from eval import verifier_eval as ve
from eval.sheets import COST_HEADER, MRP_HEADER, SHEET_REL, Row, World

Provider = Literal["meta", "baseten"]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    provider: Provider
    model: str | None  # None: the gateway default for the provider
    error_rate: float  # mock only
    fix_rate: float  # mock only: chance a retry after feedback is right
    stand_in: str = ""  # mock only: the name results carry instead of the model id


MODELS = [
    ModelSpec("muse-spark-1.3", "muse-spark-1.3 (model A)", "meta", None, error_rate=0.06, fix_rate=0.85, stand_in="scripted stand-in A"),
    ModelSpec("muse-spark-open", "Muse Spark Open via Baseten (model B)", "baseten", None, error_rate=0.12, fix_rate=0.60, stand_in="scripted stand-in B"),
]


@dataclass
class Task:
    code: str
    field: str  # cost | mrp
    truth: float
    row: int
    header: str


@dataclass
class Answer:
    value: float
    row: int
    header: str


class EvalItem(BaseModel):
    code: str
    field: Literal["cost", "mrp"]
    value: float
    row: int
    header: str


class EvalExtractions(BaseModel):
    items: list[EvalItem] = Field(default_factory=list)


def tasks_for(world: World, n: int) -> list[Task]:
    out = []
    for row in world.rows:
        out.append(Task(row.code, "cost", row.cost, row.row, COST_HEADER))
        out.append(Task(row.code, "mrp", row.mrp, row.row, MRP_HEADER))
    return out[:n]


def _row_of(world: World, code: str) -> Row:
    return world.by_code[code]


# ---------- the scripted stand-in ----------


def corrupt(rng: random.Random, world: World, task: Task) -> Answer:
    """A realistic slip: the answer the verifier should catch (or, for a few, fail to)."""
    kind = rng.choice(["transposition", "decimal", "paise", "other_row_value", "cites_other_row", "rounded"])
    if kind == "transposition":
        wrong = ve.swap_digits(rng, task.truth)
        if wrong is not None:
            return Answer(wrong, task.row, task.header)
    if kind == "decimal":
        return Answer(round(task.truth * rng.choice([10, 0.1]), 2), task.row, task.header)
    if kind == "paise":
        return Answer(round(task.truth * 100, 2), task.row, task.header)
    other = rng.choice([r for r in world.rows if r.code != task.code])
    other_value = other.cost if task.field == "cost" else other.mrp
    if kind == "other_row_value":
        return Answer(other_value, task.row, task.header)
    if kind == "cites_other_row":
        return Answer(other_value, other.row, task.header)
    step = 10 if task.truth >= 100 else 5
    return Answer(float(round(task.truth / step) * step) + step, task.row, task.header)


class MockAgent:
    def __init__(self, spec: ModelSpec, world: World, tasks: list[Task], seed: int) -> None:
        self.spec, self.world, self.tasks = spec, world, {f"{t.code}:{t.field}": t for t in tasks}
        self.rng = random.Random(f"{seed}:{spec.key}")
        self.calls = 0

    async def extract(self, tasks: list[Task]) -> dict[str, Answer]:
        out = {}
        for t in tasks:
            wrong = self.rng.random() < self.spec.error_rate
            out[f"{t.code}:{t.field}"] = corrupt(self.rng, self.world, t) if wrong else Answer(t.truth, t.row, t.header)
        return out

    async def ask(self, pending: list[Claim], attempt: int) -> tuple[dict[str, ClaimFix] | None, str | None]:
        self.calls += 1
        fixes = {}
        for claim in pending:
            task = self.tasks[task_key(claim)]
            good = self.rng.random() < self.spec.fix_rate
            ans = Answer(task.truth, task.row, task.header) if good else corrupt(self.rng, self.world, task)
            fixes[claim.id] = ClaimFix(claim_id=claim.id, value=ans.value, row=ans.row, header=ans.header)
        return fixes, None


def task_key(claim: Claim) -> str:
    # claim id is eval:<code>:<field>
    _, code, field = claim.id.split(":")
    return f"{code}:{field}"


# ---------- the live path ----------

SYSTEM = (
    "You read a vendor's SKU sheet and report exact numbers. Report each requested value as the sheet states it, in "
    "rupees, with the 1-based sheet row it came from (the header is row 1) and the column header. Reply with only JSON."
)


class LiveAgent:
    def __init__(self, spec: ModelSpec, world: World, tasks: list[Task], ctx: RunContext) -> None:
        self.spec, self.world, self.tasks, self.ctx = spec, world, tasks, ctx
        self.cost = 0.0
        self.latency_ms = 0.0
        self.messages: list[dict[str, Any]] = []
        self.previous = ""

    async def extract(self, tasks: list[Task]) -> dict[str, Answer]:
        sheet = (self.world.root / SHEET_REL).read_text(encoding="utf-8")
        wanted = [{"code": t.code, "field": t.field} for t in tasks]
        self.messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"SHEET (CSV):\n{sheet}\nExtract these values: {json.dumps(wanted)}\n"
             f'Reply {{"items": [{{"code", "field", "value", "row", "header"}}]}}.'},
        ]
        res = await llm.call("research", self.messages, task=f"eval_extract_{self.spec.key}", schema=EvalExtractions,
                             model=self.spec.model, provider=self.spec.provider, max_tokens=6000)
        self.cost += res.cost_usd
        self.latency_ms += res.latency_ms
        self.previous = res.content
        assert isinstance(res.parsed, EvalExtractions)
        return {f"{i.code}:{i.field}": Answer(i.value, i.row, i.header) for i in res.parsed.items}

    async def ask(self, pending: list[Claim], attempt: int) -> tuple[dict[str, ClaimFix] | None, str | None]:
        return await selfcorrect._ask(
            self.ctx, "research", f"eval_extract_{self.spec.key}", self.messages, self.previous, pending, attempt,
            model=self.spec.model, provider=self.spec.provider,
        )


# ---------- the run ----------


def _claim(task: Task, world: World, ans: Answer) -> Claim:
    return ve._sheet_claim(_row_of(world, task.code), task.field, ans.value, ev_row=ans.row, ev_header=ans.header)


def _verify(world: World, claims: list[Claim]) -> list[Claim]:
    out = []
    for c in claims:
        code = c.id.split(":")[1]
        owner = _row_of(world, code).row
        out.append(check_row_owner(verify_claim(c), code, owner))
    return out


def _right(task: Task, claim: Claim) -> bool:
    ev = claim.evidence
    return ev is not None and ev.row == task.row and ev.header == task.header and abs(claim.value - task.truth) < 1e-6


async def run_model(spec: ModelSpec, world: World, tasks: list[Task], mode: str, seed: int) -> dict:
    ctx = RunContext("run_eval", "V001", "2026-10-27", Sequencer())
    agent: MockAgent | LiveAgent = MockAgent(spec, world, tasks, seed) if mode != "live" else LiveAgent(spec, world, tasks, ctx)
    answers = await agent.extract(tasks)
    by_id: dict[str, Task] = {}
    claims = []
    for t in tasks:
        ans = answers.get(f"{t.code}:{t.field}")
        if ans is None:  # the model skipped the task: count it as a miss, not as silently absent
            ans = Answer(0.0, t.row, t.header)
        claim = _claim(t, world, ans)
        by_id[claim.id] = t
        claims.append(claim)
    first = _verify(world, claims)
    first_right = sum(1 for c in first if c.status == "verified" and _right(by_id[c.id], c))
    caught = [c for c in first if c.status == "rejected"]

    def rebuild(claim: Claim, fix: ClaimFix) -> Claim | None:
        t = by_id[claim.id]
        return _claim(t, world, Answer(fix.value, fix.row or t.row, fix.header or t.header))

    final = await selfcorrect.self_correct(
        ctx, "research", first, task=f"eval_extract_{spec.key}", messages=[], previous="",
        rebuild=rebuild, check=lambda batch: _verify(world, batch), ask=agent.ask,
    )
    corrected = [c for c in final if c.status == "verified" and len(c.attempts) > 1]
    unresolved = [c for c in final if c.status == "rejected"]
    silent = [c for c in final if c.status == "verified" and not _right(by_id[c.id], c)]
    model_calls = [e for e in _drain(ctx) if e.type == "model_call"]
    n = len(tasks)
    live = mode == "live"
    cost = round(agent.cost + sum(e.cost_usd or 0.0 for e in model_calls), 6) if live and isinstance(agent, LiveAgent) else None
    latency = (agent.latency_ms + sum(e.latency_ms or 0.0 for e in model_calls)) / n if live and isinstance(agent, LiveAgent) else None
    return {
        # Model ids appear only in live results; a mock result is a scripted stand-in and says so.
        "key": spec.key if mode == "live" else spec.stand_in.replace(" ", "_").replace("-", "_"),
        "label": spec.label if mode == "live" else spec.stand_in,
        "stand_in": mode != "live",
        "provider": spec.provider if mode == "live" else None,
        "tasks": n,
        "first_pass_accuracy": round(first_right / n, 4),
        "caught_by_verifier": len(caught),
        "corrected": len(corrected),
        "unresolved": len(unresolved),
        "self_correction_rate": round(len(corrected) / len(caught), 4) if caught else None,
        "final_accuracy": round(sum(1 for c in final if c.status == "verified" and _right(by_id[c.id], c)) / n, 4),
        "silent_errors": len(silent),
        "cost_usd": cost,
        "latency_ms_per_task": None if latency is None else round(latency, 1),
        **({"profile": {"error_rate": spec.error_rate, "fix_rate": spec.fix_rate}} if not live else {}),
    }


def _drain(ctx: RunContext) -> list[Any]:
    events = []
    while not ctx.queue.empty():
        events.append(ctx.queue.get_nowait())
    return events


async def run(world: World, mode: str, seed: int = 42, n_tasks: int = 100, models: list[ModelSpec] | None = None) -> dict:
    tasks = tasks_for(world, n_tasks)
    rows = [await run_model(m, world, tasks, mode, seed) for m in (models or MODELS)]
    return {
        "mode": mode,
        "stand_in": mode != "live",
        "seed": seed,
        "tasks": len(tasks),
        "models": rows,
        "note": (
            "Mock: scripted stand-ins with a fixed error profile replace the models. The loop, feedback, verifier and scoring "
            "are real; the error rates are parameters, not measurements. Cost and latency are not reported."
            if mode != "live"
            else "Live: models called through the gateway; cost from the ledger, latency wall-clock."
        ),
    }
