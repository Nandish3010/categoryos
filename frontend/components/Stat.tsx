import type { ReactNode } from "react";

export function Stat({
  label,
  value,
  hint,
  size = "md",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  size?: "md" | "lg";
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-text-dim">{label}</div>
      <div
        className={`num font-semibold tracking-tight ${size === "lg" ? "text-[36px] leading-[40px]" : "text-xl"}`}
      >
        {value}
      </div>
      {hint ? <div className="text-xs text-text-dim">{hint}</div> : null}
    </div>
  );
}
