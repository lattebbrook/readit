"""Role-based routing across configured LLM connections, with fallbacks.

Callers ask for a *role* ("comment", "post", "moderation", …) rather than a
model. The router resolves that to a connection + model from admin config,
optionally spreads load across every enabled connection so the board's voices
come from different models, and degrades to the offline mock provider rather
than letting the forum go silent.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.db import db, now
from app.llm.base import LLMMessage, LLMRequest, LLMResponse
from app.llm.providers import MockProvider, build_provider
from app.services import config_service

_MAX_CALL_LOG = 200
_semaphore: asyncio.Semaphore | None = None
_connection_semaphores: dict[str, asyncio.Semaphore] = {}


def _get_semaphore() -> asyncio.Semaphore:
    """Lazily created so the limiter binds to the running loop."""
    global _semaphore
    if _semaphore is None:
        from app.config import settings

        _semaphore = asyncio.Semaphore(settings.max_concurrent_generations)
    return _semaphore


def _connection_semaphore(connection: dict[str, Any]) -> asyncio.Semaphore:
    """Per-connection limiter.

    A self-hosted runtime serves one model on one GPU. Firing four requests at
    it does not make them finish sooner — they queue inside the server with no
    bytes flowing, so each one burns its read timeout waiting its turn. Holding
    local connections to one in-flight request keeps the queue on our side,
    where it costs nothing.
    """
    key = connection.get("id") or connection.get("provider_type", "?")
    existing = _connection_semaphores.get(key)
    if existing is None:
        limit = max(1, int(connection.get("concurrency") or 1))
        existing = asyncio.Semaphore(limit)
        _connection_semaphores[key] = existing
    return existing


def reset_semaphore() -> None:
    """Drop the cached limiters (tests create a fresh event loop per case)."""
    global _semaphore
    _semaphore = None
    _connection_semaphores.clear()


def _log_call(role: str, response: LLMResponse, *, connection_name: str) -> None:
    collection = db.collection("llm_calls")
    collection.insert(
        {
            "role": role,
            "provider": response.provider,
            "connection": connection_name,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "ok": response.ok,
            "error": response.error,
            "chars": len(response.text or ""),
            "at": now(),
        }
    )
    overflow = collection.count() - _MAX_CALL_LOG
    if overflow > 0:
        oldest = collection.find(sort=[("at", 1)], limit=overflow)
        for doc in oldest:
            collection.delete(doc["_id"])


def _pick_model(connection: dict[str, Any], preferred: str = "") -> str:
    models = connection.get("models") or []
    if preferred and (not models or preferred in models):
        return preferred
    if models:
        return random.choice(models) if len(models) > 1 else models[0]
    return preferred or "mock-1"


def _candidate_chain(role: str, connection_id: str | None, model: str | None) -> list[dict[str, Any]]:
    """Ordered list of ``{connection, model}`` attempts for this call."""
    config = config_service.get_llm_config()
    roles = config.get("roles") or {}
    role_config = roles.get(role) or {}
    enabled = [c for c in config.get("connections", []) if c.get("enabled")]

    chain: list[dict[str, Any]] = []

    def push(connection: dict[str, Any] | None, preferred: str = "") -> None:
        if not connection:
            return
        if any(entry["connection"]["id"] == connection["id"] for entry in chain):
            return
        chain.append({"connection": connection, "model": _pick_model(connection, preferred)})

    def push_if_enabled(connection: dict[str, Any] | None, preferred: str = "") -> None:
        """Disabled means disabled — at every step, not just the role lookup.

        Skipping this check on any one branch silently resurrects a connection
        the admin switched off, which is worse than having no off switch at all.
        """
        if connection and connection.get("enabled"):
            push(connection, preferred)

    if connection_id:
        push_if_enabled(config_service.get_connection(connection_id), model or "")

    if not chain:
        push_if_enabled(
            config_service.get_connection(role_config.get("connection_id")),
            model or role_config.get("model", ""),
        )

        if config.get("multi_model_mixing") and len(enabled) > 1:
            # Bias toward the role's primary but let siblings take some traffic.
            weighted: list[dict[str, Any]] = []
            for connection in enabled:
                weighted.extend([connection] * max(1, int(connection.get("weight", 1))))
            random.shuffle(weighted)
            if weighted and random.random() < 0.5:
                chain.insert(0, {"connection": weighted[0], "model": _pick_model(weighted[0])})

        if not chain:
            push_if_enabled(config_service.get_connection(config.get("default_connection_id")))

    for connection in enabled:
        push(connection)

    if config.get("fallback_to_mock", True) or not chain:
        chain.append({"connection": {"id": "__mock__", "name": "Offline mock", "provider_type": "mock"}, "model": "mock-1"})

    return chain


async def generate(
    role: str,
    messages: list[LLMMessage],
    *,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    connection_id: str | None = None,
    model: str | None = None,
) -> LLMResponse:
    """Run a completion for ``role``, walking the fallback chain on failure."""
    config = config_service.get_llm_config()
    role_config = (config.get("roles") or {}).get(role, {})
    effective_temperature = (
        temperature if temperature is not None else role_config.get("temperature", 1.0)
    )
    effective_max_tokens = (
        max_tokens if max_tokens is not None else role_config.get("max_tokens", 2048)
    )

    last: LLMResponse | None = None
    async with _get_semaphore():
        for attempt in _candidate_chain(role, connection_id, model):
            connection = attempt["connection"]
            provider = (
                MockProvider()
                if connection.get("provider_type") == "mock"
                else build_provider(connection)
            )
            request = LLMRequest(
                messages=messages,
                model=attempt["model"],
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                json_mode=json_mode,
            )
            async with _connection_semaphore(connection):
                response = await provider.complete(request)
            _log_call(role, response, connection_name=connection.get("name", "?"))
            if response.ok and response.text.strip():
                return response
            last = response

    return last or LLMResponse(text="", model="", provider="none", error="no providers configured")


async def generate_json(
    role: str,
    messages: list[LLMMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    connection_id: str | None = None,
    model: str | None = None,
    retries: int = 2,
) -> tuple[Any, LLMResponse]:
    """Generate and parse a JSON payload; returns ``(parsed_or_None, response)``.

    A successful HTTP call is not the same thing as usable output — smaller
    and local models routinely return prose-wrapped or malformed JSON,
    especially at the higher temperatures the forum roles use for variety.
    Resampling on a parse failure costs one extra call but turns "this batch
    silently produced nothing" into "it worked on the second try" far more
    often than not.
    """
    response = LLMResponse(text="", model="", provider="none", error="no attempts made")
    for _ in range(retries + 1):
        response = await generate(
            role,
            messages,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
            connection_id=connection_id,
            model=model,
        )
        parsed = response.json()
        if parsed is not None:
            return parsed, response
    return None, response


async def test_connection(connection: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    """Admin "test" button: one tiny round trip against a connection."""
    provider = build_provider(connection)
    chosen = model or _pick_model(connection)
    response = await provider.complete(
        LLMRequest(
            messages=[
                LLMMessage(role="system", content="Reply with exactly the word: pong"),
                LLMMessage(role="user", content="ping"),
            ],
            model=chosen,
            temperature=0.0,
            max_tokens=16,
        )
    )
    return {
        "ok": response.ok,
        "model": chosen,
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "error": response.error,
        "sample": (response.text or "")[:200],
    }


async def discover_models(connection: dict[str, Any]) -> list[str]:
    return await build_provider(connection).list_models()


def recent_calls(limit: int = 50) -> list[dict[str, Any]]:
    return db.collection("llm_calls").find(sort=[("at", -1)], limit=limit)


def call_stats() -> dict[str, Any]:
    calls = db.collection("llm_calls").all()
    if not calls:
        return {"total": 0, "ok": 0, "failed": 0, "avg_latency_ms": 0, "by_model": {}}
    ok = [c for c in calls if c.get("ok")]
    by_model: dict[str, int] = {}
    for call in calls:
        key = f"{call.get('provider')}:{call.get('model')}"
        by_model[key] = by_model.get(key, 0) + 1
    return {
        "total": len(calls),
        "ok": len(ok),
        "failed": len(calls) - len(ok),
        "avg_latency_ms": int(sum(c.get("latency_ms", 0) for c in calls) / len(calls)),
        "by_model": by_model,
    }
