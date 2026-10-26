import type { TraceEvent } from "./runs";

export function relTime(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function clip(s: string, n = 80): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function argsSummary(args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return clip(args);
  try {
    return clip(JSON.stringify(args));
  } catch {
    return "";
  }
}

export function describeEvent(ev: TraceEvent): { title: string; detail: string } {
  const p = ev.payload ?? {};
  const stage = ev.stage ? `${ev.stage}` : "run";
  switch (ev.type) {
    case "stage_started":
      return { title: `${stage} started`, detail: "" };
    case "tool_call": {
      const tool = String(p.tool ?? p.name ?? "tool");
      return { title: `${stage} · ${tool}`, detail: argsSummary(p.args ?? p.arguments ?? p.input) };
    }
    case "model_call":
      return { title: `${stage} · model call`, detail: typeof p.purpose === "string" ? clip(p.purpose) : "" };
    case "claim_checked": {
      const status = typeof p.status === "string" ? p.status : "checked";
      const text = typeof p.text === "string" ? p.text : typeof p.claim_id === "string" ? p.claim_id : "";
      return { title: `${stage} · claim ${status}`, detail: clip(text) };
    }
    case "stage_result":
      return { title: `${stage} · ${typeof p.status === "string" ? p.status : "result"}`, detail: typeof p.summary === "string" ? clip(p.summary) : "" };
    case "degraded":
      return { title: `${stage} · degraded`, detail: typeof p.reason === "string" ? clip(p.reason) : typeof p.message === "string" ? clip(p.message) : "" };
    case "error":
      return { title: `${stage} · error`, detail: typeof p.message === "string" ? clip(p.message) : typeof p.error === "string" ? clip(p.error) : "" };
    case "done":
      return { title: "Run complete", detail: "" };
    default:
      return { title: String(ev.type), detail: "" };
  }
}

export function eventMeta(ev: TraceEvent): string {
  const parts: string[] = [];
  if (ev.model) parts.push(ev.model);
  if (ev.latency_ms != null) parts.push(`${Math.round(ev.latency_ms)}ms`);
  if (ev.cost_usd != null) parts.push(`$${ev.cost_usd.toFixed(4)}`);
  return parts.join(" · ");
}
