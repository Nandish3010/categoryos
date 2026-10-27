"use client";

import { ArrowDown, ArrowUp, Plus, RotateCcw, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { ApiErrorBody } from "@/lib/api";
import {
  deepEqual,
  getPath,
  humanize,
  isPlainObject,
  touches,
  type SchemaHint,
} from "@/lib/policy";
import { Tag } from "../Chip";
import { DataTable, type Column } from "../DataTable";

export type Ctx = {
  draft: Record<string, unknown>;
  defaults: Record<string, unknown>;
  hints: Record<string, SchemaHint>;
  overridden: string[];
  dirty: string[];
  errors: { path: string | null; body: ApiErrorBody }[];
  disabled: boolean;
  /** Category names from the taxonomy, for pickers. */
  categoryNames: string[];
  set: (path: string, value: unknown) => void;
};

const inputCls =
  "h-9 rounded-chip border border-border bg-surface-2 px-2 text-sm text-text disabled:opacity-60";

export function NumberInput({
  value,
  onChange,
  label,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [typed, setText] = useState<string | null>(null);
  // Keep what the user typed ("0.", "-") while it still parses to the value; otherwise show the value.
  const text = typed !== null && typed !== "" && Number(typed) === value ? typed : String(value);
  return (
    <input
      type="number"
      aria-label={label}
      className={`${inputCls} num w-24`}
      value={text}
      min={min}
      max={max}
      step={step ?? "any"}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(n)) onChange(n);
      }}
    />
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <input
      type="checkbox"
      role="switch"
      aria-label={label}
      className="h-5 w-5 cursor-pointer accent-accent disabled:cursor-not-allowed"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

export function ChipList({
  values,
  onChange,
  label,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  label: string;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !values.includes(t)) onChange([...values, t]);
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex h-7 items-center gap-1 rounded-chip border border-border bg-surface-2 pl-2 text-xs"
        >
          <span className="max-w-72 truncate" title={v}>
            {v}
          </span>
          <button
            type="button"
            aria-label={`Remove ${v} from ${label}`}
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="inline-flex h-7 w-6 items-center justify-center text-text-dim hover:text-bad disabled:pointer-events-none"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        aria-label={`Add to ${label}`}
        className={`${inputCls} w-36`}
        placeholder="Add…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
      />
      <button
        type="button"
        onClick={add}
        aria-label={`Add item to ${label}`}
        className="inline-flex h-9 w-9 items-center justify-center rounded-chip border border-border text-text-dim hover:bg-surface-2 disabled:opacity-50"
      >
        <Plus size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export function FieldShell({
  path,
  label,
  help,
  unit,
  usedIn,
  ctx,
  children,
  wide,
}: {
  path: string;
  label: string;
  help?: string;
  unit?: string;
  usedIn?: string[];
  ctx: Ctx;
  children: ReactNode;
  wide?: boolean;
}) {
  const edited = touches(path, ctx.overridden);
  const unsaved = touches(path, ctx.dirty);
  const isDefault = deepEqual(getPath(ctx.draft, path), getPath(ctx.defaults, path));
  const errs = ctx.errors.filter(
    (e) => e.path && (e.path === path || e.path.startsWith(`${path}.`) || path.startsWith(`${e.path}.`)),
  );
  return (
    <div
      data-path={path}
      className={`grid gap-1.5 border-b border-border py-3 last:border-b-0 ${wide ? "" : "md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-6"}`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{label}</span>
          {edited || unsaved ? (
            <span
              className="inline-flex items-center gap-1 text-xs text-warn"
              title={unsaved ? "Unsaved change" : "Differs from the default playbook"}
            >
              <span className="h-2 w-2 rounded-full bg-warn" aria-hidden="true" />
              {unsaved ? "Unsaved" : "Edited"}
            </span>
          ) : null}
          {!isDefault && !ctx.disabled ? (
            <button
              type="button"
              aria-label={`Reset ${label}`}
              onClick={() => ctx.set(path, getPath(ctx.defaults, path))}
              className="inline-flex min-h-6 items-center gap-1 rounded px-1 text-xs text-accent hover:underline"
            >
              <RotateCcw size={16} aria-hidden="true" />
              Reset
            </button>
          ) : null}
          {unit ? <span className="text-xs text-text-dim">{unit}</span> : null}
        </div>
        {help ? <p className="mt-0.5 text-xs text-text-dim">{help}</p> : null}
        {usedIn?.length ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {usedIn.map((s) => (
              <Tag key={s}>{s}</Tag>
            ))}
          </div>
        ) : null}
      </div>
      <div className="min-w-0">
        {children}
        {errs.map((e, i) => (
          <p key={i} role="alert" className="mt-1 text-xs text-bad">
            {e.body.problem}
            {e.body.fix ? ` ${e.body.fix}` : ""}
          </p>
        ))}
      </div>
    </div>
  );
}

// ---------- scopes and taxonomy ----------

/** "all" or a list of category names, picked from the taxonomy when it has any. */
export function ScopePicker({
  value,
  onChange,
  label,
  names,
}: {
  value: unknown;
  onChange: (v: "all" | string[]) => void;
  label: string;
  names: string[];
}) {
  const all = value === "all" || value == null;
  const list = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="flex flex-col gap-1.5">
      <label className="inline-flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4 accent-accent"
          aria-label={`${label} applies to all categories`}
          checked={all}
          onChange={(e) => onChange(e.target.checked ? "all" : [])}
        />
        All categories
      </label>
      {!all ? (
        names.length ? (
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {[...new Set([...names, ...list])].map((n) => (
              <label key={n} className="inline-flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-accent"
                  aria-label={`${label} category ${n}`}
                  checked={list.includes(n)}
                  onChange={(e) => onChange(e.target.checked ? [...list, n] : list.filter((x) => x !== n))}
                />
                {n}
              </label>
            ))}
          </div>
        ) : (
          <ChipList values={list} onChange={onChange} label={label} />
        )
      ) : null}
    </div>
  );
}

function RowButtons({
  index,
  count,
  onMove,
  onRemove,
  name,
}: {
  index: number;
  count: number;
  onMove: (to: number) => void;
  onRemove: () => void;
  name: string;
}) {
  const b = "inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-text disabled:opacity-30";
  return (
    <span className="ml-auto flex items-center">
      <button type="button" className={b} aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => onMove(index - 1)}>
        <ArrowUp size={16} aria-hidden="true" />
      </button>
      <button type="button" className={b} aria-label={`Move ${name} down`} disabled={index === count - 1} onClick={() => onMove(index + 1)}>
        <ArrowDown size={16} aria-hidden="true" />
      </button>
      <button type="button" className={`${b} hover:text-bad`} aria-label={`Remove ${name}`} onClick={onRemove}>
        <X size={16} aria-hidden="true" />
      </button>
    </span>
  );
}

const moveItem = <T,>(arr: T[], from: number, to: number): T[] => {
  const next = [...arr];
  const [x] = next.splice(from, 1);
  next.splice(to, 0, x);
  return next;
};

type TaxCategory = { name: string; patterns: string[]; subcategories: Record<string, string[]> };

/** `{name: string[]}` editor (subcategories, segment values). */
function ListDict({
  value,
  onChange,
  label,
  addLabel,
}: {
  value: Record<string, string[]>;
  onChange: (v: Record<string, string[]>) => void;
  label: string;
  addLabel: string;
}) {
  const [k, setK] = useState("");
  const add = () => {
    const t = k.trim();
    if (t && !(t in value)) onChange({ ...value, [t]: [] });
    setK("");
  };
  return (
    <div className="flex flex-col gap-2">
      {Object.entries(value).map(([name, vals]) => (
        <div key={name} className="grid items-start gap-1 md:grid-cols-[10rem_minmax(0,1fr)_2rem]">
          <span className="pt-1.5 text-sm font-medium">{name}</span>
          <ChipList label={`${label} ${name}`} values={vals ?? []} onChange={(v) => onChange({ ...value, [name]: v })} />
          <button
            type="button"
            aria-label={`Remove ${label} ${name}`}
            onClick={() => {
              const n = { ...value };
              delete n[name];
              onChange(n);
            }}
            className="inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          aria-label={addLabel}
          className={`${inputCls} w-48`}
          placeholder={addLabel}
          value={k}
          onChange={(e) => setK(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" onClick={add} className="inline-flex h-9 items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2">
          <Plus size={16} aria-hidden="true" />
          Add
        </button>
      </div>
    </div>
  );
}

export function TaxonomyCategories({ path, rows, ctx }: { path: string; rows: TaxCategory[]; ctx: Ctx }) {
  const upd = (i: number, patch: Partial<TaxCategory>) =>
    ctx.set(path, rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-text-dim">Order matters: the first category whose patterns match a product wins.</p>
      {rows.map((r, i) => (
        <div key={i} className="rounded-card border border-border p-3">
          <div className="flex items-center gap-2">
            <input
              aria-label={`Category ${i + 1} name`}
              className={`${inputCls} w-56`}
              value={r.name}
              onChange={(e) => upd(i, { name: e.target.value })}
            />
            <RowButtons
              index={i}
              count={rows.length}
              name={r.name || `category ${i + 1}`}
              onMove={(to) => ctx.set(path, moveItem(rows, i, to))}
              onRemove={() => ctx.set(path, rows.filter((_, j) => j !== i))}
            />
          </div>
          <div className="mt-2 text-xs text-text-dim">Match patterns</div>
          <ChipList label={`${r.name} patterns`} values={r.patterns ?? []} onChange={(v) => upd(i, { patterns: v })} />
          <div className="mt-2 text-xs text-text-dim">Subcategories</div>
          <ListDict
            label={`${r.name} subcategory`}
            addLabel={`New ${r.name || "category"} subcategory`}
            value={r.subcategories ?? {}}
            onChange={(v) => upd(i, { subcategories: v })}
          />
        </div>
      ))}
      <button
        type="button"
        onClick={() => ctx.set(path, [...rows, { name: "new category", patterns: [], subcategories: {} }])}
        className="inline-flex h-9 w-fit items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2"
      >
        <Plus size={16} aria-hidden="true" />
        Add category
      </button>
    </div>
  );
}

type Segment = { name: string; values: Record<string, string[]> };

export function Segments({ path, rows, ctx }: { path: string; rows: Segment[]; ctx: Ctx }) {
  const upd = (i: number, patch: Partial<Segment>) =>
    ctx.set(path, rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <div key={i} className="rounded-card border border-border p-3">
          <div className="flex items-center gap-2">
            <input
              aria-label={`Segment ${i + 1} name`}
              className={`${inputCls} w-56`}
              value={r.name}
              onChange={(e) => upd(i, { name: e.target.value })}
            />
            <RowButtons
              index={i}
              count={rows.length}
              name={r.name || `segment ${i + 1}`}
              onMove={(to) => ctx.set(path, moveItem(rows, i, to))}
              onRemove={() => ctx.set(path, rows.filter((_, j) => j !== i))}
            />
          </div>
          <div className="mt-2 text-xs text-text-dim">Values and the words that identify them</div>
          <ListDict
            label={`${r.name} value`}
            addLabel={`New ${r.name || "segment"} value`}
            value={r.values ?? {}}
            onChange={(v) => upd(i, { values: v })}
          />
        </div>
      ))}
      <button
        type="button"
        onClick={() => ctx.set(path, [...rows, { name: "new segment", values: {} }])}
        className="inline-flex h-9 w-fit items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2"
      >
        <Plus size={16} aria-hidden="true" />
        Add segment
      </button>
    </div>
  );
}

type Licence = { document: string; attribute: string; categories: "all" | string[] };

export function LabelLicences({ path, rows, ctx }: { path: string; rows: Licence[]; ctx: Ctx }) {
  const upd = (i: number, patch: Partial<Licence>) =>
    ctx.set(path, rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <div key={i} className="rounded-card border border-border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label={`Licence ${i + 1} document`} className={`${inputCls} w-48`} placeholder="Document" value={r.document} onChange={(e) => upd(i, { document: e.target.value })} />
            <input aria-label={`Licence ${i + 1} attribute`} className={`${inputCls} w-48`} placeholder="Label attribute" value={r.attribute} onChange={(e) => upd(i, { attribute: e.target.value })} />
            <button type="button" aria-label={`Remove licence ${i + 1}`} onClick={() => ctx.set(path, rows.filter((_, j) => j !== i))} className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad">
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="mt-2">
            <ScopePicker label={`Licence ${i + 1}`} names={ctx.categoryNames} value={r.categories} onChange={(v) => upd(i, { categories: v })} />
          </div>
        </div>
      ))}
      <button type="button" onClick={() => ctx.set(path, [...rows, { document: "", attribute: "", categories: "all" }])} className="inline-flex h-9 w-fit items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2">
        <Plus size={16} aria-hidden="true" />
        Add licence rule
      </button>
    </div>
  );
}

/** `{key: text}` editor, e.g. image prompts per category plus "default". */
export function TextDict({ path, value, ctx }: { path: string; value: Record<string, string>; ctx: Ctx }) {
  const [k, setK] = useState("");
  const add = () => {
    const t = k.trim();
    if (t && !(t in value)) ctx.set(path, { ...value, [t]: "" });
    setK("");
  };
  return (
    <div className="flex flex-col gap-2">
      {Object.entries(value).map(([name, text]) => (
        <div key={name} className="grid items-start gap-1 md:grid-cols-[10rem_minmax(0,1fr)_2rem]">
          <span className="pt-1.5 text-sm font-medium">{name}</span>
          <textarea aria-label={`${name} text`} rows={2} className={`${inputCls} h-auto w-full py-1`} value={text} onChange={(e) => ctx.set(path, { ...value, [name]: e.target.value })} />
          {name !== "default" ? (
            <button type="button" aria-label={`Remove ${name}`} onClick={() => { const n = { ...value }; delete n[name]; ctx.set(path, n); }} className="inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad">
              <X size={16} aria-hidden="true" />
            </button>
          ) : <span />}
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input aria-label="New key" list={`${path}-names`} className={`${inputCls} w-48`} placeholder="Category name" value={k} onChange={(e) => setK(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <datalist id={`${path}-names`}>{ctx.categoryNames.map((n) => <option key={n} value={n} />)}</datalist>
        <button type="button" onClick={add} className="inline-flex h-9 items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2">
          <Plus size={16} aria-hidden="true" />
          Add
        </button>
      </div>
    </div>
  );
}

// ---------- tables ----------

function cellFor(
  value: unknown,
  label: string,
  onChange: (v: unknown) => void,
  hint?: SchemaHint,
): ReactNode {
  if (typeof value === "number")
    return (
      <NumberInput
        value={value}
        label={label}
        onChange={onChange}
        min={hint?.min}
        max={hint?.max}
        step={hint?.step}
      />
    );
  if (typeof value === "boolean") return <Toggle checked={value} label={label} onChange={onChange} />;
  if (Array.isArray(value) && value.every((x) => typeof x === "string"))
    return <ChipList values={value as string[]} label={label} onChange={onChange} />;
  return (
    <input
      aria-label={label}
      className={`${inputCls} w-full min-w-32`}
      value={value == null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** Rows keyed by name: margin categories, vendor types, brands. */
export function DictTable({
  path,
  rows,
  addable,
  keyLabel,
  template,
  ctx,
}: {
  path: string;
  rows: Record<string, Record<string, unknown>>;
  addable: boolean;
  keyLabel: string;
  template: Record<string, unknown>;
  ctx: Ctx;
}) {
  const [newKey, setNewKey] = useState("");
  const names = Object.keys(rows);
  const cols = [...new Set(names.flatMap((n) => Object.keys(rows[n] ?? {})))];
  const colKeys = cols.length ? cols : Object.keys(template);
  const update = (name: string, col: string, v: unknown) =>
    ctx.set(path, { ...rows, [name]: { ...rows[name], [col]: v } });

  const columns: Column<string>[] = [
    { key: "name", header: keyLabel, render: (n) => <span className="font-medium">{n}</span> },
    ...colKeys.map<Column<string>>((c) => ({
      key: c,
      header: humanize(c),
      render: (n) =>
        cellFor(
          rows[n]?.[c] ?? template[c],
          `${n} ${humanize(c)}`,
          (v) => update(n, c, v),
          ctx.hints[`${path}.${c}`],
        ),
    })),
  ];
  if (addable)
    columns.push({
      key: "remove",
      header: "",
      render: (n) => (
        <button
          type="button"
          aria-label={`Remove ${n}`}
          onClick={() => {
            const next = { ...rows };
            delete next[n];
            ctx.set(path, next);
          }}
          className="inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad"
        >
          <X size={16} aria-hidden="true" />
        </button>
      ),
    });

  const add = () => {
    const k = newKey.trim();
    if (!k || k in rows) return;
    ctx.set(path, { ...rows, [k]: { ...template } });
    setNewKey("");
  };

  return (
    <div className="rounded-card border border-border">
      {names.length ? (
        <DataTable caption={humanize(path.split(".").pop() ?? path)} columns={columns} rows={names} rowKey={(n) => n} />
      ) : (
        <p className="p-3 text-sm text-text-dim">No rows.</p>
      )}
      {addable ? (
        <div className="flex items-center gap-2 border-t border-border p-2">
          <input
            aria-label={`New ${keyLabel.toLowerCase()}`}
            list={`${path}-names`}
            className={`${inputCls} w-56`}
            placeholder={`New ${keyLabel.toLowerCase()}`}
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <datalist id={`${path}-names`}>
            {(path === "margins.categories" ? ctx.categoryNames.filter((n) => !(n in rows)) : []).map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
          <button
            type="button"
            onClick={add}
            className="inline-flex h-9 items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2 disabled:opacity-50"
          >
            <Plus size={16} aria-hidden="true" />
            Add row
          </button>
        </div>
      ) : null}
    </div>
  );
}

type DocRow = { type: string; blocking: boolean; categories: "all" | string[] };

export function DocumentsTable({ path, rows, ctx }: { path: string; rows: DocRow[]; ctx: Ctx }) {
  const upd = (i: number, patch: Partial<DocRow>) =>
    ctx.set(
      path,
      rows.map((r, j) => (j === i ? { ...r, ...patch } : r)),
    );
  const idx = new Map(rows.map((r, i) => [r, i]));
  const columns: Column<DocRow>[] = [
    {
      key: "type",
      header: "Document",
      render: (r) => (
        <input
          aria-label={`Document type ${r.type}`}
          className={`${inputCls} w-48`}
          value={r.type}
          onChange={(e) => upd(idx.get(r)!, { type: e.target.value })}
        />
      ),
    },
    {
      key: "blocking",
      header: "Blocking",
      render: (r) => (
        <Toggle
          label={`${r.type} blocking`}
          checked={!!r.blocking}
          onChange={(v) => upd(idx.get(r)!, { blocking: v })}
        />
      ),
    },
    {
      key: "categories",
      header: "Categories",
      render: (r) => (
        <ScopePicker
          label={`${r.type}`}
          names={ctx.categoryNames}
          value={r.categories}
          onChange={(v) => upd(idx.get(r)!, { categories: v })}
        />
      ),
    },
    {
      key: "remove",
      header: "",
      render: (r) => (
        <button
          type="button"
          aria-label={`Remove ${r.type}`}
          onClick={() => ctx.set(path, rows.filter((x) => x !== r))}
          className="inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad"
        >
          <X size={16} aria-hidden="true" />
        </button>
      ),
    },
  ];
  return (
    <div className="rounded-card border border-border">
      <DataTable caption="Screening documents" columns={columns} rows={rows} rowKey={(r) => String(idx.get(r))} />
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={() => ctx.set(path, [...rows, { type: "New document", blocking: false, categories: "all" }])}
          className="inline-flex h-9 items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2 disabled:opacity-50"
        >
          <Plus size={16} aria-hidden="true" />
          Add document
        </button>
      </div>
    </div>
  );
}

type ClaimRule = {
  type: string;
  severity: string;
  patterns: string[];
  examples: string[];
  categories?: "all" | string[];
};

export function ClaimRules({ path, rows, ctx }: { path: string; rows: ClaimRule[]; ctx: Ctx }) {
  const upd = (i: number, patch: Partial<ClaimRule>) =>
    ctx.set(
      path,
      rows.map((r, j) => (j === i ? { ...r, ...patch } : r)),
    );
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <div key={i} className="rounded-card border border-border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              aria-label={`Claim rule ${i + 1} type`}
              className={`${inputCls} w-56`}
              value={r.type}
              onChange={(e) => upd(i, { type: e.target.value })}
            />
            <select
              aria-label={`Claim rule ${r.type} severity`}
              className={inputCls}
              value={r.severity}
              onChange={(e) => upd(i, { severity: e.target.value })}
            >
              {["low", "medium", "high"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={`Remove claim rule ${r.type}`}
              onClick={() => ctx.set(path, rows.filter((_, j) => j !== i))}
              className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded text-text-dim hover:text-bad"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="mt-2 text-xs text-text-dim">Applies to</div>
          <ScopePicker label={`${r.type} rule`} names={ctx.categoryNames} value={r.categories ?? "all"} onChange={(v) => upd(i, { categories: v })} />
          <div className="mt-2 text-xs text-text-dim">Patterns (regex)</div>
          <ChipList label={`${r.type} patterns`} values={r.patterns ?? []} onChange={(v) => upd(i, { patterns: v })} />
          <div className="mt-2 text-xs text-text-dim">Examples shown to the model</div>
          <ChipList label={`${r.type} examples`} values={r.examples ?? []} onChange={(v) => upd(i, { examples: v })} />
        </div>
      ))}
      <button
        type="button"
        onClick={() => ctx.set(path, [...rows, { type: "new_rule", severity: "medium", patterns: [], examples: [] }])}
        className="inline-flex h-9 w-fit items-center gap-1 rounded-chip border border-border px-2 text-sm text-text-dim hover:bg-surface-2 disabled:opacity-50"
      >
        <Plus size={16} aria-hidden="true" />
        Add rule
      </button>
    </div>
  );
}

// ---------- tree ----------

const kindOf = (v: unknown, hint?: SchemaHint): SchemaHint["kind"] => {
  const k = hint?.kind;
  if (k === "number" && typeof v === "number") return k;
  if (k === "bool" && typeof v === "boolean") return k;
  if (k === "enum" && typeof v === "string") return k;
  if (k === "text" && typeof v === "string") return k;
  if (k === "string_list" && Array.isArray(v)) return k;
  if (typeof v === "number") return "number";
  if (typeof v === "boolean") return "bool";
  if (typeof v === "string") return "text";
  if (Array.isArray(v) && v.every((x) => typeof x === "string")) return "string_list";
  return "table";
};

const KNOWN_DICTS: Record<string, { addable: boolean; keyLabel: string; template: Record<string, unknown> }> = {
  "margins.categories": { addable: true, keyLabel: "Category", template: { target_pct: 0, min_pct: 0, payment_terms_days: 30 } },
  "onboarding.vendor_types": { addable: true, keyLabel: "Vendor type", template: { label: "", target_offset_pp: 0 } },
  "margins.brands": { addable: true, keyLabel: "Brand", template: { target_offset_pp: 0, note: "" } },
};

export function Node({ path, ctx, name }: { path: string; ctx: Ctx; name: string }) {
  const value = getPath(ctx.draft, path);
  const hint = ctx.hints[path];
  const label = hint?.label ?? humanize(name);
  const shell = (children: ReactNode, wide = false) => (
    <FieldShell path={path} label={label} help={hint?.help} unit={hint?.unit} usedIn={hint?.used_in} ctx={ctx} wide={wide}>
      {children}
    </FieldShell>
  );

  const dict = KNOWN_DICTS[path];
  if (dict && isPlainObject(value))
    return shell(
      <DictTable
        path={path}
        rows={value as Record<string, Record<string, unknown>>}
        ctx={ctx}
        {...dict}
        template={Object.keys(value).length ? { ...dict.template, ...Object.values(value as Record<string, Record<string, unknown>>)[0] } : dict.template}
      />,
      true,
    );
  if (path === "screening.documents" && Array.isArray(value))
    return shell(<DocumentsTable path={path} rows={value as DocRow[]} ctx={ctx} />, true);
  if (path === "screening.claim_rules" && Array.isArray(value))
    return shell(<ClaimRules path={path} rows={value as ClaimRule[]} ctx={ctx} />, true);

  if (path === "taxonomy.categories" && Array.isArray(value))
    return shell(<TaxonomyCategories path={path} rows={value as TaxCategory[]} ctx={ctx} />, true);
  if (path === "taxonomy.segments" && Array.isArray(value))
    return shell(<Segments path={path} rows={value as Segment[]} ctx={ctx} />, true);
  if (path === "catalog.label_licences" && Array.isArray(value))
    return shell(<LabelLicences path={path} rows={value as Licence[]} ctx={ctx} />, true);
  if (path === "catalog.image_prompts" && isPlainObject(value))
    return shell(<TextDict path={path} value={value as Record<string, string>} ctx={ctx} />, true);
  if (path.endsWith("fallback_category") && typeof value === "string" && ctx.categoryNames.length)
    return shell(
      <select aria-label={label} className={inputCls} value={value} onChange={(e) => ctx.set(path, e.target.value)}>
        {[...new Set([...ctx.categoryNames, value])].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>,
    );

  const kind = kindOf(value, hint);
  if (kind === "number")
    return shell(
      <NumberInput
        label={label}
        value={value as number}
        min={hint?.min}
        max={hint?.max}
        step={hint?.step}
        onChange={(v) => ctx.set(path, v)}
      />,
    );
  if (kind === "bool")
    return shell(<Toggle label={label} checked={value as boolean} onChange={(v) => ctx.set(path, v)} />);
  if (kind === "enum")
    return shell(
      <select
        aria-label={label}
        className={inputCls}
        value={value as string}
        onChange={(e) => ctx.set(path, e.target.value)}
      >
        {(hint?.options ?? [value as string]).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>,
    );
  if (kind === "text") {
    const long = (value as string).length > 80 || (value as string).includes("\n");
    return shell(
      long ? (
        <textarea
          aria-label={label}
          rows={Math.min(10, Math.max(3, (value as string).split("\n").length + 1))}
          className={`${inputCls} h-auto w-full py-1 font-mono text-xs`}
          value={value as string}
          onChange={(e) => ctx.set(path, e.target.value)}
        />
      ) : (
        <input
          aria-label={label}
          className={`${inputCls} w-full`}
          value={value as string}
          onChange={(e) => ctx.set(path, e.target.value)}
        />
      ),
      long,
    );
  }
  if (kind === "string_list")
    return shell(<ChipList label={label} values={value as string[]} onChange={(v) => ctx.set(path, v)} />, true);

  if (isPlainObject(value)) {
    // Group: recurse. Hint-less groups still render by value type.
    return (
      <div data-group={path} className="border-b border-border last:border-b-0">
        <div className="pt-3 text-xs font-semibold uppercase tracking-wide text-text-dim">{label}</div>
        {hint?.help ? <p className="text-xs text-text-dim">{hint.help}</p> : null}
        <div className="pl-3">
          {Object.keys(value).map((k) => (
            <Node key={k} path={`${path}.${k}`} name={k} ctx={ctx} />
          ))}
        </div>
      </div>
    );
  }
  // Unknown structure (e.g. list of objects without a dedicated editor): show it, read-only.
  return shell(
    <pre className="max-h-48 overflow-auto rounded-card border border-border bg-surface-2 p-2 font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>,
    true,
  );
}
