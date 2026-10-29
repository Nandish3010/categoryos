"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, type ApiErrorBody } from "@/lib/api";
import { invalidateLeverBounds } from "@/lib/leverPolicy";
import {
  SECTIONS,
  diffPolicy,
  fetchPolicy,
  resetPolicy,
  savePolicy,
  setPath,
  touches,
  type PolicyResponse,
} from "@/lib/policy";
import { sentences } from "@/lib/rules";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { ActingAs } from "./ActingAs";
import { ChangeLog } from "./ChangeLog";
import { Node, type Ctx } from "./fields";
import { WriteRule } from "./WriteRule";

export const SAVED_TOAST = "Playbook saved — new runs and the lever use these rules";
export const PENDING_TOAST = "Sent to the head for approval — nothing changed yet";
export const READ_ONLY_TEXT = "Public demo: the playbook is read-only. Run locally to edit.";

type SectionId = (typeof SECTIONS)[number]["id"];
type FieldError = { path: string | null; body: ApiErrorBody };

function taxonomyNames(draft: Record<string, unknown>): string[] {
  const cats = (draft.taxonomy as { categories?: unknown } | undefined)?.categories;
  return Array.isArray(cats)
    ? cats.map((c) => (c as { name?: unknown })?.name).filter((n): n is string => typeof n === "string" && !!n)
    : [];
}

function sectionUsedIn(hints: PolicyResponse["schema_hints"], id: string): string[] {
  const out = new Set<string>();
  for (const [p, h] of Object.entries(hints)) {
    if (p === id || p.startsWith(`${id}.`)) h.used_in?.forEach((s) => out.add(s));
  }
  return [...out];
}

export function RulesPage() {
  const { data, error, loading } = useAsync(fetchPolicy, "policy", { retryMs: 3000 });
  return <RulesEditor initial={data} error={error} loading={loading} />;
}

function RulesEditor({
  initial,
  error,
  loading,
}: {
  initial: PolicyResponse | null;
  error: Error | null;
  loading: boolean;
}) {
  // Adopt the first load during render (no effect): later loads never clobber unsaved edits.
  const [server, setServer] = useState<PolicyResponse | null>(initial);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(
    initial ? structuredClone(initial.policy) : null,
  );
  if (initial && !server) {
    setServer(initial);
    setDraft(structuredClone(initial.policy));
  }
  const [active, setActive] = useState<SectionId>("onboarding");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [tab, setTab] = useState<"playbook" | "log">("playbook");
  const [acting, setActing] = useState<string | null>(null);
  const [logKey, setLogKey] = useState(0);

  const adopt = useCallback((r: PolicyResponse) => {
    setServer(r);
    setDraft(structuredClone(r.policy));
    setErrors([]);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  const { partial, paths } = useMemo(
    () => (server && draft ? diffPolicy(draft, server.policy) : { partial: {}, paths: [] as string[] }),
    [server, draft],
  );

  const hints = useMemo(() => server?.schema_hints ?? {}, [server]);
  const readOnly = server ? server.editable === false : true;

  const ctx: Ctx | null = useMemo(
    () =>
      server && draft
        ? {
            draft,
            defaults: server.defaults,
            hints,
            overridden: server.overridden_paths,
            dirty: paths,
            errors,
            disabled: readOnly || saving,
            categoryNames: taxonomyNames(draft),
            set: (path, value) => {
              setDraft((d) => (d ? setPath(d, path, value) : d));
              setErrors((es) => es.filter((e) => !(e.path && touches(path, [e.path]))));
            },
          }
        : null,
    [server, draft, hints, paths, errors, readOnly, saving],
  );

  const handleError = (e: unknown) => {
    if (e instanceof ApiError) {
      const body = e.body;
      setErrors([{ path: body.path ?? null, body }]);
      const sec = SECTIONS.find((s) => body.path === s.id || body.path?.startsWith(`${s.id}.`));
      if (sec) setActive(sec.id);
      if (body.code === "policy_read_only") setServer((s) => (s ? { ...s, editable: false } : s));
    } else {
      setErrors([{ path: null, body: { code: "unknown", problem: e instanceof Error ? e.message : "Save failed" } }]);
    }
  };

  const onSave = async () => {
    if (!paths.length || saving) return;
    setSaving(true);
    try {
      const r = await savePolicy(partial);
      adopt(r);
      invalidateLeverBounds();
      setToast(r.change?.status === "pending_approval" ? PENDING_TOAST : SAVED_TOAST);
      setLogKey((k) => k + 1);
    } catch (e) {
      handleError(e);
      setLogKey((k) => k + 1); // a refused edit is logged too
    } finally {
      setSaving(false);
    }
  };

  const onResetSection = async (id: string) => {
    setSaving(true);
    try {
      const r = await resetPolicy(id);
      adopt(r);
      invalidateLeverBounds();
      setToast(r.change?.status === "pending_approval" ? PENDING_TOAST : `${SECTIONS.find((s) => s.id === id)?.label ?? id} reset to defaults`);
      setLogKey((k) => k + 1);
    } catch (e) {
      handleError(e);
    } finally {
      setSaving(false);
    }
  };

  const topErrors = errors.filter((e) => !e.path);
  const section = SECTIONS.find((s) => s.id === active)!;
  const sectionValue = draft ? (draft as Record<string, unknown>)[active] : undefined;
  const sectionEdited = !!server && touches(active, server.overridden_paths);

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 pb-28 md:px-6">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
        <Link href="/" className="inline-flex min-h-8 items-center gap-1 text-sm text-text-dim hover:text-text">
          <ArrowLeft size={16} aria-hidden="true" />
          Vendors
        </Link>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">Playbook</h1>
        <p className="mt-1 text-sm text-text-dim">
          Every rule a category manager would tune, in one place. New runs and the lever use these values.{" "}
          Starter playbooks for other verticals:{" "}
          <a
            href="https://github.com/Nandish3010/categoryos/tree/main/config/examples"
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            config/examples
          </a>
          .
        </p>
        </div>
        <ActingAs policy={server?.policy} value={acting} onChange={setActing} />
      </header>

      {error ? (
        <div className="mb-4">
          <BackendBanner error={error} cached={server != null} retrying />
        </div>
      ) : null}
      {server?.scope === "visitor" ? (
        <div className="mb-4">
          <Banner tone="info" title="Public demo: your changes go to your own sandbox playbook">
            Nobody else sees them and the recorded runs keep the original playbook. They are kept for about a day.
          </Banner>
        </div>
      ) : null}
      {server && readOnly ? (
        <div className="mb-4">
          <Banner tone="info" title={READ_ONLY_TEXT} />
        </div>
      ) : null}
      {topErrors.map((e, i) => (
        <div key={i} className="mb-4">
          <Banner tone="bad" title={e.body.problem}>
            {sentences(e.body.cause, e.body.fix)}
          </Banner>
        </div>
      ))}

      <div role="tablist" aria-label="Playbook view" className="mb-4 flex gap-1 border-b border-border">
        {(
          [
            ["playbook", "Playbook"],
            ["log", "Change log"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`-mb-px min-h-11 border-b-2 px-3 text-sm ${tab === id ? "border-accent font-medium text-text" : "border-transparent text-text-dim hover:text-text"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "log" ? (
        <ChangeLog
          refreshKey={logKey}
          actingId={acting}
          onChanged={(r) => {
            if (r) {
              adopt(r);
              invalidateLeverBounds();
            }
            setLogKey((k) => k + 1);
          }}
        />
      ) : null}

      {tab === "playbook" && server && !readOnly ? (
        <WriteRule
          acting={server.acting}
          disabled={saving}
          onApplied={(r) => {
            adopt(r);
            invalidateLeverBounds();
            setToast(r.change.status === "pending_approval" ? PENDING_TOAST : SAVED_TOAST);
            setLogKey((k) => k + 1);
          }}
          onLogged={() => setLogKey((k) => k + 1)}
        />
      ) : null}

      {tab === "playbook" ? (
      <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Playbook sections" className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
          {SECTIONS.map((s) => {
            const dirty = touches(s.id, paths);
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setActive(s.id)}
                aria-current={s.id === active ? "page" : undefined}
                className={`flex min-h-11 items-center justify-between gap-2 rounded-card px-3 text-left text-sm whitespace-nowrap ${
                  s.id === active ? "bg-accent/15 font-medium text-accent" : "text-text-dim hover:bg-surface-2 hover:text-text"
                }`}
              >
                {s.label}
                {dirty ? <span className="h-2 w-2 rounded-full bg-warn" aria-label="unsaved changes" /> : null}
              </button>
            );
          })}
        </nav>

        <section aria-label={`${section.label} rules`} className="min-w-0 rounded-card border border-border bg-surface">
          <PanelHeader
            title={section.label}
            right={
              server && !readOnly && sectionEdited ? (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => onResetSection(active)}
                  className="min-h-6 rounded px-1 text-accent hover:underline disabled:opacity-50"
                >
                  Reset section
                </button>
              ) : null
            }
          />
          {ctx && sectionValue !== undefined ? (
            <fieldset disabled={ctx.disabled} className="min-w-0 p-4">
              <legend className="sr-only">{section.label}</legend>
              {!readOnly ? <p className="mb-2 text-xs text-text-dim">Edits made here are checked against your role and logged in the change log.</p> : null}
              {server ? (
                <div className="mb-2 flex flex-wrap items-center gap-1">
                  <span className="text-xs text-text-dim">Used in</span>
                  {sectionUsedIn(hints, active).map((u) => (
                    <Tag key={u}>{u}</Tag>
                  ))}
                </div>
              ) : null}
              {active === "margins" ? (
                <p className="mb-2 rounded-card border border-border bg-surface-2 p-3 text-sm text-text-dim">
                  Effective target = category target + vendor type offset + brand offset + lever offset. The same
                  offsets apply to the minimum margin.
                </p>
              ) : null}
              {typeof sectionValue === "object" && sectionValue !== null && !Array.isArray(sectionValue) ? (
                Object.keys(sectionValue).map((k) => <Node key={k} path={`${active}.${k}`} name={k} ctx={ctx} />)
              ) : (
                <Node path={active} name={active} ctx={ctx} />
              )}
            </fieldset>
          ) : (
            <div className="flex flex-col gap-3 p-4" aria-busy={loading} aria-hidden="true">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}
        </section>
      </div>
      ) : null}

      {tab === "playbook" && !readOnly && paths.length > 0 ? (
        <div
          role="region"
          aria-label="Unsaved changes"
          className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface"
        >
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 md:px-6">
            <span className="num text-sm">
              {paths.length} unsaved {paths.length === 1 ? "change" : "changes"}
            </span>
            <span className="flex items-center gap-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => server && adopt(server)}
                className="inline-flex min-h-11 items-center rounded-card border border-border px-4 text-sm hover:bg-surface-2 disabled:opacity-50"
              >
                Discard
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={onSave}
                className="inline-flex min-h-11 items-center rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </span>
          </div>
        </div>
      ) : null}

      {toast ? (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-card border border-border bg-surface-2 px-4 py-2 text-sm shadow-lg"
        >
          {toast}
        </div>
      ) : null}
    </main>
  );
}
