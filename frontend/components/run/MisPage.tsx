"use client";

import Link from "next/link";
import { useState } from "react";
import { useAsync } from "@/lib/useAsync";
import { ACTION_LABEL, fetchReview, inrCompact, pct, pctSigned, unverified, weekLabel, type Action, type Anomaly, type Scorecard } from "@/lib/ops";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { CopyButton } from "../CopyButton";
import { DataTable, type Column } from "../DataTable";
import { Markdown } from "../Markdown";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { DraftCard } from "./DraftCard";
import { RunShell } from "./RunShell";
import { Spark } from "./Spark";
import { VerifierPanel } from "./VerifierPanel";

const sevTone = (n: number) => (n >= 3 ? "bad" : n === 2 ? "warn" : "neutral") as "bad" | "warn" | "neutral";

function Tone({ bad, children }: { bad: boolean; children: React.ReactNode }) {
  return <span className={bad ? "font-medium text-bad" : undefined}>{children}</span>;
}

export function ActionList({ actions, brand }: { actions: Action[]; brand: (id: string) => string }) {
  return (
    <ol aria-label="What to do this week" className="divide-y divide-border">
      {actions.map((a) => (
        <li key={a.id} className="flex gap-3 px-4 py-3">
          <span className="num mt-0.5 w-6 shrink-0 text-right font-mono text-sm text-text-dim">{a.rank}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{a.title}</span>
              <Tag tone={sevTone(a.severity)}>{ACTION_LABEL[a.type] ?? a.type}</Tag>
              <Link href={`/run/vendors/${a.vendor_id}`} className="text-xs text-accent hover:underline">
                {brand(a.vendor_id)}
              </Link>
            </div>
            {a.rationale ? <p className="mt-0.5 text-sm text-text-dim">{a.rationale}</p> : null}
            <p className="num mt-0.5 text-xs text-text-dim">
              Score {a.score}
              {a.exposure_inr > 0 ? ` · exposure ${inrCompact(a.exposure_inr)}` : ""}
              {a.llm_rank !== null && a.llm_rank !== a.deterministic_rank ? ` · agent moved it from #${a.deterministic_rank}` : ""}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function MisPage() {
  const [inject, setInject] = useState(false);
  const { data, error, loading } = useAsync((s) => fetchReview(inject, s), `review-${inject}`);
  const brand = (id: string) => data?.vendors.find((v) => v.vendor_id === id)?.brand ?? id;

  const cols: Column<Scorecard>[] = [
    { key: "vendor", header: "Vendor", render: (v) => <Link href={`/run/vendors/${v.vendor_id}`} className="font-medium text-accent hover:underline">{v.brand}</Link> },
    { key: "gmv", header: "GMV", align: "right", render: (v) => inrCompact(v.gmv) },
    { key: "wow", header: "Week on week", align: "right", render: (v) => pctSigned(v.gmv_growth_wow) },
    { key: "trend", header: "13 weeks", render: (v) => <Spark values={v.series} label={`${v.brand} weekly GMV`} /> },
    { key: "fill", header: "Fill rate (recent)", align: "right", render: (v) => <Tone bad={(v.fill_rate_recent ?? 1) < 0.9}>{pct(v.fill_rate_recent, 0)}</Tone> },
    { key: "otif", header: "OTIF", align: "right", render: (v) => <Tone bad={(v.otif ?? 1) < 0.85}>{pct(v.otif, 0)}</Tone> },
    { key: "cover", header: "Lowest cover", align: "right", render: (v) => <Tone bad={(v.min_cover_days ?? 99) < 14}>{v.min_cover_days == null ? "—" : `${Math.round(v.min_cover_days)} d`}</Tone> },
    { key: "aged", header: "Aged stock", align: "right", render: (v) => <Tone bad={v.aged_pct > 0.2}>{pct(v.aged_pct, 0)}</Tone> },
    { key: "ret", header: "Returns", align: "right", render: (v) => <Tone bad={(v.return_rate ?? 0) > 0.04}>{pct(v.return_rate, 1)}</Tone> },
    { key: "rate", header: "Rating", align: "right", render: (v) => (v.rating == null ? "—" : v.rating.toFixed(2)) },
  ];
  const anomalyCols: Column<Anomaly>[] = [
    { key: "vendor", header: "Vendor", render: (a) => <Link href={`/run/vendors/${a.vendor_id}`} className="text-accent hover:underline">{brand(a.vendor_id)}</Link> },
    { key: "type", header: "Issue", render: (a) => <Tag tone={sevTone(a.severity)}>{ACTION_LABEL[a.type] ?? a.type}</Tag> },
    { key: "why", header: "Why", render: (a) => <span className="block max-w-xl whitespace-normal py-1.5">{a.explanation ?? a.reason}</span> },
  ];

  return (
    <RunShell
      title="Category MIS"
      subtitle={data ? `Week of ${weekLabel(data.week_start, data.week_end)}. Python computes every number; the agent explains and drafts; you approve.` : "Weekly review of existing vendors"}
      right={
        <label className="inline-flex min-h-11 items-center gap-2 text-xs text-text-dim">
          <input type="checkbox" checked={inject} onChange={(e) => setInject(e.target.checked)} />
          Inject one wrong number to see the verifier catch it
        </label>
      }
    >
      {error ? (
        <div className="mb-4">
          <BackendBanner error={error} cached={data != null} />
        </div>
      ) : null}
      {loading && !data ? (
        <div className="grid gap-4" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-5">
          {data.verification.rejected > 0 ? (
            <Banner tone="bad" title={`${data.verification.rejected} number${data.verification.rejected === 1 ? "" : "s"} failed verification`}>
              Do not rely on the rejected numbers below. Messages that state them cannot be approved until they are fixed.
            </Banner>
          ) : null}
          {data.unclaimed_numbers.length > 0 ? (
            <Banner tone="warn" title="The commentary states numbers without a claim">
              {data.unclaimed_numbers.join(", ")}
            </Banner>
          ) : null}
          {data.degraded ? <Banner tone="info" title="Serving the mock fixture">No recorded run was found for this step, so the mock fixture was used.</Banner> : null}

          <section aria-label="Headline" className="rounded-card border border-border bg-surface p-4">
            <p className="text-base font-medium">{data.headline}</p>
            <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-5">
              <Stat label="GMV, review week" value={inrCompact(data.category.gmv)} hint={`${pctSigned(data.category.gmv_growth_wow)} week on week`} />
              <Stat label="Units" value={data.category.units.toLocaleString("en-IN")} />
              <Stat label="Gross margin" value={pct(data.category.margin_pct, 1)} />
              <Stat label="Fill rate, recent" value={pct(data.category.fill_rate_recent, 0)} hint={`${pct(data.category.fill_rate, 0)} over 13 weeks`} />
              <Stat label="On-time-in-full" value={pct(data.category.otif, 0)} hint="target 85%" />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Tag tone="accent">{data.mode}</Tag>
              <Tag title="Manual minutes this module replaces, from the playbook's impact section">
                Replaces about {Math.round(data.impact_coverage.manual_minutes_replaced)} manual minutes
                {data.impact_coverage.baseline_status === "research_estimate" ? " (research estimate)" : ""}
              </Tag>
            </div>
          </section>

          <section aria-label="Actions" className="rounded-card border border-border bg-surface">
            <PanelHeader title="What to do this week" right={`${data.actions.length} actions, ranked`} />
            <ActionList actions={data.actions} brand={brand} />
          </section>

          <section aria-label="Vendor scorecard" className="rounded-card border border-border bg-surface">
            <PanelHeader title="Vendor scorecard" right="Red = outside the playbook limit" />
            <DataTable caption="Vendor scorecard" columns={cols} rows={data.vendors} rowKey={(v) => v.vendor_id} />
          </section>

          <section aria-label="Anomalies" className="rounded-card border border-border bg-surface">
            <PanelHeader title="Anomalies and reasons" right={`${data.anomalies.length} flagged`} />
            <DataTable caption="Anomalies" columns={anomalyCols} rows={data.anomalies} rowKey={(a) => a.id} />
          </section>

          <section aria-label="MIS pack" className="rounded-card border border-border bg-surface">
            <PanelHeader title="MIS pack (markdown)" right={<CopyButton text={data.mis_markdown} label="Copy markdown" />} />
            <div className="p-4">
              <Markdown source={data.mis_markdown} />
            </div>
          </section>

          <section aria-label="Vendor review emails" className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold">Vendor review emails</h2>
              <span className="text-xs text-text-dim">
                {data.drafts.filter((d) => d.status === "pending").length} waiting for approval
                {unverified(data.drafts) ? ` · ${unverified(data.drafts)} unverified numbers` : ""}
              </span>
            </div>
            {data.drafts.map((d) => (
              <DraftCard key={d.id} draft={d} />
            ))}
          </section>

          <VerifierPanel verification={data.verification} claims={data.claims} trace={data.trace} />
        </div>
      ) : null}
    </RunShell>
  );
}
