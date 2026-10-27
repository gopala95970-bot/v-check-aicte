"""Password hashing (scrypt), JWT tokens with expiry + revocation, login throttling."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid

import jwt

ALGO = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return "scrypt${}${}${}${}${}".format(n, r, p, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# Constant-time-ish dummy so unknown users cost the same as wrong passwords.
_DUMMY = hash_password(secrets.token_urlsafe(12))


def burn_time(password: str) -> None:
    verify_password(password, _DUMMY)


def password_problems(pw: str) -> list[str]:
    out = []
    if len(pw) < 10:
        out.append("at least 10 characters")
    if pw.lower() == pw or pw.upper() == pw:
        out.append("both upper- and lower-case letters")
    if not any(c.isdigit() for c in pw):
        out.append("a digit")
    return out


def issue_token(secret: str, user_id: int, role: str, ttl_minutes: int) -> tuple[str, str, int]:
    now = int(time.time())
    jti = uuid.uuid4().hex
    exp = now + ttl_minutes * 60
    tok = jwt.encode({"sub": str(user_id), "role": role, "jti": jti, "iat": now, "exp": exp}, secret, algorithm=ALGO)
    return tok, jti, exp


def decode_token(secret: str, token: str) -> dict:
    return jwt.decode(token, secret, algorithms=[ALGO], options={"require": ["exp", "sub", "jti"]})


class LoginThrottle:
    """In-memory sliding window per key (email+ip). Good enough for a single-process demo."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max, self.window = max_failures, window_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str) -> list[float]:
        now = time.time()
        v = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = v
        return v

    def blocked_for(self, key: str) -> int:
        with self._lock:
            v = self._prune(key)
            if len(v) >= self.max:
                return max(1, int(self.window - (time.time() - v[0])))
            return 0

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
