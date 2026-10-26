"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  fetchClaims,
  fetchMode,
  fetchVendor,
  type LeverResponse,
  type Verdict,
} from "@/lib/api";
import { days, inr, inrCompact, inrDelta } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { useLever } from "@/lib/useLever";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { Tween } from "../Tween";
import { ActionBar } from "./ActionBar";
import { LeverCard } from "./LeverCard";
import { Rail } from "./Rail";
import { SkuTable } from "./SkuTable";
import { TopBar } from "./TopBar";
import { TracePanel, VerifierCard } from "./RightPanel";

type Delta = { from: number; to: number; capital: number };

export function recommendation(data: LeverResponse): { title: string; sub: string } {
  const total = data.skus.length;
  const c = data.summary.counts;
  const list = c.list ?? 0;
  const neg = c.negotiate ?? 0;
  const noun = total === 1 ? "SKU" : "SKUs";
  const title =
    list > 0
      ? `Recommend: onboard ${list} of ${total} ${noun}`
      : neg > 0
        ? `Recommend: negotiate before onboarding (${neg} of ${total} ${noun})`
        : `Recommend: do not onboard (0 of ${total} ${noun})`;
  const sub = `${list} list · ${neg} negotiate · ${c.reject ?? 0} reject${
    (c.needs_data ?? 0) > 0 ? ` · ${c.needs_data} needs data` : ""
  }`;
  return { title, sub };
}

export function Workspace({ vendorId }: { vendorId: string }) {
  const [offset, setOffset] = useState(0);
  const [moq, setMoq] = useState<number | null>(null);
  const [defaultMoq, setDefaultMoq] = useState<number | null>(null);
  const lever = useLever(vendorId, offset, moq);
  const { data } = lever;

  const [seen, setSeen] = useState<LeverResponse | null>(null);
  const [delta, setDelta] = useState<Delta | null>(null);
  const [changed, setChanged] = useState<Record<string, Verdict>>({});

  // Derive "what changed since the last response" during render (no effect needed).
  if (data && data !== seen) {
    setSeen(data);
    if (defaultMoq == null) setDefaultMoq(data.summary.moq);
    if (seen) {
      const prev = new Map(seen.skus.map((s) => [s.sku_key, s.verdict]));
      const diff: Record<string, Verdict> = {};
      for (const s of data.skus) {
        const was = prev.get(s.sku_key);
        if (was && was !== s.verdict) diff[s.sku_key] = was;
      }
      if (Object.keys(diff).length) setChanged((c) => ({ ...c, ...diff }));
      const from = seen.summary.counts.list ?? 0;
      const to = data.summary.counts.list ?? 0;
      const capital = data.summary.capital_at_risk_inr - seen.summary.capital_at_risk_inr;
      if (from !== to || Math.abs(capital) >= 1) setDelta({ from, to, capital });
    }
  }

  useEffect(() => {
    if (!delta) return;
    const t = setTimeout(() => setDelta(null), 4000);
    return () => clearTimeout(t);
  }, [delta]);

  useEffect(() => {
    if (!Object.keys(changed).length) return;
    const t = setTimeout(() => setChanged({}), 3000);
    return () => clearTimeout(t);
  }, [changed]);

  const vendor = useAsync((s) => fetchVendor(vendorId, s), `vendor-${vendorId}`);
  const mode = useAsync(fetchMode, "mode");
  const claims = useAsync((s) => fetchClaims(vendorId, false, s), `claims-${vendorId}`);
  const [injectOn, setInjectOn] = useState(false);
  const injected = useAsync(
    (s) => (injectOn ? fetchClaims(vendorId, true, s) : Promise.resolve(null)),
    `inject-${vendorId}-${injectOn}`,
  );

  const [editing, setEditing] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, Verdict>>({});
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  const brand = vendor.data?.brand_name ?? null;
  const notFound = lever.error instanceof ApiError && lever.error.status === 404 && !data;
  const rec = data ? recommendation(data) : null;
  const summary = data?.summary;
  const overrideCount = Object.keys(overrides).length;

  const announce = data
    ? `${recommendation(data).title}. Capital at risk ${inrCompact(data.summary.capital_at_risk_inr)}.`
    : "";

  const actionBar = (
    <ActionBar
      editing={editing}
      disabled={!data}
      onApprove={() => setToast("Approved. Execute stages ship in the next release, so nothing was sent.")}
      onToggleEdit={() => setEditing((e) => !e)}
      onReject={() => setToast("Vendor rejected (demo: no action taken).")}
    />
  );

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar
        vendorId={vendorId}
        brand={brand}
        mode={mode.data}
        claims={claims.data}
        onToggleDrawer={() => setDrawer((d) => !d)}
      />

      <div
        className="grid flex-1 grid-cols-1 min-[900px]:grid-cols-[56px_minmax(0,1fr)] min-[1280px]:grid-cols-[240px_minmax(0,1fr)_320px]"
      >
        <Rail />

        <main className="min-w-0 px-4 py-4 pb-28 min-[900px]:pb-4 min-[1280px]:px-6">
          <div className="mx-auto flex max-w-[880px] flex-col gap-4">
            <div aria-live="polite" role="status" className="sr-only">
              {announce}
            </div>

            {notFound ? (
              <Banner tone="bad" title={`Vendor ${vendorId} not found`}>
                <Link href="/" className="text-accent hover:underline">
                  Back to vendors
                </Link>
              </Banner>
            ) : lever.error ? (
              <BackendBanner error={lever.error} cached={data != null} />
            ) : null}

            {/* Verdict banner */}
            <section aria-label="Recommendation" className="rounded-card border border-border bg-surface p-4">
              {rec ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h1 className="text-xl font-semibold tracking-tight">{rec.title}</h1>
                    <p className="num text-sm text-text-dim">{rec.sub}</p>
                  </div>
                  {delta ? (
                    <Tag tone="warn">
                      <span className="num inline-flex items-center gap-1">
                        {delta.from} <ArrowRight size={16} aria-hidden="true" /> {delta.to} SKUs{" "}
                        {"·"} {"₹"} at risk{" "}
                        {delta.capital === 0 ? "unchanged" : inrDelta(delta.capital)}
                      </span>
                    </Tag>
                  ) : null}
                </div>
              ) : (
                <div aria-hidden="true">
                  <Skeleton className="h-6 w-80" />
                  <Skeleton className="mt-2 h-4 w-56" />
                </div>
              )}
              {overrideCount > 0 ? (
                <p className="mt-2 text-xs text-text-dim">{overrideCount} verdict(s) edited by human.</p>
              ) : null}
            </section>

            {/* Capital strip */}
            <section
              aria-label="Capital"
              className="grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-4 md:grid-cols-4"
            >
              {summary ? (
                <>
                  <div className="col-span-2 md:col-span-1">
                    <Stat
                      size="lg"
                      label="Capital at risk"
                      value={<Tween value={summary.capital_at_risk_inr} format={inrCompact} />}
                      hint={inr(summary.capital_at_risk_inr)}
                    />
                  </div>
                  <Stat
                    label="Days of cover"
                    value={summary.days_of_cover == null ? "—" : <Tween value={summary.days_of_cover} format={days} />}
                    hint={summary.moq_flag ? <Tag tone="warn">MOQ flag</Tag> : undefined}
                  />
                  <Stat
                    label="Est. monthly GMV"
                    value={<Tween value={summary.est_monthly_gmv} format={inrCompact} />}
                  />
                  <Stat
                    label="SKUs listed"
                    value={
                      <>
                        <Tween value={summary.counts.list ?? 0} format={(n) => String(Math.round(n))} /> of{" "}
                        {data!.skus.length}
                      </>
                    }
                  />
                </>
              ) : (
                <div className="col-span-full flex gap-6" aria-hidden="true">
                  <Skeleton className="h-14 w-40" />
                  <Skeleton className="h-14 w-24" />
                  <Skeleton className="h-14 w-24" />
                  <Skeleton className="h-14 w-24" />
                </div>
              )}
            </section>

            <LeverCard
              offset={offset}
              moq={moq}
              defaultMoq={defaultMoq}
              updating={lever.updating}
              failed={!!lever.error && !!data}
              onOffset={setOffset}
              onMoq={setMoq}
              onResetAll={() => {
                setOffset(0);
                setMoq(null);
              }}
            />

            <SkuTable
              skus={data?.skus ?? null}
              changed={changed}
              editing={editing}
              overrides={overrides}
              onOverride={(k, v) =>
                setOverrides((o) => {
                  const next = { ...o };
                  if (v) next[k] = v;
                  else delete next[k];
                  return next;
                })
              }
            />

            {/* <1280: right-panel content flows below, or lives in the drawer at 900-1279 */}
          </div>
        </main>

        <aside
          aria-label="Verifier and activity"
          className={`flex flex-col border-l border-border bg-bg
            max-[899px]:border-l-0 max-[899px]:px-4 max-[899px]:pb-28
            min-[900px]:max-[1279px]:fixed min-[900px]:max-[1279px]:inset-y-12 min-[900px]:max-[1279px]:right-0 min-[900px]:max-[1279px]:z-30 min-[900px]:max-[1279px]:w-80 min-[900px]:max-[1279px]:shadow-2xl
            ${drawer ? "" : "min-[900px]:max-[1279px]:hidden"}`}
        >
          <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4 max-[899px]:p-0 min-[1280px]:sticky min-[1280px]:top-12 min-[1280px]:max-h-[calc(100vh-48px-148px)] min-[900px]:max-[1279px]:max-h-full">
            <VerifierCard
              base={claims.data}
              baseLoading={claims.loading}
              baseError={claims.error}
              injected={injected.data}
              injectedLoading={injected.loading}
              injectOn={injectOn}
              onToggleInject={() => setInjectOn((v) => !v)}
            />
            <TracePanel />
          </div>
          <div className="border-t border-border p-4 max-[899px]:hidden min-[1280px]:sticky min-[1280px]:bottom-0 min-[1280px]:bg-bg">
            <div className="mb-2 text-xs text-text-dim">
              {mode.data
                ? `${mode.data.mode} mode · $${mode.data.spend_usd.toFixed(2)} of $${mode.data.max_spend_usd.toFixed(2)} spent`
                : "Mode unavailable"}
            </div>
            {actionBar}
          </div>
        </aside>
      </div>

      {/* Pinned verifier summary for 900-1279 (drawer closed) */}
      {claims.data && !drawer ? (
        <button
          type="button"
          onClick={() => setDrawer(true)}
          className="fixed bottom-4 right-4 z-20 hidden h-11 items-center gap-2 rounded-card border border-border bg-surface px-3 text-sm min-[900px]:max-[1279px]:inline-flex"
        >
          <span className="num">
            {claims.data.verified}/{claims.data.total} verified
          </span>
        </button>
      ) : null}

      {/* <900: sticky approve bar */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg p-3 min-[900px]:hidden">
        {actionBar}
      </div>

      {toast ? (
        <div
          role="status"
          className="fixed left-1/2 top-16 z-50 -translate-x-1/2 rounded-card border border-border bg-surface-2 px-4 py-2 text-sm shadow-lg"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}
