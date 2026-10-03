"""Recursive repository scanner with ignore rules and language detection."""
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "out",
               "target", "vendor", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "coverage", ".gradle"}
SECRET_NAMES = {".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc", "credentials"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
LOCK_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "Pipfile.lock"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".tgz",
                   ".jar", ".exe", ".dll", ".so", ".dylib", ".class", ".pyc", ".woff", ".woff2", ".ttf",
                   ".eot", ".mp3", ".mp4", ".mov", ".bin", ".o", ".a", ".min.js", ".map"}
LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
             ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".go": "go", ".rs": "rust",
             ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
             ".kt": "kotlin", ".swift": "swift", ".sh": "shell", ".sql": "sql", ".html": "html", ".css": "css",
             ".md": "markdown", ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml"}
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5000


@dataclass
class ScannedFile:
    path: str
    language: str | None
    size_bytes: int
    content_hash: str
    modified_at: datetime


@dataclass
class ScanResult:
    files: list[ScannedFile]
    skipped: dict[str, int]
    truncated: bool = False


def _skip_reason(p: Path, size: int) -> str | None:
    name = p.name
    if name in SECRET_NAMES or name.startswith(".env") or name.endswith(SECRET_SUFFIXES):
        return "secret"
    if name in LOCK_NAMES:
        return "lockfile"
    if any(name.endswith(s) for s in BINARY_SUFFIXES):
        return "binary"
    if size > MAX_FILE_BYTES:
        return "too_large"
    if size == 0:
        return "empty"
    with open(p, "rb") as f:
        if b"\0" in f.read(8000):
            return "binary"
    return None


def scan_repository(root: str | Path) -> ScanResult:
    root = Path(root)
    files, skipped, truncated = [], {}, False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.is_symlink() or not p.is_file():
                skipped["symlink"] = skipped.get("symlink", 0) + 1
                continue
            st = p.stat()
            reason = _skip_reason(p, st.st_size)
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            if len(files) >= MAX_FILES:
                truncated = True
                continue
            files.append(ScannedFile(
                path=p.relative_to(root).as_posix(),
                language=LANGUAGES.get(p.suffix.lower()),
                size_bytes=st.st_size,
                content_hash=hashlib.sha256(p.read_bytes()).hexdigest(),
                modified_at=datetime.fromtimestamp(st.st_mtime, timezone.utc),
            ))
    return ScanResult(files, skipped, truncated)
