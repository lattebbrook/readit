"""End-to-end tests for the HTTP API."""

from __future__ import annotations

import pytest

from app.db import db, now
from app.services import (
    comment_service,
    config_service,
    post_service,
    subreddit_service,
    user_service,
)


@pytest.fixture
def guest_headers(client):
    response = client.post("/api/auth/guest", json={"display_hint": "tester"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def user_headers(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "sam@example.com", "password": "hunter22", "username": "samwise"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def admin_headers(client):
    from app.config import settings

    response = client.post(
        "/api/auth/register",
        json={"email": settings.admin_email, "password": "hunter22", "username": "theboss"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["is_admin"] is True
    return {"Authorization": f"Bearer {response.json()['token']}"}


# --------------------------------------------------------------------------- #
# Health and site
# --------------------------------------------------------------------------- #

def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_site_info_for_anonymous(client):
    payload = client.get("/api/site").json()
    assert payload["name"] == "ReadIt"
    assert payload["user"] is None
    assert payload["is_admin"] is False
    assert payload["llm_ready"] is False


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def test_register_login_logout(client):
    registered = client.post(
        "/api/auth/register",
        json={"email": "sam@example.com", "password": "hunter22", "username": "samwise"},
    )
    assert registered.status_code == 200
    token = registered.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=headers).json()["authenticated"] is True
    assert client.post("/api/auth/logout", headers=headers).json()["ok"] is True
    assert client.get("/api/auth/me", headers=headers).json()["authenticated"] is False

    assert (
        client.post("/api/auth/login", json={"email": "sam@example.com", "password": "hunter22"}).status_code
        == 200
    )


def test_register_rejects_bad_input(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "nope", "password": "hunter22", "username": "samwise"},
    )
    assert response.status_code == 400
    assert "email" in response.json()["detail"]


def test_login_with_wrong_password_is_401(client):
    client.post(
        "/api/auth/register",
        json={"email": "sam@example.com", "password": "hunter22", "username": "samwise"},
    )
    response = client.post("/api/auth/login", json={"email": "sam@example.com", "password": "x"})
    assert response.status_code == 401


def test_guest_session_works_immediately(client, guest_headers):
    payload = client.get("/api/auth/me", headers=guest_headers).json()
    assert payload["user"]["is_guest"] is True
    assert payload["user"]["coins"] > 0


def test_guest_can_be_promoted(client, guest_headers):
    response = client.post(
        "/api/auth/promote",
        headers=guest_headers,
        json={"email": "sam@example.com", "password": "hunter22", "username": "samwise"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["is_guest"] is False
    assert response.json()["user"]["username"] == "samwise"


def test_username_availability(client, user_headers):
    assert client.get("/api/auth/username-available?username=samwise").json()["available"] is False
    assert client.get("/api/auth/username-available?username=freename").json()["available"] is True
    assert client.get("/api/auth/username-available?username=x").json()["available"] is False


def test_token_is_required_for_write_endpoints(client, board):
    assert client.post("/api/boards", json={"name": "newboard"}).status_code == 401
    assert client.post("/api/vote/post/whatever", json={"direction": 1}).status_code == 401


def test_malformed_token_is_treated_as_anonymous(client):
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/api/auth/me", headers=headers).json()["authenticated"] is False


# --------------------------------------------------------------------------- #
# Boards
# --------------------------------------------------------------------------- #

def test_list_and_get_board(client, board):
    listing = client.get("/api/boards").json()["boards"]
    assert [entry["name"] for entry in listing] == [board["name"]]

    payload = client.get(f"/api/boards/{board['name']}").json()["board"]
    assert payload["name"] == board["name"]
    assert payload["members_online"] >= 1
    assert "custom_prompt" not in payload  # hidden from non-owners


def test_get_missing_board_is_404(client):
    assert client.get("/api/boards/nosuchboard").status_code == 404


def test_create_board_with_custom_prompt(client, user_headers):
    response = client.post(
        "/api/boards",
        headers=user_headers,
        json={
            "name": "medieval",
            "description": "peasants react to modern life",
            "custom_prompt": "Everyone is a medieval peasant. Nobody breaks character.",
            "override_global": True,
            "autofill": False,
            "generate_metadata": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()["board"]
    assert payload["custom_prompt"].startswith("Everyone is a medieval peasant")
    assert payload["override_global"] is True
    assert payload["can_edit"] is True
    # The creator is subscribed automatically.
    assert "medieval" in client.get("/api/auth/me", headers=user_headers).json()["user"]["subscriptions"]


def test_create_board_rejects_duplicate_name(client, user_headers, board):
    response = client.post(
        "/api/boards",
        headers=user_headers,
        json={"name": board["name"], "autofill": False, "generate_metadata": False},
    )
    assert response.status_code == 400


def test_only_the_creator_can_edit_a_board(client, user_headers, board):
    created = client.post(
        "/api/boards",
        headers=user_headers,
        json={"name": "mine", "autofill": False, "generate_metadata": False},
    ).json()["board"]

    assert client.patch(f"/api/boards/{created['name']}", headers=user_headers,
                        json={"description": "updated"}).status_code == 200

    other = client.post("/api/auth/guest", json={}).json()
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    assert client.patch(f"/api/boards/{created['name']}", headers=other_headers,
                        json={"description": "hijacked"}).status_code == 403
    assert client.delete(f"/api/boards/{created['name']}", headers=other_headers).status_code == 403


def test_anyone_can_set_a_private_prompt_on_someone_elses_board(client, guest_headers, board):
    response = client.put(
        f"/api/boards/{board['name']}/personal-prompt",
        headers=guest_headers,
        json={"prompt": "lean technical"},
    )
    assert response.status_code == 200
    assert response.json()["prompt"] == "lean technical"

    payload = client.get(f"/api/boards/{board['name']}", headers=guest_headers).json()["board"]
    assert payload["personal_prompt"] == "lean technical"


def test_blocked_board_is_hidden_and_forbidden(client, guest_headers, board):
    client.post(f"/api/me/blocked-boards/{board['name']}", headers=guest_headers)
    assert client.get("/api/boards", headers=guest_headers).json()["boards"] == []
    assert client.get(f"/api/boards/{board['name']}", headers=guest_headers).status_code == 403


def test_subscribe_and_unsubscribe(client, guest_headers, board):
    subscribed = client.post(f"/api/me/subscriptions/{board['name']}", headers=guest_headers).json()
    assert board["name"] in subscribed["user"]["subscriptions"]
    unsubscribed = client.delete(f"/api/me/subscriptions/{board['name']}", headers=guest_headers).json()
    assert unsubscribed["user"]["subscriptions"] == []


def test_save_and_unsave_a_post(client, guest_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")

    saved = client.post(f"/api/me/saved/{post['_id']}", headers=guest_headers).json()
    assert saved["saved"] is True
    assert post["_id"] in saved["user"]["saved_posts"]

    listed = client.get("/api/me/saved", headers=guest_headers).json()
    assert listed["posts"][0]["id"] == post["_id"]
    assert listed["posts"][0]["saved"] is True

    unsaved = client.delete(f"/api/me/saved/{post['_id']}", headers=guest_headers).json()
    assert unsaved["saved"] is False
    assert client.get("/api/me/saved", headers=guest_headers).json()["posts"] == []


def test_save_missing_post_is_404(client, guest_headers):
    assert client.post("/api/me/saved/nope", headers=guest_headers).status_code == 404


def test_saved_flag_appears_on_feed_posts(client, guest_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    client.post(f"/api/me/saved/{post['_id']}", headers=guest_headers)
    feed = client.get("/api/feed?scope=popular", headers=guest_headers).json()["posts"]
    assert feed[0]["saved"] is True


def test_recommended_boards_match_interests(client, user_headers):
    subreddit_service.create("woodworking", description="planes chisels and sawdust")
    subreddit_service.create("unrelated", description="nothing to do with it")
    client.put("/api/me/interests", headers=user_headers, json={"interests": ["sawdust"]})

    boards = client.get("/api/boards/recommended", headers=user_headers).json()["boards"]
    assert boards[0]["name"] == "woodworking"


def test_board_posts_endpoint_returns_board_and_posts(client, board):
    post_service.create(subreddit=board["name"], title="hello", author="A", author_kind="ai")
    payload = client.get(f"/api/boards/{board['name']}/posts").json()
    assert payload["board"]["name"] == board["name"]
    assert payload["posts"][0]["title"] == "hello"


def test_generate_posts_endpoint(client, board):
    payload = client.post(f"/api/boards/{board['name']}/generate", json={"count": 3}).json()
    assert payload["posts"]
    assert all(post["subreddit"] == board["name"] for post in payload["posts"])


def test_board_members_carry_no_ai_marker(client, board):
    from app.services import persona_service

    persona_service.create_fallback_personas(5, board["name"])
    members = client.get(f"/api/boards/{board['name']}/members").json()["members"]
    assert members
    assert all("traits" not in member for member in members)


# --------------------------------------------------------------------------- #
# Feed, posts and threads
# --------------------------------------------------------------------------- #

def test_feed_returns_posts(client, board):
    post_service.create(subreddit=board["name"], title="hello", author="A", author_kind="ai")
    payload = client.get("/api/feed?scope=popular").json()
    assert payload["posts"][0]["title"] == "hello"


def test_home_feed_is_limited_to_subscriptions(client, user_headers, board):
    subreddit_service.create("elsewhere")
    post_service.create(subreddit=board["name"], title="subscribed", author="A", author_kind="ai")
    post_service.create(subreddit="elsewhere", title="not subscribed", author="B", author_kind="ai")
    client.post(f"/api/me/subscriptions/{board['name']}", headers=user_headers)

    titles = {p["title"] for p in client.get("/api/feed?scope=home", headers=user_headers).json()["posts"]}
    assert titles == {"subscribed"}


def test_create_post_marks_the_author_as_human(client, user_headers, board):
    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": board["name"], "title": "my first post", "body": "hi",
              "generate_replies": False},
    )
    assert response.status_code == 200
    post = response.json()["post"]
    assert post["author"] == "samwise"
    assert post["author_badge"]["label"] == "human"


def test_create_post_on_missing_board_is_404(client, user_headers):
    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": "nowhere", "title": "t", "generate_replies": False},
    )
    assert response.status_code == 404


def test_create_post_blocked_when_board_disallows_it(client, user_headers, board):
    subreddit_service.update(board["name"], {"allow_user_posts": False})
    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": board["name"], "title": "t", "generate_replies": False},
    )
    assert response.status_code == 403


def test_opening_a_thread_generates_its_discussion(client, board):
    post = post_service.create(subreddit=board["name"], title="Discuss", author="A", author_kind="ai")
    payload = client.get(f"/api/posts/{post['_id']}").json()

    assert payload["generated"] > 0
    assert payload["comments"]
    assert payload["board"]["name"] == board["name"]
    # A second read is served from storage rather than regenerated.
    assert client.get(f"/api/posts/{post['_id']}").json()["generated"] == 0


def test_auto_generation_can_be_switched_off(client, user_headers, board):
    client.patch(
        "/api/me/preferences",
        headers=user_headers,
        json={"preferences": {"auto_generate_on_open": False}},
    )
    post = post_service.create(subreddit=board["name"], title="Quiet", author="A", author_kind="ai")
    payload = client.get(f"/api/posts/{post['_id']}", headers=user_headers).json()
    assert payload["generated"] == 0
    assert payload["comments"] == []


def test_thread_updates_endpoint_reports_new_comments(client, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    checkpoint = now()
    comment_service.create(post_id=post["_id"], body="later", author="B", author_kind="ai")

    payload = client.get(f"/api/posts/{post['_id']}/updates?since={checkpoint}").json()
    assert payload["changed"] is True
    assert payload["new_comments"] == 1
    assert payload["comments"]

    quiet = client.get(f"/api/posts/{post['_id']}/updates?since={now()}").json()
    assert quiet["changed"] is False
    assert "comments" not in quiet


def test_generate_more_comments_endpoint(client, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    payload = client.post(f"/api/posts/{post['_id']}/generate", json={"count": 4}).json()
    assert payload["created"] >= 1
    assert payload["comments"]


def test_commenting_and_replying(client, user_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    created = client.post(
        f"/api/posts/{post['_id']}/comments",
        headers=user_headers,
        json={"body": "my two cents", "generate_replies": False},
    ).json()["comment"]

    assert created["author"] == "samwise"
    assert created["author_badge"]["label"] == "human"

    reply = client.post(
        f"/api/posts/{post['_id']}/comments",
        headers=user_headers,
        json={"body": "adding to myself", "parent_id": created["id"], "generate_replies": False},
    ).json()["comment"]
    assert reply["parent_id"] == created["id"]
    assert reply["depth"] == 1


def test_empty_comment_is_rejected(client, user_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    response = client.post(
        f"/api/posts/{post['_id']}/comments",
        headers=user_headers,
        json={"body": "   ", "generate_replies": False},
    )
    assert response.status_code == 400


def test_editing_and_deleting_own_content(client, user_headers, board):
    post = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": board["name"], "title": "original", "generate_replies": False},
    ).json()["post"]

    edited = client.patch(f"/api/posts/{post['id']}", headers=user_headers,
                          json={"title": "edited"}).json()["post"]
    assert edited["title"] == "edited"
    assert edited["edited"] is True

    deleted = client.delete(f"/api/posts/{post['id']}", headers=user_headers).json()["post"]
    assert deleted["deleted_by_author"] is True
    assert deleted["body"] == "[deleted]"


def test_cannot_edit_someone_elses_content(client, user_headers, guest_headers, board):
    post = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": board["name"], "title": "mine", "generate_replies": False},
    ).json()["post"]
    assert client.patch(f"/api/posts/{post['id']}", headers=guest_headers,
                        json={"title": "hijacked"}).status_code == 403
    assert client.delete(f"/api/posts/{post['id']}", headers=guest_headers).status_code == 403


def test_locked_thread_rejects_new_comments(client, user_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    db.collection("posts").update(post["_id"], {"$set": {"locked": True}})
    response = client.post(
        f"/api/posts/{post['_id']}/comments",
        headers=user_headers,
        json={"body": "let me in", "generate_replies": False},
    )
    assert response.status_code == 400


def test_removed_comments_render_as_stubs(client, board):
    from app.services import moderation_service

    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    comment = comment_service.create(post_id=post["_id"], body="secret", author="B", author_kind="ai")
    moderation_service.remove_comment(comment["_id"], reason="Rule 1: Be civil")

    node = client.get(f"/api/posts/{post['_id']}").json()["comments"][0]
    assert node["body"] == "[removed]"
    assert node["removed"] is True
    assert node["removal_reason"] == "Rule 1: Be civil"


def test_hide_removed_preference_filters_them_out(client, user_headers, board):
    from app.services import moderation_service

    client.patch("/api/me/preferences", headers=user_headers,
                 json={"preferences": {"hide_removed": True, "auto_generate_on_open": False}})
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    comment = comment_service.create(post_id=post["_id"], body="x", author="B", author_kind="ai")
    moderation_service.remove_comment(comment["_id"])

    assert client.get(f"/api/posts/{post['_id']}", headers=user_headers).json()["comments"] == []


# --------------------------------------------------------------------------- #
# Votes, awards, sharing
# --------------------------------------------------------------------------- #

def test_vote_endpoint(client, user_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    result = client.post(f"/api/vote/post/{post['_id']}", headers=user_headers,
                         json={"direction": 1}).json()
    assert result["direction"] == 1
    toggled = client.post(f"/api/vote/post/{post['_id']}", headers=user_headers,
                          json={"direction": 1}).json()
    assert toggled["direction"] == 0


def test_vote_shows_up_in_the_feed(client, user_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    client.post(f"/api/vote/post/{post['_id']}", headers=user_headers, json={"direction": -1})
    feed = client.get("/api/feed?scope=popular", headers=user_headers).json()["posts"]
    assert feed[0]["user_vote"] == -1


def test_vote_on_missing_target_is_400(client, user_headers):
    assert client.post("/api/vote/post/missing", headers=user_headers,
                       json={"direction": 1}).status_code == 400


def test_award_catalogue_and_granting(client, user_headers, board):
    catalogue = client.get("/api/awards", headers=user_headers).json()
    assert catalogue["awards"]
    assert catalogue["coins"] > 0

    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    result = client.post(f"/api/award/post/{post['_id']}", headers=user_headers,
                         json={"award_id": "silver"}).json()
    assert result["award"]["id"] == "silver"
    assert result["coins"] < catalogue["coins"]
    assert result["awards"][0]["count"] == 1


def test_award_without_coins_is_rejected(client, user_headers, board):
    user = user_service.get_by_username("samwise")
    db.collection("users").update(user["_id"], {"$set": {"coins": 0}})
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    response = client.post(f"/api/award/post/{post['_id']}", headers=user_headers,
                           json={"award_id": "gold"})
    assert response.status_code == 400
    assert "coins" in response.json()["detail"]


def test_share_returns_a_permalink(client, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    payload = client.post(f"/api/share/post/{post['_id']}").json()
    assert payload["url"] == f"/r/{board['name']}/comments/{post['_id']}"
    assert payload["shares"] == 1


def test_share_a_comment_links_into_the_thread(client, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    comment = comment_service.create(post_id=post["_id"], body="x", author="B", author_kind="ai")
    payload = client.post(f"/api/share/comment/{comment['_id']}").json()
    assert payload["url"].endswith(f"?comment={comment['_id']}")


def test_share_rejects_unknown_kind(client, board):
    assert client.post("/api/share/board/whatever").status_code == 400


def test_report_endpoint(client, guest_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    response = client.post(f"/api/report/post/{post['_id']}", headers=guest_headers,
                           json={"reason": "spam"})
    assert response.status_code == 200
    assert db.collection("reports").count() == 1


# --------------------------------------------------------------------------- #
# Profiles, settings, inbox
# --------------------------------------------------------------------------- #

def test_profile_endpoint_looks_identical_for_people_and_personas(client, board):
    from app.services import persona_service

    persona_service.ensure_persona("GrumpyOtter")
    user_service.register("sam@example.com", "hunter22", "samwise")

    persona_view = client.get("/api/users/GrumpyOtter").json()["profile"]
    human_view = client.get("/api/users/samwise").json()["profile"]

    assert set(persona_view) == set(human_view)
    assert persona_view["kind"] == "ai"
    assert human_view["kind"] == "human"


def test_profile_lists_authored_content(client, user_headers, board):
    client.post("/api/posts", headers=user_headers,
                json={"subreddit": board["name"], "title": "mine", "generate_replies": False})
    payload = client.get("/api/users/samwise").json()
    assert payload["posts"][0]["title"] == "mine"


def test_missing_profile_is_404(client):
    assert client.get("/api/users/nobody").status_code == 404


def test_preferences_round_trip(client, user_headers):
    response = client.patch(
        "/api/me/preferences",
        headers=user_headers,
        json={"preferences": {"theme": "light", "comment_density_override": "chaotic"}},
    )
    preferences = response.json()["user"]["preferences"]
    assert preferences["theme"] == "light"
    assert preferences["comment_density_override"] == "chaotic"


def test_profile_and_interests_round_trip(client, user_headers):
    profile = client.patch("/api/me/profile", headers=user_headers,
                           json={"bio": "hello", "personal_prompt": "no politics"}).json()["user"]
    assert profile["bio"] == "hello"
    assert profile["personal_prompt"] == "no politics"

    interests = client.put("/api/me/interests", headers=user_headers,
                           json={"interests": ["woodworking"]}).json()["user"]
    assert interests["interests"] == ["woodworking"]


def test_inbox_flow(client, user_headers, board):
    from app.services import notification_service

    user = user_service.get_by_username("samwise")
    notification_service.push(user["_id"], "system", title="welcome")

    inbox = client.get("/api/me/inbox", headers=user_headers).json()
    assert inbox["unread"] == 1
    client.post("/api/me/inbox/read", headers=user_headers)
    assert client.get("/api/me/inbox", headers=user_headers).json()["unread"] == 0
    assert client.request("DELETE", "/api/me/inbox", headers=user_headers).json()["cleared"] == 1


def test_export_excludes_secrets(client, user_headers):
    export = client.get("/api/me/export", headers=user_headers).json()
    assert "password_hash" not in export["user"]


def test_wipe_requires_the_confirmation_word(client, user_headers, board):
    post = client.post("/api/posts", headers=user_headers,
                       json={"subreddit": board["name"], "title": "t", "generate_replies": False}).json()["post"]

    assert client.post("/api/me/wipe", headers=user_headers,
                       json={"confirm": "yes", "delete_account": False}).status_code == 400

    summary = client.post("/api/me/wipe", headers=user_headers,
                          json={"confirm": "WIPE", "delete_account": False}).json()
    assert summary["posts_wiped"] == 1
    assert post_service.get(post["id"])["body"] == "[removed]"


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #

def test_admin_routes_are_gated(client, user_headers):
    assert client.get("/api/admin/world").status_code == 401
    assert client.get("/api/admin/world", headers=user_headers).status_code == 403


def test_admin_updates_the_global_prompt(client, admin_headers):
    response = client.patch(
        "/api/admin/world",
        headers=admin_headers,
        json={"global_prompt": "Everyone is a pirate.", "toxicity": 0.9},
    )
    world = response.json()["world"]
    assert world["global_prompt"] == "Everyone is a pirate."
    assert world["toxicity"] == 0.9
    assert config_service.get_world()["global_prompt"] == "Everyone is a pirate."


def test_admin_can_enable_serious_mode(client, admin_headers):
    response = client.patch(
        "/api/admin/world",
        headers=admin_headers,
        json={"serious_mode": True},
    )

    assert response.status_code == 200
    assert response.json()["world"]["serious_mode"] is True
    assert config_service.get_world()["serious_mode"] is True


def test_admin_world_reset(client, admin_headers):
    client.patch("/api/admin/world", headers=admin_headers, json={"humor": 0.99})
    reset = client.post("/api/admin/world/reset", headers=admin_headers).json()["world"]
    assert reset["humor"] == config_service.DEFAULT_WORLD["humor"]


def test_admin_llm_connection_lifecycle(client, admin_headers):
    payload = client.get("/api/admin/llm", headers=admin_headers).json()
    assert "openrouter" in payload["provider_types"]
    assert payload["config"]["connections"] == []

    created = client.post(
        "/api/admin/llm/connections",
        headers=admin_headers,
        json={"name": "Router", "provider_type": "openrouter", "api_key": "sk-secret-value"},
    ).json()
    connection_id = created["connection_id"]
    connection = created["config"]["connections"][0]
    assert "api_key" not in connection
    assert connection["has_api_key"] is True

    updated = client.patch(
        f"/api/admin/llm/connections/{connection_id}",
        headers=admin_headers,
        json={"enabled": False},
    ).json()["config"]
    assert updated["connections"][0]["enabled"] is False

    role = client.put(
        "/api/admin/llm/roles/comment",
        headers=admin_headers,
        json={"connection_id": connection_id, "model": "anthropic/claude-sonnet-4.5"},
    ).json()["config"]
    assert role["roles"]["comment"]["model"] == "anthropic/claude-sonnet-4.5"

    assert client.delete(
        f"/api/admin/llm/connections/{connection_id}", headers=admin_headers
    ).json()["config"]["connections"] == []


def test_admin_can_add_an_lmstudio_connection(client, admin_headers):
    payload = client.get("/api/admin/llm", headers=admin_headers).json()
    assert "lmstudio" in payload["provider_types"]

    created = client.post(
        "/api/admin/llm/connections",
        headers=admin_headers,
        json={"name": "LM Studio", "provider_type": "lmstudio"},
    ).json()
    connection = created["config"]["connections"][0]
    assert connection["provider_type"] == "lmstudio"
    assert connection["has_api_key"] is False  # no key required for a local server


def test_admin_role_must_exist(client, admin_headers):
    assert client.put("/api/admin/llm/roles/nonsense", headers=admin_headers,
                      json={"connection_id": None, "model": ""}).status_code == 400


def test_admin_connection_test_uses_the_offline_provider(client, admin_headers):
    created = client.post(
        "/api/admin/llm/connections",
        headers=admin_headers,
        json={"name": "Offline", "provider_type": "mock"},
    ).json()
    result = client.post(
        f"/api/admin/llm/connections/{created['connection_id']}/test",
        headers=admin_headers,
        json={},
    ).json()
    assert result["ok"] is True


def test_admin_simulation_controls(client, admin_headers, board):
    status = client.get("/api/admin/simulation", headers=admin_headers).json()
    assert "status" in status

    tick = client.post("/api/admin/simulation/tick", headers=admin_headers).json()["tick"]
    assert "drifted" in tick

    client.post("/api/admin/simulation/stop", headers=admin_headers)
    assert config_service.get_world()["simulation_enabled"] is False


def test_admin_can_remove_and_restore_content(client, admin_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    comment = comment_service.create(post_id=post["_id"], body="rude", author="B", author_kind="ai")

    assert client.post(f"/api/admin/moderate/comment/{comment['_id']}/remove?reason=Rule+1",
                       headers=admin_headers).json()["removed"] is True
    assert comment_service.get(comment["_id"])["removed"] is True

    assert client.post(f"/api/admin/moderate/comment/{comment['_id']}/restore",
                       headers=admin_headers).json()["restored"] is True
    assert comment_service.get(comment["_id"])["body"] == "rude"


def test_admin_moderate_rejects_unknown_kind(client, admin_headers):
    assert client.post("/api/admin/moderate/board/x/remove", headers=admin_headers).status_code == 400


def test_admin_stats_and_logs(client, admin_headers, board):
    post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    stats = client.get("/api/admin/stats", headers=admin_headers).json()
    assert stats["collections"]["posts"] == 1
    assert client.get("/api/admin/mod-log", headers=admin_headers).status_code == 200
    assert client.get("/api/admin/users", headers=admin_headers).status_code == 200
    assert client.get("/api/admin/reports", headers=admin_headers).status_code == 200


def test_admin_reset_world_keeps_accounts(client, admin_headers, board):
    post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    users_before = db.collection("users").count()
    client.post("/api/admin/reset-world?keep_users=true", headers=admin_headers)
    assert db.collection("posts").count() == 0
    assert db.collection("users").count() == users_before


def test_search_endpoint(client, board):
    post_service.create(subreddit=board["name"], title="Sourdough tips", author="A", author_kind="ai")
    payload = client.get("/api/search?q=sourdough").json()
    assert payload["posts"][0]["title"] == "Sourdough tips"


def test_activity_stream(client, board):
    post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    client.post(f"/api/share/post/{db.collection('posts').find_one()['_id']}")
    assert client.get("/api/activity").json()["events"]


# --------------------------------------------------------------------------- #
# Media and photo boards
# --------------------------------------------------------------------------- #

def _png_bytes(colour=(20, 140, 90)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), colour).save(buffer, "PNG")
    return buffer.getvalue()


def test_upload_requires_auth(client):
    response = client.post(
        "/api/media/upload", files={"file": ("x.png", _png_bytes(), "image/png")}
    )
    assert response.status_code == 401


def test_upload_and_serve_roundtrip(client, guest_headers):
    upload = client.post(
        "/api/media/upload",
        headers=guest_headers,
        files={"file": ("shot.png", _png_bytes(), "image/png")},
    )
    assert upload.status_code == 200
    media = upload.json()["media"]
    assert media["width"] == 320

    served = client.get(media["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]

    thumb = client.get(media["thumb_url"])
    assert thumb.status_code == 200


def test_upload_rejects_non_images(client, guest_headers):
    response = client.post(
        "/api/media/upload",
        headers=guest_headers,
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert response.status_code == 400


def test_serving_unknown_media_is_404(client):
    assert client.get("/api/media/nope").status_code == 404
    assert client.get("/api/media/nope/thumb").status_code == 404


def test_analysis_endpoint_reports_state(client, guest_headers):
    media = client.post(
        "/api/media/upload",
        headers=guest_headers,
        files={"file": ("a.png", _png_bytes(), "image/png")},
    ).json()["media"]

    described = client.post(f"/api/media/{media['id']}/describe", headers=guest_headers)
    assert described.status_code == 200
    assert described.json()["analysis"]["caption"]

    state = client.get(f"/api/media/{media['id']}/analysis").json()
    assert state["state"] == "done"


def test_from_url_rejects_bad_schemes(client, guest_headers):
    response = client.post(
        "/api/media/from-url", headers=guest_headers, json={"url": "file:///etc/passwd"}
    )
    assert response.status_code == 400


def test_photo_board_post_requires_an_image(client, user_headers):
    subreddit_service.create("shots", kind="photo")
    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={"subreddit": "shots", "title": "no picture", "generate_replies": False},
    )
    assert response.status_code == 400
    assert "photo board" in response.json()["detail"]


def test_photo_board_post_with_an_image(client, user_headers):
    subreddit_service.create("shots", kind="photo")
    media = client.post(
        "/api/media/upload",
        headers=user_headers,
        files={"file": ("a.png", _png_bytes(), "image/png")},
    ).json()["media"]

    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={
            "subreddit": "shots",
            "title": "caught this one",
            "media_id": media["id"],
            "generate_replies": False,
        },
    )
    assert response.status_code == 200
    post = response.json()["post"]
    assert post["media"]["id"] == media["id"]
    assert post["kind"] == "image"


def test_post_with_unknown_media_is_404(client, user_headers, board):
    response = client.post(
        "/api/posts",
        headers=user_headers,
        json={
            "subreddit": board["name"],
            "title": "t",
            "media_id": "ghost",
            "generate_replies": False,
        },
    )
    assert response.status_code == 404


def test_board_creation_accepts_photo_kind(client, user_headers):
    response = client.post(
        "/api/boards",
        headers=user_headers,
        json={"name": "aviation", "kind": "photo", "autofill": False, "generate_metadata": False},
    )
    assert response.status_code == 200
    assert response.json()["board"]["kind"] == "photo"


def test_vision_role_is_routable(client, admin_headers):
    created = client.post(
        "/api/admin/llm/connections",
        headers=admin_headers,
        json={"name": "Local", "provider_type": "lmstudio", "models": ["some-vlm"]},
    ).json()
    config = client.put(
        "/api/admin/llm/roles/vision",
        headers=admin_headers,
        json={"connection_id": created["connection_id"], "model": "some-vlm"},
    ).json()["config"]
    assert config["roles"]["vision"]["model"] == "some-vlm"


# --------------------------------------------------------------------------- #
# Turning the simulation off actually turns it off
# --------------------------------------------------------------------------- #

def _pause(client, admin_headers):
    assert client.post("/api/admin/simulation/stop", headers=admin_headers).status_code == 200


def test_pausing_stops_thread_autopopulation(client, admin_headers, board):
    """Regression: opening a thread generated comments even with the world off."""
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    _pause(client, admin_headers)

    payload = client.get(f"/api/posts/{post['_id']}", headers=admin_headers).json()
    assert payload["generated"] == 0
    assert payload["comments"] == []
    assert comment_service.count_for_post(post["_id"]) == 0


def test_pausing_stops_replies_to_your_own_comment(client, admin_headers, board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    _pause(client, admin_headers)

    client.post(
        f"/api/posts/{post['_id']}/comments",
        headers=admin_headers,
        json={"body": "anyone home?", "generate_replies": True},
    )
    # Only the human's own comment exists; nobody was summoned to answer it.
    assert comment_service.count_for_post(post["_id"]) == 1


def test_pausing_stops_thin_board_autofill(client, admin_headers, board):
    _pause(client, admin_headers)
    client.get(f"/api/boards/{board['name']}/posts", headers=admin_headers)
    assert db.collection("posts").count({"subreddit": board["name"]}) == 0


def test_pausing_stops_thin_feed_autofill(client, admin_headers, board):
    _pause(client, admin_headers)
    client.get("/api/feed?scope=popular", headers=admin_headers)
    assert db.collection("posts").count() == 0


def test_pausing_stops_replies_to_a_new_post(client, admin_headers, board):
    _pause(client, admin_headers)
    post = client.post(
        "/api/posts",
        headers=admin_headers,
        json={"subreddit": board["name"], "title": "hello", "generate_replies": True},
    ).json()["post"]
    assert comment_service.count_for_post(post["id"]) == 0


def test_explicit_buttons_still_work_while_paused(client, admin_headers, board):
    """A switch labelled 'simulation' should not disable the buttons."""
    _pause(client, admin_headers)

    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    summoned = client.post(
        f"/api/posts/{post['_id']}/generate", headers=admin_headers, json={"count": 3}
    ).json()
    assert summoned["created"] >= 1

    stirred = client.post(
        f"/api/boards/{board['name']}/generate", headers=admin_headers, json={"count": 2}
    ).json()
    assert stirred["posts"]


def test_pausing_reports_the_engine_as_stopped(client, admin_headers):
    """Regression: stop only set a flag, so status kept saying it was running."""
    client.post("/api/admin/simulation/start", headers=admin_headers)
    stopped = client.post("/api/admin/simulation/stop", headers=admin_headers).json()
    assert stopped["status"]["running"] is False
    assert client.get("/api/admin/simulation", headers=admin_headers).json()["enabled"] is False


def test_world_patch_and_buttons_agree(client, admin_headers):
    client.patch("/api/admin/world", headers=admin_headers, json={"simulation_enabled": False})
    assert client.get("/api/admin/simulation", headers=admin_headers).json()["status"]["running"] is False


def test_resuming_restores_autopopulation(client, admin_headers, board):
    _pause(client, admin_headers)
    client.post("/api/admin/simulation/start", headers=admin_headers)

    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    payload = client.get(f"/api/posts/{post['_id']}", headers=admin_headers).json()
    assert payload["generated"] > 0
