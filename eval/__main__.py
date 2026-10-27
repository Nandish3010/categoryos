"""``make eval`` / ``cd backend && PYTHONPATH=.:.. uv run python -m eval``.

Runs the verifier, agent and injection checks and writes ``eval/results/*.json``. Mock by default (free, no network).
``--live`` runs the agent and model-detector checks against the real models: it needs MODEL_MODE=live, the keys and
costs credits (honours MAX_SPEND_USD)."""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.config import settings
from eval import agent_eval, injection_eval, report, sheets, verifier_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval", description="CategoryOS measured eval")
    parser.add_argument("--live", action="store_true", help="call the real models (needs MODEL_MODE=live and keys; costs credits)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-class", type=int, default=25, help="planted errors (and matched controls) per class; 8 classes")
    parser.add_argument("--tasks", type=int, default=160, help="extraction tasks per model")
    parser.add_argument("--out", type=Path, default=report.RESULTS)
    args = parser.parse_args(argv)

    if args.live and settings.effective_mode != "live":
        print("--live needs MODEL_MODE=live and MODEL_API_KEY / BASETEN_API_KEY; refusing to fall back to mock under a live label", file=sys.stderr)
        return 2
    mode = "live" if args.live else "mock"
    if mode == "live":
        print("RUNNING LIVE: real model calls, costs credits (cap: MAX_SPEND_USD)", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="categoryos-eval-") as tmp, sheets.data_root(Path(tmp), args.seed) as world:
        verifier = verifier_eval.run(world, args.seed, args.per_class)
        agent = asyncio.run(agent_eval.run(world, mode, args.seed, args.tasks))
    args.out.mkdir(parents=True, exist_ok=True)  # persist paid agent results before the injection stage can fail
    for name, data in (("verifier", verifier), ("agent", agent)):
        (args.out / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    injection = asyncio.run(injection_eval.run(mode, injection_eval.live_model_detect if mode == "live" else None))

    args.out.mkdir(parents=True, exist_ok=True)
    meta = {"mode": mode, "seed": args.seed, "generated_at": date.today().isoformat()}
    for name, data in (("verifier", verifier), ("agent", agent), ("injection", injection), ("meta", meta)):
        (args.out / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(report.render(report.load(args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
