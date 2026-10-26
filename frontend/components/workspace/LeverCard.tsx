"use client";

import { pp } from "@/lib/format";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { Slider } from "../Slider";
import { Tag } from "../Chip";

export const OFFSET_MIN = -10;
export const OFFSET_MAX = 10;
export const MOQ_STEP = 50;

export function LeverCard({
  offset,
  moq,
  defaultMoq,
  updating,
  failed,
  onOffset,
  onMoq,
  onResetAll,
}: {
  offset: number;
  moq: number | null;
  defaultMoq: number | null;
  updating: boolean;
  failed: boolean;
  onOffset: (v: number) => void;
  onMoq: (v: number | null) => void;
  onResetAll: () => void;
}) {
  const changed = offset !== 0 || (moq != null && moq !== defaultMoq);
  return (
    <section aria-label="Levers" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Levers"
        right={
          <span className="flex items-center gap-2">
            {failed ? <Tag tone="warn">Couldn&apos;t update</Tag> : null}
            {updating && !failed ? <span aria-hidden="true">Updating&hellip;</span> : null}
            {changed ? (
              <button
                type="button"
                onClick={onResetAll}
                className="min-h-6 rounded px-1 text-accent hover:underline"
              >
                Reset all
              </button>
            ) : null}
          </span>
        }
      />
      <div className="grid gap-6 p-4 md:grid-cols-2">
        <Slider
          label="Target margin"
          value={offset}
          min={OFFSET_MIN}
          max={OFFSET_MAX}
          step={1}
          display={offset === 0 ? "category target" : `category target ${pp(offset)}`}
          valueText={
            offset === 0
              ? "at the category target"
              : `category target ${offset > 0 ? "plus" : "minus"} ${Math.abs(offset)} percentage points`
          }
          onChange={onOffset}
          onReset={() => onOffset(0)}
          resetLabel="Reset to category target"
        />
        {defaultMoq == null ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-11 w-full" />
          </div>
        ) : (
          <Slider
            label="MOQ"
            value={moq ?? defaultMoq}
            min={0}
            max={Math.max(defaultMoq * 2, MOQ_STEP * 2)}
            step={MOQ_STEP}
            display={`${moq ?? defaultMoq} units`}
            valueText={`${moq ?? defaultMoq} units minimum order quantity`}
            onChange={onMoq}
            onReset={() => onMoq(null)}
            resetLabel={`Reset to ${defaultMoq}`}
          />
        )}
      </div>
    </section>
  );
}
