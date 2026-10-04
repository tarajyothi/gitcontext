import os

os.environ["DATABASE_URL"] = "sqlite:///./test_gitcontext.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Fresh tables + limiter state for every test so tests cannot leak into each other."""
    from app.db import Base, engine, init_db
    from app.security import login_limiter
    Base.metadata.drop_all(engine)
    init_db()
    login_limiter.reset()
    yield


@pytest.fixture()
def new_client():
    """Factory: each call returns a TestClient (own cookie jar) signed up as a distinct user."""
    from app.main import app
    made = []

    def make(email: str | None = None, signup: bool = True) -> TestClient:
        c = TestClient(app)
        c.__enter__()
        made.append(c)
        if signup:
            r = c.post("/auth/signup", json={"email": email or f"user{len(made)}@example.com", "password": "correct-horse-1"})
            assert r.status_code == 201, r.text
        return c

    yield make
    for c in made:
        c.__exit__(None, None, None)
    app.dependency_overrides.clear()
