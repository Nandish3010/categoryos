export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`shimmer rounded bg-surface-2 ${className}`}
    />
  );
}
