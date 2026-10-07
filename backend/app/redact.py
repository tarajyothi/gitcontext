"""Mask well-known credential formats before text is stored, embedded or shown. Line count is always preserved."""
import re

_PATTERNS = [
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_live_key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("llm_api_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}\b")),
]
_PRIVATE_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")


def redact(text: str) -> tuple[str, int]:
    """Returns (masked text, number of secrets masked). The number of lines never changes."""
    n = 0

    def block(m: re.Match) -> str:
        nonlocal n
        n += 1
        return "[REDACTED:private_key]" + "\n" * m.group(0).count("\n")

    text = _PRIVATE_BLOCK.sub(block, text)
    for kind, rx in _PATTERNS:
        text, k = rx.subn(f"[REDACTED:{kind}]", text)
        n += k
    return text, n
