"""Render the eval results as markdown and inject them into the README between markers. Pure stdlib so
``scripts/inject_eval_readme.py`` can use it without the backend environment."""

import json
import re
from pathlib import Path

START, END = "<!-- eval:start -->", "<!-- eval:end -->"
RESULTS = Path(__file__).resolve().parent / "results"


def pct(x: float | None, digits: int = 0) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def load(results: Path = RESULTS) -> dict:
    out = {}
    for name in ("verifier", "agent", "injection", "meta"):
        path = results / f"{name}.json"
        if path.exists():
            out[name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def verifier_table(v: dict) -> str:
    lines = [
        "| Error class | Planted | Caught | Recall | Recall (error above tolerance) | False positives (of matched controls) | Precision |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in v["classes"]:
        lines.append(
            f"| {c['label']} | {c['planted']} | {c['caught']} | {pct(c['recall'])} | {pct(c['recall_beyond_tolerance'])} "
            f"({c['caught_beyond_tolerance']}/{c['beyond_tolerance']}) | {c['false_positives']} of {c['controls']} | {pct(c['precision'])} |"
        )
    o = v["overall"]
    lines.append(
        f"| **All** | {o['planted']} | {o['caught']} | {pct(o['recall'], 1)} | {pct(o['recall_beyond_tolerance'], 1)} | "
        f"{o['false_positives']} of {o['controls']} | {pct(o['precision'], 1)} |"
    )
    return "\n".join(lines)


def agent_table(a: dict) -> str:

    def cost(m: dict) -> str:
        return "n/a (mock)" if m["cost_usd"] is None else f"${m['cost_usd']:.4f}"

    def lat(m: dict) -> str:
        return "n/a (mock)" if m["latency_ms_per_task"] is None else f"{m['latency_ms_per_task']:.0f} ms"

    lines = [
        "| Model | First-pass accuracy | Caught by verifier | Corrected on retry | Self-correction rate | Final accuracy | Silent errors | Cost | Latency / task |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in a["models"]:
        lines.append(
            f"| {m['label']} | {pct(m['first_pass_accuracy'], 1)} | {m['caught_by_verifier']} | {m['corrected']} | "
            f"{pct(m['self_correction_rate'])} | {pct(m['final_accuracy'], 1)} | {m['silent_errors']} | {cost(m)} | {lat(m)} |"
        )
    return "\n".join(lines)


def injection_table(i: dict) -> str:
    model = i["model"]
    model_cell = f"{i['model']['detected']}/{i['injections']} ({pct(model['rate'])})" if model.get("ran") else "not run (mock)"
    rx = i["regex"]
    model_fp = f"{model['false_positives']}/{i['benign']}" if model.get("ran") else "not run (mock)"
    lines = [
        "| Detector | Injections caught | Benign texts wrongly flagged |",
        "|---|---|---|",
        (f"| Regex guard (playbook `screening.injection_patterns`) | {rx['detected']}/{i['injections']} ({pct(rx['rate'])}) "
        f"| {rx['false_positives']}/{i['benign']} ({pct(rx['false_positive_rate'])}) |"),
        f"| Model | {model_cell} | {model_fp} |",
        f"| Regex + model | {i['combined']['detected']}/{i['injections']} ({pct(i['combined']['rate'])}) | |",
    ]
    return "\n".join(lines)


def render(results: dict) -> str:
    meta = results.get("meta", {})
    mode = meta.get("mode", "mock")
    banner = (
        f"**Mode: {mode}.** "
        + (
            "These numbers come from a mock run: the verifier and injection checks are real code on synthetic data, but the "
            "agent rows use scripted stand-ins for the models, so they are NOT measurements of Muse Spark."
            if mode != "live"
            else "Live run: models called through the gateway."
        )
        + f" Seed {meta.get('seed', 42)}, run {meta.get('generated_at', 'n/a')}."
    )
    parts = [banner, ""]
    if "verifier" in results:
        parts += ["**Verifier** (no model; synthetic sheet, planted errors, matched correct controls)", "", verifier_table(results["verifier"]), ""]
        parts += [
            "Misses are errors smaller than the playbook tolerance (₹1 on money, 1 point on percentages), which the verifier accepts by design.",
            "",
        ]
    if "agent" in results:
        a = results["agent"]
        parts += [f"**Extraction agent** ({a['tasks']} tasks, mode: {a['mode']})", "", agent_table(a), "", f"_{a['note']}_", ""]
    if "injection" in results:
        parts += ["**Prompt injection** (30 variants hidden in vendor text, 30 look-alike benign texts)", "", injection_table(results["injection"]), ""]
    return "\n".join(parts).rstrip() + "\n"


def inject(readme: Path, block: str) -> bool:
    """Replace what sits between the markers. Returns False when the markers are missing."""
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return False
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: f"{START}\n{block}{END}", text, flags=re.DOTALL)
    readme.write_text(new, encoding="utf-8")
    return True
