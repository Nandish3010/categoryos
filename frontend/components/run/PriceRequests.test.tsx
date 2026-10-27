import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dateText, effectiveDecision, pctText, rupees, signedInr, signedPct, type PrDetail } from "@/lib/priceRequests";
import fixtures from "../../test-utils/priceRequestFixtures.json";
import { PriceRequestsPage, RequestDetail } from "./PriceRequestsPage";

afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const detail = (id: "PR-001" | "PR-002" | "PR-003") => (fixtures as unknown as Record<string, PrDetail>)[id];

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const key = `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}`;
      calls.push({ path: key, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const h = routes[key];
      return h ? h(init) : json({ code: "not_found", problem: `no stub for ${key}` }, 404);
    }),
  );
  return calls;
}

describe("price request helpers", () => {
  it("formats percent numbers, rupees and dates", () => {
    expect(pctText(4.66)).toBe("4.7%");
    expect(signedPct(-6.8)).toBe("−6.8%");
    expect(rupees(219.24)).toBe("₹219.24");
    expect(signedInr(-3170.3)).toBe("−₹3,170");
    expect(dateText("2026-11-25")).toBe("25 Nov 2026");
    expect(pctText(null)).toBe("—");
  });
  it("a delayed line leads to what it would do once the date is moved", () => {
    const l = detail("PR-003").evaluation.lines[0];
    expect(l.decision).toBe("delay");
    expect(effectiveDecision(l)).toBe("accept_partial");
  });
});

describe("RequestDetail", () => {
  it("shows the extracted table with margin, retail price, competitor gap and a decision chip per SKU", () => {
    render(<RequestDetail d={detail("PR-003")} onStatus={() => {}} />);
    const table = screen.getByRole("table", { name: /extracted price lines/i });
    const rows = within(table).getAllByRole("row");
    expect(rows.length).toBeGreaterThanOrEqual(5);
    const np01 = rows.find((r) => within(r).queryByText("NP-01"));
    expect(np01).toBeTruthy();
    expect(within(np01!).getAllByText("+15.0%")).toHaveLength(2); // asked +15% and 15% above competitors if passed on
    expect(within(np01!).getByText(/then accept partly/i)).toBeInTheDocument();
    expect(within(np01!).getByText(/ask for 25 Nov 2026/)).toBeInTheDocument();
    expect(screen.getAllByText("high").length).toBeGreaterThan(0); // elasticity risk
    expect(screen.getByTestId("request-detail")).toHaveAttribute("data-decision", "delay");
    expect(screen.getByText(/1 corrected by the agent/)).toBeInTheDocument();
  });

  it("values the volume sweetener with the deal evaluator card: a tiny probability that counts as zero", () => {
    render(<RequestDetail d={detail("PR-002")} onStatus={() => {}} />);
    const card = screen.getByTestId("deal-card");
    expect(card).toHaveAttribute("data-decision", "reject_structure");
    expect(within(card).getByTestId("probability").textContent).toBe("2.8%");
    expect(within(card).getByTestId("counted-pts").textContent).toMatch(/^\d/);
    expect(screen.getByTestId("tier")).toHaveTextContent("Category manager");
  });

  it("shows an acceptance-linked support offer and the index justification", () => {
    render(<RequestDetail d={detail("PR-001")} onStatus={() => {}} />);
    expect(screen.getByTestId("support-card")).toHaveTextContent(/2% extra marketing support/);
    expect(screen.getByTestId("justification")).toHaveTextContent(/Raw material index/);
    expect(screen.getByTestId("tier")).toHaveTextContent("Category executive");
  });

  it("says plainly when no retail change is needed instead of three equal impact rows", () => {
    render(<RequestDetail d={detail("PR-001")} onStatus={() => {}} />);
    expect(screen.getByTestId("impact-unchanged")).toHaveTextContent(/No retail change needed: absorbing keeps margin above target/);
    expect(screen.queryByText("Margin if we pass it on")).not.toBeInTheDocument();
  });

  it("compares absorb, pass-through and the decision when they differ", () => {
    render(<RequestDetail d={detail("PR-002")} onStatus={() => {}} />);
    expect(screen.queryByTestId("impact-unchanged")).not.toBeInTheDocument();
    expect(screen.getByText("Margin if we pass it on")).toBeInTheDocument();
  });

  it("gives each SKU a one-line reason from the engine, not just its code", () => {
    const d = structuredClone(detail("PR-001"));
    d.evaluation.lines[0].why = "margin stays 38.4% vs 38% target; index justifies up to 5.0%";
    render(<RequestDetail d={d} onStatus={() => {}} />);
    expect(screen.getByText(/Why: margin stays 38\.4% vs 38% target/)).toBeInTheDocument();
  });

  it("approves at a role, sending nothing: the backend records a simulated send", async () => {
    const calls = stub({
      "POST /api/price-requests/PR-001/approve": () => json({ id: "PR-001", status: "approved", by: "category_executive", at: "t", sent: { simulated: true, to: "x", subject: "s", body: "b" } }),
    });
    const seen: string[] = [];
    render(<RequestDetail d={detail("PR-001")} onStatus={(s) => seen.push(s.status)} />);
    fireEvent.click(screen.getByRole("button", { name: /approve and send \(simulated\)/i }));
    await waitFor(() => expect(seen).toEqual(["approved"]));
    expect(calls[0].body).toMatchObject({ role: "category_executive" });
    expect(screen.getByText(/Nothing is sent to the vendor/)).toBeInTheDocument();
  });

  it("shows the typed error when the approver is too junior", async () => {
    stub({
      "POST /api/price-requests/PR-002/approve": () =>
        json({ code: "approval_tier_too_low", problem: "category executive cannot approve this request: it needs Category manager", cause: "x", fix: "Escalate to the approver named in the problem" }, 403),
    });
    render(<RequestDetail d={detail("PR-002")} onStatus={() => {}} />);
    fireEvent.change(screen.getByLabelText("Approving as"), { target: { value: "category_executive" } });
    fireEvent.click(screen.getByRole("button", { name: /approve and send/i }));
    expect(await screen.findByText(/needs Category manager/)).toBeInTheDocument();
  });
});

describe("PriceRequestsPage", () => {
  it("lists the inbox and opens the first request", async () => {
    stub({
      "GET /api/price-requests": () => json(fixtures.inbox),
      "GET /api/price-requests/PR-001": () => json(detail("PR-001")),
      "GET /api/price-requests/PR-003": () => json(detail("PR-003")),
    });
    render(<PriceRequestsPage />);
    const inbox = await screen.findByRole("region", { name: "Request inbox" });
    expect(within(inbox).getAllByRole("button")).toHaveLength(3);
    expect(await screen.findByTestId("request-detail")).toHaveAttribute("data-decision", "accept");
    fireEvent.click(within(inbox).getByText("NutriPaws"));
    await waitFor(() => expect(screen.getByTestId("request-detail")).toHaveAttribute("data-decision", "delay"));
    expect(screen.getByRole("link", { name: "Price requests" })).toHaveAttribute("href", "/run/price-requests");
  });
});
