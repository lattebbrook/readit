"""Admin console: global prompts, provider connections, simulation, moderation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import admin_user, optional_user
from app.db import db, seed
from app.llm import router as llm_router
from app.llm.providers import PROVIDER_DEFAULT_MODELS, PROVIDER_TYPES
from app.models.schemas import (
    ConnectionCreate,
    ConnectionUpdate,
    LLMFlagUpdate,
    RoleUpdate,
    SeedRequest,
    TestConnectionRequest,
    WorldUpdate,
)
from app.services import (
    config_service,
    moderation_service,
    persona_service,
    simulation,
    subreddit_service,
    user_service,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
public_router = APIRouter(prefix="/api", tags=["site"])


# --------------------------------------------------------------------------- #
# Public site info
# --------------------------------------------------------------------------- #

@public_router.get("/site")
async def site_info(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    """What the client needs on boot: branding, knobs it may show, and the viewer."""
    world = config_service.get_world()
    return {
        "name": "ReadIt",
        "description": world.get("site_description", ""),
        "user": user_service.private_user(user),
        "is_admin": bool((user or {}).get("is_admin")),
        "simulation": {
            "enabled": world.get("simulation_enabled", True),
            "background": world.get("background_activity", True),
            "tick_seconds": world.get("tick_seconds", 12),
        },
        "counts": {
            "boards": db.collection("subreddits").count(),
            "posts": db.collection("posts").count(),
            "comments": db.collection("comments").count(),
            "personas": db.collection("personas").count(),
            "users": db.collection("users").count(),
        },
        "llm_ready": bool(config_service.enabled_connections()),
    }


# --------------------------------------------------------------------------- #
# World prompt and knobs
# --------------------------------------------------------------------------- #

@router.get("/world")
async def get_world(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"world": config_service.get_world()}


@router.patch("/world")
async def update_world(
    payload: WorldUpdate, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    """The single lever that redirects the entire site's personality."""
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    world = config_service.update_world(changes)

    # Flipping the switch here must do the same thing as the start/stop
    # buttons, or the engine keeps reporting itself as running after the world
    # has been turned off.
    if "simulation_enabled" in changes:
        if changes["simulation_enabled"]:
            simulation.engine.start()
        else:
            await simulation.engine.stop()

    return {"world": world}


@router.post("/world/reset")
async def reset_world(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"world": config_service.reset_world()}


# --------------------------------------------------------------------------- #
# LLM connections
# --------------------------------------------------------------------------- #

@router.get("/llm")
async def get_llm(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {
        "config": config_service.public_llm_config(),
        "provider_types": sorted(PROVIDER_TYPES),
        "suggested_models": PROVIDER_DEFAULT_MODELS,
        "stats": llm_router.call_stats(),
    }


@router.post("/llm/connections")
async def add_connection(
    payload: ConnectionCreate, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    connection = config_service.add_connection(payload.model_dump())
    return {"connection_id": connection["id"], "config": config_service.public_llm_config()}


@router.patch("/llm/connections/{connection_id}")
async def update_connection(
    connection_id: str, payload: ConnectionUpdate, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = config_service.update_connection(connection_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="No such connection.")
    return {"config": config_service.public_llm_config()}


@router.delete("/llm/connections/{connection_id}")
async def delete_connection(
    connection_id: str, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    if not config_service.delete_connection(connection_id):
        raise HTTPException(status_code=404, detail="No such connection.")
    return {"config": config_service.public_llm_config()}


@router.post("/llm/connections/{connection_id}/test")
async def test_connection(
    connection_id: str, payload: TestConnectionRequest, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    connection = config_service.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="No such connection.")
    return await llm_router.test_connection(connection, payload.model)


@router.post("/llm/connections/{connection_id}/models")
async def discover_models(
    connection_id: str, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    """Pull the live model list from the provider, when it exposes one."""
    connection = config_service.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="No such connection.")
    models = await llm_router.discover_models(connection)
    if models:
        config_service.update_connection(connection_id, {"models": models})
    return {"models": models, "config": config_service.public_llm_config()}


@router.put("/llm/roles/{role}")
async def set_role(
    role: str, payload: RoleUpdate, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    """Point a generation role (posts, comments, moderation…) at a model."""
    if role not in config_service.DEFAULT_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
    config_service.set_role(
        role,
        payload.connection_id,
        payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return {"config": config_service.public_llm_config()}


@router.patch("/llm/flags")
async def set_flags(
    payload: LLMFlagUpdate, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    if payload.fallback_to_mock is not None:
        config_service.set_llm_flag("fallback_to_mock", payload.fallback_to_mock)
    if payload.multi_model_mixing is not None:
        config_service.set_llm_flag("multi_model_mixing", payload.multi_model_mixing)
    if payload.default_connection_id is not None:
        config_service.set_default_connection(payload.default_connection_id or None)
    return {"config": config_service.public_llm_config()}


@router.get("/llm/calls")
async def recent_calls(limit: int = 50, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"calls": llm_router.recent_calls(limit), "stats": llm_router.call_stats()}


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #

@router.get("/simulation")
async def simulation_status(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    world = config_service.get_world()
    return {
        "status": simulation.engine.status(),
        "enabled": world.get("simulation_enabled", True),
        "background": world.get("background_activity", True),
        "tick_seconds": world.get("tick_seconds"),
    }


@router.post("/simulation/tick")
async def force_tick(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"tick": await simulation.engine.tick()}


@router.post("/simulation/start")
async def start_simulation(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    config_service.update_world({"simulation_enabled": True})
    simulation.engine.start()
    return {"status": simulation.engine.status()}


@router.post("/simulation/stop")
async def stop_simulation(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    """Stop the world.

    Both halves matter: the flag gates the generation that browsing would
    otherwise trigger, and cancelling the loop means the engine stops reporting
    itself as running when it is not.
    """
    config_service.update_world({"simulation_enabled": False})
    await simulation.engine.stop()
    return {"status": simulation.engine.status()}


@router.post("/seed")
async def seed_content(
    payload: SeedRequest, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    seed.bootstrap()
    return await seed.seed_content(payload.board_limit, payload.posts_per_board)


@router.post("/personas/generate")
async def generate_personas(
    count: int = 10, board: str | None = None, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    target = subreddit_service.get(board) if board else None
    created = await persona_service.generate_personas(count, target)
    return {"created": [persona_service.public_persona(persona) for persona in created]}


# --------------------------------------------------------------------------- #
# Oversight
# --------------------------------------------------------------------------- #

@router.get("/stats")
async def stats(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {
        "collections": db.stats(),
        "llm": llm_router.call_stats(),
        "simulation": simulation.engine.status(),
        "top_boards": [
            {
                "name": board["name"],
                "posts": db.collection("posts").count({"subreddit": board["name"]}),
                "subscribers": board.get("subscribers", 0),
            }
            for board in subreddit_service.list_boards(limit=15)
        ],
    }


@router.get("/mod-log")
async def mod_log(limit: int = 100, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"entries": moderation_service.recent_log(limit)}


@router.get("/reports")
async def reports(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"reports": db.collection("reports").find(sort=[("at", -1)], limit=100)}


@router.get("/users")
async def list_users(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    users = db.collection("users").find(sort=[("created_at", -1)], limit=200)
    return {"users": [user_service.public_user(user) for user in users]}


@router.post("/moderate/{kind}/{target_id}/remove")
async def admin_remove(
    kind: str, target_id: str, reason: str = "", admin: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    handler = {"post": moderation_service.remove_post, "comment": moderation_service.remove_comment}.get(kind)
    if not handler:
        raise HTTPException(status_code=400, detail="Can only remove posts and comments.")
    result = handler(target_id, reason=reason, moderator=admin["username"], by_ai=False)
    if not result:
        raise HTTPException(status_code=404, detail="Nothing to remove.")
    return {"removed": True}


@router.post("/moderate/{kind}/{target_id}/restore")
async def admin_restore(
    kind: str, target_id: str, admin: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    handler = {"post": moderation_service.restore_post, "comment": moderation_service.restore_comment}.get(kind)
    if not handler:
        raise HTTPException(status_code=400, detail="Can only restore posts and comments.")
    result = handler(target_id, moderator=admin["username"])
    if not result:
        raise HTTPException(status_code=404, detail="Nothing to restore.")
    return {"restored": True}


@router.post("/snapshot")
async def snapshot(_: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"path": db.save_snapshot()}


@router.post("/reset-world")
async def reset_everything(
    keep_users: bool = True, _: dict[str, Any] = Depends(admin_user)
) -> dict[str, Any]:
    """Wipe generated content. Accounts survive unless explicitly dropped."""
    for name in ("posts", "comments", "votes", "award_grants", "activity", "moderation_log", "watchlist"):
        db.collection(name).clear()
    if not keep_users:
        db.collection("personas").clear()
    seed.bootstrap()
    return {"ok": True, "counts": db.stats()}
