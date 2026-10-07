import subprocess

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import HashingEmbedder, get_embedder
from app.ingest.cloner import clone_repo
from app.main import app
from app.models import Chunk, ChunkEmbedding, RepoFile, Repository
from app.routes import get_cloner
from tests.test_ingest_api import local_repo

FILES = {
    "a.py": "def alpha_one():\n    return 1\n\n\ndef alpha_two():\n    return 2\n",
    "b.py": "class Beta:\n    def old_method(self):\n        return 'stale marker text'\n",
    "c.py": "def gamma():\n    return 3\n",
    "d.py": "def delta_to_be_deleted():\n    return 4\n",
    "docs/readme.md": "# Readme\n\nSome documentation about the project.\n",
}


class CountingEmbedder(HashingEmbedder):
    def __init__(self):
        self.texts, self.fail = 0, False

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("embedding service exploded")
        self.texts += len(texts)
        return super().embed(texts)


def commit(src, message, write=None, remove=()):
    for p, c in (write or {}).items():
        (src / p).parent.mkdir(parents=True, exist_ok=True)
        (src / p).write_text(c)
    for p in remove:
        (src / p).unlink()
    run = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    run("add", "-A")
    run("commit", "-qm", message)


@pytest.fixture()
def env(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    src = local_repo(tmp_path, FILES)
    emb = CountingEmbedder()
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(src), dest))
    app.dependency_overrides[get_embedder] = lambda: emb
    c = new_client()
    rid = c.post("/repositories", json={"url": "https://github.com/acme/inc"}).json()["id"]
    assert c.get(f"/repositories/{rid}").json()["status"] == "ready"
    return c, rid, src, emb


def chunk_ids(c, rid):
    out = {}
    for x in c.get(f"/repositories/{rid}/chunks?limit=500").json():
        out.setdefault(x["file_path"], set()).add(x["chunk_id"])
    return out


def reindex(c, rid):
    assert c.post(f"/repositories/{rid}/reindex").status_code == 202
    return c.get(f"/repositories/{rid}").json()


def test_first_index_is_full_then_incremental_changes_only_what_changed(env):
    c, rid, src, emb = env
    first = c.get(f"/repositories/{rid}").json()["last_index"]
    assert first["mode"] == "full" and first["new"] == 5 and first["chunks_reprocessed"] == first["chunks_total"] == emb.texts
    before, texts_before = chunk_ids(c, rid), emb.texts

    commit(src, "change", write={"b.py": "class Beta:\n    def new_method(self):\n        return 'fresh text'\n", "e.py": "def epsilon_new_file():\n    return 5\n"},
           remove=["d.py"])
    repo = reindex(c, rid)
    li = repo["last_index"]
    assert repo["status"] == "ready" and li["mode"] == "incremental"
    assert (li["new"], li["changed"], li["removed"], li["unchanged"]) == (1, 1, 1, 3)

    after = chunk_ids(c, rid)
    for untouched in ("a.py", "c.py", "docs/readme.md"):
        assert after[untouched] == before[untouched]                       # same rows: never re-chunked or re-embedded
    assert after["b.py"].isdisjoint(before["b.py"]) and "d.py" not in after and "e.py" in after
    reprocessed = len(after["b.py"]) + len(after["e.py"])
    assert li["chunks_reprocessed"] == reprocessed and emb.texts - texts_before == reprocessed   # embedder called ONLY for those
    assert li["chunks_reused"] == li["chunks_total"] - reprocessed == sum(len(after[p]) for p in ("a.py", "c.py", "docs/readme.md"))
    assert repo["chunk_count"] == li["chunks_total"] == sum(len(v) for v in after.values())

    with SessionLocal() as db:                                             # no orphan or missing vectors
        n_chunks = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.repository_id == rid))
        n_vec = db.scalar(select(func.count()).select_from(ChunkEmbedding).where(ChunkEmbedding.repository_id == rid))
        orphans = db.scalar(select(func.count()).select_from(ChunkEmbedding).where(~ChunkEmbedding.chunk_id.in_(select(Chunk.id))))
        assert n_chunks == n_vec == repo["chunk_count"] and orphans == 0
        assert db.scalar(select(func.count()).select_from(RepoFile).where(RepoFile.repository_id == rid)) == 5   # a b c e readme

    hits = c.post(f"/repositories/{rid}/search", json={"query": "epsilon_new_file", "k": 3}).json()
    assert hits[0]["file_path"] == "e.py"
    all_text = " ".join(x["content"] for x in c.get(f"/repositories/{rid}/chunks?limit=500").json())
    assert "stale marker text" not in all_text and "delta_to_be_deleted" not in all_text and "fresh text" in all_text


def test_reindex_without_changes_does_no_embedding_work(env):
    c, rid, src, emb = env
    before, texts = chunk_ids(c, rid), emb.texts
    li = reindex(c, rid)["last_index"]
    assert (li["new"], li["changed"], li["removed"], li["chunks_reprocessed"]) == (0, 0, 0, 0) and li["mode"] == "incremental"
    assert emb.texts == texts and chunk_ids(c, rid) == before


def test_model_change_or_legacy_index_forces_full_rebuild(env):
    c, rid, src, emb = env
    emb.name = "another-embedding-model"                                   # signature mismatch
    li = reindex(c, rid)["last_index"]
    assert li["mode"] == "full" and li["chunks_reprocessed"] == li["chunks_total"]
    with SessionLocal() as db:                                             # legacy repo indexed before signatures existed
        db.get(Repository, rid).index_signature = None
        db.commit()
    assert reindex(c, rid)["last_index"]["mode"] == "full"
    assert reindex(c, rid)["last_index"]["mode"] == "incremental"


def test_failure_mid_reindex_keeps_old_index_and_next_run_recovers(env):
    c, rid, src, emb = env
    before = chunk_ids(c, rid)
    with SessionLocal() as db:
        old_hash = db.scalar(select(RepoFile.content_hash).where(RepoFile.repository_id == rid, RepoFile.path == "b.py"))
    commit(src, "edit b", write={"b.py": "class Beta:\n    def replaced(self):\n        return 'new body'\n"})
    emb.fail = True
    repo = reindex(c, rid)
    assert repo["status"] == "failed" and "Unexpected" in repo["error_message"] and "exploded" not in repo["error_message"]
    assert chunk_ids(c, rid) == before                                     # old chunks untouched (transaction rolled back)
    with SessionLocal() as db:                                             # file hash NOT advanced, so the change is still detected
        assert db.scalar(select(RepoFile.content_hash).where(RepoFile.repository_id == rid, RepoFile.path == "b.py")) == old_hash
    emb.fail = False
    assert c.post(f"/repositories/{rid}/search", json={"query": "alpha_one", "k": 1}).json()[0]["file_path"] == "a.py"   # old index still searchable

    emb.fail = False
    repo = reindex(c, rid)
    assert repo["status"] == "ready" and repo["last_index"]["changed"] == 1 and repo["last_index"]["unchanged"] == 4
    after = chunk_ids(c, rid)
    assert after["a.py"] == before["a.py"] and after["b.py"].isdisjoint(before["b.py"])
