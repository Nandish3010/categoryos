"use client";

import Link from "next/link";
import { useAsync } from "@/lib/useAsync";
import { ACTION_LABEL, fetchVendorReview, inrCompact, overdueText, pct, pctSigned, RISK_TONE, statusLabel, weekLabel, type SkuRow } from "@/lib/ops";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { ActionList } from "./MisPage";
import { DraftCard } from "./DraftCard";
import { ReadingCard } from "./PoTrackerPage";
import { RunShell } from "./RunShell";
import { Spark } from "./Spark";

export function VendorReviewPage({ vendorId }: { vendorId: string }) {
  const { data, error, loading } = useAsync((s) => fetchVendorReview(vendorId, s), `ops-vendor-${vendorId}`);
  const sc = data?.scorecard;

  const cols: Column<SkuRow>[] = [
    { key: "sku", header: "SKU", render: (s) => <span>{s.name} <span className="font-mono text-xs text-text-dim">{s.sku_code}</span></span> },
    { key: "gmv", header: "GMV", align: "right", render: (s) => inrCompact(s.gmv) },
    { key: "u", header: "Units", align: "right", render: (s) => `${s.units} (was ${s.units_prev})` },
    { key: "t", header: "13 weeks", render: (s) => <Spark values={s.series} label={`${s.name} weekly units`} /> },
    { key: "z", header: "z-score", align: "right", render: (s) => (s.units_z == null ? "—" : s.units_z.toFixed(1)) },
    { key: "cover", header: "Cover", align: "right", render: (s) => <span className={s.cover_days != null && (s.cover_days < 14 || s.cover_days > 90) ? "font-medium text-bad" : undefined}>{s.cover_days == null ? "—" : `${Math.round(s.cover_days)} d`}</span> },
    { key: "ret", header: "Returns", align: "right", render: (s) => pct(s.return_rate, 1) },
    { key: "rate", header: "Rating", align: "right", render: (s) => (s.rating == null ? "—" : `${s.rating.toFixed(2)}${s.rating_change ? ` (${s.rating_change > 0 ? "+" : "−"}${Math.abs(s.rating_change).toFixed(2)})` : ""}`) },
  ];

  return (
    <RunShell
      title={data ? `${data.vendor.brand}: weekly review` : `Vendor ${vendorId}`}
      subtitle={data ? `${data.vendor.company_name} · ${data.vendor.category} · lead time ${data.vendor.lead_time_days} days · week of ${weekLabel(data.week_start, data.week_end)}` : undefined}
      right={<Link href="/run" className="inline-flex min-h-11 items-center rounded-card border border-border px-3 text-sm text-text-dim hover:bg-surface-2 hover:text-text">All vendors</Link>}
    >
      {error ? <div className="mb-4"><BackendBanner error={error} cached={data != null} /></div> : null}
      {loading && !data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {data && sc ? (
        <div className="flex flex-col gap-5">
          <section aria-label="Scorecard" className="rounded-card border border-border bg-surface p-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
              <Stat label="GMV" value={inrCompact(sc.gmv)} hint={`${pctSigned(sc.gmv_growth_wow)} week on week`} />
              <Stat label="Units" value={sc.units} />
              <Stat label="Margin" value={pct(sc.margin_pct, 1)} />
              <Stat label="Fill rate" value={pct(sc.fill_rate_recent, 0)} hint={`recent; ${pct(sc.fill_rate_prior, 0)} earlier`} />
              <Stat label="OTIF" value={pct(sc.otif, 0)} />
              <Stat label="Lowest cover" value={sc.min_cover_days == null ? "—" : `${Math.round(sc.min_cover_days)} d`} />
              <Stat label="Aged stock" value={pct(sc.aged_pct, 0)} hint={`of ${inrCompact(sc.stock_value_inr)} stock`} />
              <Stat label="Returns" value={pct(sc.return_rate, 1)} hint="4 weeks" />
              <Stat label="Rating" value={sc.rating == null ? "—" : sc.rating.toFixed(2)} hint={sc.rating_change ? `${sc.rating_change > 0 ? "+" : "−"}${Math.abs(sc.rating_change).toFixed(2)} in 4 weeks` : undefined} />
              <div className="col-span-2 md:col-span-2"><div className="text-xs text-text-dim">GMV, 13 weeks</div><Spark values={sc.series} width={220} height={40} label="Weekly GMV, 13 weeks" /></div>
            </div>
            <div className="mt-4">
              <div className="mb-1 text-xs text-text-dim">Stock age (by cost value)</div>
              <div className="flex flex-wrap gap-2">
                {sc.ageing.map((b) => (
                  <Tag key={b.label} tone={b.label.startsWith("over") && sc.aged_pct > 0.2 ? "bad" : "neutral"}>
                    {b.label}: {inrCompact(b.value_inr)}
                  </Tag>
                ))}
              </div>
            </div>
          </section>

          {data.anomalies.length === 0 ? <Banner tone="info" title="Nothing flagged this week">This vendor is inside every limit in the playbook.</Banner> : null}
          {data.actions.length > 0 ? (
            <section aria-label="Actions" className="rounded-card border border-border bg-surface">
              <PanelHeader title="Actions for this vendor" />
              <ActionList actions={data.actions} brand={() => data.vendor.brand} />
            </section>
          ) : null}
          {data.anomalies.length > 0 ? (
            <section aria-label="Anomalies" className="rounded-card border border-border bg-surface">
              <PanelHeader title="What the data shows" />
              <ul className="divide-y divide-border">
                {data.anomalies.map((a) => (
                  <li key={a.id} className="px-4 py-3 text-sm">
                    <div className="mb-0.5 flex items-center gap-2"><Tag tone={a.severity >= 3 ? "bad" : a.severity === 2 ? "warn" : "neutral"}>{ACTION_LABEL[a.type] ?? a.type}</Tag></div>
                    <p>{a.reason}</p>
                    {a.explanation ? <p className="mt-1 text-text-dim">{a.explanation}</p> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-label="SKUs" className="rounded-card border border-border bg-surface">
            <PanelHeader title="SKUs" />
            <DataTable caption="SKU performance" columns={cols} rows={sc.skus ?? []} rowKey={(s) => s.sku_code} />
          </section>

          {data.email ? (
            <section aria-label="Review email" className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">Review email</h2>
              <DraftCard draft={data.email} />
            </section>
          ) : null}

          {data.pos.length > 0 ? (
            <section aria-label="Open purchase orders" className="rounded-card border border-border bg-surface">
              <PanelHeader title="Open purchase orders" right={<Link href="/run/pos" className="text-accent hover:underline">PO tracker</Link>} />
              <ul className="divide-y divide-border">
                {data.pos.map((p) => (
                  <li key={p.po_id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
                    <span className="font-mono text-xs">{p.po_id}</span>
                    <Tag tone={p.status === "overdue" ? "bad" : p.status === "due_soon" ? "warn" : "ok"}>{statusLabel(p.status)}</Tag>
                    <span className="text-text-dim">{overdueText(p.days_overdue)}</span>
                    <Tag tone={RISK_TONE[p.risk]}>{p.risk} stock-out risk</Tag>
                    {p.rung ? <span className="text-xs text-text-dim">Rung: {p.rung.name}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {data.readings.length > 0 ? (
            <section aria-label="Vendor replies" className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">Replies from this vendor</h2>
              {data.readings.map((r) => <ReadingCard key={r.reply_id} r={r} />)}
            </section>
          ) : null}
          {data.drafts.length > 0 ? (
            <section aria-label="PO follow-ups" className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">PO follow-ups</h2>
              {data.drafts.map((d) => <DraftCard key={d.id} draft={d} />)}
            </section>
          ) : null}
        </div>
      ) : null}
    </RunShell>
  );
}
