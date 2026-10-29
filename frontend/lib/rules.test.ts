import { describe, expect, it } from "vitest";
import { formatValue, sentences } from "./rules";

describe("sentences", () => {
  it("puts a full stop between cause and fix", () => {
    expect(sentences("The X-Demo-Key header is missing or wrong", "Send X-Demo-Key with the value of DEMO_KEY")).toBe(
      "The X-Demo-Key header is missing or wrong. Send X-Demo-Key with the value of DEMO_KEY.",
    );
  });
  it("keeps existing punctuation and skips empty parts", () => {
    expect(sentences("Nothing changed.", undefined, "Try again?")).toBe("Nothing changed. Try again?");
    expect(sentences(undefined, null)).toBe("");
  });
});

describe("formatValue", () => {
  it("formats numbers with their unit, switches and missing values", () => {
    expect(formatValue(37, "%")).toBe("37 %");
    expect(formatValue(0.123456789)).toBe("0.1235");
    expect(formatValue(true)).toBe("on");
    expect(formatValue(null)).toBe("(none)");
  });
});
