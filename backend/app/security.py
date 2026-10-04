"""Password hashing (scrypt, stdlib), session tokens, and a login-failure limiter."""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${2**14}$8$1${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("timing-equaliser")  # verified when the email is unknown (no user-enumeration timing)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class FailureLimiter:
    """In-memory (single-process) limiter: max failures per key within a window."""

    def __init__(self, max_failures: int = 5, window_s: int = 900):
        self.max, self.window, self._f = max_failures, window_s, defaultdict(list)

    def blocked(self, key: str) -> bool:
        now = time.time()
        self._f[key] = [t for t in self._f[key] if now - t < self.window]
        return len(self._f[key]) >= self.max

    def fail(self, key: str) -> None:
        self._f[key].append(time.time())

    def reset(self, key: str | None = None) -> None:
        self._f.pop(key, None) if key else self._f.clear()


login_limiter = FailureLimiter()
