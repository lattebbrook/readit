"""Unit tests for the in-memory document store."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.db.memdb import MemoryDB, apply_update, matches


@pytest.fixture
def store():
    return MemoryDB()


# --------------------------------------------------------------------------- #
# Query matching
# --------------------------------------------------------------------------- #

def test_matches_equality_and_missing_fields():
    doc = {"name": "funny", "score": 10}
    assert matches(doc, {"name": "funny"})
    assert not matches(doc, {"name": "sad"})
    assert not matches(doc, {"missing": "anything"})
    assert matches(doc, None)
    assert matches(doc, {})


def test_matches_comparison_operators():
    doc = {"score": 10, "tags": ["a", "b"]}
    assert matches(doc, {"score": {"$gt": 5}})
    assert matches(doc, {"score": {"$gte": 10, "$lte": 10}})
    assert not matches(doc, {"score": {"$lt": 5}})
    assert matches(doc, {"score": {"$in": [1, 10]}})
    assert matches(doc, {"score": {"$nin": [1, 2]}})
    assert matches(doc, {"tags": {"$all": ["a", "b"]}})
    assert matches(doc, {"tags": {"$size": 2}})


def test_matches_list_membership_shorthand():
    doc = {"tags": ["funny", "sad"]}
    assert matches(doc, {"tags": "funny"})
    assert not matches(doc, {"tags": "angry"})


def test_matches_exists_distinguishes_none_from_absent():
    assert matches({"a": None}, {"a": {"$exists": True}})
    assert matches({}, {"a": {"$exists": False}})
    assert not matches({}, {"a": {"$exists": True}})


def test_matches_dotted_paths_and_logic():
    doc = {"author": {"name": "sam"}, "score": 3}
    assert matches(doc, {"author.name": "sam"})
    assert matches(doc, {"$or": [{"score": 99}, {"author.name": "sam"}]})
    assert matches(doc, {"$and": [{"score": 3}, {"author.name": "sam"}]})
    assert matches(doc, {"$not": {"score": 99}})


def test_matches_regex_is_case_insensitive():
    assert matches({"title": "Hello World"}, {"title": {"$regex": "hello"}})


def test_mismatched_types_do_not_raise():
    assert not matches({"score": "high"}, {"score": {"$gt": 5}})


def test_unknown_operator_raises():
    with pytest.raises(ValueError, match="Unsupported query operator"):
        matches({"a": 1}, {"a": {"$wat": 1}})


# --------------------------------------------------------------------------- #
# Update operators
# --------------------------------------------------------------------------- #

def test_apply_update_operators():
    doc = {"score": 1, "tags": ["a"], "nested": {"count": 2}}
    apply_update(doc, {"$inc": {"score": 4, "nested.count": 1}})
    assert doc["score"] == 5
    assert doc["nested"]["count"] == 3

    apply_update(doc, {"$push": {"tags": "b"}})
    apply_update(doc, {"$addToSet": {"tags": "b"}})
    assert doc["tags"] == ["a", "b"]

    apply_update(doc, {"$pull": {"tags": "a"}})
    assert doc["tags"] == ["b"]

    apply_update(doc, {"$set": {"nested.deep.value": 7}})
    assert doc["nested"]["deep"]["value"] == 7

    apply_update(doc, {"$unset": {"score": True}})
    assert "score" not in doc


def test_apply_update_without_operators_merges():
    doc = {"a": 1}
    apply_update(doc, {"b": 2})
    assert doc == {"a": 1, "b": 2}


def test_inc_on_missing_field_starts_at_zero():
    doc: dict = {}
    apply_update(doc, {"$inc": {"votes": 3}})
    assert doc["votes"] == 3


# --------------------------------------------------------------------------- #
# Collections
# --------------------------------------------------------------------------- #

def test_insert_assigns_id_and_timestamp(store):
    doc = store.collection("posts").insert({"title": "hi"})
    assert doc["_id"]
    assert doc["created_at"] > 0


def test_documents_are_copied_not_shared(store):
    posts = store.collection("posts")
    original = {"title": "hi", "tags": ["a"]}
    stored = posts.insert(original)
    original["tags"].append("mutated")
    assert posts.get(stored["_id"])["tags"] == ["a"]

    fetched = posts.get(stored["_id"])
    fetched["title"] = "changed"
    assert posts.get(stored["_id"])["title"] == "hi"


def test_duplicate_id_rejected(store):
    posts = store.collection("posts")
    posts.insert({"_id": "fixed", "title": "one"})
    with pytest.raises(KeyError):
        posts.insert({"_id": "fixed", "title": "two"})


def test_update_and_delete(store):
    posts = store.collection("posts")
    doc = posts.insert({"title": "hi", "score": 1})
    updated = posts.update(doc["_id"], {"$inc": {"score": 5}})
    assert updated["score"] == 6
    assert updated["updated_at"] >= updated["created_at"]
    assert posts.update("missing", {"$set": {"a": 1}}) is None
    assert posts.delete(doc["_id"]) is True
    assert posts.delete(doc["_id"]) is False


def test_find_sort_limit_skip(store):
    posts = store.collection("posts")
    for index in range(5):
        posts.insert({"title": f"p{index}", "score": index})

    top = posts.find(sort=[("score", -1)], limit=2)
    assert [doc["score"] for doc in top] == [4, 3]

    skipped = posts.find(sort=[("score", 1)], skip=3)
    assert [doc["score"] for doc in skipped] == [3, 4]


def test_sorting_tolerates_mixed_and_missing_values(store):
    posts = store.collection("posts")
    posts.insert({"score": 5})
    posts.insert({"score": None})
    posts.insert({"title": "no score"})
    posts.insert({"score": "text"})
    assert len(posts.find(sort=[("score", -1)])) == 4


def test_index_returns_same_results_as_scan(store):
    posts = store.collection("posts")
    posts.create_index("subreddit")
    for index in range(20):
        posts.insert({"subreddit": "funny" if index % 2 else "sad", "n": index})

    assert posts.count({"subreddit": "funny"}) == 10
    assert len(posts.find({"subreddit": {"$in": ["funny", "sad"]}})) == 20


def test_index_updated_on_write(store):
    posts = store.collection("posts")
    posts.create_index("subreddit")
    doc = posts.insert({"subreddit": "funny"})
    posts.update(doc["_id"], {"$set": {"subreddit": "sad"}})
    assert posts.count({"subreddit": "funny"}) == 0
    assert posts.count({"subreddit": "sad"}) == 1
    posts.delete(doc["_id"])
    assert posts.count({"subreddit": "sad"}) == 0


def test_index_created_after_inserts_backfills(store):
    posts = store.collection("posts")
    posts.insert({"subreddit": "funny"})
    posts.create_index("subreddit")
    assert posts.count({"subreddit": "funny"}) == 1


def test_index_on_list_field_matches_membership(store):
    users = store.collection("users")
    users.create_index("subscriptions")
    users.insert({"subscriptions": ["funny", "sad"]})
    assert users.count({"subscriptions": "funny"}) == 1


def test_upsert_inserts_then_updates(store):
    votes = store.collection("votes")
    first = votes.upsert({"user_id": "u1", "target": "p1"}, {"direction": 1})
    assert first["direction"] == 1
    second = votes.upsert({"user_id": "u1", "target": "p1"}, {"direction": -1})
    assert second["_id"] == first["_id"]
    assert second["direction"] == -1
    assert votes.count() == 1


def test_update_many_and_delete_many(store):
    posts = store.collection("posts")
    for index in range(6):
        posts.insert({"flag": index % 2 == 0})
    assert posts.update_many({"flag": True}, {"$set": {"seen": True}}) == 3
    assert posts.count({"seen": True}) == 3
    assert posts.delete_many({"flag": True}) == 3
    assert posts.count() == 3


def test_attribute_and_item_access_return_same_collection(store):
    assert store.posts is store["posts"]
    assert store.collection("posts") is store.posts


def test_private_attribute_access_raises(store):
    with pytest.raises(AttributeError):
        _ = store._secret


def test_snapshot_round_trip(store):
    store.collection("posts").insert({"title": "persisted"})
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "snap.json")
        assert store.save_snapshot(path) == path

        restored = MemoryDB()
        assert restored.load_snapshot(path) is True
        assert restored.collection("posts").count() == 1
        assert restored.collection("posts").find_one()["title"] == "persisted"


def test_load_snapshot_handles_missing_and_corrupt_files(store):
    assert store.load_snapshot("/nonexistent/nope.json") is False
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        assert store.load_snapshot(path) is False


def test_snapshot_write_is_atomic(store):
    store.collection("posts").insert({"title": "a"})
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "snap.json")
        store.save_snapshot(path)
        assert not os.path.exists(f"{path}.tmp")
        with open(path, encoding="utf-8") as handle:
            assert "posts" in json.load(handle)


def test_stats_and_drop_all(store):
    store.collection("posts").insert({"a": 1})
    store.collection("users").insert({"b": 2})
    assert store.stats() == {"posts": 1, "users": 1}
    store.drop_all()
    assert store.stats() == {"posts": 0, "users": 0}
    assert store.collection_names() == ["posts", "users"]


def test_indexed_queries_return_insertion_order(store):
    """An index must not change the order results come back in.

    Index buckets are sets of id strings, so iterating one directly exposes
    Python's per-process hash seed and makes the same query answer differently
    on every run.
    """
    posts = store.collection("posts")
    posts.create_index("subreddit")
    inserted = [posts.insert({"subreddit": "funny", "n": i})["_id"] for i in range(40)]

    assert [doc["_id"] for doc in posts.find({"subreddit": "funny"})] == inserted


def test_indexed_and_unindexed_queries_agree_on_order(store):
    indexed = store.collection("indexed")
    indexed.create_index("group")
    plain = store.collection("plain")
    for i in range(25):
        indexed.insert({"_id": f"d{i}", "group": "g", "n": i})
        plain.insert({"_id": f"d{i}", "group": "g", "n": i})

    assert [d["_id"] for d in indexed.find({"group": "g"})] == [
        d["_id"] for d in plain.find({"group": "g"})
    ]


def test_in_query_over_an_index_keeps_insertion_order(store):
    posts = store.collection("posts")
    posts.create_index("subreddit")
    order = [posts.insert({"subreddit": "a" if i % 2 else "b", "n": i})["_id"] for i in range(30)]

    found = [doc["_id"] for doc in posts.find({"subreddit": {"$in": ["a", "b"]}})]
    assert found == order
