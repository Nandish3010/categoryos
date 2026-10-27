import { describe, expect, it } from "vitest";
import { certificateDoc, labelCheckPayload, scannedPayload } from "../test-utils/docsFixtures";
import { stage } from "../test-utils/mockBackend";
import {
  bboxStyle,
  docUrl,
  isProblem,
  labelAsDoc,
  readBbox,
  readLabelCheck,
  readScanned,
  scannedSummary,
} from "./docs";
import { readScreen } from "./runs";
import { hasScanAlert, screenDefaultOpen, screenSummary } from "./screen";
import { readCatalog } from "./stages";

describe("readBbox / bboxStyle", () => {
  it("accepts only boxes that lie on the page, corners in order", () => {
    expect(readBbox([0.1, 0.2, 0.5, 0.6])).toEqual([0.1, 0.2, 0.5, 0.6]);
    for (const bad of [[0.5, 0.2, 0.1, 0.6], [0.1, 0.2, 1.2, 0.6], [0.1, 0.2, 0.5], null, "x", [0, 0, "a", 1], [-0.1, 0, 0.5, 0.5]]) {
      expect(readBbox(bad)).toBeNull();
    }
  });
  it("places a box with percentages so it scales with the image", () => {
    expect(bboxStyle([0.1, 0.25, 0.35, 0.5])).toEqual({ left: "10%", top: "25%", width: "25%", height: "25%" });
  });
});

describe("docUrl", () => {
  it("makes backend-relative paths absolute and leaves full URLs alone", () => {
    expect(docUrl("/api/docs/V001/a.jpg")).toMatch(/^https?:\/\/.+\/api\/docs\/V001\/a\.jpg$/);
    expect(docUrl("https://x.test/a.jpg")).toBe("https://x.test/a.jpg");
    expect(docUrl(null)).toBeNull();
  });
});

describe("readScanned", () => {
  it("reads documents, findings and the summary", () => {
    const s = readScanned(scannedPayload);
    expect(s?.documents).toHaveLength(1);
    const d = s!.documents[0];
    expect(d.title).toBe("FSSAI licence certificate (scan)");
    expect(d.expiry).toEqual({ validUntil: "2026-11-30", days: 34, state: "expiring_soon" });
    expect(d.fields.find((f) => f.name === "valid_until")).toMatchObject({ status: "verified", reread: "30 NOV 2026", bbox: [0.4, 0.62, 0.62, 0.67] });
    expect(s!.findings.filter(isProblem).map((f) => f.check)).toEqual(["certificate_expiry_vs_application"]);
    expect(scannedSummary(s!)).toBe("1 document read · 1 of 1 values verified · 1 mismatch to chase");
  });
  it("is null when the playbook turned documents off, and tolerates junk", () => {
    expect(readScanned({ enabled: false })).toBeNull();
    expect(readScanned(null)).toBeNull();
    const s = readScanned({ enabled: true, documents: [null, { nope: 1 }, { ...certificateDoc, fields: [null, { name: "x", bbox: [2, 2, 3, 3], status: "weird" }] }], findings: [{ status: "??" }] });
    expect(s!.documents).toHaveLength(1);
    expect(s!.documents[0].fields).toHaveLength(1);
    expect(s!.documents[0].fields[0]).toMatchObject({ bbox: null, status: "read" });
    expect(s!.findings).toEqual([]);
  });
  it("says there are no mismatches when everything agrees", () => {
    const s = readScanned({ ...scannedPayload, findings: [], summary: { ...scannedPayload.summary, mismatches: 0, documents: 3, claims: 5, verified: 5 } });
    expect(scannedSummary(s!)).toBe("3 documents read · 5 of 5 values verified · no mismatches");
  });
});

describe("readLabelCheck", () => {
  it("reads rows next to the sheet and the listing", () => {
    const lc = readLabelCheck(labelCheckPayload);
    expect(lc?.rows[0]).toMatchObject({ field: "protein_pct", labelValue: "30%", status: "mismatch", sheet: { value: "32%", status: "mismatch" }, listing: { value: "32%" } });
    expect(lc?.rows[1]).toMatchObject({ status: "match", listing: null });
    expect(lc?.panel?.bbox).toEqual([0.02, 0.24, 0.97, 0.92]);
    expect(labelAsDoc("HP-D01", lc!)).toMatchObject({ kind: "product_label", skuCode: "HP-D01", legible: true });
  });
  it("is null for a SKU without a label", () => {
    expect(readLabelCheck(null)).toBeNull();
    expect(readCatalog(stage("catalog", { data: { skus: [{ code: "X", name: "X" }] } }))!.skus[0].labelCheck).toBeNull();
  });
});

describe("readCatalog / readScreen carry the scans", () => {
  it("puts label_check on the SKU and the scan on the stage", () => {
    const c = readCatalog(stage("catalog", { data: { skus: [{ code: "HP-D01", name: "A", label_check: labelCheckPayload }], scanned_documents: scannedPayload } }));
    expect(c!.skus[0].labelCheck?.rows).toHaveLength(2);
    expect(c!.scanned?.summary.mismatches).toBe(1);
  });
  it("reads the scan and the from-scan document status on the screen stage", () => {
    const s = readScreen(
      stage("intake", {
        data: {
          decision: "pass",
          documents: { documents: [{ type: "FSSAI", state: "expiring_soon", source: "scan", valid_until: "2026-11-30", declared_valid_until: "2027-11-30", declared_status: "valid" }] },
          scanned_documents: scannedPayload,
        },
      }),
    )!;
    expect(s.documents[0]).toMatchObject({ label: "FSSAI", status: "expiring_soon", source: "scan", declaredValidUntil: "2027-11-30", validUntil: "2026-11-30" });
    expect(s.scanned?.documents).toHaveLength(1);
    // a pass that the scan contradicts still opens, and the summary says why
    expect(hasScanAlert(s)).toBe(true);
    expect(screenDefaultOpen(s)).toBe(true);
    expect(screenSummary(s)).toContain("1 scan mismatch");
    expect(screenSummary(s)).toContain("0 of 1 documents OK");
  });
  it("stays collapsed when the scans agree", () => {
    const s = readScreen(stage("intake", { data: { decision: "pass", documents: [], scanned_documents: { ...scannedPayload, findings: [], summary: { ...scannedPayload.summary, mismatches: 0 } } } }))!;
    expect(hasScanAlert(s)).toBe(false);
    expect(screenDefaultOpen(s)).toBe(false);
  });
});
