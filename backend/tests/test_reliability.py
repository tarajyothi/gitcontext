import json
import logging
import os
import subprocess

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.ingest import cloner
from app.ingest.errors import IngestError
from app.logging_setup import JsonFormatter, configure_logging
from app.main import app
from tests.test_security import make_repo


class Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def fake_git(script, calls):
    """Returns a replacement for cloner._git that plays back `script` results for `git clone` calls."""
    def _git(args, cwd=None, timeout=30):
        if "clone" in args:
            calls.append(1)
            rc, err = script[min(len(calls), len(script)) - 1]
            if rc == 0:
                dest = cloner.Path(args[-1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "a.py").write_text("x = 1\n" * 10)
            return Proc(rc, "", err)
        return Proc(0, "abc123def456\n" if "HEAD" in args else "main\n")
    return _git


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(cloner.time, "sleep", lambda s: None)


def test_clone_retries_transient_failures_then_succeeds(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cloner, "_git", fake_git([(128, "fatal: unable to access: Could not resolve host"), (128, "Connection reset"), (0, "")], calls))
    res = cloner.clone_repo("https://github.com/a/b.git", tmp_path / "d")
    assert len(calls) == 3 and res.commit_sha == "abc123def456"


def test_clone_gives_up_after_bounded_retries_with_a_safe_message(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cloner, "_git", fake_git([(128, "fatal: leaked internal detail /srv/secret")], calls))
    with pytest.raises(IngestError) as e:
        cloner.clone_repo("https://github.com/a/b.git", tmp_path / "d")
    assert len(calls) == cloner.ATTEMPTS == 3 and e.value.code == "clone_failed" and "secret" not in e.value.message
    assert not (tmp_path / "d").exists()


def test_not_found_is_never_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cloner, "_git", fake_git([(128, "remote: Repository not found.")], calls))
    with pytest.raises(IngestError) as e:
        cloner.clone_repo("https://github.com/a/b.git", tmp_path / "d")
    assert len(calls) == 1 and e.value.code == "repo_not_accessible"


def test_oversized_checkout_is_rejected_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(cloner, "_git", fake_git([(0, "")], []))
    monkeypatch.setattr(get_settings(), "max_clone_bytes", 5)
    with pytest.raises(IngestError) as e:
        cloner.clone_repo("https://github.com/a/b.git", tmp_path / "d")
    assert e.value.code == "repo_too_large" and not (tmp_path / "d").exists()


def test_git_runs_with_safe_defaults(tmp_path, monkeypatch):
    seen = {}
    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        return Proc(0, "")
    monkeypatch.delenv("GIT_ALLOW_PROTOCOL", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    cloner._git(["status"])
    assert "core.hooksPath=/dev/null" in seen["cmd"] and "transfer.fsckObjects=true" in seen["cmd"]
    assert seen["env"]["GIT_ALLOW_PROTOCOL"] == "https" and seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


# ---------------------------------------------------------------- readiness, logs, DB timeout
def test_ready_reports_checks_and_fails_when_workspace_unusable(tmp_path, monkeypatch, new_client):
    c = new_client(signup=False)
    monkeypatch.setattr(get_settings(), "workspace_dir", str(tmp_path / "ws"))
    r = c.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["checks"]["database"] == "ok"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(get_settings(), "workspace_dir", str(blocker / "sub"))   # cannot create a directory under a file
    r = c.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["workspace_writable"] == "fail"


def test_json_logs_are_one_parseable_object_per_line():
    rec = logging.LogRecord("gitcontext", logging.INFO, __file__, 1, "GET %s -> %d", ("/x", 200), None)
    rec.request_id, rec.status, rec.ms = "abc", 200, 7
    d = json.loads(JsonFormatter().format(rec))
    assert d["msg"] == "GET /x -> 200" and d["request_id"] == "abc" and d["status"] == 200 and d["level"] == "INFO"
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec2 = logging.LogRecord("gitcontext", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "ValueError" in json.loads(JsonFormatter().format(rec2))["exc"]      # stack stays in server logs
    configure_logging("INFO", "json")
    configure_logging("INFO", "text")                                          # idempotent, no duplicate handlers
    assert len(logging.getLogger().handlers) == 1


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("postgres"), reason="PostgreSQL only")
def test_postgres_statement_timeout_aborts_slow_queries(monkeypatch):
    from app.db import make_engine
    monkeypatch.setattr(get_settings(), "db_statement_timeout_ms", 300)
    eng = make_engine(os.environ["TEST_DATABASE_URL"])
    with eng.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "300ms"
        with pytest.raises(Exception, match="(?i)timeout|canceled"):
            conn.execute(text("SELECT pg_sleep(3)"))


# ---------------------------------------------------------------- rate limits
FILES = {"a.py": "def refund_payment():\n    return 1\n"}


def test_per_user_rate_limits_with_retry_after(tmp_path, monkeypatch, new_client):
    c, rid, _ = make_repo(tmp_path, monkeypatch, new_client, FILES)
    other = new_client()
    monkeypatch.setattr(get_settings(), "rate_search_per_min", 3)
    monkeypatch.setattr(get_settings(), "rate_ask_per_min", 2)
    assert [c.post(f"/repositories/{rid}/search", json={"query": "refund"}).status_code for _ in range(3)] == [200, 200, 200]
    r = c.post(f"/repositories/{rid}/search", json={"query": "refund"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert [c.post(f"/repositories/{rid}/ask", json={"question": "what is refund payment"}).status_code for _ in range(3)] == [200, 200, 429]
    assert other.get("/usage").status_code == 200                                # limits are per user, not global


def test_write_and_signup_limits(tmp_path, monkeypatch, new_client):
    c, rid, _ = make_repo(tmp_path, monkeypatch, new_client, FILES)
    from app.security import rate_limiter
    rate_limiter.reset()                      # creating the repo above already used one shared "write" slot
    monkeypatch.setattr(get_settings(), "rate_write_per_min", 2)
    codes = [c.post(f"/repositories/{rid}/reindex").status_code for _ in range(3)]
    assert codes == [202, 202, 429]
    monkeypatch.setattr(get_settings(), "rate_signup_per_hour", 2)
    anon = new_client(signup=False)
    codes = [anon.post("/auth/signup", json={"email": f"s{i}@example.com", "password": "correct-horse-1"}).status_code for i in range(3)]
    assert codes == [201, 201, 429]
