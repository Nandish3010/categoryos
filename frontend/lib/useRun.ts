"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  eventsHeaders,
  eventsUrl,
  fetchLatestRun,
  fetchRun,
  isMissingEndpoint,
  isRunActive,
  parseTraceEvent,
  startRun,
  type RunSnapshot,
  type TraceEvent,
} from "./runs";
import { streamSse, type SseState } from "./sse";

export type RunState = {
  runId: string | null;
  run: RunSnapshot | null;
  events: TraceEvent[];
  /** Stream connection state, "idle" before any run. */
  conn: SseState | "idle";
  /** True while the latest-run lookup is in flight. */
  loading: boolean;
  starting: boolean;
  /** Backend has no run endpoints (404): UI falls back to the static view. */
  unavailable: boolean;
  error: Error | null;
  start: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Re-open the event stream from the last seen event (a new phase started after an approve). */
  resume: () => void;
};

export function useRun(vendorId: string): RunState {
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [conn, setConn] = useState<SseState | "idle">("idle");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const lastSeq = useRef<number | null>(null);

  // Load the latest run for this vendor on mount.
  useEffect(() => {
    const controller = new AbortController();
    fetchLatestRun(vendorId, controller.signal)
      .then((r) => {
        setRunId(r.run_id);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (isMissingEndpoint(e)) setUnavailable(true);
        else setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
    return () => controller.abort();
  }, [vendorId]);

  // Snapshot + event stream for the current run.
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    const load = () =>
      fetchRun(runId, controller.signal)
        .then((snap) => {
          if (!controller.signal.aborted) setRun(snap);
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") return;
          setError(e instanceof Error ? e : new Error(String(e)));
        });
    load();
    streamSse({
      lastEventId: lastSeq.current != null ? String(lastSeq.current) : null,
      url: eventsUrl(runId),
      headers: eventsHeaders(),
      signal: controller.signal,
      onState: (s) => {
        if (!controller.signal.aborted) setConn(s);
      },
      isDone: (f) => f.event === "trace" && parseTraceEvent(f.data)?.type === "done",
      onFrame: (f) => {
        if (f.event !== "trace") return;
        const ev = parseTraceEvent(f.data);
        if (!ev) return;
        lastSeq.current = Math.max(lastSeq.current ?? 0, ev.seq);
        setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
        if (ev.type === "stage_result" || ev.type === "done") load();
      },
    });
    return () => controller.abort();
  }, [runId, tick]);

  // A phase can still be running after the stream closed on its `done` (a reload mid-phase, or
  // right after an approve): reconnect with Last-Event-ID until nothing is running any more.
  const active = isRunActive(run);
  useEffect(() => {
    if (conn !== "done" || !active) return;
    const t = setTimeout(() => setTick((n) => n + 1), 1000);
    return () => clearTimeout(t);
  }, [conn, active, tick]);

  const resume = useCallback(() => setTick((n) => n + 1), []);

  const start = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const { run_id } = await startRun(vendorId);
      setEvents([]);
      setRun(null);
      lastSeq.current = null;
      setRunId(run_id);
      setTick((t) => t + 1);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setStarting(false);
    }
  }, [vendorId]);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      setRun(await fetchRun(runId));
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, [runId]);

  return { runId, run, events, conn, loading, starting, unavailable, error, start, refresh, resume };
}
