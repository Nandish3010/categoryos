import { CheckCircle2, CircleHelp, RotateCcw, XCircle } from "lucide-react";
import type { Claim } from "@/lib/api";
import { inrExact } from "@/lib/format";
import { Tag } from "./Chip";

export function formatClaimValue(value: number | string | null | undefined, unit: Claim["unit"], metric?: string): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string") return value;
  if (metric === "deal_probability") return value < 0.001 ? "<0.1%" : `${(value * 100).toFixed(1)}%`;
  switch (unit) {
    case "inr":
      return inrExact(value);
    case "pct":
      // Backend may send fractions (0.31) or percent points (31.4); treat |v|<=1 as a fraction.
      return `${(Math.abs(value) <= 1 ? value * 100 : value).toFixed(1)}%`;
    case "units":
      return `${Math.round(value)} units`;
    case "qty":
      return `${Math.round(value * 1000) / 1000}`;
    case "ratio":
      // 0-1 scores (demand, overlap) print as the backend sees them; a deal probability reads as a percent
      return value.toFixed(2);
    case "pts":
      return `${value.toFixed(1)} pts`;
    default:
      return String(Math.round(value * 100) / 100);
  }
}

export function sourceLabel(c: Claim): string {
  if (c.origin === "vision_extraction" && c.evidence?.doc) {
    return [c.evidence.doc, c.evidence.page != null ? `p${c.evidence.page}` : null, c.source_ref.column].filter(Boolean).join(" · ");
  }
  const parts = [c.source_ref.file];
  if (c.evidence?.row != null) parts.push(`row ${c.evidence.row}`);
  const col = c.source_ref.column ?? c.evidence?.header;
  if (col) parts.push(col);
  return parts.join(" · ");
}

const STATUS = {
  verified: { Icon: CheckCircle2, cls: "text-ok", label: "Verified" },
  rejected: { Icon: XCircle, cls: "text-bad", label: "Rejected" },
  unverifiable: { Icon: CircleHelp, cls: "text-warn", label: "Unverifiable" },
  pending: { Icon: CircleHelp, cls: "text-text-dim", label: "Pending" },
} as const;

/** A claim the verifier rejected at least once and the agent then answered again. */
export function wasRetried(claim: Claim): boolean {
  return (claim.attempts?.length ?? 0) > 1;
}

/** Caught, then fixed by the agent. */
export function isCorrected(claim: Claim): boolean {
  return claim.status === "verified" && wasRetried(claim);
}

function Attempts({ claim }: { claim: Claim }) {
  const tries = claim.attempts ?? [];
  return (
    <ol aria-label="Attempts" className="mt-2 flex flex-col gap-1 border-l-2 border-border pl-3 text-xs">
      {tries.map((a) => (
        <li key={a.attempt} data-status={a.status} className={a.status === "verified" ? "text-ok" : "text-bad"}>
          <span className="num">
            {a.attempt === 0 ? "First answer" : `Retry ${a.attempt}`}: {formatClaimValue(a.value, claim.unit)} {"·"}{" "}
            {a.status === "verified" ? "verified" : "rejected"}
          </span>
          {a.status !== "verified" && a.reason ? <span className="block text-text-dim">{a.reason}</span> : null}
        </li>
      ))}
    </ol>
  );
}

export function ClaimRow({ claim, onHover }: { claim: Claim; onHover?: (claim: Claim | null) => void }) {
  const corrected = isCorrected(claim);
  const s = corrected ? { Icon: RotateCcw, cls: "text-ok", label: "Caught, then corrected" } : (STATUS[claim.status] ?? STATUS.pending);
  const rejected = claim.status === "rejected";
  const sheetValue = claim.recomputed ?? claim.evidence?.normalized_value ?? null;
  const injected = claim.origin === "injected_test";
  const vision = claim.origin === "vision_extraction";
  const hover = onHover
    ? {
        tabIndex: 0,
        onMouseEnter: () => onHover(claim),
        onMouseLeave: () => onHover(null),
        onFocus: () => onHover(claim),
        onBlur: () => onHover(null),
      }
    : {};

  return (
    <li
      className={`border-b border-border px-4 py-2 last:border-b-0 ${rejected ? "bg-bad/10" : corrected ? "bg-ok/5" : ""}`}
      data-status={corrected ? "corrected" : claim.status}
      data-origin={claim.origin}
      {...hover}
    >
      <div className="flex items-start gap-2">
        <s.Icon size={16} className={`mt-0.5 shrink-0 ${s.cls}`} aria-label={s.label} />
        <div className="min-w-0 flex-1">
          <div className={`text-sm ${rejected ? "line-through decoration-bad/60" : ""}`}>
            {claim.text}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="num text-xs text-text-dim">
              {formatClaimValue(claim.value, claim.unit, claim.metric)}
              {claim.status === "verified"
                ? vision
                  ? " · matches the re-read of the crop"
                  : claim.origin === "model_extraction"
                    ? " · matches sheet cell"
                    : " · recomputed from"
                : ""}
            </span>
            <span className="rounded-chip border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text-dim">
              {sourceLabel(claim)}
            </span>
            {injected ? <Tag tone="warn">Injected test</Tag> : null}
            {vision ? <Tag tone="accent">Scan</Tag> : null}
            {corrected ? <Tag tone="ok">Caught → corrected</Tag> : null}
            {rejected && wasRetried(claim) ? <Tag tone="bad">Unresolved after {(claim.attempts?.length ?? 1) - 1} {(claim.attempts?.length ?? 1) - 1 === 1 ? "retry" : "retries"}</Tag> : null}
          </div>
          {wasRetried(claim) ? <Attempts claim={claim} /> : null}
          {rejected && vision ? (
            <div className="mt-2 rounded-chip border border-bad/40 bg-bad/10 p-2 text-sm text-bad">
              <span className="num">
                Page read “{claim.evidence?.raw_value ?? "?"}” {"·"} Re-read of the crop “{claim.evidence?.reread_value ?? "?"}”
              </span>
              {claim.reason ? <div className="mt-0.5 text-xs text-text-dim">{claim.reason}</div> : null}
            </div>
          ) : rejected ? (
            <div className="mt-2 rounded-chip border border-bad/40 bg-bad/10 p-2 text-sm text-bad">
              <span className="num">
                Agent said {formatClaimValue(claim.value, claim.unit, claim.metric)} {"·"} Sheet says{" "}
                {formatClaimValue(sheetValue, claim.unit, claim.metric)}
              </span>
              {claim.evidence?.raw_value ? (
                <div className="mt-0.5 text-xs text-text-dim">
                  Raw cell: <span className="font-mono">{claim.evidence.raw_value}</span>
                </div>
              ) : null}
              {claim.reason ? <div className="mt-0.5 text-xs text-text-dim">{claim.reason}</div> : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
