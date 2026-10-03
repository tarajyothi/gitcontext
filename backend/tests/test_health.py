from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["database"] == "ok"
        assert "x-request-id" in r.headers


def test_unknown_route_uses_error_shape():
    with TestClient(app) as c:
        r = c.get("/nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "http_error"


def test_unhandled_error_is_safe():
    @app.get("/_boom")
    def boom():
        raise RuntimeError("secret internals")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/_boom")
        assert r.status_code == 500
        assert "secret" not in r.text
        assert r.json()["error"]["code"] == "internal_error"
