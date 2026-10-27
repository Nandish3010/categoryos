import type { RunSnapshot, ScreenData } from "./runs";

const FAIL_RE = /fail|reject|block|deny|denied/i;
const BAD_DOC_RE = /miss|absent|fail|expir|invalid|blocked/i;

/** A scanned document disagrees with what the vendor declared, on a high-severity check. */
export function hasScanAlert(screen: ScreenData): boolean {
  return !!screen.scanned?.findings.some((f) => f.status !== "match" && f.severity === "high");
}

/** The Screen card starts expanded only when something needs a human: a failed screen, an injection or a scan that contradicts the vendor. */
export function screenDefaultOpen(screen: ScreenData): boolean {
  if (screen.injection_detected || hasScanAlert(screen)) return true;
  return screen.decision != null && FAIL_RE.test(screen.decision);
}

/** One-line summary: "Screening passed · 5 documents OK · 4 low flags · 2 follow-ups". */
export function screenSummary(screen: ScreenData): string {
  const failed = screen.decision != null && FAIL_RE.test(screen.decision);
  const parts = [failed ? "Screening failed" : "Screening passed"];
  const total = screen.documents.length;
  if (total) {
    const ok = screen.documents.filter((d) => !d.status || !BAD_DOC_RE.test(d.status)).length;
    parts.push(ok === total ? `${total} document${total === 1 ? "" : "s"} OK` : `${ok} of ${total} documents OK`);
  }
  const n = screen.risk_flags.length;
  if (n) {
    const counts = new Map<string, number>();
    for (const f of screen.risk_flags) counts.set(f.severity, (counts.get(f.severity) ?? 0) + 1);
    parts.push(
      counts.size === 1
        ? `${n} ${[...counts.keys()][0]} flag${n === 1 ? "" : "s"}`
        : `${n} flags (${[...counts].map(([k, v]) => `${v} ${k}`).join(", ")})`,
    );
  }
  const q = screen.followup_questions.length;
  if (q) parts.push(`${q} follow-up${q === 1 ? "" : "s"}`);
  const scan = screen.scanned?.summary.mismatches ?? 0;
  if (scan) parts.push(`${scan} scan mismatch${scan === 1 ? "" : "es"}`);
  if (screen.injection_detected) parts.push("injection ignored");
  return parts.join(" · ");
}

/**
 * Lever values the run's research narrative was written for (`research.data.lever`), so a
 * reload starts the sliders where the narrative is not stale. Null when the run does not say.
 */
export function leverFromRun(run: RunSnapshot | null): { offset: number; moq: number } | null {
  const d = run?.stages.research?.data;
  const lv = d && typeof d === "object" ? (d as Record<string, unknown>).lever : null;
  if (!lv || typeof lv !== "object") return null;
  const { target_margin_pct_offset: offset, moq } = lv as Record<string, unknown>;
  if (typeof offset !== "number" || typeof moq !== "number") return null;
  return { offset, moq };
}
