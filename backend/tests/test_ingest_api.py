import os
import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.ingest.cloner import clone_repo
from app.ingest.errors import IngestError
from app.main import app
from app.routes import get_cloner

URL = "https://github.com/acme/shop"


def local_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"; src.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    for p, c in files.items():
        (src / p).parent.mkdir(parents=True, exist_ok=True); (src / p).write_text(c)
    run("add", "-A"); run("commit", "-qm", "init")
    return src


@pytest.fixture()
def client(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    return new_client()


def use_cloner(fn):
    app.dependency_overrides[get_cloner] = lambda: fn


def connect(client, url=URL):
    """POST returns 202 'pending'; the background pipeline has finished by the time the client returns."""
    r = client.post("/repositories", json={"url": url})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"
    return client.get(f"/repositories/{r.json()['id']}").json()


def test_ingest_success_end_to_end(client, tmp_path):
    src = local_repo(tmp_path, {"a.py": "print(1)\n", "b/c.js": "1;\n", ".env": "K=1", "node_modules/x.js": "1"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    repo = connect(client)
    assert repo["status"] == "ready" and repo["stage"] is None and repo["file_count"] == 2
    assert repo["chunk_count"] >= 2 and repo["commit_sha"] and repo["indexed_at"] and repo["updated_at"]
    assert repo["languages"] == {"python": 1, "javascript": 1}
    files = client.get(f"/repositories/{repo['id']}/files").json()
    assert [f["path"] for f in files] == ["a.py", "b/c.js"] and files[0]["indexed_at"]
    assert client.get("/repositories").json()[0]["id"] == repo["id"]


def test_reindex_replaces_not_duplicates(client, tmp_path):
    src = local_repo(tmp_path, {"a.py": "print(1)\n"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    repo = connect(client)
    r = client.post(f"/repositories/{repo['id']}/reindex")
    assert r.status_code == 202
    again = client.get(f"/repositories/{repo['id']}").json()
    assert again["status"] == "ready" and again["file_count"] == 1 and len(client.get("/repositories").json()) == 1


def test_invalid_url_422_and_nothing_stored(client):
    r = client.post("/repositories", json={"url": "https://example.com/x/y"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_url"
    assert client.get("/repositories").json() == []


def test_inaccessible_repo_ends_failed_with_message_then_retry_works(client, tmp_path):
    def deny(url, dest): raise IngestError("repo_not_accessible", "Repository not found or private.", 404)
    use_cloner(deny)
    repo = connect(client, "https://github.com/acme/private-one")
    assert repo["status"] == "failed" and "private" in repo["error_message"] and repo["stage"] is None
    src = local_repo(tmp_path, {"a.py": "print(1)\n"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))  # "access granted" -> retry
    assert client.post(f"/repositories/{repo['id']}/reindex").status_code == 202
    assert client.get(f"/repositories/{repo['id']}").json()["status"] == "ready"


def test_empty_repo_graceful(client, tmp_path):
    src = tmp_path / "e"; subprocess.run(["git", "init", "-q", str(src)], check=True)
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    repo = connect(client)
    assert repo["status"] == "failed" and "empty" in repo["error_message"]


def test_unexpected_failure_is_safe_and_recorded(client):
    def boom(url, dest): raise RuntimeError("disk exploded /secret/path")
    use_cloner(boom)
    repo = connect(client)
    assert repo["status"] == "failed" and "secret" not in str(repo) and "Unexpected" in repo["error_message"]


def test_too_large_repo_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_indexed_bytes", 10)
    src = local_repo(tmp_path, {"a.py": "x = 1\n" * 50})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    assert "too large" in connect(client)["error_message"]


def test_duplicate_limit_and_removal(client, tmp_path, monkeypatch):
    src = local_repo(tmp_path, {"a.py": "print(1)\n"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    repo = connect(client)
    assert client.post("/repositories", json={"url": URL}).json()["error"]["code"] == "duplicate_repository"
    monkeypatch.setattr(get_settings(), "max_repos_per_workspace", 1)
    assert client.post("/repositories", json={"url": "https://github.com/acme/two"}).json()["error"]["code"] == "repo_limit_reached"
    assert client.delete(f"/repositories/{repo['id']}").status_code == 204
    assert client.get(f"/repositories/{repo['id']}").status_code == 404 and client.get("/repositories").json() == []
    assert not list((tmp_path / "ws").glob("*acme*"))  # clone removed from disk


def test_usage_reports_real_counts(client, tmp_path):
    src = local_repo(tmp_path, {"a.py": "print(1)\n"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    repo = connect(client)
    u = client.get("/usage").json()
    assert u["repositories"] == {"used": 1, "limit": 5} and u["files_indexed"] == 1
    assert u["chunks_indexed"] == repo["chunk_count"] and u["questions"] == {"used_today": 0, "limit": 50}


def test_missing_repo_and_bad_body(client):
    assert client.get("/repositories/99999").status_code == 404
    assert client.post("/repositories", json={}).status_code == 422


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("SKIP_NETWORK_TESTS") == "1", reason="network tests disabled")
def test_real_public_repo_and_nonexistent_repo(client):
    repo = connect(client, "https://github.com/octocat/Hello-World")
    assert repo["status"] == "ready" and repo["file_count"] >= 1 and len(repo["commit_sha"]) == 40
    bad = connect(client, "https://github.com/octocat/this-repo-does-not-exist-gitcontext-xyz")
    assert bad["status"] == "failed" and "not found or private" in bad["error_message"]
