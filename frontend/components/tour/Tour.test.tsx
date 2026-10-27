import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, TOUR_STORAGE_KEY, startTour } from "@/lib/tour";
import { Tour } from "./Tour";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/" }));

beforeEach(() => {
  localStorage.clear();
  push.mockClear();
  window.innerWidth = 1280;
});

describe("Tour", () => {
  it("opens for a first-time visitor with Meera waving, and Skip remembers it", () => {
    render(<Tour />);
    expect(screen.getByTestId("tour")).toBeInTheDocument();
    expect(screen.getByText(`Step 1 of ${TOUR_STEPS.length}`)).toBeInTheDocument();
    expect(screen.getByTestId("meera")).toHaveAttribute("src", "/meera/meera-waving.png");
    fireEvent.click(screen.getByRole("button", { name: "Skip the tour" }));
    expect(screen.queryByTestId("tour")).toBeNull();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe("done");
    expect(screen.getByRole("button", { name: /Take the tour/ })).toBeInTheDocument();
  });

  it("stays closed for a returning visitor and Escape dismisses", () => {
    localStorage.setItem(TOUR_STORAGE_KEY, "done");
    render(<Tour />);
    expect(screen.queryByTestId("tour")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Take the tour/ }));
    expect(screen.getByTestId("tour")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("steps forward and back, navigating to each step, and ends with Meera celebrating", () => {
    render(<Tour />);
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(push).toHaveBeenLastCalledWith("/vendors/V001");
    expect(screen.getByTestId("meera")).toHaveAttribute("src", "/meera/meera-pointing.png");
    fireEvent.click(screen.getByRole("button", { name: /Back/ }));
    expect(screen.getByText(`Step 1 of ${TOUR_STEPS.length}`)).toBeInTheDocument();
    for (let i = 0; i < TOUR_STEPS.length - 1; i++) fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByTestId("meera")).toHaveAttribute("src", "/meera/meera-celebrating.png");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("opens from the board's Judges: start here event", () => {
    localStorage.setItem(TOUR_STORAGE_KEY, "done");
    render(<Tour />);
    act(() => startTour());
    expect(screen.getByTestId("tour")).toBeInTheDocument();
  });

  it("does not auto-open on a narrow screen", () => {
    window.innerWidth = 600;
    render(<Tour />);
    expect(screen.queryByTestId("tour")).toBeNull();
  });
});
