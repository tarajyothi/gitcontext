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
