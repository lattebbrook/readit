"""Awards: the coin economy, the catalogue, and the simulated gifting crowd."""

from __future__ import annotations

import random
from typing import Any

from app.db import db, now
from app.services import persona_service, user_service

AWARDS: list[dict[str, Any]] = [
    {"id": "silver", "name": "Silver", "icon": "🥈", "cost": 100, "color": "#c0c8d0",
     "description": "Shows the community's appreciation.", "rarity": "common"},
    {"id": "gold", "name": "Gold", "icon": "🥇", "cost": 500, "color": "#ffd635",
     "description": "Gives the author a week of premium, plus coins.", "rarity": "rare"},
    {"id": "platinum", "name": "Platinum", "icon": "💠", "cost": 1800, "color": "#7bd9f5",
     "description": "A month of premium and a big pile of coins.", "rarity": "legendary"},
    {"id": "wholesome", "name": "Wholesome", "icon": "🫂", "cost": 125, "color": "#5cd15c",
     "description": "When you come across a feel-good thing.", "rarity": "common"},
    {"id": "helpful", "name": "Helpful", "icon": "💡", "cost": 150, "color": "#5cb8ff",
     "description": "Thank you stranger. Shows the award.", "rarity": "common"},
    {"id": "lol", "name": "Take My Money", "icon": "💸", "cost": 200, "color": "#46d160",
     "description": "I'm not sure if I should be laughing.", "rarity": "uncommon"},
    {"id": "facepalm", "name": "Facepalm", "icon": "🤦", "cost": 80, "color": "#ff8717",
     "description": "*Very* rarely a compliment.", "rarity": "common"},
    {"id": "bruh", "name": "Bruh", "icon": "😐", "cost": 60, "color": "#94a3b8",
     "description": "No words needed.", "rarity": "common"},
    {"id": "rocket", "name": "Rocket Like", "icon": "🚀", "cost": 300, "color": "#ff4500",
     "description": "When an upvote just isn't enough.", "rarity": "uncommon"},
    {"id": "spitfire", "name": "Spit-take", "icon": "🤣", "cost": 175, "color": "#ffb000",
     "description": "Coffee. Keyboard. Gone.", "rarity": "uncommon"},
    {"id": "pot_stirrer", "name": "Pot Stirrer", "icon": "🥄", "cost": 90, "color": "#e879f9",
     "description": "For starting something and watching it burn.", "rarity": "uncommon"},
    {"id": "ternion", "name": "Ternion All-Powerful", "icon": "🔱", "cost": 5000, "color": "#a855f7",
     "description": "Legendary. Nobody has ever deserved this.", "rarity": "mythic"},
]

AWARDS_BY_ID = {award["id"]: award for award in AWARDS}

# Which awards the simulated crowd reaches for, given how a thing landed.
_POSITIVE = ["silver", "gold", "helpful", "wholesome", "rocket", "platinum"]
_FUNNY = ["lol", "spitfire", "silver", "rocket"]
_NEGATIVE = ["facepalm", "bruh", "pot_stirrer"]


class AwardError(ValueError):
    """Award validation failure (unknown award, not enough coins, bad target)."""


def _grants():
    return db.collection("award_grants")


def _collection_for(kind: str):
    name = {"post": "posts", "comment": "comments"}.get(kind)
    if not name:
        raise AwardError(f"Cannot award a '{kind}'.")
    return db.collection(name)


def catalogue() -> list[dict[str, Any]]:
    return [dict(award) for award in AWARDS]


def _apply_to_target(target_kind: str, target_id: str, award_id: str) -> dict[str, Any] | None:
    collection = _collection_for(target_kind)
    target = collection.get(target_id)
    if not target:
        return None
    awards = dict(target.get("awards") or {})
    awards[award_id] = awards.get(award_id, 0) + 1
    return collection.update(
        target_id, {"$set": {"awards": awards, "award_total": sum(awards.values())}}
    )


def grant(
    target_kind: str,
    target_id: str,
    award_id: str,
    *,
    giver_id: str | None = None,
    giver_username: str | None = None,
    simulated: bool = False,
    anonymous: bool = False,
) -> dict[str, Any]:
    """Give an award. Human gifts cost coins; simulated ones are free."""
    award = AWARDS_BY_ID.get(award_id)
    if not award:
        raise AwardError(f"Unknown award: {award_id}")

    target = _collection_for(target_kind).get(target_id)
    if not target:
        raise AwardError("That content no longer exists.")

    if giver_id and not simulated:
        giver = user_service.get_user(giver_id)
        if not giver:
            raise AwardError("Account not found.")
        if giver.get("coins", 0) < award["cost"]:
            raise AwardError(
                f"Not enough coins — {award['name']} costs {award['cost']}, you have {giver.get('coins', 0)}."
            )
        user_service.adjust_coins(giver_id, -award["cost"])
        user_service.add_karma(giver_id, "awarder", 1)
        giver_username = giver_username or giver.get("username")

    updated = _apply_to_target(target_kind, target_id, award_id)

    # Recipients bank a share of the coins, like the real thing.
    recipient_id = target.get("author_id")
    if target.get("author_kind") == "ai":
        persona_service.receive_award(target.get("author", ""), award_id)
    elif target.get("author_kind") == "human" and recipient_id:
        user_service.adjust_coins(recipient_id, int(award["cost"] * 0.2))
        recipient = user_service.get_user(recipient_id)
        if recipient:
            received = dict(recipient.get("awards_received") or {})
            received[award_id] = received.get(award_id, 0) + 1
            db.collection("users").update(
                recipient_id, {"$set": {"awards_received": received}}
            )

    grant_doc = _grants().insert(
        {
            "target_kind": target_kind,
            "target_id": target_id,
            "award_id": award_id,
            "giver_id": giver_id,
            "giver": None if anonymous else giver_username,
            "anonymous": anonymous,
            "simulated": simulated,
            "subreddit": target.get("subreddit"),
            "at": now(),
        }
    )
    return {"grant": grant_doc, "award": award, "target": updated}


def awards_for(target_kind: str, target_id: str) -> list[dict[str, Any]]:
    target = _collection_for(target_kind).get(target_id) or {}
    counts = target.get("awards") or {}
    return [
        {**AWARDS_BY_ID[award_id], "count": count}
        for award_id, count in counts.items()
        if award_id in AWARDS_BY_ID
    ]


def grants_for(target_kind: str, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return _grants().find(
        {"target_kind": target_kind, "target_id": target_id}, sort=[("at", -1)], limit=limit
    )


# --------------------------------------------------------------------------- #
# Simulated gifting
# --------------------------------------------------------------------------- #

def maybe_award(
    target_kind: str,
    target: dict[str, Any],
    *,
    world: dict[str, Any],
    tone: str = "",
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Roll for a crowd-given award, weighted by how the item landed."""
    generator = rng or random
    score = int(target.get("score", 0))
    quality = float(target.get("quality", 0.5))
    rate = float(world.get("award_rate", 0.12))

    # Highly upvoted things attract awards; heavily downvoted things attract jeers.
    probability = rate * (0.3 + min(3.0, score / 400.0) + quality)
    if score < -20:
        probability = rate * 0.8

    if generator.random() > min(0.85, probability):
        return None

    if score < -20:
        pool = _NEGATIVE
    elif tone in {"funny", "sarcastic"}:
        pool = _FUNNY
    else:
        pool = _POSITIVE

    # Expensive awards stay rare.
    weights = [1.0 / (AWARDS_BY_ID[award_id]["cost"] ** 0.6) for award_id in pool]
    award_id = generator.choices(pool, weights=weights, k=1)[0]

    giver = None
    personas = db.collection("personas").find(limit=60)
    if personas:
        giver = generator.choice(personas).get("username")

    return grant(
        target_kind,
        target["_id"],
        award_id,
        giver_username=giver,
        simulated=True,
        anonymous=generator.random() < 0.35,
    )


def top_awarded(limit: int = 10) -> list[dict[str, Any]]:
    posts = db.collection("posts").find(sort=[("award_total", -1)], limit=limit)
    return [post for post in posts if post.get("award_total")]
