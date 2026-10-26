import { vi } from "vitest";
import type { LeverResponse, SkuMetrics } from "@/lib/api";
import type { RunSnapshot, StageId, StageResult, TraceEvent } from "@/lib/runs";

/** In-memory stand-in for the backend endpoints used by the workspace. */

export const LEVER_HASH = "hash-lever-1";

export function sku(code: string, verdict: SkuMetrics["verdict"] = "list"): SkuMetrics {
  return {
    sku_key: `V001:${code}`,
    code,
    name: `Product ${code}`,
    category: "food",
    subcategory: "dry",
    pack: "1kg",
    mrp: 100,
    cost: 60,
    cost_source: "sheet",
    selling_price: 90,
    price_gap_pct: 0,
    demand_score: 0.8,
    overlap: 0.1,
    flags: [],
    target_pct: 30,
    margin_pct: 33,
    est_gmv: 1000,
    verdict,
    reasons: ["margin ok"],
    alloc_units: 10,
    capital_at_risk_inr: 600,
  };
}

export function lever(hash = LEVER_HASH): LeverResponse {
  const skus = [sku("HP-D01"), sku("HP-D02", "negotiate")];
  return {
    vendor_id: "V001",
    target_margin_pct_offset: 0,
    skus,
    summary: {
      counts: { list: 1, negotiate: 1 },
      moq: 200,
      shortlisted: 2,
      capital_at_risk_inr: 1200,
      days_of_cover: 30,
      est_monthly_gmv: 2000,
      moq_flag: false,
    },
    metrics_hash: hash,
    computed_ms: 1,
  };
}

export function stage(id: StageId, over: Partial<StageResult> = {}): StageResult {
  return {
    stage: id,
    status: "done",
    mode: "replay",
    summary: "",
    data: null,
    claims: [],
    metrics_hash: null,
    narrative_hash: null,
    needs_approval: false,
    locked_reason: null,
    error: null,
    ...over,
  };
}

export function snapshot(stages: Partial<Record<StageId, StageResult>>): RunSnapshot {
  return { run_id: "run1", vendor_id: "V001", mode: "replay", created_at: "2026-01-01T00:00:00Z", stages };
}

export const researchData = {
  headline: "Onboard 1 SKU, negotiate 1",
  rationale_per_sku: [
    { code: "HP-D01", verdict: "list", why: "Healthy margin and strong demand" },
    { code: "HP-D02", verdict: "negotiate", why: "Margin short of target" },
  ],
  counter_offer: { terms: ["Cost down 3%", { term: "MOQ", ask: 150, rationale: "x" }], email_draft: "Hi team, counter-offer attached." },
  struck: [{ claim_id: "c1", sku_code: "HP-D01", field: "cost", claimed_value: 412, sheet_value: 421, sentence: "Cost of HP-D01 is Rs 412.", reason: "sheet says 421" }],
};

export function traceEvent(seq: number, over: Partial<TraceEvent> = {}): TraceEvent {
  return {
    seq,
    run_id: "run1",
    t_rel_ms: seq * 100,
    type: "tool_call",
    stage: "research",
    model: null,
    latency_ms: null,
    cost_usd: null,
    payload: { tool: "read_sheet", args: { file: "sku_sheet.csv" } },
    ...over,
  };
}

export const frame = (ev: TraceEvent) => `id: ${ev.seq}\nevent: trace\ndata: ${JSON.stringify(ev)}\n\n`;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export type Call = { method: string; path: string; body: unknown; headers: Record<string, string> };

export type MockOpts = {
  run?: RunSnapshot | null;
  leverHash?: string;
  events?: TraceEvent[];
  approve?: { status: number; body: unknown };
  /** Calls recorded as `${method} ${path}` with parsed JSON body. */
  calls?: Call[];
};

export function mockBackend(opts: MockOpts = {}) {
  const calls = opts.calls ?? [];
  const events = opts.events ?? [traceEvent(1), traceEvent(2, { type: "done", stage: null, payload: null })];
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const path = url.pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = Object.fromEntries(new Headers(init?.headers).entries());
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body, headers });

    if (path === "/api/mode") return json({ mode: "replay", spend_usd: 0, max_spend_usd: 5 });
    if (path === "/api/vendors/V001") return json({ id: "V001", vendor_id: "V001", company_name: "Highland Paws", brand_name: "Highland Paws", categories: [], sku_count: 2 });
    if (path === "/api/vendors/V001/decide/metrics") return json(lever(opts.leverHash));
    if (path === "/api/vendors/V001/claims")
      return json({ total: 0, verified: 0, rejected: 0, unverifiable: 0, claims: [] });
    if (path === "/api/vendors/V001/runs/latest") return json({ run_id: opts.run ? opts.run.run_id : null });
    if (path === "/api/vendors/V001/runs" && method === "POST") return json({ run_id: "run1" }, 202);
    if (path === "/api/runs/run1" && method === "GET")
      return opts.run ? json(opts.run) : json({ code: "not_found", problem: "no run" }, 404);
    if (path === "/api/runs/run1/events") {
      const enc = new TextEncoder();
      return new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(enc.encode(": ping\n\n"));
            for (const e of events) c.enqueue(enc.encode(frame(e)));
            c.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    }
    if (path.endsWith("/approve") && opts.approve) return json(opts.approve.body, opts.approve.status);
    if (path.endsWith("/approve")) return json(stage("research"));
    if (path.endsWith("/override")) return json(stage("research"));
    if (path.endsWith("/decide/replan")) return json(stage("research"));
    if (path.endsWith("/reject")) return json({ ok: true });
    return json({ problem: `unmocked ${method} ${path}` }, 404);
  });
}
