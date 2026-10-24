"""Comments: threaded storage, sorting, tree building, and prompt rendering."""

from __future__ import annotations

from typing import Any

from app.db import db, now
from app.services import award_service, post_service, vote_service

REMOVED_BODY = "[removed]"
DELETED_BODY = "[deleted]"

MAX_DEPTH = 12
SORTS = {"best", "top", "new", "controversial", "old", "qa"}


class CommentError(ValueError):
    """User-facing comment validation failure."""


def _comments():
    return db.collection("comments")


def get(comment_id: str) -> dict[str, Any] | None:
    return _comments().get(comment_id)


def create(
    *,
    post_id: str,
    body: str,
    author: str,
    author_id: str | None = None,
    author_kind: str = "human",
    parent_id: str | None = None,
    subreddit: str = "",
    tone: str = "",
    quality: float = 0.5,
    controversy: float = 0.3,
    edited: bool = False,
    created_at: float | None = None,
) -> dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise CommentError("Comment can't be empty.")

    post = post_service.get(post_id)
    if not post:
        raise CommentError("That thread no longer exists.")
    if post.get("locked") and author_kind == "human":
        raise CommentError("This thread is locked.")

    depth = 0
    if parent_id:
        parent = get(parent_id)
        if not parent:
            raise CommentError("The comment you replied to is gone.")
        depth = min(MAX_DEPTH, int(parent.get("depth", 0)) + 1)

    doc = {
        "post_id": post_id,
        "parent_id": parent_id,
        "subreddit": subreddit or post.get("subreddit", ""),
        "body": body[:10000],
        "author": author,
        "author_id": author_id,
        "author_kind": author_kind,
        "depth": depth,
        "ups": 1,
        "downs": 0,
        "score": 1,
        "quality": float(quality),
        "controversy": float(controversy),
        "tone": tone,
        "awards": {},
        "award_total": 0,
        "removed": False,
        "removed_by": None,
        "removal_reason": "",
        "edited": edited,
        "deleted_by_author": False,
        "is_op": bool(post.get("author_id") and post.get("author_id") == author_id)
        or (post.get("author") == author and author_kind == "ai"),
        "created_at": created_at if created_at is not None else now(),
    }
    created = _comments().insert(doc)
    post_service.recount_comments(post_id)
    return created


def edit(comment_id: str, body: str) -> dict[str, Any] | None:
    return _comments().update(
        comment_id, {"$set": {"body": (body or "").strip()[:10000], "edited": True}}
    )


def delete_by_author(comment_id: str) -> dict[str, Any] | None:
    """Author deletion keeps the node so the thread below it survives."""
    return _comments().update(
        comment_id,
        {
            "$set": {
                "body": DELETED_BODY,
                "deleted_by_author": True,
                "author": "[deleted]",
                "author_kind": "deleted",
            }
        },
    )


def hard_delete(comment_id: str) -> bool:
    comment = get(comment_id)
    if not comment:
        return False
    db.collection("votes").delete_many({"target_id": comment_id})
    deleted = _comments().delete(comment_id)
    post_service.recount_comments(comment["post_id"])
    return deleted


def for_post(post_id: str, *, include_removed: bool = True) -> list[dict[str, Any]]:
    comments = _comments().find({"post_id": post_id})
    if not include_removed:
        comments = [c for c in comments if not c.get("removed")]
    return comments


def count_for_post(post_id: str) -> int:
    return _comments().count({"post_id": post_id})


def top_level(post_id: str) -> list[dict[str, Any]]:
    return [c for c in for_post(post_id) if not c.get("parent_id")]


def children_of(comment_id: str) -> list[dict[str, Any]]:
    return _comments().find({"parent_id": comment_id})


def _sort_key(sort: str):
    if sort == "new":
        return lambda c: c.get("created_at", 0), True
    if sort == "old":
        return lambda c: c.get("created_at", 0), False
    if sort == "top":
        return lambda c: c.get("score", 0), True
    if sort == "controversial":
        return vote_service.controversial_rank, True
    if sort == "qa":
        return lambda c: (c.get("is_op", False), c.get("score", 0)), True
    # "best": score, but recency breaks ties so live threads feel alive
    return lambda c: (c.get("score", 0) * 1.0 + c.get("created_at", 0) / 1e9), True


def build_tree(
    post_id: str,
    user: dict[str, Any] | None = None,
    *,
    sort: str = "best",
    hide_removed: bool = False,
    max_depth: int = MAX_DEPTH,
) -> list[dict[str, Any]]:
    """Assemble the nested comment tree in one pass over the flat rows."""
    comments = for_post(post_id)
    if hide_removed:
        comments = [c for c in comments if not c.get("removed")]

    vote_map = vote_service.user_votes_for(
        (user or {}).get("_id"), [c["_id"] for c in comments]
    )

    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for comment in comments:
        by_parent.setdefault(comment.get("parent_id"), []).append(comment)

    key, reverse = _sort_key(sort)
    for bucket in by_parent.values():
        bucket.sort(key=key, reverse=reverse)

    def walk(parent_id: str | None, depth: int) -> list[dict[str, Any]]:
        nodes = []
        for comment in by_parent.get(parent_id, []):
            node = public_comment(comment, user, vote_map=vote_map)
            node["replies"] = walk(comment["_id"], depth + 1) if depth < max_depth else []
            node["hidden_replies"] = (
                len(by_parent.get(comment["_id"], [])) if depth >= max_depth else 0
            )
            nodes.append(node)
        return nodes

    return walk(None, 0)


def render_tree_for_prompt(post_id: str, *, limit: int = 60, max_chars: int = 6000) -> str:
    """Indented transcript with stable ids, fed back into the comment prompt."""
    comments = for_post(post_id)
    if not comments:
        return ""

    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for comment in comments:
        by_parent.setdefault(comment.get("parent_id"), []).append(comment)
    for bucket in by_parent.values():
        bucket.sort(key=lambda c: c.get("score", 0), reverse=True)

    lines: list[str] = []

    def walk(parent_id: str | None, depth: int) -> None:
        for comment in by_parent.get(parent_id, []):
            if len(lines) >= limit:
                return
            indent = "  " * depth
            body = comment.get("body", "")
            if comment.get("removed"):
                body = "[removed by moderator]"
            elif comment.get("deleted_by_author"):
                body = "[deleted]"
            body = body.replace("\n", " ")[:280]
            marker = " (OP)" if comment.get("is_op") else ""
            lines.append(
                f"{indent}[c{comment['_id']}] {comment.get('author')}{marker} "
                f"({comment.get('score', 0)} pts): {body}"
            )
            walk(comment["_id"], depth + 1)

    walk(None, 0)
    rendered = "\n".join(lines)
    return rendered[:max_chars]


def public_comment(
    comment: dict[str, Any],
    user: dict[str, Any] | None = None,
    *,
    vote_map: dict[str, int] | None = None,
    include_internal: bool = False,
) -> dict[str, Any]:
    removed = bool(comment.get("removed"))
    deleted = bool(comment.get("deleted_by_author"))
    body = comment.get("body", "")
    if removed:
        body = REMOVED_BODY
    elif deleted:
        body = DELETED_BODY

    payload: dict[str, Any] = {
        "id": comment["_id"],
        "post_id": comment.get("post_id"),
        "parent_id": comment.get("parent_id"),
        "subreddit": comment.get("subreddit"),
        "body": body,
        "author": comment.get("author"),
        "author_id": comment.get("author_id"),
        "author_badge": post_service.author_badge(comment),
        "depth": comment.get("depth", 0),
        "score": comment.get("score", 0),
        "ups": comment.get("ups", 0),
        "downs": comment.get("downs", 0),
        "awards": award_service.awards_for("comment", comment["_id"]),
        "award_total": comment.get("award_total", 0),
        "removed": removed,
        "removal_reason": comment.get("removal_reason", "") if removed else "",
        "removed_by": comment.get("removed_by") if removed else None,
        "deleted_by_author": deleted,
        "edited": comment.get("edited", False),
        "is_op": comment.get("is_op", False),
        "tone": comment.get("tone", ""),
        "created_at": comment.get("created_at"),
        "age_label": post_service.age_label(comment.get("created_at", now())),
        "user_vote": 0,
        "is_own": bool(user and comment.get("author_id") == user.get("_id")),
        "replies": [],
        "hidden_replies": 0,
    }

    if user:
        if vote_map is not None:
            payload["user_vote"] = vote_map.get(comment["_id"], 0)
        else:
            payload["user_vote"] = vote_service.get_vote(user["_id"], "comment", comment["_id"])

    if include_internal:
        payload["quality"] = comment.get("quality")
        payload["controversy"] = comment.get("controversy")
        payload["original_body"] = comment.get("original_body")
        payload["author_kind"] = comment.get("author_kind")

    return payload


def user_comments(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    comments = _comments().find({"author_id": user_id}, sort=[("created_at", -1)], limit=limit)
    return comments


def by_author_name(author: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return _comments().find({"author": author}, sort=[("created_at", -1)], limit=limit)


def ancestors(comment_id: str) -> list[dict[str, Any]]:
    """Walk up to the root, oldest first — used for reply context in prompts."""
    chain: list[dict[str, Any]] = []
    current = get(comment_id)
    seen: set[str] = set()
    while current and current["_id"] not in seen:
        seen.add(current["_id"])
        chain.append(current)
        parent_id = current.get("parent_id")
        current = get(parent_id) if parent_id else None
    return list(reversed(chain))
