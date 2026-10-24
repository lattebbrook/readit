"""Unit tests for content generation, the simulation engine, config and seeding."""

from __future__ import annotations

import random

import pytest

from app.db import db, now, seed
from app.services import (
    comment_service,
    config_service,
    generation_service,
    post_service,
    simulation,
    subreddit_service,
    user_service,
)


# --------------------------------------------------------------------------- #
# Config service
# --------------------------------------------------------------------------- #

def test_world_is_created_on_first_read():
    world = config_service.get_world()
    assert world["global_prompt"]
    assert world["comment_density"] == "normal"
    assert world["serious_mode"] is False
    assert db.collection("config").count({"key": "world"}) == 1


def test_update_world_ignores_unknown_keys():
    updated = config_service.update_world({"humor": 0.9, "not_a_knob": 1})
    assert updated["humor"] == 0.9
    assert "not_a_knob" not in updated


def test_reset_world_restores_defaults():
    config_service.update_world(
        {"humor": 0.99, "global_prompt": "chaos", "serious_mode": True}
    )
    reset = config_service.reset_world()
    assert reset["humor"] == config_service.DEFAULT_WORLD["humor"]
    assert reset["global_prompt"] == config_service.DEFAULT_GLOBAL_PROMPT
    assert reset["serious_mode"] is False


def test_missing_keys_are_backfilled_on_read():
    world = config_service.get_world()
    db.collection("config").update(world["_id"], {"$unset": {"award_rate": True}})
    assert "award_rate" in config_service.get_world()


def test_first_connection_becomes_the_default_for_every_role():
    connection = config_service.add_connection(
        {"name": "Router", "provider_type": "openrouter", "api_key": "sk-x"}
    )
    config = config_service.get_llm_config()
    assert config["default_connection_id"] == connection["id"]
    assert all(role["connection_id"] == connection["id"] for role in config["roles"].values())
    assert connection["models"], "provider defaults should be prefilled"


def test_public_llm_config_masks_keys():
    config_service.add_connection(
        {"name": "OpenAI", "provider_type": "openai", "api_key": "sk-supersecretvalue"}
    )
    public = config_service.public_llm_config()
    connection = public["connections"][0]
    assert "api_key" not in connection
    assert connection["has_api_key"] is True
    assert "supersecret" not in connection["api_key_preview"]


def test_empty_api_key_on_update_keeps_the_stored_one():
    connection = config_service.add_connection(
        {"name": "OpenAI", "provider_type": "openai", "api_key": "sk-original"}
    )
    config_service.update_connection(connection["id"], {"api_key": "", "name": "Renamed"})
    stored = config_service.get_connection(connection["id"])
    assert stored["api_key"] == "sk-original"
    assert stored["name"] == "Renamed"


def test_clear_api_key_flag_wipes_it():
    connection = config_service.add_connection(
        {"name": "OpenAI", "provider_type": "openai", "api_key": "sk-original"}
    )
    config_service.update_connection(connection["id"], {"clear_api_key": True})
    assert config_service.get_connection(connection["id"])["api_key"] == ""


def test_delete_connection_detaches_roles():
    connection = config_service.add_connection({"name": "A", "provider_type": "mock"})
    assert config_service.delete_connection(connection["id"]) is True
    config = config_service.get_llm_config()
    assert all(role["connection_id"] is None for role in config["roles"].values())
    assert config["default_connection_id"] is None
    assert config_service.delete_connection(connection["id"]) is False


def test_enabled_connections_filters_disabled():
    connection = config_service.add_connection({"name": "A", "provider_type": "mock"})
    assert len(config_service.enabled_connections()) == 1
    config_service.update_connection(connection["id"], {"enabled": False})
    assert config_service.enabled_connections() == []


def test_set_role_and_flags():
    connection = config_service.add_connection({"name": "A", "provider_type": "mock"})
    entry = config_service.set_role("comment", connection["id"], "mock-1", temperature=1.4)
    assert entry["model"] == "mock-1"
    assert entry["temperature"] == 1.4

    config_service.set_llm_flag("multi_model_mixing", False)
    assert config_service.get_llm_config()["multi_model_mixing"] is False
    with pytest.raises(ValueError):
        config_service.set_llm_flag("nope", True)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

async def test_generate_posts_creates_scored_threads(board):
    posts = await generation_service.generate_posts(board["name"], count=3)
    assert posts
    for post in posts:
        assert post["title"]
        assert post["author_kind"] == "ai"
        assert post["created_at"] < now()  # backdated so the board looks lived-in
        assert post["ups"] >= 0


def test_roll_post_audience_spans_the_whole_range():
    """Every tier should be reachable — the whole point is an uneven spread.

    Seeded so a run that happens to draw no viral posts (2% tier) cannot fail a
    test whose subject is the shape of the distribution, not one sample of it.
    """
    random.seed(4321)
    samples = [generation_service._roll_post_audience() for _ in range(400)]
    assert min(samples) < 25  # flop tier
    assert max(samples) > 15_000  # viral tier
    assert sum(1 for s in samples if s < 300) > sum(1 for s in samples if s > 15_000), (
        "flops and quiet posts should vastly outnumber viral hits"
    )


def test_audience_for_comments_is_usually_small():
    """Most replies should be barely seen; only a rare few should break out.

    Seeded: breakouts are ~1.5% by design, so an unseeded sample can legitimately
    contain none and fail an assertion about a distribution that is actually fine.
    """
    random.seed(1234)
    samples = [generation_service._audience_for({}, 0) for _ in range(2000)]
    typical = sum(1 for s in samples if s <= 9)
    breakout = sum(1 for s in samples if s > 500)
    assert typical / len(samples) > 0.8
    assert 0 < breakout < typical


def test_audience_for_comments_shrinks_with_depth():
    random.seed(42)
    shallow = sum(generation_service._audience_for({}, 0) for _ in range(300))
    random.seed(42)
    deep = sum(generation_service._audience_for({}, 4) for _ in range(300))
    assert deep < shallow


def test_generate_posts_for_missing_board_returns_nothing(anyio_backend=None):
    import asyncio

    assert asyncio.run(generation_service.generate_posts("nope", count=2)) == []


async def test_generate_comments_builds_a_real_tree(board):
    # Seeded so the offline generator's probabilistic nesting is reproducible.
    random.seed(99)
    post = post_service.create(
        subreddit=board["name"], title="Discuss", author="OpPersona", author_kind="ai"
    )
    created = await generation_service.generate_comments(post["_id"], count=10)

    assert len(created) >= 4
    assert post_service.get(post["_id"])["comment_count"] == len(created)
    assert any(comment["parent_id"] for comment in created), "expected nested replies"
    assert all(comment["author_kind"] == "ai" for comment in created)


async def test_generated_comments_are_attributed_to_real_personas(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    created = await generation_service.generate_comments(post["_id"], count=6)
    from app.services import persona_service

    assert all(persona_service.get_persona(comment["author"]) for comment in created)


async def test_generated_comments_are_ordered_in_time(board):
    post = post_service.create(
        subreddit=board["name"], title="t", author="A", author_kind="ai",
        created_at=now() - 7200,
    )
    created = await generation_service.generate_comments(post["_id"], count=8)
    times = [comment["created_at"] for comment in created]
    assert times == sorted(times)
    assert all(post["created_at"] <= t <= now() for t in times)


async def test_live_generation_timestamps_are_recent(board):
    post = post_service.create(
        subreddit=board["name"], title="t", author="A", author_kind="ai",
        created_at=now() - 86_400,
    )
    created = await generation_service.generate_comments(post["_id"], count=4, live=True)
    assert all(now() - comment["created_at"] < 600 for comment in created)


async def test_locked_threads_reject_generation(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    db.collection("posts").update(post["_id"], {"$set": {"locked": True}})
    assert await generation_service.generate_comments(post["_id"], count=5) == []


async def test_serious_mode_always_runs_topic_moderation(board, monkeypatch):
    post = post_service.create(
        subreddit=board["name"], title="t", author="A", author_kind="ai"
    )
    comment_service.create(
        post_id=post["_id"],
        subreddit=board["name"],
        body="A calm but unrelated tangent",
        author="B",
        author_kind="ai",
    )
    calls = []

    async def fake_ai_pass(post_id, *, world):
        calls.append((post_id, world["serious_mode"]))
        return []

    monkeypatch.setattr(
        "app.services.generation_service.moderation_service.ai_pass", fake_ai_pass
    )

    await generation_service._maybe_moderate(  # noqa: SLF001 - policy regression test
        post["_id"], {**config_service.DEFAULT_WORLD, "serious_mode": True}
    )

    assert calls == [(post["_id"], True)]


async def test_ensure_thread_populated_only_fills_once(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    first = await generation_service.ensure_thread_populated(post["_id"])
    assert first
    assert await generation_service.ensure_thread_populated(post["_id"]) == []


async def test_density_setting_changes_thread_size(board):
    sparse_board = subreddit_service.create("sparseboard", overrides={"comment_density": "sparse"})
    busy_board = subreddit_service.create("busyboard", overrides={"comment_density": "chaotic"})
    sparse_post = post_service.create(
        subreddit=sparse_board["name"], title="t", author="A", author_kind="ai"
    )
    busy_post = post_service.create(
        subreddit=busy_board["name"], title="t", author="A", author_kind="ai"
    )

    await generation_service.ensure_thread_populated(sparse_post["_id"])
    await generation_service.ensure_thread_populated(busy_post["_id"])

    assert comment_service.count_for_post(busy_post["_id"]) > comment_service.count_for_post(
        sparse_post["_id"]
    )


async def test_reply_to_user_comment_lands_underneath_it(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    mine = comment_service.create(
        post_id=post["_id"], body="what do you all think", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    replies = await generation_service.reply_to_user_comment(mine["_id"], person, count=3)

    assert replies
    assert any(reply["parent_id"] == mine["_id"] for reply in replies)


async def test_replying_to_a_human_creates_a_notification(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    mine = comment_service.create(
        post_id=post["_id"], body="thoughts?", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    await generation_service.reply_to_user_comment(mine["_id"], person, count=2)
    assert db.collection("notifications").count({"user_id": person["_id"]}) >= 1


async def test_max_comments_per_thread_is_respected(board):
    config_service.update_world({"max_comments_per_thread": 5})
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    await generation_service.generate_comments(post["_id"])
    await generation_service.generate_comments(post["_id"])
    assert comment_service.count_for_post(post["_id"]) <= 5


async def test_generation_state_returns_to_idle(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    await generation_service.generate_comments(post["_id"], count=3)
    assert post_service.get(post["_id"])["generation_state"] == "idle"


async def test_activity_log_records_generation(board):
    await generation_service.generate_posts(board["name"], count=2)
    assert db.collection("activity").count({"kind": "post"}) >= 1


async def test_seed_board_produces_posts_and_a_populated_thread(board):
    result = await generation_service.seed_board(board["name"], posts=4, threads_to_fill=1)
    assert result["posts"] >= 1
    assert db.collection("comments").count() >= 1


def test_resolve_parent_maps_references():
    resolve = generation_service._resolve_parent
    existing = {"abc123"}
    new_ids = ["new0", "new1"]
    assert resolve(None, new_ids, existing) is None
    assert resolve("", new_ids, existing) is None
    assert resolve("cabc123", new_ids, existing) == "abc123"
    assert resolve("abc123", new_ids, existing) == "abc123"
    assert resolve("n1", new_ids, existing) == "new1"
    assert resolve("n9", new_ids, existing) is None
    assert resolve("nX", new_ids, existing) is None
    assert resolve("cUNKNOWN", new_ids, existing) is None


# --------------------------------------------------------------------------- #
# Simulation engine
# --------------------------------------------------------------------------- #

def test_register_view_builds_a_watchlist(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    simulation.register_view(post["_id"], "user-1")
    simulation.register_view(post["_id"], "user-2")
    entry = db.collection("watchlist").find_one({"post_id": post["_id"]})
    assert entry["priority"] == 2.0
    assert set(entry["viewers"]) == {"user-1", "user-2"}


def test_participation_outranks_a_plain_view(board):
    read = post_service.create(subreddit=board["name"], title="read", author="A", author_kind="ai")
    joined = post_service.create(subreddit=board["name"], title="joined", author="A", author_kind="ai")
    simulation.register_view(read["_id"])
    simulation.register_participation(joined["_id"], "user-1")

    entries = simulation.watched()
    assert entries[0]["post_id"] == joined["_id"]
    assert entries[0]["needs_reply"] is True


def test_expired_watch_entries_are_pruned(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    simulation.register_view(post["_id"])
    entry = db.collection("watchlist").find_one({"post_id": post["_id"]})
    db.collection("watchlist").update(entry["_id"], {"$set": {"expires_at": now() - 10}})
    assert simulation.watched() == []


def test_drift_scores_moves_recent_content(board):
    for index in range(6):
        post = post_service.create(
            subreddit=board["name"], title=f"t{index}", author="A", author_kind="ai"
        )
        db.collection("posts").update(post["_id"], {"$set": {"quality": 0.8}})
    before = sum(p["ups"] for p in db.collection("posts").all())
    simulation.drift_scores(config_service.get_world())
    after = sum(p["ups"] for p in db.collection("posts").all())
    assert after >= before


async def test_tick_is_a_no_op_when_simulation_is_off(board):
    config_service.update_world({"simulation_enabled": False})
    result = await simulation.engine.tick()
    assert result["skipped"] is True


async def test_tick_fills_an_empty_board(board):
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], board["name"])
    config_service.update_world({"simulation_enabled": True, "background_activity": True})

    result = await simulation.engine.tick()

    assert result["skipped"] is False
    assert result["boards_refreshed"] >= 1
    assert db.collection("posts").count({"subreddit": board["name"]}) > 0


async def test_tick_grows_a_thread_a_human_participated_in(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    await generation_service.generate_comments(post["_id"], count=3)
    db.collection("posts").update(post["_id"], {"$set": {"last_generated_at": now() - 3600}})
    simulation.register_participation(post["_id"], "user-1")

    before = comment_service.count_for_post(post["_id"])
    await simulation.engine.tick()
    assert comment_service.count_for_post(post["_id"]) > before


async def test_background_activity_off_stops_generation(board):
    config_service.update_world({"background_activity": False})
    result = await simulation.engine.tick()
    assert result["threads_grown"] == 0
    assert result["boards_refreshed"] == 0


def test_engine_status_shape():
    status = simulation.engine.status()
    assert {"running", "ticks", "generations", "watched_threads"} <= set(status)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #

def test_bootstrap_is_idempotent():
    first = seed.bootstrap()
    assert first["boards_created"] == len(seed.DEFAULT_BOARDS)
    assert first["personas_created"] > 0

    second = seed.bootstrap()
    assert second["boards_created"] == 0
    assert db.collection("subreddits").count() == len(seed.DEFAULT_BOARDS)


def test_bootstrap_creates_the_admin():
    seed.bootstrap()
    from app.config import settings

    admin = user_service.get_by_email(settings.admin_email)
    assert admin is not None
    assert admin["is_admin"] is True


def test_bootstrap_seeds_a_real_automoderator():
    from app.services import persona_service

    seed.bootstrap()
    automod = persona_service.get_persona("AutoModerator")
    assert automod is not None
    assert automod["kind"] == "ai"
    assert "automated" in automod["traits"]
    # Re-running bootstrap must not spawn a second, randomly-invented one.
    seed.bootstrap()
    assert db.collection("personas").count({"username_lower": "automoderator"}) == 1


def test_bootstrap_promotes_an_existing_account_to_admin():
    from app.config import settings

    user_service.register(settings.admin_email, "whatever", "someone")
    db.collection("users").update_many({}, {"$set": {"is_admin": False}})
    seed.bootstrap()
    assert user_service.get_by_email(settings.admin_email)["is_admin"] is True


def test_seeded_boards_carry_their_personality_overrides():
    seed.bootstrap()
    funny = subreddit_service.get("funny")
    assert funny["overrides"]["humor"] == 0.9
    assert subreddit_service.effective_world(funny)["humor"] == 0.9


def test_serious_mode_wins_over_board_and_reader_humor_overrides(board, person):
    config_service.update_world({"serious_mode": True})
    board = subreddit_service.update(
        board["name"],
        {
            "overrides": {
                "humor": 1.0,
                "shitpost_rate": 1.0,
                "toxicity": 1.0,
                "expertise": 0.0,
            }
        },
    )
    person = user_service.update_preferences(person["_id"], {"humor_override": 1.0})

    effective = subreddit_service.effective_world(board, person)

    assert effective["serious_mode"] is True
    assert effective["humor"] == 0.15
    assert effective["shitpost_rate"] == 0.0
    assert effective["toxicity"] == 0.2
    assert effective["expertise"] == 0.8
    assert effective["moderation_strictness"] >= 0.75


def test_seed_connections_from_environment(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "sk-from-env")
    created = seed.seed_connections()
    assert len(created) == 1
    assert created[0]["provider_type"] == "openrouter"
    assert seed.seed_connections() == []  # already present


async def test_seed_content_fills_empty_official_boards():
    seed.bootstrap()
    result = await seed.seed_content(board_limit=2, posts_per_board=3)
    assert len(result["boards"]) == 2
    assert db.collection("posts").count() > 0
