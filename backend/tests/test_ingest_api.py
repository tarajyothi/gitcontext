import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ingest.cloner import clone_repo
from app.ingest.errors import IngestError
from app.main import app
from app.routes import get_cloner


def local_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"; src.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    for p, c in files.items():
        (src / p).parent.mkdir(parents=True, exist_ok=True); (src / p).write_text(c)
    run("add", "-A"); run("commit", "-qm", "init")
    return src


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def use_cloner(fn):
    app.dependency_overrides[get_cloner] = lambda: fn


def test_ingest_success_end_to_end(client, tmp_path):
    src = local_repo(tmp_path, {"a.py": "print(1)\n", "b/c.js": "1;\n", ".env": "K=1", "node_modules/x.js": "1"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    r = client.post("/repositories", json={"url": "https://github.com/acme/shop"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "ready" and body["file_count"] == 2 and body["commit_sha"]
    assert body["languages"] == {"python": 1, "javascript": 1}
    files = client.get(f"/repositories/{body['id']}/files").json()
    assert [f["path"] for f in files] == ["a.py", "b/c.js"] and files[0]["indexed_at"]
    assert client.get("/repositories").json()[0]["id"] == body["id"]


def test_reingest_replaces_files_not_duplicates(client, tmp_path):
    src = local_repo(tmp_path, {"a.py": "print(1)\n"})
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    for _ in range(2):
        r = client.post("/repositories", json={"url": "https://github.com/acme/shop"})
    assert r.json()["file_count"] == 1 and len(client.get("/repositories").json()) == 1


def test_invalid_url_422_and_nothing_stored(client):
    n = len(client.get("/repositories").json())
    r = client.post("/repositories", json={"url": "https://example.com/x/y"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_url"
    assert len(client.get("/repositories").json()) == n


def test_inaccessible_repo_marked_failed(client):
    def deny(url, dest): raise IngestError("repo_not_accessible", "Repository not found or private.", 404)
    use_cloner(deny)
    r = client.post("/repositories", json={"url": "https://github.com/acme/private-one"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "repo_not_accessible"
    repo = [x for x in client.get("/repositories").json() if x["name"] == "private-one"][0]
    assert repo["status"] == "failed" and "private" in repo["error_message"]


def test_empty_repo_graceful(client, tmp_path):
    src = tmp_path / "e"; subprocess.run(["git", "init", "-q", str(src)], check=True)
    use_cloner(lambda url, dest: clone_repo(str(src), dest))
    r = client.post("/repositories", json={"url": "https://github.com/acme/empty"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "repo_empty"


def test_unexpected_failure_is_safe_and_recorded(client):
    def boom(url, dest): raise RuntimeError("disk exploded /secret/path")
    use_cloner(boom)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/repositories", json={"url": "https://github.com/acme/boom"})
    assert r.status_code == 500 and "secret" not in r.text


def test_missing_repo_404(client):
    assert client.get("/repositories/99999").status_code == 404
    assert client.post("/repositories", json={}).status_code == 422


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("SKIP_NETWORK_TESTS") == "1", reason="network tests disabled")
def test_real_public_repo_and_nonexistent_repo(client):
    r = client.post("/repositories", json={"url": "https://github.com/octocat/Hello-World"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "ready" and body["file_count"] >= 1 and len(body["commit_sha"]) == 40
    r = client.post("/repositories", json={"url": "https://github.com/octocat/this-repo-does-not-exist-gitcontext-xyz"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "repo_not_accessible"
