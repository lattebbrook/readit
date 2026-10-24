"""Database bootstrap: a single process-wide :class:`MemoryDB` with indexes."""

from __future__ import annotations

from app.config import settings
from app.db.memdb import Collection, Document, MemoryDB, new_id, now

# Every collection the app uses, with the fields worth indexing for equality lookups.
COLLECTION_INDEXES: dict[str, list[str]] = {
    "users": ["email", "username_lower", "is_guest"],
    "sessions": ["token", "user_id"],
    "subreddits": ["name_lower", "created_by", "is_nsfw"],
    "posts": ["subreddit", "author_id", "author_kind", "removed", "media_id"],
    "media": ["sha256", "added_by", "analysis_state"],
    "comments": ["post_id", "parent_id", "author_id", "author_kind"],
    "votes": ["target_id", "user_id", "target_kind"],
    "award_grants": ["target_id", "target_kind", "giver_id"],
    "personas": ["username_lower", "home_subreddit"],
    "notifications": ["user_id", "read"],
    "moderation_log": ["subreddit", "target_id"],
    "activity": ["subreddit", "post_id", "kind"],
    "config": ["key"],
}


def _build_db() -> MemoryDB:
    database = MemoryDB(snapshot_path=settings.effective_snapshot_path)
    for name, fields in COLLECTION_INDEXES.items():
        collection = database.collection(name)
        for field in fields:
            collection.create_index(field)
    return database


db: MemoryDB = _build_db()


def reset_db() -> MemoryDB:
    """Wipe every collection. Used by tests and by the admin "reset world" action."""
    db.drop_all()
    return db


def get_db() -> MemoryDB:
    return db


__all__ = [
    "Collection",
    "Document",
    "MemoryDB",
    "COLLECTION_INDEXES",
    "db",
    "get_db",
    "new_id",
    "now",
    "reset_db",
]
