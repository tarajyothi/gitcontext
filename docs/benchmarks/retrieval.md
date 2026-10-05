# Retrieval benchmark

**What this measures:** given a natural-language developer question about a repository, does the correct code
(file + symbol) appear in the top results of `POST /repositories/{id}/search`? Citations are exact line ranges, so
a correct hit is directly citable.

## Method
- Repository: `pallets/click` (Python, 170 files, ~1.7k chunks), pinned snapshot **`06b2a67`** (2026-09-22).
- 36 questions in `backend/benchmarks/click_questions.json`: 4 identifier lookups, 23 concept questions, 9 behaviour questions.
  Each lists the acceptable `(file, symbol)` answers. A hit is correct when the chunk's file matches and its symbol
  (minus ` (part N)`) is listed.
- **The questions and ground truth were written from the source and committed (`e2848e0`) before any retrieval code existed.**
- **24 dev / 12 held-out test.** Weights were tuned on dev only (grid of 144 settings, mid-plateau values chosen, 37 settings
  within 0.02 MRR of the best). The held-out split was evaluated once, after the weights were locked.
- Metrics: Recall@k (answer in the top k), MRR@10. Latency is HTTP round-trip in a single-process sandbox with a warm in-memory index.
- Embedder: the built-in **lexical hashing baseline** (not neural; see Limitations).

## Results at the pinned snapshot (`06b2a67`)
| Configuration | Dev R@1 | Dev R@5 | Dev MRR | Test R@1 | Test R@5 | Test MRR |
|---|---|---|---|---|---|---|
| Vector only | 0.08 | 0.17 | 0.12 | 0.17 | 0.42 | 0.29 |
| BM25 only | 0.17 | 0.62 | 0.35 | 0.25 | 0.50 | 0.41 |
| Hybrid (RRF + dedupe) | 0.08 | 0.62 | 0.29 | 0.25 | 0.50 | 0.38 |
| **Hybrid + rerank (shipped)** | **0.33** | **0.83** | **0.55** | **0.58** | **0.83** | **0.69** |

Dev R@10 / R@3 for the shipped configuration: 0.92 / 0.75. Test R@10 / R@3: 0.83 / 0.83. Latency p50 ~10 ms, p95 ~14 ms.
Before tuning, dev was R@5 0.71 / MRR 0.40, so part of the dev gain is tuning; the held-out split is the fairer number.

Supplementary robustness check: upstream moved to `2247b35` (1,693 chunks). On all 36 questions the shipped configuration
scored R@1 0.42, R@5 0.83, MRR 0.60 (`--allow-drift`, ground truth revalidated).

## What the ablation shows
1. **Naive hybrid fusion did not beat BM25 alone.** Equal-weight RRF let the weak lexical embedder drag results down
   (dev R@5 0.46 before the fix). Weighting the vector channel by embedder quality (0.15 for the baseline, 1.0 for neural embeddings) fixed that.
2. **The reranker is where most of the gain comes from** (R@5 0.62 -> 0.83 dev, 0.50 -> 0.83 test). It demotes tests/docs/examples
   for "where is X implemented" questions, prefers implementation directories, and rewards exact symbol/path matches.
3. Exact-identifier queries (`HelpFormatter.write_dl`, `split_arg_string`) are solved (4/4 at rank 1).

## Known failures
Test-split misses: *"arguments that accept an unlimited number of values"* (the code says `nargs=-1`/`_unpack_args`) and
*"pass a shared object from a group to subcommands"* (the code says `ensure_object`/`pass_obj`). Both are vocabulary gaps between
natural language and code that lexical matching cannot bridge. Neural embeddings or query expansion are the expected fix.

## Limitations (read before quoting these numbers)
- **One repository, one language, 36 questions** (12 held-out). With n=12 the 95% interval around 0.83 is roughly 0.55-0.95.
- Questions were written by the system's author, which risks unconscious bias, even though they were frozen first.
- The reranker is a hand-built heuristic with repo-layout priors (`src/`, `tests/`, `docs/`); it may not transfer to repos laid out differently.
- The default embedder is lexical. The OpenAI-compatible path is unit-tested with a mock but has **never been run against a live API**, so neural-embedding retrieval is **not measured**.
- Answer quality (generation, citation faithfulness, refusal when evidence is missing) is **not built or measured yet**.

## Reproduce
```bash
cd backend && uvicorn app.main:app --port 8000 &
python benchmarks/run_benchmark.py --split dev            # tuning split
python benchmarks/run_benchmark.py --split test --failures # held-out split
python benchmarks/run_benchmark.py --split all --allow-drift  # if upstream HEAD moved
python benchmarks/tune.py <repo_id>                        # dev-only weight grid search
```
The app always clones the default branch, so exact numbers can shift as upstream changes; the runner refuses to run on a moved commit unless `--allow-drift` is given.
