"use client";
import { FormEvent, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Health = { status: string; version: string; database: string };
type Repo = {
  id: number; url: string; owner: string; name: string; status: string; commit_sha: string | null;
  default_branch: string | null; file_count: number; total_bytes: number; languages: Record<string, number>;
  error_message: string | null;
};
type FileRow = { path: string; language: string | null; size_bytes: number };

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repo, setRepo] = useState<Repo | null>(null);
  const [files, setFiles] = useState<FileRow[]>([]);

  useEffect(() => {
    fetch(`${API}/health`).then((r) => r.json()).then(setHealth).catch(() => setHealthErr(true));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setRepo(null); setFiles([]);
    try {
      const r = await fetch(`${API}/repositories`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
      });
      const body = await r.json();
      if (!r.ok) { setError(body?.error?.message ?? "Something went wrong"); return; }
      setRepo(body);
      const f = await fetch(`${API}/repositories/${body.id}/files?limit=50`);
      setFiles(await f.json());
    } catch {
      setError("Backend unreachable. Is it running on " + API + "?");
    } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-4xl font-bold tracking-tight">GitContext</h1>
      <p className="mt-3 text-slate-400">Ask questions about any GitHub codebase and get answers backed by file and line citations.</p>
      <p className="mt-2 text-xs text-slate-500">
        Backend: {healthErr ? <span className="text-red-400">unreachable</span>
          : health ? <span className="text-emerald-400">{health.status} · v{health.version}</span> : "checking…"}
      </p>

      <form onSubmit={submit} className="mt-8 flex flex-col gap-2 sm:flex-row">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo"
          aria-label="GitHub repository URL" required
          className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-500" />
        <button disabled={busy || !url.trim()} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50">
          {busy ? "Ingesting…" : "Ingest repository"}
        </button>
      </form>

      {busy && <p className="mt-4 text-sm text-slate-400">Cloning and scanning — this can take a few seconds…</p>}
      {error && <p role="alert" className="mt-4 rounded-md border border-red-900 bg-red-950 p-3 text-sm text-red-300">{error}</p>}

      {repo && (
        <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm">
          <div className="flex items-center justify-between">
            <a href={repo.url} className="font-semibold hover:underline">{repo.owner}/{repo.name}</a>
            <span className="rounded bg-emerald-900 px-2 py-0.5 text-xs text-emerald-300">{repo.status}</span>
          </div>
          <p className="mt-2 text-slate-400">
            {repo.file_count} files · {(repo.total_bytes / 1024).toFixed(0)} KB · branch {repo.default_branch} ·{" "}
            <code>{repo.commit_sha?.slice(0, 7)}</code>
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(repo.languages).map(([l, n]) => (
              <span key={l} className="rounded bg-slate-800 px-2 py-0.5 text-xs">{l} {n}</span>
            ))}
          </div>
          <div className="mt-4 max-h-72 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1">Path</th><th>Language</th><th className="text-right">Size</th></tr></thead>
              <tbody>{files.map((f) => (
                <tr key={f.path} className="border-t border-slate-800">
                  <td className="py-1 pr-2 font-mono">{f.path}</td><td>{f.language ?? "—"}</td>
                  <td className="text-right">{f.size_bytes} B</td>
                </tr>))}</tbody>
            </table>
          </div>
          {repo.file_count > files.length && <p className="mt-2 text-xs text-slate-500">Showing first {files.length} of {repo.file_count} files.</p>}
        </section>
      )}
    </main>
  );
}
