"use client";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, ago, api, type Repo, type Usage } from "@/lib/api";
import { ErrorBanner, Shell, StatusBadge, useUser } from "@/components/ui";

const ACTIVE = (r: Repo) => r.status === "pending" || r.status === "indexing";

export default function Dashboard() {
  const user = useUser();
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [r, u] = await Promise.all([api<Repo[]>("/repositories"), api<Usage>("/usage")]);
      setRepos(r); setUsage(u); setLoadErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { window.location.href = "/login"; return; }
      setLoadErr(e instanceof ApiError ? e.message : "Could not load repositories.");
    }
  }, []);
  useEffect(() => { if (user) refresh(); }, [user, refresh]);
  // Poll real backend state only while something is pending/indexing.
  useEffect(() => {
    if (!repos?.some(ACTIVE)) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [repos, refresh]);

  async function connect(e: FormEvent) {
    e.preventDefault(); setBusy(true); setFormErr(null);
    try { await api("/repositories", { method: "POST", body: JSON.stringify({ url }) }); setUrl(""); await refresh(); }
    catch (err) { setFormErr(err instanceof ApiError ? err.message : "Something went wrong."); }
    finally { setBusy(false); }
  }
  async function act(r: Repo, kind: "reindex" | "remove") {
    if (kind === "remove" && !window.confirm(`Remove ${r.owner}/${r.name}? Its index will be deleted.`)) return;
    try { await api(kind === "remove" ? `/repositories/${r.id}` : `/repositories/${r.id}/reindex`, { method: kind === "remove" ? "DELETE" : "POST" }); await refresh(); }
    catch (err) { setLoadErr(err instanceof ApiError ? err.message : "Action failed."); }
  }

  return (
    <Shell user={user}>
      <div className="flex flex-wrap items-end justify-between gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Repositories</h1>
        {usage && <p className="text-xs text-slate-500">{usage.repositories.used}/{usage.repositories.limit} repositories · {usage.plan} plan · {usage.chunks_indexed.toLocaleString()} chunks indexed</p>}
      </div>
      <form onSubmit={connect} className="mt-5 flex flex-col gap-2 sm:flex-row">
        <input value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://github.com/owner/repo" aria-label="GitHub repository URL"
          className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-500" />
        <button disabled={busy || !url.trim()} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50">{busy ? "Connecting…" : "Connect repository"}</button>
      </form>
      {formErr && <div className="mt-3"><ErrorBanner>{formErr}</ErrorBanner></div>}
      {loadErr && <div className="mt-3"><ErrorBanner>{loadErr} <button className="underline" onClick={refresh}>Retry</button></ErrorBanner></div>}

      {repos === null && !loadErr && <p className="mt-8 text-sm text-slate-500">Loading repositories…</p>}
      {repos?.length === 0 && (
        <div className="mt-8 rounded-lg border border-dashed border-slate-700 p-10 text-center">
          <p className="font-medium">No repositories yet</p>
          <p className="mt-1 text-sm text-slate-400">Paste a public GitHub URL above to index your first codebase.</p>
        </div>
      )}
      <ul className="mt-6 grid gap-4 sm:grid-cols-2">
        {repos?.map((r) => (
          <li key={r.id} className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold" title={`${r.owner}/${r.name}`}>{r.owner}/{r.name}</p>
                <p className="text-xs text-slate-500">added {ago(r.created_at)} · indexed {ago(r.indexed_at)}</p>
              </div>
              <StatusBadge repo={r} />
            </div>
            {r.status === "ready" && (
              <p className="mt-3 text-slate-400">{r.file_count} files · {r.chunk_count.toLocaleString()} chunks · {Object.keys(r.languages).slice(0, 3).join(", ")}</p>
            )}
            {r.status === "failed" && <p className="mt-3 break-words text-red-300">{r.error_message}</p>}
            <div className="mt-4 flex gap-2">
              {r.status === "ready" && <Link href={`/repositories/${r.id}`} className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium">Open workspace</Link>}
              {(r.status === "ready" || r.status === "failed") && (
                <button onClick={() => act(r, "reindex")} className="rounded border border-slate-700 px-3 py-1 text-xs hover:bg-slate-800">{r.status === "failed" ? "Retry" : "Re-index"}</button>
              )}
              {r.status !== "indexing" && <button onClick={() => act(r, "remove")} className="ml-auto rounded px-3 py-1 text-xs text-red-400 hover:bg-red-950">Remove</button>}
            </div>
          </li>
        ))}
      </ul>
    </Shell>
  );
}
