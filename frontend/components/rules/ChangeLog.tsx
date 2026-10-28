"use client";

import { useState } from "react";
import { ApiError, type ApiErrorBody } from "@/lib/api";
import type { PolicyResponse } from "@/lib/policy";
import { actOnChange, fetchChanges, STATUS_LABEL, sentences, type Action, type Change, type ChangeStatus } from "@/lib/rules";
import { useAsync } from "@/lib/useAsync";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { ChangeLines } from "./ChangePreview";

const TONE: Record<ChangeStatus, "ok" | "warn" | "bad" | "neutral" | "accent"> = {
  applied: "ok",
  pending_approval: "warn",
  refused: "bad",
  rejected: "bad",
  undone: "neutral",
  proposed: "neutral",
};

const SOURCE: Record<Change["source"], string> = { prompt: "Written as a rule", form: "Edited in the form", undo: "Undo", reset: "Reset to defaults" };

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function Entry({ c, busy, onAct }: { c: Change; busy: boolean; onAct: (id: string, a: Action) => void }) {
  const allowed = c.allowed;
  return (
    <li className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3" data-status={c.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={TONE[c.status]}>{STATUS_LABEL[c.status]}</Tag>
        <span className="text-sm font-medium">{c.actor.name}</span>
        <Tag>{c.actor.role}</Tag>
        <span className="text-xs text-text-dim">{SOURCE[c.source]}</span>
        <time dateTime={c.at} className="ml-auto text-xs text-text-dim">
          {when(c.decided_at ?? c.at)}
        </time>
      </div>
      {c.prompt ? <blockquote className="border-l-2 border-border pl-3 text-sm italic">{c.prompt}</blockquote> : null}
      {c.diff.length ? <ChangeLines lines={c.diff} /> : null}
      {c.reason ? <p className="text-sm text-text-dim">{c.reason}</p> : null}
      {c.approver ? <p className="text-xs text-text-dim">Decided by {c.approver.name} ({c.approver.role})</p> : null}
      {c.events.filter((e) => e.action.endsWith("_refused")).map((e, i) => (
        <p key={i} className="text-xs text-bad">
          {e.actor.name} tried to {e.action.replace("_refused", "")} this: {e.reason}
        </p>
      ))}
      {allowed && (allowed.approve || allowed.reject || allowed.undo) ? (
        <div className="flex flex-wrap gap-2">
          {allowed.approve ? (
            <button type="button" disabled={busy} onClick={() => onAct(c.id, "approve")} className="min-h-11 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-50">
              Approve
            </button>
          ) : null}
          {allowed.reject ? (
            <button type="button" disabled={busy} onClick={() => onAct(c.id, "reject")} className="min-h-11 rounded-card border border-border px-4 text-sm hover:bg-surface-2 disabled:opacity-50">
              Reject
            </button>
          ) : null}
          {allowed.undo ? (
            <button type="button" disabled={busy} onClick={() => onAct(c.id, "undo")} className="min-h-11 rounded-card border border-border px-4 text-sm hover:bg-surface-2 disabled:opacity-50">
              Undo
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** Every attempt to change the playbook, newest first, refused ones included. Approve, reject and undo show only to who may use them. */
export function ChangeLog({ refreshKey, actingId, onChanged }: { refreshKey: number; actingId: string | null; onChanged: (r?: PolicyResponse) => void }) {
  const { data, error, loading, reload } = useAsync(fetchChanges, `changes-${refreshKey}-${actingId}`);
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState<ApiErrorBody | null>(null);

  const act = async (id: string, a: Action) => {
    setBusy(true);
    setFail(null);
    try {
      onChanged(await actOnChange(id, a));
    } catch (e) {
      setFail(e instanceof ApiError ? e.body : { code: "unknown", problem: e instanceof Error ? e.message : "Something went wrong" });
      reload();
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) return <Banner tone="bad" title="The change log could not be loaded">{error.message}</Banner>;
  if (loading && !data) return <p className="text-sm text-text-dim">Loading the change log…</p>;
  const changes = data?.changes ?? [];
  return (
    <section aria-label="Change log" className="flex flex-col gap-3">
      {fail ? (
        <Banner tone="bad" title={fail.problem}>
          {sentences(fail.cause, fail.fix)}
        </Banner>
      ) : null}
      {changes.length === 0 ? (
        <p className="rounded-card border border-border bg-surface p-4 text-sm text-text-dim">
          No changes yet. Every edit to the playbook, written as a rule or made in the form, is logged here, and so is every attempt that was refused.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {changes.map((c) => (
            <Entry key={c.id} c={c} busy={busy} onAct={act} />
          ))}
        </ul>
      )}
    </section>
  );
}
