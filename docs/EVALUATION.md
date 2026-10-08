# Evaluation summary

Everything here was measured; anything not measured says so. Details, methods and failure lists are in the linked documents.
All benchmarks use one public repository (`pallets/click`, Python) and were authored by the system's builder, with questions frozen
**before** the code they test (git history shows the order).

| What | Result | Detail |
|---|---|---|
| Retrieval, held-out (12 questions) | Recall@1 0.58, **Recall@5 0.83**, MRR 0.69 | [retrieval](benchmarks/retrieval.md) |
| Retrieval, dev (24, tuned on) | Recall@5 0.83, MRR 0.55 | same |
| Retrieval ablation (held-out R@5) | vector only 0.42 -> BM25 0.50 -> naive hybrid 0.50 -> **hybrid + rerank 0.83** | same |
| Retrieval on a newer upstream commit (all 36) | R@5 0.83, MRR 0.60 | same |
| Refusing unanswerable questions (24) | **23 / 24** refused (dev 12/12, held-out 11/12) | [answering](benchmarks/answering.md) |
| Wrongly refusing answerable questions (36) | 6 / 36 (17%) | same |
| Answerable questions answered with a correct source cited (36) | 25 / 36 (69%) | same |
| Citation integrity | every citation maps to a retrieved chunk and its exact lines (tests); 0 malformed in benchmarks | tests, benchmarks |
| Incremental indexing, two real `click` commits | 7 / 170 files changed; **448 of 1,693 chunks reprocessed, 1,245 reused (73.5%)**; 0.59 s vs 1.6 s full | `scripts/incremental_demo.py` |
| Latency (sandbox, 1 worker) | search p50 ~10 ms alone; p50 435 ms / p95 531 ms at 20 concurrent users over HTTPS; ~48 req/s mixed | [deployment](deployment.md) |
| Automated tests | **159** (158 on SQLite + 1 PostgreSQL-only; the real-GitHub test also passes when network is allowed) | CI workflow |
| Real-browser E2E | **22 / 22** steps over HTTPS on the production build; post-deploy smoke test 20 / 20 | `e2e/`, `scripts/smoke_test.py` |
| Static analysis / dependencies | ruff clean, bandit 0 medium/high, pip-audit clean, npm audit 0 (runtime) | [security](security.md) |
| Backup and restore | dump/restore on PostgreSQL with identical row counts | [deployment](deployment.md) |

## Not measured (do not quote)
- Retrieval or answer quality with **neural embeddings** and **LLM-written answers** (no API key was available; code paths are tested with mocked APIs only).
- Anything on a **live deployment**: no public URL exists yet.
- Other languages or repositories; larger repositories (5,000-file cap, 50 MB source on Free).
- Real user behaviour, concurrency beyond the 20-user load test, long-running stability.

## Known weaknesses (measured)
The lexical retrieval/gate cannot bridge vocabulary gaps ("unlimited number of values" vs `nargs=-1`): 2 of 12 held-out retrieval misses and
most false refusals. One near-miss unanswerable question ("two factor authentication") was wrongly answered. With n=12 held-out questions the
0.83 figures carry roughly +/-0.2 uncertainty.
