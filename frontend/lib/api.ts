import { getDemoKey } from "./demoKey";

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

export type SandboxInfo = {
  id: string;
  starter: string;
  starter_label: string;
  /** rules_only: no model calls at all; mock: canned stand-in; live: real models. */
  llm_mode: "rules_only" | "mock" | "live";
  mode_label: string;
  source: string;
  expires_at: number;
  ttl_remaining_s: number;
  application_provided: boolean;
  market_stubs: boolean;
  sku_count: number;
  warnings: string[];
  documents: { name: string; kind: string; title: string; status: "read" | "not_read"; reason: string | null }[];
  skus_without_market_data?: number;
};

export type VendorDetail = {
  sandbox?: SandboxInfo;
  id: string;
  vendor_id: string;
  company_name: string;
  brand_name?: string;
  categories: string[];
  city?: string;
  sku_count: number;
  proposed_terms?: Record<string, unknown>;
};

export type TargetBreakdown = {
  category_pct: number;
  vendor_type_pp: number;
  brand_pp: number;
  lever_pp: number;
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
  /** Present when the backend explains the effective target. */
  target_breakdown?: TargetBreakdown | null;
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

/** One try at a model-extraction claim; attempt 0 is the agent's first answer. Only present once the verifier rejected it. */
export type ClaimAttempt = {
  attempt: number;
  value: number;
  status: ClaimStatus;
  reason?: string | null;
  recomputed?: number | null;
};

export type Claim = {
  id: string;
  text: string;
  value: number;
  metric: string;
  unit: "pct" | "inr" | "units" | "score" | "ratio" | "qty" | "pts";
  sku_key?: string | null;
  status: ClaimStatus;
  recomputed?: number | null;
  reason?: string | null;
  origin: "engine" | "model_extraction" | "vision_extraction" | "injected_test";
  /** Timeline of attempts when the first answer was rejected (self-correction), oldest first. */
  attempts?: ClaimAttempt[];
  source_ref: { file: string; key: string; column?: string | null };
  evidence?: {
    row?: number | null;
    header?: string | null;
    raw_value?: string | null;
    normalized_value?: number | string | null;
    /** vision_extraction: where on which scan the value was read, and the second read of that region. */
    doc?: string | null;
    page?: number | null;
    bbox?: [number, number, number, number] | number[] | null;
    crop_sha256?: string | null;
    reread_value?: string | null;
    as_of?: string | null;
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
  /** Dotted policy path the error is about (playbook 422s). */
  path?: string;
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
        path: typeof inner.path === "string" ? inner.path : undefined,
      };
    }
    if (typeof r.detail === "string") {
      return { code: `http_${status}`, problem: r.detail };
    }
  }
  return { code: `http_${status}`, problem: `Request failed (${status})` };
}

export async function request<T>(
  method: "GET" | "POST" | "PUT",
  path: string,
  opts: { body?: unknown; signal?: AbortSignal; headers?: Record<string, string> } = {},
): Promise<T> {
  const { signal } = opts;
  const headers: Record<string, string> = { ...opts.headers };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const key = getDemoKey();
    if (key) headers["X-Demo-Key"] = key;
  }
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal,
      cache: "no-store",
    });
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
  try {
    return (await res.json()) as T;
  } catch {
    return undefined as T; // empty 200/202 body
  }
}

const get = <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, { signal });
export const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>("POST", path, { body, signal });

export const put = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>("PUT", path, { body, signal });

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

export type UploadStarter = {
  id: string;
  label: string;
  vertical: string;
  vendor_types: Record<string, string>;
  required_documents: string[];
  document_kinds: { kind: string; label: string }[];
  has_sample: boolean;
  has_market_data: boolean;
};

export type UploadOptions = {
  starters: UploadStarter[];
  limits: { sheet_mb: number; rows: number; documents: number; document_mb: number; ttl_hours: number };
  llm_mode: SandboxInfo["llm_mode"];
  mode_label: string;
  live_budget_usd: number;
};

export const fetchUploadOptions = (signal?: AbortSignal) => {
  const key = getDemoKey();
  return request<UploadOptions>("GET", "/api/uploads/options", { signal, headers: key ? { "X-Demo-Key": key } : undefined });
};

/** multipart POST /api/uploads; the browser sets the boundary, so no Content-Type here. */
export async function createUpload(form: FormData, signal?: AbortSignal): Promise<SandboxInfo> {
  const headers: Record<string, string> = {};
  const key = getDemoKey();
  if (key) headers["X-Demo-Key"] = key;
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/uploads`, { method: "POST", body: form, headers, signal, cache: "no-store" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, { code: "unreachable", problem: `Cannot reach the backend at ${BACKEND_URL}`, cause: e instanceof Error ? e.message : undefined, fix: "Run `make dev` from the repo root." });
  }
  let raw: unknown = null;
  try {
    raw = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new ApiError(res.status, parseErrorBody(res.status, raw));
  return raw as SandboxInfo;
}
