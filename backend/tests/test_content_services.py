"""Unit tests for boards, posts, comments and personas."""

from __future__ import annotations

import pytest

from app.db import db, now
from app.services import (
    comment_service,
    config_service,
    persona_service,
    post_service,
    subreddit_service,
    user_service,
)


# --------------------------------------------------------------------------- #
# Boards
# --------------------------------------------------------------------------- #

def test_create_board_defaults():
    board = subreddit_service.create("catfacts", description="cats")
    assert board["name"] == "catfacts"
    assert board["name_lower"] == "catfacts"
    assert board["rules"]
    assert "AutoModerator" in board["moderators"]
    assert board["overrides"]["humor"] is None


def test_create_board_strips_prefix():
    assert subreddit_service.create("r/catfacts")["name"] == "catfacts"


@pytest.mark.parametrize("name", ["ab", "has space", "way_too_long_board_name_here", "no-dashes!"])
def test_create_board_rejects_bad_names(name):
    with pytest.raises(subreddit_service.SubredditError):
        subreddit_service.create(name)


def test_create_board_rejects_duplicates_case_insensitively():
    subreddit_service.create("catfacts")
    with pytest.raises(subreddit_service.SubredditError, match="already exists"):
        subreddit_service.create("CatFacts")


def test_update_board_filters_and_truncates(board):
    updated = subreddit_service.update(
        board["name"],
        {
            "description": "new",
            "custom_prompt": "p" * 5000,
            "rules": [f"rule {i}" for i in range(30)],
            "subscribers": 999_999_999,
        },
    )
    assert updated["description"] == "new"
    assert len(updated["custom_prompt"]) == 4000
    assert len(updated["rules"]) == 12
    assert updated["subscribers"] == board["subscribers"]


def test_update_board_merges_overrides(board):
    subreddit_service.update(board["name"], {"overrides": {"humor": 0.9}})
    updated = subreddit_service.update(board["name"], {"overrides": {"toxicity": 0.1}})
    assert updated["overrides"]["humor"] == 0.9
    assert updated["overrides"]["toxicity"] == 0.1


def test_delete_board_removes_its_content(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    comment_service.create(post_id=post["_id"], body="c", author="A", author_kind="ai")
    assert subreddit_service.delete(board["name"]) is True
    assert db.collection("posts").count({"subreddit": board["name"]}) == 0
    assert db.collection("comments").count({"post_id": post["_id"]}) == 0


def test_can_edit_is_creator_or_admin(board, person):
    owned = subreddit_service.create("mine", creator_id=person["_id"], creator_username="realperson")
    assert subreddit_service.can_edit(owned, person) is True
    assert subreddit_service.can_edit(board, person) is False
    assert subreddit_service.can_edit(board, {"_id": "x", "is_admin": True}) is True
    assert subreddit_service.can_edit(board, None) is False


def test_effective_world_layers_board_then_user(board):
    config_service.update_world({"toxicity": 0.4, "humor": 0.5})
    subreddit_service.update(board["name"], {"overrides": {"toxicity": 0.9}})
    fresh = subreddit_service.get(board["name"])

    board_world = subreddit_service.effective_world(fresh)
    assert board_world["toxicity"] == 0.9
    assert board_world["humor"] == 0.5

    reader = {"preferences": {"content_intensity": 0.1, "comment_density_override": "chaotic"}}
    reader_world = subreddit_service.effective_world(fresh, reader)
    assert reader_world["toxicity"] == 0.1  # the reader's own setting wins
    assert reader_world["comment_density"] == "chaotic"


def test_effective_world_ignores_null_overrides(board):
    config_service.update_world({"humor": 0.7})
    assert subreddit_service.effective_world(board)["humor"] == 0.7


def test_board_moderation_toggle_reaches_the_world(board):
    subreddit_service.update(board["name"], {"moderation_enabled": False})
    fresh = subreddit_service.get(board["name"])
    assert subreddit_service.effective_world(fresh)["moderation_enabled"] is False


def test_reader_language_style_appends_to_style_prompt(board):
    reader = {"preferences": {"language_style": "keep it British"}}
    world = subreddit_service.effective_world(board, reader)
    assert "keep it British" in world["style_prompt"]


def test_personal_prompt_is_per_user_per_board(board, person):
    subreddit_service.set_personal_prompt(person["_id"], board["name"], "lean technical")
    assert subreddit_service.get_personal_prompt(person["_id"], board["name"]) == "lean technical"
    assert subreddit_service.get_personal_prompt("someone-else", board["name"]) == ""


def test_personal_prompt_combines_with_profile_prompt(board, person):
    user_service.update_profile(person["_id"], {"personal_prompt": "no politics"})
    subreddit_service.set_personal_prompt(person["_id"], board["name"], "more puns")
    combined = subreddit_service.personal_prompt_for(
        board["name"], user_service.get_user(person["_id"])
    )
    assert "no politics" in combined and "more puns" in combined


def test_list_boards_filters_nsfw_and_blocked():
    subreddit_service.create("sfw")
    subreddit_service.create("spicy", nsfw=True)
    assert {b["name"] for b in subreddit_service.list_boards(include_nsfw=False)} == {"sfw"}
    assert {b["name"] for b in subreddit_service.list_boards(exclude=["sfw"])} == {"spicy"}


def test_list_boards_search_matches_name_and_description():
    subreddit_service.create("woodwork", description="planes and chisels")
    assert subreddit_service.list_boards(query="chisel")[0]["name"] == "woodwork"
    assert subreddit_service.list_boards(query="woodw")[0]["name"] == "woodwork"


def test_online_count_scales_with_size_and_recency():
    small = subreddit_service.create("small")
    db.collection("subreddits").update(small["_id"], {"$set": {"subscribers": 100, "last_activity_at": now()}})
    big = subreddit_service.create("big")
    db.collection("subreddits").update(big["_id"], {"$set": {"subscribers": 500_000, "last_activity_at": now()}})
    assert subreddit_service.online_count(subreddit_service.get("big")) > subreddit_service.online_count(
        subreddit_service.get("small")
    )


def test_public_board_hides_prompt_unless_requested(board, person):
    plain = subreddit_service.public_board(board, person)
    assert "custom_prompt" not in plain
    assert subreddit_service.public_board(board, person, include_prompt=True)["custom_prompt"] == ""


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #

def test_fallback_personas_are_distinct():
    created = persona_service.create_fallback_personas(15)
    names = {persona["username"] for persona in created}
    assert len(names) == len(created) >= 10


def test_ensure_persona_is_idempotent():
    first = persona_service.ensure_persona("GrumpyOtter")
    second = persona_service.ensure_persona("grumpyotter")
    assert first["_id"] == second["_id"]


def test_normalise_username_strips_prefix_and_junk():
    assert persona_service.normalise_username("u/Some User!") == "SomeUser"
    assert persona_service.normalise_username("") != ""


def test_sample_for_board_prefers_locals(board):
    persona_service.create_fallback_personas(10, board["name"])
    persona_service.create_fallback_personas(10, "elsewhere")
    sample = persona_service.sample_for_board(board, count=10)
    locals_in_sample = sum(1 for p in sample if p.get("home_subreddit") == board["name"])
    assert locals_in_sample >= 5


def test_sample_for_board_honours_exclusions(board):
    persona_service.create_fallback_personas(6, board["name"])
    first = persona_service.sample_for_board(board, count=3)[0]["username"]
    sample = persona_service.sample_for_board(board, count=5, exclude=[first])
    assert all(p["username"] != first for p in sample)


def test_sample_for_board_tops_up_when_short(board):
    assert len(persona_service.sample_for_board(board, count=8)) == 8


def test_public_persona_carries_no_ai_marker():
    persona = persona_service.ensure_persona("GrumpyOtter")
    public = persona_service.public_persona(persona)
    assert public["username"] == "GrumpyOtter"
    assert "traits" not in public
    assert "posting_style" not in public
    assert public["is_admin"] is False


async def test_generate_personas_falls_back_offline(board):
    created = await persona_service.generate_personas(5, board)
    assert len(created) >= 1
    assert all(persona["home_subreddit"] == board["name"] for persona in created)


async def test_ensure_roster_reaches_the_minimum(board):
    await persona_service.ensure_roster(board, minimum=8)
    assert db.collection("personas").count({"home_subreddit": board["name"]}) >= 8


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #

def test_create_post_requires_a_title(board):
    with pytest.raises(post_service.PostError):
        post_service.create(subreddit=board["name"], title="   ", author="A")


def test_create_post_truncates_long_titles(board):
    post = post_service.create(subreddit=board["name"], title="x" * 500, author="A")
    assert len(post["title"]) == 300


def test_link_post_without_url_becomes_text(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", kind="link")
    assert post["kind"] == "text"


def test_delete_by_author_leaves_a_tombstone(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson", author_id=person["_id"]
    )
    updated = post_service.delete_by_author(post["_id"])
    assert updated["body"] == "[deleted]"
    assert updated["author"] == "[deleted]"
    assert post_service.get(post["_id"]) is not None


def test_sorting_strategies_differ(board):
    old_high = post_service.create(
        subreddit=board["name"], title="old", author="A", created_at=now() - 86_400
    )
    new_low = post_service.create(subreddit=board["name"], title="new", author="B")
    db.collection("posts").update(old_high["_id"], {"$set": {"score": 900, "ups": 950, "downs": 50}})
    db.collection("posts").update(new_low["_id"], {"$set": {"score": 5, "ups": 5, "downs": 0}})

    posts = db.collection("posts").all()
    assert post_service.sort_items(posts, "top")[0]["title"] == "old"
    assert post_service.sort_items(posts, "new")[0]["title"] == "new"
    assert post_service.sort_items(posts, "hot")[0]["title"] in {"old", "new"}
    assert post_service.sort_items(posts, "best")[0]["title"] == "old"


def test_controversial_sort_prefers_split_votes(board):
    split = post_service.create(subreddit=board["name"], title="split", author="A")
    onesided = post_service.create(subreddit=board["name"], title="onesided", author="B")
    db.collection("posts").update(split["_id"], {"$set": {"ups": 500, "downs": 480, "score": 20}})
    db.collection("posts").update(onesided["_id"], {"$set": {"ups": 900, "downs": 2, "score": 898}})
    ranked = post_service.sort_items(db.collection("posts").all(), "controversial")
    assert ranked[0]["title"] == "split"


def test_feed_respects_blocked_boards_and_nsfw():
    subreddit_service.create("sfw")
    subreddit_service.create("spicy", nsfw=True)
    post_service.create(subreddit="sfw", title="ok", author="A")
    post_service.create(subreddit="spicy", title="adult", author="B", nsfw=True)

    anonymous = post_service.feed_for_user(None, scope="popular")
    assert {p["title"] for p in anonymous} == {"ok"}

    opted_in = post_service.feed_for_user(
        {"preferences": {"show_nsfw": True}}, scope="popular"
    )
    assert {p["title"] for p in opted_in} == {"ok", "adult"}

    blocked = post_service.feed_for_user(
        {"preferences": {"show_nsfw": True}, "banned_subreddits": ["spicy"]}, scope="popular"
    )
    assert {p["title"] for p in blocked} == {"ok"}


def test_home_feed_limits_to_subscriptions():
    subreddit_service.create("joined")
    subreddit_service.create("other")
    post_service.create(subreddit="joined", title="mine", author="A")
    post_service.create(subreddit="other", title="theirs", author="B")
    user = {"subscriptions": ["joined"], "preferences": {}}
    assert {p["title"] for p in post_service.feed_for_user(user, scope="home")} == {"mine"}


def test_search_matches_title_and_body(board):
    post_service.create(subreddit=board["name"], title="Sourdough tips", author="A")
    post_service.create(subreddit=board["name"], title="Unrelated", body="about sourdough", author="B")
    assert len(post_service.search("sourdough")) == 2
    assert post_service.search("") == []


def test_age_label_reads_naturally():
    assert post_service.age_label(now()) == "just now"
    assert post_service.age_label(now() - 300) == "5 min ago"
    assert post_service.age_label(now() - 7200) == "2 hr ago"
    assert post_service.age_label(now() - 86_400 * 2) == "2 days ago"
    assert post_service.age_label(now() - 86_400 * 400) == "1 yr ago"


def test_author_badge_only_for_humans():
    assert post_service.author_badge({"author_kind": "human"})["label"] == "human"
    assert post_service.author_badge({"author_kind": "ai"}) is None
    assert post_service.author_badge({"author_kind": "deleted"}) is None


def test_public_post_masks_removed_body(board):
    post = post_service.create(subreddit=board["name"], title="t", body="secret", author="A")
    db.collection("posts").update(
        post["_id"], {"$set": {"removed": True, "removal_reason": "Rule 1", "removed_by": "Mod"}}
    )
    payload = post_service.public_post(post_service.get(post["_id"]))
    assert payload["body"] == "[removed]"
    assert payload["removal_reason"] == "Rule 1"
    assert "quality" not in payload


def test_public_post_includes_internals_only_when_asked(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", quality=0.8)
    payload = post_service.public_post(post, include_internal=True)
    assert payload["quality"] == 0.8
    assert payload["author_kind"] == "human"


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

@pytest.fixture
def post(board):
    return post_service.create(subreddit=board["name"], title="Thread", author="OpPersona", author_kind="ai")


def test_comment_requires_body(post):
    with pytest.raises(comment_service.CommentError):
        comment_service.create(post_id=post["_id"], body="  ", author="A")


def test_comment_on_missing_post_raises():
    with pytest.raises(comment_service.CommentError):
        comment_service.create(post_id="nope", body="hi", author="A")


def test_depth_increments_and_caps(post):
    parent_id = None
    for _ in range(comment_service.MAX_DEPTH + 4):
        comment = comment_service.create(
            post_id=post["_id"], parent_id=parent_id, body="deep", author="A", author_kind="ai"
        )
        parent_id = comment["_id"]
    assert comment["depth"] == comment_service.MAX_DEPTH


def test_reply_to_missing_parent_raises(post):
    with pytest.raises(comment_service.CommentError):
        comment_service.create(post_id=post["_id"], parent_id="nope", body="hi", author="A")


def test_locked_thread_blocks_humans_but_not_the_simulation(post):
    db.collection("posts").update(post["_id"], {"$set": {"locked": True}})
    with pytest.raises(comment_service.CommentError, match="locked"):
        comment_service.create(post_id=post["_id"], body="hi", author="A", author_kind="human")
    assert comment_service.create(post_id=post["_id"], body="hi", author="A", author_kind="ai")


def test_op_flag_set_for_thread_author(post):
    op = comment_service.create(
        post_id=post["_id"], body="my own thread", author="OpPersona", author_kind="ai"
    )
    other = comment_service.create(post_id=post["_id"], body="not op", author="B", author_kind="ai")
    assert op["is_op"] is True
    assert other["is_op"] is False


def test_comment_count_tracks_writes_and_deletes(post):
    first = comment_service.create(post_id=post["_id"], body="a", author="A", author_kind="ai")
    comment_service.create(post_id=post["_id"], body="b", author="B", author_kind="ai")
    assert post_service.get(post["_id"])["comment_count"] == 2
    comment_service.hard_delete(first["_id"])
    assert post_service.get(post["_id"])["comment_count"] == 1


def test_build_tree_nests_replies(post):
    root = comment_service.create(post_id=post["_id"], body="root", author="A", author_kind="ai")
    child = comment_service.create(
        post_id=post["_id"], parent_id=root["_id"], body="child", author="B", author_kind="ai"
    )
    comment_service.create(
        post_id=post["_id"], parent_id=child["_id"], body="grandchild", author="C", author_kind="ai"
    )
    tree = comment_service.build_tree(post["_id"])
    assert len(tree) == 1
    assert tree[0]["replies"][0]["body"] == "child"
    assert tree[0]["replies"][0]["replies"][0]["body"] == "grandchild"


def test_build_tree_can_hide_removed(post):
    comment_service.create(post_id=post["_id"], body="visible", author="A", author_kind="ai")
    hidden = comment_service.create(post_id=post["_id"], body="gone", author="B", author_kind="ai")
    db.collection("comments").update(hidden["_id"], {"$set": {"removed": True}})

    shown = comment_service.build_tree(post["_id"])
    assert [node["body"] for node in shown] == ["visible", "[removed]"] or [
        node["body"] for node in shown
    ] == ["[removed]", "visible"]

    filtered = comment_service.build_tree(post["_id"], hide_removed=True)
    assert [node["body"] for node in filtered] == ["visible"]


def test_build_tree_sorts_each_level(post):
    low = comment_service.create(post_id=post["_id"], body="low", author="A", author_kind="ai")
    high = comment_service.create(post_id=post["_id"], body="high", author="B", author_kind="ai")
    db.collection("comments").update(low["_id"], {"$set": {"score": 1}})
    db.collection("comments").update(high["_id"], {"$set": {"score": 500}})
    assert comment_service.build_tree(post["_id"], sort="top")[0]["body"] == "high"


def test_render_tree_for_prompt_uses_stable_ids(post):
    root = comment_service.create(post_id=post["_id"], body="root", author="A", author_kind="ai")
    comment_service.create(
        post_id=post["_id"], parent_id=root["_id"], body="child", author="B", author_kind="ai"
    )
    rendered = comment_service.render_tree_for_prompt(post["_id"])
    assert f"[c{root['_id']}]" in rendered
    assert "  [c" in rendered  # the child is indented


def test_render_tree_marks_removed_content(post):
    comment = comment_service.create(post_id=post["_id"], body="rude", author="A", author_kind="ai")
    db.collection("comments").update(comment["_id"], {"$set": {"removed": True}})
    assert "[removed by moderator]" in comment_service.render_tree_for_prompt(post["_id"])


def test_render_tree_is_empty_for_a_fresh_thread(post):
    assert comment_service.render_tree_for_prompt(post["_id"]) == ""


def test_ancestors_walk_up_to_the_root(post):
    root = comment_service.create(post_id=post["_id"], body="root", author="A", author_kind="ai")
    child = comment_service.create(
        post_id=post["_id"], parent_id=root["_id"], body="child", author="B", author_kind="ai"
    )
    chain = comment_service.ancestors(child["_id"])
    assert [node["body"] for node in chain] == ["root", "child"]


def test_delete_by_author_keeps_children_readable(post):
    parent = comment_service.create(post_id=post["_id"], body="parent", author="A", author_kind="ai")
    child = comment_service.create(
        post_id=post["_id"], parent_id=parent["_id"], body="child", author="B", author_kind="ai"
    )
    comment_service.delete_by_author(parent["_id"])
    tree = comment_service.build_tree(post["_id"])
    assert tree[0]["body"] == "[deleted]"
    assert tree[0]["replies"][0]["body"] == "child"
    assert comment_service.get(child["_id"]) is not None
