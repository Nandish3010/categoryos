import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dealsFixture } from "../../test-utils/deals";
import { LiveCall, NextAskCard } from "./LiveCall";
import { NegotiateView } from "./NegotiateView";

afterEach(() => vi.unstubAllGlobals());

const callEvent = (seq: number, type: string, payload: Record<string, unknown>) => ({ seq, call_id: "c1", type, payload });
const sse = (events: ReturnType<typeof callEvent>[]) =>
  events
    .map((e) => `id: ${e.seq}\nevent: call\ndata: ${JSON.stringify(e)}\n\n`)
    .join("");

const gap = {
  term: "margin_pct", label: "Margin offered to us", unit: "pct", direction: "higher", application: 17, offered: 21, required: 35,
  gap: -14, status: "gap", turn: 4, quote: "I can move to 21 percent.", claim_id: "c", verification: "verified",
};

function stubBackend(mode = "mock") {
  const posts: { path: string; body: unknown }[] = [];
  const events = [
    callEvent(1, "started", { mode: "simulate", state: { gap_table: [], next_ask: { kind: "ask_term", line: "What can you offer on margin?", reason: "We have not heard a position yet." } } }),
    callEvent(2, "turn", { turn: { turn: 1, speaker: "buyer", text: "Margin. Where can you get to?", source: "simulated" } }),
    callEvent(3, "turn", { turn: { turn: 2, speaker: "vendor", text: "I can move to 21 percent.", source: "simulated" } }),
    callEvent(4, "state", {
      turn: 2,
      changed: { gap_terms: ["margin_pct"], deal_ids: ["t2"] },
      state: {
        gap_table: [gap],
        deals: dealsFixture(),
        next_ask: { kind: "reject_conditional", line: "Can you set the target at 250 units in 90 days instead?", reason: "Don't accept 20% marketing support: <0.1% chance of hitting it." },
        spend_usd: 0,
      },
    }),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
      if (url.pathname === "/api/mode") return json({ mode, spend_usd: 0, max_spend_usd: 5 });
      if (url.pathname === "/api/vendors/V002/call" && init?.method === "POST") {
        posts.push({ path: url.pathname, body: JSON.parse(String(init.body)) });
        return json({ call_id: "c1", mode: "simulate" }, 202);
      }
      if (url.pathname === "/api/vendors/V002/call/c1/events")
        return new Response(
          new ReadableStream({
            start(c) {
              c.enqueue(new TextEncoder().encode(sse(events)));
              c.close();
            },
          }),
          { status: 200, headers: { "Content-Type": "text/event-stream" } },
        );
      return json({ problem: `unmocked ${url.pathname}` }, 404);
    }),
  );
  return posts;
}

describe("LiveCall", () => {
  it("simulates a call: streams the transcript, fills the gap table, prices the offer and says what to ask next", async () => {
    const posts = stubBackend();
    render(<LiveCall vendorId="V002" />);
    fireEvent.click(screen.getByRole("button", { name: "Simulate call" }));
    await waitFor(() => expect(screen.getByText("I can move to 21 percent.")).toBeInTheDocument());
    expect(posts[0].body).toEqual({ mode: "simulate", speed: 1 });
    const transcript = screen.getByRole("region", { name: "Live transcript" });
    expect(within(transcript).getAllByRole("listitem").length).toBeGreaterThanOrEqual(2);
    const table = await screen.findByRole("region", { name: "Gap table" });
    expect(table.querySelector("tr[data-term=margin_pct]")).toHaveClass("flash-amber");
    expect(within(table).getByRole("button", { name: "21%" })).toBeInTheDocument();
    expect(await screen.findByTestId("dont-accept")).toHaveTextContent("Don't accept: <0.1% chance");
    expect(screen.getByTestId("next-ask-line")).toHaveTextContent("set the target at 250 units in 90 days");
    expect(screen.getByTestId("next-ask")).toHaveAttribute("data-kind", "reject_conditional");
    expect(screen.getByRole("region", { name: "Deal evaluator" })).toBeInTheDocument();
    expect(screen.getByTestId("probability")).toHaveTextContent("<0.1%");
  });

  it("keeps the microphone off in mock mode but offers it free simulation", async () => {
    stubBackend("mock");
    render(<LiveCall vendorId="V002" />);
    const mic = screen.getByRole("button", { name: /Start live call/ });
    expect(mic).toBeDisabled();
    expect(mic).toHaveAttribute("title", expect.stringContaining("live mode and the demo key"));
    expect(screen.getByRole("button", { name: "Simulate call" })).toBeEnabled();
  });

  it("starts the simulation at 4x when asked", async () => {
    const posts = stubBackend();
    render(<LiveCall vendorId="V002" />);
    fireEvent.click(screen.getByLabelText("4× speed"));
    fireEvent.click(screen.getByRole("button", { name: "Simulate call" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].body).toEqual({ mode: "simulate", speed: 4 });
  });
});

describe("NextAskCard", () => {
  it("shows the line and the reason, and nothing without a suggestion", () => {
    const { container, rerender } = render(<NextAskCard ask={null} ended={false} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<NextAskCard ask={{ kind: "gap", line: "Can you move margin from 21% toward 35%?", reason: "Margin is still 14 pts short.", term: "margin_pct" }} ended={false} />);
    expect(screen.getByText(/Say next · Close the biggest gap/)).toBeInTheDocument();
    expect(screen.getByTestId("next-ask-reason")).toHaveTextContent("14 pts short");
  });
});

describe("NegotiateView mode switch", () => {
  it("offers Call review and Live call when it knows the vendor", () => {
    stubBackend();
    render(<NegotiateView stage={null} vendorId="V002" />);
    expect(screen.getByRole("tab", { name: "Call review" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Live call" }));
    expect(screen.getByTestId("live-call")).toBeInTheDocument();
  });
});
