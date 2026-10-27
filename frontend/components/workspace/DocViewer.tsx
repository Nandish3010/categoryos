"use client";

import { CheckCircle2, CircleHelp, ExternalLink, FileText, XCircle } from "lucide-react";
import { useState } from "react";
import { bboxStyle, isProblem, type ScanDoc, type ScanField, type ScanFinding } from "@/lib/docs";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";

const fieldKey = (f: Pick<ScanField, "name" | "skuCode" | "page">) => `${f.page}:${f.name}:${f.skuCode ?? ""}`;

const STATUS: Record<string, { Icon: typeof CheckCircle2; cls: string; label: string }> = {
  verified: { Icon: CheckCircle2, cls: "text-ok", label: "Verified: the crop re-read agrees" },
  rejected: { Icon: XCircle, cls: "text-bad", label: "Rejected: the two reads disagree" },
  conflict: { Icon: XCircle, cls: "text-bad", label: "The two reads disagree" },
  unverifiable: { Icon: CircleHelp, cls: "text-warn", label: "Unverifiable: read once" },
  low_confidence: { Icon: CircleHelp, cls: "text-warn", label: "Low confidence: not compared" },
  unreadable: { Icon: CircleHelp, cls: "text-warn", label: "Unreadable" },
  read: { Icon: CircleHelp, cls: "text-text-dim", label: "Read, not re-read" },
};

/**
 * Scanned document with its readings drawn on the page. Hover or focus a value, or a finding, in the list and its
 * bounding box lights up on the scan; hover a box and its row lights up. Used by Screen (certificates, price list) and
 * Catalog (the label of one SKU).
 */
export function DocViewer({
  documents,
  findings = [],
  initialDoc,
  initialField,
  title = "Document viewer",
}: {
  documents: ScanDoc[];
  findings?: ScanFinding[];
  initialDoc?: string;
  initialField?: string;
  title?: string;
}) {
  const [file, setFile] = useState(initialDoc ?? documents[0]?.file ?? "");
  const [pageNo, setPageNo] = useState(1);
  const [hover, setHover] = useState<string | null>(null);
  const doc = documents.find((d) => d.file === file) ?? documents[0];
  if (!doc) return null;

  const docFindings = findings.filter((f) => f.doc === doc.file && isProblem(f));
  const flagged = new Set(
    docFindings.filter((f) => f.field).map((f) => fieldKey({ name: f.field as string, skuCode: f.skuCode, page: f.page })),
  );
  const pages = doc.pages.length ? doc.pages : [{ page: 1, file: doc.file, url: doc.url, width: null, height: null }];
  const page = pages.find((p) => p.page === pageNo) ?? pages[0];
  const fields = doc.fields.filter((f) => f.page === page.page);
  const initial = initialField ? fields.find((f) => f.name === initialField) : undefined;
  const active = hover ?? (initial ? fieldKey(initial) : null);
  const activeFinding = docFindings.find((f) => `finding:${f.id}` === active);
  const isPdf = doc.file.toLowerCase().endsWith(".pdf");

  return (
    <section aria-label={title} className="rounded-card border border-border bg-surface" data-testid="doc-viewer">
      <PanelHeader
        title={title}
        right={
          isPdf ? (
            <a href={doc.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              <ExternalLink size={16} aria-hidden="true" />
              Open PDF
            </a>
          ) : null
        }
      />
      {documents.length > 1 ? (
        <div role="tablist" aria-label="Documents" className="flex flex-wrap gap-1 border-b border-border px-3 py-2">
          {documents.map((d) => (
            <button
              key={d.file}
              type="button"
              role="tab"
              aria-selected={d.file === doc.file}
              onClick={() => {
                setFile(d.file);
                setPageNo(1);
                setHover(null);
              }}
              className={`inline-flex h-8 items-center gap-1 rounded-chip border px-2 text-xs ${
                d.file === doc.file ? "border-accent/60 bg-accent/10 text-text" : "border-border text-text-dim hover:bg-surface-2"
              }`}
            >
              <FileText size={16} aria-hidden="true" />
              {d.title}
            </button>
          ))}
        </div>
      ) : null}
      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <div className="flex flex-col gap-2">
          {pages.length > 1 ? (
            <div className="flex gap-1" aria-label="Pages" role="group">
              {pages.map((p) => (
                <button
                  key={p.page}
                  type="button"
                  aria-pressed={p.page === page.page}
                  onClick={() => setPageNo(p.page)}
                  className={`h-8 rounded-chip border px-2 text-xs ${p.page === page.page ? "border-accent/60 bg-accent/10" : "border-border text-text-dim"}`}
                >
                  Page {p.page}
                </button>
              ))}
            </div>
          ) : null}
          <div className="relative overflow-hidden rounded-card border border-border bg-surface-2" data-testid="doc-page">
            {/* Backend-served scan; next/image would need remote host config. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={page.url} alt={`${doc.title}, page ${page.page}`} className="block w-full" />
            {doc.panel?.bbox && doc.panel.page === page.page ? (
              <div
                data-testid="panel-box"
                title={`SAM panel: ${doc.panel.prompt}`}
                className="pointer-events-none absolute border-2 border-dashed border-accent/70"
                style={bboxStyle(doc.panel.bbox)}
              />
            ) : null}
            {fields.map((f) => {
              if (!f.bbox) return null;
              const key = fieldKey(f);
              const on = active === key || (activeFinding?.field === f.name && activeFinding.page === f.page && activeFinding.skuCode === f.skuCode);
              const bad = flagged.has(key);
              return (
                <button
                  type="button"
                  key={key}
                  data-testid="field-box"
                  data-field={f.name}
                  data-active={on}
                  aria-label={`${f.label}: ${f.value}`}
                  onMouseEnter={() => setHover(key)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(key)}
                  onBlur={() => setHover(null)}
                  className={`absolute border ${
                    on
                      ? "border-2 border-accent bg-accent/25"
                      : bad
                        ? "border-bad/80 bg-bad/10"
                        : "border-text-dim/40 bg-transparent hover:border-accent/60"
                  }`}
                  style={bboxStyle(f.bbox)}
                />
              );
            })}
            {activeFinding?.bbox && !fields.some((f) => f.name === activeFinding.field) ? (
              <div className="pointer-events-none absolute border-2 border-accent bg-accent/25" style={bboxStyle(activeFinding.bbox)} />
            ) : null}
          </div>
          {doc.panel ? (
            <p className="text-xs text-text-dim">
              {doc.panel.bbox ? "Dashed box: panel found by " : "Panel not found: "}
              <span className="font-mono">{doc.panel.source}</span> (“{doc.panel.prompt}”)
            </p>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          {doc.error ? <Tag tone="warn">Not used: {doc.error}</Tag> : null}
          {docFindings.length ? (
            <ul className="flex flex-col gap-1" aria-label="Findings">
              {docFindings.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    onMouseEnter={() => setHover(`finding:${f.id}`)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(`finding:${f.id}`)}
                    onBlur={() => setHover(null)}
                    className="flex w-full items-start gap-2 rounded-chip border border-bad/40 bg-bad/10 px-2 py-1.5 text-left text-sm"
                  >
                    <Tag tone={f.severity === "high" ? "bad" : "warn"}>{f.status === "mismatch" ? "Mismatch" : f.status}</Tag>
                    <span className="min-w-0 flex-1">{f.message}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div>
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Read from the page</h4>
            <ul className="flex flex-col divide-y divide-border rounded-card border border-border" aria-label="Readings">
              {fields.map((f) => {
                const key = fieldKey(f);
                const s = STATUS[f.status] ?? STATUS.read;
                const on = active === key;
                return (
                  <li key={key} data-field={f.name} data-active={on} className={on ? "bg-accent/10" : flagged.has(key) ? "bg-bad/10" : ""}>
                    <button
                      type="button"
                      onMouseEnter={() => setHover(key)}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover(key)}
                      onBlur={() => setHover(null)}
                      className="grid w-full grid-cols-[16px_minmax(0,1fr)] items-start gap-2 px-3 py-2 text-left text-sm"
                    >
                      <s.Icon size={16} className={`mt-0.5 ${s.cls}`} aria-label={s.label} />
                      <span className="min-w-0">
                        <span className="text-text-dim">
                          {f.label}
                          {f.skuCode ? ` · ${f.skuCode}` : ""}
                        </span>{" "}
                        <span className="num break-words font-medium">{f.raw}</span>
                        {f.reread && f.reread !== f.raw ? (
                          <span className="block text-xs text-bad">Re-read of the crop says “{f.reread}”</span>
                        ) : f.reread ? (
                          <span className="block text-xs text-text-dim">Re-read of the crop agrees</span>
                        ) : null}
                        {f.reason && f.status !== "verified" ? <span className="block text-xs text-text-dim">{f.reason}</span> : null}
                      </span>
                    </button>
                  </li>
                );
              })}
              {fields.length === 0 ? <li className="px-3 py-2 text-sm text-text-dim">Nothing was read from this page.</li> : null}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
