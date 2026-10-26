import type { ReactNode } from "react";

export function PanelHeader({
  title,
  right,
}: {
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-2 border-b border-border px-4 py-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      {right ? <div className="text-xs text-text-dim">{right}</div> : null}
    </div>
  );
}
