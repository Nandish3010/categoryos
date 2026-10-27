import type { UploadOptions } from "./api";

export type AppMode = "none" | "form" | "file";

export type TryDraft = {
  starter: string;
  sheet: File | null;
  appMode: AppMode;
  appFile: File | null;
  form: {
    company_name: string;
    brand_name: string;
    vendor_type: string;
    categories: string;
    margin_offered_pct: string;
    payment_terms_days: string;
    moq_units: string;
    marketing_support_inr: string;
    launch_discount_pct: string;
    returns_policy: string;
  };
  docs: { file: File; kind: string; declares: string }[];
};

export const emptyForm: TryDraft["form"] = {
  company_name: "",
  brand_name: "",
  vendor_type: "",
  categories: "",
  margin_offered_pct: "",
  payment_terms_days: "",
  moq_units: "",
  marketing_support_inr: "",
  launch_discount_pct: "",
  returns_policy: "",
};

const MB = 1024 * 1024;

/** Mirrors the server's limits so people hear about a problem before uploading. The server stays the authority. */
export function checkDraft(d: TryDraft, limits: UploadOptions["limits"]): string[] {
  const out: string[] = [];
  if (!d.sheet) out.push("Choose a SKU sheet (CSV or XLSX), or use a sample.");
  else {
    if (d.sheet.size > limits.sheet_mb * MB) out.push(`The sheet is over ${limits.sheet_mb} MB.`);
    if (!/\.(csv|xlsx)$/i.test(d.sheet.name)) out.push("The sheet should be a .csv or .xlsx file.");
  }
  if (d.appMode === "form" && !(d.form.company_name.trim() || d.form.brand_name.trim())) {
    out.push("The application form needs a company or brand name.");
  }
  if (d.appMode === "file" && !d.appFile) out.push("Choose the application JSON file, or switch the application to none.");
  if (d.docs.length > limits.documents) out.push(`At most ${limits.documents} documents.`);
  for (const doc of d.docs) {
    if (doc.file.size > limits.document_mb * MB) out.push(`${doc.file.name} is over ${limits.document_mb} MB.`);
    if (!doc.kind) out.push(`Say what ${doc.file.name} is.`);
  }
  return out;
}

/** The multipart body for POST /api/uploads. File names are sent as the browser has them; the server ignores them. */
export function buildUpload(d: TryDraft): FormData {
  const f = new FormData();
  f.set("starter", d.starter);
  if (d.sheet) f.set("sheet", d.sheet);
  if (d.appMode === "file" && d.appFile) f.set("application", d.appFile);
  if (d.appMode === "form") {
    for (const [k, v] of Object.entries(d.form)) if (v.trim()) f.set(k, v.trim());
  }
  for (const doc of d.docs) {
    f.append("documents", doc.file);
    f.append("doc_kinds", doc.kind);
    f.append("doc_declares", doc.declares);
  }
  return f;
}

export function buildSample(name: string): FormData {
  const f = new FormData();
  f.set("sample", name);
  f.set("starter", name);
  return f;
}
