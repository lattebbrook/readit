"""Posts: creation, feeds, sorting, and the view model the frontend renders."""

from __future__ import annotations

import math
import random
from typing import Any

from app.db import db, now
from app.services import (
    award_service,
    media_service,
    persona_service,
    subreddit_service,
    vote_service,
)

REMOVED_BODY = "[removed]"
REMOVED_TITLE = "[removed]"
DELETED_BODY = "[deleted]"

SORTS = {"hot", "new", "top", "rising", "controversial", "best"}


class PostError(ValueError):
    """User-facing post validation failure."""


def _posts():
    return db.collection("posts")


def get(post_id: str) -> dict[str, Any] | None:
    return _posts().get(post_id)


def create(
    *,
    subreddit: str,
    title: str,
    body: str = "",
    author: str,
    author_id: str | None = None,
    author_kind: str = "human",
    kind: str = "text",
    link_url: str = "",
    flair: str = "",
    nsfw: bool = False,
    spoiler: bool = False,
    quality: float = 0.5,
    controversy: float = 0.3,
    created_at: float | None = None,
    media_id: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise PostError("A post needs a title.")
    if len(title) > 300:
        title = title[:300]
    if kind == "link" and not link_url:
        kind = "text"

    doc = {
        "subreddit": subreddit,
        "title": title,
        "body": (body or "")[:20000],
        "kind": kind,
        "link_url": link_url,
        "media_id": media_id,
        "flair": (flair or "")[:40],
        "author": author,
        "author_id": author_id,
        "author_kind": author_kind,
        "ups": 1,
        "downs": 0,
        "score": 1,
        "quality": float(quality),
        "controversy": float(controversy),
        "awards": {},
        "award_total": 0,
        "comment_count": 0,
        "view_count": 0,
        "removed": False,
        "removed_by": None,
        "removal_reason": "",
        "locked": False,
        "stickied": False,
        "nsfw": nsfw,
        "spoiler": spoiler,
        "edited": False,
        "deleted_by_author": False,
        "generation_state": "idle",
        "last_generated_at": 0.0,
        "created_at": created_at if created_at is not None else now(),
    }
    created = _posts().insert(doc)
    subreddit_service.touch_activity(subreddit)
    return created


def edit(post_id: str, *, title: str | None = None, body: str | None = None) -> dict[str, Any] | None:
    changes: dict[str, Any] = {"edited": True}
    if title is not None:
        changes["title"] = title.strip()[:300]
    if body is not None:
        changes["body"] = body[:20000]
    return _posts().update(post_id, {"$set": changes})


def delete_by_author(post_id: str) -> dict[str, Any] | None:
    return _posts().update(
        post_id,
        {
            "$set": {
                "title": "[deleted by user]",
                "body": DELETED_BODY,
                "deleted_by_author": True,
                "author": "[deleted]",
                "author_kind": "deleted",
            }
        },
    )


def hard_delete(post_id: str) -> bool:
    db.collection("comments").delete_many({"post_id": post_id})
    db.collection("votes").delete_many({"target_id": post_id})
    return _posts().delete(post_id)


def increment_views(post_id: str) -> None:
    _posts().update(post_id, {"$inc": {"view_count": 1}})


def set_generation_state(post_id: str, state: str) -> None:
    _posts().update(post_id, {"$set": {"generation_state": state}})


def recount_comments(post_id: str) -> int:
    total = db.collection("comments").count({"post_id": post_id})
    _posts().update(post_id, {"$set": {"comment_count": total}})
    return total


# --------------------------------------------------------------------------- #
# Sorting and feeds
# --------------------------------------------------------------------------- #

def _rising_rank(post: dict[str, Any]) -> float:
    age_hours = max(0.05, (now() - post.get("created_at", now())) / 3600)
    velocity = (post.get("score", 0) + post.get("comment_count", 0) * 2) / age_hours
    return velocity / (1 + math.log1p(age_hours))


def _best_rank(post: dict[str, Any]) -> float:
    """Wilson-ish lower bound: quality that survives small sample sizes."""
    ups = max(0, int(post.get("ups", 0)))
    downs = max(0, int(post.get("downs", 0)))
    total = ups + downs
    if total == 0:
        return 0.0
    z = 1.281551565545
    phat = ups / total
    return (
        phat
        + z * z / (2 * total)
        - z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    ) / (1 + z * z / total)


def sort_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "new":
        return sorted(items, key=lambda p: p.get("created_at", 0), reverse=True)
    if sort == "top":
        return sorted(items, key=lambda p: p.get("score", 0), reverse=True)
    if sort == "controversial":
        return sorted(items, key=vote_service.controversial_rank, reverse=True)
    if sort == "rising":
        return sorted(items, key=_rising_rank, reverse=True)
    if sort == "best":
        return sorted(items, key=_best_rank, reverse=True)
    return sorted(items, key=vote_service.hot_rank, reverse=True)


def list_for_board(
    subreddit: str, *, sort: str = "hot", limit: int = 25, skip: int = 0
) -> list[dict[str, Any]]:
    posts = _posts().find({"subreddit": subreddit})
    stickied = [p for p in posts if p.get("stickied")]
    rest = sort_items([p for p in posts if not p.get("stickied")], sort)
    return (stickied + rest)[skip : skip + limit]


def feed_for_user(
    user: dict[str, Any] | None,
    *,
    scope: str = "home",
    sort: str = "hot",
    limit: int = 25,
    skip: int = 0,
) -> list[dict[str, Any]]:
    """Home = subscriptions + interests; Popular = everything the user allows."""
    banned = {name.lower() for name in ((user or {}).get("banned_subreddits") or [])}
    preferences = (user or {}).get("preferences") or {}
    show_nsfw = bool(preferences.get("show_nsfw"))

    posts = _posts().all()
    posts = [p for p in posts if p.get("subreddit", "").lower() not in banned]

    if not show_nsfw:
        nsfw_boards = {
            board["name"].lower()
            for board in db.collection("subreddits").find({"nsfw": True})
        }
        posts = [
            p
            for p in posts
            if not p.get("nsfw") and p.get("subreddit", "").lower() not in nsfw_boards
        ]

    if scope == "home" and user:
        subscriptions = {name.lower() for name in (user.get("subscriptions") or [])}
        if subscriptions:
            posts = [p for p in posts if p.get("subreddit", "").lower() in subscriptions]

    return sort_items(posts, sort)[skip : skip + limit]


def search(query: str, *, subreddit: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    needle = (query or "").lower().strip()
    if not needle:
        return []
    scope = _posts().find({"subreddit": subreddit}) if subreddit else _posts().all()
    hits = [
        post
        for post in scope
        if needle in post.get("title", "").lower() or needle in post.get("body", "").lower()
    ]
    return sort_items(hits, "hot")[:limit]


def user_posts(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return sort_items(_posts().find({"author_id": user_id}), "new")[:limit]


def by_author_name(author: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return sort_items(_posts().find({"author": author}), "new")[:limit]


def posts_by_ids(ids: list[str]) -> list[dict[str, Any]]:
    """Resolve a saved-posts list to full documents, newest first."""
    found = [doc for doc_id in ids if (doc := _posts().get(doc_id))]
    return sort_items(found, "new")


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #

def age_label(timestamp: float) -> str:
    delta = max(0, now() - (timestamp or now()))
    minutes = delta / 60
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} hr ago"
    days = hours / 24
    if days < 30:
        return f"{int(days)} day{'s' if int(days) != 1 else ''} ago"
    months = days / 30
    if months < 12:
        return f"{int(months)} mo ago"
    return f"{int(months / 12)} yr ago"


def author_badge(item: dict[str, Any]) -> dict[str, Any] | None:
    """The little "human" capsule.

    Only real accounts get one. AI authors deliberately carry no marker at all —
    they are indistinguishable from everyone else in the UI.
    """
    if item.get("author_kind") != "human":
        return None
    return {"kind": "human", "label": "human", "title": "Posted by a real person"}


def public_post(
    post: dict[str, Any],
    user: dict[str, Any] | None = None,
    *,
    vote_map: dict[str, int] | None = None,
    include_internal: bool = False,
) -> dict[str, Any]:
    removed = bool(post.get("removed"))
    deleted = bool(post.get("deleted_by_author"))
    body = post.get("body", "")
    title = post.get("title", "")
    if removed:
        body = REMOVED_BODY
    elif deleted:
        body = DELETED_BODY

    payload: dict[str, Any] = {
        "id": post["_id"],
        "subreddit": post.get("subreddit"),
        "title": title,
        "body": body,
        "kind": post.get("kind", "text"),
        "link_url": post.get("link_url", ""),
        "flair": post.get("flair", ""),
        "author": post.get("author"),
        "author_id": post.get("author_id"),
        "author_badge": author_badge(post),
        "score": post.get("score", 0),
        "ups": post.get("ups", 0),
        "downs": post.get("downs", 0),
        "comment_count": post.get("comment_count", 0),
        "view_count": post.get("view_count", 0),
        "awards": award_service.awards_for("post", post["_id"]),
        "award_total": post.get("award_total", 0),
        "removed": removed,
        "removal_reason": post.get("removal_reason", "") if removed else "",
        "removed_by": post.get("removed_by") if removed else None,
        "deleted_by_author": deleted,
        "locked": post.get("locked", False),
        "stickied": post.get("stickied", False),
        "nsfw": post.get("nsfw", False),
        "spoiler": post.get("spoiler", False),
        "edited": post.get("edited", False),
        "created_at": post.get("created_at"),
        "age_label": age_label(post.get("created_at", now())),
        "generation_state": post.get("generation_state", "idle"),
        "user_vote": 0,
        "is_own": bool(user and post.get("author_id") == user.get("_id")),
        "saved": bool(user and post["_id"] in (user.get("saved_posts") or [])),
        "media": media_service.public_media(
            media_service.get(post["media_id"]) if post.get("media_id") else None
        ),
    }

    if user:
        if vote_map is not None:
            payload["user_vote"] = vote_map.get(post["_id"], 0)
        else:
            payload["user_vote"] = vote_service.get_vote(user["_id"], "post", post["_id"])

    if include_internal:
        payload["quality"] = post.get("quality")
        payload["controversy"] = post.get("controversy")
        payload["original_body"] = post.get("original_body")
        payload["author_kind"] = post.get("author_kind")

    return payload


def public_posts(
    posts: list[dict[str, Any]], user: dict[str, Any] | None = None, **kwargs: Any
) -> list[dict[str, Any]]:
    vote_map = vote_service.user_votes_for(
        (user or {}).get("_id"), [post["_id"] for post in posts]
    )
    return [public_post(post, user, vote_map=vote_map, **kwargs) for post in posts]


def author_profile(author: str) -> dict[str, Any] | None:
    """Resolve a byline to a profile, whether it belongs to a person or a persona."""
    from app.services import user_service

    account = user_service.get_by_username(author)
    if account:
        return user_service.public_user(account)
    return persona_service.public_persona(persona_service.get_persona(author))


def random_backdated_time(max_hours: float = 20.0) -> float:
    """A creation timestamp in the recent past, so seeded boards look lived-in."""
    return now() - random.uniform(0.2, max_hours) * 3600
