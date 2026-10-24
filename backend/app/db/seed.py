"""First-run world building: default boards, a starting cast, admin, providers."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.config import settings
from app.db import db
from app.services import (
    config_service,
    generation_service,
    persona_service,
    subreddit_service,
    user_service,
)

DEFAULT_BOARDS: list[dict[str, Any]] = [
    {
        "name": "AskReadIt",
        "title": "Ask ReadIt",
        "description": "Open-ended questions, answered by strangers with too much time.",
        "topics": ["hypotheticals", "life advice", "weird questions", "polls"],
        "icon": "💬",
    },
    {
        "name": "funny",
        "title": "Funny",
        "description": "Things that made someone exhale sharply through their nose.",
        "topics": ["memes", "jokes", "screenshots", "puns"],
        "icon": "🤣",
        "overrides": {"humor": 0.9, "shitpost_rate": 0.7, "expertise": 0.15},
    },
    {
        "name": "technology",
        "title": "Technology",
        "description": "Tech news and the arguments that follow it.",
        "topics": ["AI", "privacy", "startups", "hardware", "enshittification"],
        "icon": "🖥️",
        "overrides": {"expertise": 0.8, "argument_rate": 0.6},
    },
    {
        "name": "unpopularopinion",
        "title": "Unpopular Opinion",
        "description": "Opinions you hold that get you glared at.",
        "topics": ["hot takes", "food crimes", "social norms"],
        "icon": "🌶️",
        "overrides": {"argument_rate": 0.85, "toxicity": 0.6},
    },
    {
        "name": "mildlyinfuriating",
        "title": "Mildly Infuriating",
        "description": "Not a crime. Should be.",
        "topics": ["bad design", "small injustices", "packaging"],
        "icon": "😤",
    },
    {
        "name": "explainlikeimfive",
        "title": "Explain Like I'm Five",
        "description": "Complex things, simply. Mostly.",
        "topics": ["physics", "economics", "biology", "how things work"],
        "icon": "🧠",
        "overrides": {"expertise": 0.85, "toxicity": 0.15, "wholesomeness": 0.6},
    },
    {
        "name": "gaming",
        "title": "Gaming",
        "description": "Games, and complaining about games.",
        "topics": ["releases", "backlogs", "nostalgia", "microtransactions"],
        "icon": "🎮",
    },
    {
        "name": "todayilearned",
        "title": "Today I Learned",
        "description": "TIL something that was in a textbook the whole time.",
        "topics": ["history", "science", "trivia", "wikipedia holes"],
        "icon": "📚",
    },
    {
        "name": "aww",
        "title": "Aww",
        "description": "Animals being unbearable about it.",
        "topics": ["cats", "dogs", "rescues", "small creatures"],
        "icon": "🐾",
        "overrides": {"wholesomeness": 0.9, "toxicity": 0.08, "argument_rate": 0.1},
    },
    {
        "name": "AmITheJerk",
        "title": "Am I The Jerk?",
        "description": "Post your conflict. Receive a verdict. Regret asking.",
        "topics": ["family drama", "weddings", "roommates", "verdicts"],
        "icon": "⚖️",
        "overrides": {"argument_rate": 0.75, "toxicity": 0.5},
    },
    {
        "name": "science",
        "title": "Science",
        "description": "Papers, findings, and people who did not read either.",
        "topics": ["research", "space", "climate", "medicine"],
        "icon": "🔬",
        "overrides": {"expertise": 0.9},
    },
    {
        "name": "food",
        "title": "Food",
        "description": "What you made, what you ate, what you regret.",
        "topics": ["recipes", "cooking fails", "restaurants", "snacks"],
        "icon": "🍜",
    },
]


def seed_boards() -> list[dict[str, Any]]:
    created = []
    for spec in DEFAULT_BOARDS:
        if subreddit_service.exists(spec["name"]):
            continue
        board = subreddit_service.create(
            spec["name"],
            title=spec.get("title", ""),
            description=spec.get("description", ""),
            topics=spec.get("topics", []),
            is_official=True,
            overrides=spec.get("overrides"),
        )
        updates: dict[str, Any] = {}
        if spec.get("icon"):
            updates["icon"] = spec["icon"]
        if updates:
            subreddit_service.update(board["name"], updates)
        created.append(board)
    return created


def seed_personas(per_board: int = 6, global_pool: int = 30) -> int:
    """A deterministic starting cast so the site works with zero API keys."""
    before = persona_service.count_personas()
    if before < global_pool:
        persona_service.create_fallback_personas(global_pool - before)
    for board in db.collection("subreddits").all():
        existing = db.collection("personas").count({"home_subreddit": board["name"]})
        if existing < per_board:
            persona_service.create_fallback_personas(per_board - existing, board["name"])
    return persona_service.count_personas() - before


def seed_admin() -> dict[str, Any] | None:
    """Create the bootstrap admin if that email has no account yet."""
    existing = user_service.get_by_email(settings.admin_email)
    if existing:
        if not existing.get("is_admin"):
            db.collection("users").update(existing["_id"], {"$set": {"is_admin": True}})
        return existing
    try:
        return user_service.register(settings.admin_email, settings.admin_password, "readit_admin")
    except user_service.UserError:
        return None


def seed_connections() -> list[dict[str, Any]]:
    """Turn any API keys present in the environment into ready connections."""
    config = config_service.get_llm_config()
    existing_types = {c["provider_type"] for c in config.get("connections", [])}
    created = []
    env_keys = [
        ("openrouter", settings.openrouter_api_key, "OpenRouter"),
        ("openai", settings.openai_api_key, "OpenAI"),
        ("anthropic", settings.anthropic_api_key, "Claude"),
        ("google", settings.google_api_key, "Google AI"),
    ]
    for provider_type, api_key, name in env_keys:
        if not api_key or provider_type in existing_types:
            continue
        created.append(
            config_service.add_connection(
                {"name": name, "provider_type": provider_type, "api_key": api_key}
            )
        )
    return created


def bootstrap() -> dict[str, Any]:
    """Idempotent setup run on every startup."""
    config_service.get_world()
    config_service.get_llm_config()
    boards = seed_boards()
    personas = seed_personas()
    persona_service.ensure_automoderator()
    admin = seed_admin()
    connections = seed_connections()
    return {
        "boards_created": len(boards),
        "personas_created": personas,
        "admin": bool(admin),
        "connections_created": len(connections),
    }


async def seed_content(board_limit: int = 6, posts_per_board: int = 5) -> dict[str, Any]:
    """Fill empty default boards so the front page has something on first load."""
    empty = [
        board
        for board in db.collection("subreddits").find({"is_official": True})
        if db.collection("posts").count({"subreddit": board["name"]}) == 0
    ]
    random.shuffle(empty)
    filled = []
    for board in empty[:board_limit]:
        posts = await generation_service.generate_posts(
            board["name"], count=posts_per_board, backdate_hours=30
        )
        if posts:
            # Give one thread a real conversation so the first click is not empty.
            await generation_service.generate_comments(
                random.choice(posts)["_id"], count=random.randint(5, 12)
            )
        filled.append({"board": board["name"], "posts": len(posts)})
    return {"boards": filled}


async def bootstrap_async() -> dict[str, Any]:
    result = bootstrap()
    result["content"] = await seed_content()
    return result


def bootstrap_blocking() -> dict[str, Any]:
    """Synchronous helper for scripts and tests."""
    return asyncio.run(bootstrap_async())
