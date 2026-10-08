# Day 6: hardening, incremental indexing, security

## What was built
- **Incremental indexing:** content-hash diff on every re-index; only new/changed files are re-chunked and re-embedded; removed files lose chunks and vectors; file updates and chunk replacement commit in one transaction (a failed run leaves the old index intact and the next run recovers). A signature of chunker version + embedding model forces a full rebuild when either changes.
- **Plans and usage:** Free / Pro / Team entitlements (no billing; `set_plan()` is the integration point), per-workspace counts of questions, storage and LLM tokens (Anthropic usage captured when the LLM is used).
- **Reliability:** per-user rate limits with `Retry-After`, `/ready`, JSON logs with request ids, PostgreSQL `statement_timeout`, clone retries with backoff (never for not-found), checkout size cap, `https`-only git protocol, hooks off, object fsck.
- **Secret redaction:** AWS, GitHub, Slack, Stripe, Google, LLM keys and private-key blocks are masked before storage, embedding and display (line counts preserved).
- **Dependencies:** audit found 12 Starlette advisories and critical Next.js 14 advisories; upgraded to FastAPI 0.142 / Starlette 1.7 and Next.js 16.3.8 / React 19 (0 known runtime vulnerabilities).
- **Migration 0002** (verified on a legacy database that already held data), security review ([security.md](security.md)), CI audits.

## Evidence
- Real run in the UI ([screenshots](images), `day6-demo.mp4`): first index full, 14 chunks, **4 secrets masked**, hostile symlink skipped; after editing 1 file, adding 1, deleting 1: **incremental, 2 new/changed, 1 removed, 5 unchanged, 10 of 16 chunks reused**; new code searchable at once; 4th question in a minute **rate-limited**.
- Real repository: two `pallets/click` commits, 7 of 170 files changed, 73.5% of chunk work avoided.
- Tests: 158 (SQLite) / 159 (PostgreSQL). New: incremental (atomicity, no-op, model change, crash recovery), security (symlinks, hostile names, redaction, API abuse, SQL metacharacters), reliability, plans/usage.
- Bugs found by the work itself: stale search cache could serve another repo's results after delete+recreate (fixed, regression test mutation-checked); prompt-tag forgery gap; auth redirect used `http://` behind TLS (found by a real browser).

## Limits
Single backend worker; limiter and jobs are in-process; clone is still a full shallow clone each re-index (the saving is chunking and embedding); redaction is pattern-based; no billing, email verification, password reset or 2FA.
