"""Ingestion orchestration: validate -> clone -> scan -> persist, with status tracking."""
import logging
import re
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import RepoFile, Repository, utcnow
from .cloner import CloneResult, clone_repo
from .errors import IngestError
from .scanner import scan_repository
from .url import parse_github_url

log = logging.getLogger("gitcontext.ingest")
Cloner = Callable[[str, Path], CloneResult]


def workspace_path(owner: str, name: str) -> Path:
    return Path(get_settings().workspace_dir).resolve() / re.sub(r"[^A-Za-z0-9_.-]", "_", f"{owner}__{name}")


def ingest_repository(session: Session, raw_url: str, cloner: Cloner = clone_repo) -> Repository:
    owner, name = parse_github_url(raw_url)  # raises invalid_url before anything is stored
    url = f"https://github.com/{owner}/{name}"
    repo = session.scalar(select(Repository).where(Repository.url == url))
    if repo is None:
        repo = Repository(url=url, owner=owner, name=name)
        session.add(repo)
    repo.status, repo.error_message = "indexing", None
    session.commit()

    dest = workspace_path(owner, name)
    assert Path(get_settings().workspace_dir).resolve() in dest.parents  # never write outside the workspace
    try:
        clone = cloner(url + ".git", dest)
        if clone.commit_sha is None:
            raise IngestError("repo_empty", "The repository is empty (no commits).", 422)
        scan = scan_repository(clone.path)
        if not scan.files:
            raise IngestError("no_supported_files", "No indexable source files were found.", 422)
        repo.files.clear()
        session.flush()
        now = utcnow()
        repo.files.extend(RepoFile(path=f.path, language=f.language, size_bytes=f.size_bytes,
                                   content_hash=f.content_hash, modified_at=f.modified_at, indexed_at=now)
                          for f in scan.files)
        repo.commit_sha, repo.default_branch = clone.commit_sha, clone.branch
        repo.status, repo.indexed_at = "ready", now
        session.commit()
        log.info("ingested %s files=%d skipped=%s", url, len(scan.files), scan.skipped)
        return repo
    except IngestError as e:
        session.rollback()
        repo = session.get(Repository, repo.id)
        repo.status, repo.error_message = "failed", e.message
        session.commit()
        raise
    except Exception:
        session.rollback()
        repo = session.get(Repository, repo.id)
        repo.status, repo.error_message = "failed", "Unexpected ingestion error"
        session.commit()
        raise
