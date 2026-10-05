"use client";
import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { ApiError, ago, api } from "@/lib/api";
import { ErrorBanner } from "./ui";

type Citation = { n: number; file_path: string; start_line: number; end_line: number; symbol: string | null; kind: string | null; snippet: string };
type Answer = {
  question: string; status: "answered" | "insufficient_evidence"; answer: string; generation: "extractive" | "llm" | null;
  citations: Citation[]; warnings: string[]; evidence_coverage: number; closest?: { file_path: string; start_line: number; end_line: number; symbol: string | null }[];
};
type Past = { question_id: number; question: string; status: Answer["status"]; generation: Answer["generation"]; answer: string; citations: Citation[]; evidence_coverage: number; created_at: string };

function renderAnswer(text: string) {
  return text.split(/(\[\d+(?::\d+-\d+)?\]|`[^`\n]+`)/).map((part, i) => {
    const m = part.match(/^\[(\d+)/);
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) return <code key={i} className="rounded bg-slate-800 px-1 text-[0.85em] text-emerald-200">{part.slice(1, -1)}</code>;
    return m ? <a key={i} href={`#cite-${m[1]}`} className="mx-0.5 rounded bg-emerald-900 px-1 text-xs text-emerald-300 no-underline hover:bg-emerald-800">{part}</a> : <Fragment key={i}>{part}</Fragment>;
  });
}

export default function AskPanel({ repoId }: { repoId: number }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Answer | null>(null);
  const [past, setPast] = useState<Past[]>([]);

  const loadPast = useCallback(() => api<Past[]>(`/repositories/${repoId}/questions?limit=5`).then(setPast).catch(() => null), [repoId]);
  useEffect(() => { loadPast(); }, [loadPast]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null); setRes(null);
    try {
      setRes(await api<Answer>(`/repositories/${repoId}/ask`, { method: "POST", body: JSON.stringify({ question }) }));
      loadPast();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  }
  const open = (p: Past) => { setQuestion(p.question); setRes({ question: p.question, status: p.status, answer: p.answer, generation: p.generation, citations: p.citations, warnings: [], evidence_coverage: p.evidence_coverage }); };

  return (
    <section className="mt-6 rounded-lg border border-emerald-900 bg-slate-900 p-4" aria-label="Ask a question">
      <h2 className="font-semibold">Ask a question</h2>
      <p className="mt-1 text-sm text-slate-400">Answers use only code retrieved from this repository and cite file and line ranges. If the repository has no evidence, GitContext says so instead of guessing.</p>
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} required minLength={3} maxLength={1000} aria-label="Your question"
          placeholder="e.g. How do I ask the user a yes or no confirmation question?"
          className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-500" />
        <button disabled={busy || question.trim().length < 3} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50">{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {error && <div className="mt-3"><ErrorBanner>{error}</ErrorBanner></div>}

      {res?.status === "insufficient_evidence" && (
        <div data-testid="refusal" className="mt-4 rounded-md border border-amber-800 bg-amber-950 p-3 text-sm text-amber-200">
          <p className="font-medium">{res.answer}</p>
          {res.closest && res.closest.length > 0 && (
            <p className="mt-2 text-xs text-amber-300/80">Closest code found (not an answer): {res.closest.map((c) => `${c.file_path}:${c.start_line}-${c.end_line}`).join(" · ")}</p>
          )}
        </div>
      )}
      {res?.status === "answered" && (
        <div data-testid="answer" className="mt-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded bg-slate-800 px-2 py-0.5">{res.generation === "llm" ? "AI answer · citations verified" : "Extractive summary · no AI used"}</span>
            <span className="text-slate-500">evidence coverage {(res.evidence_coverage * 100).toFixed(0)}%</span>
          </div>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-6">{renderAnswer(res.answer)}</div>
          {res.warnings.map((w) => <p key={w} className="mt-2 text-xs text-amber-300">{w}</p>)}
          <ol className="mt-3 space-y-2" aria-label="Citations">
            {res.citations.map((c) => (
              <li key={c.n} id={`cite-${c.n}`} data-testid="citation" className="min-w-0 rounded-md border border-slate-800 bg-slate-950 p-3 target:border-emerald-500">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded bg-emerald-900 px-1.5 text-emerald-300">[{c.n}]</span>
                  <span className="break-all font-mono font-semibold text-emerald-300">{c.file_path}:{c.start_line}-{c.end_line}</span>
                  {c.symbol && <span className="break-all text-slate-300">{c.symbol}</span>}
                </div>
                <pre className="mt-2 max-h-48 overflow-auto text-xs leading-5 text-slate-300">{c.snippet}</pre>
              </li>
            ))}
          </ol>
        </div>
      )}
      {past.length > 0 && (
        <div className="mt-5 border-t border-slate-800 pt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent questions</h3>
          <ul className="mt-2 space-y-1" data-testid="history">
            {past.map((p) => (
              <li key={p.question_id}>
                <button onClick={() => open(p)} className="flex w-full items-center justify-between gap-3 rounded px-2 py-1 text-left text-sm hover:bg-slate-800">
                  <span className="truncate">{p.question}</span>
                  <span className={`shrink-0 text-xs ${p.status === "answered" ? "text-emerald-400" : "text-amber-400"}`}>{p.status === "answered" ? "answered" : "no evidence"} · {ago(p.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
