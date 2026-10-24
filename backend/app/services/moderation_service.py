"""Simulated moderation.

Threads that get too hot, wander off-topic, or break a board rule attract a
moderator. Removed content leaves the familiar stub behind rather than
disappearing, so the shape of the argument survives.

Humans are never banned. By default the AI moderator only touches AI-authored
content; admins can opt into moderating human comments too.
"""

from __future__ import annotations

import random
from typing import Any

from app.db import db, now
from app.llm import router
from app.llm.base import LLMMessage, extract_rows
from app.llm.prompts import moderation_prompt
from app.services import comment_service, post_service, subreddit_service

REMOVAL_REASONS = [
    "Rule 1: Be civil",
    "Rule 2: Stay on topic",
    "Rule 3: No personal attacks",
    "Removed: brigading",
    "Removed: low-effort",
    "Removed by moderators",
    "Rule 4: No spam or self-promo",
]

AUTOMOD = "AutoModerator"


def _log():
    return db.collection("moderation_log")


def _record(
    action: str,
    *,
    target_kind: str,
    target_id: str,
    subreddit: str,
    reason: str,
    moderator: str,
    by_ai: bool = True,
) -> dict[str, Any]:
    return _log().insert(
        {
            "action": action,
            "target_kind": target_kind,
            "target_id": target_id,
            "subreddit": subreddit,
            "reason": reason,
            "moderator": moderator,
            "by_ai": by_ai,
            "at": now(),
        }
    )


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #

def remove_comment(
    comment_id: str,
    *,
    reason: str = "",
    moderator: str = AUTOMOD,
    by_ai: bool = True,
) -> dict[str, Any] | None:
    comment = comment_service.get(comment_id)
    if not comment or comment.get("removed"):
        return None
    reason = reason or random.choice(REMOVAL_REASONS)
    updated = db.collection("comments").update(
        comment_id,
        {
            "$set": {
                "removed": True,
                "removed_by": moderator,
                "removal_reason": reason,
                # Kept so admins can audit what was taken down.
                "original_body": comment.get("body", ""),
                "removed_at": now(),
            }
        },
    )
    _record(
        "remove_comment",
        target_kind="comment",
        target_id=comment_id,
        subreddit=comment.get("subreddit", ""),
        reason=reason,
        moderator=moderator,
        by_ai=by_ai,
    )
    return updated


def restore_comment(comment_id: str, *, moderator: str = AUTOMOD) -> dict[str, Any] | None:
    comment = comment_service.get(comment_id)
    if not comment or not comment.get("removed"):
        return None
    updated = db.collection("comments").update(
        comment_id,
        {
            "$set": {
                "removed": False,
                "removed_by": None,
                "removal_reason": "",
                "body": comment.get("original_body") or comment.get("body", ""),
            }
        },
    )
    _record(
        "restore_comment",
        target_kind="comment",
        target_id=comment_id,
        subreddit=comment.get("subreddit", ""),
        reason="approved",
        moderator=moderator,
        by_ai=False,
    )
    return updated


def remove_post(
    post_id: str, *, reason: str = "", moderator: str = AUTOMOD, by_ai: bool = True
) -> dict[str, Any] | None:
    post = post_service.get(post_id)
    if not post or post.get("removed"):
        return None
    reason = reason or random.choice(REMOVAL_REASONS)
    updated = db.collection("posts").update(
        post_id,
        {
            "$set": {
                "removed": True,
                "removed_by": moderator,
                "removal_reason": reason,
                "original_body": post.get("body", ""),
                "removed_at": now(),
            }
        },
    )
    _record(
        "remove_post",
        target_kind="post",
        target_id=post_id,
        subreddit=post.get("subreddit", ""),
        reason=reason,
        moderator=moderator,
        by_ai=by_ai,
    )
    return updated


def restore_post(post_id: str, *, moderator: str = AUTOMOD) -> dict[str, Any] | None:
    post = post_service.get(post_id)
    if not post or not post.get("removed"):
        return None
    updated = db.collection("posts").update(
        post_id,
        {
            "$set": {
                "removed": False,
                "removed_by": None,
                "removal_reason": "",
                "body": post.get("original_body") or post.get("body", ""),
            }
        },
    )
    _record(
        "restore_post",
        target_kind="post",
        target_id=post_id,
        subreddit=post.get("subreddit", ""),
        reason="approved",
        moderator=moderator,
        by_ai=False,
    )
    return updated


def set_locked(post_id: str, locked: bool, *, moderator: str = AUTOMOD) -> dict[str, Any] | None:
    post = post_service.get(post_id)
    if not post:
        return None
    updated = db.collection("posts").update(post_id, {"$set": {"locked": locked}})
    _record(
        "lock_post" if locked else "unlock_post",
        target_kind="post",
        target_id=post_id,
        subreddit=post.get("subreddit", ""),
        reason="Thread locked by moderators" if locked else "Unlocked",
        moderator=moderator,
    )
    return updated


def set_stickied(post_id: str, stickied: bool, *, moderator: str = AUTOMOD) -> dict[str, Any] | None:
    return db.collection("posts").update(post_id, {"$set": {"stickied": stickied}})


def post_automod_notice(post_id: str, text: str) -> dict[str, Any] | None:
    """A stickied AutoModerator comment, the way real boards announce a lock."""
    post = post_service.get(post_id)
    if not post:
        return None
    return comment_service.create(
        post_id=post_id,
        body=text,
        author=AUTOMOD,
        author_kind="ai",
        subreddit=post.get("subreddit", ""),
        quality=0.4,
        tone="serious",
    )


# --------------------------------------------------------------------------- #
# Heuristic pass
# --------------------------------------------------------------------------- #

HEAT_MARKERS = (
    "idiot", "moron", "shut up", "stupid", "clown", "trash", "pathetic",
    "get a life", "kill yourself", "loser", "dumbass", "brain dead",
)


def heat_score(comments: list[dict[str, Any]]) -> float:
    """Rough 0..1 measure of how hostile a thread has become."""
    if not comments:
        return 0.0
    hostile = 0
    for comment in comments:
        body = (comment.get("body") or "").lower()
        if any(marker in body for marker in HEAT_MARKERS):
            hostile += 1
        elif comment.get("tone") == "angry":
            hostile += 0.5
    return min(1.0, hostile / max(4, len(comments) * 0.4))


def heuristic_pass(
    post_id: str, *, world: dict[str, Any], rng: random.Random | None = None
) -> list[dict[str, Any]]:
    """Cheap moderation that runs without a model call.

    Picks off the most obviously hostile comments at a rate driven by the
    board's removal_rate, and locks a thread that has fully boiled over.
    """
    generator = rng or random
    if not world.get("moderation_enabled", True):
        return []

    post = post_service.get(post_id)
    if not post:
        return []
    moderate_humans = bool(world.get("moderate_user_content", False))
    comments = [
        c
        for c in comment_service.for_post(post_id)
        if not c.get("removed") and (moderate_humans or c.get("author_kind") == "ai")
    ]
    if not comments:
        return []

    removal_rate = float(world.get("removal_rate", 0.08))
    strictness = float(world.get("moderation_strictness", 0.45))
    board = subreddit_service.get(post.get("subreddit", "")) or {}
    moderators = board.get("moderators") or [AUTOMOD]
    actions: list[dict[str, Any]] = []

    for comment in comments:
        body = (comment.get("body") or "").lower()
        hostile = any(marker in body for marker in HEAT_MARKERS)
        weight = removal_rate * (3.0 if hostile else 0.35) * (0.5 + strictness)
        if generator.random() < min(0.6, weight):
            removed = remove_comment(
                comment["_id"],
                reason=generator.choice(REMOVAL_REASONS[:3] if hostile else REMOVAL_REASONS),
                moderator=generator.choice(moderators),
            )
            if removed:
                actions.append(removed)

    heat = heat_score(comments)
    if heat > 0.75 and strictness > 0.4 and not post.get("locked") and generator.random() < 0.4:
        set_locked(post_id, True)
        post_automod_notice(
            post_id,
            "Locking this one. Y'all can't be normal for five minutes. "
            "Existing comments stay up, no new replies.",
        )
        actions.append({"locked": True})

    return actions


# --------------------------------------------------------------------------- #
# Model-driven pass
# --------------------------------------------------------------------------- #

async def ai_pass(post_id: str, *, world: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Ask a model which comments a real moderator would have acted on."""
    post = post_service.get(post_id)
    if not post:
        return []
    board = subreddit_service.get(post.get("subreddit", ""))
    if not board:
        return []
    effective = world or subreddit_service.effective_world(board)
    if not effective.get("moderation_enabled", True):
        return []

    moderate_humans = bool(effective.get("moderate_user_content", False))
    comments = [
        c
        for c in comment_service.for_post(post_id)
        if not c.get("removed") and (moderate_humans or c.get("author_kind") == "ai")
    ][:40]
    if not comments:
        return []

    system, user = moderation_prompt(effective, board, post, comments)
    parsed, _ = await router.generate_json(
        "moderation", [LLMMessage("system", system), LLMMessage("user", user)]
    )
    decisions = extract_rows(parsed, "decisions")
    if decisions is None:
        # The model gave us nothing usable, so fall back to the cheap pass.
        return heuristic_pass(post_id, world=effective)
    if not decisions:
        # An empty list is a real answer — the moderator read the thread and
        # decided nothing needed touching. Rolling the random heuristic here
        # would remove comments a moderator just explicitly cleared.
        return []

    moderators = board.get("moderators") or [AUTOMOD]
    actions: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        action = decision.get("action")
        target_id = str(decision.get("id", "")).lstrip("c")
        if action == "remove":
            removed = remove_comment(
                target_id,
                reason=str(decision.get("public_note") or decision.get("reason") or "")[:160],
                moderator=random.choice(moderators),
            )
            if removed:
                actions.append(removed)
        elif action == "lock":
            set_locked(post_id, True, moderator=random.choice(moderators))
            post_automod_notice(
                post_id,
                str(decision.get("public_note") or "Thread locked — take it to modmail."),
            )
            actions.append({"locked": True})
    return actions


# --------------------------------------------------------------------------- #
# Reporting and audit
# --------------------------------------------------------------------------- #

def report(
    target_kind: str, target_id: str, reason: str, *, reporter_id: str | None = None
) -> dict[str, Any]:
    return db.collection("reports").insert(
        {
            "target_kind": target_kind,
            "target_id": target_id,
            "reason": (reason or "")[:200],
            "reporter_id": reporter_id,
            "status": "open",
            "at": now(),
        }
    )


def log_for_board(subreddit: str, limit: int = 50) -> list[dict[str, Any]]:
    return _log().find({"subreddit": subreddit}, sort=[("at", -1)], limit=limit)


def recent_log(limit: int = 100) -> list[dict[str, Any]]:
    return _log().find(sort=[("at", -1)], limit=limit)
