"""Shared run context handed to every agent: a monotonic event sequencer and an emit() that builds TraceEvents."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.schemas import StageResult, TraceEvent, TraceType


class Sequencer:
    """Per-run monotonic event ids and the run's relative clock (shared by all stages and replans)."""

    def __init__(self, start_seq: int = 0, elapsed_ms: float = 0.0) -> None:
        self._seq = start_seq
        self._t0 = time.perf_counter() - elapsed_ms / 1000

    def next(self) -> int:
        self._seq += 1
        return self._seq

    def t_rel_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)


@dataclass
class RunContext:
    run_id: str
    vendor_id: str
    today: str
    sequencer: Sequencer
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    result: StageResult | None = None  # set by runner.run_stage when the stage ends
    results: dict[str, StageResult] = field(default_factory=dict)  # set by runner.run_stages (multi-stage agents)

    def emit(
        self,
        type: TraceType,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
        *,
        model: str | None = None,
        latency_ms: float | None = None,
        cost_usd: float | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            seq=self.sequencer.next(),
            run_id=self.run_id,
            t_rel_ms=self.sequencer.t_rel_ms(),
            type=type,
            stage=stage,
            model=model,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            payload=payload or {},
        )
        self.queue.put_nowait(event)
        return event

    def step_emitter(self, stage: str) -> Callable[[dict[str, Any]], None]:
        """Callback for llm.run_tools: one tool_call event per executed step."""

        def on_step(step: dict[str, Any]) -> None:
            self.emit(
                "tool_call",
                stage,
                {"tool": step["tool"], "args": step["args"], "result_summary": step["result_summary"]},
                latency_ms=step.get("latency_ms"),
            )

        return on_step
