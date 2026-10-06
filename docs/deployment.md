# Deployment guide

**Status: NOT DEPLOYED.** Everything below was verified on a single machine (PostgreSQL 16 + Caddy 2 + the production
build of both services, over HTTPS with a self-signed certificate). It has not run on a hosting provider and the
Dockerfiles/compose file have **not been built on Docker** (no Docker in the development sandbox).

## What was verified (and how)
| Area | Result |
|---|---|
| Backend tests | 128 pass on SQLite **and** on PostgreSQL 16 |
| Migrations | Alembic baseline creates all tables on empty Postgres; `alembic check` reports no drift; downgrade/upgrade roundtrip works |
| Production deps | Backend runs with `requirements.txt` only (no pytest); Dockerfile steps executed by hand in clean directories |
| Fail-fast config | `ENVIRONMENT=production` refuses to start with `COOKIE_SECURE=false`, SQLite, missing `ALLOWED_HOSTS`, or a missing LLM key when an LLM is selected (tested, and demonstrated with a real process) |
| HTTPS stack | Caddy (TLS) -> Next.js standalone + FastAPI -> Postgres; Secure/HttpOnly/SameSite=Lax cookie, HSTS, CSP, X-Frame-Options, nosniff; API docs hidden; forged `Host` rejected |
| Real browser | 20/20 steps in Chromium over HTTPS (signup, indexing, search, cited answer, refusal, logout/redirects, re-index, errors, mobile) |
| Smoke test | `backend/scripts/smoke_test.py` passes against the HTTPS stack |
| Backup/restore | `pg_dump | gzip` then restore into a new database: identical row counts (users, repos, chunks, embeddings, questions) |
| Load (sandbox, 1 worker, 20 concurrent) | search p50 435 ms / p95 531 ms; ~48 req/s mixed; no errors; 429s only from the daily question limit |

Bugs the production verification found and fixed: auth redirect used `http://` behind the TLS proxy (browser SSL error), and
Next config/CSP needed to be production-only. Not verified: Docker image builds, a public domain/Let's Encrypt, any hosting platform.

## Deploy to a VPS (Docker + a domain)
1. Point a DNS A record (e.g. `app.example.com`) at the server; open ports 80 and 443.
2. `cp .env.production.example .env` and set `DOMAIN` and a long random `POSTGRES_PASSWORD`.
3. `docker compose -f docker-compose.prod.yml up -d --build`. The backend runs `alembic upgrade head` on start; Caddy obtains the certificate automatically.
4. **Verify the live URL:** `python backend/scripts/smoke_test.py https://app.example.com` must print `SMOKE TEST PASSED`.
5. Open the URL in a fresh browser/incognito window and walk through signup -> connect repo -> ask.

Optional AI: set `LLM_PROVIDER=anthropic` and `LLM_API_KEY` (answers are then LLM-written and verifier-checked; not yet measured) and/or `EMBEDDING_PROVIDER=openai` + `EMBEDDING_API_KEY`.

## Configuration reference
| Variable | Purpose |
|---|---|
| `ENVIRONMENT=production` | Fail-fast validation, docs disabled, no CORS, security headers |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` |
| `COOKIE_SECURE=true` | Required in production (HTTPS only cookies + HSTS) |
| `ALLOWED_HOSTS` | Comma-separated domain allow-list |
| `DAILY_QUESTION_LIMIT`, `MAX_REPOS_PER_WORKSPACE`, `MAX_INDEXED_BYTES` | Free-plan limits |
| `LLM_*`, `EMBEDDING_*` | Optional AI providers (keys stay server-side) |

## Operations
- **Health:** `GET /api/health` (200 and `database: ok`). Container healthcheck included. Logs are one line per request with a request id (path only; no query strings, cookies or bodies).
- **Backups:** `docker compose -f docker-compose.prod.yml exec -T db pg_dump -U gitcontext gitcontext | gzip > backup-$(date +%F).sql.gz` (restore command in `deploy/backup.sh`). Cloned repositories live in the `workspace` volume and can be re-created by re-indexing.
- **Rollback:** redeploy the previous image tag; migrations are additive so far (baseline only). Take a backup before any future migration.
- **Updates:** `git pull && docker compose -f docker-compose.prod.yml up -d --build`.

## Known limitations before real traffic
- **One backend worker** by design: background indexing jobs, the login rate limiter and the search cache are in-process. Scaling out needs a job queue and shared rate-limit state.
- A restart marks in-flight indexing jobs `failed` (users retry); there is no durable queue.
- No email verification, password reset, or CSRF token (relies on SameSite=Lax and a JSON-only API).
- No error tracking or metrics endpoint yet; uptime monitoring should poll `/api/health`.
- Question text and answers are stored in the database (mention in your privacy policy).
- Default answers are extractive; LLM answer quality is unmeasured.
