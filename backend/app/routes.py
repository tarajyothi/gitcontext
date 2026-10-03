"""Repository ingestion API."""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .ingest.cloner import clone_repo
from .ingest.service import ingest_repository
from .models import RepoFile, Repository

router = APIRouter(prefix="/repositories", tags=["repositories"])


def get_cloner():
    return clone_repo


class IngestRequest(BaseModel):
    url: str


def summary(repo: Repository) -> dict:
    langs = Counter(f.language or "other" for f in repo.files)
    return {"id": repo.id, "url": repo.url, "owner": repo.owner, "name": repo.name, "status": repo.status,
            "error_message": repo.error_message, "default_branch": repo.default_branch,
            "commit_sha": repo.commit_sha, "file_count": len(repo.files),
            "total_bytes": sum(f.size_bytes for f in repo.files), "languages": dict(langs.most_common()),
            "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None}


@router.post("", status_code=201)
def create(body: IngestRequest, session: Session = Depends(get_session), cloner=Depends(get_cloner)):
    """Validate, clone, scan and store a public GitHub repository (synchronous in Day 2)."""
    return summary(ingest_repository(session, body.url, cloner))


@router.get("")
def list_repos(session: Session = Depends(get_session)):
    return [summary(r) for r in session.scalars(select(Repository).order_by(Repository.id.desc()))]


def _get(session: Session, repo_id: int) -> Repository:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    return repo


@router.get("/{repo_id}")
def get_repo(repo_id: int, session: Session = Depends(get_session)):
    return summary(_get(session, repo_id))


@router.get("/{repo_id}/files")
def list_files(repo_id: int, limit: int = 200, offset: int = 0, session: Session = Depends(get_session)):
    _get(session, repo_id)
    q = select(RepoFile).where(RepoFile.repository_id == repo_id).order_by(RepoFile.path)
    rows = session.scalars(q.limit(min(limit, 1000)).offset(max(offset, 0))).all()
    return [{"path": f.path, "language": f.language, "size_bytes": f.size_bytes,
             "modified_at": f.modified_at.isoformat() if f.modified_at else None,
             "indexed_at": f.indexed_at.isoformat() if f.indexed_at else None} for f in rows]
