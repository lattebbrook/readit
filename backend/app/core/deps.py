"""Shared FastAPI dependencies: request auth and permission gates."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app.services import user_service


def _extract_token(authorization: str | None, x_readit_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_readit_token


async def optional_user(
    authorization: str | None = Header(default=None),
    x_readit_token: str | None = Header(default=None, alias="X-ReadIt-Token"),
) -> dict[str, Any] | None:
    """Resolve the caller if they sent a valid token; anonymous browsing is allowed."""
    return user_service.resolve_token(_extract_token(authorization, x_readit_token))


async def current_user(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in or continue as a guest to do that.",
        )
    return user


async def admin_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only.")
    return user


async def request_token(
    authorization: str | None = Header(default=None),
    x_readit_token: str | None = Header(default=None, alias="X-ReadIt-Token"),
) -> str | None:
    return _extract_token(authorization, x_readit_token)
