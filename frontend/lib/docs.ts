/**
 * Defensive readers for the scanned-document results (docs/api-contract.md, `scanned_documents` on the intake and
 * catalog stages, and `label_check` on a catalog SKU). Backend data is loosely typed, so every field is checked and
 * missing pieces degrade to empty values instead of throwing.
 */
import { BACKEND_URL } from "./api";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export type Bbox = [number, number, number, number];

/** A box is drawable only when it lies on the page (fractions 0 to 1, corners in order). */
export function readBbox(v: unknown): Bbox | null {
  if (!Array.isArray(v) || v.length !== 4 || !v.every((x) => typeof x === "number" && Number.isFinite(x))) return null;
  const [x0, y0, x1, y1] = v as number[];
  return x0 >= 0 && y0 >= 0 && x1 <= 1 && y1 <= 1 && x0 < x1 && y0 < y1 ? [x0, y0, x1, y1] : null;
}

/** CSS percentages that place a box over an image of any rendered size. */
export function bboxStyle(b: Bbox): { left: string; top: string; width: string; height: string } {
  const pct = (n: number) => `${Math.round(n * 10000) / 100}%`;
  return { left: pct(b[0]), top: pct(b[1]), width: pct(b[2] - b[0]), height: pct(b[3] - b[1]) };
}

/** Document URLs are backend-relative (`/api/docs/...`). */
export function docUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  return `${BACKEND_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

export type FieldStatus =
  | "verified"
  | "rejected"
  | "unverifiable"
  | "read"
  | "conflict"
  | "low_confidence"
  | "unreadable";

export type ScanField = {
  name: string;
  label: string;
  type: string;
  raw: string;
  value: string;
  reread: string | null;
  page: number;
  bbox: Bbox | null;
  confidence: number | null;
  skuCode: string | null;
  status: FieldStatus;
  reason: string | null;
  claimId: string | null;
};

export type ScanPage = { page: number; file: string; url: string; width: number | null; height: number | null };
export type ScanPanel = { page: number; bbox: Bbox | null; prompt: string; source: string };
export type ScanExpiry = { validUntil: string; days: number; state: "valid" | "expiring_soon" | "expired" };

export type ScanDoc = {
  file: string;
  kind: string;
  label: string;
  title: string;
  declares: string | null;
  skuCode: string | null;
  url: string;
  pages: ScanPage[];
  legible: boolean;
  error: string | null;
  panel: ScanPanel | null;
  expiry: ScanExpiry | null;
  injection: string[];
  fields: ScanField[];
};

export type ScanFinding = {
  id: string;
  check: string;
  label: string;
  severity: string;
  status: "match" | "mismatch" | "unreliable" | "injection";
  doc: string;
  docLabel: string;
  page: number;
  bbox: Bbox | null;
  field: string | null;
  fieldLabel: string | null;
  skuCode: string | null;
  documentValue: string;
  otherLabel: string;
  otherValue: string;
  claimId: string | null;
  claimStatus: string | null;
  message: string;
};

export type ScanSummary = {
  documents: number;
  fields: number;
  claims: number;
  verified: number;
  rejected: number;
  unverifiable: number;
  mismatches: number;
};

export type Scanned = { enabled: boolean; documents: ScanDoc[]; findings: ScanFinding[]; summary: ScanSummary };

const FIELD_STATUS: FieldStatus[] = ["verified", "rejected", "unverifiable", "read", "conflict", "low_confidence", "unreadable"];

export function readField(f: unknown): ScanField | null {
  if (!isObj(f)) return null;
  const name = str(f.name);
  if (!name) return null;
  const status = str(f.status) as FieldStatus;
  return {
    name,
    label: str(f.label) ?? name,
    type: str(f.type) ?? "text",
    raw: str(f.raw) ?? "",
    value: str(f.value) ?? str(f.raw) ?? "",
    reread: str(f.reread),
    page: num(f.page) ?? 1,
    bbox: readBbox(f.bbox),
    confidence: num(f.confidence),
    skuCode: str(f.sku_code),
    status: FIELD_STATUS.includes(status) ? status : "read",
    reason: str(f.reason),
    claimId: str(f.claim_id),
  };
}

function readPanel(v: unknown): ScanPanel | null {
  if (!isObj(v)) return null;
  return { page: num(v.page) ?? 1, bbox: readBbox(v.bbox), prompt: str(v.prompt) ?? "", source: str(v.source) ?? "" };
}

export function readDoc(d: unknown): ScanDoc | null {
  if (!isObj(d)) return null;
  const file = str(d.file);
  if (!file) return null;
  const exp = isObj(d.expiry) ? d.expiry : null;
  const state = exp ? str(exp.state) : null;
  return {
    file,
    kind: str(d.kind) ?? "",
    label: str(d.label) ?? "Document",
    title: str(d.title) ?? str(d.label) ?? file,
    declares: str(d.declares),
    skuCode: str(d.sku_code),
    url: docUrl(str(d.url)) ?? "",
    pages: arr(d.pages)
      .filter(isObj)
      .map((p) => ({
        page: num(p.page) ?? 1,
        file: str(p.file) ?? "",
        url: docUrl(str(p.url)) ?? "",
        width: num(p.width),
        height: num(p.height),
      })),
    legible: d.legible !== false,
    error: str(d.error),
    panel: readPanel(d.panel),
    expiry:
      exp && str(exp.valid_until) && (state === "valid" || state === "expiring_soon" || state === "expired")
        ? { validUntil: str(exp.valid_until) as string, days: num(exp.days) ?? 0, state }
        : null,
    injection: arr(d.injection).filter((x): x is string => typeof x === "string"),
    fields: arr(d.fields).map(readField).filter((f): f is ScanField => f !== null),
  };
}

export function readFinding(f: unknown): ScanFinding | null {
  if (!isObj(f)) return null;
  const status = str(f.status);
  if (status !== "match" && status !== "mismatch" && status !== "unreliable" && status !== "injection") return null;
  return {
    id: str(f.id) ?? `${str(f.check)}:${str(f.doc)}`,
    check: str(f.check) ?? "",
    label: str(f.label) ?? "",
    severity: str(f.severity) ?? "medium",
    status,
    doc: str(f.doc) ?? "",
    docLabel: str(f.doc_label) ?? "",
    page: num(f.page) ?? 1,
    bbox: readBbox(f.bbox),
    field: str(f.field),
    fieldLabel: str(f.field_label),
    skuCode: str(f.sku_code),
    documentValue: str(f.document_value) ?? "",
    otherLabel: str(f.other_label) ?? "",
    otherValue: str(f.other_value) ?? "",
    claimId: str(f.claim_id),
    claimStatus: str(f.claim_status),
    message: str(f.message) ?? "",
  };
}

export function readScanned(v: unknown): Scanned | null {
  if (!isObj(v) || v.enabled !== true) return null;
  const s = isObj(v.summary) ? v.summary : {};
  return {
    enabled: true,
    documents: arr(v.documents).map(readDoc).filter((d): d is ScanDoc => d !== null),
    findings: arr(v.findings).map(readFinding).filter((f): f is ScanFinding => f !== null),
    summary: {
      documents: num(s.documents) ?? 0,
      fields: num(s.fields) ?? 0,
      claims: num(s.claims) ?? 0,
      verified: num(s.verified) ?? 0,
      rejected: num(s.rejected) ?? 0,
      unverifiable: num(s.unverifiable) ?? 0,
      mismatches: num(s.mismatches) ?? 0,
    },
  };
}

/** "3 documents read · 15 of 15 values verified · 1 mismatch to chase". */
export function scannedSummary(s: Scanned): string {
  const { documents, claims, verified, mismatches } = s.summary;
  const parts = [`${documents} document${documents === 1 ? "" : "s"} read`];
  if (claims) parts.push(`${verified} of ${claims} values verified`);
  parts.push(mismatches ? `${mismatches} mismatch${mismatches === 1 ? "" : "es"} to chase` : "no mismatches");
  return parts.join(" · ");
}

/** Findings that need a human; matches are the quiet majority. */
export const isProblem = (f: ScanFinding) => f.status !== "match";

// ---- Catalog: label vs sheet ----

export type LabelSide = { value: string; status: "match" | "mismatch"; check: string };
export type LabelRow = {
  field: string;
  label: string;
  labelValue: string;
  sheet: LabelSide | null;
  listing: LabelSide | null;
  status: "match" | "mismatch";
  severity: string;
  unreliable: boolean;
  claimId: string | null;
  claimStatus: string | null;
  page: number;
  bbox: Bbox | null;
};
export type LabelCheck = {
  doc: string;
  title: string;
  url: string;
  pages: ScanPage[];
  panel: ScanPanel | null;
  error: string | null;
  rows: LabelRow[];
  fields: ScanField[];
};

function readSide(v: unknown): LabelSide | null {
  if (!isObj(v)) return null;
  const status = str(v.status) === "mismatch" ? "mismatch" : "match";
  return { value: str(v.value) ?? "", status, check: str(v.check) ?? "" };
}

export function readLabelCheck(v: unknown): LabelCheck | null {
  if (!isObj(v)) return null;
  return {
    doc: str(v.doc) ?? "",
    title: str(v.title) ?? "Label",
    url: docUrl(str(v.url)) ?? "",
    pages: arr(v.pages)
      .filter(isObj)
      .map((p) => ({ page: num(p.page) ?? 1, file: str(p.file) ?? "", url: docUrl(str(p.url)) ?? "", width: num(p.width), height: num(p.height) })),
    panel: readPanel(v.panel),
    error: str(v.error),
    rows: arr(v.rows)
      .filter(isObj)
      .map((r) => ({
        field: str(r.field) ?? "",
        label: str(r.label) ?? str(r.field) ?? "",
        labelValue: str(r.label_value) ?? "",
        sheet: readSide(r.sheet),
        listing: readSide(r.listing),
        status: str(r.status) === "mismatch" ? ("mismatch" as const) : ("match" as const),
        severity: str(r.severity) ?? "medium",
        unreliable: r.unreliable === true,
        claimId: str(r.claim_id),
        claimStatus: str(r.claim_status),
        page: num(r.page) ?? 1,
        bbox: readBbox(r.bbox),
      })),
    fields: arr(v.fields).map(readField).filter((f): f is ScanField => f !== null),
  };
}

/** A label check as a one-document scan, so the same viewer shows it. */
export function labelAsDoc(sku: string, lc: LabelCheck): ScanDoc {
  return {
    file: lc.doc,
    kind: "product_label",
    label: "Product label",
    title: lc.title,
    declares: null,
    skuCode: sku,
    url: lc.url,
    pages: lc.pages,
    legible: !lc.error,
    error: lc.error,
    panel: lc.panel,
    expiry: null,
    injection: [],
    fields: lc.fields,
  };
}
