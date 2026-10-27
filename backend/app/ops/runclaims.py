"""A claim registry for a Run module: metric name -> unit, source file and a function that recomputes it from the data.

The weekly review, PO chaser and catalog queue each carry their own copy of this logic; the promotions planner and the price
monitor share this one. A metric function takes the claim key (``subject`` or ``subject?name=value&...``) and returns the number,
or raises a typed error. Never imports llm."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import policy
from app.errors import CategoryOSError, MissingInput, UnknownOpsMetric
from app.ops.figures import parse_shown
from app.ops.schemas import Figure
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Evidence, SourceRef
from app.verify import _finish

_SIGNED = re.compile(r"^\s*[+-]")


def split_key(key: str) -> tuple[str, dict[str, str]]:
    """``E005:LT-01?mp=MarketB`` -> (``E005:LT-01``, {mp: MarketB})."""
    subject, _, query = key.partition("?")
    return subject, dict(p.split("=", 1) for p in query.split("&") if "=" in p)


def build_key(subject: str, **params: Any) -> str:
    live = {k: v for k, v in params.items() if v is not None}
    return subject + ("?" + "&".join(f"{k}={v}" for k, v in live.items()) if live else "")


def rounded(value: float, unit: str) -> float:
    if unit == "pct":
        return round(value, 4)
    if unit == "inr":
        return round(value, 2)
    if unit in ("ratio", "pts"):
        return round(value, 2)
    return float(round(value))


@dataclass(frozen=True)
class Metric:
    unit: str
    file: str
    label: str
    fn: Callable[[str], float | None]


class Registry:
    def __init__(self, metrics: dict[str, Metric], data_sha: Callable[[], str], prefix: str) -> None:
        self.metrics, self.data_sha, self.prefix = metrics, data_sha, prefix

    def handles(self, claim: Claim) -> bool:
        return claim.metric in self.metrics and claim.origin != "model_extraction"

    def unit_of(self, metric: str) -> str:
        if metric not in self.metrics:
            raise UnknownOpsMetric(metric)
        return self.metrics[metric].unit

    def compute(self, metric: str, key: str) -> float:
        if metric not in self.metrics:
            raise UnknownOpsMetric(metric)
        mdef = self.metrics[metric]
        value = mdef.fn(key)
        if value is None:
            raise MissingInput(f"{metric} has no value for {key!r}", fix="The data has too few rows for this subject")
        return rounded(float(value), mdef.unit)

    def engine_claim(self, metric: str, key: str, text: str, *, value: float | None = None, claim_id: str | None = None) -> Claim:
        """With ``value`` omitted the engine value is used; with it set, the value is what the agent wrote and the verifier will check it."""
        mdef = self.metrics[metric]
        shown = self.compute(metric, key) if value is None else rounded(float(value), mdef.unit)
        subject, _ = split_key(key)
        return Claim(
            id=claim_id or f"{key}:{metric}",
            text=text,
            value=shown,
            metric=metric,
            unit=mdef.unit,  # type: ignore[arg-type]
            sku_key=subject if re.fullmatch(r"E\d{3}:[A-Z]{2}-\d{2}", subject) else None,
            source_ref=SourceRef(file=mdef.file, key=key, column=metric),
            evidence=Evidence(normalized_value=shown, parser_version=PARSER_VERSION, sha256=self.data_sha()),
            origin="engine",
        )

    def figure_claim(self, fig: Figure, claim_id: str) -> Claim:
        """The claim for one figure the agent wrote in prose. If the prose number disagrees with the engine, the prose number is what gets checked."""
        value = fig.value
        if fig.metric in self.metrics:
            unit = self.metrics[fig.metric].unit
            parsed = parse_shown(fig.shown, unit)
            if parsed is not None:
                try:
                    engine: float | None = self.compute(fig.metric, fig.key)
                except (CategoryOSError, ValueError):
                    engine = None
                signed = bool(_SIGNED.match(fig.shown))
                shown_value = parsed[0] if signed or engine is None else abs(parsed[0]) * (1 if fig.value >= 0 else -1)
                if engine is not None and abs(shown_value - engine) > parsed[1]:
                    value = shown_value  # the prose says something the engine does not
            return self.engine_claim(fig.metric, fig.key, fig.text, value=value, claim_id=claim_id)
        return Claim(  # an unregistered metric: kept so the verifier reports it unverifiable
            id=claim_id,
            text=fig.text,
            value=fig.value,
            metric=fig.metric,
            unit="ratio",
            source_ref=SourceRef(file=next(iter(self.metrics.values())).file, key=fig.key, column=fig.metric),
            evidence=Evidence(parser_version=PARSER_VERSION, sha256=self.data_sha()),
            origin="engine",
        )

    def verify(self, claim: Claim) -> Claim:
        if claim.metric not in self.metrics:
            return _finish(claim, "unverifiable", f"unknown metric {claim.metric!r}")
        if claim.evidence is not None and claim.evidence.sha256 != self.data_sha():
            return _finish(claim, "rejected", "source changed: evidence sha256 does not match the data")
        try:
            recomputed = self.compute(claim.metric, claim.source_ref.key)
        except (CategoryOSError, ValueError, KeyError) as exc:
            return _finish(claim, "rejected", f"cannot recompute: {getattr(exc, 'problem', str(exc))}")
        if abs(recomputed - claim.value) <= policy.tol(claim.unit):
            return _finish(claim, "verified", None, recomputed)
        return _finish(claim, "rejected", f"engine recomputed {recomputed:g}, claim says {claim.value:g}", recomputed)

    def catalogue(self, forms: dict[str, str]) -> str:
        """Prompt text: one line per metric with its unit and key form (forms: metric -> key example)."""
        return "\n".join(f"- {name}: {m.unit}, key like {forms.get(name, '')} ({m.label})" for name, m in self.metrics.items())


def strike(text: str, figures: list[Figure], verified: list[bool]) -> tuple[str, list[str]]:
    """Keep the sentences whose every number is covered by a VERIFIED figure. A number with no figure, or whose figure the verifier
    rejected, takes its sentence out. Returns (kept text, struck sentences); line breaks are kept."""
    from app.ops import figures as fg

    ok = [f for f, good in zip(figures, verified) if good]
    kept_lines: list[str] = []
    struck: list[str] = []
    for raw in text.strip().split("\n"):
        if not raw.strip():
            kept_lines.append("")
            continue
        keep = []
        for sentence in re.split(r"(?<=[.!?])\s+", raw):
            if fg.check_text([sentence], ok):
                struck.append(sentence.strip())
            else:
                keep.append(sentence)
        if keep:
            kept_lines.append(" ".join(keep))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip(), struck


def fmt_shown(unit: str, value: float) -> str:
    """A claim value as the number is written in prose: 0.12 pct -> 12.0%, 566 inr -> ₹566, 9 units -> 9."""
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit == "inr":
        return f"₹{value:,.0f}"
    if unit in ("ratio", "pts"):
        return f"{value:.2f}"
    return f"{value:,.0f}"


def compact(claim: Claim) -> dict[str, Any]:
    """A claim as the pages need it (the shape of ``Claim`` in the frontend): evidence is cut to the quote and its row, and only kept for
    a model extraction; hashes and parser versions stay out of the payload."""
    out = claim.model_dump(mode="json")
    ev = out.pop("evidence", None)
    keep = ("row", "header", "raw_value", "normalized_value")
    out["evidence"] = {k: ev[k] for k in keep if ev.get(k) is not None} if ev and claim.origin == "model_extraction" else None
    return out
