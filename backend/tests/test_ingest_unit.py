import subprocess
from pathlib import Path

import pytest

from app.ingest.cloner import clone_repo
from app.ingest.errors import IngestError
from app.ingest.scanner import scan_repository
from app.ingest.url import parse_github_url


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/octocat/Hello-World", ("octocat", "Hello-World")),
    ("https://github.com/octocat/Hello-World/", ("octocat", "Hello-World")),
    ("  https://github.com/octocat/Hello-World.git ", ("octocat", "Hello-World")),
])
def test_valid_urls(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", [
    "", "not a url", "http://github.com/a/b", "https://gitlab.com/a/b", "https://github.com/a",
    "https://github.com/a/b/tree/main", "https://github.com/a/b?x=1", "file:///etc/passwd",
    "https://github.com/a/--upload-pack=x", "https://github.com/../etc", "https://evil.com/github.com/a/b",
    "git@github.com:a/b.git", "https://github.com/a/b c",
])
def test_invalid_urls(url):
    with pytest.raises(IngestError) as e:
        parse_github_url(url)
    assert e.value.code == "invalid_url"


def test_scanner_ignores_and_detects(tmp_path: Path):
    def w(p, data=b"x = 1\n"):
        f = tmp_path / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(data)
    w("src/app.py"); w("web/index.ts"); w("README.md")
    w("node_modules/lib/index.js"); w(".git/config"); w("dist/out.js"); w("__pycache__/a.pyc")
    w(".env", b"SECRET=1"); w("deploy/key.pem", b"-----BEGIN"); w("logo.png", b"\x89PNG\0\0")
    w("data.bin", b"ab\0cd"); w("package-lock.json", b"{}"); w("empty.py", b""); w("big.py", b"a" * 1_100_000)
    r = scan_repository(tmp_path)
    got = {f.path: f.language for f in r.files}
    assert got == {"src/app.py": "python", "web/index.ts": "typescript", "README.md": "markdown"}
    assert r.skipped["secret"] == 2 and r.skipped["binary"] >= 2 and r.skipped["too_large"] == 1
    f = next(f for f in r.files if f.path == "src/app.py")
    assert f.size_bytes == 6 and len(f.content_hash) == 64 and f.modified_at.tzinfo


def test_clone_empty_local_repo(tmp_path):
    src = tmp_path / "empty"; subprocess.run(["git", "init", "-q", str(src)], check=True)
    res = clone_repo(str(src), tmp_path / "ws" / "dest")
    assert res.commit_sha is None


def test_clone_missing_repo_is_classified(tmp_path):
    with pytest.raises(IngestError) as e:
        clone_repo(str(tmp_path / "nope"), tmp_path / "ws" / "d")
    assert e.value.code in {"clone_failed", "repo_not_accessible"}
