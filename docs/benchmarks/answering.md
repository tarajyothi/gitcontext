# Answering benchmark

**What this measures:** the full `POST /repositories/{id}/ask` path: does GitContext (a) answer questions the repository
can answer and cite a correct source, and (b) **refuse** questions the repository cannot answer?

## Method
- Repository: `pallets/click` (run on upstream `2247b35`; ground truth revalidated against the indexed chunks, 0 questions dropped).
- **Answerable:** the 36 questions in `click_questions.json` (24 dev / 12 held-out).
- **Unanswerable:** 24 questions in `unanswerable_questions.json` (12 dev / 12 held-out), frozen and committed (`15ee795`) **before any
  answering code existed**. Each asks about something absent from the repo (verified: the key terms occur nowhere at either snapshot):
  18 absent technologies (SMTP, GraphQL, Redis, Stripe, ...), 5 near-misses that reuse generic words (retries with backoff, telemetry,
  rate limiting, feature flags, undo history, two-factor auth) and 1 off-topic request.
- Generator under test: the built-in **extractive** answerer (no LLM; see Limitations).
- The evidence-gate threshold (idf-weighted share of the question's terms found in the retrieved chunks, `EVIDENCE_MIN_COVERAGE`) was
  checked on dev only. It was set to 0.6 before the sweep and the sweep confirmed it as the dev optimum. The held-out split was
  evaluated once, after that; it is now consumed, so no further tuning was done.

## Gate sweep (dev only)
| threshold | unanswerable correctly refused | answerable wrongly refused |
|---|---|---|
| 0.4 | 0.50 | 0.00 |
| 0.5 | 0.75 | 0.04 |
| **0.6 (shipped)** | **1.00** | **0.12** |
| 0.7 | 1.00 | 0.17 |
| 0.8 | 1.00 | 0.33 |

The two groups overlap (highest unanswerable coverage 0.58, lowest answerable 0.47), so no threshold is perfect.

## Results
| | Dev | Held-out test | Combined |
|---|---|---|---|
| Unanswerable correctly refused | 12/12 | 11/12 | 23/24 (0.96) |
| Answerable wrongly refused | 3/24 | 3/12 | 6/36 (0.17) |
| Answerable answered **with a correct source cited** | 16/24 | 9/12 | 25/36 (0.69) |
| Answered but cited the wrong code | 5/21 | 0/9 | 5/30 |
| Malformed citations | 0 | 0 | 0 |

## Failures
- Wrongly refused (vocabulary gaps between the question and the code): "generate the help text" (q04), "progress bar drawn" (q07), "group finds the
  subcommand" (q14), "exit with a specific code" (q29), "unlimited number of values" (q30), "shared object to subcommands" (q31).
- Wrongly answered: "How is two factor authentication enforced for a command?" (coverage 0.71 from generic words). A near-miss leaked through.
- In extractive mode, "answered" means *the most relevant code was shown with its docstring summary*. When retrieval misses (5 dev cases), the
  cited code is relevant-looking but wrong. This is not a synthesized answer.

## What is guaranteed vs measured
- **Guaranteed by construction/tests (not a sampled metric):** every citation refers to a retrieved chunk and its exact lines; refusals call no
  generator; LLM output is rejected unless every claim-bearing sentence cites provided evidence and every backticked identifier exists in it.
- **Measured here:** refusal behaviour of the gate and source correctness of the extractive answer.
- **NOT measured (no LLM key was available):** real LLM answer quality, faithfulness, citation precision of generated prose, and how often the
  verifier rejects good answers. The LLM path is unit-tested only with a mocked API.

## Limitations
One repository, 60 questions, authored by the system's builder. Absent-topic negatives are easy; hard near-misses are few (6). The lexical gate
cannot tell "uses the same words" from "answers the question". Using the LLM itself to judge sufficiency (it may reply `INSUFFICIENT_EVIDENCE`)
and neural embeddings are the expected improvements.

## Reproduce
```bash
cd backend && DAILY_QUESTION_LIMIT=500 uvicorn app.main:app --port 8000 &
python benchmarks/run_answer_benchmark.py --split dev --failures
python benchmarks/run_answer_benchmark.py --split test --failures
python benchmarks/tune_gate.py <repo_id>      # dev-only threshold sweep
```
