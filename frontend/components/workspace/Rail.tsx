import {
  Boxes,
  ClipboardList,
  FileSignature,
  Handshake,
  ListChecks,
  Megaphone,
  Search,
  ShoppingCart,
  type LucideIcon,
} from "lucide-react";
import { Tag } from "../Chip";

type StageStatus = "Done" | "Active" | "Next" | "Locked";

const STAGES: { id: string; name: string; phase: string; Icon: LucideIcon; status: StageStatus }[] = [
  { id: "intake", name: "Intake", phase: "Screen", Icon: ClipboardList, status: "Done" },
  { id: "research", name: "Research", phase: "Decide", Icon: Search, status: "Active" },
  { id: "shortlist", name: "Shortlist", phase: "Decide", Icon: ListChecks, status: "Active" },
  { id: "negotiate", name: "Negotiate", phase: "Decide", Icon: Handshake, status: "Active" },
  { id: "catalog", name: "Catalog", phase: "Execute", Icon: Boxes, status: "Next" },
  { id: "marketing", name: "Marketing", phase: "Launch", Icon: Megaphone, status: "Locked" },
  { id: "jbp", name: "JBP", phase: "Launch", Icon: FileSignature, status: "Locked" },
  { id: "po", name: "PO", phase: "Launch", Icon: ShoppingCart, status: "Locked" },
];

const TONE = { Done: "ok", Active: "accent", Next: "neutral", Locked: "neutral" } as const;

export function Rail() {
  const phases = Array.from(new Set(STAGES.map((s) => s.phase)));
  return (
    <nav
      aria-label="Stages"
      className="border-r border-border bg-surface max-[899px]:hidden"
    >
      <div className="sticky top-12 flex flex-col gap-4 overflow-y-auto p-2 min-[1280px]:p-3">
        {phases.map((phase) => (
          <section key={phase} aria-label={phase}>
            <h2 className="mb-1 px-2 text-xs font-medium uppercase tracking-wide text-text-dim max-[1279px]:sr-only">
              {phase}
            </h2>
            <ul className="flex flex-col gap-1">
              {STAGES.filter((s) => s.phase === phase).map((s) => (
                <li key={s.id}>
                  <div
                    title={`${s.name} · ${s.status}`}
                    aria-current={s.status === "Active" ? "step" : undefined}
                    className={`flex min-h-10 items-center gap-2 rounded-card px-2 text-sm max-[1279px]:justify-center ${
                      s.status === "Active" ? "bg-surface-2 text-text" : "text-text-dim"
                    } ${s.status === "Locked" ? "opacity-60" : ""}`}
                  >
                    <s.Icon size={16} aria-hidden="true" />
                    <span className="max-[1279px]:sr-only">{s.name}</span>
                    <span className="ml-auto max-[1279px]:hidden">
                      <Tag tone={TONE[s.status]}>{s.status}</Tag>
                    </span>
                    <span className="sr-only min-[1280px]:hidden">{s.status}</span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
