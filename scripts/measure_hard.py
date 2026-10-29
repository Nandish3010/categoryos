"""Entry point behind ``make eval-hard``: run the hard extraction eval from the repo-root layout (backend env, repo root on
the path), then inject the table into the README between the eval-hard markers.

    cd backend && uv run python ../scripts/measure_hard.py [--live] [--seed N] [--budget-usd X] [--no-readme]

Mock by default (free, no network). See eval/hard.py for the options."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for entry in (ROOT, ROOT / "backend"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def main(argv: list[str]) -> int:
    write_readme = "--no-readme" not in argv
    argv = [a for a in argv if a != "--no-readme"]
    from eval import hard, hard_report

    code = hard.main(argv)
    if code == 0 and write_readme and "--write-set" not in argv:
        result = hard_report.load()
        readme = ROOT / "README.md"
        if result and hard_report.inject(readme, hard_report.render(result)):
            print(f"\nupdated {readme.name} between the eval-hard markers")
        else:
            print(f"\n{readme.name} has no {hard_report.START} / {hard_report.END} markers; nothing injected", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
