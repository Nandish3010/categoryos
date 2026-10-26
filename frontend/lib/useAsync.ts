"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Fetch once per `key`, keep the last good data on error, and optionally
 * retry on a timer while in error.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  key: string,
  opts: { retryMs?: number } = {},
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const { retryMs } = opts;

  useEffect(() => {
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout> | undefined;
    fnRef
      .current(controller.signal)
      .then((d) => {
        setData(d);
        setError(null);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
        if (retryMs) retry = setTimeout(() => setTick((t) => t + 1), retryMs);
      });
    return () => {
      controller.abort();
      if (retry) clearTimeout(retry);
    };
  }, [key, tick, retryMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
