"use client";

import { ArrowRight } from "lucide-react";
import type { Acting } from "@/lib/policy";
import { formatValue, sentences, type ChangeLine, type Preview } from "@/lib/rules";
import { Banner } from "../Banner";
import { Tag } from "../Chip";

const TRANSLATOR_LABEL: Record<string, string> = {
  "recorded example": "Recorded example (no model call)",
  "mock translator": "Mock translator (no model call)",
  model: "Muse Spark",
};

/** One changed setting: what it is, the value before and after (from the server's validated playbook) and the stages that read it. */
export function ChangeLines({ lines }: { lines: ChangeLine[] }) {
  return (
    <ul className="flex flex-col divide-y divide-border rounded-card border border-border">
      {lines.map((l) => (
        <li key={l.path} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-3 py-2" data-path={l.path}>
          <div className="min-w-0">
            <div className="text-sm font-medium">{l.label}</div>
            {l.used_in.length ? (
              <div className="mt-1 flex flex-wrap items-center gap-1">
                <span className="text-xs text-text-dim">Used in</span>
                {l.used_in.map((u) => (
                  <Tag key={u}>{u}</Tag>
                ))}
              </div>
            ) : null}
          </div>
          <div className="num flex items-center gap-2 text-sm">
            <span className="text-text-dim" aria-label="Before">
              {formatValue(l.before, l.unit)}
            </span>
            <ArrowRight size={16} aria-hidden="true" className="text-text-dim" />
            <span className="font-semibold" aria-label="After">
              {formatValue(l.after, l.unit)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

const btn = "inline-flex min-h-11 items-center rounded-card px-4 text-sm disabled:cursor-not-allowed disabled:opacity-50";

/**
 * The before/after card for a translated prompt. Nothing is applied until a button is pressed. What the buttons offer follows the
 * server's verdict for the acting member: Apply, Request approval when a limit is exceeded, or the same button disabled with the
 * reason when their role may not do it.
 */
export function ChangePreview({
  preview,
  acting,
  busy,
  onApply,
  onDiscard,
}: {
  preview: Preview;
  acting?: Acting;
  busy: boolean;
  onApply: () => void;
  onDiscard: () => void;
}) {
  if (preview.status === "invalid") {
    const e = preview.error;
    return (
      <Banner tone="bad" title={e?.problem ?? preview.message ?? "This rule is not valid"}>
        {sentences(e?.cause, e?.fix)} Nothing was changed.
      </Banner>
    );
  }
  if (preview.status === "unmapped" || preview.status === "unchanged") {
    return <Banner tone="info" title={preview.message ?? "Nothing to change"} />;
  }
  const outcome = preview.outcome;
  const refused = outcome?.action === "refuse";
  const request = outcome?.action === "request_approval";
  const cannotApply = preview.actor ? !preview.actor.can_apply : acting ? !acting.can_apply : false;
  return (
    <section aria-label="Rule preview" className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Preview: nothing is applied yet</h3>
        <Tag title="Where the translation came from">{TRANSLATOR_LABEL[preview.translator] ?? preview.translator}</Tag>
      </div>
      <p className="text-sm text-text-dim">
        Your words only choose existing settings. These values come from the playbook after checking it against its own rules.
      </p>
      <ChangeLines lines={preview.changes} />
      {request && outcome?.reason ? (
        <Banner tone="warn" title="Over your limit: this becomes a request for the head to approve">
          {outcome.reason}
        </Banner>
      ) : null}
      {refused && outcome?.reason ? (
        <Banner tone="bad" title="You cannot apply this">
          {outcome.reason}
        </Banner>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {request ? (
          <button type="button" disabled={busy} onClick={onApply} className={`${btn} bg-accent font-semibold text-bg`}>
            Request approval
          </button>
        ) : refused ? (
          <button type="button" disabled title={outcome?.reason ?? undefined} className={`${btn} bg-accent font-semibold text-bg`}>
            {cannotApply ? "Request approval" : "Apply"}
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={onApply} className={`${btn} bg-accent font-semibold text-bg`}>
            Apply
          </button>
        )}
        <button type="button" disabled={busy} onClick={onDiscard} className={`${btn} border border-border hover:bg-surface-2`}>
          Discard
        </button>
      </div>
    </section>
  );
}
