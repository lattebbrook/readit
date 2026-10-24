"""Profiles, settings, subscriptions, inbox, data export and wipe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import current_user, optional_user
from app.models.schemas import (
    InterestsUpdate,
    PreferencesUpdate,
    ProfileUpdate,
    WipeRequest,
)
from app.services import (
    comment_service,
    notification_service,
    persona_service,
    post_service,
    subreddit_service,
    user_service,
)

router = APIRouter(prefix="/api", tags=["users"])


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

@router.patch("/me/profile")
async def update_profile(
    payload: ProfileUpdate, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = user_service.update_profile(user["_id"], changes)
    return {"user": user_service.private_user(updated)}


@router.patch("/me/preferences")
async def update_preferences(
    payload: PreferencesUpdate, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    updated = user_service.update_preferences(user["_id"], payload.preferences)
    return {"user": user_service.private_user(updated)}


@router.put("/me/interests")
async def set_interests(
    payload: InterestsUpdate, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    updated = user_service.set_interests(user["_id"], payload.interests)
    return {"user": user_service.private_user(updated)}


@router.post("/me/subscriptions/{name}")
async def subscribe(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    updated = user_service.subscribe(user["_id"], board["name"])
    subreddit_service.bump_subscribers(board["name"], 1)
    return {"user": user_service.private_user(updated), "subscribed": True}


@router.delete("/me/subscriptions/{name}")
async def unsubscribe(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    board = subreddit_service.get(name)
    updated = user_service.unsubscribe(user["_id"], board["name"] if board else name)
    if board:
        subreddit_service.bump_subscribers(board["name"], -1)
    return {"user": user_service.private_user(updated), "subscribed": False}


@router.post("/me/blocked-boards/{name}")
async def block_board(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Personal block — the board stops appearing anywhere for this account."""
    board = subreddit_service.get(name)
    updated = user_service.ban_subreddit(user["_id"], board["name"] if board else name)
    return {"user": user_service.private_user(updated)}


@router.delete("/me/blocked-boards/{name}")
async def unblock_board(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    board = subreddit_service.get(name)
    updated = user_service.unban_subreddit(user["_id"], board["name"] if board else name)
    return {"user": user_service.private_user(updated)}


# --------------------------------------------------------------------------- #
# Saved posts
# --------------------------------------------------------------------------- #

@router.get("/me/saved")
async def list_saved(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    posts = post_service.posts_by_ids(user.get("saved_posts", []))
    return {"posts": post_service.public_posts(posts, user)}


@router.post("/me/saved/{post_id}")
async def save_post(post_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not post_service.get(post_id):
        raise HTTPException(status_code=404, detail="That post is gone.")
    updated = user_service.save_post(user["_id"], post_id)
    return {"user": user_service.private_user(updated), "saved": True}


@router.delete("/me/saved/{post_id}")
async def unsave_post(post_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    updated = user_service.unsave_post(user["_id"], post_id)
    return {"user": user_service.private_user(updated), "saved": False}


# --------------------------------------------------------------------------- #
# Inbox
# --------------------------------------------------------------------------- #

@router.get("/me/inbox")
async def inbox(
    unread_only: bool = False, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    return {
        "notifications": notification_service.list_for(user["_id"], unread_only=unread_only),
        "unread": notification_service.unread_count(user["_id"]),
    }


@router.post("/me/inbox/read")
async def mark_all_read(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"marked": notification_service.mark_all_read(user["_id"])}


@router.post("/me/inbox/{notification_id}/read")
async def mark_read(
    notification_id: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    return {"notification": notification_service.mark_read(notification_id)}


@router.delete("/me/inbox")
async def clear_inbox(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"cleared": notification_service.clear(user["_id"])}


# --------------------------------------------------------------------------- #
# Data controls
# --------------------------------------------------------------------------- #

@router.get("/me/export")
async def export_data(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    try:
        return user_service.export_profile(user["_id"])
    except user_service.UserError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/me/wipe")
async def wipe(payload: WipeRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Nuke everything this account wrote.

    Content is not erased from threads — it is tombstoned the way the real site
    does it, so replies underneath still make sense.
    """
    if payload.confirm.strip().upper() != "WIPE":
        raise HTTPException(status_code=400, detail="Type WIPE to confirm.")
    try:
        summary = user_service.wipe_content(user["_id"], delete_account=payload.delete_account)
    except user_service.UserError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return summary


# --------------------------------------------------------------------------- #
# Public profiles
# --------------------------------------------------------------------------- #

@router.get("/users/{username}")
async def public_profile(
    username: str, viewer: dict[str, Any] | None = Depends(optional_user)
) -> dict[str, Any]:
    """One endpoint for people and personas — the UI must not be able to tell."""
    account = user_service.get_by_username(username)
    profile = (
        user_service.public_user(account)
        if account
        else persona_service.public_persona(persona_service.get_persona(username))
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No such user.")

    if account:
        posts = post_service.user_posts(account["_id"])
        comments = comment_service.user_comments(account["_id"])
    else:
        posts = post_service.by_author_name(profile["username"])
        comments = comment_service.by_author_name(profile["username"])

    return {
        "profile": profile,
        "posts": post_service.public_posts(posts, viewer),
        "comments": [comment_service.public_comment(c, viewer) for c in comments],
        "is_self": bool(account and viewer and account["_id"] == viewer["_id"]),
    }
