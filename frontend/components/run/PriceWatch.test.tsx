import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RUN_NAV } from "@/lib/ops";
import { approveLabel, chartLines, daysUnder, effectText, kindLabel, recommendationLabel, recommendationTone } from "@/lib/priceWatch";
import { breachApproved, matchApproved, priceWatch } from "../../test-utils/priceWatchFixtures";
import { PriceWatchPage } from "./PriceWatchPage";

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

const base = () => ({ "GET /api/ops/price-watch": () => json(priceWatch()) });
const card = (id: string) => screen.findByRole("article", { name: `Action ${id}` });

describe("lib/priceWatch helpers", () => {
  it("labels kinds and recommendations and picks their tone", () => {
    expect(kindLabel("undercut")).toBe("Sustained undercut");
    expect(kindLabel("breach")).toBe("Vendor parity breach");
    expect(kindLabel("blip")).toBe("Blip");
    expect(kindLabel("trend")).toBe("Falling trend");
    expect(recommendationLabel("match")).toBe("Match");
    expect(recommendationLabel("ask_vendor_funding")).toBe("Ask vendor for price protection");
    expect(recommendationLabel("flag_breach")).toBe("Flag breach to vendor");
    expect(recommendationTone("match")).toBe("ok");
    expect(recommendationTone("flag_breach")).toBe("warn");
    expect(recommendationTone("hold")).toBe("neutral");
    expect(recommendationTone("escalate")).toBe("bad");
    expect(approveLabel({ recommendation: "hold" })).toBe("Acknowledge");
    expect(approveLabel({ recommendation: "match" })).toBe("Approve (simulated)");
  });
  it("counts the days in a row a marketplace has been under our price", () => {
    const [bk, gw, , , blip] = priceWatch().actions;
    expect(daysUnder(bk.series, "MarketA", 3)).toBe(9);
    expect(daysUnder(gw.series, "MarketB", 3)).toBe(6);
    expect(daysUnder(blip.series, "MarketC", 3)).toBe(1);
    expect(daysUnder(blip.series, "Nowhere", 3)).toBe(0);
  });
  it("draws the vendor storefront and the MAP line only on breach cards", () => {
    const a = priceWatch().actions;
    expect(chartLines(a[2]).map((l) => l.role)).toEqual(["ours", "competitor", "competitor", "competitor", "vendor", "map"]);
    expect(chartLines(a[0]).map((l) => l.role)).toEqual(["ours", "competitor", "competitor", "competitor"]);
  });
  it("describes what a decision did", () => {
    expect(effectText({ type: "price_change", sku_code: "GW-01", from_price: 321, to_price: 292, reason: "match MarketB" }, (n) => `R${n}`)).toBe("Price change queued (simulated): GW-01 from R321 to R292 (match MarketB).");
    expect(effectText({ type: "watch", sku_code: "NP-04", recheck: "tomorrow's sweep" }, String)).toMatch(/re-check/);
    expect(effectText(null, String)).toBe("No change was made.");
  });
  it("lists Price watch in the Run navigation", () => {
    expect(RUN_NAV.at(-1)?.href).toBe("/run/price-watch");
    expect(RUN_NAV.at(-1)?.match("/run/price-watch")).toBe(true);
  });
});

describe("PriceWatchPage", () => {
  it("shows the counts, the thresholds and the daily summary", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("SKUs scanned");
    expect(summary).toHaveTextContent("36");
    expect(summary).toHaveTextContent("Sustained undercuts");
    expect(summary).toHaveTextContent("Blips ignored");
    expect(summary).toHaveTextContent("Trends watched");
    expect(summary).toHaveTextContent("Parity breaches");
    expect(summary).toHaveTextContent("An undercut is sustained after 3 days; a shorter one is a blip.");
    const daily = screen.getByRole("region", { name: "Daily summary" });
    expect(daily).toHaveTextContent("Match one price, ask one vendor for protection");
    expect(daily).toHaveTextContent("Oatmeal Pet Shampoo 250 ml has been 9.0% under our price on MarketB for 6 days");
    expect(daily).toHaveTextContent("mock");
    expect(screen.getByText(/1 sentence removed because a number in it did not verify/)).toBeInTheDocument();
  });

  it("orders the five actions as given", async () => {
    stub(base());
    render(<PriceWatchPage />);
    await card("pw:undercut:BK-01");
    const ids = within(screen.getByRole("region", { name: "Actions" })).getAllByRole("article").map((a) => a.getAttribute("aria-label"));
    expect(ids).toEqual(["Action pw:undercut:BK-01", "Action pw:undercut:GW-01", "Action pw:breach:LT-01", "Action pw:trend:TW-02", "Action pw:blip:NP-04"]);
  });

  it("shows the match card with its reasons, key numbers and a labelled chart", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const gw = await card("pw:undercut:GW-01");
    expect(gw).toHaveTextContent("Oatmeal Pet Shampoo 250 ml");
    expect(gw).toHaveTextContent("Sustained undercut");
    expect(within(gw).getAllByText("Match").length).toBeGreaterThan(0);
    expect(gw).toHaveTextContent("Matching keeps the margin at or above the floor");
    const nums = within(gw).getByRole("list", { hidden: false, name: "Reasons" });
    expect(nums).toBeInTheDocument();
    const kn = gw.querySelector("dl")!;
    expect(kn).toHaveTextContent("₹321");
    expect(kn).toHaveTextContent("₹292, 9.0% below us");
    expect(kn).toHaveTextContent("6 days");
    expect(kn).toHaveTextContent("₹292 (cut 9.0%)");
    expect(kn).toHaveTextContent("40.8%, 34.9%, 30.0%");
    expect(kn).toHaveTextContent("+₹2,357");
    const chart = within(gw).getByRole("img", { name: /Price chart for Oatmeal Pet Shampoo 250 ml.*Our price.*MarketB/ });
    expect(chart).toBeInTheDocument();
    expect(gw).toHaveTextContent("2/2 verified");
  });

  it("asks the vendor for price protection when matching would break the margin floor", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const bk = await card("pw:undercut:BK-01");
    expect(within(bk).getByText("Ask vendor for price protection")).toBeInTheDocument();
    expect(bk).toHaveTextContent("₹41 a unit, ₹17,529 in all");
    expect(bk).toHaveTextContent("−₹10,082");
    expect(bk).toHaveTextContent("21.3%, 15.5%, 20.0%");
  });

  it("says plainly that the blip was not matched and what matching would have cost", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const blip = await card("pw:blip:NP-04");
    expect(within(blip).getByText("Not matched: this was a blip")).toBeInTheDocument();
    expect(blip).toHaveTextContent("lasted 1 day, under the 3 days that make an undercut sustained");
    expect(blip).toHaveTextContent("Matching would have cost ₹2,987 of margin over 30 days");
    expect(within(blip).getByText("Hold")).toBeInTheDocument();
    expect(within(blip).getByRole("button", { name: "Acknowledge NP-04" })).toBeInTheDocument();
    expect(within(blip).queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("shows the vendor breach with the vendor storefront and the MAP price", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const lt = await card("pw:breach:LT-01");
    expect(within(lt).getByText("Vendor parity breach")).toBeInTheDocument();
    expect(within(lt).getByText("Flag breach to vendor")).toBeInTheDocument();
    expect(lt).toHaveTextContent("₹566, 12.0% under ours");
    expect(lt).toHaveTextContent("9 days");
    expect(lt).toHaveTextContent("₹624, under it for 9 days");
    expect(lt).toHaveTextContent("₹41,388");
    expect(within(lt).getByRole("img", { name: /Vendor on MarketB.*MAP price/ })).toBeInTheDocument();
    expect(within(lt).getByText("Do not cut our price to follow the vendor; ask the vendor to restore parity.")).toBeInTheDocument();
  });

  it("shows the falling trend as a hold", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const tw = await card("pw:trend:TW-02");
    expect(within(tw).getByText("Falling trend")).toBeInTheDocument();
    expect(tw).toHaveTextContent("−0.73% a day");
  });

  it("approves a match and shows the queued price change", async () => {
    const calls = stub({ ...base(), "POST /api/ops/price-watch/actions/pw%3Aundercut%3AGW-01/approve": () => json(matchApproved()) });
    render(<PriceWatchPage />);
    const gw = await card("pw:undercut:GW-01");
    fireEvent.click(within(gw).getByRole("button", { name: "Approve (simulated) GW-01" }));
    expect(await within(gw).findByText(/Price change queued \(simulated\): GW-01 from ₹321 to ₹292 \(match MarketB\)/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "POST /api/ops/price-watch/actions/pw%3Aundercut%3AGW-01/approve")).toBe(true);
    expect(within(gw).queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("approves a breach flag, which sends the vendor message in the simulator", async () => {
    const calls = stub({ ...base(), "POST /api/ops/price-watch/actions/pw%3Abreach%3ALT-01/approve": () => json(breachApproved()) });
    render(<PriceWatchPage />);
    const lt = await card("pw:breach:LT-01");
    fireEvent.click(within(lt).getByRole("button", { name: "Approve (simulated) LT-01" }));
    expect(await within(lt).findByText(/Vendor message sent \(simulated\) to E005/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "GET /api/ops/price-watch").length).toBeGreaterThan(1); // reloaded to pick up the sent draft
  });

  it("rejects an action", async () => {
    const calls = stub({ ...base(), "POST /api/ops/price-watch/actions/pw%3Aundercut%3AGW-01/reject": () => json({ ...matchApproved(), status: "rejected", effect: null }) });
    render(<PriceWatchPage />);
    const gw = await card("pw:undercut:GW-01");
    fireEvent.click(within(gw).getByRole("button", { name: "Reject GW-01" }));
    expect(await within(gw).findByText("Rejected: no change was made.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/reject"))).toBe(true);
  });

  it("acknowledges a hold, which keeps watching", async () => {
    stub({
      ...base(),
      "POST /api/ops/price-watch/actions/pw%3Ablip%3ANP-04/approve": () => json({ ...matchApproved(), action_id: "pw:blip:NP-04", recommendation: "hold", effect: { type: "watch", sku_code: "NP-04", recheck: "tomorrow's sweep" } }),
    });
    render(<PriceWatchPage />);
    const blip = await card("pw:blip:NP-04");
    fireEvent.click(within(blip).getByRole("button", { name: "Acknowledge NP-04" }));
    expect(await within(blip).findByText("Acknowledged")).toBeInTheDocument();
    expect(blip).toHaveTextContent("Watching: re-check at tomorrow's sweep.");
  });

  it("restores an action that was already decided", async () => {
    const w = priceWatch();
    w.actions[1].decision = { status: "approved", effect: { type: "price_change", sku_code: "GW-01", from_price: 321, to_price: 292, reason: "match MarketB" }, recommendation: "match" };
    stub({ "GET /api/ops/price-watch": () => json(w) });
    render(<PriceWatchPage />);
    const gw = await card("pw:undercut:GW-01");
    expect(gw).toHaveTextContent("Approved (simulated)");
    expect(within(gw).queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("shows a typed error from an action", async () => {
    stub({
      ...base(),
      "POST /api/ops/price-watch/actions/pw%3Aundercut%3AGW-01/approve": () => json({ code: "price_watch_action_decided", problem: "This price-watch action was already decided", cause: "It was approved or rejected", fix: "Reset the demo" }, 409),
    });
    render(<PriceWatchPage />);
    const gw = await card("pw:undercut:GW-01");
    fireEvent.click(within(gw).getByRole("button", { name: "Approve (simulated) GW-01" }));
    expect(await screen.findByText("This price-watch action was already decided")).toBeInTheDocument();
    expect(within(gw).getByRole("button", { name: "Approve (simulated) GW-01" })).toBeEnabled();
  });

  it("shows the typed backend error when the sweep cannot load", async () => {
    stub({ "GET /api/ops/price-watch": () => json({ code: "ops_data_missing", problem: "The price snapshot file is missing", cause: "not generated", fix: "Run python3 data/generate_ops.py" }, 500) });
    render(<PriceWatchPage />);
    expect(await screen.findByText("The price snapshot file is missing")).toBeInTheDocument();
  });

  it("lists the vendor messages, the scanned SKUs, the verifier and the Playbook note", async () => {
    stub(base());
    render(<PriceWatchPage />);
    expect(await screen.findByRole("article", { name: /Draft Price protection request: Chicken & Rice Adult 3 kg/ })).toBeInTheDocument();
    const all = screen.getByText(/All SKUs scanned \(/).closest("details")!;
    const table = within(all).getByRole("table", { name: "All SKUs scanned" });
    expect(table).toHaveTextContent("Clumping Bentonite Unscented 10 kg");
    expect(table).toHaveTextContent("Breach");
    expect(table).toHaveTextContent("Sustained undercut");
    expect(screen.getByRole("region", { name: "Verifier" })).toHaveTextContent("3/3 verified");
    expect(screen.getByText(/tunable in the/)).toHaveTextContent("Price watch (Run)");
  });

  it("lists Price watch and Promotions in the Run navigation", async () => {
    stub(base());
    render(<PriceWatchPage />);
    const nav = await screen.findByRole("navigation", { name: "Run" });
    expect(within(nav).getByRole("link", { name: "Price watch" })).toHaveAttribute("href", "/run/price-watch");
    expect(within(nav).getByRole("link", { name: "Promotions" })).toHaveAttribute("href", "/run/promotions");
  });
});
