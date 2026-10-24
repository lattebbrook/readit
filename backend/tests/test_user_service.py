"""Unit tests for accounts, sessions, preferences and the wipe action."""

from __future__ import annotations

import pytest

from app.db import db
from app.services import comment_service, post_service, user_service


def test_register_creates_usable_account():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    assert user["email"] == "sam@example.com"
    assert user["username_lower"] == "samwise"
    assert user["password_hash"]
    assert user["is_guest"] is False
    assert user["coins"] > 0


def test_register_normalises_email_case():
    user_service.register("Sam@Example.COM", "hunter22", "samwise")
    assert user_service.get_by_email("sam@example.com") is not None


@pytest.mark.parametrize(
    "email,password,username,message",
    [
        ("not-an-email", "hunter22", "sam", "email"),
        ("a@b.com", "short", "sam", "6 characters"),
        ("a@b.com", "hunter22", "x", "3-20"),
        ("a@b.com", "hunter22", "has spaces", "3-20"),
    ],
)
def test_register_validation(email, password, username, message):
    with pytest.raises(user_service.UserError, match=message):
        user_service.register(email, password, username)


def test_register_rejects_duplicates():
    user_service.register("sam@example.com", "hunter22", "samwise")
    with pytest.raises(user_service.UserError, match="already exists"):
        user_service.register("sam@example.com", "hunter22", "other")
    with pytest.raises(user_service.UserError, match="taken"):
        user_service.register("other@example.com", "hunter22", "SamWise")


def test_bootstrap_admin_email_gets_admin_flag():
    from app.config import settings

    user = user_service.register(settings.admin_email, "hunter22", "theboss")
    assert user["is_admin"] is True


def test_login_round_trip():
    user_service.register("sam@example.com", "hunter22", "samwise")
    assert user_service.login("sam@example.com", "hunter22")["username"] == "samwise"
    with pytest.raises(user_service.UserError):
        user_service.login("sam@example.com", "wrong")
    with pytest.raises(user_service.UserError):
        user_service.login("nobody@example.com", "hunter22")


def test_guest_accounts_are_unique_and_usable():
    first = user_service.create_guest("tester")
    second = user_service.create_guest("tester")
    assert first["is_guest"] and second["is_guest"]
    assert first["username"] != second["username"]
    assert first["email"] is None


def test_guest_username_strips_unsafe_characters():
    guest = user_service.create_guest("hi there!! <b>")
    assert user_service.USERNAME_RE.match(guest["username"])


def test_promote_guest_keeps_history(board):
    guest = user_service.create_guest("tester")
    post = post_service.create(
        subreddit=board["name"],
        title="my post",
        author=guest["username"],
        author_id=guest["_id"],
    )
    upgraded = user_service.promote_guest(guest["_id"], "sam@example.com", "hunter22", "samwise")

    assert upgraded["is_guest"] is False
    assert upgraded["username"] == "samwise"
    assert upgraded["_id"] == guest["_id"]
    # The byline follows the rename so old content is still attributed.
    assert post_service.get(post["_id"])["author"] == "samwise"


def test_promote_guest_rejects_taken_username():
    user_service.register("taken@example.com", "hunter22", "samwise")
    guest = user_service.create_guest()
    with pytest.raises(user_service.UserError, match="taken"):
        user_service.promote_guest(guest["_id"], "new@example.com", "hunter22", "samwise")


def test_promote_rejects_non_guest():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    with pytest.raises(user_service.UserError, match="already registered"):
        user_service.promote_guest(user["_id"], "x@y.com", "hunter22", "other")


def test_session_lifecycle():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    token = user_service.start_session(user["_id"])
    assert user_service.resolve_token(token)["_id"] == user["_id"]
    assert user_service.end_session(token) is True
    assert user_service.resolve_token(token) is None


def test_resolve_token_rejects_unknown_and_revoked():
    assert user_service.resolve_token(None) is None
    assert user_service.resolve_token("garbage") is None


def test_end_all_sessions():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    tokens = [user_service.start_session(user["_id"]) for _ in range(3)]
    assert user_service.end_all_sessions(user["_id"]) == 3
    assert all(user_service.resolve_token(token) is None for token in tokens)


def test_update_profile_only_touches_allowed_fields():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    updated = user_service.update_profile(
        user["_id"], {"bio": "hello", "is_admin": True, "coins": 999_999}
    )
    assert updated["bio"] == "hello"
    assert updated["is_admin"] is False
    assert updated["coins"] == user["coins"]


def test_update_profile_truncates_long_values():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    updated = user_service.update_profile(user["_id"], {"bio": "x" * 900})
    assert len(updated["bio"]) == 500


def test_update_preferences_ignores_unknown_keys():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    updated = user_service.update_preferences(
        user["_id"], {"theme": "light", "not_a_preference": 1}
    )
    assert updated["preferences"]["theme"] == "light"
    assert "not_a_preference" not in updated["preferences"]


def test_subscriptions_are_a_set():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], "funny")
    updated = user_service.subscribe(user["_id"], "funny")
    assert updated["subscriptions"] == ["funny"]
    assert user_service.unsubscribe(user["_id"], "funny")["subscriptions"] == []


def test_blocking_a_board_also_unsubscribes():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], "funny")
    updated = user_service.ban_subreddit(user["_id"], "funny")
    assert updated["banned_subreddits"] == ["funny"]
    assert updated["subscriptions"] == []


def test_save_and_unsave_post_is_idempotent_and_a_set():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.save_post(user["_id"], "p1")
    twice = user_service.save_post(user["_id"], "p1")
    assert twice["saved_posts"] == ["p1"]
    unsaved = user_service.unsave_post(user["_id"], "p1")
    assert unsaved["saved_posts"] == []


def test_karma_and_coins_adjustments():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.add_karma(user["_id"], "post", 12)
    user_service.add_karma(user["_id"], "comment", -3)
    refreshed = user_service.get_user(user["_id"])
    assert refreshed["karma"]["post"] == 13
    assert refreshed["karma"]["comment"] == -2

    user_service.adjust_coins(user["_id"], -10_000)
    assert user_service.get_user(user["_id"])["coins"] == 0  # never goes negative


def test_export_profile_excludes_password_hash(board):
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    post_service.create(
        subreddit=board["name"], title="t", author=user["username"], author_id=user["_id"]
    )
    export = user_service.export_profile(user["_id"])
    assert "password_hash" not in export["user"]
    assert len(export["posts"]) == 1


def test_wipe_tombstones_content_but_keeps_the_thread(board):
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    post = post_service.create(
        subreddit=board["name"], title="my thoughts", author="samwise", author_id=user["_id"]
    )
    mine = comment_service.create(
        post_id=post["_id"], body="I said this", author="samwise", author_id=user["_id"]
    )
    theirs = comment_service.create(
        post_id=post["_id"],
        parent_id=mine["_id"],
        body="a reply that must survive",
        author="SomePersona",
        author_kind="ai",
    )

    summary = user_service.wipe_content(user["_id"])

    assert summary == {"posts_wiped": 1, "comments_wiped": 1, "account_deleted": False}
    wiped_post = post_service.get(post["_id"])
    assert wiped_post["body"] == "[removed]"
    assert wiped_post["author"] == "[deleted]"
    assert wiped_post["deleted_by_author"] is True

    wiped_comment = comment_service.get(mine["_id"])
    assert wiped_comment["body"] == "[removed]"

    # The reply underneath is untouched, so the conversation still reads.
    assert comment_service.get(theirs["_id"])["body"] == "a reply that must survive"

    account = user_service.get_user(user["_id"])
    assert account["wiped_at"] is not None
    assert account["karma"]["post"] == 1


def test_wipe_can_delete_the_account_entirely():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    token = user_service.start_session(user["_id"])
    summary = user_service.wipe_content(user["_id"], delete_account=True)
    assert summary["account_deleted"] is True
    assert user_service.get_user(user["_id"]) is None
    assert user_service.resolve_token(token) is None


def test_wipe_clears_votes_and_notifications(board):
    from app.services import notification_service, vote_service

    user = user_service.register("sam@example.com", "hunter22", "samwise")
    post = post_service.create(subreddit=board["name"], title="t", author="Persona", author_kind="ai")
    vote_service.cast_vote(user["_id"], "post", post["_id"], 1)
    notification_service.push(user["_id"], "system", title="hello")

    user_service.wipe_content(user["_id"])
    assert db.collection("votes").count({"user_id": user["_id"]}) == 0
    assert notification_service.unread_count(user["_id"]) == 0


def test_wipe_unknown_account_raises():
    with pytest.raises(user_service.UserError):
        user_service.wipe_content("nope")


def test_public_user_hides_private_fields():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    public = user_service.public_user(user)
    assert "email" not in public
    assert "preferences" not in public
    assert public["kind"] == "human"


def test_private_user_includes_settings():
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    private = user_service.private_user(user)
    assert private["email"] == "sam@example.com"
    assert "theme" in private["preferences"]
    assert private["preferences"]["live_updates"] is True


def test_public_user_of_none_is_none():
    assert user_service.public_user(None) is None
    assert user_service.private_user(None) is None
