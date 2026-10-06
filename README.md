# GitContext

**A codebase intelligence copilot.** Connect a GitHub repository, and ask questions about it. Answers are generated from retrieved code and cite exact file paths and line ranges. When the evidence isn't there, GitContext says so instead of guessing.

> **Status:** accounts, per-user workspaces, background indexing, hybrid code search and evidence-grounded answers (with honest refusals) all work, and the production stack (Postgres + HTTPS proxy + hardened app) is verified end-to-end on one machine. **Not deployed yet**: no live URL. See [deployment guide](docs/deployment.md). Benchmarks: [retrieval](docs/benchmarks/retrieval.md), [answering](docs/benchmarks/answering.md).

## Problem
Developers constantly join unfamiliar repositories. Grep finds strings but not meaning; generic chatbots hallucinate about code they can't see. GitContext grounds every answer in the actual repository and shows its evidence.

## Architecture
```
GitHub URL → Ingestion → Code-aware chunking → Embeddings → Vector store (pgvector)
                                                    │
 Question → Hybrid retrieval (vector + keyword/BM25) → Rerank → Context → LLM → Answer + file:line citations
```
Details and design decisions: [`docs/architecture.md`](docs/architecture.md).

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy 2.0 |
| Database | SQLite (default, zero-setup) · PostgreSQL + pgvector (Day 3+) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Embeddings | Local deterministic baseline (default, no key) · any OpenAI-compatible API via `EMBEDDING_PROVIDER=openai` |
| Vector store | `chunk_embeddings` table (float32 BLOB, cosine search); pgvector column planned for production |
| LLM | Added Day 5 |

## Setup
Requires Python 3.11+ and Node 18+.

```bash
git clone <your-repo-url> gitcontext && cd gitcontext
cp .env.example .env

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # dev tools (ruff, bandit): requirements-dev.txt
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/health   (interactive docs: /docs)

# Frontend (new terminal). /api/* is proxied to BACKEND_URL (default http://localhost:8000)
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

**Upgrading from an earlier checkout:** the schema changed (users, workspaces, per-user repositories) and there are no migrations yet. Delete `backend/gitcontext.db` and `backend/workspace/` once.

Optional Postgres + pgvector (needed from Day 3): `docker compose up -d`, then set `DATABASE_URL` in `.env`.

## Deployment
`docker-compose.prod.yml` (Caddy HTTPS -> Next.js + FastAPI -> PostgreSQL), `deploy/Caddyfile`, Alembic migrations, a CI workflow and a post-deploy smoke test (`backend/scripts/smoke_test.py <url>`) are included. Verified locally; **not yet run on Docker or a host**. Full steps, checks and limits: [docs/deployment.md](docs/deployment.md).

## Tests
**Record a real-time video of the app** (captioned, real HTTPS/Postgres run): `IGNORE_TLS=1 node e2e/record_demo.mjs https://localhost:8443 ./rec && python e2e/build_video.py ./rec demo.mp4` (needs `playwright-core`, `@sparticuz/chromium`, `imageio-ffmpeg`).

**Real-browser flow:** with backend and `next start` running, `cd e2e && npm i playwright-core @sparticuz/chromium && node browser_flow.mjs http://localhost:3000 ./shots` drives signup, indexing, workspace, logout/login, re-index, error states and a mobile viewport in real Chromium.

```bash
cd backend && source .venv/bin/activate && python -m pytest -q
```

## API
All routes except `/health`, `/auth/signup` and `/auth/login` require a session cookie. Errors share one shape: `{"error": {"code", "message", "request_id", "details?"}}`; internals are never leaked.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + DB connectivity |
| POST | `/auth/signup` · `/auth/login` | `{"email","password"}` (password 8-128 chars). Sets an HttpOnly session cookie. Login is limited to 5 failures per 15 min per IP+email |
| POST | `/auth/logout` · GET `/auth/me` | Destroys the server-side session · current user + workspace |
| POST | `/repositories` | `{"url"}` -> **202** with `status: pending`; clone, scan, chunk and embed run in the background |
| GET | `/repositories` · `/repositories/{id}` | Own repositories only. Fields: status, stage, error_message, file_count, chunk_count, languages, branch, commit, created/updated/indexed time |
| POST | `/repositories/{id}/reindex` | Re-clone and re-index; also the retry path for `failed` repos (409 while indexing) |
| DELETE | `/repositories/{id}` | Removes DB rows and the clone on disk (409 while indexing) |
| GET | `/repositories/{id}/files` · `/chunks` | Indexed files · chunks with exact line ranges |
| POST | `/repositories/{id}/index` | Re-chunk/re-embed without re-cloning |
| POST | `/repositories/{id}/search` | Hybrid code search. Body: `{"query", "k": 1-50, "mode": "hybrid"\|"vector"\|"bm25", "rerank": true, "filters": {"language": [], "path_prefix": "", "kinds": [], "exclude_tests": false, "exclude_docs": false}}`. Returns chunks with `file_path`, `start_line`, `end_line`, `symbol`, `kind`, `content`, `score` and `signals` (vector rank, keyword rank, identifier match, rerank adjustment) |
| POST | `/repositories/{id}/ask` | `{"question"}` (3-1000 chars). Returns `status` (`answered` \| `insufficient_evidence`), `answer` with `[n]` markers, `generation` (`extractive` \| `llm`), `citations` (file, exact lines, symbol, snippet), `evidence_coverage`, `warnings`, and `closest` code on refusal. 429 after `DAILY_QUESTION_LIMIT` questions/24 h |
| GET | `/repositories/{id}/questions` | Question history for the repository (answer + citations stored) |
| GET | `/usage` | Real counts: repositories used/limit, files, chunks. questions asked in the last 24 h vs limit |

**Repository states:** `pending -> indexing (stage: cloning | scanning | embedding) -> ready | failed`. Stages are written by the backend as work happens; the UI polls them. A server restart marks interrupted jobs `failed` with a retry message.

**Errors:** `invalid_url` (422), `duplicate_repository` (409), `repo_limit_reached` (403), `not_authenticated`/`session_expired` (401), `too_many_attempts` (429). Clone/indexing failures (`repo_not_accessible`, `repo_empty`, `no_supported_files`, `repo_too_large`, timeouts) are stored on the repository as `status=failed` + `error_message`.

**Ignored during scan:** `.git`, `node_modules`, build/cache dirs, binaries, lockfiles, files over 1 MB, symlinks, secret-like files (`.env*`, `*.pem`, `*.key`, `id_rsa`, ...). Max 5000 files and 50 MB of indexed source per repo.

## How answers stay grounded
1. Hybrid search retrieves chunks. 2. **Evidence gate:** if the question's distinctive terms are not found in the retrieved code, GitContext refuses and calls no generator.
3. The generator sees only numbered, line-numbered chunks wrapped as `untrusted` data (forged `<chunk>` tags inside files are escaped).
4. **Verifier:** an LLM answer is rejected unless it cites provided chunks, its line ranges fit, at most a third of its claims are uncited and every
`backticked` identifier exists in the evidence. Rejected or failed LLM calls fall back to the extractive answer. Repository text is never treated as instructions.
Set `LLM_PROVIDER=anthropic` and `LLM_API_KEY` to enable LLM answers (the key stays server-side).

## Authentication & authorization
- Passwords: scrypt (N=2^14, r=8, p=1) with per-user salt; never stored or logged in plaintext.
- Sessions: random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `COOKIE_SECURE=true`); only its SHA-256 is stored server-side, so logout truly invalidates it. 7-day expiry (`SESSION_DAYS`).
- The browser only talks to `/api/*` on the Next.js origin, which proxies to the backend (`BACKEND_URL`, server-side only). The cookie is first-party and no secret reaches the browser bundle.
- Ownership: User -> Workspace -> Repository. Every repository route resolves the repo *within the caller's workspace*; other users' IDs return 404 (no ID enumeration). Covered by tests on every route.
- Next.js middleware redirects cookie-less visitors from `/dashboard` and `/repositories/*` to `/login`; the API remains the real authority (401 -> login).

## Data model
`repositories → files → chunks`. Every chunk stores `file_path`, `symbol`, `language`, `start_line`, `end_line`, `content`, so any retrieved chunk is traceable to exact source lines (enforced by a DB check constraint). Each chunk has one row in `chunk_embeddings` (model name, dim, float32 vector).

## Sample repository
[`sample_repos/tiny_shop`](sample_repos/tiny_shop) is a tiny Python + JS repo with known functions/errors, used to verify ingestion, chunking and retrieval by hand.

## Security notes
Repository content is treated as untrusted data. Secrets live only in `.env` (git-ignored). Input validation (GitHub URLs, size limits) arrives with ingestion on Day 2.

## Roadmap
- [x] Day 1: Skeleton, schema, health endpoint, README
- [x] Day 2: GitHub ingestion
- [x] Day 3: Code-aware chunking + embeddings
- [x] Day 4: Hybrid retrieval + reranking (benchmarked: held-out R@5 0.83 on one repo, see docs)
- [x] Day 5: Evidence-grounded answering + citations + refusal (extractive measured; LLM path unmeasured)
- [ ] Day 6: Evaluation + reliability
- [~] Day 7: UI done; deployment artifacts verified locally, live URL pending
- [ ] Day 8: Docs, demo, release

## Limitations (current)
- Sessions, the login limiter and background jobs are in-process: single backend instance only. No email verification or password reset yet. No CSRF token (relies on SameSite=Lax + JSON-only API).
- Background jobs use FastAPI background tasks (not a durable queue); interrupted jobs are marked failed and must be retried.
- Browser E2E (`e2e/browser_flow.mjs`, Playwright + Chromium) covers the main flow, but it is a script you run manually (needs `playwright-core` and `@sparticuz/chromium`), not part of CI. There are no component-level frontend unit tests. Also see `backend/scripts/e2e_flow.py` (HTTP-level).
- The question-answering box in the workspace is an honest placeholder; usage tracking beyond counts is not implemented.
- Ingestion is synchronous (the request blocks while cloning); background jobs are not implemented.
- Public repositories only; private repo support is not implemented.
- `modified_at` is the checkout time (git clone resets file times), not the last-commit time.
- Files without a known extension are stored with `language = null`.
- **Default embedder is not a neural model.** It is a deterministic, identifier-aware feature-hashing baseline: good at exact/partial identifier and word overlap, weak at paraphrase-level meaning. Neural embeddings need `EMBEDDING_PROVIDER=openai` + `EMBEDDING_API_KEY` (code path unit-tested with a mock; **not yet run against a live API**).
- Chunking: Python (ast), JS/TS (declaration scanner; regex literals containing quotes can confuse it), Markdown (headings). Other languages use 60-line windows with 10-line overlap. Large classes split per method (Python only); other oversized chunks split into `(part N)`.
- Vector search is brute-force NumPy cosine over all chunks of a repo (fine at this scale; pgvector/ANN is a later optimisation).
- Retrieval quality is measured on one Python repo with 36 questions (see docs/benchmarks/retrieval.md); neural-embedding retrieval is unmeasured.
- The in-memory search index (BM25 + vectors) is built on the first query after (re)indexing and cached per process (4 repos).
