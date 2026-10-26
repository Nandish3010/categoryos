"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { BackendBanner } from "@/components/BackendBanner";
import { Chip, Tag } from "@/components/Chip";
import { Skeleton } from "@/components/Skeleton";
import { fetchVendors, type Verdict, type VendorListItem } from "@/lib/api";
import { inrCompact } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

function outcome(v: VendorListItem): Verdict {
  const c = v.summary.counts;
  if ((c.list ?? 0) > 0) return "list";
  if ((c.negotiate ?? 0) > 0) return "negotiate";
  if ((c.needs_data ?? 0) > 0) return "needs_data";
  return "reject";
}

function VendorCard({ v, primary }: { v: VendorListItem; primary: boolean }) {
  const c = v.summary.counts;
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
        <Chip verdict={outcome(v)} />
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

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-6">
      <header className="mb-6">
        <div className="text-xl font-semibold tracking-tight">CategoryOS</div>
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-busy={loading}>
        {data
          ? data.map((v) => <VendorCard key={v.id} v={v} primary={v.id === "V001"} />)
          : [0, 1, 2, 3].map((i) => <SkeletonCard key={i} primary={i === 0} />)}
      </div>
    </main>
  );
}
