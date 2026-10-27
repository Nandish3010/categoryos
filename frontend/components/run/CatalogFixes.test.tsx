import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { counterText, diffChanges, filterRows, selectable } from "@/lib/catalog";
import { RUN_NAV } from "@/lib/ops";
import { copyFix, priceFix, queue, summary } from "../../test-utils/catalogFixtures";
import { CatalogFixesPage } from "./CatalogFixesPage";

afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const key = `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`;
      calls.push({ path: key, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const handler = routes[key];
      return handler ? handler(init) : json({ code: "not_found", problem: `no stub for ${key}`, cause: "", fix: "" }, 404);
    }),
  );
  return calls;
}

describe("lib/catalog helpers", () => {
  it("adds the Catalog fixes entry to the Run navigation", () => {
    const entry = RUN_NAV.find((n) => n.href === "/run/catalog");
    expect(entry?.match("/run/catalog")).toBe(true);
    expect(RUN_NAV[0].match("/run/catalog")).toBe(false);
  });
  it("words the counter from the impact baseline", () => {
    expect(counterText(summary())).toBe("2 fixes ready · est. 24 minutes saved");
    expect(counterText(summary({ fixes_ready: 1, minutes_saved: 12 }))).toBe("1 fix ready · est. 12 minutes saved");
  });
  it("filters the queue by issue type and vendor", () => {
    const q = queue();
    expect(filterRows(q.rows, "mrp_mismatch", "all")).toHaveLength(1);
    expect(filterRows(q.rows, "all", "E002").map((r) => r.listing_id)).toEqual(["L-PL-05"]);
    expect(filterRows(q.rows, "banned_claim", "E002")).toHaveLength(0);
  });
  it("selects only pending, verified fixes and respects the bulk limit", () => {
    const q = queue();
    expect(selectable(q.rows, q.fixes, 25)).toEqual(["fix:L-BK-02:price", "fix:L-BK-01:copy"]);
    expect(selectable(q.rows, q.fixes, 1)).toEqual(["fix:L-BK-02:price"]);
    const fixes = { ...q.fixes, "fix:L-BK-02:price": priceFix({ decision: "approved" }), "fix:L-BK-01:copy": copyFix({ status: "blocked", decision: "blocked" }) };
    expect(selectable(q.rows, fixes, 25)).toEqual([]);
  });
  it("merges the changes of live fixes only", () => {
    expect(diffChanges([priceFix(), priceFix({ decision: "rejected", changes: [] })]).map((c) => c.field)).toEqual(["mrp"]);
    expect(diffChanges([copyFix({ status: "blocked", decision: "blocked" })])).toEqual([]);
  });
});

describe("CatalogFixesPage", () => {
  it("shows the counter, the queue, the before/after diff and claim chips", async () => {
    stub({ "GET /api/ops/catalog": () => json(queue()) });
    render(<CatalogFixesPage />);
    expect(await screen.findByTestId("counter")).toHaveTextContent("2 fixes ready · est. 24 minutes saved");
    const table = screen.getByRole("table", { name: "Fix queue" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    const card = screen.getByRole("article", { name: "Listing L-BK-02" });
    expect(within(card).getByText("1050")).toBeInTheDocument();
    expect(within(card).getByText("1100")).toBeInTheDocument();
    expect(within(card).getByText(/BK-02 MRP is ₹1,100 on the latest price list · verified/)).toBeInTheDocument();
    expect(screen.getByText(/This needs a person/)).toBeInTheDocument();
  });

  it("filters by issue type and vendor", async () => {
    stub({ "GET /api/ops/catalog": () => json(queue()) });
    render(<CatalogFixesPage />);
    await screen.findByTestId("counter");
    fireEvent.change(screen.getByLabelText("Issue type"), { target: { value: "mrp_mismatch" } });
    expect(within(screen.getByRole("table", { name: "Fix queue" })).getAllByRole("row")).toHaveLength(2);
    expect(screen.queryByRole("article", { name: "Listing L-BK-01" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Issue type"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Vendor"), { target: { value: "E002" } });
    expect(screen.getByRole("article", { name: "Listing L-PL-05" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Listing L-BK-02" })).not.toBeInTheDocument();
  });

  it("bulk approves the selected ready fixes through the simulator", async () => {
    const calls = stub({
      "GET /api/ops/catalog": () => json(queue()),
      "POST /api/ops/catalog/bulk-approve": () => json({ simulated: true, approved: ["fix:L-BK-02:price", "fix:L-BK-01:copy"], skipped: [], updates: [] }),
    });
    render(<CatalogFixesPage />);
    await screen.findByTestId("counter");
    fireEvent.click(screen.getByRole("button", { name: /Select ready/ }));
    fireEvent.click(screen.getByRole("button", { name: /Approve 2 selected/ }));
    await waitFor(() => expect(screen.getByText(/2 approved in the simulator/)).toBeInTheDocument());
    expect(calls.find((c) => c.path.startsWith("POST"))?.body).toEqual({ fix_ids: ["fix:L-BK-02:price", "fix:L-BK-01:copy"] });
    expect(screen.getByText(/Nothing was pushed to a marketplace/)).toBeInTheDocument();
  });

  it("approves one fix and rejects another from a listing card", async () => {
    const calls = stub({
      "GET /api/ops/catalog": () => json(queue()),
      "POST /api/ops/catalog/fixes/fix%3AL-BK-02%3Aprice/approve": () => json({ fix_id: "fix:L-BK-02:price", status: "approved" }),
      "POST /api/ops/catalog/fixes/fix%3AL-BK-01%3Acopy/reject": () => json({ fix_id: "fix:L-BK-01:copy", status: "rejected" }),
    });
    render(<CatalogFixesPage />);
    await screen.findByTestId("counter");
    fireEvent.click(screen.getByRole("button", { name: "Approve Set MRP to ₹1,100" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Reject Rewrite the title and bullets" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/reject"))).toBe(true));
  });

  it("shows a typed error when the bulk limit is exceeded", async () => {
    stub({
      "GET /api/ops/catalog": () => json(queue()),
      "POST /api/ops/catalog/bulk-approve": () => json({ code: "bulk_limit_exceeded", problem: "That is more fixes than one bulk approve may apply", cause: "The playbook caps a bulk approve", fix: "Select fewer fixes", run_id: null }, 409),
    });
    render(<CatalogFixesPage />);
    await screen.findByTestId("counter");
    fireEvent.click(screen.getByRole("button", { name: /Select ready/ }));
    fireEvent.click(screen.getByRole("button", { name: /Approve 2 selected/ }));
    expect(await screen.findByText("That is more fixes than one bulk approve may apply")).toBeInTheDocument();
  });

  it("warns about a fix the verifier blocked and does not offer to approve it", async () => {
    const blocked = copyFix({ status: "blocked", decision: "blocked", reason: "the proposed title is 120 characters" });
    stub({ "GET /api/ops/catalog": () => json(queue({ fixes: { "fix:L-BK-02:price": priceFix(), "fix:L-BK-01:copy": blocked }, summary: summary({ fixes_ready: 1, fixes_blocked: 1, minutes_saved: 12 }) })) });
    render(<CatalogFixesPage />);
    await screen.findByTestId("counter");
    expect(screen.getByText(/the verifier rejected/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Rewrite the title and bullets" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject Rewrite the title and bullets" })).toBeInTheDocument();
  });
});
