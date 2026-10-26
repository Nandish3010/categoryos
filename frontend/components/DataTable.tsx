import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  className?: string;
  render: (row: T) => ReactNode;
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClass,
  caption,
  renderExpanded,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowClass?: (row: T) => string;
  caption: string;
  /** Optional extra row rendered under a row (full width). */
  renderExpanded?: (row: T) => ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs text-text-dim">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`h-9 px-3 font-medium ${c.align === "right" ? "text-right" : ""} ${c.className ?? ""}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const extra = renderExpanded?.(r);
            return [
              <tr
                key={rowKey(r)}
                className={`h-10 border-b border-border last:border-b-0 ${rowClass?.(r) ?? ""}`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`px-3 align-middle ${c.align === "right" ? "text-right num" : ""} ${c.className ?? ""}`}
                  >
                    {c.render(r)}
                  </td>
                ))}
              </tr>,
              extra ? (
                <tr key={`${rowKey(r)}-x`} className="border-b border-border bg-surface-2/50">
                  <td colSpan={columns.length} className="px-3 py-2">
                    {extra}
                  </td>
                </tr>
              ) : null,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}
