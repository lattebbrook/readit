"""The background world.

The forum keeps moving while nobody is looking: scores drift, late replies land
on threads you read an hour ago, boards you follow get new posts, and moderators
occasionally clean something up. A tick is budgeted so a quiet site costs almost
nothing and a busy one degrades gracefully instead of stampeding the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from typing import Any

from app.config import settings
from app.db import db, now
from app.services import (
    comment_service,
    config_service,
    generation_service,
    moderation_service,
    post_service,
    subreddit_service,
    vision_service,
    vote_service,
)

WATCH_TTL = 3 * 3600  # a thread stays "interesting" for three hours after a read


def _watchlist():
    return db.collection("watchlist")


# --------------------------------------------------------------------------- #
# Interest tracking
# --------------------------------------------------------------------------- #

def register_view(post_id: str, user_id: str | None = None, *, weight: float = 1.0) -> None:
    """Note that somebody looked at a thread, so the world keeps writing into it."""
    existing = _watchlist().find_one({"post_id": post_id})
    payload = {
        "post_id": post_id,
        "last_view": now(),
        "expires_at": now() + WATCH_TTL,
        "priority": min(10.0, float((existing or {}).get("priority", 0)) + weight),
        "viewers": list({*(existing or {}).get("viewers", []), user_id} - {None}),
    }
    _watchlist().upsert({"post_id": post_id}, payload)


def register_participation(post_id: str, user_id: str | None = None) -> None:
    """A human posted or commented here — that deserves a real response."""
    register_view(post_id, user_id, weight=4.0)
    _watchlist().upsert(
        {"post_id": post_id}, {"human_activity_at": now(), "needs_reply": True}
    )


def clear_watch(post_id: str) -> None:
    entry = _watchlist().find_one({"post_id": post_id})
    if entry:
        _watchlist().delete(entry["_id"])


def _prune_watchlist() -> None:
    _watchlist().delete_many({"expires_at": {"$lt": now()}})


def watched(limit: int = 40) -> list[dict[str, Any]]:
    _prune_watchlist()
    return _watchlist().find(sort=[("priority", -1)], limit=limit)


# --------------------------------------------------------------------------- #
# Individual jobs
# --------------------------------------------------------------------------- #

def drift_scores(world: dict[str, Any], *, sample: int = 30) -> int:
    """Cheap, model-free: nudge scores on recent content."""
    touched = 0
    posts = db.collection("posts").find(sort=[("created_at", -1)], limit=sample)
    for post in posts:
        if random.random() < 0.45:
            board = subreddit_service.get(post.get("subreddit", ""))
            vote_service.drift_votes(
                "post", post["_id"], world=subreddit_service.effective_world(board)
            )
            touched += 1

    # Comments creep up much more slowly than posts — most should sit near
    # 0/1/2 for a long time, only drifting meaningfully if they stick around.
    comments = db.collection("comments").find(sort=[("created_at", -1)], limit=sample * 2)
    for comment in comments:
        if random.random() < 0.12:
            vote_service.drift_votes("comment", comment["_id"], world=world, intensity=0.2)
            touched += 1
    return touched


async def _grow_watched_threads(budget: int) -> int:
    """Late replies land on threads people have actually opened."""
    spent = 0
    entries = watched(limit=25)
    random.shuffle(entries)

    # Threads where a human spoke recently come first.
    entries.sort(key=lambda e: (bool(e.get("needs_reply")), e.get("priority", 0)), reverse=True)

    for entry in entries:
        if spent >= budget:
            break
        post = post_service.get(entry["post_id"])
        if not post or post.get("locked"):
            clear_watch(entry["post_id"])
            continue

        board = subreddit_service.get(post.get("subreddit", ""))
        world = subreddit_service.effective_world(board)
        if not world.get("background_activity", True):
            continue

        since_generated = now() - post.get("last_generated_at", 0)
        needs_reply = bool(entry.get("needs_reply"))
        cooldown = 45 if needs_reply else 180 + random.random() * 600
        if since_generated < cooldown:
            continue

        # A human who just spoke always gets an answer once the cooldown has
        # passed; threads merely being watched are more of a coin flip on
        # whether this is the tick that adds something.
        if not needs_reply:
            chance = min(0.9, 0.25 + 0.05 * float(entry.get("priority", 0)))
            if random.random() > chance:
                continue

        created = await generation_service.grow_thread(post["_id"])
        spent += 1
        _watchlist().upsert(
            {"post_id": post["_id"]},
            {"needs_reply": False, "priority": max(0.0, float(entry.get("priority", 0)) - 1.0)},
        )
        if created and random.random() < 0.25:
            await _maybe_moderate(post["_id"], world)
    return spent


async def _maybe_moderate(post_id: str, world: dict[str, Any]) -> None:
    comments = comment_service.for_post(post_id)
    if moderation_service.heat_score(comments) > 0.55:
        await moderation_service.ai_pass(post_id, world=world)
    else:
        moderation_service.heuristic_pass(post_id, world=world)


def _active_board_names() -> list[str]:
    """Boards worth spending generation on: subscribed, recently read, or busy."""
    names: dict[str, float] = {}

    for user in db.collection("users").find(limit=200):
        for name in user.get("subscriptions") or []:
            names[name] = names.get(name, 0) + 2.0

    for entry in watched(limit=40):
        post = post_service.get(entry["post_id"])
        if post:
            names[post["subreddit"]] = names.get(post["subreddit"], 0) + 1.0

    for board in db.collection("subreddits").find(sort=[("last_activity_at", -1)], limit=12):
        names[board["name"]] = names.get(board["name"], 0) + 0.5

    ordered = sorted(names.items(), key=lambda item: item[1], reverse=True)
    return [name for name, _ in ordered]


async def _refresh_boards(budget: int) -> int:
    """Post new threads to boards that have gone quiet."""
    spent = 0
    for name in _active_board_names():
        if spent >= budget:
            break
        board = subreddit_service.get(name)
        if not board:
            continue
        if board.get("kind") == "photo":
            # Nothing to post without a picture; these boards fill up when a
            # person captures something, and the world supplies the discussion.
            continue
        world = subreddit_service.effective_world(board)
        if not world.get("background_activity", True):
            continue

        target = int(world.get("posts_per_board_target", 12))
        current = db.collection("posts").count({"subreddit": board["name"]})
        stale = now() - board.get("last_generated_at", 0)
        activity = float(board.get("activity_level", 1.0))

        if current == 0:
            probability = 1.0  # a genuinely empty board must never stay empty
        elif current < target:
            probability = 0.9
        elif stale > 900 / max(0.2, activity):
            probability = 0.35 * activity
        else:
            continue

        if random.random() > probability:
            continue

        await generation_service.generate_posts(
            board["name"], count=random.randint(1, 3), backdate_hours=1.5
        )
        spent += 1
    return spent


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class SimulationEngine:
    """Owns the background loop and the per-tick budget."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._snapshot_task: asyncio.Task | None = None
        self._running = False
        self.ticks = 0
        self.last_tick_at: float = 0.0
        self.last_error: str | None = None
        self.generations = 0

    @property
    def running(self) -> bool:
        return self._running

    async def tick(self) -> dict[str, Any]:
        """One pass of the world. Safe to call directly (tests, admin button)."""
        started = time.perf_counter()
        world = config_service.get_world()
        result = {
            "drifted": 0,
            "threads_grown": 0,
            "boards_refreshed": 0,
            "images_described": 0,
            "skipped": False,
            "idle_no_model": False,
        }

        if not world.get("simulation_enabled", True):
            result["skipped"] = True
            return result

        # Vote drift needs no model, so the world still breathes a little even
        # with every connection switched off.
        result["drifted"] = drift_scores(world)

        if not config_service.autonomous_generation_allowed():
            result["idle_no_model"] = True
            self.ticks += 1
            self.last_tick_at = now()
            result["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return result

        # Caption anything captured since the last tick. A bulk folder import
        # drains here rather than blocking whichever request kicked it off.
        result["images_described"] = await vision_service.analyse_pending(limit=2)

        if world.get("background_activity", True):
            budget = max(1, settings.max_concurrent_generations)
            thread_budget = max(1, int(budget * 0.7))
            result["threads_grown"] = await _grow_watched_threads(thread_budget)
            result["boards_refreshed"] = await _refresh_boards(budget - thread_budget)

        self.ticks += 1
        self.last_tick_at = now()
        self.generations += result["threads_grown"] + result["boards_refreshed"]
        result["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    async def _loop(self) -> None:
        while self._running:
            world = config_service.get_world()
            interval = float(world.get("tick_seconds") or settings.tick_seconds)
            try:
                await self.tick()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad tick must not kill the world
                self.last_error = f"{type(exc).__name__}: {exc}"
            # Jitter keeps activity from arriving in visible lockstep.
            await asyncio.sleep(max(2.0, interval * random.uniform(0.7, 1.4)))

    async def _snapshot_loop(self) -> None:
        while self._running:
            await asyncio.sleep(max(10, settings.snapshot_interval_seconds))
            with contextlib.suppress(Exception):
                db.save_snapshot()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._loop())
        if settings.persist:
            self._snapshot_task = loop.create_task(self._snapshot_loop())

    async def stop(self) -> None:
        self._running = False
        for task in (self._task, self._snapshot_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
        self._snapshot_task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "ticks": self.ticks,
            "generations": self.generations,
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
            "watched_threads": _watchlist().count(),
        }


engine = SimulationEngine()
