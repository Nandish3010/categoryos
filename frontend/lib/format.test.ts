import { describe, expect, it } from "vitest";
import { days, groupIndian, inr, inrCompact, inrDelta, pct, pctSigned, pp } from "./format";

describe("format", () => {
  it("groups digits Indian style", () => {
    expect(groupIndian(999)).toBe("999");
    expect(groupIndian(1000)).toBe("1,000");
    expect(groupIndian(199334)).toBe("1,99,334");
    expect(groupIndian(12345678)).toBe("1,23,45,678");
  });

  it("formats rupees with lakh/crore grouping", () => {
    expect(inr(199333.992)).toBe("₹1,99,334");
    expect(inr(0)).toBe("₹0");
    expect(inr(null)).toBe("—");
    expect(inr(-2500)).toBe("−₹2,500");
  });

  it("formats compact rupees", () => {
    expect(inrCompact(199333.992)).toBe("₹1.99L");
    expect(inrCompact(25000000)).toBe("₹2.50Cr");
    expect(inrCompact(45678)).toBe("₹45,678");
  });

  it("formats signed deltas", () => {
    expect(inrDelta(-60000)).toBe("−₹60,000");
    expect(inrDelta(-320000)).toBe("−₹3.2L");
    expect(inrDelta(150000)).toBe("+₹1.5L");
  });

  it("formats percents, days and pp", () => {
    expect(pct(0.3136)).toBe("31.4%");
    expect(pct(null)).toBe("—");
    expect(pctSigned(-0.0323)).toBe("−3.2%");
    expect(days(25.34)).toBe("25 days");
    expect(days(1)).toBe("1 day");
    expect(pp(3)).toBe("+3 pp");
    expect(pp(-2)).toBe("−2 pp");
    expect(pp(0)).toBe("0 pp");
  });
});
