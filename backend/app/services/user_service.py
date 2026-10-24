"""Accounts, sessions, profiles, preferences, and the account-wipe action."""

from __future__ import annotations

import random
import re
import secrets
from typing import Any

from app.config import settings
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.db import db, now

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

AVATAR_COLORS = [
    "#ff4500", "#0079d3", "#46d160", "#ffb000", "#ff66ac",
    "#7193ff", "#ea0027", "#00a6a5", "#9f7aea", "#ff8717",
]

DEFAULT_PREFERENCES: dict[str, Any] = {
    "theme": "dark",
    "compact_mode": False,
    "feed_sort": "hot",
    "show_nsfw": False,
    "blur_nsfw": True,
    "live_updates": True,
    "auto_generate_on_open": True,
    "comment_density_override": None,  # None → use the board/world setting
    "content_intensity": None,         # None → use world toxicity
    "humor_override": None,
    "hide_removed": False,
    "show_human_badges": True,
    "open_links_in_new_tab": True,
    "notification_replies": True,
    "language_style": "",              # free text, e.g. "keep it British"
    "content_font_size": 13,           # px, applied to post/comment bodies
    "content_font_family": "",         # empty → site default; free text otherwise
}

DEFAULT_KARMA = {"post": 1, "comment": 1, "awarder": 0}


class UserError(ValueError):
    """User-facing validation failure (mapped to HTTP 400/409 by the API layer)."""


def _users():
    return db.collection("users")


def _sessions():
    return db.collection("sessions")


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #

def get_user(user_id: str) -> dict[str, Any] | None:
    return _users().get(user_id)


def get_by_username(username: str) -> dict[str, Any] | None:
    return _users().find_one({"username_lower": username.lower()})


def get_by_email(email: str) -> dict[str, Any] | None:
    return _users().find_one({"email": email.lower().strip()})


def username_available(username: str) -> bool:
    return get_by_username(username) is None


def _unique_username(base: str) -> str:
    candidate = base
    while not username_available(candidate):
        candidate = f"{base}_{secrets.token_hex(2)}"
    return candidate


# --------------------------------------------------------------------------- #
# Registration and login
# --------------------------------------------------------------------------- #

def _new_user_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "email": None,
        "username": "",
        "username_lower": "",
        "password_hash": None,
        "is_guest": False,
        "is_admin": False,
        "kind": "human",
        "display_name": "",
        "bio": "",
        "avatar_color": random.choice(AVATAR_COLORS),
        "avatar_emoji": random.choice(["🦊", "🐙", "🦉", "🐸", "🦝", "🐝", "🦑", "🐢", "🦋", "🐧"]),
        "banner_color": "#1a1a1b",
        "karma": dict(DEFAULT_KARMA),
        "coins": 500,
        "subscriptions": [],
        "interests": [],
        "banned_subreddits": [],
        "saved_posts": [],
        "preferences": dict(DEFAULT_PREFERENCES),
        "personal_prompt": "",
        "awards_received": {},
        "created_at": now(),
        "last_seen": now(),
        "wiped_at": None,
    }
    doc.update(overrides)
    return doc


def register(email: str, password: str, username: str) -> dict[str, Any]:
    email = (email or "").lower().strip()
    username = (username or "").strip()

    if not EMAIL_RE.match(email):
        raise UserError("That email address doesn't look right.")
    if not USERNAME_RE.match(username):
        raise UserError("Usernames are 3-20 characters: letters, numbers, _ and - only.")
    if len(password or "") < 6:
        raise UserError("Password must be at least 6 characters.")
    if get_by_email(email):
        raise UserError("An account with that email already exists.")
    if not username_available(username):
        raise UserError("That username is taken.")

    is_admin = email == settings.admin_email.lower().strip()
    return _users().insert(
        _new_user_doc(
            email=email,
            username=username,
            username_lower=username.lower(),
            password_hash=hash_password(password),
            display_name=username,
            is_admin=is_admin,
        )
    )


def login(email: str, password: str) -> dict[str, Any]:
    user = get_by_email(email or "")
    if not user or not verify_password(password or "", user.get("password_hash")):
        raise UserError("Wrong email or password.")
    _users().update(user["_id"], {"$set": {"last_seen": now()}})
    return user


def create_guest(display_hint: str = "") -> dict[str, Any]:
    """Guests are real accounts with no email — they can vote, post and comment."""
    base = re.sub(r"[^A-Za-z0-9_-]", "", display_hint)[:12] or "guest"
    username = _unique_username(f"{base}_{secrets.token_hex(3)}")
    return _users().insert(
        _new_user_doc(
            username=username,
            username_lower=username.lower(),
            display_name=username,
            is_guest=True,
            coins=100,
        )
    )


def promote_guest(user_id: str, email: str, password: str, username: str) -> dict[str, Any]:
    """Convert a guest into a full account, keeping their karma and history."""
    user = get_user(user_id)
    if not user:
        raise UserError("Account not found.")
    if not user.get("is_guest"):
        raise UserError("This account is already registered.")

    email = (email or "").lower().strip()
    username = (username or "").strip()
    if not EMAIL_RE.match(email):
        raise UserError("That email address doesn't look right.")
    if get_by_email(email):
        raise UserError("An account with that email already exists.")
    if not USERNAME_RE.match(username):
        raise UserError("Usernames are 3-20 characters: letters, numbers, _ and - only.")
    existing = get_by_username(username)
    if existing and existing["_id"] != user_id:
        raise UserError("That username is taken.")
    if len(password or "") < 6:
        raise UserError("Password must be at least 6 characters.")

    old_username = user["username"]
    updated = _users().update(
        user_id,
        {
            "$set": {
                "email": email,
                "username": username,
                "username_lower": username.lower(),
                "display_name": username,
                "password_hash": hash_password(password),
                "is_guest": False,
                "is_admin": email == settings.admin_email.lower().strip(),
            }
        },
    )
    if updated and old_username != username:
        _rename_authored_content(user_id, username)
    return updated or user


def _rename_authored_content(user_id: str, username: str) -> None:
    for collection in ("posts", "comments"):
        db.collection(collection).update_many({"author_id": user_id}, {"$set": {"author": username}})


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #

def start_session(user_id: str) -> str:
    token = create_token(user_id)
    _sessions().insert(
        {
            "token": token,
            "user_id": user_id,
            "created_at": now(),
            "expires_at": now() + settings.token_ttl_seconds,
        }
    )
    return token


def resolve_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    session = _sessions().find_one({"token": token})
    if session is None:
        return None
    user = get_user(payload["sub"])
    if user:
        _users().update(user["_id"], {"$set": {"last_seen": now()}})
    return user


def end_session(token: str) -> bool:
    session = _sessions().find_one({"token": token})
    if not session:
        return False
    return _sessions().delete(session["_id"])


def end_all_sessions(user_id: str) -> int:
    return _sessions().delete_many({"user_id": user_id})


# --------------------------------------------------------------------------- #
# Profile and preferences
# --------------------------------------------------------------------------- #

PROFILE_FIELDS = {"display_name", "bio", "avatar_color", "avatar_emoji", "banner_color", "personal_prompt"}


def update_profile(user_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {key: value for key, value in changes.items() if key in PROFILE_FIELDS}
    if "bio" in allowed:
        allowed["bio"] = str(allowed["bio"])[:500]
    if "display_name" in allowed:
        allowed["display_name"] = str(allowed["display_name"])[:40]
    if not allowed:
        return get_user(user_id)
    return _users().update(user_id, {"$set": allowed})


def update_preferences(user_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    user = get_user(user_id)
    if not user:
        return None
    preferences = {**DEFAULT_PREFERENCES, **(user.get("preferences") or {})}
    for key, value in changes.items():
        if key in DEFAULT_PREFERENCES:
            preferences[key] = value
    return _users().update(user_id, {"$set": {"preferences": preferences}})


def set_interests(user_id: str, interests: list[str]) -> dict[str, Any] | None:
    cleaned = [str(item).strip()[:60] for item in interests if str(item).strip()][:40]
    return _users().update(user_id, {"$set": {"interests": cleaned}})


def subscribe(user_id: str, subreddit: str) -> dict[str, Any] | None:
    return _users().update(user_id, {"$addToSet": {"subscriptions": subreddit}})


def unsubscribe(user_id: str, subreddit: str) -> dict[str, Any] | None:
    return _users().update(user_id, {"$pull": {"subscriptions": subreddit}})


def ban_subreddit(user_id: str, subreddit: str) -> dict[str, Any] | None:
    """Personal block: the board disappears from this user's feeds."""
    _users().update(user_id, {"$pull": {"subscriptions": subreddit}})
    return _users().update(user_id, {"$addToSet": {"banned_subreddits": subreddit}})


def unban_subreddit(user_id: str, subreddit: str) -> dict[str, Any] | None:
    return _users().update(user_id, {"$pull": {"banned_subreddits": subreddit}})


def save_post(user_id: str, post_id: str) -> dict[str, Any] | None:
    return _users().update(user_id, {"$addToSet": {"saved_posts": post_id}})


def unsave_post(user_id: str, post_id: str) -> dict[str, Any] | None:
    return _users().update(user_id, {"$pull": {"saved_posts": post_id}})


def add_karma(user_id: str, kind: str, amount: int) -> None:
    if not user_id or amount == 0:
        return
    field = "karma.post" if kind == "post" else "karma.comment"
    _users().update(user_id, {"$inc": {field: amount}})


def adjust_coins(user_id: str, amount: int) -> dict[str, Any] | None:
    user = get_user(user_id)
    if not user:
        return None
    balance = max(0, user.get("coins", 0) + amount)
    return _users().update(user_id, {"$set": {"coins": balance}})


# --------------------------------------------------------------------------- #
# Data export and wipe
# --------------------------------------------------------------------------- #

def export_profile(user_id: str) -> dict[str, Any]:
    """Everything tied to this account, for the settings "download my data" button."""
    user = get_user(user_id)
    if not user:
        raise UserError("Account not found.")
    safe_user = {k: v for k, v in user.items() if k != "password_hash"}
    return {
        "user": safe_user,
        "posts": db.collection("posts").find({"author_id": user_id}),
        "comments": db.collection("comments").find({"author_id": user_id}),
        "votes": db.collection("votes").find({"user_id": user_id}),
        "subreddits_created": db.collection("subreddits").find({"created_by": user_id}),
        "awards_given": db.collection("award_grants").find({"giver_id": user_id}),
        "exported_at": now(),
    }


def wipe_content(user_id: str, *, delete_account: bool = False) -> dict[str, Any]:
    """Reddit-style wipe: content becomes a tombstone rather than vanishing.

    Posts and comments stay in place so threads keep their shape, but the body is
    replaced with the italic "removed" stub and authorship is anonymised.
    """
    user = get_user(user_id)
    if not user:
        raise UserError("Account not found.")

    posts = db.collection("posts")
    comments = db.collection("comments")

    post_ids = [doc["_id"] for doc in posts.find({"author_id": user_id})]
    for post_id in post_ids:
        posts.update(
            post_id,
            {
                "$set": {
                    "title": "[deleted by user]",
                    "body": "[removed]",
                    "deleted_by_author": True,
                    "author": "[deleted]",
                    "author_kind": "deleted",
                    "link_url": "",
                }
            },
        )

    comment_ids = [doc["_id"] for doc in comments.find({"author_id": user_id})]
    for comment_id in comment_ids:
        comments.update(
            comment_id,
            {
                "$set": {
                    "body": "[removed]",
                    "deleted_by_author": True,
                    "author": "[deleted]",
                    "author_kind": "deleted",
                }
            },
        )

    db.collection("votes").delete_many({"user_id": user_id})
    db.collection("notifications").delete_many({"user_id": user_id})

    summary = {
        "posts_wiped": len(post_ids),
        "comments_wiped": len(comment_ids),
        "account_deleted": delete_account,
    }

    if delete_account:
        end_all_sessions(user_id)
        _users().delete(user_id)
    else:
        _users().update(
            user_id,
            {
                "$set": {
                    "wiped_at": now(),
                    "karma": dict(DEFAULT_KARMA),
                    "subscriptions": [],
                    "interests": [],
                    "awards_received": {},
                }
            },
        )
    return summary


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #

def public_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    """Profile view safe for any viewer."""
    if not user:
        return None
    return {
        "id": user["_id"],
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("username"),
        "bio": user.get("bio", ""),
        "avatar_color": user.get("avatar_color"),
        "avatar_emoji": user.get("avatar_emoji"),
        "banner_color": user.get("banner_color"),
        "karma": user.get("karma", dict(DEFAULT_KARMA)),
        "is_guest": user.get("is_guest", False),
        "is_admin": user.get("is_admin", False),
        "kind": "human",
        "created_at": user.get("created_at"),
        "awards_received": user.get("awards_received", {}),
    }


def private_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    """Everything the signed-in user needs about themselves."""
    if not user:
        return None
    payload = public_user(user) or {}
    payload.update(
        {
            "email": user.get("email"),
            "coins": user.get("coins", 0),
            "subscriptions": user.get("subscriptions", []),
            "interests": user.get("interests", []),
            "banned_subreddits": user.get("banned_subreddits", []),
            "saved_posts": user.get("saved_posts", []),
            "preferences": {**DEFAULT_PREFERENCES, **(user.get("preferences") or {})},
            "personal_prompt": user.get("personal_prompt", ""),
            "wiped_at": user.get("wiped_at"),
        }
    )
    return payload
