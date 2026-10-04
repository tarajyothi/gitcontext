import shutil
from pathlib import Path

import pytest

from app.chunking import split_lines
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.cloner import clone_repo
from app.main import app
from app.models import Chunk, ChunkEmbedding
from app.routes import get_cloner
from tests.test_ingest_api import local_repo

SAMPLE = Path(__file__).resolve().parents[2] / "sample_repos" / "tiny_shop"


@pytest.fixture()
def ingested(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    files = {str(p.relative_to(SAMPLE)): p.read_text() for p in SAMPLE.rglob("*") if p.is_file()}
    src = local_repo(tmp_path, files)
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(src), dest))
    c = new_client()
    rid = c.post("/repositories", json={"url": "https://github.com/acme/tiny_shop"}).json()["id"]
    assert c.get(f"/repositories/{rid}").json()["status"] == "ready"
    return c, rid, tmp_path / "ws" / f"{rid}__acme__tiny_shop"


def test_pipeline_stores_chunks_and_embeddings(ingested):
    c, rid, root = ingested
    repo = c.get(f"/repositories/{rid}").json()
    chunks = c.get(f"/repositories/{rid}/chunks?limit=200").json()
    assert len(chunks) == repo["chunk_count"] >= 6
    syms = {(x["file_path"], x["symbol"]) for x in chunks}
    assert {("shop/cart.py", "Cart"), ("shop/cart.py", "EmptyCartError"), ("shop/pricing.py", "apply_discount"),
            ("web/server.js", "handleCheckout")} <= syms
    for x in chunks:  # every chunk maps to the exact lines of the file on disk
        lines = split_lines((root / x["file_path"]).read_text())
        assert x["content"] == "\n".join(lines[x["start_line"] - 1:x["end_line"]])
    with SessionLocal() as db:
        rows = db.query(ChunkEmbedding).filter_by(repository_id=rid).all()
        assert len(rows) == len(chunks) and all(len(r.vector) == 384 * 4 and r.dim == 384 for r in rows)


def test_vector_search_returns_cited_chunk(ingested):
    c, rid, _ = ingested
    hits = c.post(f"/repositories/{rid}/search", json={"query": "apply_discount unknown coupons ignored", "k": 3}).json()
    assert hits[0]["symbol"] == "apply_discount" and hits[0]["file_path"] == "shop/pricing.py"
    assert hits[0]["start_line"] <= hits[0]["end_line"] and hits[0]["score"] >= hits[1]["score"]
    assert c.post(f"/repositories/{rid}/search", json={"query": "", "k": 3}).status_code == 422


def test_rechunk_is_idempotent(ingested):
    c, rid, _ = ingested
    a = c.post(f"/repositories/{rid}/index").json()
    b = c.post(f"/repositories/{rid}/index").json()
    assert a["chunks"] == b["chunks"]
    with SessionLocal() as db:
        assert db.query(Chunk).filter_by(repository_id=rid).count() == a["chunks"]
        assert db.query(ChunkEmbedding).filter_by(repository_id=rid).count() == a["chunks"]


def test_index_errors(ingested):
    c, rid, root = ingested
    assert c.post("/repositories/99999/index").status_code == 404
    shutil.rmtree(root)
    r = c.post(f"/repositories/{rid}/index")
    assert r.status_code == 409 and r.json()["error"]["code"] == "workspace_missing"
