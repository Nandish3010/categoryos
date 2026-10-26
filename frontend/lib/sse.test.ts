import { describe, expect, it, vi } from "vitest";
import { SseParser, streamSse, type SseFrame } from "./sse";

const enc = new TextEncoder();

function streamOf(chunks: string[], opts: { error?: boolean } = {}) {
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      if (opts.error) c.error(new Error("network down"));
      else c.close();
    },
  });
}

describe("SseParser", () => {
  it("parses a complete frame", () => {
    const frames = new SseParser().push('id: 1\nevent: trace\ndata: {"a":1}\n\n');
    expect(frames).toEqual([{ id: "1", event: "trace", data: '{"a":1}' }]);
  });

  it("reassembles frames split across chunks, even mid-line", () => {
    const p = new SseParser();
    expect(p.push("id: 7\nevent: tr")).toEqual([]);
    expect(p.push('ace\ndata: {"x"')).toEqual([]);
    expect(p.push(':2}\n')).toEqual([]);
    expect(p.push("\n")).toEqual([{ id: "7", event: "trace", data: '{"x":2}' }]);
  });

  it("handles CRLF split between chunks", () => {
    const p = new SseParser();
    expect(p.push("id: 1\r\ndata: hi\r")).toEqual([]);
    expect(p.push("\n\r\n")).toEqual([{ id: "1", event: "message", data: "hi" }]);
  });

  it("ignores ': ping' heartbeats and emits several frames from one chunk", () => {
    const frames = new SseParser().push(": ping\n\nid: 1\ndata: a\n\n: ping\n\nid: 2\ndata: b\n\n");
    expect(frames.map((f) => f.id)).toEqual(["1", "2"]);
    expect(frames.map((f) => f.data)).toEqual(["a", "b"]);
  });

  it("joins multi-line data", () => {
    expect(new SseParser().push("data: a\ndata: b\n\n")[0].data).toBe("a\nb");
  });
});

const isDone = (f: SseFrame) => f.data === "done";
const noSleep = () => Promise.resolve();

describe("streamSse", () => {
  it("resumes with Last-Event-ID after a dropped stream and stops on done", async () => {
    const calls: Record<string, string>[] = [];
    const bodies = [
      streamOf(["id: 1\ndata: a\n\nid: 2\ndata: b\n\n"]), // closes with no done: reconnect
      streamOf(["id: 3\ndata: done\n\n"]),
    ];
    const fetchImpl = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init?.headers as Record<string, string>);
      return new Response(bodies.shift(), { status: 200 });
    });
    const got: string[] = [];
    const states: string[] = [];
    await streamSse({
      url: "http://x/events",
      signal: new AbortController().signal,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleep: noSleep,
      isDone,
      onFrame: (f) => got.push(f.data),
      onState: (s) => states.push(s),
    });
    expect(got).toEqual(["a", "b", "done"]);
    expect(calls[0]["Last-Event-ID"]).toBeUndefined();
    expect(calls[1]["Last-Event-ID"]).toBe("2");
    expect(fetchImpl).toHaveBeenCalledTimes(2); // stopped after done
    expect(states).toContain("reconnecting");
    expect(states.at(-1)).toBe("done");
  });

  it("reconnects after a network error with exponential backoff capped at 5s", async () => {
    const delays: number[] = [];
    let n = 0;
    const fetchImpl = vi.fn(async () => {
      n += 1;
      if (n <= 5) throw new TypeError("offline");
      return new Response(streamOf(["id: 1\ndata: done\n\n"]), { status: 200 });
    });
    await streamSse({
      url: "http://x/events",
      signal: new AbortController().signal,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleep: (ms) => {
        delays.push(ms);
        return Promise.resolve();
      },
      isDone,
      onFrame: () => {},
    });
    expect(delays).toEqual([1000, 2000, 4000, 5000, 5000]);
  });

  it("stops without retrying on a 4xx", async () => {
    const fetchImpl = vi.fn(async () => new Response("nope", { status: 404 }));
    const states: string[] = [];
    await streamSse({
      url: "http://x/events",
      signal: new AbortController().signal,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleep: noSleep,
      onFrame: () => {},
      onState: (s) => states.push(s),
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(states.at(-1)).toBe("error");
  });

  it("stops when aborted", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    await streamSse({
      url: "http://x/events",
      signal: controller.signal,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleep: noSleep,
      onFrame: () => {},
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
