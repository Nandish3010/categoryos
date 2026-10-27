/** Backend-shaped `scanned_documents` and `label_check` payloads (docs/api-contract.md). */

const field = (over: Record<string, unknown>) => ({
  name: "valid_until",
  label: "Valid until",
  type: "date",
  raw: "30 NOV 2026",
  value: "2026-11-30",
  reread: "30 NOV 2026",
  page: 1,
  bbox: [0.4, 0.62, 0.62, 0.67],
  confidence: 0.97,
  sku_code: null,
  status: "verified",
  reason: null,
  claim_id: "V002:fssai_certificate:p1:valid_until:-:vision",
  ...over,
});

export const certificateDoc = {
  file: "fssai_certificate.jpg",
  kind: "licence_certificate",
  label: "Licence certificate",
  title: "FSSAI licence certificate (scan)",
  declares: "FSSAI",
  sku_code: null,
  url: "/api/docs/V002/fssai_certificate.jpg",
  pages: [{ page: 1, file: "fssai_certificate.jpg", url: "/api/docs/V002/fssai_certificate.jpg", width: 840, height: 1180 }],
  legible: true,
  error: null,
  notes: "",
  mode: "mock",
  panel: null,
  expiry: { valid_until: "2026-11-30", days: 34, state: "expiring_soon", as_of: "2026-10-27" },
  injection: [],
  fields: [
    field({ name: "licence_number", label: "Licence number", type: "text", raw: "FSSAI-DEMO-0002", value: "FSSAI-DEMO-0002", reread: "FSSAI-DEMO-0002", bbox: [0.4, 0.26, 0.68, 0.3], claim_id: null }),
    field({}),
  ],
};

export const expiryFinding = {
  id: "certificate_expiry_vs_application:fssai_certificate.jpg:-",
  check: "certificate_expiry_vs_application",
  label: "Valid-until date on the scan vs the application",
  severity: "high",
  status: "mismatch",
  doc: "fssai_certificate.jpg",
  doc_label: "FSSAI licence certificate (scan)",
  page: 1,
  bbox: [0.4, 0.62, 0.62, 0.67],
  field: "valid_until",
  field_label: "Valid until",
  sku_code: null,
  document_value: "2026-11-30",
  other_label: "application",
  other_value: "2027-11-30",
  other_source: {},
  claim_id: "V002:fssai_certificate:p1:valid_until:-:vision",
  claim_status: "verified",
  message: "FSSAI licence certificate (scan): Valid until reads 2026-11-30; the application says 2027-11-30",
};

export const matchFinding = {
  ...expiryFinding,
  id: "certificate_number_vs_application:fssai_certificate.jpg:-",
  check: "certificate_number_vs_application",
  status: "match",
  field: "licence_number",
  message: "FSSAI licence certificate (scan): Licence number FSSAI-DEMO-0002 matches the application",
};

export const scannedPayload = {
  enabled: true,
  documents: [certificateDoc],
  findings: [matchFinding, expiryFinding],
  summary: { documents: 1, fields: 2, claims: 1, verified: 1, rejected: 0, unverifiable: 0, mismatches: 1 },
};

export const labelCheckPayload = {
  doc: "label_HP-D01.jpg",
  title: "Pack label HP-D01 (photo)",
  url: "/api/docs/V001/label_HP-D01.jpg",
  pages: [{ page: 1, file: "label_HP-D01.jpg", url: "/api/docs/V001/label_HP-D01.jpg", width: 760, height: 1100 }],
  panel: { page: 1, bbox: [0.02, 0.24, 0.97, 0.92], prompt: "the nutrition panel", source: "sam-3.1 (mock fixture)", crop_sha256: null },
  error: null,
  rows: [
    {
      field: "protein_pct", label: "Protein", label_value: "30%", status: "mismatch", severity: "high", unreliable: false,
      sheet: { value: "32%", status: "mismatch", source: {}, check: "label_protein_vs_sheet" },
      listing: { value: "32%", status: "mismatch", source: {}, check: "label_protein_vs_listing" },
      claim_id: "c1", claim_status: "verified", page: 1, bbox: [0.62, 0.31, 0.72, 0.34], doc: "label_HP-D01.jpg",
    },
    {
      field: "mrp", label: "MRP", label_value: "₹1,499.00", status: "match", severity: "medium", unreliable: false,
      sheet: { value: "₹1,499.00", status: "match", source: {}, check: "label_mrp_vs_sheet" }, listing: null,
      claim_id: "c2", claim_status: "verified", page: 1, bbox: [0.3, 0.78, 0.43, 0.81], doc: "label_HP-D01.jpg",
    },
  ],
  fields: [
    field({ name: "protein_pct", label: "Protein", type: "pct", raw: "30.0 %", value: "30%", reread: "30.0 %", bbox: [0.62, 0.31, 0.72, 0.34], sku_code: "HP-D01", claim_id: "c1" }),
    field({ name: "mrp", label: "MRP", type: "inr", raw: "Rs. 1,499", value: "₹1,499.00", reread: "Rs. 1,499", bbox: [0.3, 0.78, 0.43, 0.81], sku_code: "HP-D01", claim_id: "c2" }),
  ],
};
