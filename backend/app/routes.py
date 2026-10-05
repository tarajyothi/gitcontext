"""Repository + usage API. Every route is scoped to the caller's workspace."""
import shutil
from collections import Counter
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import get_workspace, owned_repo
from .config import get_settings
from .db import get_session
from .embeddings import get_embedder
from .indexing import chunk_dict, index_repository
from .retrieval import invalidate
from .retrieval import search as hybrid_search
from .ingest.cloner import clone_repo
from .ingest.errors import IngestError
from .ingest.service import create_repository, run_pipeline, workspace_path
from .models import Chunk, RepoFile, Repository, Workspace

router = APIRouter(prefix="/repositories", tags=["repositories"])
usage_router = APIRouter(tags=["usage"])
ACTIVE = ("pending", "indexing")


def get_cloner():
    return clone_repo


def iso(d):
    return d.isoformat() if d else None


def summary(repo: Repository) -> dict:
    langs = Counter(f.language or "other" for f in repo.files)
    return {"id": repo.id, "url": repo.url, "owner": repo.owner, "name": repo.name, "status": repo.status,
            "stage": repo.stage, "error_message": repo.error_message, "default_branch": repo.default_branch,
            "commit_sha": repo.commit_sha, "file_count": len(repo.files), "chunk_count": repo.chunk_count,
            "total_bytes": sum(f.size_bytes for f in repo.files), "languages": dict(langs.most_common()),
            "created_at": iso(repo.created_at), "updated_at": iso(repo.updated_at), "indexed_at": iso(repo.indexed_at)}


class IngestRequest(BaseModel):
    url: str = Field(max_length=500)


class Filters(BaseModel):
    language: list[str] | None = Field(default=None, max_length=10)
    path_prefix: str | None = Field(default=None, max_length=300)
    kinds: list[str] | None = Field(default=None, max_length=10)
    exclude_tests: bool = False
    exclude_docs: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "vector", "bm25"] = "hybrid"
    rerank: bool = True
    filters: Filters | None = None


@router.post("", status_code=202)
def create(body: IngestRequest, bg: BackgroundTasks, ws: Workspace = Depends(get_workspace),
           session: Session = Depends(get_session), cloner=Depends(get_cloner), embedder=Depends(get_embedder)):
    """Register the repository (status=pending) and index it in the background."""
    repo = create_repository(session, ws, body.url)
    bg.add_task(run_pipeline, repo.id, cloner, embedder)
    return summary(repo)


@router.get("")
def list_repos(ws: Workspace = Depends(get_workspace), session: Session = Depends(get_session)):
    q = select(Repository).where(Repository.workspace_id == ws.id).order_by(Repository.id.desc())
    return [summary(r) for r in session.scalars(q)]


@router.get("/{repo_id}")
def get_repo(repo: Repository = Depends(owned_repo)):
    return summary(repo)


@router.post("/{repo_id}/reindex", status_code=202)
def reindex(bg: BackgroundTasks, repo: Repository = Depends(owned_repo), session: Session = Depends(get_session),
            cloner=Depends(get_cloner), embedder=Depends(get_embedder)):
    """Re-clone and re-index (also the retry path for failed repositories)."""
    if repo.status in ACTIVE:
        raise IngestError("already_indexing", "This repository is already being indexed.", 409)
    repo.status, repo.stage, repo.error_message = "pending", None, None
    session.commit()
    bg.add_task(run_pipeline, repo.id, cloner, embedder)
    return summary(repo)


@router.delete("/{repo_id}", status_code=204)
def remove(repo: Repository = Depends(owned_repo), session: Session = Depends(get_session)):
    if repo.status == "indexing":
        raise IngestError("indexing_in_progress", "Wait for indexing to finish before removing this repository.", 409)
    shutil.rmtree(workspace_path(repo.id, repo.owner, repo.name), ignore_errors=True)
    rid = repo.id
    session.delete(repo)
    session.commit()
    invalidate(rid)
    return Response(status_code=204)


@router.get("/{repo_id}/files")
def list_files(limit: int = 200, offset: int = 0, repo: Repository = Depends(owned_repo),
               session: Session = Depends(get_session)):
    q = select(RepoFile).where(RepoFile.repository_id == repo.id).order_by(RepoFile.path)
    rows = session.scalars(q.limit(min(limit, 1000)).offset(max(offset, 0))).all()
    return [{"path": f.path, "language": f.language, "size_bytes": f.size_bytes,
             "modified_at": iso(f.modified_at), "indexed_at": iso(f.indexed_at)} for f in rows]


@router.post("/{repo_id}/index")
def index(repo: Repository = Depends(owned_repo), session: Session = Depends(get_session), embedder=Depends(get_embedder)):
    """Re-chunk and re-embed from files already on disk (no re-clone)."""
    stats = index_repository(session, repo.id, embedder)
    repo.chunk_count = stats["chunks"]
    session.commit()
    return stats


@router.get("/{repo_id}/chunks")
def list_chunks(path: str | None = None, limit: int = 50, offset: int = 0, repo: Repository = Depends(owned_repo),
                session: Session = Depends(get_session)):
    q = select(Chunk).where(Chunk.repository_id == repo.id)
    if path:
        q = q.where(Chunk.file_path == path)
    q = q.order_by(Chunk.file_path, Chunk.start_line).limit(min(limit, 500)).offset(max(offset, 0))
    return [chunk_dict(c) for c in session.scalars(q)]


@router.post("/{repo_id}/search")
def search(body: SearchRequest, repo: Repository = Depends(owned_repo), session: Session = Depends(get_session),
           embedder=Depends(get_embedder)):
    """Hybrid code search (vector + BM25 + exact identifiers -> RRF -> dedupe -> rerank). Returns cited chunks."""
    hits = hybrid_search(session, repo.id, body.query, body.k, embedder, body.mode,
                         body.filters.model_dump() if body.filters else None, body.rerank)
    if hits is None:
        raise IngestError("not_indexed", "This repository has no indexed chunks yet.", 409)
    return hits


@usage_router.get("/usage")
def usage(ws: Workspace = Depends(get_workspace), session: Session = Depends(get_session)):
    """Real counts only. Question/token usage is not implemented yet and is reported as null."""
    repos = session.scalars(select(Repository).where(Repository.workspace_id == ws.id)).all()
    files = session.scalar(select(func.count()).select_from(RepoFile).join(Repository).where(Repository.workspace_id == ws.id))
    return {"plan": "free", "repositories": {"used": len(repos), "limit": get_settings().max_repos_per_workspace},
            "files_indexed": files, "chunks_indexed": sum(r.chunk_count for r in repos), "questions": None}
