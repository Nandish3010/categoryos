"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { inr, inrCompact, pct } from "@/lib/format";
import {
  approveAction,
  approveLabel,
  bandLabel,
  bandTone,
  coverPosition,
  effectText,
  fetchInventoryHealth,
  kindLabel,
  recommendationLabel,
  rejectAction,
  severityTone,
  type IhAction,
  type IhDecision,
  type IhSku,
  type IhThresholds,
  type IhVendor,
  type InventoryHealth,
} from "@/lib/inventoryHealth";
import { unverified } from "@/lib/ops";
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
const days = (n: number | null | undefined, digits = 1) => (n == null ? "—" : `${n.toFixed(digits)} days`);
const units = (n: number) => `${n.toLocaleString("en-IN")} units`;

// ---------- cover bar ----------

/** Days of cover against the target band: the marker is cover on hand, the hollow marker is cover once every open PO has landed. */
export function CoverBar({ a }: { a: IhAction }) {
  const s = a.stock;
  const max = s.band.max_days * 1.5;
  const at = (d: number | null) => `${(coverPosition(d, s.band) * 100).toFixed(1)}%`;
  const label = `Cover for ${a.name}: ${s.cover_days == null ? "not moving" : `${s.cover_days.toFixed(1)} days on hand`}, band ${s.band.min_days} to ${s.band.max_days} days`;
  return (
    <figure className="m-0">
      <div role="img" aria-label={label} className="relative h-3 rounded-full bg-surface-2">
        <div className="absolute inset-y-0 rounded-full bg-ok/25" style={{ left: `${(s.band.min_days / max) * 100}%`, width: `${((s.band.max_days - s.band.min_days) / max) * 100}%` }} />
        {s.cover_inbound_days != null && s.inbound_units > 0 ? <span className="absolute top-0 size-3 -translate-x-1/2 rounded-full border-2 border-accent bg-bg" style={{ left: at(s.cover_inbound_days) }} /> : null}
        {s.cover_days != null ? <span className="absolute top-0 size-3 -translate-x-1/2 rounded-full bg-accent" style={{ left: at(s.cover_days) }} /> : null}
      </div>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 text-xs text-text-dim">
        <span>Band {s.band.min_days}–{s.band.max_days} days (target {s.band.target_days})</span>
        <span className="num">On hand: {s.cover_days == null ? "not moving" : days(s.cover_days)}</span>
        {s.inbound_units > 0 ? <span className="num">With open POs: {days(s.cover_inbound_days)}</span> : null}
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

function KeyNumbers({ a }: { a: IhAction }) {
  const s = a.stock;
  const facts: { label: string; value: string; tone?: "bad" | "ok" }[] = [
    { label: "On hand", value: `${units(s.on_hand)}, ${inr(s.stock_value_inr)} at cost` },
    { label: "Daily demand", value: s.daily_demand > 0 ? `${s.daily_demand.toFixed(1)} units` : "Not moving" },
  ];
  if (a.kind === "stock_out") {
    facts.push({ label: "Runs out in", value: days(s.run_out_day), tone: "bad" });
    facts.push({ label: "Vendor lead time", value: `${s.lead_time_days} days` });
    if (s.inbound_units > 0) facts.push({ label: "Open PO units", value: units(s.inbound_units) });
    if (s.short_days > 0) facts.push({ label: "Out of stock for", value: days(s.short_days), tone: "bad" });
    if (a.reorder) {
      facts.push({ label: "Order now", value: `${units(a.reorder.qty)}, ${inr(a.reorder.cost_inr)}`, tone: "ok" });
      facts.push({ label: "Needed / MOQ", value: `${a.reorder.needed_units.toLocaleString("en-IN")} / ${a.reorder.moq_units.toLocaleString("en-IN")}` });
    }
  }
  if (a.pause) {
    facts.push({ label: `Pause ${a.pause.po_id}`, value: `${units(a.pause.pause_units)}, ${inr(a.pause.value_inr)}`, tone: "ok" });
    facts.push({ label: "Cover with / without it", value: `${days(a.pause.cover_with_po_days)} / ${days(a.pause.cover_without_po_days)}` });
    facts.push({ label: "Needed / MOQ", value: `${a.pause.needed_units.toLocaleString("en-IN")} / ${a.pause.moq_units.toLocaleString("en-IN")}` });
  }
  const c = a.clear;
  if (c) {
    facts.push({ label: "To clear", value: `${units(c.units)}, ${inr(c.value_inr)} at cost` });
    if (a.kind === "dead") facts.push({ label: "Days since last sale", value: s.days_since_sale == null ? "—" : `${s.days_since_sale}`, tone: "bad" });
    else facts.push({ label: "Oldest batch", value: `${s.oldest_age_days} days, ${units(s.aged_units)} aged` });
    if (c.rtv) {
      facts.push({ label: "Sell-or-return window", value: c.rtv.open ? `${c.rtv.days_left} days left (to ${c.rtv.window_ends})` : `Closed ${c.rtv.window_ends}`, tone: c.rtv.open ? (c.rtv.urgent ? "bad" : "ok") : "bad" });
      if (c.rtv.open) facts.push({ label: "Vendor credit", value: inr(c.rtv.credit_inr), tone: "ok" });
    }
    facts.push({ label: "Promo price", value: `${inr(c.liquidate.price_inr)} (${pct(c.liquidate.discount_pct)} off)` });
    facts.push({ label: "Promo recovers", value: `${inr(c.liquidate.recovery_inr)}${c.liquidate.clear_days != null ? ` in ${days(c.liquidate.clear_days)}` : ""}` });
  }
  return (
    <dl aria-label="Key numbers" className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-3">
      {facts.map((f) => (
        <Fact key={f.label} {...f} />
      ))}
    </dl>
  );
}

export function ActionCard({ a, onDone }: { a: IhAction; onDone: (needsRefresh: boolean) => void }) {
  const [decision, setDecision] = useState<IhDecision>(a.decision);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const verified = a.claims.filter((x) => x.status === "verified").length;
  const pending = decision.status === "pending";

  const act = async (fn: () => Promise<IhDecision>) => {
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
            {a.legacy ? " · discontinued, not in the live list" : ""}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Tag tone={severityTone(a.severity)}>{a.severity}</Tag>
          <Tag tone="neutral">{kindLabel(a.kind)}</Tag>
          <Tag tone="accent">{recommendationLabel(a.recommendation)}</Tag>
        </div>
      </div>

      <div className="flex flex-col gap-3 p-4">
        {a.clear?.rtv?.urgent && a.recommendation === "return_to_vendor" ? (
          <Banner tone="warn" title="The sell-or-return window closes soon">
            {a.clear.rtv.days_left} days left. After {a.clear.rtv.window_ends} this stock can only be cleared on a promo.
          </Banner>
        ) : null}
        {a.note ? <p className="text-sm">{a.note}</p> : null}
        <ul aria-label="Reasons" className="list-disc pl-5 text-sm text-text-dim">
          {a.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <KeyNumbers a={a} />
        {a.stock.daily_demand > 0 ? <CoverBar a={a} /> : null}
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
            <Tag tone={decision.status === "approved" ? "ok" : "neutral"}>{decision.status === "approved" ? "Approved (simulated)" : "Rejected"}</Tag>
            <span className="text-text-dim">{decision.status === "approved" ? effectText(decision.effect, inr) : "Rejected: no change was made."}</span>
          </div>
        )}
      </div>
    </article>
  );
}

// ---------- tables ----------

function vendorColumns(): Column<IhVendor>[] {
  return [
    { key: "vendor", header: "Vendor", render: (v) => <Link href={`/run/vendors/${v.vendor_id}`} className="text-accent hover:underline">{v.brand}</Link> },
    { key: "skus", header: "SKUs", align: "right", render: (v) => v.skus },
    { key: "value", header: "Stock at cost", align: "right", render: (v) => inrCompact(v.stock_value_inr) },
    { key: "stuck", header: "To return or clear", align: "right", render: (v) => inrCompact(v.stuck_value_inr) },
    { key: "out", header: "Stock-out risks", align: "right", render: (v) => v.stockout_skus },
    { key: "lead", header: "Lead time", align: "right", render: (v) => `${v.lead_time_days} days` },
  ];
}

function skuColumns(): Column<IhSku>[] {
  return [
    { key: "sku", header: "SKU", render: (s) => <span className="inline-block min-w-40"><span className="font-medium">{s.name}</span> <span className="num block text-xs text-text-dim">{s.sku_code}{s.legacy ? " · discontinued" : ""}</span></span> },
    { key: "vendor", header: "Vendor", render: (s) => s.brand },
    { key: "hand", header: "On hand", align: "right", render: (s) => s.on_hand.toLocaleString("en-IN") },
    { key: "demand", header: "Units a day", align: "right", render: (s) => s.daily_demand.toFixed(1) },
    { key: "cover", header: "Cover", align: "right", render: (s) => (s.cover_days == null ? "—" : days(s.cover_days)) },
    { key: "inbound", header: "Inbound", align: "right", render: (s) => s.inbound_units.toLocaleString("en-IN") },
    { key: "state", header: "Band", render: (s) => <Tag tone={bandTone(s.band_state)}>{bandLabel(s.band_state)}</Tag> },
    { key: "rec", header: "Action", render: (s) => (s.recommendation ? recommendationLabel(s.recommendation) : <span className="text-text-dim">None</span>) },
  ];
}

// ---------- page ----------

function Rules({ th }: { th: IhThresholds }) {
  return (
    <p className="mt-3 text-xs text-text-dim">
      Healthy cover is {th.cover_min_days}–{th.cover_max_days} days (reorders aim for {th.cover_target_days}), from the last {th.forecast_window_days} days of sales. A reorder is due when cover including inbound falls under lead time plus {th.review_days} review days plus {th.safety_days} safety days. Stock is aged after {th.aged_days} days and dead after {th.dead_no_sale_days} days without a sale. A PO that is {th.overbuy_ratio}x what is needed is an overbuy. A promo that would take longer than {th.max_clear_days} days to clear loses to a return.
    </p>
  );
}

function Body({ data, reload }: { data: InventoryHealth; reload: () => void }) {
  const c = data.counts;
  const drafts = data.drafts;
  return (
    <div className="flex flex-col gap-5">
      {data.verification.rejected > 0 ? <Banner tone="bad" title={`${data.verification.rejected} number${data.verification.rejected === 1 ? "" : "s"} failed verification`}>Messages that state a rejected number cannot be approved until it is fixed.</Banner> : null}

      <section aria-label="Summary" className="rounded-card border border-border bg-surface p-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="SKUs reviewed" value={c.skus} hint={`${c.legacy_lots} discontinued lots`} />
          <Stat label="Stock-out risks" value={c.stock_out} />
          <Stat label="Overbuys" value={c.overbuy} />
          <Stat label="Dead or aged" value={c.dead + c.aged} />
          <Stat label="Stuck stock" value={inrCompact(c.stuck_value_inr)} hint={`of ${inrCompact(c.stock_value_inr)} at cost`} />
        </div>
        <Rules th={data.thresholds} />
      </section>

      <section aria-label="Weekly summary" className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{data.headline}</h2>
          <ModeTags mode={data.mode} degraded={data.degraded} />
        </div>
        <Paragraphs text={data.narrative} className="text-text-dim" />
        <StruckNote struck={data.struck} />
      </section>

      <section aria-label="Actions" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">What to do this week</h2>
        {data.actions.map((a) => (
          <ActionCard key={a.id} a={a} onDone={(refresh) => (refresh ? reload() : undefined)} />
        ))}
        {data.actions.length === 0 ? <p className="text-sm text-text-dim">Every SKU is inside its cover band and nothing is ageing.</p> : null}
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

      <section aria-label="By vendor" className="rounded-card border border-border bg-surface">
        <DataTable caption="Inventory health by vendor" columns={vendorColumns()} rows={data.vendors} rowKey={(v) => v.vendor_id} />
      </section>

      <details className="rounded-card border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">All SKUs reviewed ({data.skus.length})</summary>
        <div className="border-t border-border">
          <DataTable caption="All SKUs reviewed" columns={skuColumns()} rows={data.skus} rowKey={(s) => s.sku_code} />
        </div>
      </details>

      <VerifierPanel verification={data.verification} claims={data.claims} trace={data.trace} />
      <p className="text-xs text-text-dim">
        These thresholds are tunable in the{" "}
        <Link href="/rules" className="text-accent hover:underline">Playbook</Link>
        {" "}under Inventory health (Run).
      </p>
    </div>
  );
}

export function InventoryHealthPage() {
  const { data, error, loading, reload } = useAsync((s) => fetchInventoryHealth(s), "inventory-health");
  return (
    <RunShell
      title="Inventory health"
      subtitle={data ? `Weekly review of ${data.counts.skus} SKUs as of ${data.as_of}: cover, stock-out risk, ageing and overbuy. Approving only writes to the simulator.` : "Weekly review of cover, stock-out risk, ageing and overbuy. Approving only writes to the simulator."}
    >
      {error ? <div className="mb-4"><BackendBanner error={error} cached={data != null} /></div> : null}
      {loading && !data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {data ? <Body data={data} reload={reload} /> : null}
    </RunShell>
  );
}
