/** Playbook rules written as prompts: the preview the server builds, the change log, and the calls behind them. The model only picks
 *  existing settings and numbers; every figure shown here comes from the server's validated playbook. */
import { post, request } from "./api";
import type { PolicyResponse } from "./policy";

export type Member = { id: string; name: string; role: string };

export type ChangeLine = {
  keys: string[];
  path: string;
  label: string;
  unit: string | null;
  used_in: string[];
  before: unknown;
  after: unknown;
};

export type Outcome = { action: "apply" | "request_approval" | "refuse"; reason: string | null };

export type PreviewError = { code: string; problem: string; cause?: string; fix?: string; path?: string | null };

/** What POST /api/policy/propose returns. Only "ready" has an id and changes to apply. */
export type Preview = {
  status: "ready" | "invalid" | "unmapped" | "unchanged";
  id: string | null;
  prompt: string;
  translator: string;
  changes: ChangeLine[];
  outcome: Outcome | null;
  error: PreviewError | null;
  message?: string;
};

export type ChangeStatus = "proposed" | "applied" | "pending_approval" | "refused" | "rejected" | "undone";

export type Change = {
  id: string;
  at: string;
  decided_at: string | null;
  actor: Member;
  source: "prompt" | "form" | "undo" | "reset";
  prompt: string | null;
  translator: string | null;
  diff: ChangeLine[];
  status: ChangeStatus;
  reason: string | null;
  approver: Member | null;
  hash_before: string | null;
  hash_after: string | null;
  undo_of: string | null;
  undone_by: string | null;
  events: { at: string; actor: Member; action: string; reason: string | null }[];
  /** What the acting member may do to this entry (the server checks again on every action). */
  allowed?: { approve: boolean; reject: boolean; undo: boolean };
};

export type ChangeLog = { changes: Change[]; acting: Member };

export type Example = { prompt: string; note: string };

export const fetchExamples = (signal?: AbortSignal) => request<{ examples: Example[] }>("GET", "/api/policy/examples", { signal });
export const proposeRule = (prompt: string, signal?: AbortSignal) => post<Preview>("/api/policy/propose", { prompt }, signal);
export const fetchChanges = (signal?: AbortSignal) => request<ChangeLog>("GET", "/api/policy/changes", { signal });

export type Action = "apply" | "approve" | "reject" | "undo";
/** The change record plus the playbook as it is afterwards. */
export const actOnChange = (id: string, action: Action) => post<PolicyResponse & { change: Change }>(`/api/policy/changes/${encodeURIComponent(id)}/${action}`, {});
export const discardChange = (id: string) => post<{ ok: boolean }>(`/api/policy/changes/${encodeURIComponent(id)}/discard`, {});

/** Members from the playbook's governance section, in file order. */
export function membersOf(policy: Record<string, unknown> | undefined): (Member & { roleLabel: string })[] {
  const gov = policy?.governance as
    | { members?: Record<string, { name: string; role: string }>; roles?: Record<string, { label?: string }> }
    | undefined;
  return Object.entries(gov?.members ?? {}).map(([id, m]) => ({ id, name: m.name, role: m.role, roleLabel: gov?.roles?.[m.role]?.label ?? m.role }));
}

export function formatValue(v: unknown, unit?: string | null): string {
  if (v === null || v === undefined) return "(none)";
  if (typeof v === "boolean") return v ? "on" : "off";
  if (typeof v === "number") return `${Number.isInteger(v) ? v : Number(v.toFixed(4))}${unit ? ` ${unit}` : ""}`;
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

export const STATUS_LABEL: Record<ChangeStatus, string> = {
  proposed: "Draft",
  applied: "Applied",
  pending_approval: "Waiting for approval",
  refused: "Refused",
  rejected: "Rejected",
  undone: "Undone",
};
