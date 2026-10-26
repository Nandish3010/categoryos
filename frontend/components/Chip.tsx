import {
  CheckCircle2,
  CircleHelp,
  Handshake,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Verdict } from "@/lib/api";

export const VERDICTS: Record<
  Verdict,
  { label: string; Icon: LucideIcon; cls: string }
> = {
  list: { label: "List", Icon: CheckCircle2, cls: "text-ok border-ok/40 bg-ok/10" },
  negotiate: { label: "Negotiate", Icon: Handshake, cls: "text-warn border-warn/40 bg-warn/10" },
  reject: { label: "Reject", Icon: XCircle, cls: "text-bad border-bad/40 bg-bad/10" },
  needs_data: { label: "Needs data", Icon: CircleHelp, cls: "text-warn border-warn/40 bg-warn/10" },
};

const base =
  "inline-flex items-center gap-1 rounded-chip border px-2 h-6 text-xs font-medium whitespace-nowrap";

export function Chip({ verdict }: { verdict: Verdict }) {
  const v = VERDICTS[verdict] ?? VERDICTS.needs_data;
  return (
    <span className={`${base} ${v.cls}`} data-verdict={verdict}>
      <v.Icon size={16} aria-hidden="true" />
      {v.label}
    </span>
  );
}

/** Neutral or toned generic chip for tags and statuses. */
export function Tag({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "accent";
  title?: string;
}) {
  const tones = {
    neutral: "text-text-dim border-border bg-surface-2",
    ok: "text-ok border-ok/40 bg-ok/10",
    warn: "text-warn border-warn/40 bg-warn/10",
    bad: "text-bad border-bad/40 bg-bad/10",
    accent: "text-accent border-accent/40 bg-accent/10",
  } as const;
  return (
    <span className={`${base} ${tones[tone]}`} title={title}>
      {children}
    </span>
  );
}
