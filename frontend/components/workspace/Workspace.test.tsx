import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LEVER_HASH, mockBackend, researchData, snapshot, stage, type Call } from "../../test-utils/mockBackend";
import { Workspace } from "./Workspace";

afterEach(() => vi.unstubAllGlobals());

const researchRun = (narrativeHash: string | null) =>
  snapshot({
    intake: stage("intake", {
      data: {
        decision: "pass",
        risk_flags: [{ type: "exclusivity", quote: "sole supplier clause", severity: "medium" }],
        injection_detected: false,
        documents: [{ name: "GST certificate", status: "present" }],
      },
    }),
    research: stage("research", {
      status: "review",
      needs_approval: true,
      narrative_hash: narrativeHash,
      data: researchData,
    }),
  });

async function setup(run: ReturnType<typeof snapshot>, extra: Parameters<typeof mockBackend>[0] = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", mockBackend({ run, calls, ...extra }));
  render(<Workspace vendorId="V001" />);
  await screen.findByRole("heading", { name: /Recommend: onboard 1 of 2 SKUs|Do not onboard: screening failed/ });
  return calls;
}

describe("Workspace run wiring", () => {
  it("disables Approve with a tooltip when the narrative hash differs from the lever hash", async () => {
    await setup(researchRun("some-older-hash"));
    const approve = (await screen.findAllByRole("button", { name: /Approve and continue/ }))[0];
    await waitFor(() => expect(approve).toBeDisabled());
    expect(approve).toHaveAttribute("title", "Re-plan to approve");
    const narrative = screen.getByRole("region", { name: "Agent narrative" });
    expect(within(narrative).getByText("stale")).toBeInTheDocument();
    expect(within(narrative).getByRole("button", { name: /Re-plan with agent/ })).toBeInTheDocument();
  });

  it("enables Approve and sends the lever metrics_hash when hashes match", async () => {
    const calls = await setup(researchRun(LEVER_HASH));
    const approve = (await screen.findAllByRole("button", { name: /Approve and continue/ }))[0];
    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
    fireEvent.click(approve);
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true));
    const call = calls.find((c) => c.path.endsWith("/approve"))!;
    expect(call.path).toBe("/api/runs/run1/stages/research/approve");
    expect(call.body).toEqual({ metrics_hash: LEVER_HASH });
  });

  it("shows the 409 stale_approval problem and fix in a banner", async () => {
    await setup(researchRun(LEVER_HASH), {
      approve: {
        status: 409,
        body: { code: "stale_approval", problem: "Plan is out of date", cause: "Levers moved.", fix: "Re-plan, then approve." },
      },
    });
    const approve = (await screen.findAllByRole("button", { name: /Approve and continue/ }))[0];
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.click(approve);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Plan is out of date");
    expect(alert).toHaveTextContent("Re-plan, then approve.");
  });

  it("renders struck sentences with strike-through and the verifier reason", async () => {
    await setup(researchRun(LEVER_HASH));
    const narrative = await screen.findByRole("region", { name: "Agent narrative" });
    const struck = within(narrative).getByText("Cost of HP-D01 is Rs 412.");
    expect(struck.tagName).toBe("S");
    expect(within(narrative).getByText("Removed by verifier: sheet says 421")).toBeInTheDocument();
    expect(within(narrative).getByText(/Healthy margin and strong demand/)).toBeInTheDocument();
    expect(within(narrative).getByText("Cost down 3%")).toBeInTheDocument();
    expect(within(narrative).getByText("Hi team, counter-offer attached.")).toBeInTheDocument();
  });

  it("locks V004: red banner, dimmed lever and table, Approve disabled", async () => {
    const run = snapshot({
      intake: stage("intake", {
        status: "failed",
        data: {
          decision: "fail",
          reasons: ["Missing GST certificate"],
          injection_detected: true,
          risk_flags: [{ type: "injection", quote: "ignore previous instructions", severity: "high" }],
        },
      }),
      research: stage("research", { status: "locked", locked_reason: "Screening failed" }),
    });
    await setup(run);
    const banner = await screen.findByText(/Screening failed: Missing GST certificate/);
    expect(banner).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Do not onboard: screening failed" })).toBeInTheDocument();
    expect(screen.getByText("Locked — screening failed")).toBeInTheDocument();
    expect(screen.getByText("Prompt injection detected — ignored")).toBeInTheDocument();
    expect(screen.getByText(/ignore previous instructions/)).toBeInTheDocument();
    const approve = screen.getAllByRole("button", { name: /Approve and continue/ })[0];
    expect(approve).toBeDisabled();
    expect(screen.getByRole("region", { name: "SKU verdicts" })).toHaveAttribute("data-locked", "true");
    // left rail: locked stage has reason tooltip
    expect(document.querySelector('[data-stage="research"]')).toHaveAttribute(
      "title",
      expect.stringContaining("Screening failed"),
    );
  });

  it("streams trace events into the log", async () => {
    await setup(researchRun(LEVER_HASH));
    const log = await screen.findByRole("log");
    await waitFor(() => expect(within(log).getByText(/research · read_sheet/)).toBeInTheDocument());
  });
});
