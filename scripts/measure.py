"""Entry point behind ``make eval``: run the measured eval from the repo root layout (backend env, repo root on the path),
then inject the results table into the README between the eval markers.

    cd backend && uv run python ../scripts/measure.py [--live] [--seed N] [--per-class N] [--tasks N] [--no-readme]

Mock by default (free, no network). See eval/__main__.py for the options."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for entry in (ROOT, ROOT / "backend"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def main(argv: list[str]) -> int:
    write_readme = "--no-readme" not in argv
    argv = [a for a in argv if a != "--no-readme"]
    from eval import __main__ as runner
    from eval import report

    code = runner.main(argv)
    if code == 0 and write_readme:
        readme = ROOT / "README.md"
        block = report.render(report.load())
        if report.inject(readme, block):
            print(f"\nupdated {readme.name} between the eval markers")
        else:
            print(f"\n{readme.name} has no {report.START} / {report.END} markers; nothing injected", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
