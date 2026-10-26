"use client";

import { AlertTriangle, Check, CheckCircle2, Circle, Lock, Truck } from "lucide-react";
import { inrExact } from "@/lib/format";
import type { RunSnapshot, StageResult } from "@/lib/runs";
import { poClaimVerified, readJbp, readMarketing, readPo, type PoData, type TimelineStep } from "@/lib/stages";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { Markdown } from "../Markdown";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";

function Pending({ stage, what, running }: { stage: StageResult | undefined | null; what: string; running: string }) {
  const status = stage?.status ?? "pending";
  return (
    <div className="p-4 text-sm text-text-dim" role="status">
      {status === "running" ? running : status === "failed" ? (stage?.error ?? `${what} failed.`) : `${what} is drafted after you approve the catalog.`}
      {status === "running" ? <Skeleton className="mt-2 h-16 w-full" /> : null}
    </div>
  );
}

export function MarketingCard({ stage }: { stage: StageResult | undefined | null }) {
  const m = readMarketing(stage);
  return (
    <section aria-label="Marketing" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Marketing" right={m?.imageSource === "placeholder" ? <span>placeholder · live image pending</span> : null} />
      {m ? (
        <div className="grid gap-4 p-4 md:grid-cols-[200px_minmax(0,1fr)]">
          {m.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={m.image} alt={`${m.campaign} campaign image`} loading="lazy" className="w-full rounded-card border border-border bg-surface-2 object-cover" />
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
          <div className="flex flex-col gap-3">
            <h3 className="text-base font-semibold">{m.campaign}</h3>
            <p className="text-sm">{m.copy}</p>
            <div className="rounded-card border border-border bg-surface-2 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-text-dim">Discount ask</span>
                {m.brandFundedPct != null ? <Tag tone="ok">{m.brandFundedPct}% brand-funded</Tag> : null}
                {m.ourPct != null ? <Tag>{m.ourPct}% platform-funded</Tag> : null}
                {m.brandFundedMarketingInr != null ? (
                  <span className="num text-xs text-text-dim">+ {inrExact(m.brandFundedMarketingInr)} launch marketing</span>
                ) : null}
              </div>
              {m.rationale ? <p className="mt-1 text-text-dim">{m.rationale}</p> : null}
            </div>
          </div>
        </div>
      ) : (
        <Pending stage={stage} what="Marketing" running="Drafting the campaign…" />
      )}
    </section>
  );
}

export function JbpCard({ stage }: { stage: StageResult | undefined | null }) {
  const j = readJbp(stage);
  return (
    <section aria-label="Joint business plan" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Joint business plan" />
      {j ? (
        <div className="p-4">
          <Markdown source={j.markdown} />
        </div>
      ) : (
        <Pending stage={stage} what="The joint business plan" running="Drafting the joint business plan…" />
      )}
    </section>
  );
}

const STEP_LABEL: Record<string, string> = { raised: "Raised", confirmed: "Confirmed", shipped: "Shipped", received: "Received" };

export function PoTimeline({ steps }: { steps: TimelineStep[] }) {
  return (
    <ol aria-label="PO status timeline" className="grid gap-3 md:grid-cols-4">
      {steps.map((t) => {
        const delayed = t.delayDays > 0 || t.status === "delayed";
        const done = t.status === "done";
        return (
          <li
            key={t.step}
            data-step={t.step}
            data-status={t.status}
            className={`rounded-card border p-3 text-sm ${delayed ? "border-warn/40 bg-warn/10" : "border-border bg-surface-2"}`}
          >
            <div className="flex items-center gap-2 font-medium">
              {done ? (
                <CheckCircle2 size={16} className="text-ok" aria-hidden="true" />
              ) : delayed ? (
                <AlertTriangle size={16} className="text-warn" aria-hidden="true" />
              ) : t.step === "shipped" ? (
                <Truck size={16} className="text-text-dim" aria-hidden="true" />
              ) : (
                <Circle size={16} className="text-text-dim" aria-hidden="true" />
              )}
              {STEP_LABEL[t.step] ?? t.step}
              {delayed ? <Tag tone="warn">+{t.delayDays} d</Tag> : null}
            </div>
            <div className="num mt-1 text-xs text-text-dim">
              {t.expected && t.planned && t.expected !== t.planned ? (
                <>
                  <s>{t.planned}</s> {t.expected}
                </>
              ) : (
                (t.expected ?? t.planned ?? "—")
              )}
            </div>
            {t.alert ? <p className="mt-1 text-xs text-warn">{t.alert}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}

function Tick({ ok, what }: { ok: boolean; what: string }) {
  return ok ? (
    <span title={`${what} recomputed and verified`} className="ml-1 inline-flex align-middle text-ok">
      <Check size={16} aria-label={`${what} verified`} />
    </span>
  ) : null;
}

export function PoTable({ po, claims }: { po: PoData; claims: StageResult["claims"] }) {
  const subOk = poClaimVerified(claims, "po_total");
  const grandOk = poClaimVerified(claims, "po_grand_total");
  const gstLabel = po.gstRate != null ? `GST ${Math.round(po.gstRate * 100)}%` : "GST";
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Purchase order {po.poNumber}</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs text-text-dim">
            <th scope="col" className="h-9 px-3 font-medium">SKU</th>
            <th scope="col" className="h-9 px-3 text-right font-medium">Units</th>
            <th scope="col" className="h-9 px-3 text-right font-medium">Unit cost</th>
            <th scope="col" className="h-9 px-3 text-right font-medium">Line total</th>
          </tr>
        </thead>
        <tbody>
          {po.lines.map((l) => (
            <tr key={l.code} className="h-10 border-b border-border">
              <td className="px-3">
                <span className="font-mono text-xs text-text-dim">{l.code}</span> {l.name}
                {l.costSource !== "sheet" ? <span className="ml-1"><Tag tone="warn">cost {l.costSource}</Tag></span> : null}
              </td>
              <td className="num px-3 text-right">{l.units}</td>
              <td className="num px-3 text-right">{inrExact(l.unitCost)}</td>
              <td className="num px-3 text-right">{inrExact(l.lineTotal)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="h-9 text-sm">
            <th scope="row" colSpan={3} className="px-3 text-right font-normal text-text-dim">Subtotal</th>
            <td className="num px-3 text-right" data-testid="po-subtotal">
              {inrExact(po.subtotal)}
              <Tick ok={subOk} what="Subtotal" />
            </td>
          </tr>
          <tr className="h-9 text-sm">
            <th scope="row" colSpan={3} className="px-3 text-right font-normal text-text-dim">{gstLabel}</th>
            <td className="num px-3 text-right" data-testid="po-gst">{inrExact(po.gst)}</td>
          </tr>
          <tr className="h-10 border-t border-border font-semibold">
            <th scope="row" colSpan={3} className="px-3 text-right">Grand total</th>
            <td className="num px-3 text-right text-base" data-testid="po-grand">
              {inrExact(po.grandTotal)}
              <Tick ok={grandOk} what="Grand total" />
            </td>
          </tr>
        </tfoot>
      </table>
      {po.gstNote ? <p className="px-3 py-2 text-xs text-text-dim">{po.gstNote}</p> : null}
    </div>
  );
}

export function PoCard({
  stage,
  onApprove,
  approving,
  approveLockedReason,
}: {
  stage: StageResult | undefined | null;
  onApprove?: () => void;
  approving?: boolean;
  approveLockedReason?: string | null;
}) {
  const po = readPo(stage);
  const status = stage?.status ?? "pending";
  return (
    <section aria-label="Purchase order" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title={po ? `Purchase order ${po.poNumber}` : "Purchase order"}
        right={
          status === "done" ? (
            <Tag tone="ok">
              <Check size={16} aria-hidden="true" />
              Approved
            </Tag>
          ) : null
        }
      />
      {po ? (
        <div className="flex flex-col gap-4 pb-4">
          <PoTable po={po} claims={stage?.claims ?? []} />
          <div className="px-4">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-dim">Status</h3>
            <PoTimeline steps={po.timeline} />
          </div>
          {po.timeline.some((t) => t.alert) || po.alerts.length ? (
            <div className="px-4">
              <Banner tone="warn" title="Delay alert at Shipped">
                {po.timeline.find((t) => t.alert)?.alert ?? po.alerts[0]}
              </Banner>
            </div>
          ) : null}
          <div className="flex items-center justify-between gap-3 px-4">
            <p className="num text-xs text-text-dim">{po.paymentDays != null ? `Payment ${po.paymentDays} days` : ""}</p>
            <button
              type="button"
              disabled={status !== "review" || approving || !!approveLockedReason}
              title={approveLockedReason ?? undefined}
              onClick={onApprove}
              className="h-11 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-50"
            >
              {status === "done" ? "PO approved" : approving ? "Approving…" : "Approve PO"}
            </button>
          </div>
        </div>
      ) : (
        <Pending stage={stage} what="The purchase order" running="Raising the purchase order…" />
      )}
    </section>
  );
}

export function LaunchPacket({
  run,
  onApprovePo,
  approving,
  approveLockedReason,
}: {
  run: RunSnapshot | null;
  onApprovePo?: () => void;
  approving?: boolean;
  approveLockedReason?: string | null;
}) {
  const st = run?.stages;
  const locked = st?.marketing?.status === "locked" && st?.po?.status === "locked";
  if (locked) {
    return (
      <Banner tone="bad" title="Launch packet is locked">
        <span className="inline-flex items-center gap-1">
          <Lock size={16} aria-hidden="true" />
          {st?.marketing?.locked_reason ?? "An earlier stage has not passed."}
        </span>
      </Banner>
    );
  }
  return (
    <div className="flex flex-col gap-4" data-testid="launch-packet">
      <section aria-label="Launch packet" className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-base font-semibold">Launch packet</h2>
        <p className="text-sm text-text-dim">Campaign, joint business plan and purchase order, all built from the approved plan and the call.</p>
      </section>
      <MarketingCard stage={st?.marketing} />
      <JbpCard stage={st?.jbp} />
      <PoCard stage={st?.po} onApprove={onApprovePo} approving={approving} approveLockedReason={approveLockedReason} />
    </div>
  );
}
