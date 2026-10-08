# Resume bullets and launch copy (all claims are measured; edit freely, keep the numbers honest)

## Resume bullets
- Built **GitContext**, a full-stack codebase-intelligence app (Next.js 16/React 19, FastAPI, PostgreSQL): ingests a public GitHub repo, chunks code at AST boundaries with exact line ranges, and answers questions with line-level citations, or refuses when the repo has no evidence.
- Engineered **hybrid retrieval** (BM25 + embeddings + exact-identifier matching, RRF fusion, reranking); on a frozen benchmark written before the code, held-out **Recall@5 = 0.83** (n=12) vs 0.42 for vector-only; reported failure cases and limits.
- Added **incremental indexing** (content-hash diff, transactional replacement): on two real `pallets/click` commits it reprocessed **26% of chunks** and cut index time **63%**.
- Hardened for production: per-tenant isolation tested on every route, rate limits, secret redaction, prompt-injection defences with a citation verifier, Alembic migrations, HTTPS reverse proxy; a dependency audit drove upgrades of Next.js 14->16 and FastAPI/Starlette (0 known runtime vulnerabilities).
- **159 automated tests** (SQLite + PostgreSQL), 22-step real-browser E2E, post-deploy smoke test, CI with lint, bandit and dependency audits.

## LinkedIn post
I spent the last week building GitContext in public: connect a GitHub repo, ask a question, get an answer that points at the exact files and lines, or an honest "not enough evidence".

What I'm proudest of is not the demo, it's the measuring:
- Wrote the benchmark questions before the retrieval code, tuned on a dev split, and looked at a held-out split once. Held-out Recall@5: 0.83 (12 questions, so wide error bars).
- It refused 23 of 24 questions the repo can't answer, but also wrongly refused 17% of answerable ones. I published both numbers.
- Re-indexing a repo after a real upstream commit reprocesses only the changed files: 26% of the chunk work instead of 100%.
- A real-browser test found a bug 150 passing tests missed (auth redirects broke behind HTTPS).

Honest status: it's a release candidate running end to end on my machine over HTTPS; it isn't deployed yet, and LLM-written answers aren't measured because I haven't plugged in a key. Code, benchmarks and limits are in the repo.

## X / Twitter
Built GitContext: ask questions about any GitHub repo, get answers with file:line citations, or an honest refusal.
Held-out Recall@5 0.83 (n=12). Refuses 23/24 unanswerable questions. Incremental re-index does 26% of the work.
A real-browser test caught a bug 150 tests missed. Not deployed yet; limits are documented.

## 30-second pitch
"GitContext lets a developer connect a GitHub repo and ask how it works. Every answer cites real files and line numbers, and if the code doesn't contain the answer it says so instead of guessing. I measured it on benchmarks I wrote before the code, and I can show you where it fails."
