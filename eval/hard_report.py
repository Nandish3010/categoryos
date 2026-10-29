"""Render the hard-mode results as markdown and inject them into the README between the eval-hard markers. Pure stdlib."""

import json
import re
from pathlib import Path

from eval.report import RESULTS, pct

START, END = "<!-- eval-hard:start -->", "<!-- eval-hard:end -->"


def load(results: Path = RESULTS) -> dict | None:
    path = results / "hard.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _cost(m: dict, key: str = "cost_usd") -> str:
    if m[key] is None:
        return "n/a (mock)"
    if m.get("cost_metered") is False:
        return "not metered"
    return f"${m[key]:.4f}"


def tables(h: dict) -> str:
    models = h["models"]

    def tok(m: dict) -> str:
        return "n/a" if m.get("input_tokens") is None else f"{m['input_tokens']} in / {m['output_tokens']} out"

    def lat(m: dict) -> str:
        if m["latency_ms_per_task"] is None:
            return "n/a (mock)"
        return f"{m['latency_ms_per_task'] / 1000:.1f} s (extract call {m['extract_call_latency_ms'] / 1000:.0f} s)"

    main = [
        "| Model | First-pass accuracy | Caught by verifier | Corrected on retry | Final accuracy (after retries) | Silent errors | Cost | Tokens | Latency / task |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        main.append(
            f"| {m['label']} | {pct(m['first_pass_accuracy'], 1)} | {m['caught_by_verifier']} | {m['corrected']} | {pct(m['final_accuracy'], 1)} "
            f"| {m['silent_errors']} | {_cost(m)} | {tok(m)} | {lat(m)} |"
        )
    esc = [
        "| Model | Rejected twice, escalated | Fixed by escalation | Final accuracy with escalation | Silent errors | Removed | Escalation cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in models:
        if m["escalation"]:
            esc.append(
                f"| {m['label']} | {m['escalated']} | {m['fixed_by_escalation']} | {pct(m['final_accuracy_with_escalation'], 1)} "
                f"| {m['silent_errors_with_escalation']} | {m['removed_with_escalation']} | {_cost(m, 'escalation_cost_usd')} |"
            )
    short = [m["label"].replace("scripted stand-in ", "") if m["stand_in"] else m["label"].split(" (")[0] for m in models]
    cat = [
        "| Category | Tasks | " + " | ".join(f"{s} first-pass" for s in short) + " | " + " | ".join(f"{s} silent" for s in short) + " |",
        "|---|---|" + "---|" * (2 * len(models)),
    ]
    for i, c in enumerate(models[0]["categories"]):
        cells = [pct(m["categories"][i]["first_pass_accuracy"]) for m in models] + [str(m["categories"][i]["silent_errors"]) for m in models]
        cat.append(f"| {c['label']} | {c['tasks']} | " + " | ".join(cells) + " |")
    return "\n".join(
        [
            f"**Hard extraction set** ({h['tasks']} tasks, mode: {h['mode']})",
            "",
            *main,
            "",
            "Escalation: a claim the verifier rejects after the normal retries is re-read once by muse-wonder-1.0 (model C runs without it).",
            "",
            *esc,
            "",
            "By category (first-pass accuracy; silent = accepted by the verifier but wrong against ground truth, after the retries):",
            "",
            *cat,
            "",
            f"_{h['note']}_",
        ]
    )


def render(h: dict) -> str:
    banner = (
        f"**Mode: {h['mode']}.** "
        + (
            "A mock run: scripted stand-ins replace the three models, so no model results are shown here. The generator, loop, verifier and scoring are real code."
            if h["mode"] != "live"
            else f"Live run: models called through the gateway, ${h['spent_usd']:.2f} spent."
        )
        + f" Seed {h['seed']}, run {h.get('generated_at', 'n/a')}."
    )
    return banner + "\n\n" + tables(h) + "\n"


def inject(readme: Path, block: str) -> bool:
    """Replace what sits between the markers. Returns False when the markers are missing."""
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return False
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: f"{START}\n{block}{END}", text, flags=re.DOTALL)
    readme.write_text(new, encoding="utf-8")
    return True
