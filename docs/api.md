# API reference

Base path: `/api` behind the proxy (the backend itself serves the same routes without the prefix). JSON in, JSON out. Authentication is a
session cookie (`gc_session`, HttpOnly) set by signup/login, so use `curl -c jar -b jar`. Interactive docs (`/docs`) exist in development only.

```bash
B=https://your-domain/api; J='-H content-type:application/json'
curl -c jar $J -d '{"email":"me@example.com","password":"correct-horse-1"}' $B/auth/signup
curl -b jar $J -d '{"url":"https://github.com/pallets/click"}' $B/repositories            # 202, status "pending"
curl -b jar $B/repositories/1                                                                # poll: pending > indexing (stage) > ready | failed
curl -b jar $J -d '{"query":"how is a progress bar rendered","k":5}' $B/repositories/1/search
curl -b jar $J -d '{"question":"How do I ask the user a yes or no confirmation question?"}' $B/repositories/1/ask
curl -b jar $B/usage
```

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/signup`, `/auth/login` | `{"email","password"}` (password 8-128 chars). Login: 5 failures / 15 min per IP+email. Signup: limited per IP |
| POST | `/auth/logout` · GET `/auth/me` | Destroys the server-side session · current user and workspace |
| POST | `/repositories` | `{"url":"https://github.com/owner/repo"}` -> **202**. Public repos only. Errors: `invalid_url` 422, `duplicate_repository` 409, `repo_limit_reached` 403 |
| GET | `/repositories`, `/repositories/{id}` | Own repositories. Fields: `status`, `stage`, `error_message`, `file_count`, `chunk_count`, `languages`, `commit_sha`, `last_index` (mode `full`/`incremental`, new/changed/removed/unchanged, chunks reused, seconds, truncated, redacted_secrets) |
| POST | `/repositories/{id}/reindex` | Re-clone and re-index. **Incremental**: only changed files are re-chunked/re-embedded. Also the retry path for `failed`. 409 while indexing |
| DELETE | `/repositories/{id}` | Removes rows and the clone. 409 while indexing |
| GET | `/repositories/{id}/files`, `/chunks` | `limit`, `offset`; `/chunks` also `path` |
| POST | `/repositories/{id}/index` | Re-chunk and re-embed from the existing clone (always full) |
| POST | `/repositories/{id}/search` | `{"query","k":1-50,"mode":"hybrid\|vector\|bm25","rerank":true,"filters":{"language":[],"path_prefix":"","kinds":[],"exclude_tests":false,"exclude_docs":false}}` -> chunks with `file_path`, `start_line`, `end_line`, `symbol`, `kind`, `content`, `score`, `signals` |
| POST | `/repositories/{id}/ask` | `{"question"}` (3-1000 chars) -> `status` `answered` \| `insufficient_evidence`, `answer` with `[n]` markers, `generation` `extractive` \| `llm`, `citations[]` (file, exact lines, symbol, snippet), `evidence_coverage`, `warnings`, `closest`, `usage` (LLM tokens or null) |
| GET | `/repositories/{id}/questions` | History with stored answers and citations |
| GET | `/usage` | `plan`, repositories used/limit, `files_indexed`, `chunks_indexed`, `storage_bytes`, questions today / limit, `llm_tokens_today` |
| GET | `/health`, `/ready` | Liveness; readiness (database, migrations, writable workspace, disk). 503 when not ready |

## Errors
Every error: `{"error":{"code","message","request_id","details?"}}`. Internals and stack traces are never returned.
`not_authenticated`/`session_expired` 401 · `rate_limited` 429 (+`Retry-After`) · `daily_limit_reached` 429 · `repo_not_found` surfaces as 404 (also for other users' ids) ·
`payload_too_large` 413 · `validation_error` 422 · `llm_unavailable` 503 · indexing failures are stored on the repository (`repo_not_accessible`, `repo_empty`, `no_supported_files`, `repo_too_large`, `clone_timeout`, `clone_failed`).

## Limits (Free plan; Pro = 5x, Team = 20x)
5 repositories · 50 questions / 24 h · 50 MB indexed source · 120 searches/min, 30 asks/min, 20 writes/min per user · 64 KB request body.
