import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { approveLabel, bandTone, coverPosition, effectText, kindLabel, recommendationLabel, severityTone } from "@/lib/inventoryHealth";
import { RUN_NAV } from "@/lib/ops";
import { inventoryHealth, liquidateApproved, reorderApproved, returnApproved } from "../../test-utils/inventoryHealthFixtures";
import { InventoryHealthPage } from "./InventoryHealthPage";

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

const base = () => ({ "GET /api/ops/inventory-health": () => json(inventoryHealth()) });
const card = (id: string) => screen.findByRole("article", { name: `Action ${id}` });

describe("lib/inventoryHealth helpers", () => {
  it("labels kinds and recommendations and picks tones", () => {
    expect(kindLabel("stock_out")).toBe("Stock-out risk");
    expect(kindLabel("overbuy")).toBe("MOQ overbuy");
    expect(recommendationLabel("return_to_vendor")).toBe("Return to vendor");
    expect(recommendationLabel("expedite_po")).toBe("Expedite the late PO");
    expect(severityTone("critical")).toBe("bad");
    expect(bandTone("in")).toBe("ok");
    expect(approveLabel({ recommendation: "reorder" })).toBe("Draft the PO (simulated)");
    expect(approveLabel({ recommendation: "liquidate" })).toBe("Nominate for promo (simulated)");
    expect(approveLabel({ recommendation: "pause_po" })).toBe("Approve message (simulated)");
  });
  it("places cover on the band bar and caps it", () => {
    expect(coverPosition(0, { max_days: 60 })).toBe(0);
    expect(coverPosition(45, { max_days: 60 })).toBeCloseTo(0.5);
    expect(coverPosition(900, { max_days: 60 })).toBe(1);
    expect(coverPosition(null, { max_days: 60 })).toBe(1);
  });
  it("describes what a decision did", () => {
    expect(effectText(reorderApproved.effect, (n) => `R${n}`)).toMatch(/PO draft queued \(simulated\): 1800 units of NP-03/);
    expect(effectText(liquidateApproved.effect, (n) => `R${n}`)).toMatch(/Promo nomination queued \(simulated\)/);
    expect(effectText(null, String)).toBe("No change was made.");
  });
  it("lists Inventory health in the Run navigation", () => {
    const item = RUN_NAV.find((n) => n.href === "/run/inventory-health");
    expect(item?.label).toBe("Inventory health");
    expect(item?.match("/run/inventory-health")).toBe(true);
  });
});

describe("InventoryHealthPage", () => {
  it("shows the counts, the playbook thresholds and the weekly summary", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("SKUs reviewed");
    expect(summary).toHaveTextContent("38");
    expect(summary).toHaveTextContent("Stock-out risks");
    expect(summary).toHaveTextContent("Overbuys");
    expect(summary).toHaveTextContent("Dead or aged");
    expect(summary).toHaveTextContent("Stuck stock");
    expect(summary).toHaveTextContent("Healthy cover is 14–60 days");
    const weekly = screen.getByRole("region", { name: "Weekly summary" });
    expect(weekly).toHaveTextContent("Reorder two SKUs");
    expect(weekly).toHaveTextContent("mock");
  });

  it("shows every planted issue as a card, most urgent first", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    await card("ih:stock_out:NP-03");
    const ids = within(screen.getByRole("region", { name: "Actions" })).getAllByRole("article").map((a) => a.getAttribute("aria-label"));
    expect(ids.slice(0, 3)).toEqual(["Action ih:stock_out:NP-03", "Action ih:stock_out:LT-05", "Action ih:stock_out:PL-01"]);
    for (const id of ["ih:dead:GW-91", "ih:dead:NP-91", "ih:aged:TW-05", "ih:overbuy:TW-06", "ih:aged:TW-04", "ih:aged:TW-03"]) expect(ids).toContain(`Action ${id}`);
  });

  it("shows the reorder card with the MOQ, lead time and a cover bar", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const np = await card("ih:stock_out:NP-03");
    expect(np).toHaveTextContent("Peanut Butter Biscuits 400 g");
    expect(np).toHaveTextContent("critical");
    expect(np).toHaveTextContent("Stock-out risk");
    const kn = np.querySelector("dl")!;
    expect(kn).toHaveTextContent("1,800 units");
    expect(kn).toHaveTextContent("6 days");
    expect(kn).toHaveTextContent("1,447 / 600");
    expect(within(np).getByRole("img", { name: /Cover for Peanut Butter Biscuits 400 g.*band 14 to 60 days/ })).toBeInTheDocument();
    expect(np).toHaveTextContent("5/5 verified");
  });

  it("shows the late PO as an expedite, not a reorder", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const lt = await card("ih:stock_out:LT-05");
    expect(within(lt).getByText("Expedite the late PO")).toBeInTheDocument();
    expect(within(lt).getByRole("button", { name: "Approve message (simulated) LT-05" })).toBeInTheDocument();
  });

  it("warns when the sell-or-return window is closing and shows the vendor credit", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const tw = await card("ih:aged:TW-05");
    expect(within(tw).getByText("The sell-or-return window closes soon")).toBeInTheDocument();
    expect(tw.querySelector("dl")).toHaveTextContent("₹35,844");
    expect(within(tw).getByText("Return to vendor")).toBeInTheDocument();
  });

  it("shows a lapsed window and a promo price for the liquidation", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const tw = await card("ih:aged:TW-03");
    expect(within(tw).getByText("Liquidate on a promo")).toBeInTheDocument();
    expect(tw.querySelector("dl")).toHaveTextContent("Closed 2026-10-10");
    expect(tw.querySelector("dl")).toHaveTextContent("25.0% off");
  });

  it("shows the MOQ overbuy with the cover with and without the PO", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const ob = await card("ih:overbuy:TW-06");
    expect(within(ob).getByText("MOQ overbuy")).toBeInTheDocument();
    expect(ob.querySelector("dl")).toHaveTextContent("Cover with / without it");
    expect(within(ob).getByText("Pause the PO")).toBeInTheDocument();
  });

  it("marks discontinued lots", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    expect(await card("ih:dead:GW-91")).toHaveTextContent("discontinued, not in the live list");
  });

  it("approves a reorder and shows the PO draft", async () => {
    const calls = stub({ ...base(), "POST /api/ops/inventory-health/actions/ih%3Astock_out%3ANP-03/approve": () => json(reorderApproved) });
    render(<InventoryHealthPage />);
    const np = await card("ih:stock_out:NP-03");
    fireEvent.click(within(np).getByRole("button", { name: "Draft the PO (simulated) NP-03" }));
    expect(await within(np).findByText(/PO draft queued \(simulated\): 1800 units of NP-03/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true);
    expect(within(np).queryByRole("button", { name: /Draft the PO/ })).not.toBeInTheDocument();
  });

  it("approves a return, which sends the vendor message in the simulator and reloads", async () => {
    const calls = stub({ ...base(), "POST /api/ops/inventory-health/actions/ih%3Aaged%3ATW-05/approve": () => json(returnApproved) });
    render(<InventoryHealthPage />);
    const tw = await card("ih:aged:TW-05");
    fireEvent.click(within(tw).getByRole("button", { name: "Approve message (simulated) TW-05" }));
    expect(await within(tw).findByText(/Vendor message sent \(simulated\) to E004/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "GET /api/ops/inventory-health").length).toBeGreaterThan(1);
  });

  it("rejects an action", async () => {
    stub({ ...base(), "POST /api/ops/inventory-health/actions/ih%3Aaged%3ATW-04/reject": () => json({ ...liquidateApproved, status: "rejected", effect: null }) });
    render(<InventoryHealthPage />);
    const tw = await card("ih:aged:TW-04");
    fireEvent.click(within(tw).getByRole("button", { name: "Reject TW-04" }));
    expect(await within(tw).findByText("Rejected: no change was made.")).toBeInTheDocument();
  });

  it("restores an action that was already decided", async () => {
    const d = inventoryHealth();
    d.actions[0].decision = { status: "approved", effect: reorderApproved.effect, recommendation: "reorder" };
    stub({ "GET /api/ops/inventory-health": () => json(d) });
    render(<InventoryHealthPage />);
    const np = await card("ih:stock_out:NP-03");
    expect(np).toHaveTextContent("Approved (simulated)");
    expect(within(np).queryByRole("button", { name: /Draft the PO/ })).not.toBeInTheDocument();
  });

  it("shows a typed error from an action and keeps the button usable", async () => {
    stub({
      ...base(),
      "POST /api/ops/inventory-health/actions/ih%3Astock_out%3ANP-03/approve": () => json({ code: "inventory_action_decided", problem: "This inventory action was already decided", cause: "It was approved or rejected", fix: "Reset the demo" }, 409),
    });
    render(<InventoryHealthPage />);
    const np = await card("ih:stock_out:NP-03");
    fireEvent.click(within(np).getByRole("button", { name: "Draft the PO (simulated) NP-03" }));
    expect(await screen.findByText("This inventory action was already decided")).toBeInTheDocument();
    expect(within(np).getByRole("button", { name: "Draft the PO (simulated) NP-03" })).toBeEnabled();
  });

  it("shows the typed backend error when the review cannot load", async () => {
    stub({ "GET /api/ops/inventory-health": () => json({ code: "inventory_health_data_missing", problem: "The inventory health data files are missing or unreadable", cause: "not generated", fix: "Run python3 data/generate_inventory_health.py" }, 500) });
    render(<InventoryHealthPage />);
    expect(await screen.findByText("The inventory health data files are missing or unreadable")).toBeInTheDocument();
  });

  it("lists the vendor roll-up, the SKUs, the vendor messages, the verifier and the Playbook note", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    expect(await screen.findByRole("table", { name: "Inventory health by vendor" })).toHaveTextContent("NutriPaws");
    expect(screen.getAllByRole("article", { name: /Draft Inventory review/ }).length).toBeGreaterThan(0);
    const all = screen.getByText(/All SKUs reviewed \(/).closest("details")!;
    expect(within(all).getByRole("table", { name: "All SKUs reviewed" })).toHaveTextContent("Peanut Butter Biscuits 400 g");
    expect(screen.getByRole("region", { name: "Verifier" })).toBeInTheDocument();
    expect(screen.getByText(/tunable in the/)).toHaveTextContent("Inventory health (Run)");
  });

  it("lists Inventory health in the Run navigation", async () => {
    stub(base());
    render(<InventoryHealthPage />);
    const nav = await screen.findByRole("navigation", { name: "Run" });
    expect(within(nav).getByRole("link", { name: "Inventory health" })).toHaveAttribute("href", "/run/inventory-health");
  });
});
