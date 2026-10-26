import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import type { ReactNode } from "react";

const tones = {
  info: { cls: "border-accent/40 bg-accent/10", Icon: Info },
  warn: { cls: "border-warn/40 bg-warn/10", Icon: AlertTriangle },
  bad: { cls: "border-bad/40 bg-bad/10", Icon: OctagonAlert },
} as const;

export function Banner({
  tone = "info",
  title,
  children,
  action,
  role,
}: {
  tone?: keyof typeof tones;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  role?: "alert" | "status";
}) {
  const t = tones[tone];
  return (
    <div
      role={role ?? (tone === "bad" ? "alert" : "status")}
      className={`flex items-start gap-3 rounded-card border p-3 ${t.cls}`}
    >
      <t.Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{title}</div>
        {children ? <div className="text-sm text-text-dim">{children}</div> : null}
      </div>
      {action}
    </div>
  );
}
