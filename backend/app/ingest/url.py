"""Strict GitHub URL validation. Only https://github.com/<owner>/<repo> is accepted."""
import re

from .errors import IngestError

_URL = re.compile(r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})/?$")


def parse_github_url(raw: str) -> tuple[str, str]:
    """Return (owner, name). Raises IngestError(invalid_url) otherwise."""
    url = (raw or "").strip()
    if url.endswith(".git"):
        url = url[:-4]
    m = _URL.match(url)
    if not m or m.group(2) in {".", ".."} or m.group(2).startswith("-"):
        raise IngestError("invalid_url", "Enter a GitHub URL like https://github.com/owner/repo", 422)
    return m.group(1), m.group(2)
