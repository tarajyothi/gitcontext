# GitContext

**A codebase intelligence copilot.** Connect a GitHub repository, and ask questions about it. Answers are generated from retrieved code and cite exact file paths and line ranges. When the evidence isn't there, GitContext says so instead of guessing.

> **Status:** Day 3 of 8 complete: ingestion, code-aware chunking and embedding storage work. Hybrid retrieval, reranking and RAG answering are **not built yet** (see [Roadmap](#roadmap)). Retrieval/answer quality: **NOT MEASURED YET**. No quality metrics have been measured: **NOT MEASURED YET**.

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
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/health   (interactive docs: /docs)

# Frontend (new terminal)
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

Optional Postgres + pgvector (needed from Day 3): `docker compose up -d`, then set `DATABASE_URL` in `.env`.

## Tests
```bash
cd backend && source .venv/bin/activate && python -m pytest -q
```

## API
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + DB connectivity. `200 {"status":"ok",...}` or `503` if DB is down |
| POST | `/repositories` | Body `{"url": "https://github.com/owner/repo"}`. Validates, shallow-clones into `WORKSPACE_DIR`, scans, stores metadata. `201` summary |
| GET | `/repositories` · `/repositories/{id}` | Repository summaries (status, commit, file count, language breakdown) |
| GET | `/repositories/{id}/files?limit&offset` | Indexed files: path, language, size, modified/indexed time |

Ingestion errors: `invalid_url` (422), `repo_not_accessible` (404; GitHub gives the same answer for private and non-existent repos), `repo_empty` (422), `no_supported_files` (422), `clone_timeout` (504), `clone_failed` (502). Only public `https://github.com/owner/repo` URLs are accepted.

| POST | `/repositories/{id}/index` | Chunk every indexable file, embed, store. Idempotent (replaces previous chunks). Returns counts, model, timings |
| GET | `/repositories/{id}/chunks?path&limit&offset` | Inspect stored chunks (file, symbol, kind, exact line range, content) |
| POST | `/repositories/{id}/search` | `{"query","k"}` vector-only cosine search (verification endpoint; hybrid retrieval is Day 4) |

**Ignored during scan:** `.git`, `node_modules`, build/cache dirs, binaries, lockfiles, files over 1 MB, symlinks, and secret-like files (`.env*`, `*.pem`, `*.key`, `id_rsa`, …). Max 5000 files per repo.

All errors share one shape: `{"error": {"code", "message", "request_id", "details?"}}`. Internals are never leaked to clients.

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
- [ ] Day 4: Hybrid retrieval + reranking
- [ ] Day 5: RAG answering + citations
- [ ] Day 6: Evaluation + reliability
- [ ] Day 7: UI + deployment
- [ ] Day 8: Docs, demo, release

## Limitations (current)
- Ingestion is synchronous (the request blocks while cloning); background jobs are not implemented.
- Public repositories only; private repo support is not implemented.
- `modified_at` is the checkout time (git clone resets file times), not the last-commit time.
- Files without a known extension are stored with `language = null`.
- **Default embedder is not a neural model.** It is a deterministic, identifier-aware feature-hashing baseline: good at exact/partial identifier and word overlap, weak at paraphrase-level meaning. Neural embeddings need `EMBEDDING_PROVIDER=openai` + `EMBEDDING_API_KEY` (code path unit-tested with a mock; **not yet run against a live API**).
- Chunking: Python (ast), JS/TS (declaration scanner; regex literals containing quotes can confuse it), Markdown (headings). Other languages use 60-line windows with 10-line overlap. Large classes split per method (Python only); other oversized chunks split into `(part N)`.
- Vector search is brute-force NumPy cosine over all chunks of a repo (fine at this scale; pgvector/ANN is a later optimisation).
- No retrieval or answer quality metrics yet.
