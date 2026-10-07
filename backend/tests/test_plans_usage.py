import httpx
import pytest

from app.answering import AnthropicGenerator, get_generator
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Workspace
from app.plans import MULTIPLIER, limits_for, set_plan
from tests.test_security import make_repo


def test_limits_scale_by_plan_and_unknown_plans_fall_back_to_free(monkeypatch):
    s = get_settings()
    free = limits_for("free")
    assert (free.repos, free.daily_questions) == (s.max_repos_per_workspace, s.daily_question_limit)
    for plan, m in MULTIPLIER.items():
        assert limits_for(plan).repos == free.repos * m and limits_for(plan).daily_questions == free.daily_questions * m
    assert limits_for("enterprise-gold").plan == "free" and limits_for(None).plan == "free"


def test_plan_upgrade_raises_limits_and_is_reflected_in_usage(tmp_path, monkeypatch, new_client):
    monkeypatch.setattr(get_settings(), "max_repos_per_workspace", 1)
    c, rid, _ = make_repo(tmp_path, monkeypatch, new_client, {"a.py": "def a():\n    return 1\n"})
    assert c.get("/usage").json()["plan"] == "free" and c.get("/usage").json()["repositories"] == {"used": 1, "limit": 1}
    blocked = c.post("/repositories", json={"url": "https://github.com/acme/second"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "repo_limit_reached" and "free plan" in blocked.json()["error"]["message"]
    with SessionLocal() as db:
        ws = db.query(Workspace).one()
        set_plan(db, ws, "pro")
        with pytest.raises(ValueError):
            set_plan(db, ws, "platinum")
    u = c.get("/usage").json()
    assert u["plan"] == "pro" and u["repositories"]["limit"] == 5 and u["questions"]["limit"] == get_settings().daily_question_limit * 5
    assert c.post("/repositories", json={"url": "https://github.com/acme/second"}).status_code == 202


def test_usage_reports_storage_and_llm_tokens(tmp_path, monkeypatch, new_client):
    c, rid, _ = make_repo(tmp_path, monkeypatch, new_client, {"auth.py": "def login_user(u):\n    \"\"\"Log the user in.\"\"\"\n    return u\n"})
    u0 = c.get("/usage").json()
    assert u0["storage_bytes"] > 0 and u0["llm_tokens_today"] == {"input": 0, "output": 0}

    def handler(req):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "`login_user` logs the user in [1]."}],
                                         "usage": {"input_tokens": 1200, "output_tokens": 85}})
    app.dependency_overrides[get_generator] = lambda: AnthropicGenerator("sk-test", "m", "https://llm.test/v1", httpx.MockTransport(handler))
    for _ in range(2):
        r = c.post(f"/repositories/{rid}/ask", json={"question": "where is the user login implemented"}).json()
        assert r["generation"] == "llm" and r["usage"] == [1200, 85]
    assert c.get("/usage").json()["llm_tokens_today"] == {"input": 2400, "output": 170}
    # extractive answers cost no tokens
    app.dependency_overrides[get_generator] = lambda: None
    assert c.post(f"/repositories/{rid}/ask", json={"question": "where is the user login implemented"}).json()["usage"] is None
    assert c.get("/usage").json()["llm_tokens_today"] == {"input": 2400, "output": 170}
