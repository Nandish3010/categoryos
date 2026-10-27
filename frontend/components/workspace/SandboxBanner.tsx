import Link from "next/link";
import { Banner } from "../Banner";
import { BACKEND_URL, type SandboxInfo } from "@/lib/api";

/** How long a sandbox vendor has left, in words. */
export function ttlText(seconds: number): string {
  if (seconds <= 0) return "expired";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h} h ${m} min left` : `${Math.max(m, 1)} min left`;
}

/** Says, on a vendor you uploaded, what ran it: rules only, a mock, or live models; and what was not scored. */
export function SandboxBanner({ info, vendorId }: { info: SandboxInfo; vendorId: string }) {
  const tone = info.llm_mode === "live" ? "info" : "warn";
  const unread = info.documents.filter((d) => d.status === "not_read");
  const noMarket = info.skus_without_market_data ?? 0;
  return (
    <div className="px-4 pt-3" data-testid="sandbox-banner">
      <Banner
        tone={tone}
        title={`Your upload (${info.starter_label}): ${info.mode_label}`}
        action={
          <a
            href={`${BACKEND_URL}/api/vendors/${vendorId}/export.csv`}
            className="inline-flex min-h-11 items-center rounded-card border border-border px-3 text-sm hover:bg-surface-2"
          >
            Download verdicts (CSV)
          </a>
        }
      >
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {info.llm_mode === "rules_only" ? (
            <li>The numbers and verdicts come from the rules engine. No model was called, so there are no model-written narratives or document readings.</li>
          ) : null}
          {info.llm_mode === "mock" ? (
            <li>This server runs a canned stand-in for the model. Its text is generic and not a real review; every verdict is still the engine&apos;s.</li>
          ) : null}
          <li>
            Screen and Decide run on this vendor; later stages are not part of the sandbox. Kept for {ttlText(info.ttl_remaining_s)}, then deleted.
          </li>
          {noMarket > 0 ? (
            <li>
              {noMarket} SKU(s) show <b>Needs data</b>: their category has no market benchmark or search-demand rows, so demand and
              overlap are not guessed.
            </li>
          ) : null}
          {!info.application_provided ? (
            <li>No application was given: required documents are listed as pending, and the proposed terms are empty.</li>
          ) : null}
          {unread.length > 0 ? <li>{unread.length} document(s) stored but not read: {unread[0].reason}</li> : null}
          {info.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <div className="mt-2">
          <Link href="/try" className="underline">
            Try another vendor
          </Link>
        </div>
      </Banner>
    </div>
  );
}
