"""Repository lifecycle: create (pending) -> background pipeline (indexing) -> ready | failed."""
import logging
import re
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..embeddings import Embedder, EmbeddingError
from ..models import RepoFile, Repository, Workspace, utcnow
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
    limit = get_settings().max_repos_per_workspace
    if session.scalar(select(func.count()).select_from(Repository).where(Repository.workspace_id == ws.id)) >= limit:
        raise IngestError("repo_limit_reached", f"The free plan allows {limit} repositories. Remove one to add another.", 403)
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
    from ..indexing import index_repository  # local import: indexing imports this module

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
            if sum(f.size_bytes for f in scan.files) > get_settings().max_indexed_bytes:
                raise IngestError("repo_too_large", "This repository is too large to index on the free plan.", 413)
            repo.files.clear()
            session.flush()
            now = utcnow()
            repo.files.extend(RepoFile(path=f.path, language=f.language, size_bytes=f.size_bytes,
                                       content_hash=f.content_hash, modified_at=f.modified_at, indexed_at=now)
                              for f in scan.files)
            repo.commit_sha, repo.default_branch = clone.commit_sha, clone.branch
            _stage(session, repo, "embedding")
            stats = index_repository(session, repo.id, embedder, check_ready=False)

            repo = session.get(Repository, repo_id)
            repo.status, repo.stage, repo.chunk_count, repo.indexed_at = "ready", None, stats["chunks"], utcnow()
            session.commit()
            log.info("repo %s ready files=%d chunks=%d skipped=%s", repo_id, len(scan.files), stats["chunks"], scan.skipped)
        except IngestError as e:
            _fail(session, repo_id, e.message)
        except EmbeddingError:
            log.exception("embedding failure repo=%s", repo_id)
            _fail(session, repo_id, "The embedding service is unavailable. Please retry in a moment.")
        except Exception:
            log.exception("unexpected pipeline failure repo=%s", repo_id)
            _fail(session, repo_id, "Unexpected indexing error. Please retry.")
