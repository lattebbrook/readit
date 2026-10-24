"""Media upload, capture-by-URL, and file serving."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.deps import current_user, optional_user
from app.models.schemas import MediaUrlIngest
from app.services import media_service, subreddit_service, vision_service

router = APIRouter(prefix="/api/media", tags=["media"])

# Files are content-addressed, so a given id can never point at different
# bytes later — safe to cache hard and skip the revalidation round trip.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def _describe_later(background: BackgroundTasks, media_id: str, board_name: str = "") -> None:
    """Queue the vision pass so upload responses stay instant."""
    board = subreddit_service.get(board_name) if board_name else None
    background.add_task(vision_service.analyse, media_id, subreddit=board)


@router.post("/upload")
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    board: str = "",
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Accept a file from a picker, a paste, or a drag-and-drop."""
    try:
        raw = await file.read()
        media = media_service.ingest_bytes(
            raw, added_by=user["_id"], filename=file.filename or ""
        )
    except media_service.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _describe_later(background, media["_id"], board)
    return {"media": media_service.public_media(media)}


@router.post("/from-url")
async def from_url(
    payload: MediaUrlIngest,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Pull an image in by link.

    Fetched server-side so CORS never applies and a Referer can be sent, which
    is what most image hosts check before serving a hotlinked file.
    """
    try:
        media = await media_service.ingest_url(
            payload.url, source_page=payload.source_page, added_by=user["_id"]
        )
    except media_service.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _describe_later(background, media["_id"], payload.board)
    return {"media": media_service.public_media(media)}


@router.get("/{media_id}")
async def serve(media_id: str) -> Response:
    media = media_service.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="No such image.")
    data = media_service.read_variant(media, "display")
    if data is None:
        raise HTTPException(status_code=404, detail="That image file is missing from disk.")
    return Response(
        content=data,
        media_type=media_service.DISPLAY_MIME,
        headers={"Cache-Control": IMMUTABLE_CACHE, "ETag": f'"{media["sha256"]}"'},
    )


@router.get("/{media_id}/thumb")
async def serve_thumb(media_id: str) -> Response:
    media = media_service.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="No such image.")
    data = media_service.read_variant(media, "thumb")
    if data is None:
        raise HTTPException(status_code=404, detail="That thumbnail is missing from disk.")
    return Response(
        content=data,
        media_type=media_service.DISPLAY_MIME,
        headers={"Cache-Control": IMMUTABLE_CACHE, "ETag": f'"{media["sha256"]}t"'},
    )


@router.get("/{media_id}/analysis")
async def analysis(
    media_id: str, _: dict[str, Any] | None = Depends(optional_user)
) -> dict[str, Any]:
    """Poll target while a freshly captured image is still being described."""
    media = media_service.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="No such image.")
    return {
        "state": media.get("analysis_state", "pending"),
        "model": media.get("analysis_model", ""),
        "analysis": media.get("analysis"),
    }


@router.post("/{media_id}/describe")
async def describe(
    media_id: str,
    board: str = "",
    force: bool = False,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Run (or re-run) the vision pass on demand."""
    if not media_service.get(media_id):
        raise HTTPException(status_code=404, detail="No such image.")
    target = subreddit_service.get(board) if board else None
    result = await vision_service.analyse(media_id, subreddit=target, force=force)
    if result is None:
        raise HTTPException(
            status_code=502,
            detail="The vision model did not return a usable description. "
            "Check the 'vision' role in Admin → AI connections.",
        )
    return {"analysis": result}
