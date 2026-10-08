import { describe, expect, it } from "vitest";
import { calculateBid, type BidInputs } from "./BidCalculator";

const baseInputs: BidInputs = {
  quantity: "2",
  unitCost: "100000",
  logistics: "20000",
  labor: "10000",
  taxes: "5000",
  banking: "3000",
  overhead: "7000",
  riskReserve: "5000",
  minimumMargin: "5",
  targetMargin: "15",
  marketReference: "",
  specificationConfirmed: false,
  supplierPriceConfirmed: false,
  logisticsConfirmed: false,
  taxesConfirmed: false,
};

describe("calculateBid", () => {
  it("includes quantity and every declared cost in the recommendation", () => {
    const result = calculateBid(baseInputs, 400_000);

    expect(result.productCost).toBe(200_000);
    expect(result.totalCost).toBe(250_000);
    expect(result.minimumSafePrice).toBeCloseTo(263_157.89, 2);
    expect(result.targetPrice).toBeCloseTo(294_117.65, 2);
    expect(result.recommendedPrice).toBeCloseTo(294_117.65, 2);
    expect(result.expectedMarginPct).toBeCloseTo(15, 5);
    expect(result.viable).toBe(true);
  });

  it("does not recommend bidding when the ceiling is below the safe price", () => {
    const result = calculateBid(baseInputs, 260_000);

    expect(result.viable).toBe(false);
    expect(result.recommendedPrice).toBeNull();
    expect(result.expectedProfit).toBeNull();
  });

  it("uses the target price when the official budget is missing", () => {
    const result = calculateBid(baseInputs, 0);

    expect(result.viable).toBe(true);
    expect(result.recommendedPrice).toBeCloseTo(result.targetPrice, 5);
  });

  it("respects a verified public market ceiling", () => {
    const result = calculateBid({ ...baseInputs, marketReference: "280000" }, 400_000);

    expect(result.viable).toBe(true);
    expect(result.recommendedPrice).toBe(280_000);
    expect(result.expectedProfit).toBe(30_000);
  });
});
