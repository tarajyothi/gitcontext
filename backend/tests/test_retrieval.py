import pytest

from app.config import get_settings
from app.ingest.cloner import clone_repo
from app.main import app
from app.retrieval import BM25Index, Rec, is_doc, is_test_path, overlaps, split_ident, tokenize
from app.routes import get_cloner
from tests.test_ingest_api import local_repo

FILES = {
    "app/auth.py": '"""Authentication helpers."""\nimport hashlib\n\n\ndef hash_password(password, salt):\n    """Return a salted sha256 digest of the password."""\n    return hashlib.sha256((salt + password).encode()).hexdigest()\n\n\ndef login_user(username, password, store):\n    """Check the credentials and create a session for the user."""\n    user = store.get(username)\n    if user is None or user["hash"] != hash_password(password, user["salt"]):\n        raise PermissionError("invalid credentials")\n    return {"user": username, "session": "token"}\n',
    "app/billing.py": 'def charge_customer(customer, amount):\n    """Charge the customer card for an invoice amount."""\n    return {"customer": customer, "charged": amount}\n\n\ndef refund_payment(payment_id):\n    """Refund a payment back to the customer."""\n    return payment_id\n\n\nclass InvoiceBuilder:\n    """Builds invoices from line items."""\n\n    def build(self, items):\n        return sum(items)\n',
    "tests/test_auth.py": "from app.auth import login_user\n\n\ndef test_login_user_rejects_bad_password():\n    # login the user with a wrong password and expect an error\n    login_user('a', 'bad', {})\n",
    "docs/guide.md": "# Login guide\n\nUsers log in with the login_user function. See also the user login flow.\n",
}


@pytest.fixture()
def repo(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    src = local_repo(tmp_path, FILES)
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(src), dest))
    c = new_client()
    rid = c.post("/repositories", json={"url": "https://github.com/acme/svc"}).json()["id"]
    assert c.get(f"/repositories/{rid}").json()["status"] == "ready"
    return c, rid


def search(c, rid, query, **kw):
    r = c.post(f"/repositories/{rid}/search", json={"query": query, "k": kw.pop("k", 8), **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- units
def test_tokenize_splits_identifiers_and_stems():
    assert split_ident("HelpFormatter") == ["help", "formatter"] and split_ident("get_app_dir") == ["get", "app", "dir"]
    t = tokenize("def getAppDir(): prompts")
    assert "getappdir" in t and "app" in t and "dir" in t and "prompt" in t and "def" not in t


def test_bm25_prefers_rare_terms_and_shorter_docs():
    idx = BM25Index([["alpha", "common"], ["common", "common", "common"], ["beta", "common"], ["common"]])
    s = idx.scores(["alpha"])
    assert s.argmax() == 0 and s[1] == 0 and idx.scores(["common"]).max() < s.max()


def test_path_classifiers():
    assert is_test_path("tests/test_x.py") and is_test_path("src/foo_test.go") and is_test_path("web/a.spec.ts")
    assert not is_test_path("src/contest.py") and not is_test_path("app/latest.py")
    assert is_doc("docs/a.py", "python") and is_doc("README.md", "markdown") and is_doc("examples/x.py", "python")
    assert not is_doc("src/a.py", "python")


def rec(path, s, e):
    return Rec(1, path, "f", "function", "python", s, e, "", "f", "f")


def test_overlap_rule():
    assert overlaps(rec("a.py", 1, 10), rec("a.py", 5, 12))          # 6/8 of the shorter chunk
    assert not overlaps(rec("a.py", 1, 10), rec("a.py", 10, 40))     # 1 shared line of 10
    assert not overlaps(rec("a.py", 1, 10), rec("b.py", 1, 10))      # different files


# ---------------------------------------------------------------- API behaviour
def test_hybrid_finds_login_implementation_not_its_test(repo):
    c, rid = repo
    hits = search(c, rid, "where is the user login implemented")
    top3 = [(h["file_path"], h["symbol"]) for h in hits[:3]]
    assert ("app/auth.py", "login_user") in top3
    assert hits[0]["file_path"] != "tests/test_auth.py"          # tests/docs are demoted for "where is X implemented"
    assert hits[0]["signals"].keys() >= {"vector_rank", "bm25_rank", "identifier", "rerank_adjustment"}
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


def test_exact_identifier_wins(repo):
    c, rid = repo
    hits = search(c, rid, "what does hash_password do")
    assert hits[0]["symbol"] == "hash_password" and hits[0]["signals"]["identifier"] >= 1.5
    assert search(c, rid, "InvoiceBuilder.build")[0]["symbol"] == "InvoiceBuilder"  # class chunk contains the method


def test_modes_and_validation(repo):
    c, rid = repo
    for mode in ("vector", "bm25", "hybrid"):
        assert search(c, rid, "refund payment", mode=mode)
    assert search(c, rid, "refund payment", mode="bm25")[0]["symbol"] == "refund_payment"
    assert search(c, rid, "refund payment", rerank=False)[0]["signals"]["rerank_adjustment"] is None
    for bad in ({"mode": "magic"}, {"k": 0}, {"k": 51}, {"query": ""}):
        body = {"query": "x", "k": 3, **bad}
        assert c.post(f"/repositories/{rid}/search", json=body).status_code == 422


def test_filters(repo):
    c, rid = repo
    assert {h["file_path"] for h in search(c, rid, "login user", filters={"language": ["markdown"]})} == {"docs/guide.md"}
    assert {h["file_path"] for h in search(c, rid, "customer", filters={"path_prefix": "app/billing"})} == {"app/billing.py"}
    assert {h["kind"] for h in search(c, rid, "invoice", filters={"kinds": ["class"]})} == {"class"}
    no_noise = search(c, rid, "login user", filters={"exclude_tests": True, "exclude_docs": True})
    assert no_noise and all(not h["file_path"].startswith(("tests/", "docs/")) for h in no_noise)
    assert search(c, rid, "login", filters={"path_prefix": "does/not/exist"}) == []


def test_index_cache_survives_reindex(repo):
    c, rid = repo
    first = search(c, rid, "refund payment")
    assert c.post(f"/repositories/{rid}/index").status_code == 200   # chunk ids change
    again = search(c, rid, "refund payment")
    live = {x["chunk_id"] for x in c.get(f"/repositories/{rid}/chunks?limit=200").json()}
    assert again[0]["symbol"] == first[0]["symbol"] and all(h["chunk_id"] in live for h in again)


def test_results_cite_exact_lines(repo):
    c, rid = repo
    for h in search(c, rid, "charge customer card"):
        src = FILES[h["file_path"]].split("\n")
        assert h["content"] == "\n".join(src[h["start_line"] - 1:h["end_line"]])


def test_cache_never_serves_another_repository_after_delete_and_recreate(tmp_path, monkeypatch, new_client):
    """SQLite reuses row ids after deletes: a stale search index must not leak into a new repo with the same ids."""
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = local_repo(tmp_path / "a", {"alpha.py": "def zebra_stripes():\n    return 1\n"})
    b = local_repo(tmp_path / "b", {"beta.py": "def yak_shaving():\n    return 2\n"})
    current = {"src": a}
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(current["src"]), dest))
    c = new_client()
    rid = c.post("/repositories", json={"url": "https://github.com/acme/one"}).json()["id"]
    assert search(c, rid, "zebra stripes")[0]["file_path"] == "alpha.py"
    assert c.delete(f"/repositories/{rid}").status_code == 204
    current["src"] = b
    rid2 = c.post("/repositories", json={"url": "https://github.com/acme/one"}).json()["id"]
    hits = search(c, rid2, "zebra stripes yak shaving")
    assert {h["file_path"] for h in hits} == {"beta.py"}
