"""Password hashing with PBKDF2-HMAC-SHA256 (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


_ITERATIONS = 260_000
_SALT_LEN = 16


def hash_password(password: str) -> str:
    """Return a base64-encoded PBKDF2 hash string (salt + digest)."""
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return base64.b64encode(salt + dk).decode()


def verify_password(password: str, stored: str) -> bool:
    """Verify a plaintext password against a hash produced by hash_password."""
    try:
        data = base64.b64decode(stored.encode())
    except Exception:
        return False
    salt, dk = data[:_SALT_LEN], data[_SALT_LEN:]
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(check, dk)
