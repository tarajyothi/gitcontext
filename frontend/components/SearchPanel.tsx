"use client";
import { FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { ErrorBanner } from "./ui";

type Hit = {
  chunk_id: number; file_path: string; symbol: string | null; kind: string | null; start_line: number; end_line: number;
  content: string; score: number; signals: { vector_rank: number | null; bm25_rank: number | null; identifier: number | null };
};
const SNIPPET_LINES = 14;

export default function SearchPanel({ repoId }: { repoId: number }) {
  const [query, setQuery] = useState("");
  const [hideNoise, setHideNoise] = useState(false);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const body = { query, k: 8, filters: hideNoise ? { exclude_tests: true, exclude_docs: true } : undefined };
      setHits(await api<Hit[]>(`/repositories/${repoId}/search`, { method: "POST", body: JSON.stringify(body) }));
      setAsked(query);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed. Please try again.");
    } finally { setBusy(false); }
  }

  return (
    <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="font-semibold">Search this codebase</h2>
      <p className="mt-1 text-sm text-slate-400">Finds the code most relevant to your question, with file and line citations. Cited answers are the next release; this is the evidence they will use.</p>
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input value={query} onChange={(e) => setQuery(e.target.value)} required maxLength={1000} aria-label="Search query"
          placeholder="e.g. How does a group find a subcommand?"
          className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-500" />
        <button disabled={busy || !query.trim()} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50">{busy ? "Searching…" : "Search"}</button>
      </form>
      <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
        <input type="checkbox" checked={hideNoise} onChange={(e) => setHideNoise(e.target.checked)} /> Hide tests &amp; docs
      </label>
      {error && <div className="mt-3"><ErrorBanner>{error}</ErrorBanner></div>}
      {hits && hits.length === 0 && <p className="mt-4 text-sm text-slate-400">No matching code found for “{asked}”. Try different words or turn off filters.</p>}
      {hits && hits.length > 0 && (
        <ol className="mt-4 space-y-3" aria-label="Search results">
          {hits.map((h) => {
            const lines = h.content.split("\n");
            return (
              <li key={h.chunk_id} data-testid="hit" className="min-w-0 rounded-md border border-slate-800 bg-slate-950 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="break-all font-mono font-semibold text-emerald-300">{h.file_path}:{h.start_line}-{h.end_line}</span>
                  {h.kind && <span className="rounded bg-slate-800 px-1.5 py-0.5">{h.kind}</span>}
                  {h.symbol && <span className="break-all text-slate-300">{h.symbol}</span>}
                  <span className="ml-auto text-slate-500" title="vector rank / keyword rank / identifier match">
                    score {h.score.toFixed(2)}{h.signals.identifier ? " · exact name" : ""}
                  </span>
                </div>
                <pre className="mt-2 max-h-56 overflow-auto text-xs leading-5 text-slate-300">{lines.slice(0, SNIPPET_LINES).join("\n")}{lines.length > SNIPPET_LINES ? `\n… ${lines.length - SNIPPET_LINES} more lines` : ""}</pre>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
