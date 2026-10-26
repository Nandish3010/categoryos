"use client";

import { ChevronDown, ChevronRight, ShieldCheck } from "lucide-react";
import { ApiError, type ClaimsResponse } from "@/lib/api";
import { ClaimRow } from "../ClaimRow";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Tag } from "../Chip";

export function VerifierCard({
  base,
  baseLoading,
  baseError,
  injected,
  injectedLoading,
  injectOn,
  onToggleInject,
}: {
  base: ClaimsResponse | null;
  baseLoading: boolean;
  baseError: Error | null;
  injected: ClaimsResponse | null;
  injectedLoading: boolean;
  injectOn: boolean;
  onToggleInject: () => void;
}) {
  const shown = injectOn && injected ? injected : base;
  const unavailable = baseError instanceof ApiError && baseError.status === 404;
  const sorted = shown
    ? [...shown.claims].sort((a, b) => Number(b.status === "rejected") - Number(a.status === "rejected"))
    : [];

  return (
    <section aria-label="Verifier" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Verifier"
        right={
          shown ? (
            <span className="num inline-flex items-center gap-1">
              <ShieldCheck size={16} aria-hidden="true" />
              {shown.verified}/{shown.total} verified
            </span>
          ) : null
        }
      />
      {baseLoading && !shown ? (
        <div className="flex flex-col gap-2 p-4" aria-label="Verifying" role="status">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : unavailable ? (
        <p className="p-4 text-sm text-text-dim">
          Verifier unavailable: this backend has no claims endpoint yet.
        </p>
      ) : !shown ? (
        <p className="p-4 text-sm text-text-dim">
          Claims unavailable{baseError ? `: ${baseError.message}` : ""}. Unverifiable.
        </p>
      ) : shown.total === 0 ? (
        <p className="p-4 text-sm text-text-dim">No claims in this stage.</p>
      ) : (
        <>
          <ul className="max-h-96 overflow-y-auto">
            {sorted.map((c) => (
              <ClaimRow key={c.id} claim={c} />
            ))}
          </ul>
          <div className="border-t border-border px-4 py-2 text-xs text-text-dim">
            <span className="num">
              {shown.verified} verified
              {shown.rejected > 0 ? ` · ${shown.rejected} rejected and removed` : ""}
              {shown.unverifiable > 0 ? ` · ${shown.unverifiable} unverifiable` : ""}
            </span>
          </div>
        </>
      )}
      {!unavailable && (base || injectOn) ? (
        <div className="border-t border-border px-4 py-2">
          <button
            type="button"
            aria-expanded={injectOn}
            onClick={onToggleInject}
            className="inline-flex min-h-8 items-center gap-1 text-xs text-accent hover:underline"
          >
            {injectOn ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
            Test the verifier
          </button>
          {injectOn ? (
            <p className="text-xs text-text-dim">
              {injectedLoading
                ? "Injecting wrong claims…"
                : "Deliberately wrong claims are injected and labelled “Injected test”. The verifier should reject them."}{" "}
              {injected ? <Tag tone="warn">Injected test</Tag> : null}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

