"use client";

import { Check, Mail, Send, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { parseDeals } from "@/lib/deals";
import {
  approveRequest,
  DECISION_LABEL,
  DECISION_TONE,
  dateText,
  effectiveDecision,
  fetchInbox,
  fetchRequest,
  pctText,
  rejectRequest,
  RISK_TONE,
  rupees,
  signedInr,
  signedPct,
  type PrDetail,
  type PrDecision,
  type PrLine,
  type PrRow,
  type PrStatus,
} from "@/lib/priceRequests";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { CopyButton } from "../CopyButton";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { DealCard } from "../workspace/DealEvaluator";
import { RunShell } from "./RunShell";

export function DecisionTag({ decision, then }: { decision: PrDecision; then?: PrDecision | null }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-decision={decision}>
      <Tag tone={DECISION_TONE[decision]}>{DECISION_LABEL[decision]}</Tag>
      {decision === "delay" && then ? <span className="text-xs text-text-dim">then {DECISION_LABEL[then].toLowerCase()}</span> : null}
    </span>
  );
}

function Inbox({ rows, selected, onSelect }: { rows: PrRow[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <section aria-label="Request inbox" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Inbox" right={<span className="num">{rows.length}</span>} />
      <ul>
        {rows.map((r) => (
          <li key={r.id} className="border-b border-border last:border-b-0">
            <button
              type="button"
              onClick={() => onSelect(r.id)}
              aria-current={selected === r.id ? "true" : undefined}
              className={`flex min-h-11 w-full flex-col gap-0.5 px-4 py-3 text-left hover:bg-surface-2 ${selected === r.id ? "bg-surface-2" : ""}`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{r.brand}</span>
                <Tag tone={r.status === "approved" ? "ok" : r.status === "rejected" ? "bad" : "neutral"}>{r.status === "pending" ? "Waiting for approval" : r.status}</Tag>
              </span>
              <span className="truncate text-sm text-text-dim">{r.subject}</span>
              <span className="font-mono text-xs text-text-dim">
                {r.id} {"·"} {r.vendor_id} {"·"} received {dateText(r.received_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function marginCell(l: PrLine) {
  if (l.new_margin_pct == null) return "—";
  const under = l.floor_margin_pct != null && l.new_margin_pct < l.floor_margin_pct;
  const belowTarget = l.target_margin_pct != null && l.new_margin_pct < l.target_margin_pct;
  return (
    <span title={`Today ${pctText(l.current_margin_pct)}; target ${pctText(l.target_margin_pct, 0)}, floor ${pctText(l.floor_margin_pct, 0)}`}>
      <span className={under ? "font-medium text-bad" : belowTarget ? "text-warn" : ""}>{pctText(l.new_margin_pct)}</span>
      <span className="block text-[11px] text-text-dim">from {pctText(l.current_margin_pct)}</span>
    </span>
  );
}

export function LinesTable({ lines }: { lines: PrLine[] }) {
  const cols: Column<PrLine>[] = [
    { key: "sku", header: "SKU", render: (l) => (<span><span className="font-mono text-xs text-text-dim">{l.sku_code}</span><span className="block text-sm">{l.name}</span></span>) },
    { key: "old", header: "Old cost", align: "right", render: (l) => rupees(l.old_cost) },
    { key: "new", header: "New cost", align: "right", render: (l) => rupees(l.new_cost) },
    { key: "pct", header: "Change", align: "right", render: (l) => <span className="font-medium">{signedPct(l.pct_change)}</span> },
    { key: "margin", header: "New margin", align: "right", render: marginCell },
    {
      key: "need",
      header: "Retail needed",
      align: "right",
      render: (l) => (
        <span title="Retail price that defends the category target (or today's margin when already under target)">
          {rupees(l.needed_retail)}
          <span className="block text-[11px] text-text-dim">now {rupees(l.selling_price)}</span>
        </span>
      ),
    },
    {
      key: "gap",
      header: "vs competitors",
      align: "right",
      render: (l) => (
        <span className={l.gap_if_passed_pct != null && l.gap_if_passed_pct > 5 ? "font-medium text-bad" : ""} title="Our price if we pass the increase on, against the competitor median">
          {signedPct(l.gap_if_passed_pct)}
          {l.volume_change_pct != null && l.volume_change_pct !== 0 ? <span className="block text-[11px] text-text-dim">units {signedPct(l.volume_change_pct)}</span> : null}
        </span>
      ),
    },
    { key: "risk", header: "Elasticity risk", render: (l) => (l.elasticity_risk ? <Tag tone={RISK_TONE[l.elasticity_risk]}>{l.elasticity_risk}</Tag> : "—") },
    {
      key: "dec",
      header: "Decision",
      render: (l) => (
        <span className="flex flex-col gap-1">
          <DecisionTag decision={l.decision} then={l.then_decision} />
          {(l.decision === "accept_partial" || l.then_decision === "accept_partial") && l.counter_pct != null ? (
            <span className="num text-xs text-text-dim">counter {pctText(l.counter_pct)} = {rupees(l.counter_cost)}</span>
          ) : null}
          {l.decision === "delay" && l.ask_effective_date ? <span className="text-xs text-text-dim">ask for {dateText(l.ask_effective_date)}</span> : null}
        </span>
      ),
    },
  ];
  return (
    <DataTable
      caption="Extracted price lines with margin, retail price, competitor gap and decision"
      columns={cols}
      rows={lines}
      rowKey={(l) => l.sku_code}
      renderExpanded={(l) => (
        <details>
          <summary className="cursor-pointer text-xs text-text-dim">Why: {l.sku_code}</summary>
          <ul className="mt-1 list-disc pl-5 text-xs text-text-dim">
            {l.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
            {l.quote ? <li>Quoted from the vendor: &ldquo;{l.quote}&rdquo;</li> : null}
          </ul>
        </details>
      )}
    />
  );
}

function Impact({ d }: { d: PrDetail }) {
  const i = d.evaluation.impact;
  return (
    <section aria-label="Impact" className="rounded-card border border-border bg-surface">
      <PanelHeader title={`Next ${i.horizon_days} days`} right="GMV and margin versus today" />
      <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4">
        <Stat label="Margin if we absorb it" value={<span className="text-bad">{signedInr(i.absorb.margin_delta)}</span>} hint={`GMV ${signedInr(i.absorb.gmv_delta)}`} />
        <Stat label="Margin if we pass it on" value={signedInr(i.pass_through.margin_delta)} hint={`GMV ${signedInr(i.pass_through.gmv_delta)} (elasticity)`} />
        <Stat label="Margin with our decision" value={<span className="text-ok">{signedInr(i.recommended.margin_delta)}</span>} hint={`GMV ${signedInr(i.recommended.gmv_delta)}`} />
        <Stat label="Baseline margin" value={signedInr(i.baseline_margin_inr).replace("+", "")} hint={`on GMV ${signedInr(i.baseline_gmv).replace("+", "")}`} />
      </div>
    </section>
  );
}

function Sweeteners({ d }: { d: PrDetail }) {
  const deals = parseDeals(d.deals);
  const [open, setOpen] = useState<string | null>(deals?.assessments[0]?.termId ?? null);
  const acceptance = d.evaluation.sweeteners.filter((s) => s.engine === "acceptance");
  if (!deals && acceptance.length === 0) return null;
  return (
    <section aria-label="Sweetener" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">What the vendor offered in return</h2>
      {deals?.assessments.map((a) => (
        <DealCard key={a.termId} a={a} deals={deals} open={open === a.termId} onToggle={() => setOpen(open === a.termId ? null : a.termId)} />
      ))}
      {acceptance.map((s) => (
        <article key={s.id} aria-label={`Sweetener: ${s.label}`} className="rounded-card border border-border bg-surface p-4" data-testid="support-card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs text-text-dim">Acceptance-linked offer</div>
              <div className="text-sm font-semibold">{s.label}</div>
            </div>
            <Tag tone="ok">Certain once we accept in full</Tag>
          </div>
          <p className="mt-2 text-sm">{s.call}</p>
          <blockquote className="mt-2 border-l-2 border-border pl-3 text-sm text-text-dim">&ldquo;{s.quote}&rdquo;</blockquote>
        </article>
      ))}
    </section>
  );
}

function ApprovalBar({ d, onDone }: { d: PrDetail; onDone: (s: PrStatus) => void }) {
  const ev = d.evaluation;
  const [role, setRole] = useState(ev.approval.tier.role);
  const [body, setBody] = useState(d.reply.body);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  useEffect(() => setBody(d.reply.body), [d.reply.body]);
  const status = d.status;
  async function act(fn: () => Promise<PrStatus>) {
    setBusy(true);
    setErr(null);
    try {
      onDone(await fn());
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, { code: "error", problem: String(e) }));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Reply and approval" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Counter-offer and reply draft"
        right={
          <span className="flex items-center gap-2">
            <Mail size={16} aria-hidden="true" />
            {d.reply.source === "model" ? "written by the agent from engine figures" : "standard wording from engine figures"}
          </span>
        }
      />
      <div className="flex flex-col gap-3 p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Stat label="Approval needed" value={<span data-testid="tier">{ev.approval.tier.label}</span>} hint={`largest increase we would agree to: ${pctText(ev.approval.pct)} (asked ${pctText(ev.approval.asked_pct)})`} />
          <div className="md:col-span-2">
            <ul className="list-disc pl-5 text-xs text-text-dim">
              {ev.approval.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        </div>
        {ev.counter_offer.effective_date_ask ? (
          <p className="text-sm">
            Effective date we ask for: <span className="font-medium">{dateText(ev.counter_offer.effective_date_ask)}</span>
          </p>
        ) : null}
        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <label htmlFor="reply-body" className="text-xs font-medium uppercase tracking-wide text-text-dim">
              {d.reply.subject}
            </label>
            <CopyButton text={body} />
          </div>
          <textarea
            id="reply-body"
            value={body}
            disabled={status.status !== "pending"}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            className="w-full rounded-card border border-border bg-bg p-3 text-sm"
          />
          {d.reply.struck.length > 0 ? (
            <p className="mt-1 text-xs text-warn">
              {d.reply.struck.length} sentence(s) removed: they stated a number the engine did not produce.
            </p>
          ) : null}
          {d.reply.note ? <p className="mt-1 text-xs text-text-dim">{d.reply.note}</p> : null}
        </div>
        {err ? <BackendBanner error={err} cached={false} /> : null}
        {status.status === "pending" ? (
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-text-dim" htmlFor="approver">
              Approving as
            </label>
            <select id="approver" value={role} onChange={(e) => setRole(e.target.value)} className="h-11 rounded-card border border-border bg-bg px-2 text-sm">
              {ev.approval.matrix.map((t) => (
                <option key={t.role} value={t.role}>
                  {t.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => approveRequest(d.request.id, role, body !== d.reply.body ? body : undefined))}
              className="inline-flex h-11 items-center gap-1.5 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-50"
            >
              <Send size={16} aria-hidden="true" />
              Approve and send (simulated)
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => rejectRequest(d.request.id, role))}
              className="inline-flex h-11 items-center gap-1.5 rounded-card border border-border px-4 text-sm text-text-dim hover:bg-surface-2 disabled:opacity-50"
            >
              <X size={16} aria-hidden="true" />
              Reject
            </button>
            <span className="text-xs text-text-dim">Nothing is sent to the vendor: this is a simulator.</span>
          </div>
        ) : (
          <div role="status" className="flex items-center gap-1.5 text-sm text-text-dim">
            <Check size={16} aria-hidden="true" />
            {status.status === "approved" ? `Approved by ${status.by?.replace(/_/g, " ")}; marked sent in the simulator` : `Rejected by ${status.by?.replace(/_/g, " ")}`}. No message left this app.
          </div>
        )}
      </div>
    </section>
  );
}

export function RequestDetail({ d, onStatus }: { d: PrDetail; onStatus: (s: PrStatus) => void }) {
  const ev = d.evaluation;
  const v = d.verification;
  const j = ev.justification;
  return (
    <div className="flex flex-col gap-4" data-testid="request-detail" data-decision={ev.decision}>
      <section className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-mono text-xs text-text-dim">
              {d.request.id} {"·"} {d.request.vendor_id} {"·"} {d.request.sender}
            </div>
            <h2 className="text-lg font-semibold">{d.request.subject}</h2>
            <p className="mt-1 text-sm text-text-dim">{ev.headline}</p>
            {d.reason ? (
              <p className="mt-1 text-sm">
                Stated reason: <span className="text-text-dim">{d.reason}</span>
              </p>
            ) : null}
          </div>
          <div className="flex flex-col items-end gap-1">
            <DecisionTag decision={ev.decision} />
            <Tag tone="accent">Needs {ev.approval.tier.label}</Tag>
            <span className="num text-xs text-text-dim">
              {v.verified}/{v.total} figures verified{v.self_corrected ? ` · ${v.self_corrected} corrected by the agent` : ""}
            </span>
          </div>
        </div>
        {j.assessed ? (
          <p className="mt-3 text-sm" data-testid="justification">
            {j.index_name} {j.index_change_pct != null ? `${signedPct(j.index_change_pct)}` : ""} + {j.tolerance_pp} pt tolerance = {pctText(j.ceiling_pct)} justified. Asked up to{" "}
            <span className={j.unjustified_skus.length ? "font-medium text-bad" : "font-medium text-ok"}>{pctText(j.asked_max_pct)}</span>
            {j.unjustified_skus.length ? `: not justified for ${j.unjustified_skus.join(", ")}` : ": justified"}.
          </p>
        ) : null}
      </section>

      {d.rejected.length > 0 ? (
        <Banner tone="warn" title="Some lines could not be verified against the email, so they are not evaluated">
          <ul className="list-disc pl-5">
            {d.rejected.map((r) => (
              <li key={r.id}>
                {r.label}: {r.reasons.join("; ")}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {ev.notes.map((n) => (
        <Banner key={n} tone="info" title={n} />
      ))}

      <section aria-label="Extracted lines" className="rounded-card border border-border bg-surface">
        <PanelHeader title={`What the vendor asked, line by line (effective ${dateText(d.effective_date)})`} right={d.mode} />
        <LinesTable lines={ev.lines} />
        <details className="border-t border-border px-4 py-2">
          <summary className="cursor-pointer text-xs text-text-dim">The vendor&rsquo;s email and price list</summary>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-xs text-text-dim">{d.email}</pre>
          <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-text-dim">{d.price_list}</pre>
        </details>
      </section>

      <Sweeteners d={d} />
      <Impact d={d} />
      <ApprovalBar key={d.request.id + d.reply.body.length} d={d} onDone={onStatus} />
    </div>
  );
}

export function PriceRequestsPage() {
  const inbox = useAsync(fetchInbox, "pr-inbox", { retryMs: 3000 });
  const [selected, setSelected] = useState<string | null>(null);
  const rows = inbox.data?.requests ?? [];
  const current = selected ?? rows[0]?.id ?? null;
  const detail = useAsync((s) => fetchRequest(current ?? "", s), `pr-${current}`);
  const [statuses, setStatuses] = useState<Record<string, PrStatus>>({});
  const shown: PrRow[] = rows.map((r) => ({ ...r, status: statuses[r.id]?.status ?? r.status }));

  return (
    <RunShell title="Price requests" subtitle="Existing vendors asking to raise their prices. The agent reads the email and price list; Python decides each SKU; a person approves the reply.">
      {inbox.error ? (
        <div className="mb-4">
          <BackendBanner error={inbox.error} cached={inbox.data != null} retrying />
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        {inbox.data ? <Inbox rows={shown} selected={current} onSelect={setSelected} /> : <Skeleton className="h-48 w-full" />}
        <div aria-busy={detail.loading}>
          {detail.error && !detail.data ? <BackendBanner error={detail.error} cached={false} /> : null}
          {detail.data && detail.data.request.id === current ? (
            <RequestDetail d={{ ...detail.data, status: statuses[detail.data.request.id] ?? detail.data.status }} onStatus={(s) => setStatuses((m) => ({ ...m, [detail.data!.request.id]: s }))} />
          ) : detail.loading ? (
            <Skeleton className="h-96 w-full" />
          ) : null}
        </div>
      </div>
    </RunShell>
  );
}

/** The decision a line leads to, for callers that only need the headline. */
export { effectiveDecision };
