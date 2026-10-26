"use client";

import { useTween } from "@/lib/motion";

/** Renders `format(value)` with a 250 ms tween between values. */
export function Tween({
  value,
  format,
  ms = 250,
}: {
  value: number;
  format: (n: number) => string;
  ms?: number;
}) {
  const v = useTween(value, ms);
  return <span className="num">{format(v)}</span>;
}
