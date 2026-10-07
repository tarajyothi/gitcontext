# Security review

Scope: the GitContext web app (Next.js), API (FastAPI), PostgreSQL, and the repository-ingestion pipeline. Every row names the
automated test that exercises the control. "Accepted / open" lists what is **not** covered.

## Threat model
| Threat | Controls | Tests |
|---|---|---|
| Account takeover, credential stuffing | scrypt hashes; generic login errors + dummy hash (no user enumeration); 5 failures/15 min per IP+email; signup limit per IP; random 256-bit session token, only its SHA-256 stored; HttpOnly + SameSite=Lax (+ Secure, HSTS in production); logout deletes the session server-side | `test_auth.py`, `test_reliability.py::test_write_and_signup_limits` |
| Reading or changing another tenant's data | every repository route resolves the id **inside the caller's workspace**; foreign and missing ids both return 404; search index cache keyed by version stamp and invalidated on re-index/delete | `test_ownership.py` (all routes x non-owner/anonymous/forged ids), `test_retrieval.py::test_cache_never_serves_another_repository...` |
| Hostile repository contents | symlinks never followed; binaries, lockfiles, secret-named files, files >1 MB skipped; 5,000-file and plan byte caps; 800 MB checkout cap; hostile file names treated as data; credential patterns masked before storing/embedding/showing | `test_security.py` (symlink escape, hostile names, caps, redaction), `test_ingest_unit.py` |
| Prompt injection via repository text | content is escaped (opening and closing structural tags), numbered, marked `untrusted`; system prompt forbids following it; LLM output must cite provided chunks, use only identifiers present in the evidence, and not be mostly uncited; otherwise an extractive answer is shown; refusals call no model | `test_answering.py` (tag breakout, hijacked model, invented identifiers) |
| SSRF / command injection through the repo URL | strict `https://github.com/owner/repo` allow-list, `--` before the URL, `GIT_ALLOW_PROTOCOL=https`, hooks disabled, `transfer.fsckObjects`, no prompts, 120 s timeout | `test_ingest_unit.py` (13 hostile URLs), `test_reliability.py::test_git_runs_with_safe_defaults` |
| Resource exhaustion | per-user rate limits (search/ask/write) with `Retry-After`; daily question quota and repository/storage limits per plan; 64 KB body limit; bounded clone retries; PostgreSQL `statement_timeout` (verified to cancel a slow query); one-worker design documented | `test_reliability.py`, `test_plans_usage.py`, `test_production.py` |
| Information leakage | uniform error envelope; unhandled errors return a generic 500 (stack stays in server logs); API docs disabled in production; no secrets in the browser bundle; `.env*` never committed | `test_health.py`, `test_production.py`, browser run over HTTPS |
| Browser attacks (XSS, clickjacking, MITM) | React escaping; CSP (`default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`); X-Frame-Options, nosniff, Referrer-Policy; HSTS; same-origin API via the proxy (no CORS in production); JSON-only API + SameSite=Lax cookie | `test_production.py`, smoke test, 22-step browser flow over HTTPS |
| Vulnerable dependencies | `pip-audit` and `npm audit` run in CI | see below |

## Dependency audit (run during this review)
- Backend: **no known vulnerabilities** after upgrading FastAPI 0.115 -> 0.142 and Starlette 0.41 -> 1.7 (the old Starlette had 12 advisories).
- Frontend runtime: **0 vulnerabilities** after upgrading Next.js 14.2.18 -> 16.3.8 (14.x had critical advisories) and React 18 -> 19.
- Frontend build tooling: Tailwind CSS 3 pulls in glob/regex packages with ReDoS advisories (7 findings, build-time only, never shipped, run on our own source). Accepted; fix is the Tailwind 4 migration.

## Accepted / open risks
- No CSRF token (relies on SameSite=Lax and a JSON-only API); no email verification, password reset or 2FA.
- Rate limiters, sessions' brute-force counters and background jobs are in-process: a single backend instance only.
- Secret redaction is pattern-based (AWS, GitHub, Slack, Stripe, Google, LLM keys, private keys). Unknown formats pass through; only public repositories are supported.
- The verifier proves a claim cites real evidence, not that the claim is true.
- Question text and answers are stored per workspace.
- SonarQube was not available in the development environment; static analysis used ruff (security rules) and bandit instead.

## Reporting
Open a private security advisory on the repository.
