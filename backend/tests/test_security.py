"""Unit tests for password hashing and signed session tokens."""

from __future__ import annotations

import time

from app.config import settings
from app.core import security


def test_hash_password_is_salted():
    first = security.hash_password("hunter22")
    second = security.hash_password("hunter22")
    assert first != second
    assert first.startswith("pbkdf2$")


def test_verify_password_round_trip():
    encoded = security.hash_password("hunter22")
    assert security.verify_password("hunter22", encoded)
    assert not security.verify_password("hunter23", encoded)


def test_verify_password_rejects_malformed_input():
    assert not security.verify_password("x", None)
    assert not security.verify_password("x", "")
    assert not security.verify_password("x", "garbage")
    assert not security.verify_password("x", "bcrypt$1$aa$bb")
    assert not security.verify_password("x", "pbkdf2$1$zz$zz")


def test_token_round_trip_carries_subject():
    token = security.create_token("user-123")
    payload = security.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["exp"] > time.time()


def test_token_rejects_tampering():
    token = security.create_token("user-123")
    body, _, signature = token.partition(".")
    assert security.decode_token(f"{body}x.{signature}") is None
    assert security.decode_token(f"{body}.{signature[:-2]}xy") is None


def test_token_rejects_wrong_secret():
    token = security.create_token("user-123")
    original = settings.secret_key
    try:
        settings.secret_key = "a-different-secret"
        assert security.decode_token(token) is None
    finally:
        settings.secret_key = original


def test_expired_token_is_rejected():
    assert security.decode_token(security.create_token("user-123", ttl=-1)) is None


def test_decode_handles_junk():
    assert security.decode_token("") is None
    assert security.decode_token("nodot") is None
    assert security.decode_token("!!!.!!!") is None


def test_tokens_are_unique_per_call():
    assert security.create_token("u") != security.create_token("u")
