/**
 * Minimal SSE client over fetch + ReadableStream. EventSource cannot send
 * headers (X-Demo-Key, Last-Event-ID on reconnect), so frames are parsed by hand.
 */

export type SseFrame = { id: string | null; event: string; data: string };

export class SseParser {
  private buf = "";
  private id: string | null = null;
  private event = "";
  private data: string[] = [];

  /** Feed a decoded text chunk; returns the frames completed by it. */
  push(chunk: string): SseFrame[] {
    this.buf += chunk;
    const out: SseFrame[] = [];
    const eol = /\r\n|\n|\r/;
    for (;;) {
      const m = eol.exec(this.buf);
      if (!m) break;
      // A trailing "\r" may be the first half of "\r\n": wait for more input.
      if (m[0] === "\r" && m.index + 1 === this.buf.length) break;
      const line = this.buf.slice(0, m.index);
      this.buf = this.buf.slice(m.index + m[0].length);
      const frame = this.line(line);
      if (frame) out.push(frame);
    }
    return out;
  }

  private line(line: string): SseFrame | null {
    if (line === "") {
      if (this.data.length === 0) {
        this.event = "";
        this.id = null;
        return null;
      }
      const frame = { id: this.id, event: this.event || "message", data: this.data.join("\n") };
      this.event = "";
      this.data = [];
      this.id = null;
      return frame;
    }
    if (line.startsWith(":")) return null; // comment / heartbeat
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    let value = i === -1 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") this.id = value;
    else if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    return null;
  }
}

export type SseState = "connecting" | "open" | "reconnecting" | "done" | "error";

export type SseOptions = {
  url: string;
  headers?: Record<string, string>;
  signal: AbortSignal;
  onFrame: (frame: SseFrame) => void;
  /** Return true to stop the stream for good (e.g. the "done" event). */
  isDone?: (frame: SseFrame) => boolean;
  onState?: (state: SseState) => void;
  lastEventId?: string | null;
  fetchImpl?: typeof fetch;
  /** Reconnect delays; the last value repeats. */
  backoffMs?: number[];
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
};

export const SSE_BACKOFF_MS = [1000, 2000, 4000, 5000];

export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const done = () => {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const t = setTimeout(done, ms);
    signal.addEventListener("abort", done);
  });
}

/**
 * Streams until `isDone`, abort, or a non-retryable HTTP error. Reconnects with
 * `Last-Event-ID` after a dropped stream or network error.
 */
export async function streamSse(opts: SseOptions): Promise<void> {
  const {
    url,
    signal,
    onFrame,
    isDone,
    onState,
    fetchImpl = (...a: Parameters<typeof fetch>) => fetch(...a),
    backoffMs = SSE_BACKOFF_MS,
    sleep = abortableSleep,
  } = opts;
  let lastId = opts.lastEventId ?? null;
  let failures = 0;
  onState?.("connecting");

  while (!signal.aborted) {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream", ...opts.headers };
      if (lastId != null) headers["Last-Event-ID"] = lastId;
      const res = await fetchImpl(url, { headers, signal, cache: "no-store" });
      if (!res.ok || !res.body) {
        if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
          onState?.("error");
          return;
        }
        throw new Error(`SSE HTTP ${res.status}`);
      }
      failures = 0;
      onState?.("open");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
            if (frame.id != null) lastId = frame.id;
            onFrame(frame);
            if (isDone?.(frame)) {
              onState?.("done");
              return;
            }
          }
        }
      } finally {
        reader.cancel().catch(() => {});
      }
    } catch (e) {
      if (signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
    }
    if (signal.aborted) return;
    onState?.("reconnecting");
    const delay = backoffMs[Math.min(failures, backoffMs.length - 1)] ?? 5000;
    failures += 1;
    await sleep(delay, signal);
  }
}
