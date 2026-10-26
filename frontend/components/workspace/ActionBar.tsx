"use client";

import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import type { Progress } from "@/lib/stages";

const APPROVE_LABEL = { research: "Approve and continue", catalog: "Approve catalog", po: "Approve PO" } as const;

export function ActionBar({
  editing,
  onApprove,
  onToggleEdit,
  onReject,
  disabled,
  approveLockedReason,
  approving,
  progress,
}: {
  editing: boolean;
  onApprove: () => void;
  onToggleEdit: () => void;
  onReject: () => void;
  disabled?: boolean;
  /** When set, Approve is disabled and this is shown as its tooltip. */
  approveLockedReason?: string | null;
  approving?: boolean;
  /** Where the run is: which stage Approve targets, or what is running after an approval. */
  progress?: Progress;
}) {
  const [confirming, setConfirming] = useState(false);
  const stageLabel = progress?.kind === "review" ? APPROVE_LABEL[progress.stage] : APPROVE_LABEL.research;

  // After an approval: no button, just what happened and what is running next.
  if (progress && (progress.kind === "running" || progress.kind === "approved") && (progress.kind === "approved" || progress.approved)) {
    return (
      <div className="flex flex-col gap-1" role="status" aria-live="polite" data-testid="approved-state">
        <div className="flex items-center gap-2 text-sm font-semibold text-ok">
          <Check size={16} aria-hidden="true" />
          {progress.kind === "approved" ? `${progress.label} ✓` : "Approved ✓"}
        </div>
        {progress.kind === "running" ? (
          <div className="flex items-center gap-2 text-sm text-text-dim">
            <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            {progress.label}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {confirming ? (
        <div role="alertdialog" aria-label="Confirm reject vendor" className="rounded-card border border-bad/40 bg-bad/10 p-3 text-sm">
          <p>Reject this vendor? This closes the application.</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => {
                setConfirming(false);
                onReject();
              }}
              className="h-11 flex-1 rounded-card bg-bad px-3 font-medium text-bg"
            >
              Confirm reject
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="h-11 flex-1 rounded-card border border-border px-3"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      <button
        type="button"
        disabled={disabled || !!approveLockedReason || approving}
        title={approveLockedReason ?? undefined}
        onClick={onApprove}
        className="h-11 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-50"
      >
        {approving ? "Approving…" : stageLabel}
      </button>
      <div className="flex gap-2">
        <button
          type="button"
          aria-pressed={editing}
          onClick={onToggleEdit}
          className={`h-11 flex-1 rounded-card border px-3 text-sm ${editing ? "border-accent text-accent" : "border-border"}`}
        >
          {editing ? "Done editing" : "Edit decision"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="h-11 flex-1 rounded-card border border-bad/50 px-3 text-sm text-bad"
        >
          Reject vendor
        </button>
      </div>
    </div>
  );
}
