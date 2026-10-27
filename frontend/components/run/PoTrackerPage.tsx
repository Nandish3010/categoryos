"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useAsync } from "@/lib/useAsync";
import { fetchPoTracker, inrCompact, overdueText, RISK_TONE, statusLabel, unverified, type Commitment, type Po, type PoLine, type Reading } from "@/lib/ops";
import { pct } from "@/lib/format";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { DraftCard } from "./DraftCard";
import { RunShell } from "./RunShell";
import { VerifierPanel } from "./VerifierPanel";

const STATUS_TONE = { overdue: "bad", due_soon: "warn", on_track: "ok" } as const;
const BASIS = { vendor_reply: "vendor's verified date", promised_date: "promised date", assumed: "assumed (no dated commitment)" } as const;

export function CommitmentRow({ c }: { c: Commitment }) {
  const value = c.kind === "eta_date" ? (c.resolved_eta ?? c.eta_date ?? "no date") : `${c.qty ?? "?"} units`;
  const tone = c.status === "verified" ? (c.corrected ? "warn" : "ok") : "bad";
  const label = c.status === "verified" ? (c.corrected ? "Verified after correction" : "Verified") : c.status === "rejected" ? "Rejected" : c.status;
  return (
    <li className="flex flex-col gap-1 border-t border-border px-3 py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-text-dim">{c.kind === "eta_date" ? "Date" : "Quantity"}</span>
        <span className="num text-sm font-medium">{value}</span>
        {c.note ? <span className="text-xs text-text-dim">({c.note})</span> : null}
        <Tag tone={tone}>{label}</Tag>
      </div>
      <blockquote className="border-l-2 border-border pl-2 text-sm text-text-dim">&ldquo;{c.quote}&rdquo;</blockquote>
      {c.corrected && c.first_value !== null ? (
        <p className="text-xs text-text-dim">The agent first read this as {c.first_value} days after the reply; the verifier disagreed and the corrected reading passed.</p>
      ) : null}
      {c.status !== "verified" && c.reason ? <p className="text-xs text-bad">{c.reason}</p> : null}
    </li>
  );
}

export function ReadingCard({ r }: { r: Reading }) {
  const tone = r.stance === "committed" || r.stance === "shipped" ? "ok" : r.stance === "partial" ? "warn" : "bad";
  return (
    <article aria-label={`Reply ${r.reply_id}`} className="rounded-card border border-border bg-bg">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <span className="font-mono text-xs text-text-dim">{r.po_id}</span>
        <Tag tone={tone}>{r.stance.replace("_", " ")}</Tag>
        {r.root_cause !== "none" ? <Tag>{r.root_cause.replace("_", " ")}</Tag> : null}
        <span className="text-xs text-text-dim">{r.from.split("<")[0].trim()} {"·"} {r.received_at.slice(0, 16).replace("T", " ")}</span>
      </div>
      <p className="px-3 pb-2 text-sm">{r.summary}</p>
      {r.excuse ? <p className="px-3 pb-2 text-xs text-text-dim">Reason given: {r.excuse}</p> : null}
      {r.commitments.length > 0 ? (
        <ul aria-label="Extracted commitments" className="border-t border-border">
          {r.commitments.map((c, i) => (
            <CommitmentRow key={i} c={c} />
          ))}
        </ul>
      ) : (
        <p className="border-t border-border px-3 py-2 text-xs text-warn">No date or quantity promised: the tracker keeps the PO&rsquo;s own date and treats the reply as vague.</p>
      )}
      <details className="border-t border-border px-3 py-2">
        <summary className="cursor-pointer text-xs text-text-dim">Original email</summary>
        <pre className="mt-2 whitespace-pre-wrap font-sans text-xs text-text-dim">{r.body}</pre>
      </details>
    </article>
  );
}

function LineTable({ lines, lead }: { lines: PoLine[]; lead?: number }) {
  const cols: Column<PoLine>[] = [
    { key: "sku", header: "SKU", render: (l) => l.name },
    { key: "open", header: "Still to arrive", align: "right", render: (l) => `${l.open_qty.toLocaleString("en-IN")} of ${l.ordered.toLocaleString("en-IN")}` },
    { key: "cover", header: "Cover now", align: "right", render: (l) => (l.cover_days == null ? "—" : `${l.cover_days} d`) },
    { key: "arr", header: "Expected", render: (l) => <span>{l.arrival} <span className="text-xs text-text-dim">({BASIS[l.arrival_basis]})</span></span> },
    { key: "so", header: "Out of stock", align: "right", render: (l) => (l.stockout_days > 0 ? <span className="font-medium text-bad">{l.stockout_days} d · {inrCompact(l.lost_gmv)}</span> : "—") },
    { key: "risk", header: "Risk", render: (l) => <Tag tone={RISK_TONE[l.risk]}>{l.risk}</Tag> },
    { key: "re", header: "Suggested reorder", align: "right", render: (l) => (l.suggested_reorder ? `${l.suggested_reorder.toLocaleString("en-IN")} units` : "—") },
  ];
  return (
    <>
      <DataTable caption="PO lines" columns={cols} rows={lines} rowKey={(l) => l.sku_code} />
      {lead ? <p className="px-3 pb-2 text-xs text-text-dim">Reorder suggestion covers the vendor&rsquo;s {lead}-day lead time plus the stock-cover alert window.</p> : null}
    </>
  );
}

export function PoTrackerPage() {
  const [inject, setInject] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const { data, error, loading } = useAsync((s) => fetchPoTracker(inject, s), `pos-${inject}`);
  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const cols: Column<Po>[] = [
    {
      key: "po",
      header: "PO",
      render: (p) => (
        <button type="button" onClick={() => toggle(p.po_id)} aria-expanded={open.has(p.po_id)} className="inline-flex min-h-8 items-center gap-1 font-mono text-xs hover:text-accent">
          {open.has(p.po_id) ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
          {p.po_id}
        </button>
      ),
    },
    { key: "vendor", header: "Vendor", render: (p) => <Link href={`/run/vendors/${p.vendor_id}`} className="text-accent hover:underline">{p.brand}</Link> },
    { key: "promised", header: "Promised", render: (p) => <span>{p.promised_date} <span className="text-xs text-text-dim">({overdueText(p.days_overdue)})</span></span> },
    { key: "status", header: "Status", render: (p) => <span className="inline-flex gap-1"><Tag tone={STATUS_TONE[p.status]}>{statusLabel(p.status)}</Tag>{p.partial ? <Tag tone="warn">Partial</Tag> : null}</span> },
    { key: "fill", header: "Received", align: "right", render: (p) => pct(p.fill_so_far, 0) },
    { key: "says", header: "Vendor says", render: (p) => (p.eta ? <span className="num">{p.eta}</span> : p.vague_reply ? <Tag tone="bad">No date given</Tag> : <span className="text-text-dim">No reply read</span>) },
    { key: "risk", header: "Stock-out risk", render: (p) => <span className="inline-flex items-center gap-1"><Tag tone={RISK_TONE[p.risk]}>{p.risk}</Tag>{p.stockout_days > 0 ? <span className="num text-xs text-bad">{p.stockout_days} d</span> : null}</span> },
    { key: "rung", header: "Escalation", render: (p) => (p.rung ? <span>{p.rung.name}{p.rung.bumped_by_vague_reply ? <span className="text-xs text-warn"> (+1, vague reply)</span> : null}</span> : <span className="text-text-dim">None yet</span>) },
  ];

  return (
    <RunShell
      title="PO tracker"
      subtitle="Open purchase orders against promised dates. The agent reads vendor replies; only dates and quantities the verifier confirms move the risk."
      right={
        <label className="inline-flex min-h-11 items-center gap-2 text-xs text-text-dim">
          <input type="checkbox" checked={inject} onChange={(e) => setInject(e.target.checked)} />
          Inject one wrong number to see the verifier catch it
        </label>
      }
    >
      {error ? <div className="mb-4"><BackendBanner error={error} cached={data != null} /></div> : null}
      {loading && !data ? <div className="grid gap-4" aria-busy="true"><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div> : null}
      {data ? (
        <div className="flex flex-col gap-5">
          {data.verification.rejected > 0 ? (
            <Banner tone="bad" title={`${data.verification.rejected} number${data.verification.rejected === 1 ? "" : "s"} failed verification`}>
              {data.unresolved.length > 0 ? "A vendor-reply reading is still wrong after the last retry and was left out of the tracker." : "Messages that state a rejected number cannot be approved until it is fixed."}
            </Banner>
          ) : null}
          {data.corrected.length > 0 ? (
            <Banner tone="info" title={`The verifier rejected ${data.corrected.length} reading, and the agent corrected it`}>
              The agent&rsquo;s first answer is kept in the trace. Only the corrected, verified value is used.
            </Banner>
          ) : null}
          {data.unclaimed_numbers.length > 0 ? <Banner tone="warn" title="A draft states numbers without a claim">{data.unclaimed_numbers.join(", ")}</Banner> : null}

          <section aria-label="Summary" className="grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-4 md:grid-cols-5">
            <Stat label="Open POs" value={data.pos.length} />
            <Stat label="Overdue" value={data.pos.filter((p) => p.status === "overdue").length} />
            <Stat label="Need a chase" value={data.pos.filter((p) => p.needs_chase).length} />
            <Stat label="Stock-out risk" value={data.pos.filter((p) => p.risk === "critical" || p.risk === "high").length} hint="high or critical" />
            <Stat label="GMV at risk" value={inrCompact(data.pos.reduce((n, p) => n + p.lost_gmv, 0))} hint="while out of stock" />
          </section>

          <section aria-label="PO tracker" className="rounded-card border border-border bg-surface">
            <PanelHeader title="Open purchase orders" right={`as of ${data.as_of}`} />
            <DataTable
              caption="Open purchase orders"
              columns={cols}
              rows={data.pos}
              rowKey={(p) => p.po_id}
              renderExpanded={(p) => (open.has(p.po_id) ? <LineTable lines={p.lines} /> : null)}
            />
          </section>

          <section aria-label="Escalation ladder" className="rounded-card border border-border bg-surface">
            <PanelHeader title="Escalation ladder" right="Edit in the Playbook, Operations" />
            <ol className="grid gap-2 p-4 md:grid-cols-4">
              {data.ladder.map((r, i) => (
                <li key={r.name} className="rounded-card border border-border bg-bg p-3">
                  <div className="text-xs text-text-dim">Rung {i + 1} {"·"} from {r.days_overdue > 0 ? `${r.days_overdue} days overdue` : r.days_overdue === 0 ? "the due date" : `${-r.days_overdue} days before due`}</div>
                  <div className="text-sm font-medium">{r.name}</div>
                  <div className="text-xs text-text-dim">{r.channel} {"·"} {r.owner}</div>
                </li>
              ))}
            </ol>
          </section>

          <section aria-label="Vendor replies" className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold">Vendor replies, as the agent read them</h2>
            <div className="grid gap-3 lg:grid-cols-2">
              {data.readings.map((r) => (
                <ReadingCard key={r.reply_id} r={r} />
              ))}
            </div>
          </section>

          {data.ledger.length > 0 ? (
            <section aria-label="Fill-rate ledger" className="rounded-card border border-border bg-surface">
              <PanelHeader title="Fill-rate ledger" right="Shortfalls on late POs, tagged with the reason the vendor gave" />
              <DataTable
                caption="Fill-rate ledger"
                columns={[
                  { key: "po", header: "PO", render: (l) => <span className="font-mono text-xs">{l.po_id}</span> },
                  { key: "v", header: "Vendor", render: (l) => l.brand },
                  { key: "s", header: "SKU", render: (l) => l.name },
                  { key: "q", header: "Short by", align: "right", render: (l) => `${l.shortfall_units.toLocaleString("en-IN")} units` },
                  { key: "d", header: "Late by", align: "right", render: (l) => `${l.days_overdue} d` },
                  { key: "c", header: "Root cause", render: (l) => <Tag>{l.root_cause === "none" ? "not stated" : l.root_cause.replace("_", " ")}</Tag> },
                ]}
                rows={data.ledger}
                rowKey={(l) => `${l.po_id}-${l.sku_code}`}
              />
            </section>
          ) : null}

          <section aria-label="Follow-up drafts" className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold">Follow-ups waiting for approval</h2>
              <span className="text-xs text-text-dim">
                {data.drafts.filter((d) => d.status === "pending").length} pending
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
