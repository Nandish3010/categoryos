import {
  Boxes,
  ClipboardList,
  FileSignature,
  Handshake,
  ListChecks,
  Lock,
  Megaphone,
  Search,
  ShoppingCart,
  type LucideIcon,
} from "lucide-react";
import type { RunSnapshot, RunStageStatus, StageId } from "@/lib/runs";
import { Tag } from "../Chip";

type Label = "Done" | "Active" | "Next" | "Locked" | "Running" | "Review" | "Failed" | "Degraded";

const STAGES: { id: StageId; name: string; phase: string; Icon: LucideIcon; status: Label }[] = [
  { id: "intake", name: "Intake", phase: "Screen", Icon: ClipboardList, status: "Done" },
  { id: "research", name: "Research", phase: "Decide", Icon: Search, status: "Active" },
  { id: "shortlist", name: "Shortlist", phase: "Decide", Icon: ListChecks, status: "Active" },
  { id: "negotiate", name: "Negotiate", phase: "Decide", Icon: Handshake, status: "Active" },
  { id: "catalog", name: "Catalog", phase: "Execute", Icon: Boxes, status: "Next" },
  { id: "marketing", name: "Marketing", phase: "Launch", Icon: Megaphone, status: "Locked" },
  { id: "jbp", name: "JBP", phase: "Launch", Icon: FileSignature, status: "Locked" },
  { id: "po", name: "PO", phase: "Launch", Icon: ShoppingCart, status: "Locked" },
];

const TONE = {
  Done: "ok",
  Active: "accent",
  Next: "neutral",
  Locked: "neutral",
  Running: "accent",
  Review: "warn",
  Failed: "bad",
  Degraded: "warn",
} as const;

const FROM_RUN: Record<RunStageStatus, Label> = {
  pending: "Next",
  running: "Running",
  review: "Review",
  done: "Done",
  locked: "Locked",
  failed: "Failed",
  degraded: "Degraded",
};

export function Rail({ stages }: { stages?: RunSnapshot["stages"] | null }) {
  const phases = Array.from(new Set(STAGES.map((s) => s.phase)));
  return (
    <nav aria-label="Stages" className="border-r border-border bg-surface max-[899px]:hidden">
      <div className="sticky top-12 flex flex-col gap-4 overflow-y-auto p-2 min-[1280px]:p-3">
        {phases.map((phase) => (
          <section key={phase} aria-label={phase}>
            <h2 className="mb-1 px-2 text-xs font-medium uppercase tracking-wide text-text-dim max-[1279px]:sr-only">
              {phase}
            </h2>
            <ul className="flex flex-col gap-1">
              {STAGES.filter((s) => s.phase === phase).map((s) => {
                const result = stages?.[s.id];
                const status: Label = result ? FROM_RUN[result.status] : s.status;
                const active = status === "Active" || status === "Running" || status === "Review";
                const reason = status === "Locked" ? result?.locked_reason : null;
                return (
                  <li key={s.id}>
                    <div
                      title={reason ? `${s.name} · Locked: ${reason}` : `${s.name} · ${status}`}
                      data-stage={s.id}
                      data-status={status}
                      aria-current={active ? "step" : undefined}
                      className={`flex min-h-10 items-center gap-2 rounded-card px-2 text-sm max-[1279px]:justify-center ${
                        active ? "bg-surface-2 text-text" : "text-text-dim"
                      } ${status === "Locked" ? "opacity-60" : ""}`}
                    >
                      {status === "Locked" ? (
                        <Lock size={16} aria-hidden="true" />
                      ) : (
                        <s.Icon size={16} aria-hidden="true" />
                      )}
                      <span className="max-[1279px]:sr-only">{s.name}</span>
                      <span className="ml-auto max-[1279px]:hidden">
                        <Tag tone={TONE[status]}>{status}</Tag>
                      </span>
                      <span className="sr-only min-[1280px]:hidden">
                        {status}
                        {reason ? `: ${reason}` : ""}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
