# v1.0.0-rc1 (release candidate; not yet deployed)
**Features:** accounts and workspaces; GitHub ingestion with background indexing states; AST-aware chunking; hybrid retrieval with reranking; evidence-grounded answers with verified citations and refusals; incremental re-indexing; Free/Pro/Team limits and usage; rate limiting; secret redaction.
**Quality:** 159 tests (SQLite/PostgreSQL), 22-step browser E2E over HTTPS, smoke test, CI (lint, bandit, pip-audit, npm audit), frozen benchmarks with published failures.
**Security:** 0 known runtime vulnerabilities (Next.js 16.3.8, FastAPI 0.142, Starlette 1.7); threat model in `docs/security.md`.
**Known limits:** single backend worker; no email verification/password reset/2FA; LLM answers and neural embeddings implemented but unmeasured; one-repo benchmark; Docker images not yet built on a Docker host.
**Promotion to v1.0.0:** deploy, pass `smoke_test.py` on the live URL, repeat the fresh-browser walkthrough.
