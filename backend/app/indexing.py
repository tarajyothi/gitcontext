"""Chunk + embed + store a previously ingested repository; vector search over stored embeddings."""
import logging
import time
from collections import Counter

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .chunking import chunk_file
from .embeddings import Embedder
from .ingest.errors import IngestError
from .ingest.service import workspace_path
from .retrieval import invalidate
from .models import Chunk, ChunkEmbedding, RepoFile, Repository, utcnow

log = logging.getLogger("gitcontext.index")


def embed_text(c: Chunk) -> str:
    """Text sent to the embedder: location + symbol context + exact code (stored content is untouched)."""
    head = f"{c.file_path}\n{c.symbol or ''} {c.symbol_kind} {c.language or ''}\n"
    return (head + c.content)[:8000]


def index_repository(session: Session, repo_id: int, embedder: Embedder, batch_size: int = 64,
                     check_ready: bool = True) -> dict:
    t0 = time.perf_counter()
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise IngestError("not_found", "Repository not found", 404)
    if check_ready and repo.status != "ready":
        raise IngestError("repo_not_ready", "Repository must be ingested successfully before indexing.", 409)
    root = workspace_path(repo.id, repo.owner, repo.name)
    if not root.is_dir():
        raise IngestError("workspace_missing", "Repository files are no longer on disk. Re-ingest it first.", 409)

    session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.repository_id == repo_id))
    session.execute(delete(Chunk).where(Chunk.repository_id == repo_id))
    rows, skipped = [], Counter()
    for f in session.scalars(select(RepoFile).where(RepoFile.repository_id == repo_id, RepoFile.language.is_not(None))):
        path = (root / f.path).resolve()
        if root not in path.parents or not path.is_file():
            skipped["missing_or_unsafe"] += 1
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:8000]:
            skipped["binary"] += 1
            continue
        for c in chunk_file(f.path, raw.decode("utf-8", errors="replace"), f.language):
            rows.append(Chunk(repository_id=repo_id, file_id=f.id, file_path=c.file_path, symbol=c.symbol,
                              symbol_kind=c.kind, language=c.language, start_line=c.start_line,
                              end_line=c.end_line, content=c.content, content_hash=c.content_hash))
        f.indexed_at = utcnow()
    session.add_all(rows)
    session.flush()
    t_chunk = time.perf_counter()

    dim = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        mat = embedder.embed([embed_text(c) for c in batch]).astype(np.float32)
        dim = mat.shape[1]
        session.add_all(ChunkEmbedding(chunk_id=c.id, repository_id=repo_id, model=embedder.name, dim=dim,
                                       vector=mat[k].tobytes()) for k, c in enumerate(batch))
    session.commit()
    invalidate(repo_id)
    t_end = time.perf_counter()
    stats = {"repository_id": repo_id, "files_indexed": len({c.file_id for c in rows}), "chunks": len(rows),
             "embeddings": len(rows), "model": embedder.name, "dim": dim,
             "by_kind": dict(Counter(c.symbol_kind for c in rows)), "skipped": dict(skipped),
             "chunk_seconds": round(t_chunk - t0, 3), "embed_seconds": round(t_end - t_chunk, 3)}
    log.info("indexed %s", stats)
    return stats


def chunk_dict(c: Chunk, score: float | None = None) -> dict:
    d = {"chunk_id": c.id, "file_path": c.file_path, "symbol": c.symbol, "kind": c.symbol_kind,
         "language": c.language, "start_line": c.start_line, "end_line": c.end_line, "content": c.content}
    if score is not None:
        d["score"] = round(float(score), 4)
    return d


def vector_search(session: Session, repo_id: int, query: str, k: int, embedder: Embedder) -> list[dict]:
    """Vector-only cosine search (hybrid retrieval + reranking arrive on Day 4)."""
    rows = session.execute(select(ChunkEmbedding.chunk_id, ChunkEmbedding.vector).where(
        ChunkEmbedding.repository_id == repo_id, ChunkEmbedding.model == embedder.name)).all()
    if not rows:
        raise IngestError("not_indexed", "No embeddings for this repository and model. Index it first.", 409)
    ids = [r[0] for r in rows]
    mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    scores = mat @ embedder.embed([query])[0]
    top = np.argsort(-scores)[:k]
    by_id = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_([ids[i] for i in top])))}
    return [chunk_dict(by_id[ids[i]], scores[i]) for i in top]
