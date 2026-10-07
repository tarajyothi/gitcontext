"""Shallow git clone into a controlled workspace, with classified failures, bounded retries and safe defaults."""
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .errors import IngestError

CLONE_TIMEOUT_S = 120
ATTEMPTS = 3  # first try + 2 retries (transient network errors only), backoff 1s then 2s


@dataclass
class CloneResult:
    path: Path
    commit_sha: str | None
    branch: str | None


def _git(args, cwd=None, timeout=30):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo", "GCM_INTERACTIVE": "never",
           # only https unless the operator overrides (blocks ext::/file::/ssh tricks); hooks are never run by clone
           "GIT_ALLOW_PROTOCOL": os.environ.get("GIT_ALLOW_PROTOCOL", "https")}
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "transfer.fsckObjects=true", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout)  # noqa: S603


def _dir_bytes(root: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def clone_repo(clone_url: str, dest: Path) -> CloneResult:
    """Clone depth=1 into dest (replaced if present). dest must be inside the workspace."""
    for attempt in range(ATTEMPTS):
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = _git(["clone", "--depth", "1", "--quiet", "--no-tags", "--", clone_url, str(dest)], timeout=CLONE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            shutil.rmtree(dest, ignore_errors=True)
            raise IngestError("clone_timeout", f"Cloning took longer than {CLONE_TIMEOUT_S}s", 504) from None
        if r.returncode == 0:
            break
        shutil.rmtree(dest, ignore_errors=True)
        err = r.stderr.lower()
        if any(s in err for s in ("not found", "could not read username", "authentication", "403", "access denied")):
            # GitHub deliberately answers the same for private and non-existent repos. Not transient: no retry.
            raise IngestError("repo_not_accessible", "Repository not found or private. Only public repositories are supported.", 404)
        if attempt == ATTEMPTS - 1:
            raise IngestError("clone_failed", "Could not clone the repository. Please try again later.", 502)
        time.sleep(2 ** attempt)
    if _dir_bytes(dest) > get_settings().max_clone_bytes:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError("repo_too_large", "This repository is too large to clone and index.", 413)
    head = _git(["rev-parse", "HEAD"], cwd=dest)
    if head.returncode != 0:  # empty repository: clone succeeds but there is no HEAD
        return CloneResult(dest, None, None)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest).stdout.strip() or None
    return CloneResult(dest, head.stdout.strip(), branch)
