"use client";

import { ArrowRight, XCircle } from "lucide-react";
import Link from "next/link";
import { BackendBanner } from "@/components/BackendBanner";
import { Chip, Tag } from "@/components/Chip";
import { ImpactTeam } from "@/components/ImpactTeam";
import { Skeleton } from "@/components/Skeleton";
import { fetchVendors, type VendorListItem } from "@/lib/api";
import { fetchTeamImpact } from "@/lib/impact";
import { vendorOutcome } from "@/lib/outcome";
import { fetchLatestRun, fetchRun, screeningFailure } from "@/lib/runs";
import { inrCompact } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { useEffect, useState } from "react";

/** Vendor ids whose latest run failed screening. Best effort: a missing run just means "not failed". */
function useScreeningFailures(ids: string[]): Set<string> {
  const [failed, setFailed] = useState<Set<string>>(new Set());
  const key = ids.join(",");
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    Promise.all(
      key.split(",").map(async (id) => {
        try {
          const latest = await fetchLatestRun(id, controller.signal);
          if (!latest?.run_id) return null;
          const run = await fetchRun(latest.run_id, controller.signal);
          return screeningFailure(run) ? id : null;
        } catch {
          return null;
        }
      }),
    ).then((r) => {
      if (!controller.signal.aborted) setFailed(new Set(r.filter((x): x is string => !!x)));
    });
    return () => controller.abort();
  }, [key]);
  return failed;
}

export function VendorCard({
  v,
  primary,
  screeningFailed = false,
}: {
  v: VendorListItem;
  primary: boolean;
  screeningFailed?: boolean;
}) {
  const c = v.summary.counts;
  const outcome = vendorOutcome(v.summary, screeningFailed);
  return (
    <Link
      href={`/vendors/${v.id}`}
      className={`flex min-h-44 flex-col justify-between rounded-card border bg-surface p-5 transition-colors hover:bg-surface-2 ${
        primary ? "border-accent md:col-span-2" : "border-border"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-xs text-text-dim">{v.id}</div>
          <h2 className={`font-semibold ${primary ? "text-[28px] leading-9" : "text-xl"}`}>
            {v.brand}
          </h2>
          <div className="text-sm text-text-dim">{v.categories.join(" · ")}</div>
        </div>
        {outcome === "failed_screening" ? (
          <Tag tone="bad" title="Screening failed: do not onboard">
            <XCircle size={16} aria-hidden="true" />
            Failed screening
          </Tag>
        ) : (
          <Chip verdict={outcome} />
        )}
      </div>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs text-text-dim">Capital at risk</div>
          <div className={`num font-semibold ${primary ? "text-[36px] leading-10" : "text-[28px] leading-9"}`}>
            {inrCompact(v.summary.capital_at_risk_inr)}
          </div>
          <div className="num text-xs text-text-dim">
            {c.list ?? 0} list {"·"} {c.negotiate ?? 0} negotiate {"·"} {c.reject ?? 0} reject
            {(c.needs_data ?? 0) > 0 ? ` · ${c.needs_data} needs data` : ""} {"·"} {v.sku_count} SKUs
          </div>
        </div>
        {primary ? (
          <span className="inline-flex h-11 items-center gap-1 rounded-card bg-accent px-4 text-sm font-semibold text-bg">
            Start here <ArrowRight size={16} aria-hidden="true" />
          </span>
        ) : (
          <Tag>Open</Tag>
        )}
      </div>
    </Link>
  );
}

function SkeletonCard({ primary }: { primary: boolean }) {
  return (
    <div
      className={`min-h-44 rounded-card border border-border bg-surface p-5 ${primary ? "md:col-span-2" : ""}`}
    >
      <Skeleton className="h-3 w-12" />
      <Skeleton className="mt-2 h-7 w-48" />
      <Skeleton className="mt-2 h-4 w-64" />
      <Skeleton className="mt-8 h-9 w-32" />
    </div>
  );
}

export default function VendorsBoard() {
  const { data, error, loading } = useAsync(fetchVendors, "vendors", { retryMs: 3000 });
  const failedScreen = useScreeningFailures(data?.map((v) => v.id) ?? []);
  const impact = useAsync(fetchTeamImpact, "team-impact");

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-6">
      <header className="mb-6">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xl font-semibold tracking-tight">CategoryOS</div>
          <div className="flex gap-2">
            <Link href="/try" className="inline-flex min-h-11 items-center rounded-card border border-accent/40 px-3 text-sm text-accent hover:bg-surface-2">
              Try your own vendor
            </Link>
            <Link href="/rules" className="inline-flex min-h-11 items-center rounded-card border border-border px-3 text-sm text-text-dim hover:bg-surface-2 hover:text-text">
              Playbook
            </Link>
          </div>
        </div>
        <p className="mt-1 text-sm text-text-dim">
          Vendor applications waiting for a decision. Open one to see the recommendation, move the
          levers and check every number.
        </p>
      </header>

      {error ? (
        <div className="mb-4">
          <BackendBanner error={error} cached={data != null} retrying />
        </div>
      ) : null}

      {impact.data ? <ImpactTeam impact={impact.data} /> : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-busy={loading}>
        {data
          ? data.map((v) => <VendorCard
                key={v.id}
                v={v}
                primary={v.id === "V001"}
                screeningFailed={failedScreen.has(v.id)}
              />)
          : [0, 1, 2, 3].map((i) => <SkeletonCard key={i} primary={i === 0} />)}
      </div>
    </main>
  );
}
