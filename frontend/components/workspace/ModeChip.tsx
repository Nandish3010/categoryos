"use client";

import { useState } from "react";
import { getDemoKey, setDemoKey } from "@/lib/demoKey";

/** Mode chip; opens a small settings popover holding the live demo key (sessionStorage only). */
export function ModeChip({ label, known }: { label: string; known: boolean }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);

  const toggle = () => {
    if (!open) {
      setValue(getDemoKey() ?? "");
      setSaved(false);
    }
    setOpen((o) => !o);
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${label}. Settings`}
        onClick={toggle}
        className={`inline-flex h-6 items-center rounded-chip border px-2 text-xs font-medium whitespace-nowrap ${
          known ? "border-accent/40 bg-accent/10 text-accent" : "border-border bg-surface-2 text-text-dim"
        }`}
      >
        <span className="num">{label}</span>
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="Settings"
          className="absolute right-0 top-8 z-50 w-64 rounded-card border border-border bg-surface-2 p-3 shadow-lg"
        >
          <label htmlFor="live-key" className="mb-1 block text-xs text-text-dim">
            Live key
          </label>
          <input
            id="live-key"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setDemoKey(e.target.value);
              setSaved(true);
            }}
            className="h-11 w-full rounded-card border border-border bg-bg px-2 text-sm"
          />
          <p className="mt-1 text-xs text-text-dim">
            {saved ? "Saved for this tab only. " : ""}Needed only in live mode. Kept in sessionStorage and cleared when the tab closes.
          </p>
        </div>
      ) : null}
    </div>
  );
}
