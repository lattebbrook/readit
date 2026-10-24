"""AI inhabitants of the forum.

Personas are the fictional regulars who post and comment. They persist so that
the same handle keeps the same voice, karma and grudges across threads.
"""

from __future__ import annotations

import random
import re
from typing import Any

from app.db import db, now
from app.llm import router
from app.llm.base import LLMMessage, extract_rows
from app.llm.prompts import personas_prompt
from app.services import config_service

AVATAR_COLORS = [
    "#ff4500", "#0079d3", "#46d160", "#ffb000", "#ff66ac", "#7193ff",
    "#ea0027", "#00a6a5", "#9f7aea", "#ff8717", "#94e044", "#ffd635",
]
AVATAR_EMOJI = list("🦊🐙🦉🐸🦝🐝🦑🐢🦋🐧🦈🐿️🦔🐺🦭🪿🐌🦩🐊🦦")

AGE_LABELS = [
    "account made last week", "3 year old account", "8 year old account",
    "made this account to comment", "lurker since forever", "2 year old account",
    "11 year old account, mostly lurks", "6 month old account",
]

_FALLBACK_PREFIX = [
    "Grumpy", "Tired", "Chaotic", "Mildly", "Loud", "Quiet", "Feral", "Anxious",
    "Professional", "Retired", "Amateur", "Reluctant", "Certified", "Local",
]
_FALLBACK_NOUN = [
    "Otter", "Toaster", "Barnacle", "Comet", "Pigeon", "Kettle", "Moss", "Wrench",
    "Gremlin", "Sandwich", "Cactus", "Lighthouse", "Beetle", "Trombone", "Radish",
]
_FALLBACK_TRAITS = [
    "sarcastic", "earnest", "pedantic", "warm", "blunt", "anxious", "smug",
    "self-deprecating", "conspiratorial", "encouraging", "exhausted", "combative",
    "chronically online", "unexpectedly wise", "argumentative", "deadpan",
]
_FALLBACK_TONES = ["dry", "chaotic", "academic", "casual", "aggressive", "gentle", "clipped", "rambling"]

USERNAME_CLEAN = re.compile(r"[^A-Za-z0-9_\-]")


def _personas():
    return db.collection("personas")


def normalise_username(raw: str) -> str:
    name = USERNAME_CLEAN.sub("", (raw or "").strip().removeprefix("u/"))
    return name[:22] or fallback_username()


def fallback_username() -> str:
    return (
        f"{random.choice(_FALLBACK_PREFIX)}{random.choice(_FALLBACK_NOUN)}"
        f"{random.choice(['', '', str(random.randint(2, 99)), '_' + str(random.randint(70, 99))])}"
    )


def _make_persona_doc(payload: dict[str, Any], home: str | None) -> dict[str, Any]:
    username = normalise_username(payload.get("username", ""))
    traits = payload.get("traits") or random.sample(_FALLBACK_TRAITS, 2)
    return {
        "username": username,
        "username_lower": username.lower(),
        "bio": (payload.get("bio") or "")[:160],
        "traits": [str(trait)[:30] for trait in traits][:4],
        "tone": payload.get("tone") or random.choice(_FALLBACK_TONES),
        "posting_style": (payload.get("posting_style") or "")[:200],
        "home_subreddit": home,
        "kind": "ai",
        "karma": {
            "post": random.randint(-40, 40_000),
            "comment": random.randint(10, 180_000),
        },
        "avatar_color": random.choice(AVATAR_COLORS),
        "avatar_emoji": random.choice(AVATAR_EMOJI),
        "banner_color": "#1a1a1b",
        "awards_received": {},
        "account_age_label": random.choice(AGE_LABELS),
        "activity": round(random.uniform(0.2, 1.0), 2),
        "last_active": now(),
        "created_at": now(),
    }


def get_persona(username: str) -> dict[str, Any] | None:
    return _personas().find_one({"username_lower": (username or "").lower()})


def ensure_persona(username: str, home: str | None = None) -> dict[str, Any]:
    """Look up a handle, inventing a plausible regular if the model made it up."""
    cleaned = normalise_username(username)
    existing = get_persona(cleaned)
    if existing:
        return existing
    return _personas().insert(_make_persona_doc({"username": cleaned}, home))


AUTOMOD_USERNAME = "AutoModerator"


def ensure_automoderator() -> dict[str, Any]:
    """A fixed identity for the moderation bot, rather than a random invention.

    Every removal in ``moderation_service`` can default to this handle, so
    ``u/AutoModerator`` needs to resolve to a real, recognisable profile the
    first time anyone clicks it — not whatever ``ensure_persona`` would have
    made up on the spot.
    """
    existing = get_persona(AUTOMOD_USERNAME)
    if existing:
        return existing
    return _personas().insert(
        {
            "username": AUTOMOD_USERNAME,
            "username_lower": AUTOMOD_USERNAME.lower(),
            "bio": "Beep boop. I watch the boards for trouble and occasionally overreact. "
            "Message the moderators if I got one wrong.",
            "traits": ["automated", "impartial", "literal-minded"],
            "tone": "robotic",
            "posting_style": "posts stickied notices, never argues back",
            "home_subreddit": None,
            "kind": "ai",
            "karma": {"post": 45210, "comment": 128430},
            "avatar_color": "#5b6b73",
            "avatar_emoji": "🤖",
            "banner_color": "#1a1a1b",
            "awards_received": {},
            "account_age_label": "very old account, mostly automated",
            "activity": 1.0,
            "last_active": now(),
            "created_at": now() - 86_400 * 365 * 4,
        }
    )


def create_fallback_personas(count: int, home: str | None = None) -> list[dict[str, Any]]:
    """Deterministic roster used when no model is reachable."""
    created: list[dict[str, Any]] = []
    attempts = 0
    while len(created) < count and attempts < count * 12:
        attempts += 1
        username = fallback_username()
        if get_persona(username):
            continue
        created.append(_personas().insert(_make_persona_doc({"username": username}, home)))
    return created


async def generate_personas(
    count: int, subreddit: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Ask the model for a fresh cast; fall back to the local generator."""
    world = config_service.get_world()
    existing = [doc["username"] for doc in _personas().find(limit=80)]
    system, user = personas_prompt(world, subreddit, count=count, existing=existing)
    parsed, _ = await router.generate_json(
        "persona",
        [LLMMessage("system", system), LLMMessage("user", user)],
    )
    home = (subreddit or {}).get("name")
    rows = extract_rows(parsed, "personas")
    if not rows:
        return create_fallback_personas(count, home)

    created: list[dict[str, Any]] = []
    for row in rows[:count]:
        if not isinstance(row, dict) or not row.get("username"):
            continue
        username = normalise_username(row["username"])
        if get_persona(username):
            continue
        created.append(_personas().insert(_make_persona_doc({**row, "username": username}, home)))
    if not created:
        created = create_fallback_personas(count, home)
    return created


async def ensure_roster(subreddit: dict[str, Any], minimum: int = 12) -> list[dict[str, Any]]:
    """Guarantee a board has enough distinct regulars to feel populated.

    A generation pass can return fewer than asked for — the model repeats names,
    or collides with handles already in use — so top up until the floor is met
    rather than trusting a single call.
    """
    name = subreddit.get("name")
    locals_ = _personas().find({"home_subreddit": name})
    attempts = 0
    while len(locals_) < minimum and attempts < 3:
        attempts += 1
        await generate_personas(minimum - len(locals_), subreddit)
        locals_ = _personas().find({"home_subreddit": name})

    if len(locals_) < minimum:
        create_fallback_personas(minimum - len(locals_), name)
        locals_ = _personas().find({"home_subreddit": name})
    return locals_


def sample_for_board(
    subreddit: dict[str, Any] | None, count: int = 10, *, exclude: list[str] | None = None
) -> list[dict[str, Any]]:
    """A cast for one generation pass: mostly board regulars, some passers-by."""
    excluded = {name.lower() for name in (exclude or [])}
    name = (subreddit or {}).get("name")
    locals_ = [p for p in _personas().find({"home_subreddit": name}) if p["username_lower"] not in excluded]
    globals_ = [
        p
        for p in _personas().find(limit=200)
        if p.get("home_subreddit") != name and p["username_lower"] not in excluded
    ]

    random.shuffle(locals_)
    random.shuffle(globals_)
    local_take = max(1, int(count * 0.7))
    chosen = locals_[:local_take] + globals_[: count - min(local_take, len(locals_))]
    if len(chosen) < count:
        chosen += create_fallback_personas(count - len(chosen), name)
    random.shuffle(chosen)
    return chosen[:count]


def touch(username: str) -> None:
    persona = get_persona(username)
    if persona:
        _personas().update(persona["_id"], {"$set": {"last_active": now()}})


def add_karma(username: str, kind: str, amount: int) -> None:
    persona = get_persona(username)
    if not persona or amount == 0:
        return
    field = "karma.post" if kind == "post" else "karma.comment"
    _personas().update(persona["_id"], {"$inc": {field: amount}})


def receive_award(username: str, award_id: str) -> None:
    """Personas collect trophies too, so their profiles look like anyone else's."""
    persona = get_persona(username)
    if not persona:
        return
    received = dict(persona.get("awards_received") or {})
    received[award_id] = received.get(award_id, 0) + 1
    _personas().update(persona["_id"], {"$set": {"awards_received": received}})


def public_persona(persona: dict[str, Any] | None) -> dict[str, Any] | None:
    """AI authors expose no marker of being AI — that is the whole point.

    The key set must match :func:`user_service.public_user` exactly. A missing
    field is as much of a tell as an explicit "bot" flag would be.
    """
    if not persona:
        return None
    return {
        "id": persona["_id"],
        "username": persona.get("username"),
        "display_name": persona.get("username"),
        "bio": persona.get("bio", ""),
        "avatar_color": persona.get("avatar_color"),
        "avatar_emoji": persona.get("avatar_emoji"),
        "banner_color": persona.get("banner_color", "#1a1a1b"),
        "karma": persona.get("karma", {"post": 0, "comment": 0}),
        "created_at": persona.get("created_at"),
        "awards_received": persona.get("awards_received", {}),
        "kind": "ai",
        "is_guest": False,
        "is_admin": False,
    }


def count_personas() -> int:
    return _personas().count()
