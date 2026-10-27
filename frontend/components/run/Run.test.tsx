import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RUN_NAV, overdueText, statusLabel, unverified, weekLabel } from "@/lib/ops";
import { draft, review, tracker, vendorReview } from "../../test-utils/opsFixtures";
import { DraftCard } from "./DraftCard";
import { MisPage } from "./MisPage";
import { CommitmentRow, PoTrackerPage } from "./PoTrackerPage";
import { VendorReviewPage } from "./VendorReviewPage";

afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { path: string; method: string; body: unknown }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`;
    calls.push({ path: key, method: (init?.method ?? "GET").toUpperCase(), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const handler = routes[key];
    return handler ? handler(init) : json({ code: "not_found", problem: `no stub for ${key}` }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

describe("lib/ops helpers", () => {
  it("describes lateness and status", () => {
    expect(overdueText(6)).toBe("6 days overdue");
    expect(overdueText(1)).toBe("1 day overdue");
    expect(overdueText(0)).toBe("due today");
    expect(overdueText(-3)).toBe("due in 3 days");
    expect(statusLabel("due_soon")).toBe("Due soon");
    expect(weekLabel("2026-10-19", "2026-10-25")).toMatch(/19 Oct.*25 Oct/);
    expect(unverified([draft({ figures: [{ claim_id: "a", shown: "1", status: "rejected", reason: null }] })])).toBe(1);
  });
  it("keeps the Run nav extensible: each entry is a plain item with a matcher", () => {
    expect(RUN_NAV.map((n) => n.href)).toEqual(["/run", "/run/pos", "/run/price-requests", "/run/catalog", "/run/promotions", "/run/price-watch"]);
    expect(RUN_NAV[0].match("/run/vendors/E002")).toBe(true);
    expect(RUN_NAV[1].match("/run/pos")).toBe(true);
    expect(RUN_NAV[1].match("/run")).toBe(false);
  });
});

describe("MisPage", () => {
  it("shows the category numbers, ranked actions, scorecard, MIS pack and the queued emails", async () => {
    stub({ "GET /api/ops/review": () => json(review()) });
    render(<MisPage />);
    expect(await screen.findByText("Demand is steady but supply is the problem")).toBeInTheDocument();
    const actions = screen.getByRole("list", { name: "What to do this week" });
    expect(within(actions).getAllByRole("listitem")).toHaveLength(2);
    expect(within(actions).getByText(/agent moved it from #4/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Vendor scorecard" });
    expect(within(table).getByRole("link", { name: "Purrline Foods" })).toHaveAttribute("href", "/run/vendors/E002");
    expect(within(table).getByText("54%")).toHaveClass("text-bad"); // below the 90% floor
    expect(screen.getByTestId("markdown")).toHaveTextContent("₹13,65,809");
    expect(screen.getByRole("article", { name: /Draft Weekly review/ })).toBeInTheDocument();
    expect(screen.getByText(/Replaces about 690 manual minutes \(research estimate\)/)).toBeInTheDocument();
    expect(screen.getByText("3/3 verified")).toBeInTheDocument();
  });

  it("warns when the verifier rejected a number or the commentary has an unclaimed one", async () => {
    stub({ "GET /api/ops/review": () => json(review({ verification: { total: 3, verified: 2, rejected: 1, unverifiable: 0 }, unclaimed_numbers: ["120"] })) });
    render(<MisPage />);
    expect(await screen.findByText("1 number failed verification")).toBeInTheDocument();
    expect(screen.getByText("The commentary states numbers without a claim")).toBeInTheDocument();
  });

  it("asks for the injected-fault run when the toggle is on", async () => {
    const calls = stub({ "GET /api/ops/review": () => json(review()), "GET /api/ops/review?inject=1": () => json(review({ verification: { total: 3, verified: 2, rejected: 1, unverifiable: 0 } })) });
    render(<MisPage />);
    await screen.findByText("Demand is steady but supply is the problem");
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByText("1 number failed verification")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("inject=1"))).toBe(true);
  });

  it("shows the typed backend error", async () => {
    stub({ "GET /api/ops/review": () => json({ code: "ops_data_missing", problem: "The operations data files are missing", cause: "not generated", fix: "Run python3 data/generate_ops.py" }, 500) });
    render(<MisPage />);
    expect(await screen.findByText("The operations data files are missing")).toBeInTheDocument();
    expect(screen.getByText(/generate_ops/)).toBeInTheDocument();
  });
});

describe("PoTrackerPage", () => {
  it("lists POs with status, vendor date, risk and rung, and expands a PO to its lines", async () => {
    stub({ "GET /api/ops/pos": () => json(tracker()) });
    render(<PoTrackerPage />);
    const table = await screen.findByRole("table", { name: "Open purchase orders" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("PO-E003-0010");
    expect(rows[1]).toHaveTextContent("6 days overdue");
    expect(rows[1]).toHaveTextContent("2026-11-03");
    expect(rows[1]).toHaveTextContent("Escalate");
    expect(rows[2]).toHaveTextContent("No date given");
    expect(rows[2]).toHaveTextContent("+1, vague reply");
    fireEvent.click(within(table).getByRole("button", { name: /PO-E003-0010/ }));
    expect(await screen.findByRole("table", { name: "PO lines" })).toHaveTextContent("vendor's verified date");
    expect(screen.getByText("The verifier rejected 1 reading, and the agent corrected it")).toBeInTheDocument();
  });

  it("shows the quote behind every extracted date and how the verifier judged it", async () => {
    stub({ "GET /api/ops/pos": () => json(tracker()) });
    render(<PoTrackerPage />);
    const card = await screen.findByRole("article", { name: "Reply R004" });
    expect(within(card).getAllByText(/approx 5-6 working days from today/).length).toBeGreaterThan(0);
    expect(within(card).getByText("Verified after correction")).toBeInTheDocument();
    expect(within(card).getByText(/first read this as 7 days/)).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Reply R006" })).getByText(/No date or quantity promised/)).toBeInTheDocument();
  });

  it("renders a rejected commitment with the verifier's reason", () => {
    render(<ul><CommitmentRow c={{ kind: "qty", quote: "ship 900 units", eta_date: null, qty: 900, note: null, claim_id: "x", status: "rejected", reason: "the quote states 600; the claim says 900", first_value: null, corrected: false, resolved_eta: null }} /></ul>);
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText(/the quote states 600/)).toBeInTheDocument();
  });

  it("shows the escalation ladder, the ledger and the queued follow-ups", async () => {
    stub({ "GET /api/ops/pos": () => json(tracker()) });
    render(<PoTrackerPage />);
    expect(await screen.findByRole("region", { name: "Escalation ladder" })).toHaveTextContent("Rung 2");
    expect(screen.getByRole("table", { name: "Fill-rate ledger" })).toHaveTextContent("packing");
    expect(screen.getByRole("article", { name: /Draft PO-E003-0010 out of stock/ })).toBeInTheDocument();
  });
});

describe("DraftCard", () => {
  it("approves with the edited text and says nothing was sent", async () => {
    const calls = stub({
      "POST /api/ops/outbox/DR-REVIEW-E002/approve": () => json(draft({ status: "sent_simulated", decided_at: "2026-10-26T10:00:00+00:00", body: "Edited body 54%" })),
    });
    const onChange = vi.fn();
    render(<DraftCard draft={draft()} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Edited body 54%" } });
    fireEvent.click(screen.getByRole("button", { name: /Approve and send \(simulated\)/ }));
    expect(await screen.findByText("Sent (simulated)")).toBeInTheDocument();
    expect(screen.getByText(/No message left this app/)).toBeInTheDocument();
    expect(calls[0].body).toEqual({ body: "Edited body 54%" });
    expect(onChange).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("blocks approval while the message states a rejected number, and unblocks when it is edited out", () => {
    const bad = draft({ body: "Fill rate is 45%.", figures: [{ claim_id: "c", shown: "45%", status: "rejected", reason: "engine recomputed 0.54" }] });
    render(<DraftCard draft={bad} />);
    expect(screen.getByText("This message states a number the verifier rejected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve and send/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Fill rate dropped." } });
    expect(screen.getByRole("button", { name: /Approve and send/ })).toBeEnabled();
  });

  it("rejects a draft and shows a typed error from the backend", async () => {
    stub({ "POST /api/ops/outbox/DR-REVIEW-E002/reject": () => json({ code: "draft_not_pending", problem: "This draft was already decided", cause: "Only drafts waiting for approval can be changed", fix: "Open the outbox" }, 409) });
    render(<DraftCard draft={draft()} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(screen.getByText("This draft was already decided")).toBeInTheDocument());
  });

  it("marks template drafts", () => {
    render(<DraftCard draft={draft({ source: "template" })} />);
    expect(screen.getByText("Template")).toBeInTheDocument();
  });
});

describe("VendorReviewPage", () => {
  it("shows the scorecard, SKU table, email draft and the vendor's POs", async () => {
    stub({ "GET /api/ops/vendors/E002": () => json(vendorReview()) });
    render(<VendorReviewPage vendorId="E002" />);
    expect(await screen.findByRole("heading", { name: "Purrline Foods: weekly review" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "SKU performance" })).toHaveTextContent("Ocean Fish Adult 1.2 kg");
    expect(screen.getByRole("region", { name: "Review email" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Open purchase orders" })).toHaveTextContent("PO-E002-0012");
    expect(screen.getByText("Likely the transporter strike.")).toBeInTheDocument();
  });

  it("reports an unknown vendor from the typed 404", async () => {
    stub({ "GET /api/ops/vendors/E099": () => json({ code: "unknown_ops_vendor", problem: "unknown existing vendor: 'E099'", cause: "not in vendors.json", fix: "Use an id from the Run page" }, 404) });
    render(<VendorReviewPage vendorId="E099" />);
    expect(await screen.findByText("unknown existing vendor: 'E099'")).toBeInTheDocument();
  });
});
