"""Content generation: turning prompts into posts, comments and threads.

This is where the forum actually gets written. Everything else stores or ranks;
this module decides who speaks, what about, and how the room reacts.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.db import db, now
from app.llm import router
from app.llm.base import LLMImage, LLMMessage, extract_rows
from app.llm.prompts import comments_prompt, density_target, pick_focus, posts_prompt
from app.services import (
    award_service,
    comment_service,
    config_service,
    media_service,
    moderation_service,
    notification_service,
    persona_service,
    post_service,
    subreddit_service,
    vision_service,
    vote_service,
)

# One generation at a time per thread/board, so a burst of readers opening the
# same post does not produce four overlapping batches of comments.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def reset_locks() -> None:
    """Tests run on fresh event loops; stale locks would bind to a dead one."""
    _locks.clear()


def _record_activity(kind: str, **payload: Any) -> None:
    collection = db.collection("activity")
    collection.insert({"kind": kind, "at": now(), **payload})
    overflow = collection.count() - 500
    if overflow > 0:
        for doc in collection.find(sort=[("at", 1)], limit=overflow):
            collection.delete(doc["_id"])


def _distribute_times(count: int, start: float, end: float) -> list[float]:
    """Spread ``count`` timestamps over a window, clustered like real traffic."""
    if count <= 0:
        return []
    span = max(1.0, end - start)
    points = sorted(random.random() ** 1.4 for _ in range(count))
    return [start + point * span for point in points]


def _audience_for(post: dict[str, Any], depth: int) -> int:
    """How many people plausibly saw a comment at this depth in this thread.

    Real threads have a long tail: most replies are read by a handful of
    people and land near 0/1/2 points (occasionally negative), independent of
    how big the parent post is. A small slice gets real traction, and a rare
    one breaks out — that's what should occasionally rival the post's own
    score, not the median comment.
    """
    roll = random.random()
    if roll > 0.985:
        base = random.randint(150, 1500)  # rare breakout reply
    elif roll > 0.90:
        base = random.randint(15, 80)  # noticed
    else:
        base = random.randint(2, 9)  # typical: barely seen
    return max(1, int(base * (0.55**depth)))


# Weight, low, high — most posts land in the middle, a few take off, a few
# flop outright. Rolled once per post so the eventual score is unrelated to
# quality alone; a good post can still land quiet, a mediocre one can catch on.
_POST_POPULARITY_TIERS: list[tuple[float, int, int]] = [
    (0.02, 18000, 35000),  # viral
    (0.10, 4000, 12000),  # popular
    (0.35, 300, 2500),  # normal
    (0.35, 15, 250),  # quiet
    (0.18, 0, 20),  # flop
]


def _roll_post_audience() -> int:
    _, low, high = random.choices(
        _POST_POPULARITY_TIERS, weights=[tier[0] for tier in _POST_POPULARITY_TIERS], k=1
    )[0]
    return random.randint(low, high)


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #

async def generate_posts(
    board_name: str,
    *,
    count: int = 4,
    user: dict[str, Any] | None = None,
    backdate_hours: float = 20.0,
) -> list[dict[str, Any]]:
    """Write new posts for a board and give each one an opening score."""
    board = subreddit_service.get(board_name)
    if not board:
        return []
    if board.get("kind") == "photo":
        # A photo board's posts are images, and the writer cannot produce one.
        # Threads here start when a person captures something.
        return []

    async with _lock_for(f"board:{board['_id']}"):
        world = subreddit_service.effective_world(board, user)
        await persona_service.ensure_roster(board, minimum=10)
        personas = persona_service.sample_for_board(board, count=max(6, count * 2))

        existing_titles = [
            post["title"]
            for post in db.collection("posts").find(
                {"subreddit": board["name"]}, sort=[("created_at", -1)], limit=25
            )
        ]
        system, user_prompt = posts_prompt(
            world,
            board,
            personas,
            count=count,
            existing_titles=existing_titles,
            seed_topics=board.get("topics") or None,
            user_prompt=subreddit_service.personal_prompt_for(board["name"], user),
        )
        parsed, response = await router.generate_json(
            "post", [LLMMessage("system", system), LLMMessage("user", user_prompt)]
        )
        rows = extract_rows(parsed, "posts")
        if not rows:
            return []

        created: list[dict[str, Any]] = []
        timestamps = _distribute_times(len(rows), now() - backdate_hours * 3600, now() - 120)

        for index, row in enumerate(rows[:count]):
            if not isinstance(row, dict) or not row.get("title"):
                continue
            persona = persona_service.ensure_persona(
                row.get("author") or random.choice(personas)["username"], board["name"]
            )
            quality = float(row.get("quality", random.uniform(0.3, 0.9)))
            controversy = float(row.get("controversy", random.uniform(0.1, 0.7)))
            post = post_service.create(
                subreddit=board["name"],
                title=str(row["title"])[:300],
                body=str(row.get("body", ""))[:20000],
                author=persona["username"],
                author_kind="ai",
                kind=row.get("kind", "text") if row.get("kind") in {"text", "link", "image"} else "text",
                link_url=str(row.get("link_url", ""))[:500],
                flair=str(row.get("flair", ""))[:40],
                nsfw=bool(board.get("nsfw")),
                quality=quality,
                controversy=controversy,
                created_at=timestamps[index] if index < len(timestamps) else now(),
            )
            vote_service.apply_simulated_votes(
                "post",
                post["_id"],
                quality=quality,
                controversy=controversy,
                world=world,
                audience=_roll_post_audience(),
            )
            refreshed = post_service.get(post["_id"]) or post
            award_service.maybe_award("post", refreshed, world=world)
            created.append(post_service.get(post["_id"]) or post)
            _record_activity(
                "post", subreddit=board["name"], post_id=post["_id"], author=persona["username"]
            )

        db.collection("subreddits").update(
            board["_id"], {"$set": {"last_generated_at": now(), "last_activity_at": now()}}
        )
        return created


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

def _resolve_parent(
    reply_to: Any, new_ids: list[str], existing_ids: set[str]
) -> str | None:
    """Map the model's ``reply_to`` reference onto a real comment id."""
    if reply_to in (None, "", "null"):
        return None
    token = str(reply_to).strip()
    if token.startswith("n"):
        try:
            index = int(token[1:])
        except ValueError:
            return None
        return new_ids[index] if 0 <= index < len(new_ids) else None
    candidate = token[1:] if token.startswith("c") else token
    return candidate if candidate in existing_ids else None


def _target_comment_count(post: dict[str, Any], world: dict[str, Any], existing: int) -> int:
    """How many comments this pass should add."""
    base = density_target(world, base=8)
    # Popular threads keep pulling people in; quiet ones stay quiet.
    popularity = 1.0 + min(2.0, max(0, post.get("score", 0)) / 800.0)
    target = int(base * popularity * random.uniform(0.7, 1.4))
    ceiling = int(world.get("max_comments_per_thread", 150))
    return max(0, min(target, ceiling - existing, 30))


async def generate_comments(
    post_id: str,
    *,
    count: int | None = None,
    user: dict[str, Any] | None = None,
    focus: str | None = None,
    reply_to_comment_id: str | None = None,
    live: bool = False,
) -> list[dict[str, Any]]:
    """Add a batch of comments to a thread.

    ``live=True`` timestamps them at the present moment (background growth);
    otherwise they are spread across the thread's lifetime so a first read of an
    older post looks like it has been accumulating replies for hours.
    """
    post = post_service.get(post_id)
    if not post:
        return []
    board = subreddit_service.get(post.get("subreddit", ""))
    if not board:
        return []

    async with _lock_for(f"post:{post_id}"):
        post = post_service.get(post_id) or post
        if post.get("locked"):
            return []

        world = subreddit_service.effective_world(board, user)
        existing_count = comment_service.count_for_post(post_id)
        wanted = count if count is not None else _target_comment_count(post, world, existing_count)
        if wanted <= 0:
            return []

        post_service.set_generation_state(post_id, "generating")
        try:
            await persona_service.ensure_roster(board, minimum=10)
            recent_authors = [
                c["author"]
                for c in db.collection("comments").find(
                    {"post_id": post_id}, sort=[("created_at", -1)], limit=6
                )
            ]
            personas = persona_service.sample_for_board(board, count=min(14, wanted + 6))
            # Keep a couple of people already in the thread so arguments continue.
            for name in recent_authors[:3]:
                persona = persona_service.get_persona(name)
                if persona and persona not in personas:
                    personas.insert(0, persona)

            existing_tree = comment_service.render_tree_for_prompt(post_id)
            chosen_focus = focus or pick_focus(world)
            if reply_to_comment_id:
                target = comment_service.get(reply_to_comment_id)
                if target:
                    chosen_focus = (
                        f"Reply directly to comment [c{target['_id']}] by {target['author']}: "
                        f"\"{(target.get('body') or '')[:220]}\". Some agree, some push back hard."
                    )

            # Describe once, discuss many: the image was captioned at ingest, so
            # thirty comment generations read that text instead of re-encoding
            # the picture thirty times.
            media_analysis = None
            if post.get("media_id"):
                media_analysis = await vision_service.analyse(post["media_id"], subreddit=board)

            system, user_prompt = comments_prompt(
                world,
                board,
                {**post, "age_label": post_service.age_label(post.get("created_at", now()))},
                personas,
                count=wanted,
                existing_tree=existing_tree,
                focus=chosen_focus,
                user_prompt=subreddit_service.personal_prompt_for(board["name"], user),
                is_user_post=post.get("author_kind") == "human",
                media_analysis=media_analysis,
            )

            # Occasionally hand the batch the real picture as well. Those are the
            # replies that catch a detail the caption never mentioned, and they
            # are worth the extra cost precisely because they are rare.
            attachments: list[LLMImage] = []
            if media_analysis and random.random() < 0.15:
                payload = media_service.vision_bytes(
                    media_service.get(post["media_id"]) or {}
                )
                if payload:
                    attachments = [LLMImage(data=payload, mime=media_service.VISION_MIME)]

            parsed, _ = await router.generate_json(
                "comment",
                [
                    LLMMessage("system", system),
                    LLMMessage("user", user_prompt, images=attachments),
                ],
            )
            rows = extract_rows(parsed, "comments")
            if not rows:
                return []

            existing_ids = {c["_id"] for c in comment_service.for_post(post_id)}
            if live:
                start, end = now() - 240, now()
            else:
                latest = max(
                    [post.get("created_at", now())]
                    + [c.get("created_at", 0) for c in comment_service.for_post(post_id)]
                )
                start, end = latest + 30, now()
                if end <= start:
                    start, end = now() - 300, now()
            timestamps = _distribute_times(len(rows), start, end)

            created: list[dict[str, Any]] = []
            new_ids: list[str] = []

            for index, row in enumerate(rows[:wanted]):
                if not isinstance(row, dict) or not str(row.get("body", "")).strip():
                    new_ids.append("")
                    continue
                persona = persona_service.ensure_persona(
                    row.get("author") or random.choice(personas)["username"], board["name"]
                )
                parent_id = _resolve_parent(row.get("reply_to"), new_ids, existing_ids)
                if reply_to_comment_id and parent_id is None and index == 0:
                    parent_id = reply_to_comment_id

                quality = float(row.get("quality", random.uniform(0.2, 0.9)))
                try:
                    comment = comment_service.create(
                        post_id=post_id,
                        parent_id=parent_id,
                        body=str(row["body"])[:10000],
                        author=persona["username"],
                        author_kind="ai",
                        subreddit=board["name"],
                        tone=str(row.get("tone", ""))[:20],
                        quality=quality,
                        controversy=float(row.get("controversy", random.uniform(0.1, 0.8))),
                        edited=bool(row.get("edited")),
                        created_at=timestamps[index] if index < len(timestamps) else now(),
                    )
                except comment_service.CommentError:
                    new_ids.append("")
                    continue

                new_ids.append(comment["_id"])
                existing_ids.add(comment["_id"])

                vote_service.apply_simulated_votes(
                    "comment",
                    comment["_id"],
                    quality=quality,
                    controversy=float(row.get("controversy", 0.3)),
                    world=world,
                    audience=_audience_for(post, comment.get("depth", 0)),
                )
                refreshed = comment_service.get(comment["_id"]) or comment
                granted = award_service.maybe_award(
                    "comment", refreshed, world=world, tone=str(row.get("tone", ""))
                )
                if granted:
                    notification_service.notify_award(
                        refreshed, granted["award"], granted["grant"].get("giver")
                    )

                parent = comment_service.get(parent_id) if parent_id else None
                notification_service.notify_reply(refreshed, parent, post)
                persona_service.touch(persona["username"])
                created.append(refreshed)

            post_service.recount_comments(post_id)
            db.collection("posts").update(post_id, {"$set": {"last_generated_at": now()}})
            subreddit_service.touch_activity(board["name"])
            _record_activity(
                "comments", subreddit=board["name"], post_id=post_id, count=len(created)
            )

            if created and world.get("moderation_enabled", True):
                await _maybe_moderate(post_id, world)

            return created
        finally:
            post_service.set_generation_state(post_id, "idle")


async def _maybe_moderate(post_id: str, world: dict[str, Any]) -> None:
    """Run a moderation pass sometimes — a model pass when it is worth the call."""
    comments = comment_service.for_post(post_id)
    heat = moderation_service.heat_score(comments)
    strictness = float(world.get("moderation_strictness", 0.45))

    # Serious Mode promises topicality, so review every new batch even when an
    # off-topic derail is calm rather than hostile. The ordinary modes keep the
    # cheaper probabilistic behaviour.
    if world.get("serious_mode"):
        actions = await moderation_service.ai_pass(post_id, world=world)
    elif heat > 0.5 and random.random() < strictness:
        actions = await moderation_service.ai_pass(post_id, world=world)
    elif random.random() < float(world.get("removal_rate", 0.08)):
        actions = moderation_service.heuristic_pass(post_id, world=world)
    else:
        return

    for action in actions:
        if isinstance(action, dict) and action.get("author_kind") == "human":
            notification_service.notify_mod_action(
                action, action.get("removal_reason", ""), action.get("removed_by", "AutoModerator")
            )


async def ensure_thread_populated(
    post_id: str, user: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """First read of a thread: fill it with a believable amount of discussion."""
    post = post_service.get(post_id)
    if not post:
        return []
    if comment_service.count_for_post(post_id) > 0:
        return []
    board = subreddit_service.get(post.get("subreddit", ""))
    world = subreddit_service.effective_world(board, user)

    batch = await generate_comments(post_id, user=user)
    # Busy boards get a second wave so the thread has real depth on first view.
    if world.get("comment_density") in {"busy", "chaotic"} and batch:
        batch += await generate_comments(post_id, user=user, focus=pick_focus(world))
    return batch


async def grow_thread(
    post_id: str, user: dict[str, Any] | None = None, *, count: int | None = None
) -> list[dict[str, Any]]:
    """Background growth: a few more people wander in later."""
    post = post_service.get(post_id)
    if not post or post.get("locked"):
        return []
    board = subreddit_service.get(post.get("subreddit", ""))
    world = subreddit_service.effective_world(board, user)
    amount = count if count is not None else max(1, int(density_target(world, base=3) * random.uniform(0.4, 1.2)))
    return await generate_comments(post_id, count=amount, user=user, live=True)


async def reply_to_user_comment(
    comment_id: str, user: dict[str, Any] | None = None, *, count: int | None = None
) -> list[dict[str, Any]]:
    """Someone answers a human's comment — the payoff for participating."""
    comment = comment_service.get(comment_id)
    if not comment:
        return []
    amount = count if count is not None else random.randint(1, 4)
    return await generate_comments(
        comment["post_id"],
        count=amount,
        user=user,
        reply_to_comment_id=comment_id,
        live=True,
    )


async def seed_board(
    board_name: str, *, posts: int = 6, threads_to_fill: int = 2
) -> dict[str, Any]:
    """Give a brand new board enough content that it does not look empty."""
    created_posts = await generate_posts(board_name, count=posts)
    filled = 0
    for post in created_posts[:threads_to_fill]:
        await generate_comments(post["_id"], count=random.randint(4, 10))
        filled += 1
    return {"posts": len(created_posts), "threads_filled": filled}
