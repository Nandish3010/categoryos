import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UploadOptions } from "@/lib/api";
import { buildSample, buildUpload, checkDraft, emptyForm, type TryDraft } from "@/lib/try";
import { SandboxBanner, ttlText } from "../workspace/SandboxBanner";
import { TryForm } from "./TryPage";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

const starter = (id: string, over = {}) => ({
  id, label: id, vertical: id, vendor_types: { d2c_brand: "D2C brand" }, required_documents: ["GST"],
  document_kinds: [{ kind: "licence_certificate", label: "Licence" }], has_sample: id !== "pet", has_market_data: true, ...over,
});

const options = (mode: UploadOptions["llm_mode"] = "rules_only"): UploadOptions => ({
  starters: [starter("pet"), starter("beauty"), starter("electronics")],
  limits: { sheet_mb: 2, rows: 200, documents: 5, document_mb: 5, ttl_hours: 24 },
  llm_mode: mode,
  mode_label: mode === "rules_only" ? "Rules-only (no model calls)" : "Live models",
  live_budget_usd: 0.5,
});

const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

describe("draft checks and request bodies", () => {
  const draft = (over: Partial<TryDraft> = {}): TryDraft => ({
    starter: "pet", sheet: null, appMode: "none", appFile: null, form: { ...emptyForm }, docs: [], ...over,
  });
  const limits = options().limits;

  it("asks for a sheet", () => {
    expect(checkDraft(draft(), limits)[0]).toMatch(/Choose a SKU sheet/);
  });
  it("catches size, type and count problems before uploading", () => {
    const big = new File([new Uint8Array(3 * 1024 * 1024)], "s.csv");
    expect(checkDraft(draft({ sheet: big }), limits)).toContain("The sheet is over 2 MB.");
    expect(checkDraft(draft({ sheet: new File(["x"], "s.pdf") }), limits).join()).toMatch(/\.csv or \.xlsx/);
    const docs = Array.from({ length: 6 }, (_, i) => ({ file: new File(["x"], `d${i}.png`), kind: "k", declares: "" }));
    expect(checkDraft(draft({ sheet: new File(["x"], "s.csv"), docs }), limits)).toContain("At most 5 documents.");
  });
  it("needs a name when the form is chosen", () => {
    expect(checkDraft(draft({ sheet: new File(["x"], "s.csv"), appMode: "form" }), limits)[0]).toMatch(/company or brand/);
  });
  it("builds multipart bodies, sending only what was filled in", () => {
    const f = buildUpload(
      draft({
        starter: "beauty", sheet: new File(["a"], "s.csv"), appMode: "form",
        form: { ...emptyForm, company_name: " Acme ", moq_units: "100" },
        docs: [{ file: new File(["x"], "c.png"), kind: "licence_certificate", declares: "GST" }],
      }),
    );
    expect(f.get("starter")).toBe("beauty");
    expect(f.get("company_name")).toBe("Acme");
    expect(f.get("moq_units")).toBe("100");
    expect(f.has("brand_name")).toBe(false);
    expect(f.getAll("doc_kinds")).toEqual(["licence_certificate"]);
    expect(f.getAll("doc_declares")).toEqual(["GST"]);
    const s = buildSample("beauty");
    expect(s.get("sample")).toBe("beauty");
  });
});

describe("TryForm", () => {
  it("states the model mode and offers one-click samples", () => {
    render(<TryForm options={options()} />);
    expect(screen.getByText("Rules-only (no model calls)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use the beauty sample/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use the electronics sample/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Use the pet sample/ })).toBeNull();
  });

  it("a sample goes straight to the new vendor", async () => {
    const calls: FormData[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init?: RequestInit) => {
      calls.push(init?.body as FormData);
      return json({ id: "U-abcd1234" }, 201);
    }));
    render(<TryForm options={options()} />);
    fireEvent.click(screen.getByRole("button", { name: /Use the beauty sample/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/vendors/U-abcd1234"));
    expect(calls[0].get("sample")).toBe("beauty");
  });

  it("shows the server's problem, cause and fix when an upload is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "upload_too_large", problem: "The sheet has 300 SKU rows; the limit is 200", cause: "c", fix: "Upload the first batch" }, 413)));
    render(<TryForm options={options()} />);
    fireEvent.change(screen.getByLabelText("SKU sheet"), { target: { files: [new File(["x"], "s.csv")] } });
    fireEvent.click(screen.getByRole("button", { name: /Create vendor/ }));
    expect(await screen.findByText(/limit is 200/)).toBeInTheDocument();
    expect(screen.getByText(/Upload the first batch/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("does not call the server when the draft is invalid", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<TryForm options={options()} />);
    fireEvent.click(screen.getByRole("button", { name: /Create vendor/ }));
    expect(screen.getByText("Fix these before uploading")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("SandboxBanner", () => {
  const info = {
    id: "U-abcd1234", starter: "beauty", starter_label: "Beauty", llm_mode: "rules_only" as const, mode_label: "Rules-only (no model calls)",
    source: "upload", expires_at: 0, ttl_remaining_s: 5400, application_provided: false, market_stubs: true, sku_count: 3,
    warnings: ["1 cell(s) start with = + - or @"], documents: [{ name: "doc1.png", kind: "k", title: "t", status: "not_read" as const, reason: "Rules-only: no model reads scans" }],
    skus_without_market_data: 2,
  };
  it("says what ran the vendor and what was not scored", () => {
    render(<SandboxBanner info={info} vendorId="U-abcd1234" />);
    expect(screen.getByText(/Rules-only \(no model calls\)/)).toBeInTheDocument();
    expect(screen.getByText(/No model was called/)).toBeInTheDocument();
    expect(screen.getByText(/2 SKU\(s\) show/)).toBeInTheDocument();
    expect(screen.getByText(/No application was given/)).toBeInTheDocument();
    expect(screen.getByText(/stored but not read/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download verdicts (CSV)" })).toHaveAttribute("href", expect.stringContaining("/api/vendors/U-abcd1234/export.csv"));
  });
  it("formats the time left", () => {
    expect(ttlText(5400)).toBe("1 h 30 min left");
    expect(ttlText(120)).toBe("2 min left");
    expect(ttlText(0)).toBe("expired");
  });
});
