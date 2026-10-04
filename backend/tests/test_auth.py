from datetime import timedelta

from app.db import SessionLocal
from app.models import AuthSession, User, utcnow

PW = "correct-horse-1"


def test_signup_sets_httponly_cookie_and_returns_user(new_client):
    c = new_client(signup=False)
    r = c.post("/auth/signup", json={"email": " New@Example.COM ", "password": PW})
    assert r.status_code == 201 and r.json()["email"] == "new@example.com" and r.json()["workspace"]["id"]
    sc = r.headers["set-cookie"].lower()
    assert "gc_session=" in sc and "httponly" in sc and "samesite=lax" in sc
    assert c.get("/auth/me").json()["email"] == "new@example.com"  # session persists across requests


def test_signup_validation_and_duplicates(new_client):
    c = new_client(signup=False)
    assert c.post("/auth/signup", json={"email": "a@b.co", "password": "short"}).status_code == 422
    assert c.post("/auth/signup", json={"email": "not-an-email", "password": PW}).json()["error"]["code"] == "invalid_email"
    assert c.post("/auth/signup", json={"email": "a@b.co", "password": PW}).status_code == 201
    r = c.post("/auth/signup", json={"email": "A@B.co", "password": PW})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_password_and_token_never_stored_in_plaintext(new_client):
    c = new_client(email="x@y.co")
    token = c.cookies.get("gc_session")
    with SessionLocal() as db:
        u = db.query(User).one()
        assert PW not in u.password_hash and u.password_hash.startswith("scrypt$")
        assert token not in {s.token_hash for s in db.query(AuthSession)}


def test_login_logout_cycle(new_client):
    c = new_client(email="x@y.co")
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/auth/me").status_code == 401
    other = new_client(signup=False)
    r = other.post("/auth/login", json={"email": "X@Y.co", "password": PW})
    assert r.status_code == 200 and other.get("/auth/me").json()["email"] == "x@y.co"


def test_logged_out_token_is_dead_server_side(new_client):
    c = new_client(email="x@y.co")
    stolen = c.cookies.get("gc_session")
    c.post("/auth/logout")
    thief = new_client(signup=False)
    thief.cookies.set("gc_session", stolen)
    assert thief.get("/auth/me").status_code == 401


def test_bad_credentials_are_generic(new_client):
    c = new_client(email="x@y.co")
    c2 = new_client(signup=False)
    a = c2.post("/auth/login", json={"email": "x@y.co", "password": "wrong-password"})
    b = c2.post("/auth/login", json={"email": "nobody@y.co", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401 and a.json()["error"]["message"] == b.json()["error"]["message"]


def test_login_rate_limit(new_client):
    new_client(email="x@y.co")
    c = new_client(signup=False)
    for _ in range(5):
        assert c.post("/auth/login", json={"email": "x@y.co", "password": "bad-password"}).status_code == 401
    r = c.post("/auth/login", json={"email": "x@y.co", "password": PW})  # even the right password is blocked
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


def test_expired_session(new_client):
    c = new_client(email="x@y.co")
    with SessionLocal() as db:
        s = db.query(AuthSession).one()
        s.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = c.get("/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"
    assert c.get("/auth/me").json()["error"]["code"] == "not_authenticated"  # row was purged
