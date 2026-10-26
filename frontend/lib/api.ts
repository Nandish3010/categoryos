export const BACKEND_URL = (
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8001"
).replace(/\/$/, "");

export type Verdict = "list" | "negotiate" | "reject" | "needs_data";
export type CostSource = "sheet" | "inferred" | "missing";

export type DecideSummary = {
  counts: Partial<Record<Verdict, number>>;
  moq: number;
  shortlisted: number;
  capital_at_risk_inr: number;
  days_of_cover: number | null;
  est_monthly_gmv: number;
  moq_flag: boolean;
};

export type VendorListItem = {
  id: string;
  brand: string;
  company_name: string;
  categories: string[];
  proposed_terms: Record<string, unknown>;
  sku_count: number;
  summary: DecideSummary;
  metrics_hash: string;
};

export type VendorDetail = {
  id: string;
  vendor_id: string;
  company_name: string;
  brand_name?: string;
  categories: string[];
  city?: string;
  sku_count: number;
  proposed_terms?: Record<string, unknown>;
};

export type SkuMetrics = {
  sku_key: string;
  code: string;
  name: string;
  category: string;
  subcategory: string;
  pack: string | null;
  mrp: number | null;
  cost: number | null;
  cost_source: CostSource;
  selling_price: number | null;
  price_gap_pct: number | null;
  demand_score: number;
  overlap: number;
  flags: string[];
  target_pct: number;
  margin_pct: number | null;
  est_gmv: number;
  verdict: Verdict;
  reasons: string[];
  alloc_units: number;
  capital_at_risk_inr: number;
};

export type LeverResponse = {
  vendor_id: string;
  target_margin_pct_offset: number;
  skus: SkuMetrics[];
  summary: DecideSummary;
  metrics_hash: string;
  computed_ms: number;
};

export type ClaimStatus = "pending" | "verified" | "rejected" | "unverifiable";

export type Claim = {
  id: string;
  text: string;
  value: number;
  metric: string;
  unit: "pct" | "inr" | "units" | "score";
  sku_key?: string | null;
  status: ClaimStatus;
  recomputed?: number | null;
  reason?: string | null;
  origin: "engine" | "model_extraction" | "injected_test";
  source_ref: { file: string; key: string; column?: string | null };
  evidence?: {
    row?: number | null;
    header?: string | null;
    raw_value?: string | null;
    normalized_value?: number | string | null;
  } | null;
};

export type ClaimsResponse = {
  total: number;
  verified: number;
  rejected: number;
  unverifiable: number;
  claims: Claim[];
};

export type ModeResponse = {
  mode: string;
  live_stages?: string[];
  spend_usd: number;
  max_spend_usd: number;
  warn_spend_usd?: number;
};

export type ApiErrorBody = {
  code: string;
  problem: string;
  cause?: string;
  fix?: string;
};

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.problem);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
  /** True when the server could not be reached at all. */
  get unreachable() {
    return this.status === 0;
  }
}

/** Accepts `{code, problem, cause, fix}`, FastAPI `{detail}` or anything else. */
export function parseErrorBody(status: number, raw: unknown): ApiErrorBody {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const inner =
      r.detail && typeof r.detail === "object" ? (r.detail as Record<string, unknown>) : r;
    if (typeof inner.problem === "string") {
      return {
        code: typeof inner.code === "string" ? inner.code : `http_${status}`,
        problem: inner.problem,
        cause: typeof inner.cause === "string" ? inner.cause : undefined,
        fix: typeof inner.fix === "string" ? inner.fix : undefined,
      };
    }
    if (typeof r.detail === "string") {
      return { code: `http_${status}`, problem: r.detail };
    }
  }
  return { code: `http_${status}`, problem: `Request failed (${status})` };
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, { signal, cache: "no-store" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, {
      code: "unreachable",
      problem: `Cannot reach the backend at ${BACKEND_URL}`,
      cause: e instanceof Error ? e.message : undefined,
      fix: "Run `make dev` from the repo root.",
    });
  }
  if (!res.ok) {
    let raw: unknown = null;
    try {
      raw = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, parseErrorBody(res.status, raw));
  }
  return (await res.json()) as T;
}

export const fetchVendors = (signal?: AbortSignal) => get<VendorListItem[]>("/api/vendors", signal);

export const fetchVendor = (id: string, signal?: AbortSignal) =>
  get<VendorDetail>(`/api/vendors/${encodeURIComponent(id)}`, signal);

export const fetchLever = (
  id: string,
  offset: number,
  moq: number | null,
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams({ target_margin_pct_offset: String(offset) });
  if (moq != null) q.set("moq", String(moq));
  return get<LeverResponse>(`/api/vendors/${encodeURIComponent(id)}/decide/metrics?${q}`, signal);
};

export const fetchClaims = (id: string, inject: boolean, signal?: AbortSignal) =>
  get<ClaimsResponse>(
    `/api/vendors/${encodeURIComponent(id)}/claims${inject ? "?inject=1" : ""}`,
    signal,
  );

export const fetchMode = (signal?: AbortSignal) => get<ModeResponse>("/api/mode", signal);
