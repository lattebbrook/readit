"""Password hashing and signed session tokens (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import settings

_PBKDF2_ROUNDS = 120_000


def hash_password(password: str) -> str:
    """Return ``pbkdf2$rounds$salt$digest`` for the given plaintext password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        expected = bytes.fromhex(digest_hex)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
    return hmac.compare_digest(candidate, expected)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def create_token(user_id: str, *, ttl: int | None = None) -> str:
    """Create a compact signed token: ``payload.signature``."""
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + (ttl if ttl is not None else settings.token_ttl_seconds),
        "jti": secrets.token_hex(8),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_token(token: str) -> dict | None:
    """Validate signature and expiry; return the payload or ``None``."""
    if not token or "." not in token:
        return None
    body, _, signature = token.partition(".")
    expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    try:
        provided = _b64decode(signature)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload
