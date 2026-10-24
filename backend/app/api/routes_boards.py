"""Boards: browsing, creation, per-board settings and prompt overrides."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.deps import current_user, optional_user
from app.models.schemas import (
    BoardCreate,
    BoardUpdate,
    GenerateRequest,
    PersonalPromptUpdate,
)
from app.services import (
    config_service,
    generation_service,
    moderation_service,
    persona_service,
    post_service,
    simulation,
    subreddit_service,
    user_service,
)

router = APIRouter(prefix="/api/boards", tags=["boards"])


def _visible_to(user: dict[str, Any] | None) -> list[str]:
    return (user or {}).get("banned_subreddits") or []


@router.get("")
async def list_boards(
    q: str | None = None,
    sort: str = "subscribers",
    limit: int = Query(default=100, ge=1, le=300),
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    preferences = (user or {}).get("preferences") or {}
    boards = subreddit_service.list_boards(
        query=q,
        sort=sort,
        limit=limit,
        include_nsfw=bool(preferences.get("show_nsfw", False)),
        exclude=_visible_to(user),
    )
    return {"boards": [subreddit_service.public_board(board, user) for board in boards]}


@router.get("/recommended")
async def recommended(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    """Boards matched to the interests the user typed into settings."""
    interests = [item.lower() for item in ((user or {}).get("interests") or [])]
    subscriptions = {name.lower() for name in ((user or {}).get("subscriptions") or [])}
    boards = subreddit_service.list_boards(
        limit=300,
        include_nsfw=bool(((user or {}).get("preferences") or {}).get("show_nsfw", False)),
        exclude=_visible_to(user),
    )

    def score(board: dict[str, Any]) -> float:
        if board["name_lower"] in subscriptions:
            return -1.0
        haystack = " ".join(
            [board["name_lower"], (board.get("description") or "").lower(), *[
                str(topic).lower() for topic in board.get("topics", [])
            ]]
        )
        matches = sum(1 for interest in interests if interest and interest in haystack)
        return matches * 10 + board.get("subscribers", 0) / 100_000

    ranked = sorted(boards, key=score, reverse=True)
    return {
        "boards": [
            subreddit_service.public_board(board, user)
            for board in ranked[:12]
            if board["name_lower"] not in subscriptions
        ]
    }


@router.post("")
async def create_board(
    payload: BoardCreate,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Anyone can start a board, with their own prompt steering everything in it."""
    try:
        board = subreddit_service.create(
            payload.name,
            kind=payload.kind,
            creator_id=user["_id"],
            creator_username=user["username"],
            title=payload.title,
            description=payload.description,
            custom_prompt=payload.custom_prompt,
            override_global=payload.override_global,
            nsfw=payload.nsfw,
            rules=payload.rules,
            topics=payload.topics,
            overrides=payload.overrides,
        )
    except subreddit_service.SubredditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_service.subscribe(user["_id"], board["name"])

    async def prepare() -> None:
        if payload.generate_metadata and not payload.description:
            metadata = await subreddit_service.generate_metadata(
                board["name"], payload.custom_prompt or payload.title
            )
            if metadata:
                subreddit_service.update(board["name"], metadata)
        await persona_service.ensure_roster(subreddit_service.get(board["name"]) or board)
        # Photo boards cannot be seeded — the regulars have no pictures to post.
        # They fill up when someone captures something.
        if payload.autofill and payload.kind != "photo":
            await generation_service.seed_board(board["name"], posts=6, threads_to_fill=2)

    background.add_task(prepare)

    fresh = subreddit_service.get(board["name"]) or board
    return {
        "board": subreddit_service.public_board(fresh, user, include_prompt=True),
        "preparing": payload.autofill or payload.generate_metadata,
    }


@router.get("/{name}")
async def get_board(
    name: str, user: dict[str, Any] | None = Depends(optional_user)
) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} does not exist (yet).")
    if board["name"] in ((user or {}).get("banned_subreddits") or []):
        raise HTTPException(status_code=403, detail=f"You've blocked r/{board['name']}.")
    return {
        "board": subreddit_service.public_board(
            board, user, include_prompt=subreddit_service.can_edit(board, user)
        )
    }


@router.get("/{name}/posts")
async def board_posts(
    name: str,
    sort: str = "hot",
    limit: int = Query(default=25, ge=1, le=100),
    skip: int = 0,
    background: BackgroundTasks = None,  # type: ignore[assignment]
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} does not exist (yet).")

    posts = post_service.list_for_board(board["name"], sort=sort, limit=limit, skip=skip)

    # An empty or thin board fills itself the moment somebody looks at it —
    # but not while the simulation is switched off.
    if (
        len(posts) < 3
        and background is not None
        and config_service.automatic_generation_allowed()
    ):
        background.add_task(generation_service.generate_posts, board["name"], count=6)

    return {
        "board": subreddit_service.public_board(board, user),
        "posts": post_service.public_posts(posts, user),
        "sort": sort,
    }


@router.patch("/{name}")
async def update_board(
    name: str, payload: BoardUpdate, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    if not subreddit_service.can_edit(board, user):
        raise HTTPException(status_code=403, detail="Only the board's creator can change this.")
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = subreddit_service.update(board["name"], changes)
    return {"board": subreddit_service.public_board(updated or board, user, include_prompt=True)}


@router.delete("/{name}")
async def delete_board(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    if not subreddit_service.can_edit(board, user):
        raise HTTPException(status_code=403, detail="Only the board's creator can delete it.")
    return {"deleted": subreddit_service.delete(board["name"])}


@router.put("/{name}/personal-prompt")
async def set_personal_prompt(
    name: str, payload: PersonalPromptUpdate, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """Your own steer for someone else's board — affects only what you see."""
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    subreddit_service.set_personal_prompt(user["_id"], board["name"], payload.prompt)
    return {"prompt": subreddit_service.get_personal_prompt(user["_id"], board["name"])}


@router.post("/{name}/generate")
async def generate_posts(
    name: str,
    payload: GenerateRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """Force a fresh batch of posts — the board's "stir the pot" button."""
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    try:
        posts = await asyncio.wait_for(
            generation_service.generate_posts(
                board["name"], count=payload.count or 4, user=user, backdate_hours=2
            ),
            timeout=180,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Generation timed out — try again.") from None
    return {"posts": post_service.public_posts(posts, user)}


@router.get("/{name}/mod-log")
async def mod_log(name: str) -> dict[str, Any]:
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    return {"entries": moderation_service.log_for_board(board["name"])}


@router.get("/{name}/members")
async def board_members(name: str) -> dict[str, Any]:
    """The regulars, shown exactly like any other user list."""
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    personas = persona_service.sample_for_board(board, count=24)
    return {
        "members": [persona_service.public_persona(persona) for persona in personas],
        "online": subreddit_service.online_count(board),
    }


@router.post("/{name}/simulate")
async def simulate_board(name: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Run one world tick immediately, scoped by the caller pressing the button."""
    board = subreddit_service.get(name)
    if not board:
        raise HTTPException(status_code=404, detail=f"r/{name} not found.")
    result = await simulation.engine.tick()
    return {"tick": result}
