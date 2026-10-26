"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLever, type ApiError, type LeverResponse } from "./api";

export const LEVER_DEBOUNCE_MS = 150;

export type LeverFetcher = (
  vendorId: string,
  offset: number,
  moq: number | null,
  signal?: AbortSignal,
) => Promise<LeverResponse>;

export type LeverState = {
  /** Last good response; kept on error. */
  data: LeverResponse | null;
  /** Error from the most recent request, cleared on next success. */
  error: ApiError | Error | null;
  /** True until the first response (drives skeletons). */
  initialLoading: boolean;
  /** True while a debounced or in-flight request is pending. */
  updating: boolean;
  /** Increments on every accepted response. */
  seq: number;
};

type Internal = Omit<LeverState, "updating"> & { settledKey: string | null };

/**
 * Debounced lever fetch. Each change aborts the previous request and bumps a
 * monotonic id so a late response from an older request is dropped.
 */
export function useLever(
  vendorId: string,
  offset: number,
  moq: number | null,
  fetcher: LeverFetcher = fetchLever,
  debounceMs: number = LEVER_DEBOUNCE_MS,
): LeverState {
  const key = `${vendorId}|${offset}|${moq ?? "default"}`;
  const [state, setState] = useState<Internal>({
    data: null,
    error: null,
    initialLoading: true,
    settledKey: null,
    seq: 0,
  });
  const reqId = useRef(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    const id = ++reqId.current;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetcherRef
        .current(vendorId, offset, moq, controller.signal)
        .then((data) => {
          if (id !== reqId.current) return; // stale
          setState((s) => ({
            data,
            error: null,
            initialLoading: false,
            settledKey: key,
            seq: s.seq + 1,
          }));
        })
        .catch((err: unknown) => {
          if (id !== reqId.current) return;
          if (err instanceof DOMException && err.name === "AbortError") return;
          setState((s) => ({
            ...s,
            error: err instanceof Error ? err : new Error(String(err)),
            initialLoading: false,
            settledKey: key,
          }));
        });
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [vendorId, offset, moq, debounceMs, key]);

  const { settledKey, ...rest } = state;
  return { ...rest, updating: settledKey !== key };
}
