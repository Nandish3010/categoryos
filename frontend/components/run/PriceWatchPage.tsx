"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { inr, pct, pctSigned } from "@/lib/format";
import { unverified } from "@/lib/ops";
import { pctNumber } from "@/lib/promotions";
import {
  approveAction,
  approveLabel,
  chartLines,
  daysUnder,
  effectText,
  fetchPriceWatch,
  isBlip,
  kindLabel,
  recommendationLabel,
  recommendationTone,
  rejectAction,
  stateLabel,
  stateTone,
  type ChartLine,
  type PriceWatch,
  type PwAction,
  type PwDecision,
  type PwSku,
  type PwThresholds,
} from "@/lib/priceWatch";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { DraftCard } from "./DraftCard";
import { ModeTags, Paragraphs, StruckNote } from "./RunBits";
import { RunShell } from "./RunShell";
import { VerifierPanel } from "./VerifierPanel";

const btn = "inline-flex h-11 items-center gap-1.5 rounded-card px-4 text-sm disabled:opacity-50";

// ---------- chart ----------

const W = 640;
const H = 200;
const PAD = { l: 44, r: 8, t: 8, b: 20 };
const STROKE: Record<ChartLine["role"], string> = {
  ours: "var(--color-accent)",
  competitor: "var(--color-text-dim)",
  vendor: "var(--color-bad)",
  map: "var(--color-bad)",
};
const COMPETITOR_STROKES = ["var(--color-warn)", "var(--color-ok)", "var(--color-text-dim)"];

/** Price lines over the scan window: ours flat, each marketplace, and the vendor storefront on breach cards. */
export function PriceChart({ action, highlight }: { action: PwAction; highlight?: string }) {
  const lines = chartLines(action);
  const n = action.series.dates.length;
  if (n < 2) return null;
  const all = lines.flatMap((l) => l.values);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
  let ci = 0;
  const colored = lines.map((l) => ({ ...l, stroke: l.role === "competitor" ? COMPETITOR_STROKES[ci++ % COMPETITOR_STROKES.length] : STROKE[l.role] }));
  const label = `Price chart for ${action.name}, ${action.series.dates[0]} to ${action.series.dates[n - 1]}: ${lines.map((l) => l.label).join(", ")}`;
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-auto w-full">
        <line x1={PAD.l} y1={y(hi)} x2={W - PAD.r} y2={y(hi)} stroke="var(--color-border)" strokeWidth="1" />
        <line x1={PAD.l} y1={y(lo)} x2={W - PAD.r} y2={y(lo)} stroke="var(--color-border)" strokeWidth="1" />
        <text x={PAD.l - 6} y={y(hi) + 4} textAnchor="end" fontSize="11" fill="var(--color-text-dim)">{inr(hi)}</text>
        <text x={PAD.l - 6} y={y(lo) + 4} textAnchor="end" fontSize="11" fill="var(--color-text-dim)">{inr(lo)}</text>
        <text x={PAD.l} y={H - 4} fontSize="11" fill="var(--color-text-dim)">{action.series.dates[0].slice(5)}</text>
        <text x={W - PAD.r} y={H - 4} textAnchor="end" fontSize="11" fill="var(--color-text-dim)">{action.series.dates[n - 1].slice(5)}</text>
        {colored.map((l) => (
          <polyline
            key={l.key}
            points={l.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={l.stroke}
            strokeWidth={l.role === "ours" || l.key === highlight || l.role === "vendor" ? 2.25 : 1.25}
            strokeDasharray={l.dashed ? "5 4" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-dim">
        {colored.map((l) => (
          <span key={l.key} className="inline-flex items-center gap-1.5">
            <svg width="16" height="8" aria-hidden="true"><line x1="0" y1="4" x2="16" y2="4" stroke={l.stroke} strokeWidth="2" strokeDasharray={l.dashed ? "4 3" : undefined} /></svg>
            {l.label}
            <span className="num">{inr(l.values[l.values.length - 1])}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

// ---------- action card ----------

function Fact({ label, value, tone }: { label: string; value: string; tone?: "bad" | "ok" }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-text-dim">{label}</dt>
      <dd className={`num text-sm font-medium ${tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : ""}`}>{value}</dd>
    </div>
  );
}

function KeyNumbers({ a, th }: { a: PwAction; th: PwThresholds }) {
  const c = a.competitor;
  const v = a.vendor;
  const facts: { label: string; value: string; tone?: "bad" | "ok" }[] = [{ label: "Our price", value: inr(a.our_price) }];
  if (c) {
    const days = daysUnder(a.series, c.marketplace, th.undercut_threshold_pct);
    if (a.kind === "trend") {
      facts.push({ label: `Competitor on ${c.marketplace}`, value: inr(c.price) });
      if (c.slope_pct_per_day != null) facts.push({ label: "Trend", value: `${pctSigned(c.slope_pct_per_day, 2)} a day` });
    } else {
      facts.push({ label: `Competitor on ${c.marketplace}`, value: `${inr(c.price)}${c.cut_pct != null ? `, ${pct(c.cut_pct)} below us` : ""}` });
      facts.push({ label: "Days in a row", value: `${days} ${days === 1 ? "day" : "days"}` });
      if (c.match_price != null) facts.push({ label: "Match price", value: `${inr(c.match_price)}${c.cut_pct != null ? ` (cut ${pct(c.cut_pct)})` : ""}` });
      if (c.margin_now_pct != null && c.margin_after_match_pct != null)
        facts.push({ label: "Margin now, after match, floor", value: `${pct(c.margin_now_pct)}, ${pct(c.margin_after_match_pct)}, ${pct(c.floor_pct)}`, tone: c.floor_pct != null && c.margin_after_match_pct < c.floor_pct ? "bad" : "ok" });
      if (c.margin_impact_inr != null)
        facts.push({ label: `${c.horizon_days ?? th.horizon_days}-day margin, match vs hold`, value: `${c.margin_impact_inr >= 0 ? "+" : "−"}${inr(Math.abs(c.margin_impact_inr))}`, tone: c.margin_impact_inr >= 0 ? "ok" : "bad" });
      if (c.protection_ask_unit_inr != null && a.recommendation === "ask_vendor_funding")
        facts.push({ label: "Price protection ask", value: `${inr(c.protection_ask_unit_inr)} a unit, ${inr(c.protection_ask_inr)} in all` });
    }
  }
  if (v) {
    facts.push({ label: `Vendor on ${v.marketplace}`, value: `${inr(v.price)}, ${pct(v.gap_below_pct)} under ours`, tone: "bad" });
    facts.push({ label: "Days in breach", value: `${v.parity_days} ${v.parity_days === 1 ? "day" : "days"}` });
    if (v.map_price != null) facts.push({ label: "MAP price", value: `${inr(v.map_price)}${v.map_breach ? `, under it for ${v.map_days} days` : ""}` });
    facts.push({ label: "Margin at risk", value: inr(v.lost_margin_inr), tone: "bad" });
  }
  return (
    <dl aria-label="Key numbers" className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-3">
      {facts.map((f) => (
        <Fact key={f.label} {...f} />
      ))}
    </dl>
  );
}

export function ActionCard({ a, th, onDone }: { a: PwAction; th: PwThresholds; onDone: (needsRefresh: boolean) => void }) {
  const [decision, setDecision] = useState<PwDecision>(a.decision);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const c = a.competitor;
  const verified = a.claims.filter((x) => x.status === "verified").length;
  const pending = decision.status === "pending";

  const act = async (fn: () => Promise<PwDecision>) => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await fn();
      setDecision(r);
      onDone(r.effect?.type === "vendor_message");
    } catch (e) {
      if (e instanceof ApiError) setProblem(e);
      else throw e;
    } finally {
      setBusy(false);
    }
  };

  return (
    <article aria-label={`Action ${a.id}`} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{a.name}</div>
          <div className="num text-xs text-text-dim">
            {a.sku_code} {"·"} <Link href={`/run/vendors/${a.vendor_id}`} className="text-accent hover:underline">{a.brand}</Link>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Tag tone={a.kind === "breach" ? "bad" : a.kind === "undercut" ? "warn" : "neutral"}>{kindLabel(a.kind)}</Tag>
          <Tag tone={recommendationTone(a.recommendation)}>{recommendationLabel(a.recommendation)}</Tag>
        </div>
      </div>

      <div className="flex flex-col gap-3 p-4">
        {isBlip(a) && c ? (
          <Banner tone="info" title="Not matched: this was a blip">
            {inr(c.price)} on {c.marketplace} lasted {daysUnder(a.series, c.marketplace, th.undercut_threshold_pct)} {daysUnder(a.series, c.marketplace, th.undercut_threshold_pct) === 1 ? "day" : "days"}, under the {th.min_sustained_days} days that make an undercut sustained.
            {c.margin_impact_inr != null ? ` Matching would have cost ${inr(Math.abs(c.margin_impact_inr))} of margin over ${c.horizon_days ?? th.horizon_days} days.` : ""} We re-check tomorrow.
          </Banner>
        ) : null}
        <ul aria-label="Reasons" className="list-disc pl-5 text-sm">
          {a.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <KeyNumbers a={a} th={th} />
        <PriceChart action={a} highlight={c?.marketplace} />
        <div className="text-xs text-text-dim">
          <span className="num">{verified}/{a.claims.length} verified</span> numbers on this card
          {a.email_id ? <span>{" "}{"·"} message {a.email_id} waits in Vendor messages</span> : null}
        </div>

        {problem ? <Banner tone="bad" title={problem.body.problem}>{problem.body.cause} {problem.body.fix}</Banner> : null}
        {pending ? (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" disabled={busy} onClick={() => act(() => approveAction(a.id))} aria-label={`${approveLabel(a)} ${a.sku_code}`} className={`${btn} bg-accent font-semibold text-bg`}>
              <Check size={16} aria-hidden="true" /> {approveLabel(a)}
            </button>
            <button type="button" disabled={busy} onClick={() => act(() => rejectAction(a.id))} aria-label={`Reject ${a.sku_code}`} className={`${btn} border border-border text-text-dim hover:bg-surface-2`}>
              <X size={16} aria-hidden="true" /> Reject
            </button>
          </div>
        ) : (
          <div role="status" className="flex flex-wrap items-center gap-2 text-sm">
            <Tag tone={decision.status === "approved" ? "ok" : "neutral"}>{decision.status === "approved" ? (a.recommendation === "hold" ? "Acknowledged" : "Approved (simulated)") : "Rejected"}</Tag>
            <span className="text-text-dim">{decision.status === "approved" ? effectText(decision.effect, inr) : "Rejected: no change was made."}</span>
          </div>
        )}
      </div>
    </article>
  );
}

// ---------- scanned SKUs ----------

function skuColumns(): Column<PwSku>[] {
  return [
    { key: "sku", header: "SKU", render: (s) => <span className="inline-block min-w-40"><span className="font-medium">{s.name}</span> <span className="num block text-xs text-text-dim">{s.sku_code}</span></span> },
    { key: "vendor", header: "Vendor", render: (s) => s.brand },
    { key: "ours", header: "Our price", align: "right", render: (s) => inr(s.our_price) },
    { key: "low", header: "Lowest competitor", render: (s) => (s.lowest_competitor == null ? "—" : <span>{inr(s.lowest_competitor)} <span className="text-xs text-text-dim">{s.lowest_marketplace}</span></span>) },
    { key: "gap", header: "Gap", align: "right", render: (s) => pctSigned(s.gap_pct) },
    { key: "state", header: "State", render: (s) => <Tag tone={stateTone(s.state)}>{stateLabel(s.state)}</Tag> },
    { key: "breach", header: "Vendor breach", render: (s) => (s.vendor_breach ? <Tag tone="bad">Breach</Tag> : <span className="text-text-dim">No</span>) },
  ];
}

// ---------- page ----------

function Body({ data, reload }: { data: PriceWatch; reload: () => void }) {
  const c = data.counts;
  const th = data.thresholds;
  const drafts = data.drafts;
  return (
    <div className="flex flex-col gap-5">
      {data.verification.rejected > 0 ? <Banner tone="bad" title={`${data.verification.rejected} number${data.verification.rejected === 1 ? "" : "s"} failed verification`}>Messages that state a rejected number cannot be approved until it is fixed.</Banner> : null}

      <section aria-label="Summary" className="rounded-card border border-border bg-surface p-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="SKUs scanned" value={c.skus} hint={`${c.marketplaces} marketplaces`} />
          <Stat label="Sustained undercuts" value={c.sustained} />
          <Stat label="Blips ignored" value={c.blips} />
          <Stat label="Trends watched" value={c.trends} />
          <Stat label="Parity breaches" value={c.breaches} />
        </div>
        <p className="mt-3 text-xs text-text-dim">
          An undercut is sustained after {th.min_sustained_days} days; a shorter one is a blip. It counts once a competitor is {pctNumber(th.undercut_threshold_pct)} under us. A vendor breach is {pctNumber(th.parity_tolerance_pct)} under our price for {th.parity_min_days} days. We never cut more than {pctNumber(th.max_cut_pct)} in one move, and cost each move over {th.horizon_days} days.
        </p>
      </section>

      <section aria-label="Daily summary" className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{data.headline}</h2>
          <ModeTags mode={data.mode} degraded={data.degraded} />
        </div>
        <Paragraphs text={data.narrative} className="text-text-dim" />
        <StruckNote struck={data.struck} />
      </section>

      <section aria-label="Actions" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">What to do today</h2>
        {data.actions.map((a) => (
          <ActionCard key={a.id} a={a} th={th} onDone={(refresh) => (refresh ? reload() : undefined)} />
        ))}
        {data.actions.length === 0 ? <p className="text-sm text-text-dim">No competitor needs a response today.</p> : null}
      </section>

      <section aria-label="Vendor messages" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Vendor messages</h2>
          <span className="text-xs text-text-dim">
            {drafts.filter((d) => d.status === "pending").length} pending
            {unverified(drafts) ? ` · ${unverified(drafts)} unverified numbers` : ""}
          </span>
        </div>
        {drafts.map((d) => (
          <DraftCard key={`${d.id}-${d.status}`} draft={d} />
        ))}
      </section>

      <details className="rounded-card border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">All SKUs scanned ({data.skus.length})</summary>
        <div className="border-t border-border">
          <DataTable caption="All SKUs scanned" columns={skuColumns()} rows={data.skus} rowKey={(s) => s.sku_code} />
        </div>
      </details>

      <VerifierPanel verification={data.verification} claims={data.claims} trace={data.trace} />
      <p className="text-xs text-text-dim">
        These thresholds are tunable in the{" "}
        <Link href="/rules" className="text-accent hover:underline">Playbook</Link>
        {" "}under Price watch (Run).
      </p>
    </div>
  );
}

export function PriceWatchPage() {
  const { data, error, loading, reload } = useAsync((s) => fetchPriceWatch(s), "price-watch");
  return (
    <RunShell
      title="Competitor price monitor"
      subtitle={data ? `Daily sweep of ${data.counts.skus} SKUs on ${data.marketplaces.join(", ")} as of ${data.as_of}. Each move is costed; approving only writes to the simulator.` : "Daily sweep of competitor prices. Each move is costed; approving only writes to the simulator."}
    >
      {error ? <div className="mb-4"><BackendBanner error={error} cached={data != null} /></div> : null}
      {loading && !data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {data ? <Body data={data} reload={reload} /> : null}
    </RunShell>
  );
}
