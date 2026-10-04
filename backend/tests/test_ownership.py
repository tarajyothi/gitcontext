import pytest

from app.config import get_settings
from app.ingest.cloner import clone_repo
from app.main import app
from app.routes import get_cloner
from tests.test_ingest_api import local_repo

URL = "https://github.com/acme/shop"
ROUTES = [("get", "/repositories/{id}"), ("get", "/repositories/{id}/files"), ("get", "/repositories/{id}/chunks"),
          ("post", "/repositories/{id}/reindex"), ("post", "/repositories/{id}/index"),
          ("post", "/repositories/{id}/search"), ("delete", "/repositories/{id}")]


@pytest.fixture()
def two_users(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    src = local_repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(src), dest))
    alice, bob = new_client("alice@example.com"), new_client("bob@example.com")
    rid = alice.post("/repositories", json={"url": URL}).json()["id"]
    return alice, bob, rid


def call(c, method, path, **kw):
    return getattr(c, method)(path, **({"json": {"query": "f"}} if method == "post" and "search" in path else {}), **kw)


def test_owner_can_access(two_users):
    alice, _, rid = two_users
    assert alice.get(f"/repositories/{rid}").json()["status"] == "ready"
    assert alice.get(f"/repositories/{rid}/files").status_code == 200


@pytest.mark.parametrize("method,path", ROUTES)
def test_non_owner_gets_404_on_every_repo_route(two_users, method, path):
    alice, bob, rid = two_users
    r = call(bob, method, path.format(id=rid))
    assert r.status_code == 404
    assert alice.get(f"/repositories/{rid}").json()["status"] == "ready"  # untouched (not deleted/re-queued)


@pytest.mark.parametrize("method,path", ROUTES + [("get", "/repositories"), ("post", "/repositories"), ("get", "/usage"), ("get", "/auth/me")])
def test_unauthenticated_gets_401(two_users, new_client, method, path):
    anon = new_client(signup=False)
    r = call(anon, method, path.format(id=1))
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("bad_id", ["99999", "0", "-1"])
def test_manipulated_ids_rejected(two_users, bad_id):
    _, bob, _ = two_users
    assert bob.get(f"/repositories/{bad_id}").status_code == 404


def test_non_numeric_id_rejected(two_users):
    _, bob, _ = two_users
    assert bob.get("/repositories/abc").status_code == 422
    assert bob.get("/repositories/1 OR 1=1").status_code in (404, 422)


def test_listing_and_usage_only_show_own(two_users):
    alice, bob, rid = two_users
    assert [r["id"] for r in alice.get("/repositories").json()] == [rid]
    assert bob.get("/repositories").json() == [] and bob.get("/usage").json()["repositories"]["used"] == 0


def test_same_repo_url_allowed_for_different_users_with_separate_clones(two_users, tmp_path):
    alice, bob, rid = two_users
    r = bob.post("/repositories", json={"url": URL})
    assert r.status_code == 202 and r.json()["id"] != rid
    assert len(list((tmp_path / "ws").iterdir())) == 2  # distinct on-disk directories
    bob.delete(f"/repositories/{r.json()['id']}")
    assert alice.get(f"/repositories/{rid}/files").status_code == 200  # alice's clone untouched
