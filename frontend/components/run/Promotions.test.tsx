import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RUN_NAV } from "@/lib/ops";
import { assumptionItems, offerLabel, offerTone, pctNumber, startsText, stockRiskResolution, upliftText } from "@/lib/promotions";
import { planApproved, promoList, promoPlan } from "../../test-utils/promotionsFixtures";
import { PromotionsPage } from "./PromotionsPage";

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

const base = () => ({ "GET /api/ops/promotions": () => json(promoList()), "GET /api/ops/promotions/festive": () => json(promoPlan()) });

const row = (table: HTMLElement, sku: string) => {
  const r = within(table).getAllByRole("row").find((x) => x.textContent?.includes(sku));
  if (!r) throw new Error(`no row for ${sku}`);
  return r;
};

describe("lib/promotions helpers", () => {
  it("words the event timing, uplift and offer verdicts", () => {
    expect(startsText(11)).toBe("starts in 11 days");
    expect(startsText(1)).toBe("starts tomorrow");
    expect(startsText(-2)).toBe("started 2 days ago");
    expect(upliftText(2.66)).toBe("x2.7");
    expect(offerLabel("reject_structure")).toBe("Reject structure and counter");
    expect(offerTone("accept")).toBe("ok");
    expect(offerTone("declined")).toBe("neutral");
    expect(pctNumber(10)).toBe("10%");
  });
  it("explains what the plan did about a stock risk", () => {
    const rows = promoPlan().rows;
    expect(stockRiskResolution(rows.find((r) => r.sku_code === "PL-02")!)).toBe("Discount capped at 10%");
    expect(stockRiskResolution(rows.find((r) => r.sku_code === "GW-03")!)).toMatch(/Stock-up PO of 30 units, order by 2026-10-26/);
  });
  it("flattens the assumptions, including the nested deal evaluator", () => {
    const items = assumptionItems({ max_uplift: 4, deal_evaluator: { cv: 0.45 } });
    expect(items.map((i) => i.key)).toEqual(["max_uplift", "deal_evaluator.cv"]);
  });
  it("lists the two new modules in the Run navigation", () => {
    const hrefs = RUN_NAV.map((n) => n.href);
    expect(hrefs).toContain("/run/promotions");
    expect(RUN_NAV.find((n) => n.href === "/run/promotions")?.match("/run/promotions")).toBe(true);
  });
});

describe("PromotionsPage", () => {
  it("lists the events with timing and loads the selected plan", async () => {
    const calls = stub({ ...base(), "GET /api/ops/promotions/payday": () => json(promoPlan({ headline: "Payday plan headline", event: { ...promoPlan().event, id: "payday", name: "Payday Sale" } })) });
    render(<PromotionsPage />);
    const festive = await screen.findByRole("button", { name: /Festive Sale/ });
    expect(festive).toHaveTextContent("starts in 11 days");
    expect(festive).toHaveTextContent("24 SKUs planned");
    expect(festive).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Payday Sale/ })).toHaveTextContent("starts in 33 days");
    fireEvent.click(screen.getByRole("button", { name: /Payday Sale/ }));
    expect(await screen.findByText("Payday plan headline")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "GET /api/ops/promotions/payday")).toBe(true);
  });

  it("shows the totals and the event brief", async () => {
    stub(base());
    render(<PromotionsPage />);
    const totals = await screen.findByRole("region", { name: "Plan totals" });
    expect(totals).toHaveTextContent("SKUs on promo");
    expect(totals).toHaveTextContent("24");
    expect(totals).toHaveTextContent("₹17.06L");
    expect(totals).toHaveTextContent("₹35,820");
    expect(totals).toHaveTextContent("₹1.40L");
    expect(totals).toHaveTextContent("₹25,850");
    const brief = screen.getByRole("region", { name: "Event brief" });
    expect(brief).toHaveTextContent("Put 24 SKUs on promo for the Festive Sale");
    expect(brief).toHaveTextContent("would run out on day 5 of the event at 19.9% off");
    expect(brief).toHaveTextContent("mock");
  });

  it("notes sentences struck from the brief", async () => {
    stub({ ...base(), "GET /api/ops/promotions/festive": () => json(promoPlan({ struck: ["A sentence with a wrong number."] })) });
    render(<PromotionsPage />);
    expect(await screen.findByText(/1 sentence removed because a number in it did not verify/)).toBeInTheDocument();
    expect(screen.getByText("A sentence with a wrong number.")).toBeInTheDocument();
  });

  it("shows the planted cases in the plan table: capped by stock, stock-up PO, the cannibalising pair", async () => {
    stub(base());
    render(<PromotionsPage />);
    const table = await screen.findByRole("table", { name: "Promotion plan" });
    expect(within(table).getAllByRole("row")).toHaveLength(5); // header + 4 planned rows, the excluded SKU is not in the table
    const pl2 = row(table, "PL-02");
    expect(pl2).toHaveTextContent("Capped by stock");
    expect(pl2).toHaveTextContent("At 19.9% off it runs out on day 5");
    expect(pl2).toHaveTextContent("Cannibalises Ocean Fish Adult 1.2 kg");
    expect(pl2).toHaveTextContent("22/22 verified");
    expect(pl2).toHaveTextContent("x1.5");
    expect(row(table, "GW-03")).toHaveTextContent("Stock-up PO 30");
    const pl1 = row(table, "PL-01");
    expect(pl1).toHaveTextContent("Cannibalises Chicken & Tuna Adult 1.2 kg");
    expect(pl1).toHaveTextContent("Chicken & Tuna Adult 1.2 kg is also on promo");
    expect(pl1).toHaveTextContent("20.0%");
    expect(pl1).toHaveTextContent("4.5% to 17.0%");
    const gw1 = row(table, "GW-01");
    expect(gw1).toHaveTextContent("Stock ok");
    expect(gw1).toHaveTextContent("Banner 1");
    expect(gw1).toHaveTextContent("x2.7");
  });

  it("lists the excluded SKUs under Why not", async () => {
    stub(base());
    render(<PromotionsPage />);
    const why = (await screen.findByText(/Why not: 1 SKUs left out/)).closest("details")!;
    expect(why).toHaveTextContent("Senior Care 3 kg");
    expect(why).toHaveTextContent("the event's SKU limit left it out");
  });

  it("compares the deepest discount that pays with what the plan did", async () => {
    stub(base());
    render(<PromotionsPage />);
    const card = await screen.findByRole("article", { name: "Stock risk PL-02" });
    expect(card).toHaveTextContent("Deepest discount that pays");
    expect(card).toHaveTextContent("19.9%");
    expect(card).toHaveTextContent("day 5");
    expect(card).toHaveTextContent("85"); // units short
    expect(card).toHaveTextContent("₹41,161"); // lost GMV
    expect(card).toHaveTextContent("Discount capped at 10%");
    expect(screen.getByRole("article", { name: "Stock risk GW-03" })).toHaveTextContent("Stock-up PO of 30 units, order by 2026-10-26, arrives 2026-11-04");
  });

  it("shows the stock-up PO card", async () => {
    stub(base());
    render(<PromotionsPage />);
    const po = await screen.findByRole("article", { name: "Stock-up PO Groomwell" });
    expect(po).toHaveTextContent("Paw Balm 50 g");
    expect(po).toHaveTextContent("Order by 2026-10-26, arrives 2026-11-04");
    expect(po).toHaveTextContent("Draft, not placed");
  });

  it("values each vendor's offer: a rejected structure, a corrected reading and a decline", async () => {
    stub(base());
    render(<PromotionsPage />);
    const e1 = await screen.findByRole("article", { name: "Funding Barkley & Co" });
    expect(within(e1).getAllByText("Reject structure and counter").length).toBeGreaterThan(0);
    expect(e1).toHaveTextContent("3.6%");
    expect(e1).toHaveTextContent("keep the 3,400 units target but allow 30 days");
    expect(e1).toHaveTextContent("We can fund 50% of the markdown on the Barkley range");
    expect(e1).toHaveTextContent("Deal evaluator: P(target) 3.6%");
    const e3 = screen.getByRole("article", { name: "Funding NutriPaws" });
    expect(within(e3).getByText("Caught, then corrected: first read 53%, verified 35%")).toBeInTheDocument();
    expect(within(e3).getByText("Verified after correction")).toBeInTheDocument();
    const e5 = screen.getByRole("article", { name: "Funding Litterly" });
    expect(e5).toHaveTextContent("Declined");
    expect(e5).toHaveTextContent("Litterly declined to fund the event.");
    expect(e5).toHaveTextContent("Ask Litterly whether a smaller share is possible.");
  });

  it("queues the vendor emails as drafts and approves one", async () => {
    const plan = promoPlan();
    const calls = stub({ ...base(), "POST /api/ops/outbox/DR-PROMO-festive-E001/approve": () => json({ ...plan.drafts[0], status: "sent_simulated", decided_at: "2026-10-27T04:00:00+00:00" }) });
    render(<PromotionsPage />);
    const card = await screen.findByRole("article", { name: /Draft Festive Sale: funding with Barkley/ });
    fireEvent.click(within(card).getByRole("button", { name: /Approve and send/ }));
    expect(await within(card).findByText("Sent (simulated)")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "POST /api/ops/outbox/DR-PROMO-festive-E001/approve")).toBe(true);
  });

  it("approves the plan through the simulator and shows what was queued", async () => {
    const calls = stub({ ...base(), "POST /api/ops/promotions/festive/approve": () => json(planApproved()) });
    render(<PromotionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Approve plan \(simulated\)/ }));
    expect(await screen.findByText(/Plan approved \(simulated\): 24 prices queued, 3 stock-up POs queued, ₹25,850 total/)).toBeInTheDocument();
    expect(calls.find((c) => c.path.startsWith("POST"))?.path).toBe("POST /api/ops/promotions/festive/approve");
    expect(screen.getAllByText("queued (simulated)").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Approve plan \(simulated\)/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject plan" })).toBeDisabled();
  });

  it("rejects the plan", async () => {
    const calls = stub({ ...base(), "POST /api/ops/promotions/festive/reject": () => json(planApproved({ status: "rejected", n_skus: 0, prices: [], pos: [], stock_up_inr: 0 })) });
    render(<PromotionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject plan" }));
    expect(await screen.findByText("Plan rejected")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "POST /api/ops/promotions/festive/reject")).toBe(true);
  });

  it("shows the recorded decision when the plan was already decided", async () => {
    stub({ ...base(), "GET /api/ops/promotions/festive": () => json(promoPlan({ decision: { status: "approved", decided_at: "2026-10-26T09:30:00+00:00", n_skus: 24, stock_up_inr: 25850, pos: promoPlan().pos.map((p) => ({ ...p, status: "queued_simulated" })) } })) });
    render(<PromotionsPage />);
    expect(await screen.findByText(/Plan approved \(simulated\): 24 prices queued, 1 stock-up PO queued/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve plan \(simulated\)/ })).toBeDisabled();
  });

  it("shows a typed error from the approve call", async () => {
    stub({
      ...base(),
      "POST /api/ops/promotions/festive/approve": () => json({ code: "promo_plan_decided", problem: "This event plan was already decided", cause: "The plan was approved or rejected", fix: "Reset the demo", run_id: null }, 409),
    });
    render(<PromotionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Approve plan \(simulated\)/ }));
    expect(await screen.findByText("This event plan was already decided")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve plan \(simulated\)/ })).toBeEnabled();
  });

  it("shows the typed backend error when a plan cannot load", async () => {
    stub({ "GET /api/ops/promotions": () => json(promoList()), "GET /api/ops/promotions/festive": () => json({ code: "unknown_promo_event", problem: "unknown promotion event: 'festive'", cause: "not in the calendar", fix: "List the events" }, 404) });
    render(<PromotionsPage />);
    expect(await screen.findByText("unknown promotion event: 'festive'")).toBeInTheDocument();
  });

  it("ends with the verifier and the assumptions, which point to the Playbook", async () => {
    stub(base());
    render(<PromotionsPage />);
    expect(await screen.findByRole("region", { name: "Verifier" })).toHaveTextContent("3/3 verified");
    const details = screen.getByText("Assumptions").closest("details")!;
    expect(details).toHaveTextContent("Largest sales uplift allowed");
    const link = within(details).getByRole("link", { name: "Playbook" });
    expect(link).toHaveAttribute("href", "/rules");
    expect(details).toHaveTextContent("Promotions (Run)");
  });

  it("lists Promotions and Price watch in the Run navigation", async () => {
    stub(base());
    render(<PromotionsPage />);
    const nav = await screen.findByRole("navigation", { name: "Run" });
    expect(within(nav).getByRole("link", { name: "Promotions" })).toHaveAttribute("href", "/run/promotions");
    expect(within(nav).getByRole("link", { name: "Price watch" })).toHaveAttribute("href", "/run/price-watch");
  });
});
