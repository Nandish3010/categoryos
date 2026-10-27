import {
  ApiError,
  BACKEND_URL,
  post,
  request,
  type Claim,
  type ClaimsResponse,
  type Verdict,
} from "./api";
import { getDemoKey } from "./demoKey";
import { readScanned, type Scanned } from "./docs";

export const STAGE_IDS = [
  "intake",
  "research",
  "shortlist",
  "negotiate",
  "catalog",
  "marketing",
  "jbp",
  "po",
] as const;
export type StageId = (typeof STAGE_IDS)[number];

export type RunStageStatus =
  | "pending"
  | "running"
  | "review"
  | "done"
  | "locked"
  | "failed"
  | "degraded";

export type StageResult = {
  stage: StageId;
  status: RunStageStatus;
  mode: string;
  summary: string;
  data: Record<string, unknown> | null;
  claims: Claim[];
  metrics_hash: string | null;
  narrative_hash: string | null;
  needs_approval: boolean;
  locked_reason: string | null;
  error: string | null;
};

export type RunSnapshot = {
  run_id: string;
  vendor_id: string;
  mode: string;
  created_at: string;
  stages: Partial<Record<StageId, StageResult>>;
};

export type TraceEventType =
  | "stage_started"
  | "tool_call"
  | "model_call"
  | "claim_checked"
  | "stage_result"
  | "degraded"
  | "error"
  | "done";

export type TraceEvent = {
  seq: number;
  run_id: string;
  t_rel_ms: number;
  type: TraceEventType;
  stage: StageId | null;
  model: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  payload: Record<string, unknown> | null;
};

const vid = (id: string) => encodeURIComponent(id);

export const startRun = (vendorId: string) =>
  post<{ run_id: string }>(`/api/vendors/${vid(vendorId)}/runs`, {});
export const fetchLatestRun = (vendorId: string, signal?: AbortSignal) =>
  request<{ run_id: string | null }>("GET", `/api/vendors/${vid(vendorId)}/runs/latest`, { signal });
export const fetchRun = (runId: string, signal?: AbortSignal) =>
  request<RunSnapshot>("GET", `/api/runs/${encodeURIComponent(runId)}`, { signal });
export const approveStage = (runId: string, stage: StageId, metricsHash: string) =>
  post<StageResult>(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/approve`, {
    metrics_hash: metricsHash,
  });
export const overrideSku = (
  runId: string,
  stage: StageId,
  body: { sku_code: string; verdict: Verdict; note?: string },
) => post<StageResult>(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/override`, body);
export const replanVendor = (
  vendorId: string,
  body: { run_id: string; target_margin_pct_offset: number; moq: number },
) => post<StageResult>(`/api/vendors/${vid(vendorId)}/decide/replan`, body);
export const rejectVendor = (vendorId: string, body: { run_id: string; reason: string }) =>
  post<unknown>(`/api/vendors/${vid(vendorId)}/reject`, body);

export const eventsUrl = (runId: string) =>
  `${BACKEND_URL}/api/runs/${encodeURIComponent(runId)}/events`;
export function eventsHeaders(): Record<string, string> {
  const key = getDemoKey();
  return key ? { "X-Demo-Key": key } : {};
}

export function parseTraceEvent(data: string): TraceEvent | null {
  try {
    const raw = JSON.parse(data) as Partial<TraceEvent> | null;
    if (!raw || typeof raw !== "object" || typeof raw.seq !== "number" || !raw.type) return null;
    return {
      seq: raw.seq,
      run_id: raw.run_id ?? "",
      t_rel_ms: raw.t_rel_ms ?? 0,
      type: raw.type,
      stage: raw.stage ?? null,
      model: raw.model ?? null,
      latency_ms: raw.latency_ms ?? null,
      cost_usd: raw.cost_usd ?? null,
      payload: raw.payload ?? null,
    };
  } catch {
    return null;
  }
}

/** True when the endpoint does not exist (older backend): degrade silently. */
export const isMissingEndpoint = (e: unknown) => e instanceof ApiError && e.status === 404;

// ---- Stage output readers (defensive: backend data is loosely typed) ----

const isObj = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export type RiskFlag = { type: string; quote: string; severity: string };
export type ScreenData = {
  risk_flags: RiskFlag[];
  injection_detected: boolean;
  followup_questions: string[];
  decision: string | null;
  reasons: string[];
  documents: ScreenDocument[];
  /** The vision pipeline's reading of the vendor's scans (absent when the playbook turns it off). */
  scanned?: Scanned | null;
};

/** `source` is "scan" when the scanned certificate, not the application, decided the status and date. */
export type ScreenDocument = {
  label: string;
  status: string | null;
  source?: string | null;
  validUntil?: string | null;
  declaredValidUntil?: string | null;
  declaredStatus?: string | null;
};

export function readScreen(stage: StageResult | undefined | null): ScreenData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  return {
    risk_flags: arr(d.risk_flags)
      .filter(isObj)
      .map((f) => ({
        type: str(f.type) ?? "flag",
        quote: str(f.quote) ?? "",
        severity: str(f.severity) ?? "info",
      })),
    injection_detected: d.injection_detected === true,
    followup_questions: arr(d.followup_questions).filter((q): q is string => typeof q === "string"),
    decision: str(d.decision),
    reasons: arr(d.reasons).filter((q): q is string => typeof q === "string"),
    documents: (isObj(d.documents) ? arr(d.documents.documents) : arr(d.documents)).map((x) => {
      if (typeof x === "string") return { label: x, status: null };
      if (isObj(x)) {
        const label = str(x.name) ?? str(x.type) ?? str(x.file) ?? str(x.title) ?? "document";
        const status = str(x.status) ?? str(x.state) ?? (typeof x.present === "boolean" ? (x.present ? "present" : "missing") : null);
        return {
          label,
          status,
          source: str(x.source),
          validUntil: str(x.valid_until),
          declaredValidUntil: str(x.declared_valid_until),
          declaredStatus: str(x.declared_status),
        };
      }
      return { label: String(x), status: null };
    }),
    scanned: readScanned(d.scanned_documents),
  };
}

export type ResearchData = {
  headline: string | null;
  rationale: { code: string; verdict: string | null; why: string }[];
  terms: string[];
  email_draft: string | null;
  struck: { code: string | null; text: string; reason: string }[];
  replanned: boolean;
};

export function termText(t: unknown): string {
  if (typeof t === "string") return t;
  if (isObj(t)) {
    const text = str(t.text) ?? str(t.term) ?? str(t.label) ?? str(t.name);
    if (text && t.ask != null) return `${text}: ask ${String(t.ask)}${t.fallback != null ? ` (fallback ${String(t.fallback)})` : ""}`;
    if (text && t.value != null) return `${text}: ${String(t.value)}`;
    if (text) return text;
  }
  return JSON.stringify(t);
}

export function readResearch(stage: StageResult | undefined | null): ResearchData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  const counter = isObj(d.counter_offer) ? d.counter_offer : {};
  return {
    headline: str(d.headline),
    rationale: arr(d.rationale_per_sku)
      .filter(isObj)
      .map((r) => ({ code: str(r.code) ?? "", verdict: str(r.verdict), why: str(r.why) ?? "" })),
    terms: arr(counter.terms).map(termText),
    email_draft: str(counter.email_draft),
    struck: arr(d.struck)
      .filter(isObj)
      .map((x) => ({
        code: str(x.sku_code) ?? str(x.code),
        text:
          str(x.sentence) ??
          str(x.text) ??
          `${str(x.field) ?? "value"}: claimed ${String(x.claimed_value ?? "?")}, sheet says ${String(x.sheet_value ?? "?")}`,
        reason: str(x.reason) ?? "failed verification",
      })),
    replanned: d.replanned === true,
  };
}

// ---- Derived state ----

const FAIL_RE = /fail|reject|block|deny|denied/i;

/** Screening failure (V004): intake failed or its decision says so. Returns reasons, or null. */
export function screeningFailure(run: RunSnapshot | null): string[] | null {
  const intake = run?.stages.intake;
  if (!intake) return null;
  const screen = readScreen(intake);
  const failed = intake.status === "failed" || (screen?.decision != null && FAIL_RE.test(screen.decision));
  if (!failed) return null;
  const reasons = screen?.reasons.length ? screen.reasons : [intake.error ?? intake.summary].filter(Boolean);
  return reasons.length ? reasons : ["see Screen card"];
}

/** Narrative is stale when its hash no longer matches the lever's metrics hash. */
export function isNarrativeStale(run: RunSnapshot | null, leverHash: string | null | undefined): boolean {
  const h = run?.stages.research?.narrative_hash;
  return !!h && !!leverHash && h !== leverHash;
}

/** First stage waiting on a human, else research. */
export function approvableStage(run: RunSnapshot | null): StageId {
  if (!run) return "research";
  return STAGE_IDS.find((s) => run.stages[s]?.status === "review") ?? "research";
}

export function isRunActive(run: RunSnapshot | null): boolean {
  return !!run && Object.values(run.stages).some((s) => s?.status === "running");
}

/** Merge /claims results with run claims, de-duped by id (run claims win: they are fresher). */
export function mergeClaims(
  base: ClaimsResponse | null,
  run: RunSnapshot | null,
): ClaimsResponse | null {
  const runClaims = run ? Object.values(run.stages).flatMap((s) => s?.claims ?? []) : [];
  if (!base && runClaims.length === 0) return null;
  const byId = new Map<string, Claim>();
  for (const c of base?.claims ?? []) byId.set(c.id, c);
  for (const c of runClaims) byId.set(c.id, c);
  const claims = [...byId.values()];
  const count = (s: Claim["status"]) => claims.filter((c) => c.status === s).length;
  return {
    total: claims.length,
    verified: count("verified"),
    rejected: count("rejected"),
    unverifiable: count("unverifiable"),
    claims,
  };
}
