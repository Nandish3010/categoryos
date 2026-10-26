import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import type { Claim } from "@/lib/api";
import { inr } from "@/lib/format";
import { Tag } from "./Chip";

export function formatClaimValue(value: number | string | null | undefined, unit: Claim["unit"]): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string") return value;
  switch (unit) {
    case "inr":
      return inr(value);
    case "pct":
      // Backend may send fractions (0.31) or percent points (31.4); treat |v|<=1 as a fraction.
      return `${(Math.abs(value) <= 1 ? value * 100 : value).toFixed(1)}%`;
    case "units":
      return `${Math.round(value)} units`;
    case "ratio":
      return value.toFixed(2); // 0-1 scores (demand, overlap), shown as the backend sees them
    default:
      return String(Math.round(value * 100) / 100);
  }
}

export function sourceLabel(c: Claim): string {
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

export function ClaimRow({ claim }: { claim: Claim }) {
  const s = STATUS[claim.status] ?? STATUS.pending;
  const rejected = claim.status === "rejected";
  const sheetValue = claim.recomputed ?? claim.evidence?.normalized_value ?? null;
  const injected = claim.origin === "injected_test";

  return (
    <li
      className={`border-b border-border px-4 py-2 last:border-b-0 ${rejected ? "bg-bad/10" : ""}`}
      data-status={claim.status}
    >
      <div className="flex items-start gap-2">
        <s.Icon size={16} className={`mt-0.5 shrink-0 ${s.cls}`} aria-label={s.label} />
        <div className="min-w-0 flex-1">
          <div className={`text-sm ${rejected ? "line-through decoration-bad/60" : ""}`}>
            {claim.text}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="num text-xs text-text-dim">
              {formatClaimValue(claim.value, claim.unit)}
              {claim.status === "verified"
                ? claim.origin === "model_extraction"
                  ? " · matches sheet cell"
                  : " · recomputed from"
                : ""}
            </span>
            <span className="rounded-chip border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text-dim">
              {sourceLabel(claim)}
            </span>
            {injected ? <Tag tone="warn">Injected test</Tag> : null}
          </div>
          {rejected ? (
            <div className="mt-2 rounded-chip border border-bad/40 bg-bad/10 p-2 text-sm text-bad">
              <span className="num">
                Agent said {formatClaimValue(claim.value, claim.unit)} {"·"} Sheet says{" "}
                {formatClaimValue(sheetValue, claim.unit)}
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
