"""The single vision pass, and the cache that keeps it single.

Attaching an image to every generation call would be ruinous: a busy thread
runs thirty comment generations, and a local VLM would re-encode the same
picture thirty times for no new information. Instead the image is described
once, the description is cached against its content hash, and every downstream
text call reads the description.

Two things fall out of that. Bulk imports cost one vision call per *distinct*
image no matter how often it is reposted, and text-only models can hold a
conversation about a photo they cannot see.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.db import db, now
from app.llm import router
from app.llm.base import LLMImage, LLMMessage
from app.llm.prompts import image_analysis_prompt
from app.services import config_service, media_service

# One analysis at a time per image, so two readers opening the same fresh post
# do not both pay for the vision call.
_locks: dict[str, asyncio.Lock] = {}


def reset_locks() -> None:
    """Tests run on fresh event loops; stale locks would bind to a dead one."""
    _locks.clear()


def _lock_for(sha: str) -> asyncio.Lock:
    lock = _locks.get(sha)
    if lock is None:
        lock = asyncio.Lock()
        _locks[sha] = lock
    return lock


def _clean(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce a model response into the shape the rest of the app expects."""

    def text(key: str, limit: int) -> str:
        value = parsed.get(key)
        return str(value)[:limit] if isinstance(value, (str, int, float)) else ""

    def strings(key: str, limit: int, count: int) -> list[str]:
        value = parsed.get(key)
        if not isinstance(value, list):
            return []
        return [str(item)[:limit] for item in value if str(item).strip()][:count]

    subject = text("subject_type", 20).lower()
    return {
        "caption": text("caption", 300),
        "detailed_description": text("detailed_description", 2000),
        "visible_text": text("visible_text", 1000),
        "subject_type": subject if subject in
        {"photo", "screenshot", "artwork", "diagram", "meme", "other"} else "other",
        "tags": [tag.lower() for tag in strings("tags", 40, 12)],
        "mood": text("mood", 120),
        "technical_notes": text("technical_notes", 800),
        "discussion_hooks": strings("discussion_hooks", 300, 6),
        "suggested_titles": strings("suggested_titles", 300, 4),
        "nsfw": bool(parsed.get("nsfw")),
        "depicts_identifiable_person": bool(parsed.get("depicts_identifiable_person")),
    }


def _store(media_id: str, *, state: str, analysis: dict[str, Any] | None, model: str) -> dict[str, Any] | None:
    return db.collection("media").update(
        media_id,
        {
            "$set": {
                "analysis": analysis,
                "analysis_state": state,
                "analysis_model": model,
                "analysed_at": now(),
            }
        },
    )


async def analyse(
    media_id: str,
    *,
    subreddit: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """Describe an image, or return the cached description.

    Returns the analysis dict, or ``None`` when the image is gone or the vision
    call failed. A failure is recorded rather than retried forever — the board
    still works without it, just with less to talk about.
    """
    media = media_service.get(media_id)
    if not media:
        return None
    if media.get("analysis") and not force:
        return media["analysis"]

    async with _lock_for(media["sha256"]):
        # Another waiter may have finished while this one queued.
        media = media_service.get(media_id) or media
        if media.get("analysis") and not force:
            return media["analysis"]

        payload = media_service.vision_bytes(media)
        if not payload:
            _store(media_id, state="failed", analysis=None, model="")
            return None

        world = config_service.get_world()
        system, contract = image_analysis_prompt(world, subreddit)
        parsed, response = await router.generate_json(
            "vision",
            [
                LLMMessage("system", system),
                LLMMessage(
                    "user",
                    contract,
                    images=[LLMImage(data=payload, mime=media_service.VISION_MIME)],
                ),
            ],
        )

        if not isinstance(parsed, dict):
            _store(media_id, state="failed", analysis=None, model=response.model or "")
            return None

        analysis = _clean(parsed)
        _store(media_id, state="done", analysis=analysis, model=response.model or "")
        return analysis


def analysis_for(media_id: str | None) -> dict[str, Any] | None:
    """Cached analysis only — never triggers a vision call."""
    if not media_id:
        return None
    media = media_service.get(media_id)
    return (media or {}).get("analysis")


async def analyse_pending(limit: int = 3, subreddit: dict[str, Any] | None = None) -> int:
    """Work through images that have not been described yet.

    Used by the background loop so a bulk folder import gets captioned over
    time instead of blocking the request that started it.
    """
    pending = db.collection("media").find({"analysis_state": "pending"}, limit=limit)
    done = 0
    for media in pending:
        if await analyse(media["_id"], subreddit=subreddit):
            done += 1
    return done
