"""In-memory NoSQL document store.

A small, dependency-free document database that behaves like a minimal MongoDB:
collections of JSON-ish documents, dict-based queries with operators, indexes for
equality lookups, sorting/pagination, and atomic-ish updates guarded by a lock.

Everything lives in RAM. An optional JSON snapshot lets a process restart without
losing user accounts and boards; the snapshot is a convenience, not a dependency.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Iterable

Document = dict[str, Any]
Query = dict[str, Any]


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# Query matching
# --------------------------------------------------------------------------- #

def _resolve(doc: Document, path: str) -> Any:
    """Resolve a dotted path such as ``author.name`` inside a document."""
    current: Any = doc
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


class _Missing:
    """Sentinel distinguishing "absent" from a stored ``None``."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


_MISSING = _Missing()


def _compare(left: Any, right: Any, op: Callable[[Any, Any], bool]) -> bool:
    """Compare values, treating type mismatches as a non-match instead of raising."""
    try:
        return op(left, right)
    except TypeError:
        return False


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "$eq": lambda value, expected: value == expected,
    "$ne": lambda value, expected: value != expected,
    "$gt": lambda value, expected: _compare(value, expected, lambda a, b: a > b),
    "$gte": lambda value, expected: _compare(value, expected, lambda a, b: a >= b),
    "$lt": lambda value, expected: _compare(value, expected, lambda a, b: a < b),
    "$lte": lambda value, expected: _compare(value, expected, lambda a, b: a <= b),
    "$in": lambda value, expected: value in expected,
    "$nin": lambda value, expected: value not in expected,
    "$exists": lambda value, expected: (value is not _MISSING) == bool(expected),
    "$contains": lambda value, expected: bool(value) and expected in value,
    "$regex": lambda value, expected: isinstance(value, str)
    and re.search(expected, value, re.IGNORECASE) is not None,
    "$all": lambda value, expected: isinstance(value, (list, tuple))
    and all(item in value for item in expected),
    "$size": lambda value, expected: hasattr(value, "__len__") and len(value) == expected,
}


def matches(doc: Document, query: Query | None) -> bool:
    """Return True when ``doc`` satisfies ``query``.

    Supports ``$and`` / ``$or`` / ``$not`` at the top level, comparison operators
    per field, and plain equality (with list membership as a convenience, so
    ``{"tags": "funny"}`` matches a document whose ``tags`` list contains it).
    """
    if not query:
        return True

    for key, condition in query.items():
        if key == "$and":
            if not all(matches(doc, sub) for sub in condition):
                return False
            continue
        if key == "$or":
            if not any(matches(doc, sub) for sub in condition):
                return False
            continue
        if key == "$not":
            if matches(doc, condition):
                return False
            continue

        value = _resolve(doc, key)

        if isinstance(condition, dict) and any(k.startswith("$") for k in condition):
            for op_name, expected in condition.items():
                handler = _OPERATORS.get(op_name)
                if handler is None:
                    raise ValueError(f"Unsupported query operator: {op_name}")
                if op_name != "$exists" and value is _MISSING:
                    return False
                if not handler(value, expected):
                    return False
            continue

        if value is _MISSING:
            return False
        if isinstance(value, list) and not isinstance(condition, list):
            if condition not in value:
                return False
            continue
        if value != condition:
            return False

    return True


def apply_update(doc: Document, changes: Query) -> Document:
    """Apply Mongo-style update operators (or a plain field merge) to ``doc``."""
    has_operators = any(key.startswith("$") for key in changes)
    if not has_operators:
        doc.update(copy.deepcopy(changes))
        return doc

    for op_name, payload in changes.items():
        if op_name == "$set":
            for path, value in payload.items():
                _assign(doc, path, copy.deepcopy(value))
        elif op_name == "$unset":
            for path in payload:
                _remove(doc, path)
        elif op_name == "$inc":
            for path, delta in payload.items():
                current = _resolve(doc, path)
                base = 0 if current is _MISSING or current is None else current
                _assign(doc, path, base + delta)
        elif op_name == "$push":
            for path, value in payload.items():
                current = _resolve(doc, path)
                target = [] if current is _MISSING or current is None else list(current)
                target.append(copy.deepcopy(value))
                _assign(doc, path, target)
        elif op_name == "$addToSet":
            for path, value in payload.items():
                current = _resolve(doc, path)
                target = [] if current is _MISSING or current is None else list(current)
                if value not in target:
                    target.append(copy.deepcopy(value))
                _assign(doc, path, target)
        elif op_name == "$pull":
            for path, value in payload.items():
                current = _resolve(doc, path)
                if isinstance(current, list):
                    _assign(doc, path, [item for item in current if item != value])
        else:
            raise ValueError(f"Unsupported update operator: {op_name}")
    return doc


def _assign(doc: Document, path: str, value: Any) -> None:
    parts = path.split(".")
    target = doc
    for part in parts[:-1]:
        nxt = target.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            target[part] = nxt
        target = nxt
    target[parts[-1]] = value


def _remove(doc: Document, path: str) -> None:
    parts = path.split(".")
    target = doc
    for part in parts[:-1]:
        nxt = target.get(part)
        if not isinstance(nxt, dict):
            return
        target = nxt
    target.pop(parts[-1], None)


# --------------------------------------------------------------------------- #
# Collections
# --------------------------------------------------------------------------- #

class Collection:
    """A named set of documents with equality indexes and dict queries."""

    def __init__(self, name: str, lock: threading.RLock) -> None:
        self.name = name
        self._lock = lock
        self._docs: dict[str, Document] = {}
        self._indexes: dict[str, dict[Any, set[str]]] = {}

    # -- indexing ----------------------------------------------------------- #

    def create_index(self, field: str) -> None:
        with self._lock:
            if field in self._indexes:
                return
            index: dict[Any, set[str]] = {}
            for doc_id, doc in self._docs.items():
                self._index_add(index, doc, doc_id, field)
            self._indexes[field] = index

    @staticmethod
    def _index_keys(doc: Document, field: str) -> list[Any]:
        value = _resolve(doc, field)
        if value is _MISSING:
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, (str, int, float, bool))]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return [value]
        return []

    def _index_add(
        self, index: dict[Any, set[str]], doc: Document, doc_id: str, field: str
    ) -> None:
        for key in self._index_keys(doc, field):
            index.setdefault(key, set()).add(doc_id)

    def _index_remove(self, doc: Document, doc_id: str) -> None:
        for field, index in self._indexes.items():
            for key in self._index_keys(doc, field):
                bucket = index.get(key)
                if bucket:
                    bucket.discard(doc_id)
                    if not bucket:
                        index.pop(key, None)

    def _index_insert(self, doc: Document, doc_id: str) -> None:
        for field, index in self._indexes.items():
            self._index_add(index, doc, doc_id, field)

    def _candidates(self, query: Query | None) -> Iterable[Document] | None:
        """Narrow the scan using an index when the query allows it."""
        if not query:
            return None
        for field, index in self._indexes.items():
            if field not in query:
                continue
            condition = query[field]
            if isinstance(condition, dict):
                if set(condition) == {"$eq"}:
                    ids = index.get(condition["$eq"], set())
                elif set(condition) == {"$in"}:
                    ids = set()
                    for value in condition["$in"]:
                        ids |= index.get(value, set())
                else:
                    continue
            elif isinstance(condition, (str, int, float, bool)) or condition is None:
                ids = index.get(condition, set())
            else:
                continue
            # Indexes hold ids in a set, whose iteration order follows Python's
            # per-process string hash seed. Returning that raw makes the same
            # query yield a different order on every run, and makes an indexed
            # field behave differently from an unindexed one — a difference that
            # should never be observable. Walk the document map instead so
            # results always arrive in insertion order.
            #
            # The index still earns its keep: it decides which documents reach
            # the comparatively expensive `matches()` call below. A set
            # membership test per document is not what costs anything here.
            return [doc for doc_id, doc in self._docs.items() if doc_id in ids]
        return None

    # -- writes -------------------------------------------------------------- #

    def insert(self, doc: Document) -> Document:
        with self._lock:
            stored = copy.deepcopy(doc)
            doc_id = stored.get("_id") or new_id()
            stored["_id"] = doc_id
            stored.setdefault("created_at", now())
            if doc_id in self._docs:
                raise KeyError(f"Duplicate _id in {self.name}: {doc_id}")
            self._docs[doc_id] = stored
            self._index_insert(stored, doc_id)
            return copy.deepcopy(stored)

    def insert_many(self, docs: Iterable[Document]) -> list[Document]:
        return [self.insert(doc) for doc in docs]

    def update(self, doc_id: str, changes: Query) -> Document | None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc is None:
                return None
            self._index_remove(doc, doc_id)
            apply_update(doc, changes)
            doc["_id"] = doc_id
            doc["updated_at"] = now()
            self._index_insert(doc, doc_id)
            return copy.deepcopy(doc)

    def update_many(self, query: Query, changes: Query) -> int:
        with self._lock:
            targets = [doc["_id"] for doc in self._iter(query)]
            for doc_id in targets:
                self.update(doc_id, changes)
            return len(targets)

    def upsert(self, query: Query, doc: Document) -> Document:
        with self._lock:
            existing = self.find_one(query)
            if existing:
                return self.update(existing["_id"], {"$set": doc}) or existing
            merged = {**{k: v for k, v in query.items() if not k.startswith("$")}, **doc}
            return self.insert(merged)

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            doc = self._docs.pop(doc_id, None)
            if doc is None:
                return False
            self._index_remove(doc, doc_id)
            return True

    def delete_many(self, query: Query) -> int:
        with self._lock:
            targets = [doc["_id"] for doc in self._iter(query)]
            for doc_id in targets:
                self.delete(doc_id)
            return len(targets)

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()
            for index in self._indexes.values():
                index.clear()

    # -- reads --------------------------------------------------------------- #

    def _iter(self, query: Query | None) -> list[Document]:
        candidates = self._candidates(query)
        source = candidates if candidates is not None else self._docs.values()
        return [doc for doc in source if matches(doc, query)]

    def get(self, doc_id: str) -> Document | None:
        with self._lock:
            doc = self._docs.get(doc_id)
            return copy.deepcopy(doc) if doc else None

    def find_one(self, query: Query | None = None) -> Document | None:
        with self._lock:
            for doc in self._iter(query):
                return copy.deepcopy(doc)
            return None

    def find(
        self,
        query: Query | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
        skip: int = 0,
    ) -> list[Document]:
        with self._lock:
            results = self._iter(query)
            if sort:
                for field, direction in reversed(sort):
                    results.sort(
                        key=lambda doc, f=field: _sort_key(_resolve(doc, f)),
                        reverse=direction < 0,
                    )
            if skip:
                results = results[skip:]
            if limit is not None:
                results = results[:limit]
            return [copy.deepcopy(doc) for doc in results]

    def count(self, query: Query | None = None) -> int:
        with self._lock:
            return len(self._iter(query))

    def exists(self, query: Query) -> bool:
        return self.find_one(query) is not None

    def all(self) -> list[Document]:
        return self.find()

    def __len__(self) -> int:
        return len(self._docs)


def _sort_key(value: Any) -> tuple[int, Any]:
    """Sort key that keeps mixed/missing types orderable."""
    if value is _MISSING or value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    return (3, str(value))


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

class MemoryDB:
    """Container of collections plus optional JSON snapshotting."""

    def __init__(self, snapshot_path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._collections: dict[str, Collection] = {}
        self.snapshot_path = snapshot_path

    def collection(self, name: str) -> Collection:
        with self._lock:
            if name not in self._collections:
                self._collections[name] = Collection(name, self._lock)
            return self._collections[name]

    def __getitem__(self, name: str) -> Collection:
        return self.collection(name)

    def __getattr__(self, name: str) -> Collection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.collection(name)

    def collection_names(self) -> list[str]:
        return sorted(self._collections)

    def drop_all(self) -> None:
        with self._lock:
            for collection in self._collections.values():
                collection.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {name: len(col) for name, col in self._collections.items()}

    # -- persistence ---------------------------------------------------------- #

    def to_dict(self) -> dict[str, list[Document]]:
        with self._lock:
            return {name: col.all() for name, col in self._collections.items()}

    def load_dict(self, payload: dict[str, list[Document]]) -> None:
        with self._lock:
            for name, docs in payload.items():
                collection = self.collection(name)
                collection.clear()
                for doc in docs:
                    collection.insert(doc)

    def save_snapshot(self, path: str | None = None) -> str | None:
        target = path or self.snapshot_path
        if not target:
            return None
        with self._lock:
            payload = self.to_dict()
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, target)
        return target

    def load_snapshot(self, path: str | None = None) -> bool:
        target = path or self.snapshot_path
        if not target or not os.path.exists(target):
            return False
        try:
            with open(target, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return False
        self.load_dict(payload)
        return True
