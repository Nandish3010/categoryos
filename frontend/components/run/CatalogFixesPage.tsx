"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ApiError, type Claim } from "@/lib/api";
import {
  approveFix,
  bulkApprove,
  bulkReject,
  counterText,
  DECISION_LABEL,
  diffChanges,
  fetchCatalog,
  filterRows,
  ISSUE_LABEL,
  rejectFix,
  selectable,
  SEVERITY_TONE,
  type CatalogQueue,
  type Fix,
  type Listing,
  type QueueRow,
} from "@/lib/catalog";
import { inrCompact } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { RunShell } from "./RunShell";
import { VerifierPanel } from "./VerifierPanel";

const btn = "inline-flex h-11 items-center gap-1.5 rounded-card px-4 text-sm disabled:opacity-50";
const select = "min-h-11 rounded-card border border-border bg-surface px-2 text-sm";

function ClaimChip({ claim }: { claim: Claim }) {
  const corrected = claim.status === "verified" && (claim.attempts?.length ?? 0) > 1;
  const tone = claim.status === "verified" ? (corrected ? "warn" : "ok") : "bad";
  const label = claim.status === "verified" ? (corrected ? "verified after correction" : "verified") : claim.status;
  return (
    <Tag tone={tone} title={claim.reason ?? claim.text}>
      {claim.text.length > 52 ? `${claim.text.slice(0, 50)}…` : claim.text} · {label}
    </Tag>
  );
}

function Diff({ listing, fixes }: { listing: Listing; fixes: Fix[] }) {
  const changes = diffChanges(fixes);
  if (changes.length === 0) return <p className="px-4 py-3 text-sm text-text-dim">No change is proposed for this listing yet.</p>;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Before and after for {listing.title}</caption>
      <thead>
        <tr className="border-b border-border text-left text-xs text-text-dim">
          <th scope="col" className="h-8 w-32 px-4 font-medium">Field</th>
          <th scope="col" className="px-2 font-medium">Before</th>
          <th scope="col" className="px-2 font-medium">After</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c) => (
          <tr key={c.field} className="border-b border-border align-top last:border-b-0">
            <th scope="row" className="px-4 py-2 text-left font-medium">{c.label}</th>
            <td className="whitespace-pre-wrap px-2 py-2 text-bad/90 line-through decoration-bad/40">{c.before_text || "—"}</td>
            <td className="whitespace-pre-wrap px-2 py-2 text-ok">{c.after_text || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ListingCard({ listing, data, busy, onApprove, onReject }: { listing: Listing; data: CatalogQueue; busy: boolean; onApprove: (ids: string[]) => void; onReject: (id: string) => void }) {
  const fixes = listing.fixes.map((id) => data.fixes[id]);
  const claims = new Map(data.claims.map((c) => [c.id, c]));
  const ready = fixes.filter((f) => f.decision === "pending" && f.status === "ready");
  const issues = data.rows.filter((r) => r.listing_id === listing.listing_id);
  return (
    <article aria-label={`Listing ${listing.listing_id}`} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{listing.title}</div>
          <div className="num text-xs text-text-dim">
            {listing.listing_id} {"·"} {listing.brand} {"·"} {inrCompact(listing.gmv_at_risk_inr)} GMV at risk
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {issues.map((r) => (
            <Tag key={r.id} tone={SEVERITY_TONE[r.severity]}>{ISSUE_LABEL[r.type] ?? r.type}</Tag>
          ))}
        </div>
      </div>
      <Diff listing={listing} fixes={fixes} />
      {fixes.length > 0 ? (
        <ul aria-label="Fixes" className="border-t border-border">
          {fixes.map((f) => (
            <li key={f.id} className="flex flex-col gap-1.5 border-t border-border px-4 py-3 first:border-t-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{f.title}</span>
                <Tag tone={f.decision === "approved" ? "ok" : f.decision === "blocked" ? "bad" : f.decision === "rejected" ? "neutral" : "accent"}>{DECISION_LABEL[f.decision]}</Tag>
                <Tag>{f.source === "model" ? "Model-written" : f.source === "label" ? "From the pack label" : "From the data"}</Tag>
                {f.decision === "pending" || f.decision === "blocked" ? (
                  <span className="ml-auto flex gap-1.5">
                    {f.decision === "pending" ? (
                      <button type="button" disabled={busy} onClick={() => onApprove([f.id])} className={`${btn} min-h-9 h-9 bg-accent font-semibold text-bg`} aria-label={`Approve ${f.title}`}>
                        <Check size={16} aria-hidden="true" /> Approve
                      </button>
                    ) : null}
                    <button type="button" disabled={busy} onClick={() => onReject(f.id)} className={`${btn} h-9 border border-border text-text-dim hover:bg-surface-2`} aria-label={`Reject ${f.title}`}>
                      <X size={16} aria-hidden="true" /> Reject
                    </button>
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-1.5" aria-label="Claims checked by the verifier">
                {f.claim_ids.map((id) => {
                  const c = claims.get(id);
                  return c ? <ClaimChip key={id} claim={c} /> : null;
                })}
              </div>
              {f.status === "blocked" && f.reason ? <p className="text-xs text-bad">{f.reason}</p> : null}
              {f.notes.map((n) => (
                <p key={n} className="text-xs text-text-dim">{n}</p>
              ))}
            </li>
          ))}
        </ul>
      ) : null}
      {issues.filter((r) => !r.fix_id).map((r) => (
        <p key={r.id} className="border-t border-border px-4 py-2 text-xs text-warn">
          {ISSUE_LABEL[r.type] ?? r.type}: {r.no_fix_reason}
        </p>
      ))}
      {listing.label ? (
        <details className="border-t border-border px-4 py-2">
          <summary className="cursor-pointer text-xs text-text-dim">
            Pack label read by vision: {listing.label.mismatches === 0 ? "matches the listing" : `${listing.label.mismatches} difference(s)`}
          </summary>
          <ul className="mt-2 grid gap-1 text-xs">
            {listing.label.rows.map((r) => (
              <li key={r.field}>
                {r.field_label}: label {r.label_value}, listing {r.listing_value} <Tag tone={r.status === "match" ? "ok" : r.status === "mismatch" ? "bad" : "warn"}>{r.status}</Tag>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {ready.length > 1 ? (
        <div className="border-t border-border px-4 py-3">
          <button type="button" disabled={busy} onClick={() => onApprove(ready.map((f) => f.id))} className={`${btn} border border-accent text-accent`}>
            Approve all {ready.length} fixes for this listing
          </button>
        </div>
      ) : null}
    </article>
  );
}

export function CatalogFixesPage() {
  const [inject, setInject] = useState(false);
  const [type, setType] = useState("all");
  const [vendor, setVendor] = useState("all");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync((s) => fetchCatalog(inject, s), `catalog-${inject}`);

  const rows = useMemo(() => (data ? filterRows(data.rows, type, vendor) : []), [data, type, vendor]);
  const limit = data?.limits.bulk_approve ?? 25;
  const eligible = useMemo(() => (data ? selectable(rows, data.fixes, 10_000) : []), [data, rows]);
  const chosen = eligible.filter((id) => picked.has(id));
  const visibleListings = useMemo(() => {
    const ids = new Set(rows.map((r) => r.listing_id));
    return data ? data.listings.filter((l) => ids.has(l.listing_id)) : [];
  }, [data, rows]);

  const run = async (fn: () => Promise<unknown>, done: (r: unknown) => string | null) => {
    setBusy(true);
    setProblem(null);
    setNotice(null);
    try {
      const r = await fn();
      setNotice(done(r));
      setPicked(new Set());
      reload();
    } catch (e) {
      if (e instanceof ApiError) setProblem(e);
      else throw e;
    } finally {
      setBusy(false);
    }
  };
  const approve = (ids: string[]) =>
    run(
      () => (ids.length === 1 ? approveFix(ids[0]) : bulkApprove(ids)),
      (r) => {
        const b = r as { approved?: string[]; skipped?: { reason: string }[] };
        return b.approved ? `${b.approved.length} approved in the simulator${b.skipped?.length ? `, ${b.skipped.length} skipped` : ""}. Nothing was pushed to a marketplace.` : "Approved in the simulator. Nothing was pushed to a marketplace.";
      },
    );
  const reject = (id: string) => run(() => rejectFix(id), () => "Rejected.");
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const cols: Column<QueueRow>[] = [
    {
      key: "pick",
      header: "Select",
      render: (r) => {
        const ok = eligible.includes(r.fix_id ?? "");
        return <input type="checkbox" aria-label={`Select fix for ${r.listing_id} ${ISSUE_LABEL[r.type] ?? r.type}`} disabled={!ok} checked={ok && picked.has(r.fix_id ?? "")} onChange={() => r.fix_id && toggle(r.fix_id)} />;
      },
    },
    { key: "rank", header: "#", align: "right", render: (r) => r.rank },
    { key: "listing", header: "Listing", render: (r) => <span><span className="font-medium">{r.sku_code}</span> <span className="text-xs text-text-dim">{r.listing_id}</span></span> },
    { key: "vendor", header: "Vendor", render: (r) => <Link href={`/run/vendors/${r.vendor_id}`} className="text-accent hover:underline">{r.brand}</Link> },
    { key: "issue", header: "Issue", render: (r) => <span title={r.message}><Tag tone={SEVERITY_TONE[r.severity]}>{ISSUE_LABEL[r.type] ?? r.type}</Tag></span> },
    { key: "sev", header: "Severity", render: (r) => r.severity },
    { key: "score", header: "Priority", align: "right", render: (r) => r.score.toFixed(1) },
    { key: "gmv", header: "GMV at risk", align: "right", render: (r) => inrCompact(r.gmv_at_risk_inr) },
    { key: "fix", header: "Fix", render: (r) => <Tag tone={r.decision === "approved" ? "ok" : r.decision === "blocked" ? "bad" : r.decision === "pending" ? "accent" : "neutral"}>{DECISION_LABEL[r.decision]}</Tag> },
  ];

  return (
    <RunShell
      title="Catalog fixes"
      subtitle="Every live listing of your existing vendors, scanned against the playbook. Each proposed value is a claim the verifier checked; approving only writes to a simulated catalog update."
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
        <div className="grid gap-4">
          <section aria-label="Summary" className="grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-4 md:grid-cols-5">
            <div className="col-span-2 md:col-span-2">
              <div className="text-xs text-text-dim">Ready to approve</div>
              <div data-testid="counter" className="num text-xl font-semibold tracking-tight">{counterText(data.summary)}</div>
              <div className="text-xs text-text-dim">
                {data.summary.minutes_per_listing} min per listing by hand ({data.summary.baseline_status === "measured" ? "measured" : "research estimate"})
              </div>
            </div>
            <Stat label="Issues" value={data.summary.issues} hint={`${data.counts.listings_with_issues} of ${data.counts.listings} listings`} />
            <Stat label="Approved" value={data.summary.fixes_approved} hint={`${Math.round(data.summary.minutes_saved_approved)} min saved`} />
            <Stat label="Not verified" value={data.summary.fixes_blocked} hint="cannot be approved" />
          </section>
          {data.degraded ? <Banner tone="warn" title="Some model-written fixes are missing">{data.degraded_reason ?? "A fixture was served instead of a recorded run."} The deterministic fixes are unaffected.</Banner> : null}
          {data.summary.fixes_blocked > 0 ? <Banner tone="bad" title={`${data.summary.fixes_blocked} fix has a value the verifier rejected`}>It cannot be approved. Reject it, or fix the listing by hand.</Banner> : null}
          {data.corrected.length > 0 ? <Banner tone="info" title={`The verifier rejected ${data.corrected.length} number the model stated, and the model corrected it`}>Only the corrected, verified value is used; the first answer stays in the trace.</Banner> : null}
          {problem ? <Banner tone="bad" title={problem.body.problem}>{problem.body.cause} {problem.body.fix}</Banner> : null}
          {notice ? <Banner tone="info" title={notice} /> : null}

          <section aria-label="Fix queue" className="rounded-card border border-border bg-surface">
            <PanelHeader title="Fix queue" right={<span className="num">{rows.length} of {data.rows.length} issues</span>} />
            <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
              <label className="text-xs text-text-dim">
                Issue type{" "}
                <select aria-label="Issue type" value={type} onChange={(e) => { setType(e.target.value); setPicked(new Set()); }} className={select}>
                  <option value="all">All types</option>
                  {data.issue_types.filter((t) => data.counts.by_type[t]).map((t) => (
                    <option key={t} value={t}>{ISSUE_LABEL[t] ?? t} ({data.counts.by_type[t]})</option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-text-dim">
                Vendor{" "}
                <select aria-label="Vendor" value={vendor} onChange={(e) => { setVendor(e.target.value); setPicked(new Set()); }} className={select}>
                  <option value="all">All vendors</option>
                  {data.vendors.map((v) => <option key={v.id} value={v.id}>{v.brand}</option>)}
                </select>
              </label>
              <span className="ml-auto flex flex-wrap items-center gap-2">
                <button type="button" className={`${btn} border border-border text-text-dim hover:bg-surface-2`} onClick={() => setPicked(new Set(eligible.slice(0, limit)))} disabled={eligible.length === 0}>
                  Select ready (up to {limit})
                </button>
                <button type="button" disabled={busy || chosen.length === 0} onClick={() => approve(chosen)} className={`${btn} bg-accent font-semibold text-bg`}>
                  <Check size={16} aria-hidden="true" /> Approve {chosen.length} selected (simulated)
                </button>
                <button type="button" disabled={busy || chosen.length === 0} onClick={() => run(() => bulkReject(chosen), () => `${chosen.length} rejected.`)} className={`${btn} border border-border text-text-dim hover:bg-surface-2`}>
                  <X size={16} aria-hidden="true" /> Reject selected
                </button>
              </span>
              {chosen.length > limit ? <span className="w-full text-xs text-bad">The playbook allows {limit} fixes per bulk approve; select fewer.</span> : null}
            </div>
            <DataTable caption="Fix queue" columns={cols} rows={rows} rowKey={(r) => r.id} />
            {rows.length === 0 ? <p className="px-4 py-6 text-sm text-text-dim">No issue matches these filters.</p> : null}
          </section>

          <section aria-label="Listings" className="grid gap-3">
            <h2 className="text-sm font-semibold">Before and after, per listing</h2>
            {visibleListings.map((l) => (
              <ListingCard key={l.listing_id} listing={l} data={data} busy={busy} onApprove={approve} onReject={reject} />
            ))}
          </section>

          {data.updates.length > 0 ? (
            <section aria-label="Catalog update outbox" className="rounded-card border border-border bg-surface">
              <PanelHeader title="Catalog update outbox (simulated)" right={<span className="num">{data.updates.length} queued</span>} />
              <ul className="divide-y divide-border text-sm">
                {data.updates.map((u) => (
                  <li key={u.id} className="px-4 py-2">
                    <span className="num font-medium">{u.listing_id}</span> {"·"} {u.changes.map((c) => c.label).join(", ")} <Tag tone="ok">applied in the simulator</Tag>
                  </li>
                ))}
              </ul>
              <p className="border-t border-border px-4 py-2 text-xs text-text-dim">No update was sent to any marketplace or vendor.</p>
            </section>
          ) : null}

          <VerifierPanel verification={data.verification} claims={data.claims} trace={data.trace} />
          <p className="text-xs text-text-dim">
            Replaces about {Math.round(data.impact_coverage.manual_minutes_replaced)} manual minutes across {data.counts.listings_with_issues} listings (
            {data.impact_coverage.baseline_status === "measured" ? "measured" : "research estimate"}).
          </p>
        </div>
      ) : null}
    </RunShell>
  );
}
