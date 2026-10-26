"use client";

import { useState } from "react";

export function ActionBar({
  editing,
  onApprove,
  onToggleEdit,
  onReject,
  disabled,
}: {
  editing: boolean;
  onApprove: () => void;
  onToggleEdit: () => void;
  onReject: () => void;
  disabled?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
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
        disabled={disabled}
        onClick={onApprove}
        className="h-11 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-50"
      >
        Approve and continue
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
