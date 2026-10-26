"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { SkuMetrics, Verdict } from "@/lib/api";
import { pct, pctSigned } from "@/lib/format";
import { Chip, Tag, VERDICTS } from "../Chip";
import { DataTable, type Column } from "../DataTable";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";

const ORDER: Record<Verdict, number> = { list: 0, negotiate: 1, needs_data: 2, reject: 3 };

export function sortSkus(skus: SkuMetrics[]): SkuMetrics[] {
  return [...skus].sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict]);
}

export function SkuTable({
  skus,
  changed,
  editing,
  overrides,
  onOverride,
  whys,
  dimmed,
}: {
  skus: SkuMetrics[] | null;
  /** sku_key -> verdict it had before the last lever move */
  changed: Record<string, Verdict>;
  editing: boolean;
  overrides: Record<string, Verdict>;
  onOverride: (skuKey: string, v: Verdict | null) => void;
  /** Agent rationale by SKU code, from the run's research stage. */
  whys?: Record<string, string>;
  /** Locked (screening failed): table is shown but inert. */
  dimmed?: boolean;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (!skus) {
    return (
      <section aria-label="SKU verdicts" className="rounded-card border border-border bg-surface">
        <PanelHeader title="SKU verdicts" />
        <div className="flex flex-col gap-2 p-4" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </section>
    );
  }

  const columns: Column<SkuMetrics>[] = [
    {
      key: "sku",
      header: "SKU",
      className: "min-w-48",
      render: (s) => (
        <div className="py-1">
          <div className="flex items-center gap-1.5">
            <span className="font-medium">{s.name}</span>
            {s.cost_source === "inferred" ? (
              <Tag tone="neutral" title="Cost is estimated working capital, not a sourced figure">
                cost inferred
              </Tag>
            ) : null}
          </div>
          <div className="font-mono text-xs text-text-dim">
            {s.code}
            {s.pack ? ` · ${s.pack}` : ""}
          </div>
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      render: (s) => (
        <span className="text-text-dim" title={`${s.category} · ${s.subcategory}`}>
          {s.category ? s.category.charAt(0).toUpperCase() + s.category.slice(1) : ""}
          {s.subcategory ? ` · ${s.subcategory}` : ""}
        </span>
      ),
    },
    { key: "margin", header: "Margin", align: "right", render: (s) => pct(s.margin_pct) },
    { key: "target", header: "Target", align: "right", render: (s) => pct(s.target_pct) },
    {
      key: "gap",
      header: "Price gap",
      align: "right",
      render: (s) => pctSigned(s.price_gap_pct),
    },
    {
      key: "demand",
      header: "Demand",
      align: "right",
      render: (s) => (s.demand_score * 100).toFixed(0),
    },
    {
      key: "overlap",
      header: "Overlap",
      align: "right",
      render: (s) => pct(s.overlap, 0),
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (s) => {
        const was = changed[s.sku_key];
        const override = overrides[s.sku_key];
        const isOpen = !!open[s.sku_key];
        return (
          <div className="flex flex-wrap items-center gap-1.5">
            {editing ? (
              <select
                aria-label={`Verdict for ${s.name}`}
                value={override ?? s.verdict}
                onChange={(e) => {
                  const v = e.target.value as Verdict;
                  onOverride(s.sku_key, v === s.verdict ? null : v);
                }}
                className="h-8 rounded-chip border border-border bg-surface-2 px-1 text-xs"
              >
                {(Object.keys(VERDICTS) as Verdict[]).map((v) => (
                  <option key={v} value={v}>
                    {VERDICTS[v].label}
                  </option>
                ))}
              </select>
            ) : (
              <Chip verdict={override ?? s.verdict} />
            )}
            {override ? <Tag tone="accent">Edited by human</Tag> : null}
            {was && was !== s.verdict ? <Tag tone="warn">was {VERDICTS[was].label}</Tag> : null}
            <button
              type="button"
              aria-expanded={isOpen}
              aria-label={`${isOpen ? "Hide" : "Show"} reasons for ${s.name}`}
              onClick={() => setOpen((o) => ({ ...o, [s.sku_key]: !o[s.sku_key] }))}
              className="inline-flex h-6 w-6 items-center justify-center rounded text-text-dim hover:bg-surface-2"
              title={s.reasons.join("; ")}
            >
              {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <section
      aria-label="SKU verdicts"
      data-locked={dimmed || undefined}
      className={`rounded-card border border-border bg-surface ${dimmed ? "pointer-events-none opacity-50" : ""}`}
    >
      <PanelHeader title="SKU verdicts" right={<span className="num">{skus.length} SKUs</span>} />
      <DataTable
        caption="SKU verdicts with margin, target, price gap, demand and overlap"
        columns={columns}
        rows={sortSkus(skus)}
        rowKey={(s) => s.sku_key}
        rowClass={(s) =>
          `${changed[s.sku_key] && changed[s.sku_key] !== s.verdict ? "flash-amber" : ""} ${
            s.verdict === "reject" ? "text-text-dim" : ""
          }`
        }
        renderExpanded={(s) =>
          open[s.sku_key] ? (
            <ul className="list-disc pl-5 text-sm text-text-dim">
              {whys?.[s.code] ? <li data-agent-why>Agent: {whys[s.code]}</li> : null}
              {s.reasons.length ? s.reasons.map((r) => <li key={r}>{r}</li>) : <li>No reasons recorded.</li>}
              {s.flags.length ? <li>Flags: {s.flags.join(", ")}</li> : null}
            </ul>
          ) : null
        }
      />
    </section>
  );
}
