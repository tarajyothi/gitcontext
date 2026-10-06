import pytest
from fastapi.testclient import TestClient

from app.config import Settings, validate_production
from app.main import create_app

GOOD = dict(environment="production", cookie_secure=True, database_url="postgresql+psycopg://u:p@db/x", allowed_hosts="app.example.com")


def prod(**over) -> Settings:
    return Settings(**{**GOOD, **over})


def test_validate_production_accepts_good_config():
    assert validate_production(prod()) == []


@pytest.mark.parametrize("over,needle", [
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"database_url": "sqlite:///./x.db"}, "PostgreSQL"),
    ({"allowed_hosts": ""}, "ALLOWED_HOSTS"),
    ({"llm_provider": "anthropic", "llm_api_key": ""}, "LLM_API_KEY"),
    ({"embedding_provider": "openai", "embedding_api_key": ""}, "EMBEDDING_API_KEY"),
])
def test_validate_production_rejects_insecure_config(over, needle):
    assert any(needle in p for p in validate_production(prod(**over)))


def test_production_refuses_to_start_when_insecure():
    app = create_app(prod(cookie_secure=False))
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        with TestClient(app):
            pass


def test_production_hides_docs_and_sets_security_headers():
    c = TestClient(create_app(prod()), base_url="http://app.example.com")   # no lifespan: no DB needed
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    r = c.get("/auth/me")
    assert r.status_code == 401
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    assert "max-age" in r.headers["strict-transport-security"] and r.headers["x-request-id"]
    assert "access-control-allow-origin" not in c.get("/auth/me", headers={"Origin": "https://evil.example"}).headers


def test_development_keeps_docs_and_has_no_hsts():
    c = TestClient(create_app(Settings(environment="development", cookie_secure=False)))
    assert c.get("/docs").status_code == 200
    assert "strict-transport-security" not in c.get("/auth/me").headers


def test_host_allow_list_and_body_limit():
    c = TestClient(create_app(prod(max_body_bytes=100)), base_url="http://app.example.com")
    assert c.get("/auth/me", headers={"Host": "evil.example.com"}).status_code == 400
    r = c.post("/auth/login", content=b'{"email":"' + b"a" * 300 + b'"}', headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    assert c.post("/auth/login", json={"email": "a@b.co", "password": "x"}).status_code != 413


def test_request_id_is_echoed_and_bounded():
    c = TestClient(create_app(Settings(environment="development")))
    assert c.get("/auth/me", headers={"x-request-id": "abc123"}).headers["x-request-id"] == "abc123"
    assert len(c.get("/auth/me", headers={"x-request-id": "z" * 500}).headers["x-request-id"]) == 64
