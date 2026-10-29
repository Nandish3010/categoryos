"use client";

import { useEffect, useId } from "react";
import { getActingAs, setActingAs } from "@/lib/identity";
import { membersOf } from "@/lib/rules";

/** The member to act as: the saved choice if that member still exists, else the first head, else the first member. */
export function resolveActing(policy: Record<string, unknown> | undefined, saved: string | null): string | null {
  const members = membersOf(policy);
  if (!members.length) return null;
  return (saved && members.find((m) => m.id === saved)?.id) || members.find((m) => m.role === "head")?.id || members[0].id;
}

/**
 * "Signed in as": a DEMO identity picker. It is not authentication: anyone can pick anyone, and the page says so. The choice is kept in
 * localStorage and sent as X-Acting-As; the server checks what that member may do on every action.
 */
export function ActingAs({
  policy,
  value,
  onChange,
}: {
  policy: Record<string, unknown> | undefined;
  value: string | null;
  onChange: (id: string) => void;
}) {
  const id = useId();
  const members = membersOf(policy);
  // adopt the saved choice once the team is known (localStorage is not available while rendering on the server)
  useEffect(() => {
    if (value === null && members.length) {
      const next = resolveActing(policy, getActingAs());
      if (next) {
        setActingAs(next);
        onChange(next);
      }
    }
  }, [value, members.length, policy, onChange]);

  if (!members.length) return null;
  return (
    <div className="flex flex-col items-start gap-1 md:items-end">
      <label htmlFor={id} className="flex items-center gap-2 text-sm">
        <span className="text-text-dim">Signed in as</span>
        <select
          id={id}
          value={value ?? ""}
          onChange={(e) => {
            setActingAs(e.target.value);
            onChange(e.target.value);
          }}
          className="h-9 rounded-chip border border-border bg-surface-2 px-2 text-sm text-text"
        >
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}, {m.roleLabel}
            </option>
          ))}
        </select>
      </label>
      <p className="text-xs text-text-dim">Demo identity, not a login: anyone can pick anyone. The server still enforces each role.</p>
    </div>
  );
}
