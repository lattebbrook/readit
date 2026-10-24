"""Inbox: replies, mentions, awards and moderator actions aimed at a real user."""

from __future__ import annotations

from typing import Any

from app.db import db, now

KINDS = {"post_reply", "comment_reply", "award", "mention", "mod_action", "system"}


def _notifications():
    return db.collection("notifications")


def push(
    user_id: str,
    kind: str,
    *,
    title: str,
    body: str = "",
    subreddit: str = "",
    post_id: str | None = None,
    comment_id: str | None = None,
    actor: str = "",
) -> dict[str, Any] | None:
    if not user_id or kind not in KINDS:
        return None
    return _notifications().insert(
        {
            "user_id": user_id,
            "kind": kind,
            "title": title[:200],
            "body": body[:600],
            "subreddit": subreddit,
            "post_id": post_id,
            "comment_id": comment_id,
            "actor": actor,
            "read": False,
            "at": now(),
        }
    )


def notify_reply(comment: dict[str, Any], parent: dict[str, Any] | None, post: dict[str, Any]) -> None:
    """Tell a human they got a reply, whether on their post or their comment."""
    if parent:
        if parent.get("author_kind") != "human" or not parent.get("author_id"):
            return
        if parent.get("author_id") == comment.get("author_id"):
            return
        push(
            parent["author_id"],
            "comment_reply",
            title=f"{comment.get('author')} replied to your comment",
            body=(comment.get("body") or "")[:300],
            subreddit=post.get("subreddit", ""),
            post_id=post["_id"],
            comment_id=comment["_id"],
            actor=comment.get("author", ""),
        )
        return

    if post.get("author_kind") != "human" or not post.get("author_id"):
        return
    if post.get("author_id") == comment.get("author_id"):
        return
    push(
        post["author_id"],
        "post_reply",
        title=f"{comment.get('author')} commented on {post.get('title', '')[:60]}",
        body=(comment.get("body") or "")[:300],
        subreddit=post.get("subreddit", ""),
        post_id=post["_id"],
        comment_id=comment["_id"],
        actor=comment.get("author", ""),
    )


def notify_award(target: dict[str, Any], award: dict[str, Any], giver: str | None) -> None:
    if target.get("author_kind") != "human" or not target.get("author_id"):
        return
    push(
        target["author_id"],
        "award",
        title=f"You received {award['name']} {award['icon']}",
        body=f"from {giver or 'an anonymous redditor'}",
        subreddit=target.get("subreddit", ""),
        post_id=target.get("post_id") or target.get("_id"),
        comment_id=target["_id"] if target.get("post_id") else None,
        actor=giver or "",
    )


def notify_mod_action(target: dict[str, Any], reason: str, moderator: str) -> None:
    if target.get("author_kind") != "human" or not target.get("author_id"):
        return
    push(
        target["author_id"],
        "mod_action",
        title="Your comment was removed",
        body=reason or "Removed by moderators",
        subreddit=target.get("subreddit", ""),
        post_id=target.get("post_id") or target.get("_id"),
        actor=moderator,
    )


def list_for(user_id: str, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"user_id": user_id}
    if unread_only:
        query["read"] = False
    return _notifications().find(query, sort=[("at", -1)], limit=limit)


def unread_count(user_id: str) -> int:
    return _notifications().count({"user_id": user_id, "read": False})


def mark_read(notification_id: str) -> dict[str, Any] | None:
    return _notifications().update(notification_id, {"$set": {"read": True}})


def mark_all_read(user_id: str) -> int:
    return _notifications().update_many({"user_id": user_id, "read": False}, {"$set": {"read": True}})


def clear(user_id: str) -> int:
    return _notifications().delete_many({"user_id": user_id})
