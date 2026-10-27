import { post, put, request } from "./api";

export type FieldKind = "number" | "bool" | "enum" | "string_list" | "table" | "text";

export type SchemaHint = {
  label?: string;
  help?: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  kind?: FieldKind;
  options?: string[];
  used_in?: string[];
};

export type Json = unknown;
export type PolicyObject = Record<string, Json>;

export type PolicyResponse = {
  policy: PolicyObject;
  defaults: PolicyObject;
  overridden_paths: string[];
  hash: string;
  editable: boolean;
  schema_hints: Record<string, SchemaHint>;
};

export const SECTIONS = [
  { id: "onboarding", label: "Onboarding" },
  { id: "taxonomy", label: "Taxonomy" },
  { id: "screening", label: "Screening" },
  { id: "research", label: "Research" },
  { id: "margins", label: "Margins" },
  { id: "negotiation", label: "Negotiation" },
  { id: "catalog", label: "Catalog" },
  { id: "documents", label: "Documents" },
  { id: "launch", label: "Launch" },
  { id: "po", label: "PO" },
  { id: "levers", label: "Levers" },
  { id: "verifier", label: "Verifier" },
] as const;

export const fetchPolicy = (signal?: AbortSignal) =>
  request<PolicyResponse>("GET", "/api/policy", { signal });
export const savePolicy = (partial: PolicyObject) => put<PolicyResponse>("/api/policy", partial);
export const resetPolicy = (section?: string) =>
  post<PolicyResponse>("/api/policy/reset", section ? { section } : {});

export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => k in b && deepEqual(a[k], b[k]));
  }
  return false;
}

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const k of path.split(".")) {
    if (!isPlainObject(cur)) return undefined;
    cur = cur[k];
  }
  return cur;
}

export function setPath<T extends PolicyObject>(obj: T, path: string, value: unknown): T {
  const keys = path.split(".");
  const walk = (node: unknown, i: number): unknown => {
    const base = isPlainObject(node) ? node : {};
    return { ...base, [keys[i]]: i === keys.length - 1 ? value : walk(base[keys[i]], i + 1) };
  };
  return walk(obj, 0) as T;
}

/**
 * Minimal partial between the edited draft and the saved policy. Objects recurse; arrays and
 * scalars are replaced whole. A key removed from an object (table row deleted) is sent as `null`.
 */
export function diffPolicy(draft: unknown, base: unknown): { partial: PolicyObject; paths: string[] } {
  const paths: string[] = [];
  const walk = (a: unknown, b: unknown, path: string): unknown => {
    if (isPlainObject(a) && isPlainObject(b)) {
      const out: Record<string, unknown> = {};
      for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
        const p = path ? `${path}.${k}` : k;
        if (!(k in a)) {
          out[k] = null;
          paths.push(p);
        } else if (!(k in b)) {
          out[k] = a[k];
          paths.push(p);
        } else {
          const d = walk(a[k], b[k], p);
          if (d !== undefined) out[k] = d;
        }
      }
      return Object.keys(out).length ? out : undefined;
    }
    if (deepEqual(a, b)) return undefined;
    paths.push(path);
    return a;
  };
  const partial = walk(draft, base, "");
  return { partial: (partial as PolicyObject) ?? {}, paths };
}

/** True when `path` equals, contains or sits inside one of `others`. */
export function touches(path: string, others: string[]): boolean {
  return others.some((o) => o === path || o.startsWith(`${path}.`) || path.startsWith(`${o}.`));
}

export function humanize(key: string): string {
  const s = key.replace(/_/g, " ").replace(/\bpct\b/, "%").replace(/\bpp\b/, "pp").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
