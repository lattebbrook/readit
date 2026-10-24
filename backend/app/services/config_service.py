"""Site-wide configuration: the world prompt/knobs and LLM connection settings.

Both live in the ``config`` collection as singleton documents keyed by ``key``.
The world document is what admins tune to steer the entire board; the llm
document holds provider credentials and per-role model routing.
"""

from __future__ import annotations

import copy
from typing import Any

from app.db import db, new_id, now
from app.llm.providers import PROVIDER_DEFAULT_MODELS

WORLD_KEY = "world"
LLM_KEY = "llm"

DEFAULT_GLOBAL_PROMPT = (
    "ReadIt is a sprawling, chaotic, very-online public forum in the spirit of a large "
    "link aggregator. Its people are ordinary internet strangers: funny, petty, generous, "
    "know-it-all, tired, passionate. Threads should feel unmistakably real — inside jokes, "
    "typos, half-remembered facts confidently stated, someone correcting them, someone else "
    "correcting the correction. Not everything is agreeable: expect sarcasm, mockery, blunt "
    "disagreement and genuine arguments that escalate. Expect warmth too — people helping "
    "strangers at 3am for no reason. Never write like a press release, a customer service "
    "agent, or an AI assistant. Nobody here is an assistant. Nobody says 'as an AI'."
)

DEFAULT_STYLE_PROMPT = (
    "Write like real forum users type. Vary length hard: most comments are one or two lines, "
    "some are a single word or an emoji, a few are long effortposts. Lowercase is common. "
    "Use forum shorthand naturally (op, imo, tbh, ymmv, edit:, /s, this.). Sometimes reply to "
    "the person above rather than the post. Sometimes derail into a tangent. Do not number "
    "your comments, do not summarise the thread, do not be evenhanded for its own sake."
)

DEFAULT_WORLD: dict[str, Any] = {
    "key": WORLD_KEY,
    "global_prompt": DEFAULT_GLOBAL_PROMPT,
    "style_prompt": DEFAULT_STYLE_PROMPT,
    "site_description": "The front page of a very fake internet.",
    # A high-priority, site-wide policy. Unlike the numeric knobs, boards and
    # reader preferences cannot dilute this after an admin enables it.
    "serious_mode": False,
    # Behavioural knobs, all 0..1 unless noted.
    "humor": 0.55,
    "toxicity": 0.35,
    "argument_rate": 0.30,
    "wholesomeness": 0.40,
    "shitpost_rate": 0.25,
    "expertise": 0.45,
    "comment_density": "normal",  # sparse | normal | busy | chaotic
    "thread_depth": 4,
    "allow_nsfw": True,
    # Moderation.
    "moderation_enabled": True,
    "moderation_strictness": 0.45,
    "removal_rate": 0.08,
    # Economy.
    "award_rate": 0.12,
    "user_vote_bonus": 0.35,  # how much friendlier votes are toward human posts
    "vote_volatility": 0.5,
    # Simulation.
    "simulation_enabled": True,
    "background_activity": True,
    "tick_seconds": 12.0,
    "max_comments_per_thread": 150,
    "posts_per_board_target": 12,
}

DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    "post": {"connection_id": None, "model": "", "temperature": 1.0, "max_tokens": 2400},
    "comment": {"connection_id": None, "model": "", "temperature": 1.05, "max_tokens": 3000},
    "moderation": {"connection_id": None, "model": "", "temperature": 0.2, "max_tokens": 600},
    "persona": {"connection_id": None, "model": "", "temperature": 1.1, "max_tokens": 1600},
    "utility": {"connection_id": None, "model": "", "temperature": 0.7, "max_tokens": 1200},
    # Runs once per image at ingest, never on the hot path — so it can point at
    # a slower, better vision model than the roles that fire per comment.
    "vision": {"connection_id": None, "model": "", "temperature": 0.4, "max_tokens": 1400},
}

DEFAULT_LLM: dict[str, Any] = {
    "key": LLM_KEY,
    "connections": [],
    "roles": copy.deepcopy(DEFAULT_ROLES),
    "fallback_to_mock": True,
    "default_connection_id": None,
    # When several connections are enabled, spread generation across them so
    # different board voices come from different models.
    "multi_model_mixing": True,
}


def _config() -> Any:
    return db.collection("config")


def _get_or_create(key: str, default: dict[str, Any]) -> dict[str, Any]:
    doc = _config().find_one({"key": key})
    if doc is None:
        doc = _config().insert(copy.deepcopy(default))
    else:
        # Backfill any key added since the document was first written.
        missing = {k: v for k, v in default.items() if k not in doc}
        if missing:
            doc = _config().update(doc["_id"], {"$set": missing}) or doc
    return doc


# --------------------------------------------------------------------------- #
# World settings
# --------------------------------------------------------------------------- #

def get_world() -> dict[str, Any]:
    return _get_or_create(WORLD_KEY, DEFAULT_WORLD)


def update_world(changes: dict[str, Any]) -> dict[str, Any]:
    world = get_world()
    allowed = {k: v for k, v in changes.items() if k in DEFAULT_WORLD and k != "key"}
    if not allowed:
        return world
    return _config().update(world["_id"], {"$set": allowed}) or world


def reset_world() -> dict[str, Any]:
    world = get_world()
    payload = {k: v for k, v in copy.deepcopy(DEFAULT_WORLD).items() if k != "key"}
    return _config().update(world["_id"], {"$set": payload}) or world


# --------------------------------------------------------------------------- #
# LLM connections
# --------------------------------------------------------------------------- #

def get_llm_config() -> dict[str, Any]:
    doc = _get_or_create(LLM_KEY, DEFAULT_LLM)
    roles = doc.get("roles") or {}
    missing_roles = {name: cfg for name, cfg in DEFAULT_ROLES.items() if name not in roles}
    if missing_roles:
        roles = {**roles, **copy.deepcopy(missing_roles)}
        doc = _config().update(doc["_id"], {"$set": {"roles": roles}}) or doc

    # Connections saved before per-connection pacing existed have neither
    # field; fill them in from the provider defaults rather than making the
    # user delete and re-add a working connection.
    connections = doc.get("connections") or []
    if any("timeout" not in c or "concurrency" not in c for c in connections):
        patched = copy.deepcopy(connections)
        for connection in patched:
            defaults = provider_defaults(connection.get("provider_type", "mock"))
            connection.setdefault("timeout", defaults["timeout"])
            connection.setdefault("concurrency", defaults["concurrency"])
        doc = _config().update(doc["_id"], {"$set": {"connections": patched}}) or doc
    return doc


def _mask(secret: str | None) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}{'•' * 8}{secret[-4:]}"


def public_llm_config() -> dict[str, Any]:
    """LLM config with API keys masked — safe to send to the admin UI."""
    config = copy.deepcopy(get_llm_config())
    for connection in config.get("connections", []):
        connection["api_key_preview"] = _mask(connection.get("api_key"))
        connection["has_api_key"] = bool(connection.get("api_key"))
        connection.pop("api_key", None)
    return config


# A self-hosted runtime is one model on one GPU: parallel requests queue behind
# each other and stall rather than finishing sooner, so hold them to one at a
# time and give each far longer to finish. Hosted APIs have neither problem.
LOCAL_PROVIDER_TYPES = {"lmstudio", "openai_compatible"}
LOCAL_DEFAULT_TIMEOUT = 600.0
LOCAL_DEFAULT_CONCURRENCY = 1
HOSTED_DEFAULT_TIMEOUT = 90.0
HOSTED_DEFAULT_CONCURRENCY = 4


def provider_defaults(provider_type: str) -> dict[str, Any]:
    if provider_type in LOCAL_PROVIDER_TYPES:
        return {"timeout": LOCAL_DEFAULT_TIMEOUT, "concurrency": LOCAL_DEFAULT_CONCURRENCY}
    return {"timeout": HOSTED_DEFAULT_TIMEOUT, "concurrency": HOSTED_DEFAULT_CONCURRENCY}


def add_connection(payload: dict[str, Any]) -> dict[str, Any]:
    config = get_llm_config()
    provider_type = payload.get("provider_type", "mock")
    defaults = provider_defaults(provider_type)
    connection = {
        "id": new_id(),
        "name": payload.get("name") or provider_type.replace("_", " ").title(),
        "provider_type": provider_type,
        "api_key": payload.get("api_key", ""),
        "base_url": payload.get("base_url", ""),
        "models": payload.get("models") or list(PROVIDER_DEFAULT_MODELS.get(provider_type, [])),
        "enabled": payload.get("enabled", True),
        "weight": payload.get("weight", 1),
        "timeout": payload.get("timeout") or defaults["timeout"],
        "concurrency": payload.get("concurrency") or defaults["concurrency"],
        "extra_headers": payload.get("extra_headers") or {},
        "created_at": now(),
    }
    connections = [*config.get("connections", []), connection]
    updates: dict[str, Any] = {"connections": connections}
    if not config.get("default_connection_id"):
        updates["default_connection_id"] = connection["id"]
        roles = copy.deepcopy(config.get("roles") or DEFAULT_ROLES)
        for role in roles.values():
            if not role.get("connection_id"):
                role["connection_id"] = connection["id"]
                role["model"] = connection["models"][0] if connection["models"] else ""
        updates["roles"] = roles
    _config().update(config["_id"], {"$set": updates})
    return connection


def update_connection(connection_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    config = get_llm_config()
    connections = copy.deepcopy(config.get("connections", []))
    target = None
    for connection in connections:
        if connection["id"] == connection_id:
            target = connection
            break
    if target is None:
        return None
    for field in (
        "name", "provider_type", "base_url", "models", "enabled", "weight",
        "timeout", "concurrency", "extra_headers",
    ):
        if field in changes:
            target[field] = changes[field]
    # An empty api_key means "leave the stored key alone".
    if changes.get("api_key"):
        target["api_key"] = changes["api_key"]
    if changes.get("clear_api_key"):
        target["api_key"] = ""
    _config().update(config["_id"], {"$set": {"connections": connections}})
    return target


def delete_connection(connection_id: str) -> bool:
    config = get_llm_config()
    connections = [c for c in config.get("connections", []) if c["id"] != connection_id]
    if len(connections) == len(config.get("connections", [])):
        return False
    roles = copy.deepcopy(config.get("roles") or DEFAULT_ROLES)
    for role in roles.values():
        if role.get("connection_id") == connection_id:
            role["connection_id"] = None
            role["model"] = ""
    default_id = config.get("default_connection_id")
    if default_id == connection_id:
        default_id = connections[0]["id"] if connections else None
    _config().update(
        config["_id"],
        {"$set": {"connections": connections, "roles": roles, "default_connection_id": default_id}},
    )
    return True


def get_connection(connection_id: str | None) -> dict[str, Any] | None:
    if not connection_id:
        return None
    for connection in get_llm_config().get("connections", []):
        if connection["id"] == connection_id:
            return connection
    return None


def enabled_connections() -> list[dict[str, Any]]:
    return [c for c in get_llm_config().get("connections", []) if c.get("enabled")]


def autonomous_generation_allowed() -> bool:
    """Whether the background world should keep writing on its own.

    Two situations look identical to the router but mean opposite things to a
    person. A site with no connections at all has simply never been set up, and
    the offline generator exists precisely so the front page is not empty —
    that world should keep turning. A site whose connections are all switched
    off is one where somebody reached over and turned the model off, and they
    do not expect the boards to keep filling with placeholder text, or their
    local GPU to keep running, because of it.
    """
    connections = get_llm_config().get("connections", [])
    if not connections:
        return True
    return any(c.get("enabled") for c in connections)


def automatic_generation_allowed() -> bool:
    """Whether anything may be written without somebody asking for it.

    Covers both switches a person can actually reach for — turning the
    simulation off, and disabling every model connection. It gates the writing
    that happens as a side effect of browsing: filling a thread you opened,
    answering a comment you left, topping up a thin feed.

    Deliberate actions deliberately bypass this. "More discussion", "summon
    posts" and poking a comment are someone asking on purpose, and a switch
    labelled *simulation* should not disable the buttons.
    """
    if not get_world().get("simulation_enabled", True):
        return False
    return autonomous_generation_allowed()


def set_role(role: str, connection_id: str | None, model: str, **overrides: Any) -> dict[str, Any]:
    config = get_llm_config()
    roles = copy.deepcopy(config.get("roles") or DEFAULT_ROLES)
    entry = roles.get(role) or copy.deepcopy(DEFAULT_ROLES.get(role, DEFAULT_ROLES["utility"]))
    entry["connection_id"] = connection_id
    entry["model"] = model
    for key in ("temperature", "max_tokens"):
        if key in overrides and overrides[key] is not None:
            entry[key] = overrides[key]
    roles[role] = entry
    _config().update(config["_id"], {"$set": {"roles": roles}})
    return entry


def set_default_connection(connection_id: str | None) -> None:
    config = get_llm_config()
    _config().update(config["_id"], {"$set": {"default_connection_id": connection_id}})


def set_llm_flag(field: str, value: Any) -> None:
    if field not in {"fallback_to_mock", "multi_model_mixing"}:
        raise ValueError(f"Unknown LLM flag: {field}")
    config = get_llm_config()
    _config().update(config["_id"], {"$set": {field: value}})
