# Architecture & Design Decisions

## Pipeline (target)
1. **Ingest**: validate GitHub URL, clone into `WORKSPACE_DIR`, scan, filter (`.git`, binaries, `node_modules`, secrets), detect language, record metadata.
2. **Chunk**: parse supported languages into function/class/module chunks with exact line ranges; fall back to a line-window chunker elsewhere.
3. **Embed & store**: embeddings + metadata in Postgres/pgvector.
4. **Retrieve**: vector search + keyword/BM25 search → merge → dedupe → metadata filters → rerank.
5. **Answer**: LLM sees only retrieved evidence, must cite `path:start-end`, and returns an insufficient-evidence response when support is missing.
6. **Evaluate**: frozen question set; Recall@K, citation accuracy, answer correctness, latency.

## Decisions (Day 1)
| Decision | Why |
|---|---|
| FastAPI | Typed, auto-generated docs, easy testing |
| SQLAlchemy 2.0 with SQLite default | A fresh clone runs with no services; same models target Postgres |
| pgvector (not a separate vector DB) | One datastore for relational + vector + metadata filters; less infrastructure |
| Denormalised `chunks.file_path` | Citations need no join |
| DB `CHECK(end_line >= start_line)` | Guarantees chunk traceability at the storage layer |
| Uniform JSON error envelope + request IDs | Debuggable, no internal leakage |
| Embedding column deferred to Day 3 | Dimension depends on the embedding model chosen then |

## Security stance
Repository content is untrusted: it is passed to the LLM strictly as quoted data, never as instructions. Secrets only via environment variables.

## Day 3 decisions: chunking & embeddings
| Decision | Why |
|---|---|
| Chunk = exact contiguous line range; `content == lines[start-1:end]` | Citations must map back to real lines; enforced by tests and a real-repo verifier |
| Python via `ast`; JS/TS via brace-aware scanner; Markdown by heading | Semantic units (function/class/method/section) without heavy parser dependencies |
| Large class -> per-method chunks (`Class.method`); oversized chunk -> `(part N)` | Keeps chunks small enough to embed and cite precisely |
| Leading comments/decorators attach to the symbol | Preserves docs and behaviour-changing decorators |
| Parse failure -> line-window fallback (never crash indexing) | Robustness on arbitrary repos |
| Embedding text = path + symbol + kind + code; stored `content` stays exact | Embeddings get location context without corrupting citations |
| Embeddings in `chunk_embeddings` BLOB, NumPy cosine | No new infrastructure; portable SQLite/Postgres; swap to pgvector later |
| Default hashing embedder, pluggable OpenAI-compatible provider | Works offline and reproducibly; sandbox had no embedding API access/key |

## SaaS core decisions
| Decision | Why |
|---|---|
| Server-side sessions (hashed token in HttpOnly cookie) over JWT | Real logout/revocation; nothing sensitive in the browser |
| Next.js `/api` rewrite proxy | First-party cookies, no CORS, backend URL stays server-side |
| Ownership resolved by `WHERE id=? AND workspace_id=?`; 404 for foreign IDs | One enforcement point (`owned_repo`), no ID enumeration |
| `POST /repositories` returns 202 + background pipeline writing `status`/`stage` | The UI shows real progress instead of blocking or faking it |
| Workspace dir `{repo_id}__{owner}__{name}` | Two users indexing the same repo never share or delete each other's clone |
| Startup marks pending/indexing repos failed | A crash can never leave a repo "indexing" forever |
| Free-plan limits (5 repos, 50 MB indexed source) as config | Entitlement boundary without fake billing |

## Retrieval decisions
| Decision | Why |
|---|---|
| Three channels (vector, BM25 with identifier splitting, exact-symbol match) fused by weighted RRF | Code queries mix concepts and exact names; no single signal covers both |
| Channel weight comes from the embedder (`retrieval_weight`) | Measured: equal weights let the weak lexical embedder hurt BM25; neural embeddings should get full weight |
| Dedupe overlapping chunks of the same file before reranking | Avoids showing a class and its method as two "different" results |
| Heuristic reranker with transparent `signals` | No cross-encoder available offline; every adjustment is inspectable and measured in an ablation |
| Benchmark frozen before implementation, dev/held-out split | Prevents tuning to the test set; documents limits honestly |
| In-memory corpus cache keyed by (repo, chunk count, max chunk id, model) | Re-indexing changes chunk ids, so stale caches cannot be served |

## Answering decisions
| Decision | Why |
|---|---|
| Evidence gate before any generation | Refusing is cheaper and safer than generating and hoping; absent topics never reach a model |
| Extractive answerer as default and as fallback | Faithful by construction, works offline; the LLM path can never be worse than showing the evidence |
| Verifier on LLM output (citations, line ranges, identifiers, uncited share) | Catches the most damaging failure, invented names and unsupported claims, without trusting the model |
| Repo text delimited, escaped (opening and closing tags), marked untrusted | Prompt-injection hygiene. A test found forged opening tags were not escaped; fixed |
| Question history stored with answers and citations | Activity feed, daily limits, and reproducibility |
| Unanswerable-question benchmark frozen first | Refusal quality is measurable; avoids tuning the gate to the test set |
