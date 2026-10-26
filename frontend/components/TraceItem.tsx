import type { ReactNode } from "react";

export function TraceItem({
  time,
  title,
  children,
}: {
  time?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <li className="flex gap-3 border-b border-border px-4 py-2 last:border-b-0">
      <span className="num w-12 shrink-0 font-mono text-xs text-text-dim">{time ?? "--"}</span>
      <div className="min-w-0">
        <div className="text-sm">{title}</div>
        {children ? <div className="text-xs text-text-dim">{children}</div> : null}
      </div>
    </li>
  );
}
