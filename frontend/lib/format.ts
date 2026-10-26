const MINUS = "−";

/** Group digits Indian style: 1234567 -> "12,34,567". */
export function groupIndian(n: number): string {
  const digits = Math.round(Math.abs(n)).toString();
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  const rest = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${rest},${last3}`;
}

/** Full rupee amount, e.g. "₹1,99,334". */
export function inr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = Math.round(n) < 0 ? MINUS : "";
  return `${sign}₹${groupIndian(n)}`;
}

/** Compact rupee amount: "₹1.99L", "₹2.4Cr", below a lakh falls back to full grouping. */
export function inrCompact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 && abs >= 50 ? MINUS : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
  return `${sign}₹${groupIndian(abs)}`;
}

/** Signed compact delta, e.g. "+₹0.6L" / "−₹0.6L" (one decimal for readability). */
export function inrDelta(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? MINUS : "+";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)}L`;
  return `${sign}₹${groupIndian(abs)}`;
}

/** Fraction to percent: 0.3136 -> "31.4%". */
export function pct(fraction: number | null | undefined, digits = 1): string {
  if (fraction == null || Number.isNaN(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** Signed percent for gaps: -0.0323 -> "−3.2%". */
export function pctSigned(fraction: number | null | undefined, digits = 1): string {
  if (fraction == null || Number.isNaN(fraction)) return "—";
  const v = fraction * 100;
  const sign = v < 0 ? MINUS : v > 0 ? "+" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

/** Days of cover: 25.34 -> "25 days", 1 -> "1 day". */
export function days(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const r = Math.round(n);
  return `${groupIndian(r)} ${r === 1 ? "day" : "days"}`;
}

/** Percentage points offset: 3 -> "+3 pp", -2 -> "−2 pp", 0 -> "0 pp". */
export function pp(n: number): string {
  if (n === 0) return "0 pp";
  return `${n < 0 ? MINUS : "+"}${Math.abs(n)} pp`;
}
