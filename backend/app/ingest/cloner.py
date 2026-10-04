"""Shallow git clone into a controlled workspace, with classified failures."""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import IngestError

CLONE_TIMEOUT_S = 120


@dataclass
class CloneResult:
    path: Path
    commit_sha: str | None
    branch: str | None


def _git(args, cwd=None, timeout=30):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo", "GCM_INTERACTIVE": "never"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def clone_repo(clone_url: str, dest: Path) -> CloneResult:
    """Clone depth=1 into dest (replaced if present). dest must be inside the workspace."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = _git(["clone", "--depth", "1", "--quiet", "--no-tags", "--", clone_url, str(dest)], timeout=CLONE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError("clone_timeout", f"Cloning took longer than {CLONE_TIMEOUT_S}s", 504) from None
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        err = r.stderr.lower()
        if any(s in err for s in ("not found", "could not read username", "authentication", "403", "access denied")):
            # GitHub deliberately answers the same for private and non-existent repos.
            raise IngestError("repo_not_accessible",
                              "Repository not found or private. Only public repositories are supported.", 404)
        raise IngestError("clone_failed", "Could not clone the repository.", 502)
    head = _git(["rev-parse", "HEAD"], cwd=dest)
    if head.returncode != 0:  # empty repository: clone succeeds but there is no HEAD
        return CloneResult(dest, None, None)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest).stdout.strip() or None
    return CloneResult(dest, head.stdout.strip(), branch)
