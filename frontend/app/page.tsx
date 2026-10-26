"use client";

import { useEffect, useState } from "react";

type Stage = {
  id: string;
  name: string;
  description: string;
  status: string;
};

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8001";

export default function Home() {
  const [stages, setStages] = useState<Stage[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/stages`)
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then(setStages)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 px-6 py-16 text-zinc-100">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-5xl font-bold tracking-tight">CategoryOS</h1>
        <p className="mt-3 text-lg text-zinc-400">
          From vendor request to warehouse — run by agents
        </p>

        {loading && <p className="mt-12 text-zinc-500">Loading stages…</p>}

        {error && (
          <div className="mt-12 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200">
            Couldn&apos;t reach the backend at {BACKEND_URL}. Start it with{" "}
            <code className="rounded bg-zinc-900 px-1">
              make dev
            </code>{" "}
            and refresh.
          </div>
        )}

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stages.map((stage, i) => (
            <div
              key={stage.id}
              className="rounded-xl border border-zinc-800 bg-zinc-900 p-5"
            >
              <div className="flex items-center justify-between text-sm text-zinc-500">
                <span>Stage {i + 1}</span>
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs">
                  {stage.status}
                </span>
              </div>
              <h2 className="mt-3 font-semibold">{stage.name}</h2>
              <p className="mt-1 text-sm text-zinc-400">{stage.description}</p>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
