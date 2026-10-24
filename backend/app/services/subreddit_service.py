"""Boards (r/…): creation, settings, per-board prompt overrides."""

from __future__ import annotations

import random
import re
from typing import Any

from app.db import db, now
from app.llm import router
from app.llm.base import LLMMessage
from app.llm.prompts import board_meta_prompt
from app.services import config_service

NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,21}$")

BOARD_COLORS = [
    "#ff4500", "#0079d3", "#46d160", "#ffb000", "#ff66ac",
    "#7193ff", "#ea0027", "#00a6a5", "#9f7aea", "#24a0ed",
]
BOARD_ICONS = list("🔥💬🎮🍕🧠🛠️🎬📚🐈🌍🎧🚀🧪🎨🏋️🪴🧵🍜🎲🛰️")

# Knobs a board may override; None means "inherit from the world".
BOARD_OVERRIDE_FIELDS = [
    "humor", "toxicity", "argument_rate", "wholesomeness", "shitpost_rate",
    "expertise", "comment_density", "thread_depth", "moderation_strictness",
    "removal_rate", "award_rate", "posts_per_board_target",
]

EDITABLE_FIELDS = {
    "title", "description", "sidebar", "rules", "topics", "custom_prompt",
    "override_global", "nsfw", "color", "icon", "allow_user_posts",
    "moderation_enabled", "activity_level", "banner_color", "kind",
}

# "text" boards behave as they always have. "photo" boards are built around an
# image per post: the grid replaces the list, posting requires media, and the
# world never invents threads for them because it has no pictures to post.
BOARD_KINDS = {"text", "photo"}


class SubredditError(ValueError):
    """User-facing board validation failure."""


def _subs():
    return db.collection("subreddits")


def get(name: str) -> dict[str, Any] | None:
    return _subs().find_one({"name_lower": (name or "").lower()})


def get_by_id(sub_id: str) -> dict[str, Any] | None:
    return _subs().get(sub_id)


def exists(name: str) -> bool:
    return get(name) is not None


def list_boards(
    *,
    query: str | None = None,
    limit: int = 100,
    sort: str = "subscribers",
    include_nsfw: bool = True,
    exclude: list[str] | None = None,
) -> list[dict[str, Any]]:
    boards = _subs().all()
    if not include_nsfw:
        boards = [b for b in boards if not b.get("nsfw")]
    if exclude:
        blocked = {name.lower() for name in exclude}
        boards = [b for b in boards if b["name_lower"] not in blocked]
    if query:
        needle = query.lower()
        boards = [
            b
            for b in boards
            if needle in b["name_lower"] or needle in (b.get("description") or "").lower()
        ]
    key = {
        "subscribers": lambda b: b.get("subscribers", 0),
        "new": lambda b: b.get("created_at", 0),
        "active": lambda b: b.get("last_activity_at", b.get("created_at", 0)),
    }.get(sort, lambda b: b.get("subscribers", 0))
    boards.sort(key=key, reverse=True)
    return boards[:limit]


def create(
    name: str,
    *,
    creator_id: str | None = None,
    creator_username: str | None = None,
    title: str = "",
    description: str = "",
    custom_prompt: str = "",
    override_global: bool = False,
    nsfw: bool = False,
    rules: list[str] | None = None,
    topics: list[str] | None = None,
    is_official: bool = False,
    overrides: dict[str, Any] | None = None,
    kind: str = "text",
) -> dict[str, Any]:
    name = (name or "").strip().removeprefix("r/").strip()
    if not NAME_RE.match(name):
        raise SubredditError("Board names are 3-21 characters: letters, numbers and underscores.")
    if exists(name):
        raise SubredditError(f"r/{name} already exists.")
    if kind not in BOARD_KINDS:
        raise SubredditError(f"Unknown board kind: {kind}")

    doc = {
        "name": name,
        "name_lower": name.lower(),
        "kind": kind,
        "title": title or name,
        "description": description,
        "sidebar": "",
        "rules": rules or ["Stay on topic", "Don't be a jerk", "No spam"],
        "topics": topics or [],
        "custom_prompt": custom_prompt,
        "override_global": bool(override_global),
        "nsfw": bool(nsfw),
        "created_by": creator_id,
        "creator_username": creator_username,
        "is_official": is_official,
        "moderators": ["AutoModerator"] + ([creator_username] if creator_username else []),
        "subscribers": random.randint(1_200, 480_000) if is_official else random.randint(12, 4_000),
        "members_online": 0,
        "color": random.choice(BOARD_COLORS),
        "banner_color": "#0b1416",
        "icon": random.choice(BOARD_ICONS),
        "allow_user_posts": True,
        "moderation_enabled": True,
        "activity_level": 1.0,
        "overrides": {field: None for field in BOARD_OVERRIDE_FIELDS},
        "last_generated_at": 0.0,
        "last_activity_at": now(),
        "post_count": 0,
        "created_at": now(),
    }
    if overrides:
        doc["overrides"].update(
            {k: v for k, v in overrides.items() if k in BOARD_OVERRIDE_FIELDS}
        )
    created = _subs().insert(doc)
    created["members_online"] = online_count(created)
    return created


def update(name: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    board = get(name)
    if not board:
        return None
    allowed = {key: value for key, value in changes.items() if key in EDITABLE_FIELDS}
    if "rules" in allowed:
        allowed["rules"] = [str(rule)[:200] for rule in (allowed["rules"] or [])][:12]
    if "topics" in allowed:
        allowed["topics"] = [str(topic)[:60] for topic in (allowed["topics"] or [])][:20]
    if "custom_prompt" in allowed:
        allowed["custom_prompt"] = str(allowed["custom_prompt"])[:4000]
    if "kind" in allowed and allowed["kind"] not in BOARD_KINDS:
        raise SubredditError(f"Unknown board kind: {allowed['kind']}")

    if "overrides" in changes and isinstance(changes["overrides"], dict):
        merged = {**(board.get("overrides") or {})}
        for key, value in changes["overrides"].items():
            if key in BOARD_OVERRIDE_FIELDS:
                merged[key] = value
        allowed["overrides"] = merged

    if not allowed:
        return board
    return _subs().update(board["_id"], {"$set": allowed})


def delete(name: str) -> bool:
    board = get(name)
    if not board:
        return False
    posts = db.collection("posts").find({"subreddit": board["name"]})
    for post in posts:
        db.collection("comments").delete_many({"post_id": post["_id"]})
    db.collection("posts").delete_many({"subreddit": board["name"]})
    return _subs().delete(board["_id"])


def can_edit(board: dict[str, Any], user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return board.get("created_by") == user.get("_id")


def touch_activity(name: str) -> None:
    board = get(name)
    if board:
        _subs().update(board["_id"], {"$set": {"last_activity_at": now()}})


def bump_subscribers(name: str, delta: int) -> None:
    board = get(name)
    if board:
        _subs().update(board["_id"], {"$inc": {"subscribers": delta}})


def online_count(board: dict[str, Any]) -> int:
    """A plausible "N here now" figure derived from size and recent activity."""
    subscribers = max(1, board.get("subscribers", 1))
    recency = max(0.0, 1.0 - min(1.0, (now() - board.get("last_activity_at", 0)) / 3600))
    base = subscribers ** 0.55
    return max(1, int(base * (0.4 + 0.9 * recency)))


# --------------------------------------------------------------------------- #
# Effective settings
# --------------------------------------------------------------------------- #

def effective_world(
    board: dict[str, Any] | None = None, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """World knobs with board overrides then per-user preferences applied.

    This is what actually drives generation: admins set the site default, a board
    owner narrows it, and the reader's own settings get the final say over how
    intense their feed is.
    """
    world = dict(config_service.get_world())

    if board:
        for key, value in (board.get("overrides") or {}).items():
            if value is not None and key in world:
                world[key] = value
        if board.get("moderation_enabled") is False:
            world["moderation_enabled"] = False

    if user:
        preferences = user.get("preferences") or {}
        if preferences.get("comment_density_override"):
            world["comment_density"] = preferences["comment_density_override"]
        if preferences.get("content_intensity") is not None:
            world["toxicity"] = float(preferences["content_intensity"])
        if preferences.get("humor_override") is not None:
            world["humor"] = float(preferences["humor_override"])
        if preferences.get("language_style"):
            world["style_prompt"] = (
                f"{world.get('style_prompt', '')}\nReader preference: {preferences['language_style']}"
            )

    # Serious Mode is an admin-level guarantee, not another soft dial. Apply it
    # after board and reader overrides so a comedy-heavy board, an old troll
    # persona, or a high-humour preference cannot quietly undo it.
    if world.get("serious_mode"):
        world["humor"] = min(float(world.get("humor", 0.5)), 0.15)
        world["shitpost_rate"] = 0.0
        world["toxicity"] = min(float(world.get("toxicity", 0.35)), 0.2)
        world["argument_rate"] = min(float(world.get("argument_rate", 0.3)), 0.4)
        world["expertise"] = max(float(world.get("expertise", 0.45)), 0.8)
        world["moderation_strictness"] = max(
            float(world.get("moderation_strictness", 0.45)), 0.75
        )
    return world


def personal_prompt_for(board_name: str, user: dict[str, Any] | None) -> str:
    """A reader's private steer for one board, layered on top of the board's own."""
    if not user:
        return ""
    override = db.collection("board_overrides").find_one(
        {"user_id": user["_id"], "subreddit": board_name}
    )
    parts = []
    if user.get("personal_prompt"):
        parts.append(user["personal_prompt"])
    if override and override.get("prompt"):
        parts.append(override["prompt"])
    return " ".join(parts)[:2000]


def set_personal_prompt(user_id: str, board_name: str, prompt: str) -> dict[str, Any]:
    return db.collection("board_overrides").upsert(
        {"user_id": user_id, "subreddit": board_name},
        {"prompt": (prompt or "")[:2000], "updated_at": now()},
    )


def get_personal_prompt(user_id: str, board_name: str) -> str:
    doc = db.collection("board_overrides").find_one(
        {"user_id": user_id, "subreddit": board_name}
    )
    return (doc or {}).get("prompt", "")


# --------------------------------------------------------------------------- #
# Board bootstrapping via the model
# --------------------------------------------------------------------------- #

async def generate_metadata(name: str, hint: str = "") -> dict[str, Any]:
    """Have the model flesh out description/sidebar/rules for a new board."""
    world = config_service.get_world()
    system, user = board_meta_prompt(world, name, hint)
    parsed, _ = await router.generate_json(
        "utility", [LLMMessage("system", system), LLMMessage("user", user)]
    )
    if not isinstance(parsed, dict):
        return {}
    return {
        "description": str(parsed.get("description", ""))[:280],
        "sidebar": str(parsed.get("sidebar", ""))[:800],
        "rules": [str(rule)[:200] for rule in (parsed.get("rules") or [])][:8],
        "topics": [str(topic)[:60] for topic in (parsed.get("topics") or [])][:12],
        "nsfw": bool(parsed.get("nsfw")),
    }


def public_board(
    board: dict[str, Any], user: dict[str, Any] | None = None, *, include_prompt: bool = False
) -> dict[str, Any]:
    payload = {
        "id": board["_id"],
        "name": board["name"],
        # Boards created before photo support default to text.
        "kind": board.get("kind", "text"),
        "title": board.get("title") or board["name"],
        "description": board.get("description", ""),
        "sidebar": board.get("sidebar", ""),
        "rules": board.get("rules", []),
        "topics": board.get("topics", []),
        "nsfw": board.get("nsfw", False),
        "color": board.get("color"),
        "banner_color": board.get("banner_color"),
        "icon": board.get("icon"),
        "subscribers": board.get("subscribers", 0),
        "members_online": online_count(board),
        "moderators": board.get("moderators", []),
        "created_at": board.get("created_at"),
        "created_by": board.get("created_by"),
        "creator_username": board.get("creator_username"),
        "is_official": board.get("is_official", False),
        "allow_user_posts": board.get("allow_user_posts", True),
        "moderation_enabled": board.get("moderation_enabled", True),
        "post_count": db.collection("posts").count({"subreddit": board["name"]}),
        "subscribed": bool(user and board["name"] in (user.get("subscriptions") or [])),
        "can_edit": can_edit(board, user),
    }
    if include_prompt:
        payload.update(
            {
                "custom_prompt": board.get("custom_prompt", ""),
                "override_global": board.get("override_global", False),
                "overrides": board.get("overrides", {}),
                "activity_level": board.get("activity_level", 1.0),
            }
        )
    if user:
        payload["personal_prompt"] = get_personal_prompt(user["_id"], board["name"])
    return payload
