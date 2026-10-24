"""The local media library.

Images arrive from an upload, a paste, a drag, or a URL the backend fetches
itself, and all four land here. Binaries live on disk keyed by content hash;
only metadata goes into the document store, so the JSON snapshot stays small
no matter how many pictures pile up.

Everything is normalised on the way in: oversized images are downscaled, the
display copy is WebP, and a separate JPEG derivative is kept for vision calls
because not every local vision stack can decode WebP.
"""

from __future__ import annotations

import hashlib
import io
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.db import db, now

# Formats we are willing to decode. Anything else is rejected rather than
# guessed at — a mislabelled binary should fail loudly at ingest, not later.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}

DISPLAY_MIME = "image/webp"
VISION_MIME = "image/jpeg"


class MediaError(ValueError):
    """User-facing media validation failure."""


def _media():
    return db.collection("media")


def media_root() -> str:
    path = os.path.abspath(settings.media_dir)
    os.makedirs(path, exist_ok=True)
    return path


def _paths(sha: str) -> dict[str, str]:
    """Shard by the first two hex characters so one directory never holds
    thousands of files."""
    root = os.path.join(media_root(), sha[:2])
    os.makedirs(root, exist_ok=True)
    return {
        "display": os.path.join(root, f"{sha}.webp"),
        "thumb": os.path.join(root, f"{sha}.thumb.webp"),
        "vision": os.path.join(root, f"{sha}.vision.jpg"),
    }


# --------------------------------------------------------------------------- #
# Decoding and normalisation
# --------------------------------------------------------------------------- #

def _open_image(raw: bytes) -> Image.Image:
    if not raw:
        raise MediaError("That file was empty.")
    if len(raw) > settings.media_max_bytes:
        limit = settings.media_max_bytes // (1024 * 1024)
        raise MediaError(f"That image is larger than the {limit}MB limit.")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except UnidentifiedImageError as exc:
        raise MediaError("That doesn't look like an image.") from exc
    except Exception as exc:  # truncated/corrupt payloads
        raise MediaError(f"Could not read that image: {exc}") from exc

    if image.format and image.format.upper() not in ALLOWED_FORMATS:
        raise MediaError(f"Unsupported image format: {image.format}")
    # Respect EXIF orientation now so every derivative agrees on which way is up.
    return ImageOps.exif_transpose(image)


def _flatten(image: Image.Image) -> Image.Image:
    """Drop alpha onto white so JPEG encoding cannot fail on transparency."""
    if image.mode in {"RGBA", "LA", "P"}:
        converted = image.convert("RGBA")
        canvas = Image.new("RGB", converted.size, (255, 255, 255))
        canvas.paste(converted, mask=converted.split()[-1])
        return canvas
    return image.convert("RGB")


def _fit(image: Image.Image, max_edge: int) -> Image.Image:
    if max(image.size) <= max_edge:
        return image.copy()
    resized = image.copy()
    resized.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return resized


def _write_derivatives(image: Image.Image, sha: str) -> dict[str, str]:
    paths = _paths(sha)
    flat = _flatten(image)

    display = _fit(flat, settings.media_max_edge)
    display.save(paths["display"], "WEBP", quality=88, method=4)

    thumb = _fit(flat, settings.media_thumb_edge)
    thumb.save(paths["thumb"], "WEBP", quality=80, method=4)

    # JPEG for the vision pass: llama.cpp-backed runtimes (LM Studio, Ollama)
    # decode via stb_image, which has no WebP support.
    vision = _fit(flat, settings.media_vision_edge)
    vision.save(paths["vision"], "JPEG", quality=85, optimize=True)

    return {"paths": paths, "width": display.width, "height": display.height}


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #

def get(media_id: str) -> dict[str, Any] | None:
    return _media().get(media_id)


def by_hash(sha: str) -> dict[str, Any] | None:
    return _media().find_one({"sha256": sha})


def ingest_bytes(
    raw: bytes,
    *,
    source_url: str = "",
    source_page: str = "",
    added_by: str | None = None,
    filename: str = "",
) -> dict[str, Any]:
    """Store an image and return its media document.

    Re-ingesting identical bytes returns the existing record rather than a
    duplicate, which keeps a cached vision analysis attached to the image
    however many times it gets captured.
    """
    sha = hashlib.sha256(raw).hexdigest()
    existing = by_hash(sha)
    if existing:
        return existing

    image = _open_image(raw)
    written = _write_derivatives(image, sha)

    return _media().insert(
        {
            "sha256": sha,
            "width": written["width"],
            "height": written["height"],
            "bytes": len(raw),
            "mime": DISPLAY_MIME,
            "original_format": (image.format or "").upper(),
            "original_filename": (filename or "")[:200],
            "source_url": (source_url or "")[:1000],
            "source_page": (source_page or "")[:1000],
            "source_site": urlparse(source_page or source_url or "").netloc[:120],
            "added_by": added_by,
            "added_at": now(),
            # Filled in by the vision pass; see analysis_service.
            "analysis": None,
            "analysis_state": "pending",
            "analysis_model": "",
        }
    )


async def ingest_url(
    url: str,
    *,
    source_page: str = "",
    added_by: str | None = None,
) -> dict[str, Any]:
    """Fetch an image server-side.

    Doing this on the backend rather than in the browser sidesteps CORS
    entirely and lets us send a Referer, which is what most image hosts check
    before serving a hotlinked file.
    """
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise MediaError("Image links must start with http:// or https://")

    referer = source_page or f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ReadIt/1.0; local media capture)",
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.media_fetch_timeout, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:
        raise MediaError(f"Could not reach that image: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise MediaError(f"That image returned HTTP {response.status_code}.")

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and not content_type.startswith("image/"):
        raise MediaError(
            f"That link is {content_type or 'not an image'}, not an image file. "
            "Try right-clicking the picture and copying the image address."
        )

    return ingest_bytes(
        response.content,
        source_url=url,
        source_page=source_page,
        added_by=added_by,
        filename=os.path.basename(parsed.path)[:200],
    )


# --------------------------------------------------------------------------- #
# Reading files back
# --------------------------------------------------------------------------- #

def file_path(media: dict[str, Any], variant: str = "display") -> str | None:
    paths = _paths(media["sha256"])
    path = paths.get(variant)
    return path if path and os.path.exists(path) else None


def read_variant(media: dict[str, Any], variant: str = "display") -> bytes | None:
    path = file_path(media, variant)
    if not path:
        return None
    with open(path, "rb") as handle:
        return handle.read()


def vision_bytes(media: dict[str, Any]) -> bytes | None:
    """The JPEG derivative used for vision calls."""
    return read_variant(media, "vision")


def delete(media_id: str) -> bool:
    media = get(media_id)
    if not media:
        return False
    for path in _paths(media["sha256"]).values():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    return _media().delete(media_id)


def orphans() -> list[dict[str, Any]]:
    """Media not referenced by any post — useful for a cleanup pass."""
    used = {
        post.get("media_id")
        for post in db.collection("posts").all()
        if post.get("media_id")
    }
    return [doc for doc in _media().all() if doc["_id"] not in used]


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #

def public_media(media: dict[str, Any] | None) -> dict[str, Any] | None:
    if not media:
        return None
    analysis = media.get("analysis") or {}
    return {
        "id": media["_id"],
        "url": f"/api/media/{media['_id']}",
        "thumb_url": f"/api/media/{media['_id']}/thumb",
        "width": media.get("width", 0),
        "height": media.get("height", 0),
        # Lets the grid reserve the right space before the image loads.
        "aspect_ratio": round(media.get("width", 1) / max(1, media.get("height", 1)), 4),
        "source_url": media.get("source_url", ""),
        "source_page": media.get("source_page", ""),
        "source_site": media.get("source_site", ""),
        "analysis_state": media.get("analysis_state", "pending"),
        # The caption doubles as alt text, so the grid stays usable for
        # screen readers and while images are still loading.
        "caption": analysis.get("caption", ""),
        "tags": analysis.get("tags", []),
        "nsfw": bool(analysis.get("nsfw")),
    }
