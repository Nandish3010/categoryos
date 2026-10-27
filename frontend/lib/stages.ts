/**
 * Defensive readers for the Negotiate, Catalog, Marketing, JBP and PO stage `data`
 * (shapes: docs/api-contract.md). Backend data is loosely typed, so every field is
 * checked and missing pieces degrade to empty values instead of throwing.
 */
import { BACKEND_URL } from "./api";
import type { Claim } from "./api";
import { readLabelCheck, readScanned, type LabelCheck, type Scanned } from "./docs";
import type { RunSnapshot, StageId, StageResult } from "./runs";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const strArr = (v: unknown): string[] => arr(v).filter((x): x is string => typeof x === "string");

/** Backend-relative asset paths (`/api/assets/...`) become absolute backend URLs. */
export function assetUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  return `${BACKEND_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

// ---- Stage navigation ----

export type ViewId = "screen" | "decide" | "catalog" | "launch";

/** The centre-panel view that renders a given stage. */
export function viewForStage(stage: StageId): ViewId {
  switch (stage) {
    case "intake":
      return "screen";
    case "research":
    case "shortlist":
    case "negotiate":
      return "decide";
    case "catalog":
      return "catalog";
    default:
      return "launch";
  }
}

const ORDER: StageId[] = ["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"];

export function isStageId(v: string | null | undefined): v is StageId {
  return !!v && (ORDER as string[]).includes(v);
}

/**
 * Stage shown when the user has not picked one: the furthest stage that is in
 * `review` or `running`; else the furthest finished stage; else research.
 * A failed Screen (V004) keeps the Decide view, where the lock is explained.
 */
export function defaultStage(run: RunSnapshot | null): StageId {
  if (!run) return "research";
  const at = (statuses: string[]) =>
    [...ORDER].reverse().find((s) => statuses.includes(run.stages[s]?.status ?? ""));
  const active = at(["review", "running"]);
  if (active) return active === "shortlist" ? "research" : active;
  if (run.stages.intake?.status === "failed") return "research";
  const done = at(["done"]);
  if (!done || done === "intake") return "research";
  // An approval just landed and the next phase has not reported yet: show where it will appear.
  const next = ORDER[ORDER.indexOf(done) + 1];
  if (next && run.stages[next]?.status === "pending") return next;
  return done === "shortlist" ? "research" : done;
}

/** Phase-stepper target stage for each phase name. */
export const PHASE_STAGE: Record<string, StageId> = {
  Screen: "intake",
  Decide: "research",
  Execute: "catalog",
  Launch: "marketing",
};

export function phaseOfStage(stage: StageId): string {
  const v = viewForStage(stage);
  return v === "screen" ? "Screen" : v === "decide" ? "Decide" : v === "catalog" ? "Execute" : "Launch";
}

// ---- Footer / approve progress ----

export type ApproveTarget = "research" | "catalog" | "po";
const TARGETS: ApproveTarget[] = ["research", "catalog", "po"];

export type Progress =
  | { kind: "none" }
  | { kind: "locked" }
  | { kind: "review"; stage: ApproveTarget }
  | { kind: "running"; label: string; approved: boolean }
  | { kind: "approved"; label: string };

/** What the sticky footer should say: the stage to approve, or what is running after an approval. */
export function progressOf(run: RunSnapshot | null): Progress {
  if (!run) return { kind: "none" };
  const st = run.stages;
  if (st.intake?.status === "failed" || st.research?.status === "locked") return { kind: "locked" };
  const target = TARGETS.find((t) => st[t]?.status === "review");
  if (target) return { kind: "review", stage: target };
  if (st.po?.status === "done") return { kind: "approved", label: "PO approved" };
  if (st.catalog?.status === "done") return { kind: "running", label: "Drafting launch packet…", approved: true };
  if (st.research?.status === "done") {
    if (st.negotiate?.status !== "done") return { kind: "running", label: "Negotiating…", approved: true };
    return { kind: "running", label: "Building catalog…", approved: true };
  }
  if (Object.values(st).some((s) => s?.status === "running")) {
    return { kind: "running", label: "Agents working…", approved: false };
  }
  return { kind: "none" };
}

/** metrics_hash to send when approving a stage; later stages use the approved research hash. */
export function approvalHash(run: RunSnapshot | null, stage: ApproveTarget, leverHash: string | null): string | null {
  if (stage === "research") return leverHash;
  const s = run?.stages[stage];
  return s?.metrics_hash ?? s?.narrative_hash ?? run?.stages.research?.narrative_hash ?? leverHash;
}

// ---- Negotiate ----

export type GapStatus = "met" | "gap" | "not_stated";
export type GapRow = {
  term: string;
  label: string;
  unit: string;
  direction: string;
  application: number | null;
  offered: number | null;
  required: number | null;
  gap: number | null;
  status: GapStatus;
  turn: number | null;
  quote: string | null;
  claimId: string | null;
  verification: string | null;
};
export type TranscriptTurn = { turn: number; speaker: string; text: string };
export type Refusal = { term: string; quote: string; turn: number | null; note: string; verified: boolean };
export type Commitment = { term: string; offered: number | null; quote: string; turn: number | null; claimId: string | null; status: string };
export type NegotiateData = {
  gaps: GapRow[];
  commitments: Commitment[];
  refusals: Refusal[];
  asks: string[];
  emailDraft: string | null;
  turns: TranscriptTurn[] | null;
  source: "canonical" | "asr";
  similarityPct: number | null;
  negotiatedSkus: string[];
  verification: { total: number; verified: number; rejected: number } | null;
};

export function readNegotiate(stage: StageResult | undefined | null): NegotiateData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  const counter = isObj(d.counter_offer) ? d.counter_offer : {};
  const tr = isObj(d.transcript) ? d.transcript : null;
  const ver = isObj(d.verification) ? d.verification : null;
  return {
    gaps: arr(d.gap_table)
      .filter(isObj)
      .map((g) => {
        const status = str(g.status);
        return {
          term: str(g.term) ?? "",
          label: str(g.label) ?? str(g.term) ?? "term",
          unit: str(g.unit) ?? "",
          direction: str(g.direction) ?? "higher",
          application: num(g.application),
          offered: num(g.offered),
          required: num(g.required),
          gap: num(g.gap),
          status: status === "met" || status === "gap" ? status : "not_stated",
          turn: num(g.turn),
          quote: str(g.quote),
          claimId: str(g.claim_id),
          verification: str(g.verification),
        };
      }),
    commitments: arr(d.commitments)
      .filter(isObj)
      .map((c) => ({
        term: str(c.term) ?? "",
        offered: num(c.offered),
        quote: str(c.transcript_quote) ?? "",
        turn: num(c.turn),
        claimId: str(c.claim_id),
        status: str(c.status) ?? "unverifiable",
      })),
    refusals: arr(d.refusals)
      .filter(isObj)
      .map((r) => ({
        term: str(r.term) ?? "",
        quote: str(r.transcript_quote) ?? "",
        turn: num(r.turn),
        note: str(r.note) ?? "",
        verified: r.quote_verified === true,
      })),
    asks: strArr(counter.asks),
    emailDraft: str(counter.email_draft),
    turns: tr
      ? arr(tr.turns)
          .filter(isObj)
          .map((t, i) => ({ turn: num(t.turn) ?? i + 1, speaker: str(t.speaker) ?? "speaker", text: str(t.text) ?? "" }))
      : null,
    source: d.transcript_source === "asr" ? "asr" : "canonical",
    similarityPct: tr ? num(tr.similarity_pct) : null,
    negotiatedSkus: strArr(d.negotiated_skus),
    verification: ver
      ? { total: num(ver.total) ?? 0, verified: num(ver.verified) ?? 0, rejected: num(ver.rejected) ?? 0 }
      : null,
  };
}

/** Format a gap-table value by its unit (null -> "Not stated"). */
export function termValue(v: number | null, unit: string): string {
  if (v == null) return "Not stated";
  const n = Number.isInteger(v) ? String(v) : v.toFixed(1);
  switch (unit) {
    case "pct":
      return `${n}%`;
    case "days":
      return `${n} days`;
    case "units":
      return `${n} units`;
    case "inr": {
      const whole = Number.isInteger(v);
      const body = whole ? Math.abs(v).toLocaleString("en-IN") : Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return `${v < 0 ? "−" : ""}₹${body}`;
    }
    default:
      return n;
  }
}

/** Signed gap text; positive gaps print with "+". */
export function gapValue(v: number | null, unit: string): string {
  if (v == null) return "—";
  if (v === 0) return "0";
  const body = termValue(Math.abs(v), unit);
  return `${v < 0 ? "−" : "+"}${body}`;
}

// ---- Catalog ----

export type Severity = "high" | "medium" | "low" | string;
export type ComplianceFlag = { rule: string; text: string; severity: Severity; source: string };
export type CatalogSku = {
  code: string;
  name: string;
  verdict: string;
  rawRow: [string, string][];
  rules: { category: string; subcategory: string } | null;
  model: { category: string; subcategory: string; valid: boolean } | null;
  agreement: boolean | null;
  classificationNote: string | null;
  title: string;
  bullets: string[];
  description: string;
  attributes: [string, string][];
  flags: ComplianceFlag[];
  packshot: string | null;
  cutout: string | null;
  cutoutUnavailable: boolean;
  lifestyle: string | null;
  imageSource: string;
  hero: boolean;
  generatedBy: string;
  corrections: number;
  /** The scanned label of this SKU read against the sheet and the listing copy; null when no label was filed. */
  labelCheck: LabelCheck | null;
};
export type CatalogData = {
  skus: CatalogSku[];
  agreementPct: number | null;
  imageMode: string | null;
  heroSkus: string[];
  scanned: Scanned | null;
};

const cell = (v: unknown): string => (v == null ? "" : typeof v === "string" ? v : String(v));
const label = (o: unknown): { category: string; subcategory: string } | null =>
  isObj(o) ? { category: str(o.category) ?? "?", subcategory: str(o.subcategory) ?? "?" } : null;

export function readCatalog(stage: StageResult | undefined | null): CatalogData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  return {
    skus: arr(d.skus)
      .filter(isObj)
      .map((s) => {
        const cls = isObj(s.classification) ? s.classification : {};
        const copy = isObj(s.copy) ? s.copy : {};
        const img = isObj(s.images) ? s.images : {};
        const model = isObj(cls.model) ? cls.model : null;
        const cutout = str(img.cutout);
        return {
          code: str(s.code) ?? "",
          name: str(s.name) ?? "",
          verdict: str(s.verdict) ?? "",
          rawRow: isObj(s.raw_row) ? Object.entries(s.raw_row).map(([k, v]) => [k, cell(v)] as [string, string]) : [],
          rules: label(cls.rules),
          model: model ? { category: str(model.category) ?? "?", subcategory: str(model.subcategory) ?? "?", valid: model.valid !== false } : null,
          agreement: typeof cls.agreement === "boolean" ? cls.agreement : null,
          classificationNote: str(cls.note),
          title: str(copy.title) ?? "",
          bullets: strArr(copy.bullets),
          description: str(copy.description) ?? "",
          attributes: isObj(copy.attributes) ? Object.entries(copy.attributes).map(([k, v]) => [k, cell(v)] as [string, string]) : [],
          flags: arr(copy.compliance_flags)
            .filter(isObj)
            .map((f) => ({
              rule: str(f.rule) ?? "flag",
              text: str(f.text) ?? "",
              severity: str(f.severity) ?? "low",
              source: str(f.source) ?? "rules",
            })),
          packshot: assetUrl(str(img.packshot)),
          cutout: cutout && cutout !== "unavailable" ? assetUrl(cutout) : null,
          cutoutUnavailable: cutout === "unavailable",
          lifestyle: assetUrl(str(img.lifestyle)),
          imageSource: str(img.image_source) ?? "live",
          hero: s.hero === true,
          generatedBy: str(copy.generated_by) ?? "rules",
          corrections: arr(s.corrections).length,
          labelCheck: readLabelCheck(s.label_check),
        };
      }),
    agreementPct: num(d.classifier_agreement_pct),
    imageMode: str(d.image_mode),
    heroSkus: strArr(d.hero_skus),
    scanned: readScanned(d.scanned_documents),
  };
}

/** "Rules: X · Muse Spark Open: Y · agree" line pieces. */
export function classificationText(sku: Pick<CatalogSku, "rules" | "model" | "agreement">): {
  rules: string;
  model: string;
  verdict: "agree" | "disagree" | "rules only";
} {
  const fmt = (l: { category: string; subcategory: string } | null) => (l ? `${l.category} / ${l.subcategory}` : "n/a");
  return {
    rules: fmt(sku.rules),
    model: sku.model && sku.model.valid ? fmt(sku.model) : "n/a",
    verdict: sku.agreement === true ? "agree" : sku.agreement === false ? "disagree" : "rules only",
  };
}

// ---- Launch packet ----

export type MarketingData = {
  campaign: string;
  copy: string;
  brandFundedPct: number | null;
  ourPct: number | null;
  rationale: string;
  image: string | null;
  imageSource: string | null;
  brandFundedMarketingInr: number | null;
};
export function readMarketing(stage: StageResult | undefined | null): MarketingData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  const ask = isObj(d.discount_ask) ? d.discount_ask : {};
  const image = isObj(d.image) ? d.image : {};
  return {
    campaign: str(d.campaign_name) ?? "Launch campaign",
    copy: str(d.copy) ?? "",
    brandFundedPct: num(ask.brand_funded_pct),
    ourPct: num(ask.our_pct),
    rationale: str(ask.rationale) ?? "",
    image: assetUrl(str(image.url)),
    imageSource: str(image.image_source),
    brandFundedMarketingInr: num(d.brand_funded_marketing_inr),
  };
}

export function readJbp(stage: StageResult | undefined | null): { markdown: string } | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  const md = str(d.markdown);
  return md ? { markdown: md } : null;
}

export type PoLine = { code: string; name: string; units: number; unitCost: number; lineTotal: number; costSource: string };
export type TimelineStep = { step: string; status: string; planned: string | null; expected: string | null; delayDays: number; alert: string | null };
export type PoData = {
  poNumber: string;
  date: string | null;
  lines: PoLine[];
  subtotal: number | null;
  gstRate: number | null;
  gst: number | null;
  grandTotal: number | null;
  gstNote: string | null;
  paymentDays: number | null;
  timeline: TimelineStep[];
  alerts: string[];
};
export function readPo(stage: StageResult | undefined | null): PoData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  return {
    poNumber: str(d.po_number) ?? "PO",
    date: str(d.date),
    lines: arr(d.lines)
      .filter(isObj)
      .map((l) => ({
        code: str(l.code) ?? "",
        name: str(l.name) ?? "",
        units: num(l.units) ?? 0,
        unitCost: num(l.unit_cost) ?? 0,
        lineTotal: num(l.line_total) ?? 0,
        costSource: str(l.cost_source) ?? "sheet",
      })),
    subtotal: num(d.subtotal),
    gstRate: num(d.gst_rate),
    gst: num(d.gst),
    grandTotal: num(d.grand_total),
    gstNote: str(d.gst_note),
    paymentDays: num(d.payment_days),
    timeline: arr(d.timeline)
      .filter(isObj)
      .map((t) => ({
        step: str(t.step) ?? "",
        status: str(t.status) ?? "scheduled",
        planned: str(t.planned_date),
        expected: str(t.expected_date),
        delayDays: num(t.delay_days) ?? 0,
        alert: str(t.alert),
      })),
    alerts: strArr(d.alerts),
  };
}

/** Is the PO claim for `metric` (po_total / po_grand_total) verified? */
export function poClaimVerified(claims: Claim[], metric: "po_total" | "po_grand_total"): boolean {
  return claims.some((c) => c.metric === metric && c.status === "verified");
}
