"use client";

import { ArrowRight, Check, Flag, Lock, ScanSearch } from "lucide-react";
import { useState } from "react";
import { labelAsDoc, scannedSummary, type LabelRow } from "@/lib/docs";
import type { StageResult } from "@/lib/runs";
import { classificationText, readCatalog, type CatalogSku } from "@/lib/stages";
import { Banner } from "../Banner";
import { Chip, Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { DocViewer } from "./DocViewer";
import type { Verdict } from "@/lib/api";

const SEV_TONE = (s: string) => (/high|critical/i.test(s) ? "bad" : /medium/i.test(s) ? "warn" : "neutral") as "bad" | "warn" | "neutral";
const isVerdict = (v: string): v is Verdict => ["list", "negotiate", "reject", "needs_data"].includes(v);

function Img({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  // Backend-served PNGs (placeholders in mock/replay); next/image would need remote host config.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} loading="lazy" className={`rounded-chip border border-border bg-surface-2 object-contain ${className}`} />;
}

export function ClassificationBadge({ sku }: { sku: CatalogSku }) {
  const c = classificationText(sku);
  const tone = c.verdict === "agree" ? "ok" : c.verdict === "disagree" ? "warn" : "neutral";
  return (
    <span data-testid="classification" className="inline-flex flex-wrap items-center gap-1 text-xs">
      <Tag tone={tone} title={sku.classificationNote ?? undefined}>
        Rules: {c.rules} · Muse Spark Open: {c.model} · {c.verdict}
      </Tag>
    </span>
  );
}

const side = (s: LabelRow["sheet"]) => (s ? <span className={`num ${s.status === "mismatch" ? "font-semibold text-bad" : ""}`}>{s.value}</span> : <span className="text-text-dim">—</span>);

/** The scanned label next to the vendor sheet and the listing copy: where the pack and the paperwork disagree. */
export function LabelVsSheet({ sku }: { sku: CatalogSku }) {
  const [viewer, setViewer] = useState<string | null>(null);
  const lc = sku.labelCheck;
  if (!lc) return null;
  const mismatches = lc.rows.filter((r) => r.status === "mismatch").length;
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3" aria-label={`Label versus sheet for ${sku.code}`} role="group" data-testid="label-vs-sheet">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-text-dim">Label vs sheet</h4>
        <Tag tone={mismatches ? "bad" : "ok"}>{mismatches ? `${mismatches} mismatch${mismatches === 1 ? "" : "es"}` : "label agrees"}</Tag>
        <button
          type="button"
          aria-expanded={viewer !== null}
          onClick={() => setViewer(viewer === null ? "" : null)}
          className="ml-auto inline-flex min-h-8 items-center gap-1 text-xs text-accent hover:underline"
        >
          <ScanSearch size={16} aria-hidden="true" />
          {viewer === null ? "View the label" : "Hide the label"}
        </button>
      </div>
      {lc.error ? <p className="text-xs text-text-dim">Label not used: {lc.error}</p> : null}
      {lc.rows.length ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-dim">
              <th className="py-1 pr-2 font-medium">Field</th>
              <th className="py-1 pr-2 font-medium">Label says</th>
              <th className="py-1 pr-2 font-medium">Sheet says</th>
              <th className="py-1 pr-2 font-medium">Listing says</th>
              <th className="py-1 font-medium">
                <span className="sr-only">Result</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lc.rows.map((r) => (
              <tr key={r.field} data-status={r.status} data-field={r.field} className={r.status === "mismatch" ? "bg-bad/10" : ""}>
                <td className="py-1 pr-2">{r.label}</td>
                <td className="num py-1 pr-2">
                  <button type="button" onClick={() => setViewer(r.field)} className="underline decoration-dotted underline-offset-2" aria-label={`Show ${r.label} on the label`}>
                    {r.labelValue}
                  </button>
                </td>
                <td className="py-1 pr-2">{side(r.sheet)}</td>
                <td className="py-1 pr-2">{side(r.listing)}</td>
                <td className="py-1">
                  {r.unreliable ? <Tag tone="warn">unclear read</Tag> : r.status === "mismatch" ? <Tag tone={r.severity === "high" ? "bad" : "warn"}>Mismatch</Tag> : <Tag tone="ok">Match</Tag>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-text-dim">Nothing on this label could be compared with the sheet.</p>
      )}
      {viewer !== null ? (
        <DocViewer key={viewer} documents={[labelAsDoc(sku.code, lc)]} initialField={viewer || undefined} title={`${sku.code} label`} />
      ) : null}
    </div>
  );
}

function RawSheetRow({ sku }: { sku: CatalogSku }) {
  return (
    <div className="flex flex-col gap-2" aria-label={`Raw sheet row for ${sku.code}`} role="group">
      <h4 className="text-xs font-medium uppercase tracking-wide text-text-dim">Vendor sheet row</h4>
      <dl className="flex flex-col divide-y divide-border rounded-card border border-border bg-surface-2">
        {sku.rawRow.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-3 py-1.5 text-sm">
            <dt className="font-mono text-xs text-text-dim">{k}</dt>
            <dd className="min-w-0 break-words font-mono text-xs">{v === "" ? <span className="text-text-dim">(blank)</span> : v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Listing({ sku }: { sku: CatalogSku }) {
  const main = sku.cutout ?? sku.packshot;
  return (
    <div className="flex flex-col gap-3" aria-label={`Generated listing for ${sku.code}`} role="group">
      <h4 className="text-xs font-medium uppercase tracking-wide text-text-dim">Generated listing</h4>
      <div className="flex flex-wrap gap-2">
        {main ? <Img src={main} alt={`${sku.name} ${sku.cutout ? "cutout" : "packshot"}`} className="h-28 w-28" /> : null}
        {sku.cutout && sku.packshot ? <Img src={sku.packshot} alt={`${sku.name} packshot`} className="h-28 w-28 opacity-80" /> : null}
        {sku.hero && sku.lifestyle ? <Img src={sku.lifestyle} alt={`${sku.name} lifestyle`} className="h-28 w-40" /> : null}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {sku.imageSource !== "live" ? (
          <span className="text-xs text-text-dim" data-testid="image-source">
            {sku.imageSource === "placeholder" ? "placeholder · live image pending" : `${sku.imageSource} images`}
          </span>
        ) : null}
        {sku.cutoutUnavailable ? <Tag tone="warn">cutout unavailable</Tag> : null}
        {sku.hero ? <Tag tone="accent">Hero SKU</Tag> : null}
      </div>
      <div>
        <p className="text-base font-medium">{sku.title || sku.name}</p>
        {sku.bullets.length ? (
          <ul className="mt-1 list-disc pl-5 text-sm">
            {sku.bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : null}
        {sku.description ? <p className="mt-2 text-sm text-text-dim">{sku.description}</p> : null}
      </div>
      {sku.attributes.length ? (
        <ul className="flex flex-wrap gap-1" aria-label="Attributes">
          {sku.attributes.map(([k, v]) => (
            <li key={k}>
              <span className="inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-chip border border-border bg-surface-2 px-2 text-xs">
                <span className="text-text-dim">{k.replace(/_/g, " ")}</span>
                <span className="num">{v}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {sku.flags.length ? (
        <ul className="flex flex-col gap-1" aria-label="Compliance flags">
          {sku.flags.map((f, i) => (
            <li key={`${f.rule}-${i}`} className="flex flex-wrap items-center gap-2 text-sm">
              <Tag tone={SEV_TONE(f.severity)}>
                <Flag size={16} aria-hidden="true" />
                {f.severity}
              </Tag>
              <span className="font-mono text-xs text-text-dim">{f.rule}</span>
              {f.source === "label" ? <Tag tone="accent">from label</Tag> : null}
              <span className="text-text-dim">{f.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-text-dim">No compliance flags.</p>
      )}
    </div>
  );
}

export function SkuCard({ sku }: { sku: CatalogSku }) {
  return (
    <article aria-label={`${sku.code} before and after`} className="rounded-card border border-border bg-surface" data-sku={sku.code}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-text-dim">{sku.code}</span>
          <h3 className="text-sm font-semibold">{sku.name}</h3>
          {isVerdict(sku.verdict) ? <Chip verdict={sku.verdict} /> : null}
        </div>
        <ClassificationBadge sku={sku} />
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,5fr)_auto_minmax(0,7fr)]">
        <RawSheetRow sku={sku} />
        <div className="hidden items-center text-text-dim md:flex" aria-hidden="true">
          <ArrowRight size={16} />
        </div>
        <Listing sku={sku} />
      </div>
      <LabelVsSheet sku={sku} />
    </article>
  );
}

export function CatalogStudio({
  stage,
  onApprove,
  approving,
  approveLockedReason,
}: {
  stage: StageResult | undefined | null;
  onApprove?: () => void;
  approving?: boolean;
  approveLockedReason?: string | null;
}) {
  const data = readCatalog(stage);
  const status = stage?.status ?? "pending";

  if (status === "locked") {
    return (
      <Banner tone="bad" title="Catalog is locked">
        <span className="inline-flex items-center gap-1">
          <Lock size={16} aria-hidden="true" />
          {stage?.locked_reason ?? "An earlier stage has not passed."}
        </span>
      </Banner>
    );
  }
  if (!data) {
    return (
      <section aria-label="Catalog studio" className="rounded-card border border-border bg-surface p-4" aria-busy={status === "running"}>
        <p className="text-sm text-text-dim" role="status">
          {status === "running" ? "Building catalog…" : status === "pending" ? "Catalog is built after you approve the Decide plan and the call is reviewed." : (stage?.error ?? "No sheet loaded.")}
        </p>
        {status === "running" ? (
          <div className="mt-3 flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : null}
      </section>
    );
  }

  const flagged = data.skus.filter((s) => s.flags.length > 0).length;
  const canApprove = status === "review";
  return (
    <div className="flex flex-col gap-4" data-testid="catalog-studio">
      <section aria-label="Catalog summary" className="rounded-card border border-border bg-surface">
        <PanelHeader
          title="Catalog studio"
          right={
            <span className="flex items-center gap-2">
              {data.imageMode === "placeholder" ? <Tag>placeholder images</Tag> : null}
              {status === "done" ? (
                <Tag tone="ok">
                  <Check size={16} aria-hidden="true" />
                  Approved
                </Tag>
              ) : null}
            </span>
          }
        />
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <p className="text-base font-medium">{stage?.summary || `${data.skus.length} listings drafted`}</p>
            <p className="num text-sm text-text-dim">
              {data.skus.length} SKUs · {flagged} with compliance flags ·{" "}
              {data.agreementPct != null ? (
                <span data-testid="agreement">Classifier agreement {data.agreementPct}%</span>
              ) : (
                <span data-testid="agreement">Classified by rules</span>
              )}
            </p>
            {data.scanned && data.scanned.documents.length ? (
              <p className="num text-sm text-text-dim" data-testid="label-summary">
                Labels: {scannedSummary(data.scanned)}
              </p>
            ) : null}
          </div>
          {canApprove || status === "done" ? (
            <button
              type="button"
              disabled={!canApprove || approving || !!approveLockedReason}
              title={approveLockedReason ?? undefined}
              onClick={onApprove}
              className="h-11 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-50"
            >
              {status === "done" ? "Catalog approved" : approving ? "Approving…" : "Approve catalog"}
            </button>
          ) : null}
        </div>
      </section>
      {data.skus.map((s) => (
        <SkuCard key={s.code} sku={s} />
      ))}
    </div>
  );
}
