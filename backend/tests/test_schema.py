import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import init_db, make_engine
from app.models import Chunk, RepoFile, Repository, User, Workspace


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        yield s


def _repo_file(s):
    u = User(email="a@b.co", password_hash="x")
    s.add(u); s.flush()
    w = Workspace(owner_id=u.id, name="w"); s.add(w); s.flush()
    r = Repository(workspace_id=w.id, url="https://github.com/o/n", owner="o", name="n")
    f = RepoFile(repository=r, path="a.py", language="python", size_bytes=10)
    s.add_all([r, f]); s.commit()
    return r, f


def test_chunk_traceable_to_file_and_lines(session):
    r, f = _repo_file(session)
    session.add(Chunk(repository_id=r.id, file_id=f.id, file_path=f.path, symbol="main",
                      symbol_kind="function", language="python", start_line=3, end_line=9, content="def main(): ..."))
    session.commit()
    c = session.query(Chunk).one()
    assert (c.file_path, c.start_line, c.end_line) == ("a.py", 3, 9)


def test_invalid_line_range_rejected(session):
    r, f = _repo_file(session)
    session.add(Chunk(repository_id=r.id, file_id=f.id, file_path=f.path, start_line=9, end_line=3, content="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_duplicate_file_path_rejected(session):
    r, _ = _repo_file(session)
    session.add(RepoFile(repository_id=r.id, path="a.py"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_cascade_delete(session):
    r, f = _repo_file(session)
    session.add(Chunk(repository_id=r.id, file_id=f.id, file_path="a.py", start_line=1, end_line=1, content="x"))
    session.commit()
    session.delete(r); session.commit()
    assert session.query(Chunk).count() == 0 and session.query(RepoFile).count() == 0
