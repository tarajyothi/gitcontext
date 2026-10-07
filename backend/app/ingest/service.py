"""Repository lifecycle: create (pending) -> background pipeline (indexing) -> ready | failed."""
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..plans import limits_for
from ..db import SessionLocal
from ..embeddings import Embedder, EmbeddingError
from ..models import Chunk, RepoFile, Repository, Workspace, utcnow
from .cloner import CloneResult
from .errors import IngestError
from .scanner import scan_repository
from .url import parse_github_url

log = logging.getLogger("gitcontext.ingest")
Cloner = Callable[[str, Path], CloneResult]


def workspace_path(repo_id: int, owner: str, name: str) -> Path:
    """Per-repository directory (id-prefixed so two users cloning the same repo never collide)."""
    return Path(get_settings().workspace_dir).resolve() / re.sub(r"[^A-Za-z0-9_.-]", "_", f"{repo_id}__{owner}__{name}")


def create_repository(session: Session, ws: Workspace, raw_url: str) -> Repository:
    owner, name = parse_github_url(raw_url)  # invalid_url (422) before anything is stored
    url = f"https://github.com/{owner}/{name}"
    limit = limits_for(ws.plan).repos
    if session.scalar(select(func.count()).select_from(Repository).where(Repository.workspace_id == ws.id)) >= limit:
        raise IngestError("repo_limit_reached", f"Your {limits_for(ws.plan).plan} plan allows {limit} repositories. Remove one to add another.", 403)
    if session.scalar(select(Repository).where(Repository.workspace_id == ws.id, Repository.url == url)):
        raise IngestError("duplicate_repository", "You have already connected this repository.", 409)
    repo = Repository(workspace_id=ws.id, url=url, owner=owner, name=name, status="pending")
    session.add(repo)
    session.commit()
    return repo


def _stage(session: Session, repo: Repository, stage: str) -> None:
    repo.status, repo.stage = "indexing", stage
    session.commit()


def _fail(session: Session, repo_id: int, message: str) -> None:
    session.rollback()
    repo = session.get(Repository, repo_id)
    if repo:  # may have been deleted while running
        repo.status, repo.stage, repo.error_message = "failed", None, message
        session.commit()


def run_pipeline(repo_id: int, cloner: Cloner, embedder: Embedder) -> None:
    """Clone -> scan -> persist files -> chunk + embed. Runs in a background task with its own session."""
    from ..indexing import index_repository, index_signature  # local import: indexing imports this module

    with SessionLocal() as session:
        repo = session.get(Repository, repo_id)
        if repo is None:
            return
        repo.error_message = None
        try:
            _stage(session, repo, "cloning")
            dest = workspace_path(repo.id, repo.owner, repo.name)
            if Path(get_settings().workspace_dir).resolve() not in dest.parents:  # explicit guard (assert is stripped by -O)
                raise IngestError("invalid_workspace_path", "Refusing to write outside the workspace.", 500)
            clone = cloner(repo.url + ".git", dest)
            if clone.commit_sha is None:
                raise IngestError("repo_empty", "The repository is empty (no commits).", 422)

            _stage(session, repo, "scanning")
            scan = scan_repository(clone.path)
            if not scan.files:
                raise IngestError("no_supported_files", "No indexable source files were found.", 422)
            plan = limits_for(session.get(Workspace, repo.workspace_id).plan)
            if sum(f.size_bytes for f in scan.files) > plan.max_indexed_bytes:
                raise IngestError("repo_too_large", f"This repository is too large to index on the {plan.plan} plan.", 413)
            # ---- incremental diff: compare content hashes with what is already indexed
            t_start = time.perf_counter()
            existing = {f.path: f for f in repo.files}
            scanned = {f.path: f for f in scan.files}
            signature = index_signature(embedder)
            full = repo.index_signature != signature or not existing  # chunker/embedding model changed, or first index
            removed = [p for p in existing if p not in scanned]
            added = [p for p in scanned if p not in existing]
            changed = [p for p in scanned if p in existing and (full or existing[p].content_hash != scanned[p].content_hash
                                                                 or existing[p].language != scanned[p].language)]
            unchanged = len(scanned) - len(added) - len(changed)
            _stage(session, repo, "embedding")  # commits the status only: no file/chunk changes yet
            # ---- apply file changes and replace chunks in ONE transaction (index_repository commits at the end)
            now = utcnow()
            for p in removed:
                session.delete(existing[p])  # cascades to its chunks (and their vectors)
            touched = []
            for p in changed:
                f, row = scanned[p], existing[p]
                row.language, row.size_bytes, row.content_hash, row.modified_at, row.indexed_at = f.language, f.size_bytes, f.content_hash, f.modified_at, now
                touched.append(row)
            for p in added:
                f = scanned[p]
                row = RepoFile(path=f.path, language=f.language, size_bytes=f.size_bytes, content_hash=f.content_hash,
                               modified_at=f.modified_at, indexed_at=now)
                repo.files.append(row)
                touched.append(row)
            repo.commit_sha, repo.default_branch = clone.commit_sha, clone.branch
            session.flush()
            stats = index_repository(session, repo.id, embedder, check_ready=False,
                                     only_file_ids=None if full else {f.id for f in touched})
            total_chunks = session.scalar(select(func.count()).select_from(Chunk).where(Chunk.repository_id == repo.id)) or 0
            repo = session.get(Repository, repo_id)
            repo.index_signature = signature
            repo.last_index_json = json.dumps({
                "mode": "full" if full else "incremental", "files": len(scanned), "new": len(added), "changed": len(changed),
                "removed": len(removed), "unchanged": unchanged, "truncated": scan.truncated, "redacted_secrets": stats.get("redacted_secrets", 0), "chunks_total": total_chunks,
                "chunks_reprocessed": stats["chunks"], "chunks_reused": total_chunks - stats["chunks"],
                "seconds": round(time.perf_counter() - t_start, 2)})
            repo.status, repo.stage, repo.chunk_count, repo.indexed_at = "ready", None, total_chunks, utcnow()
            session.commit()
            log.info("repo %s ready %s", repo_id, repo.last_index_json)
        except IngestError as e:
            _fail(session, repo_id, e.message)
        except EmbeddingError:
            log.exception("embedding failure repo=%s", repo_id)
            _fail(session, repo_id, "The embedding service is unavailable. Please retry in a moment.")
        except Exception:
            log.exception("unexpected pipeline failure repo=%s", repo_id)
            _fail(session, repo_id, "Unexpected indexing error. Please retry.")
