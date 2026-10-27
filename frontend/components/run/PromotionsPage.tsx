"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { inr, inrCompact, pct } from "@/lib/format";
import { weekLabel, unverified } from "@/lib/ops";
import {
  approvePlan,
  assumptionItems,
  atRisk,
  cannibalText,
  excluded,
  exclusionLabel,
  fetchPromoPlan,
  fetchPromotions,
  offerLabel,
  offerTone,
  planned,
  pctNumber,
  rejectPlan,
  stanceLabel,
  startsText,
  stockRiskResolution,
  upliftText,
  type FundingTerm,
  type PlanDecisionResult,
  type PromoDecision,
  type PromoPlan,
  type PromoPo,
  type PromoReading,
  type PromoRow,
  type TermClaim,
  type VendorBlock,
} from "@/lib/promotions";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { DraftCard } from "./DraftCard";
import { ModeTags, Paragraphs, StruckNote } from "./RunBits";
import { RunShell } from "./RunShell";
import { VerifierPanel } from "./VerifierPanel";

const DECISION_TONE = { pending: "warn", approved: "ok", rejected: "neutral" } as const;
const DECISION_LABEL = { pending: "Waiting for a decision", approved: "Approved (simulated)", rejected: "Rejected" } as const;

const btn = "inline-flex h-11 items-center gap-1.5 rounded-card px-4 text-sm disabled:opacity-50";

// ---------- plan table ----------

function StatusCell({ r }: { r: PromoRow }) {
  const deep = r.deep_option;
  return (
    <div className="flex min-w-44 flex-col items-start gap-1 py-1">
      <div className="flex flex-wrap gap-1">
        {!r.capped_by_stock && !r.stock_up && r.stock_ok ? <Tag tone="ok">Stock ok</Tag> : null}
        {r.capped_by_stock ? <Tag tone="warn" title={deep ? `At ${pct(deep.depth)} off it runs out on day ${deep.stockout_day}` : undefined}>Capped by stock</Tag> : null}
        {r.stock_up ? <Tag tone="accent" title={`Order by ${r.stock_up.order_by}, arrives ${r.stock_up.arrives}`}>Stock-up PO {r.stock_up.qty}</Tag> : null}
        {r.stock_up_blocked ? <Tag tone="bad" title={r.stock_up_blocked.reason}>Stock-up blocked</Tag> : null}
        {r.cannibalisation ? <Tag tone="warn" title={cannibalText(r.cannibalisation)}>Cannibalises {r.cannibalisation.siblings[0]?.name}</Tag> : null}
        {r.banner_candidate ? <Tag tone="accent">Banner {r.banner_rank}</Tag> : null}
      </div>
      {r.capped_by_stock && deep ? <span className="text-xs text-text-dim">At {pct(deep.depth)} off it runs out on day {deep.stockout_day}.</span> : null}
      {r.cannibalisation ? <span className="text-xs text-text-dim">{r.cannibalisation.siblings.map((s) => `${s.name} is ${s.on_promo ? "also on promo" : "not on promo"}`).join("; ")}.</span> : null}
    </div>
  );
}

function planColumns(): Column<PromoRow>[] {
  return [
    { key: "sku", header: "SKU", render: (r) => <span className="inline-block min-w-40"><span className="font-medium">{r.name}</span> <span className="num block text-xs text-text-dim">{r.sku_code}</span></span> },
    { key: "vendor", header: "Vendor", render: (r) => <Link href={`/run/vendors/${r.vendor_id}`} className="text-accent hover:underline">{r.brand}</Link> },
    { key: "disc", header: "Discount", align: "right", render: (r) => pct(r.discount_pct) },
    { key: "price", header: "Promo price", align: "right", render: (r) => <span>{inr(r.promo_price)} <span className="text-xs text-text-dim">(was {inr(r.selling_price)})</span></span> },
    { key: "uplift", header: "Uplift", align: "right", render: (r) => upliftText(r.uplift) },
    { key: "units", header: "Promo units", align: "right", render: (r) => (r.promo_units == null ? "—" : Math.round(r.promo_units).toLocaleString("en-IN")) },
    { key: "margin", header: "Margin, unfunded to funded", align: "right", render: (r) => <span>{pct(r.margin_unfunded_pct)} to {pct(r.margin_at_ask_pct)}</span> },
    { key: "ask", header: "Funding ask", align: "right", render: (r) => inrCompact(r.funding_ask_inr) },
    { key: "net", header: "Net extra margin", align: "right", render: (r) => inrCompact(r.incremental_margin_inr) },
    { key: "status", header: "Status", render: (r) => <StatusCell r={r} /> },
    { key: "ver", header: "Checked", render: (r) => <span className="num text-xs text-text-dim">{r.verification.verified}/{r.verification.total} verified</span> },
  ];
}

// ---------- stock risk ----------

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <dt className="text-text-dim">{label}</dt>
      <dd className="num text-right">{value}</dd>
    </div>
  );
}

function StockRiskCard({ r }: { r: PromoRow }) {
  const d = r.deep_option!;
  return (
    <article aria-label={`Stock risk ${r.sku_code}`} className="rounded-card border border-border bg-bg">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <span className="text-sm font-semibold">{r.name}</span>
        <span className="num text-xs text-text-dim">{r.sku_code}</span>
        {d.why ? <span className="text-xs text-text-dim">{d.why}</span> : null}
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Deepest discount that pays</h3>
          <dl className="grid gap-1">
            <Fact label="Discount" value={pct(d.depth)} />
            <Fact label="Promo price" value={inr(d.promo_price)} />
            <Fact label="Units wanted" value={Math.round(d.units).toLocaleString("en-IN")} />
            <Fact label="Stock-out" value={d.stockout_day == null ? "none" : `day ${d.stockout_day}`} />
            <Fact label="Units short" value={Math.round(d.short_units).toLocaleString("en-IN")} />
            <Fact label="Lost GMV" value={inrCompact(d.lost_gmv_inr)} />
          </dl>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">What the plan does</h3>
          <dl className="grid gap-1">
            <Fact label="Discount" value={pct(r.discount_pct)} />
            <Fact label="Promo price" value={inr(r.promo_price)} />
            <Fact label="Units" value={r.promo_units == null ? "—" : Math.round(r.promo_units).toLocaleString("en-IN")} />
            <Fact label="Stock-out" value={r.stockout_day == null ? "none" : `day ${r.stockout_day}`} />
          </dl>
          <p className="mt-2 text-sm font-medium">{stockRiskResolution(r)}</p>
        </div>
      </div>
    </article>
  );
}

// ---------- stock-up POs ----------

function PoCard({ po, queued }: { po: PromoPo; queued: boolean }) {
  return (
    <article aria-label={`Stock-up PO ${po.brand}`} className="rounded-card border border-border bg-bg">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <div>
          <div className="text-sm font-semibold">{po.brand}</div>
          <div className="num text-xs text-text-dim">{po.po_ref}</div>
        </div>
        {queued ? <Tag tone="ok">queued (simulated)</Tag> : <Tag>Draft, not placed</Tag>}
      </div>
      <ul className="divide-y divide-border text-sm">
        {po.lines.map((l) => (
          <li key={l.sku_code} className="flex flex-wrap justify-between gap-2 px-4 py-2">
            <span>{l.name} <span className="num text-xs text-text-dim">{l.sku_code}</span></span>
            <span className="num">{l.qty} units {"·"} {inr(l.cost_inr)}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap justify-between gap-2 border-t border-border px-4 py-2 text-xs text-text-dim">
        <span>{po.qty} units {"·"} {inr(po.cost_inr)}</span>
        <span>Order by {po.order_by}, arrives {po.arrives}</span>
      </div>
    </article>
  );
}

// ---------- vendor funding ----------

const METRIC: Record<string, string> = {
  promo_ext_share_pct: "Share of the markdown",
  promo_ext_threshold_units: "Sales target",
  promo_ext_banner_top_n: "Banner placement",
  promo_ext_window_days: "Window",
};

function claimValue(metric: string, v: number | null): string {
  if (v == null) return "—";
  if (metric === "promo_ext_share_pct") return pct(v, 0);
  if (metric === "promo_ext_threshold_units") return `${Math.round(v).toLocaleString("en-IN")} units`;
  if (metric === "promo_ext_banner_top_n") return `top ${v}`;
  if (metric === "promo_ext_window_days") return `${v} days`;
  return String(v);
}

export function TermClaimRow({ c }: { c: TermClaim }) {
  const ok = c.status === "verified";
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-text-dim">{METRIC[c.metric] ?? c.metric}:</span>
      <span className="num font-medium">{claimValue(c.metric, c.value)}</span>
      <Tag tone={ok ? (c.corrected ? "warn" : "ok") : "bad"} title={c.reason ?? undefined}>
        {ok ? (c.corrected ? "Verified after correction" : "Verified") : c.status}
      </Tag>
      {c.corrected ? (
        <Tag tone="warn">
          Caught, then corrected: first read {claimValue(c.metric, c.first_value)}, verified {claimValue(c.metric, c.value)}
        </Tag>
      ) : null}
      {!ok && c.reason ? <span className="w-full text-xs text-bad">{c.reason}</span> : null}
    </li>
  );
}

function TermBlock({ t }: { t: FundingTerm }) {
  return (
    <div className="flex flex-col gap-1.5 border-t border-border px-4 py-3">
      <blockquote className="border-l-2 border-border pl-2 text-sm text-text-dim">&ldquo;{t.quote}&rdquo;</blockquote>
      <ul aria-label="Extracted terms" className="grid gap-1">
        {t.claims.map((c) => (
          <TermClaimRow key={c.id} c={c} />
        ))}
      </ul>
      {t.scope.length > 0 ? <p className="text-xs text-text-dim">Applies to {t.scope.join(", ")}.</p> : null}
    </div>
  );
}

function VendorCard({ v, readings }: { v: VendorBlock; readings: PromoReading[] }) {
  const o = v.offer;
  const a = v.assessment;
  return (
    <article aria-label={`Funding ${v.brand}`} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{v.brand}</div>
          <div className="num text-xs text-text-dim">
            We ask {inrCompact(v.ask_inr)} ({pct(v.ask_share, 0)} of the {inrCompact(v.markdown_inr)} markdown) {"·"} {v.n_skus} SKUs {"·"} {inrCompact(v.gmv)} GMV
          </div>
        </div>
        {o ? <Tag tone={offerTone(o.decision)}>{offerLabel(o.decision)}</Tag> : <Tag>No reply</Tag>}
      </div>

      {readings.map((rd) => (
        <div key={rd.reply_id} className="border-b border-border">
          <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
            <span className="text-xs uppercase tracking-wide text-text-dim">Vendor&rsquo;s reading</span>
            <Tag tone={rd.stance === "decline" ? "neutral" : "accent"}>{stanceLabel(rd.stance)}</Tag>
            <span className="text-xs text-text-dim">{rd.reply_id}</span>
          </div>
          <p className="px-4 pb-2 pt-1 text-sm">{rd.summary}</p>
          {rd.terms.map((t, i) => (
            <TermBlock key={i} t={t} />
          ))}
        </div>
      ))}

      {v.stated_lead_time_days != null ? <p className="border-b border-border px-4 py-2 text-sm">The vendor states a lead time of {v.stated_lead_time_days} days.</p> : null}

      {o ? (
        <div className="flex flex-col gap-2 px-4 py-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-text-dim">Offer valuation</h3>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Face value" value={inrCompact(o.face_inr)} />
            <Stat label="Counted" value={inrCompact(o.counted_inr)} hint={`${pct(o.covers_ask_pct, 0)} of our ask`} />
            <Stat label="Chance of target" value={o.probability == null ? "—" : pct(o.probability)} />
            <Stat label="Decision" value={<Tag tone={offerTone(o.decision)}>{offerLabel(o.decision)}</Tag>} />
          </div>
          <p className="text-sm">{o.call}</p>
          {o.counter?.text ? (
            <p className="text-sm text-text-dim">
              <span className="font-medium text-text">Our counter:</span> {o.counter.text}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="px-4 py-3 text-sm text-text-dim">No funding reply is on file for this vendor.</p>
      )}

      {a ? (
        <div className="border-t border-border px-4 py-2 text-xs text-text-dim">
          <p className="num">
            Deal evaluator: P(target) {a.probability == null ? "—" : pct(a.probability)} {"·"} counted {a.counted_pts.toFixed(1)} pts
            {a.required_pts != null ? ` against ${a.required_pts.toFixed(1)} required` : ""} {"·"} {a.counters.length} {a.counters.length === 1 ? "counter" : "counters"}
          </p>
          {a.counters.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {a.counters.map((c, i) => (
                <li key={i}>{c.text}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

// ---------- approve ----------

function DecisionResult({ d }: { d: PlanDecisionResult | PromoDecision }) {
  const n = d.n_skus ?? 0;
  const pos = d.pos ?? [];
  const stock = d.stock_up_inr ?? 0;
  if (d.status === "rejected") {
    return (
      <Banner tone="info" title="Plan rejected">
        Nothing was queued.{d.note ? ` Note: ${d.note}` : ""}
      </Banner>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <Banner tone="info" title={`Plan approved (simulated): ${n} ${n === 1 ? "price" : "prices"} queued, ${pos.length} stock-up ${pos.length === 1 ? "PO" : "POs"} queued, ${inr(stock)} total`}>
        {d.decided_at ? `Decided ${d.decided_at.slice(0, 16).replace("T", " ")} UTC. ` : ""}Nothing was sent to a marketplace or a vendor.
      </Banner>
      {pos.length > 0 ? (
        <ul aria-label="Queued stock-up POs" className="grid gap-1 text-sm">
          {pos.map((p) => (
            <li key={p.po_ref} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{p.brand}</span> <span className="num text-text-dim">{p.qty} units {"·"} {inr(p.cost_inr)}</span>
              <Tag tone="ok">queued (simulated)</Tag>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ---------- plan view ----------

function PlanView({ id, onDecided }: { id: string; onDecided: () => void }) {
  const { data, error, loading } = useAsync((s) => fetchPromoPlan(id, s), `promo-${id}`);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const [result, setResult] = useState<PlanDecisionResult | null>(null);

  const decide = async (fn: () => Promise<PlanDecisionResult>) => {
    setBusy(true);
    setProblem(null);
    try {
      setResult(await fn());
      onDecided();
    } catch (e) {
      if (e instanceof ApiError) setProblem(e);
      else throw e;
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {error ? <div className="mb-4"><BackendBanner error={error} cached={data != null} /></div> : null}
      {loading && !data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {data ? <PlanBody data={data} busy={busy} problem={problem} result={result} onApprove={() => decide(() => approvePlan(id))} onReject={() => decide(() => rejectPlan(id))} /> : null}
    </>
  );
}

function PlanBody({ data, busy, problem, result, onApprove, onReject }: { data: PromoPlan; busy: boolean; problem: ApiError | null; result: PlanDecisionResult | null; onApprove: () => void; onReject: () => void }) {
  const t = data.totals;
  const rows = planned(data.rows);
  const out = excluded(data.rows);
  const risky = atRisk(data.rows);
  const recorded = result ?? (data.decision.status !== "pending" ? data.decision : null);
  const drafts = data.drafts;

  return (
    <div className="flex flex-col gap-5">
      {data.verification.rejected > 0 ? <Banner tone="bad" title={`${data.verification.rejected} number${data.verification.rejected === 1 ? "" : "s"} failed verification`}>Messages that state a rejected number cannot be approved until it is fixed.</Banner> : null}
      {data.corrected.length > 0 ? (
        <Banner tone="info" title={`The verifier rejected ${data.corrected.length} reading, and the agent corrected it`}>
          The agent&rsquo;s first answer is kept in the trace. Only the corrected, verified value is used.
        </Banner>
      ) : null}

      <section aria-label="Plan totals" className="grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-4 md:grid-cols-5">
        <Stat label="SKUs on promo" value={t.planned_skus} hint={`${t.excluded_skus} left out`} />
        <Stat label="GMV" value={inrCompact(t.gmv_inr)} hint={`${Math.round(t.units).toLocaleString("en-IN")} units`} />
        <Stat label="Net extra margin" value={inrCompact(t.incremental_margin_inr)} hint="after pull-forward and cannibalisation" />
        <Stat label="Funding asked" value={inrCompact(t.funding_ask_inr)} hint={`margin ${pct(t.margin_unfunded_pct)} to ${pct(t.margin_at_ask_pct)}`} />
        <Stat label="Stock-up cost" value={inrCompact(t.stock_up_inr)} hint={`${t.stock_up_units} units in ${t.stock_up_pos} POs`} />
      </section>

      <section aria-label="Event brief" className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{data.headline}</h2>
          <ModeTags mode={data.mode} degraded={data.degraded} />
        </div>
        <Paragraphs text={data.brief} className="text-text-dim" />
        <StruckNote struck={data.struck} />
      </section>

      <section aria-label="Promotion plan" className="rounded-card border border-border bg-surface">
        <PanelHeader title="Plan" right={`${rows.length} SKUs on promo`} />
        <DataTable caption="Promotion plan" columns={planColumns()} rows={rows} rowKey={(r) => r.sku_code} />
      </section>

      {out.length > 0 ? (
        <details className="rounded-card border border-border bg-surface">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Why not: {out.length} SKUs left out</summary>
          <ul className="divide-y divide-border border-t border-border text-sm">
            {out.map((r) => (
              <li key={r.sku_code} className="flex flex-col gap-1 px-4 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{r.name}</span>
                  <span className="num text-xs text-text-dim">{r.sku_code}</span>
                  {r.exclusion ? <Tag>{exclusionLabel(r.exclusion.code)}</Tag> : null}
                </div>
                {r.exclusion ? <p className="text-text-dim">{r.exclusion.text}</p> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {risky.length > 0 ? (
        <section aria-label="Stock risk" className="rounded-card border border-border bg-surface">
          <PanelHeader title="Stock risk" right={`${risky.length} SKUs would sell out at the deepest discount that pays`} />
          <div className="grid gap-3 p-4 lg:grid-cols-2">
            {risky.map((r) => (
              <StockRiskCard key={r.sku_code} r={r} />
            ))}
          </div>
        </section>
      ) : null}

      {data.pos.length > 0 ? (
        <section aria-label="Stock-up POs" className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Stock-up POs for the event</h2>
          <div className="grid gap-3 lg:grid-cols-3">
            {data.pos.map((po) => (
              <PoCard key={po.po_ref} po={po} queued={!!recorded && recorded.status === "approved"} />
            ))}
          </div>
        </section>
      ) : null}

      <section aria-label="Vendor funding" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Vendor funding</h2>
        <div className="grid gap-3 lg:grid-cols-2">
          {data.vendors.map((v) => (
            <VendorCard key={v.vendor_id} v={v} readings={data.readings.filter((r) => r.vendor_id === v.vendor_id)} />
          ))}
        </div>
      </section>

      <section aria-label="Vendor emails" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Vendor emails waiting for approval</h2>
          <span className="text-xs text-text-dim">
            {drafts.filter((d) => d.status === "pending").length} pending
            {unverified(drafts) ? ` · ${unverified(drafts)} unverified numbers` : ""}
          </span>
        </div>
        {drafts.map((d) => (
          <DraftCard key={d.id} draft={d} />
        ))}
      </section>

      <section aria-label="Approve plan" className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">Decision</h2>
        {problem ? <Banner tone="bad" title={problem.body.problem}>{problem.body.cause} {problem.body.fix}</Banner> : null}
        {recorded ? <DecisionResult d={recorded} /> : null}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={busy || !!recorded} onClick={onApprove} className={`${btn} bg-accent font-semibold text-bg`}>
            <Check size={16} aria-hidden="true" /> Approve plan (simulated)
          </button>
          <button type="button" disabled={busy || !!recorded} onClick={onReject} className={`${btn} border border-border text-text-dim hover:bg-surface-2`}>
            <X size={16} aria-hidden="true" /> Reject plan
          </button>
          <span className="text-xs text-text-dim">Approving queues the promo prices and stock-up POs in the simulator. No price changes on a marketplace and no PO reaches a vendor.</span>
        </div>
      </section>

      <VerifierPanel verification={data.verification} claims={data.claims} trace={data.trace} />

      <details className="rounded-card border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Assumptions</summary>
        <div className="border-t border-border px-4 py-3">
          <ul className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
            {assumptionItems(data.assumptions).map((a) => (
              <li key={a.key} className="flex justify-between gap-3">
                <span className="text-text-dim">{a.label}</span>
                <span className="num text-right">{a.value}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-text-dim">
            These are tunable in the{" "}
            <Link href="/rules" className="text-accent hover:underline">Playbook</Link>
            {" "}under Promotions (Run).
          </p>
        </div>
      </details>
    </div>
  );
}

// ---------- page ----------

export function PromotionsPage() {
  const list = useAsync((s) => fetchPromotions(s), "promotions");
  const [picked, setPicked] = useState<string | null>(null);
  const events = list.data?.events ?? [];
  const selected = picked ?? events[0]?.id ?? null;

  return (
    <RunShell
      title="Promotions and event planner"
      subtitle="Pick an event: the planner chooses SKUs and depths, protects stock, asks vendors to fund the markdown and values their offers. Numbers are checked by the verifier; approving only writes to the simulator."
    >
      {list.error ? <div className="mb-4"><BackendBanner error={list.error} cached={list.data != null} /></div> : null}
      {list.loading && !list.data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-20 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {list.data ? (
        <div className="flex flex-col gap-5">
          <section aria-label="Events" className="grid gap-3 md:grid-cols-2">
            {events.map((e) => {
              const on = e.id === selected;
              return (
                <button
                  key={e.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setPicked(e.id)}
                  className={`flex min-h-11 flex-col items-start gap-1 rounded-card border p-3 text-left ${on ? "border-accent bg-surface-2" : "border-border bg-surface hover:bg-surface-2"}`}
                >
                  <span className="flex w-full flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{e.name}</span>
                    <Tag tone={DECISION_TONE[e.decision.status]}>{DECISION_LABEL[e.decision.status]}</Tag>
                  </span>
                  <span className="text-xs text-text-dim">
                    {weekLabel(e.start, e.end)} {"·"} {e.days} days {"·"} {startsText(e.days_away)}
                  </span>
                  <span className="text-xs text-text-dim">
                    {e.planned_skus} SKUs planned {"·"} traffic {pctNumber(e.traffic_lift_pct)} higher {"·"} {e.banner_slots} banner slots
                  </span>
                </button>
              );
            })}
          </section>
          {selected ? <PlanView key={selected} id={selected} onDecided={list.reload} /> : null}
        </div>
      ) : null}
    </RunShell>
  );
}
