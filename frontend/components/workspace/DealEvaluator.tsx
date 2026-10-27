"use client";

import { CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Scale, UserRound, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import {
  DECISION_LABEL,
  claimState,
  fmtMetric,
  fmtProb,
  fmtPts,
  metricNoun,
  type DealAssessment,
  type DealCounter,
  type DealDecision,
  type DealDistribution,
  type DealsData,
} from "@/lib/deals";
import { Tag } from "../Chip";
import { CopyButton } from "../CopyButton";
import { PanelHeader } from "../PanelHeader";

const DECISION_TONE: Record<DealDecision, "ok" | "bad" | "warn" | "neutral"> = {
  accept: "ok",
  reject_structure: "bad",
  needs_human: "warn",
  not_assessable: "neutral",
};
const DECISION_ICON = { accept: CheckCircle2, reject_structure: XCircle, needs_human: UserRound, not_assessable: CircleHelp } as const;

export function DecisionChip({ decision }: { decision: DealDecision }) {
  const Icon = DECISION_ICON[decision];
  return (
    <Tag tone={DECISION_TONE[decision]}>
      <Icon size={16} aria-hidden="true" />
      {DECISION_LABEL[decision]}
    </Tag>
  );
}

function Verified({ state, what }: { state: "verified" | "rejected" | "unknown"; what: string }) {
  if (state === "unknown") return null;
  return state === "verified" ? (
    <span title={`${what} verified`} className="text-ok">
      <CheckCircle2 size={16} aria-label={`${what} verified`} />
    </span>
  ) : (
    <Tag tone="bad">{what} rejected</Tag>
  );
}

// ---- probability meter ----

/** The chance of hitting the target, with the playbook's minimum marked on the bar. */
export function ProbabilityMeter({ p, min, label }: { p: number; min: number; label: string }) {
  const likely = p >= min;
  return (
    <div data-testid="probability-meter">
      <div className="text-xs text-text-dim">{label}</div>
      <div className={`num text-[36px] font-semibold leading-[40px] tracking-tight ${likely ? "text-ok" : "text-bad"}`} data-testid="probability">
        {fmtProb(p)}
      </div>
      <div className="relative mt-2 h-2 rounded-chip bg-border" role="img" aria-label={`Probability ${fmtProb(p)}; the bar to count it is ${Math.round(min * 100)}%`}>
        <div className={`h-2 rounded-chip ${likely ? "bg-ok" : "bg-bad"}`} style={{ width: `${Math.min(Math.max(p, 0.004), 1) * 100}%` }} />
        <div className="absolute -top-1 h-4 w-0.5 bg-text" style={{ left: `${min * 100}%` }} aria-hidden="true" />
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-text-dim">
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${Math.min(Math.max(min * 100, 12), 88)}%` }}>
          counts above {Math.round(min * 100)}%
        </span>
      </div>
    </div>
  );
}

// ---- what the offer is worth ----

/** Face value vs risk-adjusted vs required, in margin points. */
export function WorthBars({ a }: { a: DealAssessment }) {
  const top = Math.max(a.facePts, a.requiredPts, a.countedPts, 1) * 1.04;
  const w = (v: number) => `${Math.max((v / top) * 100, 0)}%`;
  const short = a.countedPts < a.requiredPts;
  const marker = <div className="absolute inset-y-[-2px] w-0.5 bg-warn" style={{ left: w(a.requiredPts) }} aria-hidden="true" />;
  return (
    <div data-testid="worth-bars" className="flex flex-col gap-3">
      <div>
        <div className="mb-1 flex items-baseline justify-between text-xs text-text-dim">
          <span>As the vendor states it</span>
          <span className="num text-text">{fmtPts(a.facePts)}%</span>
        </div>
        <div className="relative flex h-3 rounded-chip bg-border/60">
          <div className="h-3 rounded-l-chip bg-text-dim/60" style={{ width: w(a.basePts) }} title={`Guaranteed base ${fmtPts(a.basePts)}`} />
          <div className="h-3 border border-dashed border-text-dim/70" style={{ width: w(Math.max(a.facePts - a.basePts, 0)) }} title="Conditional bonus at face value" />
          {marker}
        </div>
      </div>
      <div>
        <div className="mb-1 flex items-baseline justify-between text-xs text-text-dim">
          <span>Risk-adjusted: what we count</span>
          <span className={`num font-medium ${short ? "text-bad" : "text-ok"}`} data-testid="counted-pts">
            {fmtPts(a.countedPts)}%
          </span>
        </div>
        <div className="relative flex h-3 rounded-chip bg-border/60">
          <div className="h-3 rounded-l-chip bg-text-dim/60" style={{ width: w(a.basePts) }} />
          <div className="h-3 bg-accent" style={{ width: w(a.countedBonusPts) }} title="Bonus we count (probability x bonus)" />
          {marker}
        </div>
      </div>
      <div className="relative h-4 text-[11px] text-warn">
        <span className="num absolute whitespace-nowrap" style={{ left: `clamp(0%, ${w(a.requiredPts)}, 72%)`, transform: "translateX(-50%)" }}>
          we need {fmtPts(a.requiredPts)}%
        </span>
      </div>
      <dl className="num grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-text-dim">Guaranteed base</dt>
          <dd>{fmtPts(a.basePts)}%</dd>
        </div>
        <div>
          <dt className="text-text-dim">Expected bonus</dt>
          <dd>+{fmtPts(a.expectedBonusPts)}</dd>
        </div>
        <div>
          <dt className="text-text-dim">Counted bonus</dt>
          <dd>+{fmtPts(a.countedBonusPts)}</dd>
        </div>
        <div>
          <dt className="text-text-dim">{a.shortfallPts >= 0 ? "Above the bar" : "Short by"}</dt>
          <dd className={a.shortfallPts >= 0 ? "text-ok" : "text-bad"}>{fmtPts(Math.abs(a.shortfallPts))} pts</dd>
        </div>
      </dl>
    </div>
  );
}

// ---- distribution chart ----

const W = 520;
const H = 170;
const PAD = { l: 8, r: 16, t: 26, b: 34 };

/** Histogram of the simulated outcome with the P10-P90 band, the P50 tick, the vendor's target line(s) and our counter. */
export function DistributionChart({ d, thresholds, counters = [] }: { d: DealDistribution; thresholds: number[]; counters?: number[] }) {
  const lo = d.bins[0] ?? 0;
  const hi = d.bins[d.bins.length - 1] ?? 1;
  const span = Math.max(hi - lo, 1e-9);
  const x = (v: number) => PAD.l + ((Math.min(Math.max(v, lo), hi) - lo) / span) * (W - PAD.l - PAD.r);
  const maxD = Math.max(...d.density, 1e-9);
  const base = H - PAD.b;
  const bw = (W - PAD.l - PAD.r) / Math.max(d.density.length, 1);
  const off = thresholds.filter((t) => t > hi);
  const inside = thresholds.filter((t) => t <= hi);
  const ours = counters.filter((t) => t >= lo && t <= hi);
  const label = `Simulated ${metricNoun(d.metric)} over ${d.windowDays} days: P10 ${fmtMetric(d.metric, d.p10)}, P50 ${fmtMetric(d.metric, d.p50)}, P90 ${fmtMetric(d.metric, d.p90)}. Target ${thresholds.map((t) => fmtMetric(d.metric, t)).join(", ")}${off.length ? ", beyond the chart" : ""}.`;
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-auto w-full" data-testid="distribution-chart">
        <rect x={x(d.p10)} y={PAD.t} width={Math.max(x(d.p90) - x(d.p10), 1)} height={base - PAD.t} className="fill-accent/10" />
        {d.density.map((v, i) => (
          <rect
            key={i}
            x={PAD.l + i * bw + 0.5}
            y={base - (v / maxD) * (base - PAD.t)}
            width={Math.max(bw - 1, 1)}
            height={(v / maxD) * (base - PAD.t)}
            className="fill-accent/55"
          />
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={base} y2={base} className="stroke-border" />
        <line x1={x(d.p50)} x2={x(d.p50)} y1={PAD.t} y2={base} className="stroke-text" strokeWidth={1.5} />
        {[
          { v: d.p10, t: "P10" },
          { v: d.p50, t: "P50" },
          { v: d.p90, t: "P90" },
        ].map((q) => (
          <g key={q.t}>
            <text x={x(q.v)} y={base + 14} textAnchor="middle" className="fill-text-dim" fontSize={12}>
              {q.t}
            </text>
            <text x={x(q.v)} y={base + 28} textAnchor="middle" className="fill-text-dim" fontSize={12}>
              {fmtMetric(d.metric, q.v)}
            </text>
          </g>
        ))}
        {ours.map((t) => (
          <g key={`c${t}`}>
            <line x1={x(t)} x2={x(t)} y1={PAD.t - 4} y2={base} className="stroke-ok" strokeWidth={2} />
            <text x={x(t)} y={PAD.t - 8} textAnchor="start" className="fill-ok" fontSize={12}>
              our counter {fmtMetric(d.metric, t)}
            </text>
          </g>
        ))}
        {inside.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={PAD.t - 4} y2={base} className="stroke-warn" strokeWidth={2} strokeDasharray="4 3" />
            <text x={x(t)} y={PAD.t - 8} textAnchor="end" className="fill-warn" fontSize={12}>
              their target {fmtMetric(d.metric, t)}
            </text>
          </g>
        ))}
        {off.length ? (
          <g>
            <line x1={W - PAD.r} x2={W - PAD.r} y1={PAD.t - 4} y2={base} className="stroke-warn" strokeWidth={2} strokeDasharray="4 3" />
            <text x={W - PAD.r - 6} y={PAD.t - 8} textAnchor="end" className="fill-warn" fontSize={12}>
              their target {off.map((t) => fmtMetric(d.metric, t)).join(" / ")} →
            </text>
          </g>
        ) : null}
      </svg>
      <figcaption className="num mt-1 text-xs text-text-dim">
        Over {d.windowDays} days, {metricNoun(d.metric)}: P10 {fmtMetric(d.metric, d.p10)} · P50 {fmtMetric(d.metric, d.p50)} · P90 {fmtMetric(d.metric, d.p90)}
      </figcaption>
    </figure>
  );
}

// ---- counters ----

const KIND_LABEL: Record<string, string> = {
  threshold: "Lower the target",
  window: "Give more time",
  scope: "Narrow the scope",
  convert_to_base: "Make it guaranteed",
};

function Counters({ a }: { a: DealAssessment }) {
  if (!a.counters.length) return null;
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Counter with</h4>
      <ol className="flex flex-col gap-2" data-testid="counters">
        {a.counters.map((c: DealCounter, i) => {
          const rec = a.recommendedCounter === i;
          return (
            <li
              key={`${c.kind}-${i}`}
              data-kind={c.kind}
              data-recommended={rec}
              className={`rounded-card border p-3 text-sm ${rec ? "border-accent/60 bg-accent/10" : "border-border bg-surface-2"}`}
            >
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="font-medium">{KIND_LABEL[c.kind] ?? c.kind}</span>
                {rec ? <Tag tone="accent">Recommended</Tag> : null}
                {c.meetsRequirement ? <Tag tone="ok">Meets our bar</Tag> : <Tag tone="warn">Still short</Tag>}
                {c.probability != null ? <span className="num text-xs text-text-dim">P {fmtProb(c.probability)}</span> : null}
                <span className="num ml-auto text-xs text-text-dim">counts {fmtPts(c.countedPtsAfter)}% vs {fmtPts(a.requiredPts)}%</span>
              </div>
              <p className="text-text-dim">{c.text.charAt(0).toUpperCase() + c.text.slice(1)}</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ---- one card ----

function Block({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-card border border-border bg-surface-2 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-text-dim">{title}</h4>
        {right}
      </div>
      {children}
    </section>
  );
}

export function DealCard({
  a,
  deals,
  open,
  onToggle,
  onShowQuote,
}: {
  a: DealAssessment;
  deals: DealsData;
  open: boolean;
  onToggle: () => void;
  onShowQuote?: (turn: number, quote: string) => void;
}) {
  const quoteState = claimState(deals.claimStatus, `:dealterm:${a.termId}:`);
  const probState = claimState(deals.claimStatus, `:deal:${a.termId}:deal_probability:`);
  const min = deals.assumptions.minProbability;
  const d = a.distribution;
  const thresholds = a.tiers.map((t) => t.threshold);
  const hasProb = a.probability != null && d != null;
  const isTrade = a.netPts != null;
  return (
    <article id={`deal-${a.termId}`} data-testid="deal-card" data-decision={a.decision} aria-label={`Deal: ${a.label}`} className="rounded-card border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-2 px-4 py-3">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`deal-body-${a.termId}`}
          onClick={onToggle}
          className="inline-flex min-h-8 min-w-0 flex-1 items-start gap-2 text-left"
        >
          {open ? <ChevronDown size={16} className="mt-1 shrink-0" aria-hidden="true" /> : <ChevronRight size={16} className="mt-1 shrink-0" aria-hidden="true" />}
          <span className="min-w-0">
            <span className="block text-xs text-text-dim">{a.kind.replace(/_/g, " ")} offer · {a.source === "application" ? `application term ${a.turn}` : `vendor, turn ${a.turn}`}</span>
            <span className="block text-sm font-semibold">{a.label}</span>
          </span>
        </button>
        <DecisionChip decision={a.decision} />
      </header>
      {open ? (
        <div id={`deal-body-${a.termId}`} className="flex flex-col gap-3 border-t border-border p-4">
          <p className="text-sm" data-testid="deal-call">
            {a.call}
          </p>
          {hasProb ? (
            <div className="grid gap-3 md:grid-cols-2">
              <Block
                title={a.tiers.length > 1 ? "Chance of the first target" : "Chance of hitting the target"}
                right={<Verified state={probState} what="Probability" />}
              >
                <ProbabilityMeter
                  p={a.probability ?? 0}
                  min={min}
                  label={`${fmtMetric(d.metric, a.tiers[0]?.threshold ?? d.threshold)} ${metricNoun(d.metric)} in ${d.windowDays} days`}
                />
                {a.tiers.length > 1 ? (
                  <ul className="num mt-3 flex flex-col gap-1 text-xs" data-testid="tiers">
                    {a.tiers.map((t, i) => (
                      <li key={i} className="flex items-center justify-between gap-2">
                        <span>
                          Tier {i + 1}: {fmtMetric(d.metric, t.threshold)} → {t.bonusPts}% bonus
                        </span>
                        <span className="flex items-center gap-2">
                          {fmtProb(t.probability)}
                          <Tag tone={t.counted ? "ok" : "neutral"}>{t.counted ? "counts" : "counts as 0"}</Tag>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </Block>
              <Block title="What the offer is worth (margin points)">
                <WorthBars a={a} />
              </Block>
            </div>
          ) : isTrade ? (
            <Block title="Net value after costs">
              <div className={`num text-[28px] font-semibold ${a.netPts! >= 0 ? "text-ok" : "text-bad"}`}>
                {a.netPts! >= 0 ? "+" : "−"}
                {fmtPts(Math.abs(a.netPts!))} pts
              </div>
            </Block>
          ) : null}
          {d && d.bins.length > 1 ? (
            <Block title="Simulated outcome">
              <DistributionChart d={d} thresholds={thresholds} counters={a.counters.filter((c) => c.kind === "threshold" && c.threshold != null).map((c) => c.threshold!)} />
            </Block>
          ) : null}
          <Counters a={a} />
          <details className="text-sm">
            <summary className="cursor-pointer text-text-dim">How this was worked out</summary>
            <ul className="mt-2 list-disc pl-5 text-text-dim">
              {a.reasoning.map((r) => (
                <li key={r}>{r}</li>
              ))}
              <li>
                Simulation: {deals.assumptions.mcDraws.toLocaleString("en-IN")} draws, seed {deals.assumptions.seed}, {Math.round(deals.assumptions.cv * 100)}% forecast uncertainty, ramp{" "}
                {deals.assumptions.rampByMonth.map((r) => `${Math.round(r * 100)}%`).join(" / ")}. Edit these in the Playbook (Negotiation).
              </li>
            </ul>
          </details>
          {a.quote ? (
            <blockquote className="border-l-2 border-border pl-3 text-sm text-text-dim">
              “{a.quote}” <Verified state={quoteState} what="Quote" />
              {a.source === "transcript" && onShowQuote ? (
                <button type="button" onClick={() => onShowQuote(a.turn, a.quote)} className="ml-2 inline-flex min-h-8 items-center text-xs text-accent hover:underline">
                  Show on the call
                </button>
              ) : null}
            </blockquote>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

// ---- the section ----

export function DealEvaluator({
  deals,
  isOpen,
  onToggle,
  onShowQuote,
}: {
  deals: DealsData;
  isOpen: (a: DealAssessment) => boolean;
  onToggle: (id: string) => void;
  onShowQuote?: (turn: number, quote: string) => void;
}) {
  const total = deals.verification;
  return (
    <section aria-label="Deal evaluator" className="rounded-card border border-border bg-surface" data-testid="deal-evaluator" data-decision={deals.decision}>
      <PanelHeader
        title="Deal evaluator: conditional offers"
        right={
          <span className="flex items-center gap-2">
            <Scale size={16} aria-hidden="true" />
            {total ? <span className="num">{total.verified}/{total.total} figures verified</span> : null}
          </span>
        }
      />
      <div className="flex flex-col gap-3 p-4">
        <p className="text-sm text-text-dim">
          A conditional bonus only counts if we are likely to earn it. The agent reads the offer; Python simulates demand, prices the bonus at probability × value, and decides. Bonuses under a{" "}
          {Math.round(deals.assumptions.minProbability * 100)}% chance count as zero.
        </p>
        {deals.assessments.map((a) => (
          <DealCard key={a.termId} a={a} deals={deals} open={isOpen(a)} onToggle={() => onToggle(a.termId)} onShowQuote={onShowQuote} />
        ))}
        {deals.rejectedTerms.length ? (
          <div role="status" className="rounded-card border border-warn/40 bg-warn/10 p-3 text-sm">
            <div className="font-medium">Not valued: could not verify against the call</div>
            <ul className="mt-1 list-disc pl-5 text-text-dim">
              {deals.rejectedTerms.map((r) => (
                <li key={r.id}>
                  {r.label}: {r.reasons.join("; ")}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {deals.talk ? (
          <div className="grid gap-3 md:grid-cols-2" data-testid="deal-talk">
            <Block title="What to say" right={<CopyButton text={deals.talk.talkTrack} />}>
              <p className="text-sm">{deals.talk.talkTrack}</p>
            </Block>
            <Block title="For the follow-up email" right={<CopyButton text={deals.talk.emailParagraph} />}>
              <p className="text-sm">{deals.talk.emailParagraph}</p>
            </Block>
            <p className="text-xs text-text-dim md:col-span-2">
              {deals.talk.source === "model" ? "Written by the agent from the figures above." : "Standard wording built from the figures above."}
              {deals.talk.struck.length ? ` ${deals.talk.struck.length} sentence(s) removed: they stated a number the evaluator did not produce.` : ""}
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
