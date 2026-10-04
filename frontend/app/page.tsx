import Link from "next/link";

const STEPS = [
  ["Connect", "Paste a public GitHub URL. GitContext clones and scans it."],
  ["Understand", "Code is split at real function, class and method boundaries, with exact line ranges."],
  ["Search", "Every chunk is embedded and stored so the right code can be found."],
  ["Ask (coming)", "Answers cite file and line evidence, and say so when evidence is missing."],
];

export default function Landing() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-20">
      <p className="text-sm font-medium text-emerald-400">Codebase intelligence for developers</p>
      <h1 className="mt-3 text-5xl font-bold tracking-tight">Understand any GitHub repo, with evidence.</h1>
      <p className="mt-5 text-lg text-slate-400">Connect a repository, explore how it is structured, and retrieve the code that matters. Built so every answer points to real files and lines.</p>
      <div className="mt-8 flex gap-3">
        <Link href="/signup" className="rounded-md bg-emerald-600 px-5 py-2.5 text-sm font-medium">Get started</Link>
        <Link href="/login" className="rounded-md border border-slate-700 px-5 py-2.5 text-sm">Log in</Link>
      </div>
      <ol className="mt-16 grid gap-4 sm:grid-cols-2">
        {STEPS.map(([t, d], i) => (
          <li key={t} className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <span className="text-xs text-slate-500">0{i + 1}</span>
            <h2 className="font-semibold">{t}</h2><p className="mt-1 text-sm text-slate-400">{d}</p>
          </li>
        ))}
      </ol>
      <p className="mt-10 text-xs text-slate-500">Status: repository indexing is live. Question answering is under construction.</p>
    </main>
  );
}
