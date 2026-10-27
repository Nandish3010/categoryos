"use client";

import { budgetMessage } from "@/lib/publicLive";
import { ArrowLeft, FileUp, FlaskConical, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, BACKEND_URL, createUpload, fetchUploadOptions, type UploadOptions } from "@/lib/api";
import { buildSample, buildUpload, checkDraft, emptyForm, type AppMode, type TryDraft } from "@/lib/try";
import { useAsync } from "@/lib/useAsync";
import { BackendBanner } from "../BackendBanner";
import { Banner } from "../Banner";
import { Skeleton } from "../Skeleton";

const field = "h-11 w-full rounded-card border border-border bg-bg px-2 text-sm";
const label = "mb-1 block text-xs text-text-dim";
const card = "rounded-card border border-border bg-surface p-4";

const FORM_FIELDS: { key: keyof TryDraft["form"]; text: string; type?: string }[] = [
  { key: "company_name", text: "Company name" },
  { key: "brand_name", text: "Brand" },
  { key: "categories", text: "Categories (comma separated)" },
  { key: "margin_offered_pct", text: "Margin offered (%)", type: "number" },
  { key: "payment_terms_days", text: "Payment terms (days)", type: "number" },
  { key: "moq_units", text: "MOQ (units)", type: "number" },
  { key: "marketing_support_inr", text: "Marketing support (INR)", type: "number" },
  { key: "launch_discount_pct", text: "Launch discount (%)", type: "number" },
];

export function TryPage() {
  const { data: options, error, loading } = useAsync(fetchUploadOptions, "upload-options", { retryMs: 3000 });
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 md:px-6">
      <header className="mb-6">
        <Link href="/" className="inline-flex min-h-11 items-center gap-1 text-sm text-text-dim hover:text-text">
          <ArrowLeft size={16} aria-hidden="true" /> Vendors
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Bring your own vendor</h1>
        <p className="mt-1 text-sm text-text-dim">
          Upload a vendor&apos;s SKU sheet and get the same screening, verdict table, levers and verified numbers as the demo vendors.
          Your vendor lives in a private sandbox and is deleted after 24 hours.
        </p>
      </header>
      {error ? <BackendBanner error={error} cached={options != null} retrying /> : null}
      {options ? <TryForm options={options} /> : loading ? <Skeleton className="h-64 w-full" /> : null}
    </main>
  );
}

export function TryForm({ options }: { options: UploadOptions }) {
  const router = useRouter();
  const [draft, setDraft] = useState<TryDraft>({
    starter: "pet",
    sheet: null,
    appMode: "none",
    appFile: null,
    form: { ...emptyForm },
    docs: [],
  });
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const starter = options.starters.find((s) => s.id === draft.starter) ?? options.starters[0];
  const set = (patch: Partial<TryDraft>) => setDraft((d) => ({ ...d, ...patch }));

  async function send(body: FormData) {
    setBusy(true);
    setFailure(null);
    try {
      const made = await createUpload(body);
      router.push(`/vendors/${made.id}`);
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, { code: "unknown", problem: "The upload failed" }));
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = checkDraft(draft, options.limits);
    setProblems(found);
    if (found.length === 0) void send(buildUpload(draft));
  }

  const modeTone = options.llm_mode === "live" ? "info" : "warn";

  return (
    <form onSubmit={submit} className="space-y-4" aria-busy={busy}>
      <Banner tone={modeTone} title={options.mode_label}>
        {options.llm_mode === "rules_only"
          ? "The rules engine scores every SKU for free. No model is called, so there is no model-written narrative or document reading."
          : options.llm_mode === "mock"
            ? "This server uses a canned stand-in for the model. Verdicts and numbers are still the engine's."
            : options.public_live?.enabled && !options.public_live.exhausted && options.public_live.ip_remaining_usd != null
              ? `Model stages run live on the public budget: about $${options.public_live.ip_remaining_usd.toFixed(2)} left for you today, then rules-only.`
              : `Model stages may run. Without the demo key they stop after about $${options.live_budget_usd.toFixed(2)} of spend per visitor per day.`}
      </Banner>

      {budgetMessage(options.public_live) ? (
        <Banner tone="warn" title={budgetMessage(options.public_live) ?? ""}>
          Uploads still work: the rules engine scores every SKU for free.
        </Banner>
      ) : null}

      <section className={card} aria-labelledby="sample-h">
        <h2 id="sample-h" className="flex items-center gap-2 text-base font-semibold">
          <FlaskConical size={16} aria-hidden="true" /> One click: try a sample
        </h2>
        <p className="mb-3 text-sm text-text-dim">
          Synthetic vendors for other verticals, with a matching playbook and small market-data stubs so they get real verdicts.
          Some categories deliberately have no market data, to show how that is reported.
        </p>
        <div className="flex flex-wrap gap-2">
          {options.starters
            .filter((s) => s.has_sample)
            .map((s) => (
              <button
                key={s.id}
                type="button"
                disabled={busy}
                onClick={() => void send(buildSample(s.id))}
                className="inline-flex min-h-11 items-center rounded-card border border-accent bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-60"
              >
                Use the {s.vertical} sample
              </button>
            ))}
          {options.starters
            .filter((s) => s.has_sample)
            .map((s) => (
              <a
                key={`dl-${s.id}`}
                href={`${BACKEND_URL}/api/uploads/samples/${s.id}/sku_sheet.csv`}
                className="inline-flex min-h-11 items-center rounded-card border border-border px-3 text-sm text-text-dim hover:bg-surface-2 hover:text-text"
              >
                Download the {s.vertical} sheet
              </a>
            ))}
        </div>
      </section>

      <section className={card} aria-labelledby="play-h">
        <h2 id="play-h" className="text-base font-semibold">1. Starter playbook</h2>
        <p className="mb-3 text-sm text-text-dim">Applies to this vendor only. The playbook page is unchanged.</p>
        <div role="radiogroup" aria-label="Starter playbook" className="grid gap-2 md:grid-cols-3">
          {options.starters.map((s) => (
            <label
              key={s.id}
              className={`flex min-h-11 cursor-pointer flex-col rounded-card border p-3 text-sm ${draft.starter === s.id ? "border-accent bg-accent/10" : "border-border"}`}
            >
              <span className="flex items-center gap-2 font-medium">
                <input type="radio" name="starter" value={s.id} checked={draft.starter === s.id} onChange={() => set({ starter: s.id, form: { ...draft.form, vendor_type: "" }, docs: draft.docs.map((d) => ({ ...d, kind: "" })) })} />
                {s.label}
              </span>
              <span className="mt-1 text-xs text-text-dim">
                {s.has_market_data ? "Includes market data" : "No market data: demand and overlap show Needs data"}
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className={card} aria-labelledby="sheet-h">
        <h2 id="sheet-h" className="flex items-center gap-2 text-base font-semibold">
          <FileUp size={16} aria-hidden="true" /> 2. SKU sheet
        </h2>
        <p className="mb-3 text-sm text-text-dim">
          CSV (UTF-8) or XLSX, up to {options.limits.sheet_mb} MB and {options.limits.rows} rows. Needs columns for the SKU code, the
          product name and the MRP; a cost column is optional. Messy headers are fine.
        </p>
        <label htmlFor="sheet" className={label}>SKU sheet</label>
        <input
          id="sheet"
          type="file"
          accept=".csv,.xlsx,text/csv"
          onChange={(e) => set({ sheet: e.target.files?.[0] ?? null })}
          className={`${field} py-2`}
        />
      </section>

      <section className={card} aria-labelledby="app-h">
        <h2 id="app-h" className="text-base font-semibold">3. Application (optional)</h2>
        <p className="mb-3 text-sm text-text-dim">
          Without one, the playbook&apos;s required documents are listed as pending and the proposed terms stay empty.
        </p>
        <div role="radiogroup" aria-label="Application" className="mb-3 flex flex-wrap gap-4 text-sm">
          {(["none", "form", "file"] as AppMode[]).map((m) => (
            <label key={m} className="inline-flex min-h-11 items-center gap-2">
              <input type="radio" name="appmode" checked={draft.appMode === m} onChange={() => set({ appMode: m })} />
              {m === "none" ? "No application" : m === "form" ? "Short form" : "JSON file"}
            </label>
          ))}
        </div>
        {draft.appMode === "file" ? (
          <>
            <label htmlFor="appfile" className={label}>Application JSON</label>
            <input id="appfile" type="file" accept=".json,application/json" onChange={(e) => set({ appFile: e.target.files?.[0] ?? null })} className={`${field} py-2`} />
          </>
        ) : null}
        {draft.appMode === "form" ? (
          <div className="grid gap-3 md:grid-cols-2">
            {FORM_FIELDS.map((f) => (
              <div key={f.key}>
                <label htmlFor={`f-${f.key}`} className={label}>{f.text}</label>
                <input
                  id={`f-${f.key}`}
                  type={f.type ?? "text"}
                  value={draft.form[f.key]}
                  onChange={(e) => set({ form: { ...draft.form, [f.key]: e.target.value } })}
                  className={field}
                />
              </div>
            ))}
            <div>
              <label htmlFor="f-vendor_type" className={label}>Vendor type</label>
              <select id="f-vendor_type" value={draft.form.vendor_type} onChange={(e) => set({ form: { ...draft.form, vendor_type: e.target.value } })} className={field}>
                <option value="">Playbook default</option>
                {Object.entries(starter.vendor_types).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="f-returns" className={label}>Returns policy</label>
              <input id="f-returns" value={draft.form.returns_policy} onChange={(e) => set({ form: { ...draft.form, returns_policy: e.target.value } })} className={field} />
            </div>
          </div>
        ) : null}
      </section>

      <section className={card} aria-labelledby="docs-h">
        <h2 id="docs-h" className="text-base font-semibold">4. Documents (optional)</h2>
        <p className="mb-3 text-sm text-text-dim">
          Up to {options.limits.documents} PNG, JPEG or PDF files of {options.limits.document_mb} MB each, such as a licence certificate.
          {options.llm_mode === "rules_only" ? " In rules-only mode they are stored but not read." : " PDFs are stored but not read; send a page as an image."}
        </p>
        {starter.document_kinds.length === 0 ? (
          <p className="text-sm text-text-dim">This playbook does not read documents.</p>
        ) : (
          <>
            <label htmlFor="docs" className={label}>Add documents</label>
            <input
              id="docs"
              type="file"
              multiple
              accept="image/png,image/jpeg,application/pdf"
              onChange={(e) =>
                set({
                  docs: Array.from(e.target.files ?? []).map((file) => ({ file, kind: starter.document_kinds[0]?.kind ?? "", declares: "" })),
                })
              }
              className={`${field} py-2`}
            />
            <ul className="mt-3 space-y-2">
              {draft.docs.map((d, i) => (
                <li key={`${d.file.name}-${i}`} className="grid gap-2 md:grid-cols-[1fr_1fr_1fr] md:items-end">
                  <span className="truncate text-sm">{d.file.name}</span>
                  <div>
                    <label htmlFor={`k-${i}`} className={label}>What is it</label>
                    <select id={`k-${i}`} value={d.kind} onChange={(e) => set({ docs: draft.docs.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)) })} className={field}>
                      {starter.document_kinds.map((k) => (
                        <option key={k.kind} value={k.kind}>{k.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor={`d-${i}`} className={label}>Declared as (application document)</label>
                    <select id={`d-${i}`} value={d.declares} onChange={(e) => set({ docs: draft.docs.map((x, j) => (j === i ? { ...x, declares: e.target.value } : x)) })} className={field}>
                      <option value="">Not linked</option>
                      {starter.required_documents.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {problems.length > 0 ? (
        <Banner tone="bad" title="Fix these before uploading">
          <ul className="list-disc pl-4">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {failure ? (
        failure.unreachable ? (
          <BackendBanner error={failure} />
        ) : (
          <Banner tone="bad" title={failure.body.problem}>
            {[failure.body.cause, failure.body.fix].filter(Boolean).join(" ")}
          </Banner>
        )
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="inline-flex min-h-11 items-center gap-2 rounded-card bg-accent px-5 text-sm font-semibold text-bg disabled:opacity-60"
      >
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : null}
        {busy ? "Scoring…" : "Create vendor and score it"}
      </button>
    </form>
  );
}
