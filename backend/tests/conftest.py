import os

os.environ["DATABASE_URL"] = "sqlite:///./test_gitcontext.db"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Fresh tables for every test so tests cannot leak rows into each other."""
    from app.db import Base, engine, init_db
    Base.metadata.drop_all(engine)
    init_db()
    yield
