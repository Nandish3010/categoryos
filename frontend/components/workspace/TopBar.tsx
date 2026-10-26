import { ChevronRight, PanelRight } from "lucide-react";
import Link from "next/link";
import type { ClaimsResponse, ModeResponse } from "@/lib/api";
import { Tag } from "../Chip";

const PHASES = ["Screen", "Decide", "Execute", "Launch"] as const;

export function modeLabel(mode: ModeResponse | null, claims: ClaimsResponse | null): string {
  if (!mode) return "Mode unavailable";
  const name = mode.mode.charAt(0).toUpperCase() + mode.mode.slice(1);
  const parts = [name, `$${mode.spend_usd.toFixed(2)}`];
  if (claims) parts.push(`${claims.verified}/${claims.total} verified`);
  return parts.join(" · ");
}

export function TopBar({
  vendorId,
  brand,
  mode,
  claims,
  onToggleDrawer,
}: {
  vendorId: string;
  brand: string | null;
  mode: ModeResponse | null;
  claims: ClaimsResponse | null;
  onToggleDrawer: () => void;
}) {
  return (
    <header className="sticky top-0 z-40 flex h-12 items-center gap-3 border-b border-border bg-bg px-4">
      <Link href="/" className="text-sm font-semibold tracking-tight">
        CategoryOS
      </Link>
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm text-text-dim">
        <ChevronRight size={16} aria-hidden="true" />
        <span className="truncate">
          {brand ? `${brand} · ` : ""}
          <span className="font-mono">{vendorId}</span>
        </span>
      </nav>

      <ol
        aria-label="Phase"
        className="mx-auto flex items-center gap-1 text-xs max-[899px]:hidden"
      >
        {PHASES.map((p, i) => (
          <li key={p} className="flex items-center gap-1">
            <span
              aria-current={p === "Decide" ? "step" : undefined}
              className={`rounded-chip px-2 py-1 ${
                p === "Decide" ? "bg-accent/15 font-medium text-accent" : "text-text-dim"
              }`}
            >
              {p}
            </span>
            {i < PHASES.length - 1 ? (
              <ChevronRight size={16} className="text-border" aria-hidden="true" />
            ) : null}
          </li>
        ))}
      </ol>

      <div className="ml-auto flex items-center gap-2 min-[900px]:ml-0">
        <Tag tone={mode ? "accent" : "neutral"}>
          <span className="num">{modeLabel(mode, claims)}</span>
        </Tag>
      </div>
      <button
        type="button"
        onClick={onToggleDrawer}
        aria-label="Toggle verifier panel"
        className="inline-flex h-11 w-11 items-center justify-center rounded-card border border-border text-text-dim hover:bg-surface-2 min-[900px]:max-[1279px]:inline-flex min-[1280px]:hidden max-[899px]:hidden"
      >
        <PanelRight size={16} aria-hidden="true" />
      </button>
    </header>
  );
}
