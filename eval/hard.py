"""``make eval-hard`` / ``cd backend && PYTHONPATH=.:.. uv run python -m eval.hard``.

Runs the hard extraction set through three models and writes ``eval/results/hard.json``. Mock by default (free, no network).
``--live`` calls the real models: it needs MODEL_MODE=live, the keys, and costs credits (honours MAX_SPEND_USD and ``--budget-usd``).
``--write-set`` rewrites the committed copy of the generated set in ``eval/hard_set/``."""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.config import settings
from eval import hard_data, hard_eval, hard_report
from eval.report import RESULTS

SET_DIR = Path(__file__).resolve().parent / "hard_set"


def write_set(seed: int = 42, out: Path = SET_DIR) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in hard_data.committed_files(hard_data.build(seed)).items():
        (out / name).write_text(text, encoding="utf-8", newline="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.hard", description="CategoryOS hard-mode extraction eval")
    parser.add_argument("--live", action="store_true", help="call the real models (needs MODEL_MODE=live and keys; costs credits)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget-usd", type=float, default=3.0, help="stop calling models once this run has spent this much")
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--write-set", action="store_true", help="rewrite eval/hard_set/ from the generator and exit")
    args = parser.parse_args(argv)

    if args.write_set:
        write_set(args.seed)
        print(f"wrote {SET_DIR}")
        return 0
    if args.live and settings.effective_mode != "live":
        print("--live needs MODEL_MODE=live and MODEL_API_KEY / BASETEN_API_KEY; refusing to fall back to mock under a live label", file=sys.stderr)
        return 2
    mode = "live" if args.live else "mock"
    if mode == "live":
        print(f"RUNNING LIVE: real model calls, costs credits (this run stops at ${args.budget_usd:.2f}; cap: MAX_SPEND_USD)", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="categoryos-hard-") as tmp, hard_data.hard_root(Path(tmp), args.seed) as hs:
        result = asyncio.run(hard_eval.run(hs, mode, args.seed, budget_usd=args.budget_usd))
    args.out.mkdir(parents=True, exist_ok=True)
    result["generated_at"] = date.today().isoformat()
    (args.out / "hard.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(hard_report.render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
