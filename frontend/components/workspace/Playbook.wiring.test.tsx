import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sku } from "../../test-utils/mockBackend";
import { recommendation } from "./Workspace";
import { SkuTable } from "./SkuTable";
import { lever } from "../../test-utils/mockBackend";
import { VendorCard } from "@/app/page";

describe("playbook wiring", () => {
  it("recommendation says do not onboard when screening failed", () => {
    expect(recommendation(lever(), true).title).toBe("Do not onboard: screening failed");
    expect(recommendation(lever(), false).title).toMatch(/^Recommend: onboard/);
  });

  it("target cell carries the breakdown tooltip when present", () => {
    const s = { ...sku("A"), target_breakdown: { category_pct: 30, vendor_type_pp: -3, brand_pp: 0, lever_pp: 3 } };
    render(<SkuTable skus={[s]} changed={{}} editing={false} overrides={{}} onOverride={() => {}} />);
    expect(screen.getByTitle(/30% category −3 pp vendor type/)).toBeInTheDocument();
  });

  const item = (counts: Record<string, number>) => ({
    id: "V9", brand: "Acme", company_name: "Acme", categories: ["x"], proposed_terms: {}, sku_count: 4,
    metrics_hash: "h",
    summary: { counts, moq: 1, shortlisted: 1, capital_at_risk_inr: 0, days_of_cover: null, est_monthly_gmv: 0, moq_flag: false },
  });

  it("board shows Failed screening and Reject chips", () => {
    const { unmount } = render(<VendorCard v={item({ negotiate: 2 })} primary={false} screeningFailed />);
    expect(screen.getByText("Failed screening")).toBeInTheDocument();
    unmount();
    render(<VendorCard v={item({ reject: 4 })} primary={false} />);
    expect(screen.getByText("Reject")).toBeInTheDocument();
  });
});
