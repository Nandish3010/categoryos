import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEMO_KEY_STORAGE } from "./demoKey";
import { useRun } from "./useRun";
import { mockBackend, type Call, researchData, snapshot, stage, traceEvent } from "../test-utils/mockBackend";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("useRun", () => {
  it("loads the latest run, streams its events and refetches the snapshot on stage_result/done", async () => {
    const run = snapshot({ research: stage("research", { data: researchData }) });
    const calls: Call[] = [];
    vi.stubGlobal(
      "fetch",
      mockBackend({
        run,
        calls,
        events: [traceEvent(1), traceEvent(2, { type: "stage_result" }), traceEvent(3, { type: "done", stage: null })],
      }),
    );
    const { result } = renderHook(() => useRun("V001"));
    await waitFor(() => expect(result.current.events).toHaveLength(3));
    expect(result.current.runId).toBe("run1");
    await waitFor(() => expect(result.current.conn).toBe("done"));
    expect(result.current.run?.stages.research?.status).toBe("done");
    // initial load + stage_result + done
    const snapshotFetches = calls.filter((c) => c.method === "GET" && c.path === "/api/runs/run1");
    expect(snapshotFetches.length).toBeGreaterThanOrEqual(3);
  });

  it("starts a run, sending the demo key from sessionStorage", async () => {
    sessionStorage.setItem(DEMO_KEY_STORAGE, "k-test");
    const calls: Call[] = [];
    vi.stubGlobal("fetch", mockBackend({ run: null, calls }));
    const { result } = renderHook(() => useRun("V001"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.runId).toBeNull();
    await act(async () => {
      await result.current.start();
    });
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/vendors/V001/runs")!;
    expect(post.headers["x-demo-key"]).toBe("k-test");
    expect(result.current.runId).toBe("run1");
  });

  it("de-dupes replayed events by seq", async () => {
    vi.stubGlobal(
      "fetch",
      mockBackend({
        run: snapshot({}),
        events: [traceEvent(1), traceEvent(1), traceEvent(2, { type: "done", stage: null })],
      }),
    );
    const { result } = renderHook(() => useRun("V001"));
    await waitFor(() => expect(result.current.conn).toBe("done"));
    expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
  });

  it("marks run endpoints unavailable on 404 and degrades quietly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    const { result } = renderHook(() => useRun("V001"));
    await waitFor(() => expect(result.current.unavailable).toBe(true));
    expect(result.current.error).toBeNull();
  });
});
