"use client";

import { useEffect, useState } from "react";
import { ApiError, type ApiErrorBody } from "@/lib/api";
import type { Acting, PolicyResponse } from "@/lib/policy";
import { actOnChange, discardChange, fetchExamples, proposeRule, type Change, type Example, sentences, type Preview } from "@/lib/rules";
import { Banner } from "../Banner";
import { ChangePreview } from "./ChangePreview";

/**
 * "Write a rule": a plain-English sentence becomes a preview of structured playbook changes. The sentence is never stored as a rule;
 * it only picks existing settings and values, which the server validates and checks against the acting member's role.
 */
export function WriteRule({
  acting,
  disabled,
  onApplied,
  onLogged,
}: {
  acting?: Acting;
  disabled: boolean;
  onApplied: (r: PolicyResponse & { change: Change }) => void;
  onLogged: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [examples, setExamples] = useState<Example[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  useEffect(() => {
    let live = true;
    fetchExamples()
      .then((r) => live && setExamples(Array.isArray(r?.examples) ? r.examples : []))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const fail = (e: unknown) =>
    setError(e instanceof ApiError ? e.body : { code: "unknown", problem: e instanceof Error ? e.message : "Something went wrong" });

  const run = async (text: string) => {
    if (busy || text.trim().length < 3) return;
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await proposeRule(text.trim()));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview?.id || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await actOnChange(preview.id, "apply");
      setPreview(null);
      setPrompt("");
      onApplied(r);
    } catch (e) {
      fail(e);
      onLogged(); // a refused attempt is in the log too
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    const id = preview?.id;
    setPreview(null);
    if (id) await discardChange(id).catch(() => undefined);
  };

  return (
    <section aria-label="Write a rule" className="mb-4 rounded-card border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">Write a rule</h2>
      <p className="mt-1 text-sm text-text-dim">
        Say it in plain English. It is turned into changes to existing playbook settings that you review before anything is applied.
      </p>
      <div className="mt-3 flex flex-col gap-2 md:flex-row">
        <textarea
          aria-label="Describe a rule"
          rows={2}
          maxLength={500}
          value={prompt}
          disabled={disabled || busy}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="For example: raise the target margin on treats by 2 points"
          className="min-h-11 w-full flex-1 rounded-card border border-border bg-surface-2 px-3 py-2 text-sm text-text disabled:opacity-60"
        />
        <button
          type="button"
          disabled={disabled || busy || prompt.trim().length < 3}
          onClick={() => run(prompt)}
          className="inline-flex min-h-11 items-center justify-center rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-50"
        >
          {busy && !preview ? "Reading…" : "Preview rule"}
        </button>
      </div>
      {examples.length ? (
        <div className="mt-2 flex flex-wrap items-center gap-2" aria-label="Example rules">
          <span className="text-xs text-text-dim">Try</span>
          {examples.map((ex) => (
            <button
              key={ex.prompt}
              type="button"
              title={ex.note}
              disabled={disabled || busy}
              onClick={() => {
                setPrompt(ex.prompt);
                void run(ex.prompt);
              }}
              className="min-h-8 rounded-chip border border-border px-2 text-left text-xs text-text-dim hover:bg-surface-2 hover:text-text disabled:opacity-50"
            >
              {ex.prompt}
            </button>
          ))}
        </div>
      ) : null}
      {error ? (
        <div className="mt-3">
          <Banner tone="bad" title={error.problem}>
            {sentences(error.cause, error.fix)}
          </Banner>
        </div>
      ) : null}
      {preview ? (
        <div className="mt-3">
          <ChangePreview preview={preview} acting={acting} busy={busy} onApply={apply} onDiscard={discard} />
        </div>
      ) : null}
    </section>
  );
}
