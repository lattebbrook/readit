"""Voting: real votes from humans, and the simulated crowd that votes on everything."""

from __future__ import annotations

import math
import random
from typing import Any

from app.db import db, now
from app.services import persona_service, user_service

VOTABLE = {"post": "posts", "comment": "comments"}


class VoteError(ValueError):
    """Invalid vote target or direction."""


def _collection_for(kind: str):
    name = VOTABLE.get(kind)
    if not name:
        raise VoteError(f"Cannot vote on '{kind}'.")
    return db.collection(name)


def _votes():
    return db.collection("votes")


def get_vote(user_id: str, target_kind: str, target_id: str) -> int:
    doc = _votes().find_one(
        {"user_id": user_id, "target_kind": target_kind, "target_id": target_id}
    )
    return int((doc or {}).get("direction", 0))


def user_votes_for(user_id: str | None, target_ids: list[str]) -> dict[str, int]:
    """Bulk lookup so a feed render costs one pass, not one query per card."""
    if not user_id or not target_ids:
        return {}
    wanted = set(target_ids)
    return {
        doc["target_id"]: int(doc.get("direction", 0))
        for doc in _votes().find({"user_id": user_id})
        if doc["target_id"] in wanted and doc.get("direction")
    }


def cast_vote(user_id: str, target_kind: str, target_id: str, direction: int) -> dict[str, Any]:
    """Apply a human vote. Re-sending the same direction toggles it off."""
    if direction not in (-1, 0, 1):
        raise VoteError("Vote direction must be -1, 0 or 1.")
    collection = _collection_for(target_kind)
    target = collection.get(target_id)
    if not target:
        raise VoteError("That content no longer exists.")

    previous = get_vote(user_id, target_kind, target_id)
    if direction == previous:
        direction = 0  # clicking the same arrow again clears the vote

    _votes().upsert(
        {"user_id": user_id, "target_kind": target_kind, "target_id": target_id},
        {"direction": direction, "updated_at": now()},
    )

    up_delta = (1 if direction == 1 else 0) - (1 if previous == 1 else 0)
    down_delta = (1 if direction == -1 else 0) - (1 if previous == -1 else 0)
    if up_delta or down_delta:
        collection.update(target_id, {"$inc": {"ups": up_delta, "downs": down_delta}})

    updated = collection.get(target_id) or target
    score = int(updated.get("ups", 0)) - int(updated.get("downs", 0))
    collection.update(target_id, {"$set": {"score": score}})

    # Karma follows the score change for whoever wrote it.
    karma_delta = up_delta - down_delta
    if karma_delta:
        if updated.get("author_kind") == "human" and updated.get("author_id"):
            user_service.add_karma(updated["author_id"], target_kind, karma_delta)
        elif updated.get("author_kind") == "ai":
            persona_service.add_karma(updated.get("author", ""), target_kind, karma_delta)

    return {
        "target_id": target_id,
        "target_kind": target_kind,
        "direction": direction,
        "score": score,
        "ups": updated.get("ups", 0),
        "downs": updated.get("downs", 0),
    }


# --------------------------------------------------------------------------- #
# Simulated crowd
# --------------------------------------------------------------------------- #

def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def effective_quality(quality: float, *, is_human: bool, world: dict[str, Any]) -> float:
    """Human-written content gets a friendlier reception, as requested.

    The bonus lifts a human's score without making downvotes impossible — a bad
    take still sinks, just not as fast.
    """
    quality = max(0.0, min(1.0, float(quality)))
    if not is_human:
        return quality
    bonus = float(world.get("user_vote_bonus", 0.35))
    return min(1.0, quality + (1.0 - quality) * bonus)


def simulate_votes(
    *,
    quality: float,
    controversy: float = 0.3,
    is_human: bool = False,
    world: dict[str, Any],
    audience: int = 120,
    rng: random.Random | None = None,
) -> tuple[int, int]:
    """Return ``(ups, downs)`` for a piece of content seen by ``audience`` people."""
    generator = rng or random
    adjusted = effective_quality(quality, is_human=is_human, world=world)
    volatility = float(world.get("vote_volatility", 0.5))

    # Perceived quality wobbles: the same comment lands differently by thread mood.
    noise = generator.gauss(0, 0.12 + 0.18 * volatility)
    perceived = max(0.0, min(1.0, adjusted + noise))

    engagement = max(1, int(audience * generator.uniform(0.35, 1.0)))
    up_rate = _sigmoid((perceived - 0.45) * 7.0)
    ups = int(engagement * up_rate)

    hostility = 0.25 + 0.75 * float(controversy) + 0.5 * float(world.get("toxicity", 0.35))
    downs = int(engagement * (1.0 - up_rate) * hostility)

    if is_human:
        downs = int(downs * (1.0 - 0.5 * float(world.get("user_vote_bonus", 0.35))))

    # Occasional runaway: something catches fire, or gets brigaded.
    roll = generator.random()
    if roll > 0.97:
        ups = int(ups * generator.uniform(3.0, 9.0))
    elif roll < 0.03 and not is_human:
        downs = int(downs * generator.uniform(2.0, 5.0))

    return max(0, ups), max(0, downs)


def apply_simulated_votes(
    target_kind: str,
    target_id: str,
    *,
    quality: float,
    controversy: float = 0.3,
    world: dict[str, Any],
    audience: int = 120,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Seed a freshly generated item with a plausible score."""
    collection = _collection_for(target_kind)
    target = collection.get(target_id)
    if not target:
        return None
    ups, downs = simulate_votes(
        quality=quality,
        controversy=controversy,
        is_human=target.get("author_kind") == "human",
        world=world,
        audience=audience,
        rng=rng,
    )
    return collection.update(
        target_id,
        {"$set": {"ups": ups, "downs": downs, "score": ups - downs, "quality": quality,
                  "controversy": controversy}},
    )


def drift_votes(
    target_kind: str,
    target_id: str,
    *,
    world: dict[str, Any],
    intensity: float = 1.0,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Nudge an existing score as if time passed and more people saw it.

    Older content attracts fewer new votes; controversial content keeps churning
    in both directions long after the score stops moving.
    """
    generator = rng or random
    collection = _collection_for(target_kind)
    target = collection.get(target_id)
    if not target:
        return None

    age_hours = max(0.0, (now() - target.get("created_at", now())) / 3600)
    decay = 1.0 / (1.0 + age_hours / 6.0)
    quality = float(target.get("quality", 0.5))
    controversy = float(target.get("controversy", 0.3))

    audience = max(2, int(40 * decay * intensity * generator.uniform(0.4, 1.6)))
    ups, downs = simulate_votes(
        quality=quality,
        controversy=controversy,
        is_human=target.get("author_kind") == "human",
        world=world,
        audience=audience,
        rng=generator,
    )
    if not ups and not downs:
        return target

    collection.update(target_id, {"$inc": {"ups": ups, "downs": downs}})
    updated = collection.get(target_id) or target
    score = int(updated.get("ups", 0)) - int(updated.get("downs", 0))
    collection.update(target_id, {"$set": {"score": score}})

    karma_delta = ups - downs
    if karma_delta:
        if updated.get("author_kind") == "human" and updated.get("author_id"):
            user_service.add_karma(updated["author_id"], target_kind, karma_delta)
        elif updated.get("author_kind") == "ai":
            persona_service.add_karma(updated.get("author", ""), target_kind, karma_delta)

    return collection.get(target_id)


def hot_rank(item: dict[str, Any]) -> float:
    """Score/age ranking in the spirit of the classic 'hot' sort."""
    score = int(item.get("score", 0))
    order = math.log10(max(abs(score), 1))
    sign = 1 if score > 0 else (-1 if score < 0 else 0)
    seconds = item.get("created_at", now()) - 1_700_000_000
    return round(sign * order + seconds / 45000, 7)


def controversial_rank(item: dict[str, Any]) -> float:
    ups = int(item.get("ups", 0))
    downs = int(item.get("downs", 0))
    if ups <= 0 or downs <= 0:
        return 0.0
    magnitude = ups + downs
    balance = min(ups, downs) / max(ups, downs)
    return magnitude ** balance
