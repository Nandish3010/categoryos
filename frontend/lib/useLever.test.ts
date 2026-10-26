import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeverResponse } from "./api";
import { useLever, type LeverFetcher } from "./useLever";

function resp(tag: number): LeverResponse {
  return {
    vendor_id: "V001",
    target_margin_pct_offset: tag,
    skus: [],
    summary: {
      counts: {},
      moq: 150,
      shortlisted: 0,
      capital_at_risk_inr: tag,
      days_of_cover: null,
      est_monthly_gmv: 0,
      moq_flag: false,
    },
    metrics_hash: String(tag),
    computed_ms: 1,
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useLever", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces rapid changes into one request", async () => {
    const fetcher = vi.fn<LeverFetcher>(async (_v, offset) => resp(offset));
    const { rerender } = renderHook(({ o }) => useLever("V001", o, null, fetcher), {
      initialProps: { o: 0 },
    });
    rerender({ o: 1 });
    rerender({ o: 2 });
    rerender({ o: 3 });
    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1]).toBe(3);
  });

  it("aborts the previous in-flight request", async () => {
    const signals: AbortSignal[] = [];
    const fetcher: LeverFetcher = (_v, offset, _m, signal) => {
      signals.push(signal!);
      return new Promise(() => {
        void offset;
      });
    };
    const { rerender } = renderHook(({ o }) => useLever("V001", o, null, fetcher), {
      initialProps: { o: 0 },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    rerender({ o: 5 });
    expect(signals[0].aborted).toBe(true);
  });

  it("drops a stale response that resolves after a newer one", async () => {
    const d: ReturnType<typeof deferred<LeverResponse>>[] = [];
    const fetcher: LeverFetcher = () => {
      const x = deferred<LeverResponse>();
      d.push(x);
      return x.promise;
    };
    const { result, rerender } = renderHook(({ o }) => useLever("V001", o, null, fetcher), {
      initialProps: { o: 1 },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    rerender({ o: 2 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(d).toHaveLength(2);
    await act(async () => {
      d[1].resolve(resp(2));
    });
    expect(result.current.data?.target_margin_pct_offset).toBe(2);
    await act(async () => {
      d[0].resolve(resp(1)); // stale, must be ignored
    });
    expect(result.current.data?.target_margin_pct_offset).toBe(2);
    expect(result.current.seq).toBe(1);
  });

  it("keeps last good data when a later request fails", async () => {
    let n = 0;
    const fetcher: LeverFetcher = async (_v, offset) => {
      if (n++ > 0) throw new Error("boom");
      return resp(offset);
    };
    const { result, rerender } = renderHook(({ o }) => useLever("V001", o, null, fetcher), {
      initialProps: { o: 1 },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(result.current.data).not.toBeNull();
    rerender({ o: 2 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(result.current.error?.message).toBe("boom");
    expect(result.current.data?.target_margin_pct_offset).toBe(1);
  });
});
