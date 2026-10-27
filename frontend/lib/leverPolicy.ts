"use client";

import { useEffect, useState } from "react";
import { fetchPolicy } from "./policy";

export type LeverBounds = {
  offsetMin: number;
  offsetMax: number;
  offsetStep: number;
  moqStep: number;
  moqMaxFactor: number;
};

/** Used until (or unless) the playbook answers. */
export const DEFAULT_LEVER_BOUNDS: LeverBounds = {
  offsetMin: -10,
  offsetMax: 10,
  offsetStep: 1,
  moqStep: 50,
  moqMaxFactor: 2,
};

let cached: Promise<LeverBounds> | null = null;
const listeners = new Set<() => void>();

const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

export function boundsFromPolicy(policy: unknown): LeverBounds {
  const lv = (policy as { levers?: Record<string, Record<string, unknown>> } | null)?.levers;
  const mo = lv?.margin_offset ?? {};
  const moq = lv?.moq ?? {};
  const d = DEFAULT_LEVER_BOUNDS;
  const b: LeverBounds = {
    offsetMin: num(mo.min, d.offsetMin),
    offsetMax: num(mo.max, d.offsetMax),
    offsetStep: num(mo.step, d.offsetStep),
    moqStep: num(moq.step, d.moqStep),
    moqMaxFactor: num(moq.max_factor, d.moqMaxFactor),
  };
  return b.offsetMin < b.offsetMax && b.offsetStep > 0 && b.moqStep > 0 ? b : d;
}

function load(): Promise<LeverBounds> {
  cached ??= fetchPolicy()
    .then((r) => boundsFromPolicy(r.policy))
    .catch(() => {
      cached = null; // retry next time; fall back for now
      return DEFAULT_LEVER_BOUNDS;
    });
  return cached;
}

/** Call after a playbook save/reset so open levers refetch their ranges. */
export function invalidateLeverBounds() {
  cached = null;
  listeners.forEach((l) => l());
}

export function useLeverBounds(): LeverBounds {
  const [bounds, setBounds] = useState<LeverBounds>(DEFAULT_LEVER_BOUNDS);
  useEffect(() => {
    let live = true;
    const run = () => void load().then((b) => live && setBounds(b));
    run();
    listeners.add(run);
    return () => {
      live = false;
      listeners.delete(run);
    };
  }, []);
  return bounds;
}
