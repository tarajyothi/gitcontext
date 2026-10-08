# Launch checklist (Day 7 gate)

**Verdict: release candidate. NOT launched: there is no live URL.** Everything below that can be proven on one machine has been; the
single blocker is hosting (a server with Docker and a domain).

## Launch gate
| Gate | Status | Evidence |
|---|---|---|
| Live URL loads | **BLOCKED** | not deployed. `docker-compose.prod.yml` + `deploy/Caddyfile` ready; verified as a bare-metal equivalent (PostgreSQL + FastAPI + Next.js standalone + Caddy TLS), Docker images never built |
| Auth works | PASS (local HTTPS) | smoke test, 22-step browser flow |
| Ingestion works | PASS | `pallets/click`: 170 files, 1,693 chunks, states observed in the UI |
| Retrieval works | PASS | held-out Recall@5 0.83 (n=12), MRR 0.69 |
| RAG works | PARTIAL | extractive answers measured; **LLM answers implemented and mock-tested, not measured** (no key) |
| Citations work | PASS | exact lines verified against source (tests + sed check on 1,673 chunks) |
| Unanswerable handling | PASS (with caveat) | 23/24 refused; 6/36 answerable questions wrongly refused |
| Errors understandable | PASS | invalid URL, failed repo + Retry, rate limit, expired session verified in the browser |
| No critical security issue | PASS (no known) | [security.md](../security.md); open risks listed there |
| Fresh-browser test | PASS locally / **BLOCKED live** | fresh Chromium context over HTTPS on the production build; must be repeated on the live URL |

## Final acceptance gate (plan section 13)
| Area | Requirement | Status |
|---|---|---|
| Product | Live SaaS, live URL works from a fresh browser | BLOCKED (not deployed) |
| GitHub | Real public repository imports | PASS |
| AI | Relevant code in top-K | PASS (R@5 0.83 held-out) |
| AI | Answer grounded in evidence | PASS (extractive); LLM unmeasured |
| Evidence | File + exact lines map to source | PASS |
| Safety | Unsupported claims refused | PASS (23/24) |
| Reliability | Timeout/error/retry behaviour tested | PASS |
| Security | No exposed secrets or unauthorized access | PASS (tests + audits) |
| Evaluation | Results reproducible, not fabricated | PASS (scripts + frozen questions + caveats) |
| Deployment | Frontend/backend/database work together | PASS locally; live BLOCKED |
| Recruiter | Ingest -> ask -> retrieve -> cite -> answer demo | PASS (recorded video) |

## To go live (about an hour)
1. Server with Docker + a domain A record pointing at it. 2. `cp .env.production.example .env`; set `DOMAIN`, `POSTGRES_PASSWORD`.
3. `docker compose -f docker-compose.prod.yml up -d --build`. 4. `python backend/scripts/smoke_test.py https://your-domain` must print `SMOKE TEST PASSED`.
5. Walk the flow once in an incognito window. 6. Replace the rc tag with `v1.0.0` and update the README "Live demo" line.
