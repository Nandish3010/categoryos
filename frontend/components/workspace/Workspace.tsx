"use client";

import { ArrowRight, Lock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  fetchClaims,
  fetchMode,
  fetchVendor,
  type ApiErrorBody,
  type LeverResponse,
  type Verdict,
} from "@/lib/api";
import { days, inr, inrCompact, inrDelta } from "@/lib/format";
import {
  approveStage,
  isNarrativeStale,
  isRunActive,
  mergeClaims,
  overrideSku,
  readResearch,
  readScreen,
  rejectVendor,
  replanVendor,
  screeningFailure,
  type StageId,
} from "@/lib/runs";
import { leverFromRun } from "@/lib/screen";
import {
  PHASE_STAGE,
  approvalHash,
  defaultStage,
  isStageId,
  phaseOfStage,
  progressOf,
  viewForStage,
} from "@/lib/stages";
import { useAsync } from "@/lib/useAsync";
import { useLever } from "@/lib/useLever";
import { useRun } from "@/lib/useRun";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { Skeleton } from "../Skeleton";
import { Stat } from "../Stat";
import { Tween } from "../Tween";
import { ActionBar } from "./ActionBar";
import { CatalogStudio } from "./CatalogStudio";
import { LaunchPacket } from "./LaunchPacket";
import { ImpactPanel } from "./ImpactPanel";
import { LeverCard } from "./LeverCard";
import { NegotiateView } from "./NegotiateView";
import { Rail } from "./Rail";
import { SandboxBanner } from "./SandboxBanner";
import { VerifierCard } from "./RightPanel";
import { NarrativeCard, RunBar } from "./RunPanels";
import { ScreenCard } from "./ScreenCard";
import { SkuTable } from "./SkuTable";
import { TopBar } from "./TopBar";
import { TracePanel } from "./TracePanel";

type Delta = { from: number; to: number; capital: number };

export function recommendation(
  data: LeverResponse,
  screeningFailed = false,
): { title: string; sub: string } {
  const total = data.skus.length;
  const c = data.summary.counts;
  const list = c.list ?? 0;
  const neg = c.negotiate ?? 0;
  const noun = total === 1 ? "SKU" : "SKUs";
  const title = screeningFailed
    ? "Do not onboard: screening failed"
    : list > 0
      ? `Recommend: onboard ${list} of ${total} ${noun}`
      : neg > 0
        ? `Recommend: negotiate before onboarding (${neg} of ${total} ${noun})`
        : `Recommend: do not onboard (0 of ${total} ${noun})`;
  const sub = `${list} list · ${neg} negotiate · ${c.reject ?? 0} reject${
    (c.needs_data ?? 0) > 0 ? ` · ${c.needs_data} needs data` : ""
  }`;
  return { title, sub };
}

/** Write (or clear) `?stage=` without a navigation; Next syncs native history calls. */
function writeStageParam(stage: StageId | null) {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    if (stage) url.searchParams.set("stage", stage);
    else url.searchParams.delete("stage");
    window.history.replaceState(window.history.state, "", url);
  } catch {
    /* history unavailable (sandboxed iframe): the view still switches */
  }
}

function DecideTabs({ stage, onSelect }: { stage: StageId; onSelect: (s: StageId) => void }) {
  const tabs: { id: StageId; label: string }[] = [
    { id: "research", label: "Decision" },
    { id: "negotiate", label: "Negotiate" },
  ];
  const current = stage === "negotiate" ? "negotiate" : "research";
  return (
    <div role="tablist" aria-label="Decide view" className="flex gap-1 border-b border-border">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={current === t.id}
          onClick={() => onSelect(t.id)}
          className={`-mb-px min-h-11 border-b-2 px-3 text-sm ${
            current === t.id ? "border-accent font-medium text-text" : "border-transparent text-text-dim hover:text-text"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
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
  const [impactOpen, setImpactOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  // ---- Agent run ----
  const runState = useRun(vendorId);
  const { run, runId } = runState;
  const screening = useMemo(() => readScreen(run?.stages.intake), [run]);
  const screenFail = screeningFailure(run);
  const researchStage = run?.stages.research ?? null;
  const research = useMemo(() => readResearch(researchStage), [researchStage]);
  const running = runState.starting || isRunActive(run);
  const mergedClaims = useMemo(() => mergeClaims(claims.data, run), [claims.data, run]);
  const mergedInjected = useMemo(
    () => (injected.data ? mergeClaims(injected.data, run) : null),
    [injected.data, run],
  );
  const whys = useMemo(
    () => Object.fromEntries((research?.rationale ?? []).map((r) => [r.code, r.why])),
    [research],
  );

  // Start the sliders where the run's narrative was written, so a reload does not look stale.
  // Needs the default MOQ first (an MOQ equal to it means "no override").
  const [leverInitFor, setLeverInitFor] = useState<string | null>(null);
  const runLever = leverFromRun(run);
  if (run && runLever && defaultMoq != null && leverInitFor !== run.run_id) {
    setLeverInitFor(run.run_id);
    setOffset(runLever.offset);
    setMoq(runLever.moq === defaultMoq ? null : runLever.moq);
  }
  const leverPending = !!run && !!runLever && leverInitFor !== run.run_id;
  const stale = isNarrativeStale(run, data?.metrics_hash) && !lever.updating && !leverPending;

  // ---- Stage navigation: explicit pick (rail / stepper / ?stage=) or follow the run ----
  const [picked, setPicked] = useState<StageId | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("stage");
    // One-time read of the URL after hydration (cannot be an initial state value: SSR has no URL).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (isStageId(q)) setPicked(q);
  }, []);
  const stage: StageId = picked ?? defaultStage(run);
  const view = viewForStage(stage);
  const selectStage = useCallback((s: StageId | null) => {
    setPicked(s);
    writeStageParam(s);
  }, []);

  const progress = progressOf(run);

  const [replanning, setReplanning] = useState(false);
  const [replanError, setReplanError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<ApiErrorBody | null>(null);

  const errorBody = (e: unknown): ApiErrorBody =>
    e instanceof ApiError ? e.body : { code: "error", problem: e instanceof Error ? e.message : String(e) };

  const replan = async () => {
    if (!runId || !data) return;
    setReplanning(true);
    setReplanError(null);
    setApproveError(null);
    try {
      await replanVendor(vendorId, {
        run_id: runId,
        target_margin_pct_offset: offset,
        moq: moq ?? defaultMoq ?? data.summary.moq,
      });
      await runState.refresh();
    } catch (e) {
      setReplanError(errorBody(e).problem);
    } finally {
      setReplanning(false);
    }
  };

  // Approve targets the stage waiting on a human: research, then catalog, then po.
  const approve = async () => {
    const target = progress.kind === "review" ? progress.stage : "research";
    if (!runId || (target === "research" && !data)) {
      setToast("Run the agents first, then approve their plan.");
      return;
    }
    const hash = approvalHash(run, target, data?.metrics_hash ?? null);
    if (!hash) {
      setToast("Nothing to approve yet.");
      return;
    }
    setApproving(true);
    setApproveError(null);
    try {
      await approveStage(runId, target, hash);
      setToast("Approved.");
      selectStage(null); // follow the run into Negotiate / Catalog / Launch as results arrive
      await runState.refresh();
      runState.resume(); // the next phase streams under a new `done`: reconnect with Last-Event-ID
    } catch (e) {
      setApproveError(errorBody(e));
    } finally {
      setApproving(false);
    }
  };

  const reject = async () => {
    if (!runId) {
      setToast("Run the agents first, then reject with their plan on record.");
      return;
    }
    try {
      await rejectVendor(vendorId, { run_id: runId, reason: "Rejected by reviewer" });
      setToast("Vendor rejected.");
      await runState.refresh();
    } catch (e) {
      setToast(`Couldn't reject: ${errorBody(e).problem}`);
    }
  };

  const override = async (skuKey: string, v: Verdict | null) => {
    setOverrides((o) => {
      const next = { ...o };
      if (v) next[skuKey] = v;
      else delete next[skuKey];
      return next;
    });
    const sku = data?.skus.find((s) => s.sku_key === skuKey);
    if (!runId || !sku) return;
    try {
      await overrideSku(runId, "research", { sku_code: sku.code, verdict: v ?? sku.verdict });
    } catch (e) {
      setToast(`Couldn't save edit: ${errorBody(e).problem}`);
    }
  };

  const brand = vendor.data?.brand_name ?? null;
  const notFound = lever.error instanceof ApiError && lever.error.status === 404 && !data;
  const rec = data ? recommendation(data, !!screenFail) : null;
  const summary = data?.summary;
  const overrideCount = Object.keys(overrides).length;

  const announce = data
    ? `${recommendation(data).title}. Capital at risk ${inrCompact(data.summary.capital_at_risk_inr)}.`
    : "";

  // Only the research approval depends on the sliders (its hash is the lever's metrics hash).
  const researchTarget = progress.kind !== "review" || progress.stage === "research";
  const approveLocked = screenFail
    ? "Locked — screening failed"
    : !researchTarget
      ? null
      : leverPending
        ? "Loading levers…"
        : lever.updating && data && research
          ? "Updating levers…"
          : stale
            ? "Re-plan to approve"
            : null;

  const actionBar = (
    <ActionBar
      editing={editing}
      disabled={!data}
      approving={approving}
      approveLockedReason={approveLocked}
      progress={progress}
      onApprove={approve}
      onToggleEdit={() => setEditing((e) => !e)}
      onReject={reject}
    />
  );

  const catalogApproveLocked = progress.kind === "review" && progress.stage === "catalog" ? null : "Not ready to approve";
  const poApproveLocked = progress.kind === "review" && progress.stage === "po" ? null : "Not ready to approve";

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar
        vendorId={vendorId}
        brand={brand}
        mode={mode.data}
        claims={mergedClaims}
        onToggleDrawer={() => setDrawer((d) => !d)}
        phase={phaseOfStage(stage)}
        onPhase={(p) => selectStage(PHASE_STAGE[p])}
        impact={run?.impact ?? null}
        impactOpen={impactOpen}
        onToggleImpact={() => setImpactOpen((o) => !o)}
      />
      {vendor.data?.sandbox ? <SandboxBanner info={vendor.data.sandbox} vendorId={vendorId} /> : null}
      {impactOpen && run?.impact ? <ImpactPanel impact={run.impact} onClose={() => setImpactOpen(false)} /> : null}

      <div
        className="grid flex-1 grid-cols-1 min-[900px]:grid-cols-[56px_minmax(0,1fr)] min-[1280px]:grid-cols-[240px_minmax(0,1fr)_320px]"
      >
        <Rail stages={run?.stages ?? null} selected={stage} onSelect={(s) => selectStage(s)} />

        <main className="min-w-0 px-4 py-4 pb-28 min-[900px]:pb-4 min-[1280px]:px-6">
          <div className="mx-auto flex max-w-[880px] flex-col gap-4" data-view={view} data-stage={stage}>
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

            <RunBar
              running={running}
              hasRun={!!run}
              unavailable={runState.unavailable}
              onRun={() => {
                selectStage(null);
                void runState.start();
              }}
            />
            {runState.error && !runState.unavailable ? (
              <Banner tone="warn" title="Agent run problem">
                {runState.error instanceof ApiError
                  ? [runState.error.body.problem, runState.error.body.fix].filter(Boolean).join(" ")
                  : runState.error.message}
              </Banner>
            ) : null}

            {screenFail ? (
              <Banner tone="bad" title={`Screening failed: ${screenFail.join("; ")}`}>
                Stages after Intake are locked for this vendor.
              </Banner>
            ) : null}

            {approveError ? (
              <Banner tone="bad" title={approveError.problem}>
                {[approveError.cause, approveError.fix].filter(Boolean).join(" ")}
              </Banner>
            ) : null}

            {view === "screen" ? (
              screening ? (
                <ScreenCard screen={screening} forceOpen />
              ) : (
                <section aria-label="Screen" className="rounded-card border border-border bg-surface p-4 text-sm text-text-dim">
                  {running ? "Screening documents…" : "No screening result yet. Run the agents to screen this vendor."}
                </section>
              )
            ) : null}

            {view === "catalog" ? (
              <CatalogStudio
                stage={run?.stages.catalog}
                onApprove={() => void approve()}
                approving={approving}
                approveLockedReason={catalogApproveLocked}
              />
            ) : null}

            {view === "launch" ? (
              <LaunchPacket
                run={run}
                onApprovePo={() => void approve()}
                approving={approving}
                approveLockedReason={poApproveLocked}
              />
            ) : null}

            {view === "decide" ? <DecideTabs stage={stage} onSelect={selectStage} /> : null}

            {view === "decide" && stage === "negotiate" ? <NegotiateView stage={run?.stages.negotiate} vendorId={vendorId} /> : null}

            {view === "decide" && stage !== "negotiate" ? (
              <>
                {screening ? <ScreenCard screen={screening} /> : null}

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

                {research ? (
                  <NarrativeCard
                    research={research}
                    stale={stale}
                    replanning={replanning}
                    replanError={replanError}
                    onReplan={() => void replan()}
                  />
                ) : null}

                <div className="relative flex flex-col gap-4">
                  {screenFail ? (
                    <div
                      role="status"
                      className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-2 py-2 text-sm font-medium text-bad"
                    >
                      <Lock size={16} aria-hidden="true" />
                      Locked — screening failed
                    </div>
                  ) : null}
                  <div
                    aria-disabled={screenFail ? true : undefined}
                    className={screenFail ? "pointer-events-none opacity-40" : ""}
                    inert={screenFail ? true : undefined}
                  >
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
                  </div>

                  <div inert={screenFail ? true : undefined}>
                    <SkuTable
                      skus={data?.skus ?? null}
                      changed={changed}
                      editing={editing}
                      overrides={overrides}
                      onOverride={(k, v) => void override(k, v)}
                      whys={whys}
                      dimmed={!!screenFail}
                    />
                  </div>
                </div>
              </>
            ) : null}

            {/* <1280: right-panel content flows below, or lives in the drawer at 900-1279 */}
          </div>
        </main>

        <aside
          aria-label="Verifier and activity"
          className={`flex flex-col border-l border-border bg-bg
            max-[899px]:border-l-0 max-[899px]:px-4 max-[899px]:pb-28
            min-[900px]:max-[1279px]:fixed min-[900px]:max-[1279px]:inset-y-12 min-[900px]:max-[1279px]:right-0 min-[900px]:max-[1279px]:z-30 min-[900px]:max-[1279px]:w-80 min-[900px]:max-[1279px]:shadow-2xl
            min-[1280px]:sticky min-[1280px]:top-12 min-[1280px]:h-[calc(100vh-48px)] min-[1280px]:self-start
            ${drawer ? "" : "min-[900px]:max-[1279px]:hidden"}`}
        >
          {/* Scroll area (verifier + trace) and a footer that never overlaps it. */}
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 max-[899px]:overflow-visible max-[899px]:p-0">
            <VerifierCard
              base={mergedClaims}
              baseLoading={claims.loading}
              baseError={mergedClaims ? null : claims.error}
              injected={mergedInjected}
              injectedLoading={injected.loading}
              injectOn={injectOn}
              onToggleInject={() => setInjectOn((v) => !v)}
            />
            <TracePanel
              events={runState.events}
              conn={runState.conn}
              running={running}
              hasRun={!!runId}
            />
          </div>
          <div
            data-testid="right-footer"
            className="shrink-0 border-t border-border bg-bg p-4 max-[899px]:hidden"
          >
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
      {mergedClaims && !drawer ? (
        <button
          type="button"
          onClick={() => setDrawer(true)}
          className="fixed bottom-4 right-4 z-20 hidden h-11 items-center gap-2 rounded-card border border-border bg-surface px-3 text-sm min-[900px]:max-[1279px]:inline-flex"
        >
          <span className="num">
            {mergedClaims.verified}/{mergedClaims.total} verified
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
