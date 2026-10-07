import os
import subprocess

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.ingest import scanner
from app.ingest.cloner import clone_repo
from app.main import app
from app.models import User
from app.redact import redact
from app.routes import get_cloner
from tests.test_ingest_api import local_repo

FAKE_AWS = "AKIAIOSFODNN7EXAMPLE"
FAKE_GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2
FAKE_SLACK = "xoxb-123456789012-abcdefABCDEF"
FAKE_STRIPE = "sk_live_" + "x9Y8z7W6v5U4t3S2r1Q0p9O8"
FAKE_GOOGLE = "AIza" + "SyA-1234567890abcdefghijklmnopqrstu"[:35]
FAKE_LLM = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz"
PRIVATE = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAfakefakefake\nAbCdEf123456\n-----END RSA PRIVATE KEY-----"


# ---------------------------------------------------------------- redaction (unit)
@pytest.mark.parametrize("secret,kind", [(FAKE_AWS, "aws_access_key"), (FAKE_GH, "github_token"), (FAKE_SLACK, "slack_token"),
                                         (FAKE_STRIPE, "stripe_live_key"), (FAKE_GOOGLE, "google_api_key"), (FAKE_LLM, "llm_api_key")])
def test_redacts_known_credential_formats(secret, kind):
    out, n = redact(f'KEY = "{secret}"  # prod')
    assert n == 1 and secret not in out and f"[REDACTED:{kind}]" in out


def test_redaction_keeps_line_count_and_handles_private_keys():
    text = f"a = 1\n{PRIVATE}\nb = 2\n"
    out, n = redact(text)
    assert n == 1 and "MIIEow" not in out and "AbCdEf" not in out
    assert out.count("\n") == text.count("\n") and out.startswith("a = 1\n") and out.endswith("b = 2\n")
    assert redact("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\nnot ended")[1] == 1   # chunk cut mid-key is still masked


def test_redaction_leaves_normal_code_alone():
    code = "import sklearn\nTOKEN_URL = 'https://x.test/task-force-sk-learn'\nname = 'AKIA' + 'short'\nrisk-assessment = 1\n"
    assert redact(code) == (code, 0)


# ---------------------------------------------------------------- end to end with hostile repositories
def make_repo(tmp_path, monkeypatch, new_client, files, extra=None):
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    src = local_repo(tmp_path, files)
    if extra:
        extra(src)
        run = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
        run("add", "-A"); run("commit", "-qm", "extra")
    app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo(str(src), dest))
    c = new_client()
    rid = c.post("/repositories", json={"url": "https://github.com/acme/evil"}).json()["id"]
    return c, rid, c.get(f"/repositories/{rid}").json()


def test_secrets_in_a_repository_never_reach_chunks_search_or_answers(tmp_path, monkeypatch, new_client):
    cfg = f'AWS = "{FAKE_AWS}"\nGITHUB = "{FAKE_GH}"\n\ndef connect():\n    """Connect to the database."""\n    return AWS\n'
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {"config.py": cfg, "key.txt.py": PRIVATE.replace("\n", "\n# ") })
    assert repo["status"] == "ready" and repo["last_index"]["redacted_secrets"] >= 3
    blob = " ".join(x["content"] for x in c.get(f"/repositories/{rid}/chunks?limit=100").json())
    assert FAKE_AWS not in blob and FAKE_GH not in blob and "MIIEow" not in blob and "[REDACTED:aws_access_key]" in blob
    for q in (FAKE_AWS, "AWS key", FAKE_GH):
        assert FAKE_AWS not in str(c.post(f"/repositories/{rid}/search", json={"query": q, "k": 5}).json())
    ans = c.post(f"/repositories/{rid}/ask", json={"question": "how does connect work with the database"}).json()
    assert FAKE_AWS not in str(ans) and FAKE_GH not in str(ans)


def test_symlinks_cannot_leak_files_outside_the_repository(tmp_path, monkeypatch, new_client):
    def add_links(src):
        os.symlink("/etc/passwd", src / "passwd_link.py")
        os.symlink("/etc", src / "etc_dir")
        os.symlink("../../../etc/hostname", src / "up.py")
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {"ok.py": "def fine():\n    return 1\n"}, add_links)
    assert repo["status"] == "ready" and repo["file_count"] == 1
    paths = [f["path"] for f in c.get(f"/repositories/{rid}/files").json()]
    assert paths == ["ok.py"]
    assert "root:x:0:0" not in str(c.post(f"/repositories/{rid}/search", json={"query": "root:x:0:0 /bin/bash", "k": 10}).json())
    assert c.get(f"/repositories/{rid}/chunks", params={"path": "../../etc/passwd"}).json() == []


def test_hostile_file_names_are_inert_data(tmp_path, monkeypatch, new_client):
    evil = "<img src=x onerror=alert(1)>.py"
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {evil: "def x():\n    return 1\n", 'q"uote \' name.py': "def y():\n    return 2\n"})
    assert repo["status"] == "ready" and repo["file_count"] == 2
    r = c.get(f"/repositories/{rid}/files")
    assert r.headers["content-type"].startswith("application/json") and evil in [f["path"] for f in r.json()]   # data, never HTML


def test_file_count_cap_is_reported(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(scanner, "MAX_FILES", 3)
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {f"f{i}.py": f"def f{i}():\n    return {i}\n" for i in range(6)})
    assert repo["file_count"] == 3 and repo["last_index"]["truncated"] is True


# ---------------------------------------------------------------- API abuse
def test_malformed_and_hostile_requests_get_clean_errors(tmp_path, monkeypatch, new_client):
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {"a.py": "def a():\n    return 1\n"})
    bad = [("post", f"/repositories/{rid}/ask", {"content": b"{not json", "headers": {"content-type": "application/json"}}),
           ("post", f"/repositories/{rid}/ask", {"json": {"question": 123}}),
           ("post", f"/repositories/{rid}/search", {"json": {"query": "x", "k": 10**9}}),
           ("post", f"/repositories/{rid}/search", {"json": {"query": "x", "filters": {"language": "python"}}}),
           ("post", "/repositories", {"json": {"url": ["https://github.com/a/b"]}}),
           ("post", "/auth/login", {"json": {"email": None, "password": "x"}})]
    for method, path, kw in bad:
        r = getattr(c, method)(path, **kw)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error" and "Traceback" not in r.text, (path, r.text)
    assert c.get(f"/repositories/{rid}/ask").status_code == 405 and c.get("/repositories/-5").status_code == 404
    assert c.get("/definitely/not/a/route").json()["error"]["code"] == "http_error"


def test_sql_metacharacters_are_just_text(tmp_path, monkeypatch, new_client):
    c, rid, repo = make_repo(tmp_path, monkeypatch, new_client, {"a.py": "def a():\n    return 1\n"})
    nasty = "'; DROP TABLE users; -- \" OR 1=1 /*"
    assert c.post(f"/repositories/{rid}/search", json={"query": nasty, "k": 3}).status_code == 200
    assert c.post(f"/repositories/{rid}/ask", json={"question": nasty}).status_code == 200
    assert c.post("/auth/login", json={"email": nasty, "password": nasty}).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1   # users table intact
