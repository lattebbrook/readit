"""Unit tests for votes, awards, moderation and notifications."""

from __future__ import annotations

import random

import pytest

from app.db import db, now
from app.services import (
    award_service,
    comment_service,
    config_service,
    moderation_service,
    notification_service,
    persona_service,
    post_service,
    user_service,
    vote_service,
)


@pytest.fixture
def post(board):
    return post_service.create(
        subreddit=board["name"], title="Thread", author="OpPersona", author_kind="ai"
    )


@pytest.fixture
def world():
    return config_service.get_world()


# --------------------------------------------------------------------------- #
# Voting
# --------------------------------------------------------------------------- #

def test_cast_vote_moves_the_score(person, post):
    result = vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    assert result["direction"] == 1
    assert result["score"] == post["score"] + 1


def test_repeating_the_same_vote_clears_it(person, post):
    vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    result = vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    assert result["direction"] == 0
    assert result["score"] == post["score"]


def test_switching_direction_moves_two_points(person, post):
    vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    result = vote_service.cast_vote(person["_id"], "post", post["_id"], -1)
    assert result["direction"] == -1
    assert result["score"] == post["score"] - 1
    assert result["ups"] == post["ups"]
    assert result["downs"] == 1


def test_vote_is_recorded_once_per_user(person, post):
    for direction in (1, -1, 1):
        vote_service.cast_vote(person["_id"], "post", post["_id"], direction)
    assert db.collection("votes").count({"user_id": person["_id"]}) == 1


def test_vote_rejects_bad_input(person, post):
    with pytest.raises(vote_service.VoteError):
        vote_service.cast_vote(person["_id"], "post", post["_id"], 5)
    with pytest.raises(vote_service.VoteError):
        vote_service.cast_vote(person["_id"], "board", post["_id"], 1)
    with pytest.raises(vote_service.VoteError):
        vote_service.cast_vote(person["_id"], "post", "missing", 1)


def test_vote_awards_karma_to_the_author(board, person):
    author = user_service.register("author@example.com", "hunter22", "author")
    post = post_service.create(
        subreddit=board["name"], title="t", author="author", author_id=author["_id"]
    )
    before = user_service.get_user(author["_id"])["karma"]["post"]
    vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    assert user_service.get_user(author["_id"])["karma"]["post"] == before + 1


def test_vote_awards_karma_to_personas(post):
    persona_service.ensure_persona("OpPersona")
    person = user_service.create_guest()
    before = persona_service.get_persona("OpPersona")["karma"]["post"]
    vote_service.cast_vote(person["_id"], "post", post["_id"], 1)
    assert persona_service.get_persona("OpPersona")["karma"]["post"] == before + 1


def test_user_votes_for_bulk_lookup(person, board):
    posts = [
        post_service.create(subreddit=board["name"], title=f"t{i}", author="A", author_kind="ai")
        for i in range(3)
    ]
    vote_service.cast_vote(person["_id"], "post", posts[0]["_id"], 1)
    vote_service.cast_vote(person["_id"], "post", posts[1]["_id"], -1)
    votes = vote_service.user_votes_for(person["_id"], [p["_id"] for p in posts])
    assert votes == {posts[0]["_id"]: 1, posts[1]["_id"]: -1}
    assert vote_service.user_votes_for(None, ["x"]) == {}


def test_effective_quality_favours_humans(world):
    assert vote_service.effective_quality(0.4, is_human=False, world=world) == 0.4
    assert vote_service.effective_quality(0.4, is_human=True, world=world) > 0.4
    # The bonus is a lift, never a ceiling break.
    assert vote_service.effective_quality(1.0, is_human=True, world=world) == 1.0


def test_simulated_votes_track_quality(world):
    rng = random.Random(7)
    good_ups, good_downs = vote_service.simulate_votes(
        quality=0.95, controversy=0.1, world=world, audience=400, rng=rng
    )
    bad_ups, bad_downs = vote_service.simulate_votes(
        quality=0.05, controversy=0.1, world=world, audience=400, rng=rng
    )
    assert good_ups > bad_ups
    assert bad_downs > good_downs


def test_human_content_is_treated_more_kindly(world):
    ai_scores = []
    human_scores = []
    for seed in range(40):
        ups, downs = vote_service.simulate_votes(
            quality=0.35, world=world, audience=200, rng=random.Random(seed)
        )
        ai_scores.append(ups - downs)
        ups, downs = vote_service.simulate_votes(
            quality=0.35, is_human=True, world=world, audience=200, rng=random.Random(seed)
        )
        human_scores.append(ups - downs)
    assert sum(human_scores) > sum(ai_scores)


def test_a_bad_human_post_can_still_be_downvoted(world):
    downvoted = 0
    for seed in range(60):
        ups, downs = vote_service.simulate_votes(
            quality=0.02, controversy=0.9, is_human=True, world=world,
            audience=300, rng=random.Random(seed),
        )
        if downs > ups:
            downvoted += 1
    assert downvoted > 0, "the human bonus must not make downvotes impossible"


def test_apply_simulated_votes_persists_score(post, world):
    updated = vote_service.apply_simulated_votes(
        "post", post["_id"], quality=0.9, world=world, audience=300, rng=random.Random(3)
    )
    assert updated["score"] == updated["ups"] - updated["downs"]
    assert updated["quality"] == 0.9


def test_drift_decays_with_age(board, world):
    fresh = post_service.create(subreddit=board["name"], title="fresh", author="A", author_kind="ai")
    stale = post_service.create(
        subreddit=board["name"], title="stale", author="B", author_kind="ai",
        created_at=now() - 86_400 * 5,
    )
    for post_doc in (fresh, stale):
        db.collection("posts").update(post_doc["_id"], {"$set": {"quality": 0.8, "controversy": 0.2}})

    fresh_gain = 0
    stale_gain = 0
    for seed in range(15):
        fresh_before = post_service.get(fresh["_id"])["ups"]
        vote_service.drift_votes("post", fresh["_id"], world=world, rng=random.Random(seed))
        fresh_gain += post_service.get(fresh["_id"])["ups"] - fresh_before

        stale_before = post_service.get(stale["_id"])["ups"]
        vote_service.drift_votes("post", stale["_id"], world=world, rng=random.Random(seed))
        stale_gain += post_service.get(stale["_id"])["ups"] - stale_before

    assert fresh_gain > stale_gain


def test_drift_on_missing_target_is_safe(world):
    assert vote_service.drift_votes("post", "nope", world=world) is None


def test_hot_rank_prefers_recent_at_equal_score(board):
    old = {"score": 100, "created_at": now() - 86_400}
    new = {"score": 100, "created_at": now()}
    assert vote_service.hot_rank(new) > vote_service.hot_rank(old)


def test_controversial_rank_needs_both_directions():
    assert vote_service.controversial_rank({"ups": 100, "downs": 0}) == 0.0
    assert vote_service.controversial_rank({"ups": 100, "downs": 90}) > 0


# --------------------------------------------------------------------------- #
# Awards
# --------------------------------------------------------------------------- #

def test_catalogue_entries_are_well_formed():
    for award in award_service.catalogue():
        assert {"id", "name", "icon", "cost", "color"} <= set(award)
        assert award["cost"] > 0


def test_grant_award_charges_the_giver_and_pays_the_author(board, person):
    author = user_service.register("author@example.com", "hunter22", "author")
    post = post_service.create(
        subreddit=board["name"], title="t", author="author", author_id=author["_id"]
    )
    coins_before = user_service.get_user(person["_id"])["coins"]

    result = award_service.grant(
        "post", post["_id"], "silver", giver_id=person["_id"], giver_username="realperson"
    )

    cost = result["award"]["cost"]
    assert user_service.get_user(person["_id"])["coins"] == coins_before - cost
    assert user_service.get_user(author["_id"])["coins"] > 500
    assert user_service.get_user(author["_id"])["awards_received"]["silver"] == 1
    assert post_service.get(post["_id"])["awards"]["silver"] == 1


def test_grant_rejects_unknown_award_and_target(post, person):
    with pytest.raises(award_service.AwardError, match="Unknown award"):
        award_service.grant("post", post["_id"], "nonexistent", giver_id=person["_id"])
    with pytest.raises(award_service.AwardError):
        award_service.grant("post", "missing", "silver", giver_id=person["_id"])
    with pytest.raises(award_service.AwardError, match="Cannot award"):
        award_service.grant("board", post["_id"], "silver", giver_id=person["_id"])


def test_grant_requires_enough_coins(post, person):
    db.collection("users").update(person["_id"], {"$set": {"coins": 10}})
    with pytest.raises(award_service.AwardError, match="Not enough coins"):
        award_service.grant("post", post["_id"], "gold", giver_id=person["_id"])


def test_simulated_grants_are_free(post):
    award_service.grant("post", post["_id"], "gold", giver_username="APersona", simulated=True)
    assert post_service.get(post["_id"])["award_total"] == 1


def test_anonymous_grant_hides_the_giver(post, person):
    result = award_service.grant(
        "post", post["_id"], "silver", giver_id=person["_id"],
        giver_username="realperson", anonymous=True,
    )
    assert result["grant"]["giver"] is None
    assert result["grant"]["anonymous"] is True


def test_repeat_awards_accumulate(post):
    for _ in range(3):
        award_service.grant("post", post["_id"], "silver", simulated=True)
    awards = award_service.awards_for("post", post["_id"])
    assert awards[0]["count"] == 3
    assert post_service.get(post["_id"])["award_total"] == 3


def test_maybe_award_favours_popular_content(post, world):
    db.collection("posts").update(post["_id"], {"$set": {"score": 4000, "quality": 0.95}})
    popular = post_service.get(post["_id"])
    granted = sum(
        1
        for seed in range(40)
        if award_service.maybe_award("post", popular, world=world, rng=random.Random(seed))
    )
    assert granted > 0


def test_maybe_award_gives_jeers_to_heavily_downvoted(post, world):
    persona_service.create_fallback_personas(3)
    db.collection("posts").update(post["_id"], {"$set": {"score": -900, "quality": 0.05}})
    hated = post_service.get(post["_id"])
    negative = {"facepalm", "bruh", "pot_stirrer"}
    seen = set()
    for seed in range(80):
        result = award_service.maybe_award(
            "post", hated, world={**world, "award_rate": 1.0}, rng=random.Random(seed)
        )
        if result:
            seen.add(result["award"]["id"])
    assert seen and seen <= negative


def test_maybe_award_respects_a_zero_rate(post, world):
    db.collection("posts").update(post["_id"], {"$set": {"score": 5000, "quality": 1.0}})
    popular = post_service.get(post["_id"])
    assert all(
        award_service.maybe_award("post", popular, world={**world, "award_rate": 0.0},
                                  rng=random.Random(seed)) is None
        for seed in range(20)
    )


# --------------------------------------------------------------------------- #
# Moderation
# --------------------------------------------------------------------------- #

def test_remove_comment_leaves_a_stub_and_keeps_the_original(post):
    comment = comment_service.create(
        post_id=post["_id"], body="you absolute clown", author="A", author_kind="ai"
    )
    removed = moderation_service.remove_comment(comment["_id"], reason="Rule 1: Be civil")

    assert removed["removed"] is True
    assert removed["original_body"] == "you absolute clown"
    assert comment_service.public_comment(removed)["body"] == "[removed]"
    assert comment_service.public_comment(removed)["removal_reason"] == "Rule 1: Be civil"
    assert moderation_service.log_for_board(post["subreddit"])[0]["action"] == "remove_comment"


def test_removing_twice_is_a_no_op(post):
    comment = comment_service.create(post_id=post["_id"], body="x", author="A", author_kind="ai")
    moderation_service.remove_comment(comment["_id"])
    assert moderation_service.remove_comment(comment["_id"]) is None


def test_restore_puts_the_text_back(post):
    comment = comment_service.create(post_id=post["_id"], body="original", author="A", author_kind="ai")
    moderation_service.remove_comment(comment["_id"])
    restored = moderation_service.restore_comment(comment["_id"])
    assert restored["removed"] is False
    assert restored["body"] == "original"


def test_remove_and_restore_post(post):
    moderation_service.remove_post(post["_id"], reason="spam")
    assert post_service.get(post["_id"])["removed"] is True
    moderation_service.restore_post(post["_id"])
    assert post_service.get(post["_id"])["removed"] is False


def test_lock_records_an_action(post):
    moderation_service.set_locked(post["_id"], True)
    assert post_service.get(post["_id"])["locked"] is True
    assert moderation_service.recent_log()[0]["action"] == "lock_post"


def test_heat_score_rises_with_hostility(post):
    calm = [{"body": "interesting point", "tone": "serious"} for _ in range(6)]
    nasty = [{"body": "you absolute moron, shut up", "tone": "angry"} for _ in range(6)]
    assert moderation_service.heat_score([]) == 0.0
    assert moderation_service.heat_score(nasty) > moderation_service.heat_score(calm)


def test_heuristic_pass_targets_hostile_comments(post, world):
    for index in range(8):
        comment_service.create(
            post_id=post["_id"],
            body="you absolute idiot" if index % 2 else "fair enough",
            author=f"P{index}",
            author_kind="ai",
        )
    actions = moderation_service.heuristic_pass(
        post["_id"], world={**world, "removal_rate": 1.0, "moderation_strictness": 1.0},
        rng=random.Random(1),
    )
    removed_bodies = [action.get("original_body", "") for action in actions if "original_body" in action]
    assert removed_bodies
    assert any("idiot" in body for body in removed_bodies)


def test_heuristic_pass_spares_humans_by_default(post, person, world):
    comment_service.create(
        post_id=post["_id"], body="you absolute idiot", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    moderation_service.heuristic_pass(
        post["_id"], world={**world, "removal_rate": 1.0, "moderation_strictness": 1.0},
        rng=random.Random(1),
    )
    assert db.collection("comments").count({"removed": True}) == 0


def test_heuristic_pass_can_moderate_humans_when_enabled(post, person, world):
    comment_service.create(
        post_id=post["_id"], body="you absolute idiot", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    moderation_service.heuristic_pass(
        post["_id"],
        world={**world, "removal_rate": 1.0, "moderation_strictness": 1.0,
               "moderate_user_content": True},
        rng=random.Random(1),
    )
    assert db.collection("comments").count({"removed": True}) == 1


def test_moderation_off_removes_nothing(post, world):
    comment_service.create(post_id=post["_id"], body="you absolute idiot", author="A", author_kind="ai")
    assert moderation_service.heuristic_pass(
        post["_id"], world={**world, "moderation_enabled": False}
    ) == []


async def test_ai_pass_runs_offline_without_removing_everything(post, world):
    for index in range(5):
        comment_service.create(
            post_id=post["_id"], body=f"comment {index}", author=f"P{index}", author_kind="ai"
        )
    await moderation_service.ai_pass(post["_id"], world=world)
    assert db.collection("comments").count({"removed": False}) >= 4


def test_report_is_recorded(post, person):
    entry = moderation_service.report("post", post["_id"], "spam", reporter_id=person["_id"])
    assert entry["status"] == "open"
    assert db.collection("reports").count() == 1


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def test_reply_to_a_human_post_notifies_them(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    reply = comment_service.create(
        post_id=post["_id"], body="nice", author="APersona", author_kind="ai"
    )
    notification_service.notify_reply(reply, None, post)
    inbox = notification_service.list_for(person["_id"])
    assert inbox[0]["kind"] == "post_reply"
    assert notification_service.unread_count(person["_id"]) == 1


def test_reply_to_a_human_comment_notifies_them(post, person):
    mine = comment_service.create(
        post_id=post["_id"], body="mine", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    reply = comment_service.create(
        post_id=post["_id"], parent_id=mine["_id"], body="theirs",
        author="APersona", author_kind="ai",
    )
    notification_service.notify_reply(reply, mine, post)
    assert notification_service.list_for(person["_id"])[0]["kind"] == "comment_reply"


def test_personas_receive_no_notifications(post):
    theirs = comment_service.create(post_id=post["_id"], body="a", author="A", author_kind="ai")
    reply = comment_service.create(
        post_id=post["_id"], parent_id=theirs["_id"], body="b", author="B", author_kind="ai"
    )
    notification_service.notify_reply(reply, theirs, post)
    assert db.collection("notifications").count() == 0


def test_self_replies_do_not_notify(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    mine = comment_service.create(
        post_id=post["_id"], body="a", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    notification_service.notify_reply(mine, None, post)
    assert db.collection("notifications").count() == 0


def test_award_notification_names_the_giver(board, person):
    post = post_service.create(
        subreddit=board["name"], title="t", author="realperson",
        author_id=person["_id"], author_kind="human",
    )
    notification_service.notify_award(post, award_service.AWARDS_BY_ID["gold"], "SomeoneNice")
    entry = notification_service.list_for(person["_id"])[0]
    assert "Gold" in entry["title"]
    assert "SomeoneNice" in entry["body"]


def test_mark_read_and_clear(person):
    for index in range(3):
        notification_service.push(person["_id"], "system", title=f"n{index}")
    assert notification_service.unread_count(person["_id"]) == 3
    notification_service.mark_all_read(person["_id"])
    assert notification_service.unread_count(person["_id"]) == 0
    assert notification_service.clear(person["_id"]) == 3


def test_push_rejects_unknown_kind(person):
    assert notification_service.push(person["_id"], "not-a-kind", title="x") is None
    assert notification_service.push("", "system", title="x") is None


async def test_ai_pass_respects_an_explicit_allow_everything(post, world, monkeypatch):
    """An empty decisions list means 'nothing to remove', not 'model failed'.

    Falling through to the random heuristic here would delete comments the
    moderator had just explicitly cleared.
    """
    for index in range(5):
        comment_service.create(
            post_id=post["_id"], body=f"comment {index}", author=f"P{index}", author_kind="ai"
        )

    async def allow_all(*args, **kwargs):
        from app.llm.base import LLMResponse

        return {"decisions": []}, LLMResponse(text="{}", model="m", provider="p")

    monkeypatch.setattr(moderation_service.router, "generate_json", allow_all)

    assert await moderation_service.ai_pass(post["_id"], world=world) == []
    assert db.collection("comments").count({"removed": True}) == 0


async def test_ai_pass_falls_back_when_the_model_returns_junk(post, world, monkeypatch):
    comment_service.create(post_id=post["_id"], body="x", author="P", author_kind="ai")

    async def junk(*args, **kwargs):
        from app.llm.base import LLMResponse

        return None, LLMResponse(text="not json", model="m", provider="p")

    monkeypatch.setattr(moderation_service.router, "generate_json", junk)

    # Reaching the heuristic at all is the point; it may or may not remove.
    result = await moderation_service.ai_pass(
        post["_id"], world={**world, "removal_rate": 0.0}
    )
    assert result == []
