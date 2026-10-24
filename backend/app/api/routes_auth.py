"""Sign up, sign in, guest sessions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import current_user, optional_user, request_token
from app.models.schemas import (
    AuthResponse,
    GuestRequest,
    LoginRequest,
    PromoteGuestRequest,
    RegisterRequest,
)
from app.services import user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_payload(user: dict[str, Any]) -> AuthResponse:
    token = user_service.start_session(user["_id"])
    return AuthResponse(token=token, user=user_service.private_user(user) or {})


@router.post("/register", response_model=AuthResponse)
async def register(payload: RegisterRequest) -> AuthResponse:
    try:
        user = user_service.register(payload.email, payload.password, payload.username)
    except user_service.UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _auth_payload(user)


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    try:
        user = user_service.login(payload.email, payload.password)
    except user_service.UserError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _auth_payload(user)


@router.post("/guest", response_model=AuthResponse)
async def guest(payload: GuestRequest) -> AuthResponse:
    """Guest mode: a real, usable account with no email attached."""
    user = user_service.create_guest(payload.display_hint)
    return _auth_payload(user)


@router.post("/promote", response_model=AuthResponse)
async def promote(
    payload: PromoteGuestRequest, user: dict[str, Any] = Depends(current_user)
) -> AuthResponse:
    """Keep a guest's karma and history while attaching an email and password."""
    try:
        upgraded = user_service.promote_guest(
            user["_id"], payload.email, payload.password, payload.username
        )
    except user_service.UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _auth_payload(upgraded)


@router.post("/logout")
async def logout(token: str | None = Depends(request_token)) -> dict[str, Any]:
    return {"ok": bool(token and user_service.end_session(token))}


@router.get("/me")
async def me(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    return {"user": user_service.private_user(user), "authenticated": bool(user)}


@router.get("/username-available")
async def username_available(username: str) -> dict[str, Any]:
    return {
        "username": username,
        "available": bool(
            user_service.USERNAME_RE.match(username) and user_service.username_available(username)
        ),
    }
