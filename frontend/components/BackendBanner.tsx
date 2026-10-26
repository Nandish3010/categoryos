import { BACKEND_URL, ApiError } from "@/lib/api";
import { Banner } from "./Banner";

/** Error banner that names the URL tried and the fix. */
export function BackendBanner({
  error,
  cached,
  retrying,
}: {
  error: Error;
  cached?: boolean;
  retrying?: boolean;
}) {
  const api = error instanceof ApiError ? error : null;
  const unreachable = !api || api.unreachable;
  return (
    <Banner
      tone={unreachable ? "warn" : "bad"}
      title={unreachable ? "Backend warming up or not running" : api!.body.problem}
    >
      {unreachable ? (
        <>
          Tried <span className="font-mono text-text">{BACKEND_URL}</span>. Run{" "}
          <code className="rounded bg-surface-2 px-1 font-mono text-text">make dev</code> from the
          repo root.
          {retrying ? " Retrying every 3 s." : ""}
          {cached ? " Showing cached data." : ""}
        </>
      ) : (
        <>
          {api!.body.cause ? `${api!.body.cause} ` : ""}
          {api!.body.fix ?? ""}
          {cached ? " Using cached plan." : ""}
        </>
      )}
    </Banner>
  );
}
