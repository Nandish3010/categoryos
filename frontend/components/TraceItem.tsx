import type { ReactNode } from "react";

export function TraceItem({
  time,
  title,
  icon,
  meta,
  children,
}: {
  time?: string;
  title: string;
  icon?: ReactNode;
  /** model · latency · cost line */
  meta?: string;
  children?: ReactNode;
}) {
  return (
    <li className="flex gap-3 border-b border-border px-4 py-2 last:border-b-0">
      <span className="num w-12 shrink-0 font-mono text-xs text-text-dim">{time ?? "--"}</span>
      {icon ? <span className="mt-0.5 shrink-0 text-text-dim">{icon}</span> : null}
      <div className="min-w-0">
        <div className="text-sm">{title}</div>
        {children ? <div className="break-words text-xs text-text-dim">{children}</div> : null}
        {meta ? <div className="num font-mono text-xs text-text-dim">{meta}</div> : null}
      </div>
    </li>
  );
}
