"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Health = { status: string; version: string; database: string };

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("Backend unreachable"));
  }, []);

  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-4xl font-bold tracking-tight">GitContext</h1>
      <p className="mt-3 text-slate-400">
        Ask questions about any GitHub codebase and get answers backed by file and line citations.
      </p>
      <div className="mt-10 rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm">
        <span className="text-slate-400">Backend: </span>
        {error ? (
          <span className="text-red-400">{error}</span>
        ) : health ? (
          <span className="text-emerald-400">
            {health.status} · v{health.version} · db {health.database}
          </span>
        ) : (
          <span className="text-slate-500">checking…</span>
        )}
      </div>
    </main>
  );
}
