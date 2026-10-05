"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, ago, api, type FileRow, type Repo } from "@/lib/api";
import SearchPanel from "@/components/SearchPanel";
import { ErrorBanner, Shell, StatusBadge, useUser } from "@/components/ui";

export default function Workspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const user = useUser();
  const [repo, setRepo] = useState<Repo | null>(null);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<Repo>(`/repositories/${id}`);
      setRepo(r); setError(null);
      if (r.status === "ready") setFiles(await api<FileRow[]>(`/repositories/${id}/files?limit=100`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotFound(true);
      else if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e instanceof ApiError ? e.message : "Could not load this repository.");
    }
  }, [id, router]);
  useEffect(() => { if (user) load(); }, [user, load]);
  useEffect(() => {
    if (!repo || (repo.status !== "pending" && repo.status !== "indexing")) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [repo, load]);

  async function reindex() {
    try { await api(`/repositories/${id}/reindex`, { method: "POST" }); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Action failed."); }
  }
  async function remove() {
    if (!repo || !window.confirm(`Remove ${repo.owner}/${repo.name}?`)) return;
    try { await api(`/repositories/${id}`, { method: "DELETE" }); router.replace("/dashboard"); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Action failed."); }
  }

  return (
    <Shell user={user}>
      <Link href="/dashboard" className="text-sm text-slate-400 hover:text-slate-200">← All repositories</Link>
      {notFound && <div className="mt-6"><ErrorBanner>Repository not found. It may have been removed.</ErrorBanner></div>}
      {error && <div className="mt-6"><ErrorBanner>{error} <button className="underline" onClick={load}>Retry</button></ErrorBanner></div>}
      {!repo && !notFound && !error && <p className="mt-6 text-sm text-slate-500">Loading workspace…</p>}
      {repo && (
        <>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="break-words text-2xl font-bold tracking-tight">{repo.owner}/{repo.name}</h1>
              <a href={repo.url} target="_blank" rel="noreferrer" className="break-all text-xs text-slate-500 hover:underline">{repo.url}</a>
            </div>
            <StatusBadge repo={repo} />
          </div>
          {repo.status === "failed" && <div className="mt-4"><ErrorBanner>{repo.error_message}</ErrorBanner></div>}
          <dl className="mt-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[["Files", repo.file_count], ["Chunks", repo.chunk_count.toLocaleString()], ["Size", `${(repo.total_bytes / 1024).toFixed(0)} KB`],
              ["Branch", repo.default_branch ?? "—"], ["Commit", repo.commit_sha?.slice(0, 7) ?? "—"], ["Last indexed", ago(repo.indexed_at)],
              ["Added", ago(repo.created_at)], ["Updated", ago(repo.updated_at)]].map(([k, v]) => (
              <div key={String(k)} className="rounded-lg border border-slate-800 bg-slate-900 p-3"><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>
            ))}
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(repo.languages).map(([l, n]) => <span key={l} className="rounded bg-slate-800 px-2 py-0.5 text-xs">{l} {n}</span>)}
          </div>
          {repo.status === "ready" && <SearchPanel repoId={repo.id} />}
          <div className="mt-6 flex gap-2">
            {(repo.status === "ready" || repo.status === "failed") && <button onClick={reindex} className="rounded border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800">{repo.status === "failed" ? "Retry indexing" : "Re-index"}</button>}
            {repo.status !== "indexing" && <button onClick={remove} className="rounded px-3 py-1.5 text-sm text-red-400 hover:bg-red-950">Remove repository</button>}
          </div>
          {files.length > 0 && (
            <section className="mt-8">
              <h2 className="mb-2 text-sm font-semibold text-slate-400">Files (first {files.length} of {repo.file_count})</h2>
              <div className="max-h-96 overflow-auto rounded-lg border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500"><tr><th className="p-2">Path</th><th>Language</th><th className="pr-2 text-right">Size</th></tr></thead>
                  <tbody>{files.map((f) => <tr key={f.path} className="border-t border-slate-800"><td className="p-2 font-mono">{f.path}</td><td>{f.language ?? "—"}</td><td className="pr-2 text-right">{f.size_bytes} B</td></tr>)}</tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </Shell>
  );
}
