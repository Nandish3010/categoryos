/** Where a replayed run came from, as the backend reports it (fixture meta.source). Never call a scripted run live. */

export type Provenance = {
  source: "live" | "mock";
  recorded_at: string | null;
  cost_usd: number;
  degraded: boolean;
};

function fmtDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function provenanceLabel(p: Provenance | null | undefined): string | null {
  if (!p) return null;
  if (p.source !== "live") return "Replay of scripted run";
  const parts = ["Replay of live run"];
  const date = fmtDate(p.recorded_at);
  if (date) parts.push(`recorded ${date}`);
  if (p.cost_usd > 0) parts.push(`$${p.cost_usd.toFixed(2)}`);
  return parts.join(" · ");
}
