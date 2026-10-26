import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LEVER_HASH, mockBackend, researchData, snapshot, stage } from "../../test-utils/mockBackend";
import { Workspace } from "./Workspace";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const run = (extra = {}) =>
  snapshot({
    intake: stage("intake", { data: { decision: "pass", documents: [{ name: "GST", status: "valid" }], risk_flags: [] } }),
    research: stage("research", {
      status: "review",
      needs_approval: true,
      narrative_hash: LEVER_HASH,
      data: { ...researchData, lever: { target_margin_pct_offset: 3, moq: 400 } },
    }),
    ...extra,
  });

async function setup(r = run()) {
  vi.stubGlobal("fetch", mockBackend({ run: r }));
  render(<Workspace vendorId="V001" />);
  await screen.findByRole("heading", { name: /Recommend: onboard/ });
}

describe("Workspace stage views and lever init", () => {
  it("initialises sliders from the run's lever so a reload is not stale", async () => {
    await setup();
    const margin = screen.getByLabelText("Target margin") as HTMLInputElement;
    await waitFor(() => expect(margin.value).toBe("3"));
    expect((screen.getByLabelText("MOQ") as HTMLInputElement).value).toBe("400");
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
  });

  it("switches the centre panel from the rail and writes ?stage=", async () => {
    await setup(run({ catalog: stage("catalog", { status: "pending" }) }));
    expect(screen.getByRole("tab", { name: "Decision" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(document.querySelector('nav[aria-label="Stages"] [data-stage="catalog"]')!);
    expect(await screen.findByRole("region", { name: "Catalog studio" })).toBeInTheDocument();
    expect(window.location.search).toBe("?stage=catalog");
    fireEvent.click(document.querySelector('nav[aria-label="Stages"] [data-stage="negotiate"]')!);
    expect(await screen.findByRole("tab", { name: "Negotiate" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(document.querySelector('nav[aria-label="Stages"] [data-stage="po"]')!);
    expect(await screen.findByTestId("launch-packet")).toBeInTheDocument();
    fireEvent.click(document.querySelector('nav[aria-label="Stages"] [data-stage="intake"]')!);
    expect(await screen.findByRole("button", { name: /Collapse/ })).toBeInTheDocument();
  });

  it("follows the run into negotiate and shows Approved state after research", async () => {
    vi.stubGlobal(
      "fetch",
      mockBackend({
        run: snapshot({
        intake: stage("intake"),
        research: stage("research", { narrative_hash: LEVER_HASH, data: researchData }),
        shortlist: stage("shortlist"),
        negotiate: stage("negotiate", { status: "running" }),
        }),
      }),
    );
    render(<Workspace vendorId="V001" />);
    await waitFor(() => expect(document.querySelector("main [data-view]")).toHaveAttribute("data-stage", "negotiate"));
    const state = (await screen.findAllByTestId("approved-state"))[0];
    expect(state).toHaveTextContent("Approved ✓");
    expect(state).toHaveTextContent("Negotiating…");
  });
});
