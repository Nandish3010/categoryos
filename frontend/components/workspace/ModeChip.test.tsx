import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DEMO_KEY_STORAGE } from "@/lib/demoKey";
import { ModeChip } from "./ModeChip";

beforeEach(() => sessionStorage.clear());

describe("ModeChip", () => {
  it("stores the live key in sessionStorage only", () => {
    render(<ModeChip label="Live · $0.10" known />);
    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    fireEvent.change(screen.getByLabelText("Live key"), { target: { value: "abc" } });
    expect(sessionStorage.getItem(DEMO_KEY_STORAGE)).toBe("abc");
    expect(localStorage.getItem(DEMO_KEY_STORAGE)).toBeNull();
  });
});
