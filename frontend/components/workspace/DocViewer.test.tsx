import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { labelAsDoc, readLabelCheck, readScanned } from "@/lib/docs";
import { labelCheckPayload, scannedPayload } from "../../test-utils/docsFixtures";
import { stage } from "../../test-utils/mockBackend";
import { CatalogStudio } from "./CatalogStudio";
import { DocViewer } from "./DocViewer";
import { ScreenCard } from "./ScreenCard";
import { readScreen } from "@/lib/runs";
import { ClaimRow } from "../ClaimRow";
import type { Claim } from "@/lib/api";

const scanned = readScanned(scannedPayload)!;

describe("DocViewer", () => {
  it("draws the page with a box per reading and lights up the box when a reading is hovered", () => {
    render(<DocViewer documents={scanned.documents} findings={scanned.findings} />);
    const page = screen.getByTestId("doc-page");
    expect(within(page).getByRole("img")).toHaveAttribute("src", expect.stringContaining("/api/docs/V002/fssai_certificate.jpg"));
    const boxes = screen.getAllByTestId("field-box");
    expect(boxes).toHaveLength(2);
    const expiry = boxes.find((b) => b.getAttribute("data-field") === "valid_until")!;
    expect(expiry).toHaveAttribute("data-active", "false");
    expect(expiry.style.left).toBe("40%");
    expect(expiry.style.top).toBe("62%");

    const row = within(screen.getByRole("list", { name: "Readings" })).getByText("30 NOV 2026").closest("button")!;
    fireEvent.mouseEnter(row);
    expect(expiry).toHaveAttribute("data-active", "true");
    expect(screen.getAllByTestId("field-box").find((b) => b.getAttribute("data-field") === "licence_number")).toHaveAttribute("data-active", "false");
    fireEvent.mouseLeave(row);
    expect(expiry).toHaveAttribute("data-active", "false");
  });

  it("highlights the reading's row when its box is hovered or focused", () => {
    render(<DocViewer documents={scanned.documents} findings={scanned.findings} />);
    const box = screen.getAllByTestId("field-box").find((b) => b.getAttribute("data-field") === "licence_number")!;
    fireEvent.focus(box);
    const li = screen.getByRole("list", { name: "Readings" }).querySelector('li[data-field="licence_number"]')!;
    expect(li).toHaveAttribute("data-active", "true");
    fireEvent.blur(box);
    expect(li).toHaveAttribute("data-active", "false");
  });

  it("lists the mismatch as a finding, marks its box and lights the box when the finding is hovered", () => {
    render(<DocViewer documents={scanned.documents} findings={scanned.findings} />);
    const findings = screen.getByRole("list", { name: "Findings" });
    expect(within(findings).getAllByRole("listitem")).toHaveLength(1);  // the match is not a finding to chase
    expect(within(findings).getByText(/reads 2026-11-30; the application says 2027-11-30/)).toBeInTheDocument();
    const expiry = screen.getAllByTestId("field-box").find((b) => b.getAttribute("data-field") === "valid_until")!;
    expect(expiry.className).toContain("border-bad");
    fireEvent.mouseEnter(within(findings).getByRole("button"));
    expect(expiry).toHaveAttribute("data-active", "true");
  });

  it("shows the second read and flags a disagreement", () => {
    const doc = { ...scanned.documents[0], fields: scanned.documents[0].fields.map((f) => (f.name === "valid_until" ? { ...f, status: "rejected" as const, reread: "30 NOV 2027", reason: "the page read says X" } : f)) };
    render(<DocViewer documents={[doc]} />);
    expect(screen.getByText(/Re-read of the crop says “30 NOV 2027”/)).toBeInTheDocument();
    expect(screen.getByLabelText("Rejected: the two reads disagree")).toBeInTheDocument();
    expect(screen.getByText("Re-read of the crop agrees")).toBeInTheDocument(); // the licence number
  });

  it("switches documents with tabs, shows the SAM panel box and a PDF link", () => {
    const lc = readLabelCheck(labelCheckPayload)!;
    const label = labelAsDoc("HP-D01", lc);
    const pdf = { ...scanned.documents[0], file: "price_list.pdf", title: "Supplier price list (PDF)", url: "/api/docs/V001/price_list.pdf", fields: [], panel: null };
    render(<DocViewer documents={[scanned.documents[0], label, pdf]} />);
    expect(screen.queryByTestId("panel-box")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: /Pack label HP-D01/ }));
    expect(screen.getByTestId("panel-box").style.top).toBe("24%");
    expect(screen.getByText(/Dashed box: panel found by/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Supplier price list/ }));
    expect(screen.getByRole("link", { name: /Open PDF/ })).toHaveAttribute("href", expect.stringContaining("price_list.pdf"));
    expect(screen.getByText("Nothing was read from this page.")).toBeInTheDocument();
  });

  it("starts on a given field and renders nothing without documents", () => {
    const lc = readLabelCheck(labelCheckPayload)!;
    render(<DocViewer documents={[labelAsDoc("HP-D01", lc)]} initialField="protein_pct" title="HP-D01 label" />);
    expect(screen.getAllByTestId("field-box").find((b) => b.getAttribute("data-field") === "protein_pct")).toHaveAttribute("data-active", "true");
    const { container } = render(<DocViewer documents={[]} />);
    expect(container.querySelector("[data-testid=doc-viewer]")).toBeNull();
  });
});

describe("ScreenCard with scanned documents", () => {
  const data = (over: Record<string, unknown> = {}) => ({
    decision: "pass",
    reasons: [],
    risk_flags: [{ type: "document_expiring_soon", quote: "FSSAI scan: valid until 2026-11-30", severity: "medium" }],
    followup_questions: [],
    documents: { documents: [{ type: "FSSAI", state: "expiring_soon", declared_status: "valid", source: "scan", valid_until: "2026-11-30", declared_valid_until: "2027-11-30" }] },
    scanned_documents: scannedPayload,
    ...over,
  });

  it("opens by itself when the scan contradicts the application, and says the scan decided", () => {
    render(<ScreenCard screen={readScreen(stage("intake", { data: data() }))!} />);
    const section = screen.getByTestId("scanned-documents");
    expect(within(section).getByText(/Valid until reads 2026-11-30; the application says 2027-11-30/)).toBeInTheDocument();
    expect(within(section).getByText("1 document read · 1 of 1 values verified · 1 mismatch to chase")).toBeInTheDocument();
    expect(within(section).getByText("expiring soon 2026-11-30")).toBeInTheDocument();
    expect(screen.getByText("from scan")).toBeInTheDocument();
    expect(screen.getByText(/declared valid until 2027-11-30/)).toBeInTheDocument();
    expect(within(section).getByText("1 check agrees with the application and the SKU sheet.")).toBeInTheDocument();
  });

  it("opens the viewer on demand", () => {
    render(<ScreenCard screen={readScreen(stage("intake", { data: data() }))!} />);
    expect(screen.queryByTestId("doc-viewer")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show the scans/ }));
    expect(screen.getByTestId("doc-viewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Hide the scans/ }));
    expect(screen.queryByTestId("doc-viewer")).toBeNull();
  });

  it("has no scanned section when the pipeline is off", () => {
    render(<ScreenCard screen={readScreen(stage("intake", { data: data({ scanned_documents: { enabled: false } }) }))!} forceOpen />);
    expect(screen.queryByTestId("scanned-documents")).toBeNull();
  });
});

describe("CatalogStudio label vs sheet", () => {
  const cat = () =>
    stage("catalog", {
      status: "review",
      summary: "1 listings drafted",
      data: {
        classifier_agreement_pct: null,
        scanned_documents: scannedPayload,
        skus: [
          {
            code: "HP-D01", name: "Alpine", verdict: "list", raw_row: { "Ingredients / Claims": "32% protein" },
            classification: { rules: { category: "a", subcategory: "b" }, model: null, agreement: null },
            copy: {
              title: "T", bullets: ["32% protein"], description: "d", attributes: {},
              compliance_flags: [{ rule: "label_mismatch", text: "Protein reads 30%; the SKU sheet says 32%", severity: "high", source: "label" }],
            },
            images: { packshot: "/api/assets/V/HP-D01-packshot.png", cutout: "unavailable", lifestyle: null, image_source: "placeholder" },
            hero: false,
            label_check: labelCheckPayload,
          },
          {
            code: "HP-D05", name: "Puppy", verdict: "list", raw_row: {},
            classification: { rules: { category: "a", subcategory: "b" }, model: null, agreement: null },
            copy: { title: "T2", bullets: [], description: "", attributes: {}, compliance_flags: [] },
            images: { packshot: null, cutout: "unavailable", lifestyle: null, image_source: "placeholder" }, hero: false, label_check: null,
          },
        ],
      },
    });

  it("shows the label next to the sheet and the listing, with the mismatch row marked", () => {
    render(<CatalogStudio stage={cat()} />);
    const block = screen.getByTestId("label-vs-sheet");
    expect(within(block).getByText("1 mismatch")).toBeInTheDocument();
    const protein = block.querySelector("tr[data-field=protein_pct]")!;
    expect(protein).toHaveAttribute("data-status", "mismatch");
    expect(within(protein as HTMLElement).getByText("30%")).toBeInTheDocument();
    expect(within(protein as HTMLElement).getAllByText("32%")).toHaveLength(2); // sheet and listing
    expect(within(protein as HTMLElement).getByText("Mismatch")).toBeInTheDocument();
    expect(block.querySelector("tr[data-field=mrp]")).toHaveAttribute("data-status", "match");
    expect(screen.getByText("from label")).toBeInTheDocument(); // the flag came from the label
    expect(screen.getAllByTestId("label-vs-sheet")).toHaveLength(1); // the SKU without a label has none
    expect(screen.getByTestId("label-summary")).toHaveTextContent("Labels: 1 document read");
  });

  it("opens the viewer on the clicked field", () => {
    render(<CatalogStudio stage={cat()} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Protein on the label" }));
    const viewer = screen.getByTestId("doc-viewer");
    expect(within(viewer).getAllByTestId("field-box").find((b) => b.getAttribute("data-field") === "protein_pct")).toHaveAttribute("data-active", "true");
    expect(within(viewer).getByTestId("panel-box")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide the label" }));
    expect(screen.queryByTestId("doc-viewer")).toBeNull();
  });
});

describe("ClaimRow for a vision claim", () => {
  const claim: Claim = {
    id: "v1", text: "Protein on the label reads 30.0 %", value: 0.3, metric: "doc_value:product_label.protein_pct", unit: "pct",
    status: "verified", origin: "vision_extraction", source_ref: { file: "vendors/V001/docs/label_HP-D01.jpg", key: "p1:protein_pct", column: "protein_pct" },
    evidence: { doc: "label_HP-D01.jpg", page: 1, bbox: [0.6, 0.3, 0.7, 0.34], raw_value: "30.0 %", reread_value: "30.0 %", crop_sha256: "a".repeat(64) },
  };
  it("names the scan and page, says the re-read matched, and reports hover", () => {
    const seen: (string | null)[] = [];
    render(<ul><ClaimRow claim={claim} onHover={(c) => seen.push(c?.id ?? null)} /></ul>);
    expect(screen.getByText("label_HP-D01.jpg · p1 · protein_pct")).toBeInTheDocument();
    expect(screen.getByText(/30\.0% · matches the re-read of the crop/)).toBeInTheDocument();
    expect(screen.getByText("Scan")).toBeInTheDocument();
    const li = screen.getByRole("listitem");
    fireEvent.mouseEnter(li);
    fireEvent.mouseLeave(li);
    fireEvent.focus(li);
    expect(seen).toEqual(["v1", null, "v1"]);
  });
  it("shows both reads when they disagree", () => {
    render(<ul><ClaimRow claim={{ ...claim, status: "rejected", evidence: { ...claim.evidence, reread_value: "32.0 %" }, reason: "the page read says X" }} /></ul>);
    expect(screen.getByText(/Page read “30\.0 %” · Re-read of the crop “32\.0 %”/)).toBeInTheDocument();
  });
});
