"""Feeds, threads, commenting, voting, awards, sharing and search."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.deps import current_user, optional_user
from app.db import db, now
from app.models.schemas import (
    AwardRequest,
    CommentCreate,
    CommentEdit,
    GenerateRequest,
    PostCreate,
    PostEdit,
    ReportRequest,
    VoteRequest,
)
from app.services import (
    award_service,
    comment_service,
    config_service,
    generation_service,
    media_service,
    moderation_service,
    notification_service,
    post_service,
    simulation,
    subreddit_service,
    user_service,
    vote_service,
)

router = APIRouter(prefix="/api", tags=["content"])

THREAD_LOAD_TIMEOUT = 120.0


# --------------------------------------------------------------------------- #
# Feeds
# --------------------------------------------------------------------------- #

@router.get("/feed")
async def feed(
    background: BackgroundTasks,
    scope: str = "home",
    sort: str = "hot",
    limit: int = Query(default=25, ge=1, le=100),
    skip: int = 0,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    posts = post_service.feed_for_user(user, scope=scope, sort=sort, limit=limit, skip=skip)

    # A thin front page quietly asks the world for more — unless the world has
    # been switched off, in which case quiet means quiet.
    if len(posts) < 5 and config_service.automatic_generation_allowed():
        for board in subreddit_service.list_boards(limit=3, sort="active"):
            background.add_task(generation_service.generate_posts, board["name"], count=4)

    return {
        "posts": post_service.public_posts(posts, user),
        "scope": scope,
        "sort": sort,
        "has_more": len(posts) == limit,
    }


@router.get("/search")
async def search(
    q: str,
    subreddit: str | None = None,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    posts = post_service.search(q, subreddit=subreddit)
    boards = subreddit_service.list_boards(query=q, limit=10)
    return {
        "posts": post_service.public_posts(posts, user),
        "boards": [subreddit_service.public_board(board, user) for board in boards],
    }


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #

@router.post("/posts")
async def create_post(
    payload: PostCreate,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    board = subreddit_service.get(payload.subreddit)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{payload.subreddit} not found.")
    if not board.get("allow_user_posts", True):
        raise HTTPException(status_code=403, detail="This board is not accepting posts.")

    media = media_service.get(payload.media_id) if payload.media_id else None
    if payload.media_id and not media:
        raise HTTPException(status_code=404, detail="That image is no longer available.")
    if board.get("kind") == "photo" and not media:
        raise HTTPException(
            status_code=400, detail=f"r/{board['name']} is a photo board — posts need an image."
        )

    try:
        post = post_service.create(
            subreddit=board["name"],
            title=payload.title,
            body=payload.body,
            author=user["username"],
            author_id=user["_id"],
            author_kind="human",
            kind="image" if media else payload.kind,
            link_url=payload.link_url,
            media_id=payload.media_id,
            flair=payload.flair,
            # An image the vision pass already flagged as adult marks its own
            # post, so the reader's NSFW preference is respected either way.
            nsfw=payload.nsfw
            or bool(board.get("nsfw"))
            or bool((media or {}).get("analysis", {}).get("nsfw")),
            spoiler=payload.spoiler,
            quality=0.55,
            controversy=0.3,
        )
    except post_service.PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    simulation.register_participation(post["_id"], user["_id"])
    if payload.generate_replies and config_service.automatic_generation_allowed():
        background.add_task(generation_service.generate_comments, post["_id"], user=user)

    return {"post": post_service.public_post(post, user)}


@router.get("/posts/{post_id}")
async def get_post(
    post_id: str,
    background: BackgroundTasks,
    sort: str = "best",
    wait: bool = True,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """Open a thread.

    On the first view the discussion does not exist yet, so it is written now —
    that is the whole trick. Later views return instantly and let the background
    world add the stragglers.
    """
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")

    board = subreddit_service.get(post.get("subreddit", ""))
    post_service.increment_views(post_id)
    simulation.register_view(post_id, (user or {}).get("_id"))

    preferences = (user or {}).get("preferences") or {}
    auto = preferences.get("auto_generate_on_open", True)
    empty = comment_service.count_for_post(post_id) == 0

    generated = 0
    if empty and auto and not post.get("locked") and config_service.automatic_generation_allowed():
        if wait:
            try:
                created = await asyncio.wait_for(
                    generation_service.ensure_thread_populated(post_id, user),
                    timeout=THREAD_LOAD_TIMEOUT,
                )
                generated = len(created)
            except asyncio.TimeoutError:
                generated = 0
        else:
            background.add_task(generation_service.ensure_thread_populated, post_id, user)

    hide_removed = bool(preferences.get("hide_removed"))
    fresh = post_service.get(post_id) or post
    return {
        "post": post_service.public_post(fresh, user),
        "board": subreddit_service.public_board(board, user) if board else None,
        "comments": comment_service.build_tree(
            post_id, user, sort=sort, hide_removed=hide_removed
        ),
        "sort": sort,
        "generated": generated,
        "server_time": now(),
    }


@router.get("/posts/{post_id}/updates")
async def post_updates(
    post_id: str,
    since: float = 0.0,
    sort: str = "best",
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """Poll target: has anything landed in this thread since I last looked?"""
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")

    new_comments = [
        comment
        for comment in comment_service.for_post(post_id)
        if comment.get("created_at", 0) > since
    ]
    changed = bool(new_comments) or post.get("last_generated_at", 0) > since

    payload: dict[str, Any] = {
        "changed": changed,
        "new_comments": len(new_comments),
        "post": post_service.public_post(post, user),
        "server_time": now(),
        "generating": post.get("generation_state") == "generating",
    }
    if changed:
        preferences = (user or {}).get("preferences") or {}
        payload["comments"] = comment_service.build_tree(
            post_id, user, sort=sort, hide_removed=bool(preferences.get("hide_removed"))
        )
    return payload


@router.post("/posts/{post_id}/generate")
async def generate_more_comments(
    post_id: str,
    payload: GenerateRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """The "load more discussion" button: summon another wave of replies."""
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")
    try:
        created = await asyncio.wait_for(
            generation_service.generate_comments(
                post_id, count=payload.count, user=user, focus=payload.focus, live=True
            ),
            timeout=THREAD_LOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Generation timed out — try again.") from None
    return {
        "created": len(created),
        "comments": comment_service.build_tree(post_id, user),
        "post": post_service.public_post(post_service.get(post_id) or post, user),
    }


@router.patch("/posts/{post_id}")
async def edit_post(
    post_id: str, payload: PostEdit, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")
    if post.get("author_id") != user["_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="That isn't yours to edit.")
    updated = post_service.edit(post_id, title=payload.title, body=payload.body)
    return {"post": post_service.public_post(updated or post, user)}


@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")
    if post.get("author_id") != user["_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="That isn't yours to delete.")
    updated = post_service.delete_by_author(post_id)
    return {"post": post_service.public_post(updated or post, user)}


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

@router.post("/posts/{post_id}/comments")
async def add_comment(
    post_id: str,
    payload: CommentCreate,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    post = post_service.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="That thread is gone.")

    try:
        comment = comment_service.create(
            post_id=post_id,
            parent_id=payload.parent_id,
            body=payload.body,
            author=user["username"],
            author_id=user["_id"],
            author_kind="human",
            subreddit=post.get("subreddit", ""),
            quality=0.6,
        )
    except comment_service.CommentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    simulation.register_participation(post_id, user["_id"])

    # Somebody always answers. That is the point of posting — unless the
    # simulation is off, in which case nobody is home.
    if payload.generate_replies and config_service.automatic_generation_allowed():
        background.add_task(generation_service.reply_to_user_comment, comment["_id"], user)

    return {"comment": comment_service.public_comment(comment, user)}


@router.patch("/comments/{comment_id}")
async def edit_comment(
    comment_id: str, payload: CommentEdit, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    comment = comment_service.get(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="That comment is gone.")
    if comment.get("author_id") != user["_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="That isn't yours to edit.")
    updated = comment_service.edit(comment_id, payload.body)
    return {"comment": comment_service.public_comment(updated or comment, user)}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    comment = comment_service.get(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="That comment is gone.")
    if comment.get("author_id") != user["_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="That isn't yours to delete.")
    updated = comment_service.delete_by_author(comment_id)
    return {"comment": comment_service.public_comment(updated or comment, user)}


@router.post("/comments/{comment_id}/replies")
async def summon_replies(
    comment_id: str,
    payload: GenerateRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """Poke the thread: get answers to one specific comment right now."""
    comment = comment_service.get(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="That comment is gone.")
    try:
        created = await asyncio.wait_for(
            generation_service.reply_to_user_comment(comment_id, user, count=payload.count),
            timeout=THREAD_LOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Generation timed out — try again.") from None
    return {
        "created": len(created),
        "comments": comment_service.build_tree(comment["post_id"], user),
    }


# --------------------------------------------------------------------------- #
# Votes, awards, sharing, reports
# --------------------------------------------------------------------------- #

@router.post("/vote/{kind}/{target_id}")
async def vote(
    kind: str,
    target_id: str,
    payload: VoteRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        return vote_service.cast_vote(user["_id"], kind, target_id, payload.direction)
    except vote_service.VoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/awards")
async def award_catalogue(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    return {"awards": award_service.catalogue(), "coins": (user or {}).get("coins", 0)}


@router.post("/award/{kind}/{target_id}")
async def give_award(
    kind: str,
    target_id: str,
    payload: AwardRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        result = award_service.grant(
            kind,
            target_id,
            payload.award_id,
            giver_id=user["_id"],
            giver_username=user["username"],
            anonymous=payload.anonymous,
        )
    except award_service.AwardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target = result["target"]
    if target:
        notification_service.notify_award(
            target, result["award"], None if payload.anonymous else user["username"]
        )
    refreshed = user_service.get_user(user["_id"])
    return {
        "award": result["award"],
        "awards": award_service.awards_for(kind, target_id),
        "coins": (refreshed or {}).get("coins", 0),
    }


@router.post("/share/{kind}/{target_id}")
async def share(
    kind: str, target_id: str, user: dict[str, Any] | None = Depends(optional_user)
) -> dict[str, Any]:
    """Record a share and hand back the canonical link."""
    collection = {"post": "posts", "comment": "comments"}.get(kind)
    if not collection:
        raise HTTPException(status_code=400, detail="You can only share posts and comments.")
    target = db.collection(collection).get(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="That content is gone.")

    db.collection(collection).update(target_id, {"$inc": {"shares": 1}})
    db.collection("activity").insert(
        {"kind": "share", "target_kind": kind, "target_id": target_id, "at": now()}
    )

    post_id = target["_id"] if kind == "post" else target.get("post_id")
    subreddit = target.get("subreddit", "")
    path = f"/r/{subreddit}/comments/{post_id}"
    if kind == "comment":
        path += f"?comment={target_id}"
    updated = db.collection(collection).get(target_id) or target
    return {"url": path, "shares": updated.get("shares", 0)}


@router.post("/report/{kind}/{target_id}")
async def report(
    kind: str,
    target_id: str,
    payload: ReportRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    entry = moderation_service.report(
        kind, target_id, payload.reason, reporter_id=(user or {}).get("_id")
    )
    return {"report": entry, "message": "Thanks — the mods will take a look."}


@router.get("/activity")
async def activity_stream(limit: int = Query(default=40, ge=1, le=200)) -> dict[str, Any]:
    """Recent world events, for the live ticker in the sidebar."""
    return {"events": db.collection("activity").find(sort=[("at", -1)], limit=limit)}
