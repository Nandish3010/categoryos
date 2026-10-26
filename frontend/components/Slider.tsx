"use client";

import { useId, type KeyboardEvent } from "react";

export function Slider({
  label,
  value,
  min,
  max,
  step,
  valueText,
  display,
  onChange,
  onReset,
  resetLabel = "Reset",
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  /** Spoken value, e.g. "category target plus 3 percentage points". */
  valueText: string;
  /** Visible value text. */
  display: string;
  onChange: (v: number) => void;
  onReset?: () => void;
  resetLabel?: string;
}) {
  const id = useId();

  // Native range handles one-step arrows; add Shift+arrow = 5 steps.
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!e.shiftKey) return;
    const dir = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    onChange(Math.min(max, Math.max(min, value + dir * 5 * step)));
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <span className="num text-sm text-accent">{display}</span>
      </div>
      <input
        id={id}
        type="range"
        className="h-11 w-full cursor-pointer accent-accent"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={valueText}
        onChange={(e) => onChange(Number(e.target.value))}
        onKeyDown={onKeyDown}
      />
      <div className="flex items-center justify-between text-xs text-text-dim">
        <span className="num">{min}</span>
        {onReset ? (
          <button
            type="button"
            onClick={onReset}
            className="min-h-6 rounded px-1 text-accent hover:underline"
          >
            {resetLabel}
          </button>
        ) : null}
        <span className="num">{max}</span>
      </div>
    </div>
  );
}
