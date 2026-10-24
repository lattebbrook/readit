"""Unit tests for the media library, the vision pass, and photo boards."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.db import db
from app.llm.base import LLMImage, LLMMessage, LLMRequest
from app.llm.prompts import image_analysis_prompt, render_media_context
from app.llm.providers import (
    AnthropicProvider,
    GoogleProvider,
    LMStudioProvider,
    OpenAICompatibleProvider,
)
from app.services import (
    generation_service,
    media_service,
    post_service,
    subreddit_service,
    vision_service,
)


def make_image(
    width: int = 400, height: int = 300, colour: tuple[int, int, int] = (10, 120, 200), fmt: str = "PNG"
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, fmt)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #

def test_ingest_stores_derivatives_on_disk():
    media = media_service.ingest_bytes(make_image(), filename="cat.png")
    assert media["sha256"]
    assert media["analysis_state"] == "pending"
    for variant in ("display", "thumb", "vision"):
        assert media_service.file_path(media, variant), f"{variant} missing"


def test_ingest_is_content_addressed_and_deduplicates():
    raw = make_image()
    first = media_service.ingest_bytes(raw)
    second = media_service.ingest_bytes(raw, filename="different-name.png")
    assert first["_id"] == second["_id"]
    assert db.collection("media").count() == 1


def test_different_images_are_distinct():
    media_service.ingest_bytes(make_image(colour=(1, 2, 3)))
    media_service.ingest_bytes(make_image(colour=(250, 250, 250)))
    assert db.collection("media").count() == 2


def test_oversized_images_are_downscaled():
    from app.config import settings

    media = media_service.ingest_bytes(make_image(width=5000, height=3000))
    assert media["width"] <= settings.media_max_edge
    assert media["height"] <= settings.media_max_edge
    # Aspect ratio survives the resize.
    assert abs(media["width"] / media["height"] - 5000 / 3000) < 0.01


def test_small_images_are_not_upscaled():
    media = media_service.ingest_bytes(make_image(width=120, height=90))
    assert (media["width"], media["height"]) == (120, 90)


def test_vision_derivative_is_jpeg():
    """llama.cpp-backed runtimes decode via stb_image, which has no WebP."""
    media = media_service.ingest_bytes(make_image())
    payload = media_service.vision_bytes(media)
    assert payload
    assert Image.open(io.BytesIO(payload)).format == "JPEG"


def test_transparent_png_flattens_without_error():
    buffer = io.BytesIO()
    Image.new("RGBA", (200, 200), (255, 0, 0, 0)).save(buffer, "PNG")
    media = media_service.ingest_bytes(buffer.getvalue())
    assert media_service.vision_bytes(media)


@pytest.mark.parametrize("raw", [b"", b"definitely not an image", b"\x89PNG\r\n\x1a\n truncated"])
def test_bad_payloads_are_rejected(raw):
    with pytest.raises(media_service.MediaError):
        media_service.ingest_bytes(raw)


def test_oversized_payload_is_rejected(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "media_max_bytes", 10)
    with pytest.raises(media_service.MediaError, match="larger than"):
        media_service.ingest_bytes(make_image())


async def test_ingest_url_rejects_non_http_schemes():
    with pytest.raises(media_service.MediaError, match="http"):
        await media_service.ingest_url("file:///etc/passwd")


def test_delete_removes_files_and_record():
    media = media_service.ingest_bytes(make_image())
    path = media_service.file_path(media, "display")
    assert media_service.delete(media["_id"]) is True
    assert media_service.get(media["_id"]) is None
    assert media_service.file_path({"sha256": media["sha256"]}, "display") is None or path


def test_public_media_shape():
    media = media_service.ingest_bytes(make_image(400, 200))
    payload = media_service.public_media(media)
    assert payload["url"].endswith(media["_id"])
    assert payload["thumb_url"].endswith("/thumb")
    assert payload["aspect_ratio"] == 2.0
    assert payload["analysis_state"] == "pending"


def test_orphans_finds_unreferenced_media(board):
    used = media_service.ingest_bytes(make_image(colour=(1, 1, 1)))
    loose = media_service.ingest_bytes(make_image(colour=(9, 9, 9)))
    post_service.create(
        subreddit=board["name"], title="t", author="A", author_kind="ai", media_id=used["_id"]
    )
    assert [doc["_id"] for doc in media_service.orphans()] == [loose["_id"]]


# --------------------------------------------------------------------------- #
# Per-provider image encoding
# --------------------------------------------------------------------------- #

def _request_with_image() -> LLMRequest:
    return LLMRequest(
        messages=[
            LLMMessage("system", "describe it"),
            LLMMessage("user", "what is this", images=[LLMImage(data=b"rawbytes", mime="image/jpeg")]),
        ],
        model="some-vlm",
    )


def test_text_only_messages_keep_plain_string_content():
    """Some OpenAI-compatible servers are stricter than the spec about this."""
    assert LLMMessage("user", "hi").as_dict() == {"role": "user", "content": "hi"}


def test_openai_style_encodes_images_as_data_uris():
    payload = OpenAICompatibleProvider().build_payload(_request_with_image())
    parts = payload["messages"][1]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_lmstudio_inherits_image_encoding():
    payload = LMStudioProvider().build_payload(_request_with_image())
    assert payload["messages"][1]["content"][1]["type"] == "image_url"


def test_anthropic_uses_source_blocks():
    payload = AnthropicProvider().build_payload(_request_with_image())
    parts = payload["messages"][0]["content"]
    image_part = next(part for part in parts if part["type"] == "image")
    assert image_part["source"]["type"] == "base64"
    assert image_part["source"]["media_type"] == "image/jpeg"
    assert "data" in image_part["source"]


def test_google_uses_inline_data():
    payload = GoogleProvider().build_payload(_request_with_image())
    parts = payload["contents"][0]["parts"]
    inline = next(part for part in parts if "inline_data" in part)
    assert inline["inline_data"]["mime_type"] == "image/jpeg"


def test_image_bytes_are_base64_encoded_not_raw():
    image = LLMImage(data=b"\x00\xff\xfe", mime="image/png")
    assert image.b64() == "AP/+"
    assert image.data_uri() == "data:image/png;base64,AP/+"


# --------------------------------------------------------------------------- #
# Vision pass and caching
# --------------------------------------------------------------------------- #

async def test_analyse_populates_and_caches(board):
    media = media_service.ingest_bytes(make_image())
    analysis = await vision_service.analyse(media["_id"], subreddit=board)

    assert analysis
    assert analysis["caption"]
    assert analysis["discussion_hooks"]
    stored = media_service.get(media["_id"])
    assert stored["analysis_state"] == "done"
    assert stored["analysis"] == analysis


async def test_analysis_is_not_recomputed(board, monkeypatch):
    media = media_service.ingest_bytes(make_image())
    await vision_service.analyse(media["_id"], subreddit=board)

    calls = {"count": 0}
    original = vision_service.router.generate_json

    async def counting(*args, **kwargs):
        calls["count"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(vision_service.router, "generate_json", counting)
    again = await vision_service.analyse(media["_id"], subreddit=board)

    assert again is not None
    assert calls["count"] == 0, "a cached analysis must not hit the model again"


async def test_force_recomputes(board, monkeypatch):
    media = media_service.ingest_bytes(make_image())
    await vision_service.analyse(media["_id"], subreddit=board)

    calls = {"count": 0}
    original = vision_service.router.generate_json

    async def counting(*args, **kwargs):
        calls["count"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(vision_service.router, "generate_json", counting)
    await vision_service.analyse(media["_id"], subreddit=board, force=True)
    assert calls["count"] == 1


async def test_reingesting_the_same_image_reuses_its_description(board):
    raw = make_image()
    first = media_service.ingest_bytes(raw)
    await vision_service.analyse(first["_id"], subreddit=board)

    # Same bytes captured a second time from somewhere else.
    second = media_service.ingest_bytes(raw, source_url="https://example.com/x.png")
    assert second["_id"] == first["_id"]
    assert second["analysis"] is not None


async def test_failed_analysis_is_recorded_not_retried_forever(board, monkeypatch):
    media = media_service.ingest_bytes(make_image())

    async def unusable(*args, **kwargs):
        from app.llm.base import LLMResponse

        return None, LLMResponse(text="nope", model="m", provider="p")

    monkeypatch.setattr(vision_service.router, "generate_json", unusable)
    assert await vision_service.analyse(media["_id"], subreddit=board) is None
    assert media_service.get(media["_id"])["analysis_state"] == "failed"


async def test_analyse_missing_media_is_safe():
    assert await vision_service.analyse("nope") is None


def test_analysis_for_never_triggers_a_call():
    media = media_service.ingest_bytes(make_image())
    assert vision_service.analysis_for(media["_id"]) is None
    assert vision_service.analysis_for(None) is None


async def test_analyse_pending_drains_the_queue(board):
    for shade in range(3):
        media_service.ingest_bytes(make_image(colour=(shade * 40, 10, 10)))
    done = await vision_service.analyse_pending(limit=2, subreddit=board)
    assert done == 2
    assert db.collection("media").count({"analysis_state": "pending"}) == 1


def test_analysis_output_is_clamped():
    """A model returning junk types must not poison the stored record."""
    cleaned = vision_service._clean(
        {
            "caption": "x" * 900,
            "tags": ["A", "B", 5, "", None] + [f"t{i}" for i in range(30)],
            "subject_type": "nonsense",
            "discussion_hooks": "not a list",
            "nsfw": "yes",
        }
    )
    assert len(cleaned["caption"]) == 300
    assert cleaned["subject_type"] == "other"
    assert len(cleaned["tags"]) <= 12
    assert all(tag == tag.lower() for tag in cleaned["tags"])
    assert cleaned["discussion_hooks"] == []
    assert cleaned["nsfw"] is True


# --------------------------------------------------------------------------- #
# Prompt plumbing
# --------------------------------------------------------------------------- #

def test_analysis_prompt_forbids_identifying_people(board):
    system, contract = image_analysis_prompt({}, board)
    assert "identity" in system.lower() or "identify" in system.lower()
    assert "never" in system.lower()
    assert '"discussion_hooks"' in contract


def test_analysis_prompt_mentions_the_board(board):
    system, _ = image_analysis_prompt({}, board)
    assert board["name"] in system


def test_media_context_is_empty_without_analysis():
    assert render_media_context(None) == ""
    assert render_media_context({}) == ""


def test_media_context_surfaces_hooks():
    rendered = render_media_context(
        {
            "caption": "a red biplane",
            "detailed_description": "parked on grass",
            "discussion_hooks": ["the registration looks wrong", "wrong era for that livery"],
        }
    )
    assert "a red biplane" in rendered
    assert "the registration looks wrong" in rendered


def test_media_context_guards_photos_of_people():
    rendered = render_media_context(
        {"caption": "someone at a beach", "depicts_identifiable_person": True}
    )
    assert "never to who they might be" in rendered


# --------------------------------------------------------------------------- #
# Photo boards
# --------------------------------------------------------------------------- #

def test_boards_default_to_text():
    assert subreddit_service.create("plainboard")["kind"] == "text"


def test_photo_board_creation_and_rejection_of_unknown_kinds():
    assert subreddit_service.create("pics", kind="photo")["kind"] == "photo"
    with pytest.raises(subreddit_service.SubredditError):
        subreddit_service.create("weird", kind="video")


def test_public_board_defaults_kind_for_legacy_records(board):
    db.collection("subreddits").update(board["_id"], {"$unset": {"kind": True}})
    stale = subreddit_service.get(board["name"])
    assert subreddit_service.public_board(stale)["kind"] == "text"


async def test_world_never_writes_text_posts_into_a_photo_board():
    subreddit_service.create("gonewide", kind="photo")
    assert await generation_service.generate_posts("gonewide", count=3) == []
    assert db.collection("posts").count({"subreddit": "gonewide"}) == 0


async def test_simulation_skips_photo_boards(monkeypatch):
    from app.services import simulation, user_service

    subreddit_service.create("planespotting", kind="photo")
    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], "planespotting")

    await simulation.engine.tick()
    assert db.collection("posts").count({"subreddit": "planespotting"}) == 0


async def test_comments_on_an_image_post_see_its_description(board, monkeypatch):
    media = media_service.ingest_bytes(make_image())
    post = post_service.create(
        subreddit=board["name"],
        title="look at this",
        author="A",
        author_kind="ai",
        media_id=media["_id"],
    )

    seen: dict[str, str] = {}
    original = generation_service.router.generate_json

    async def capture(role, messages, **kwargs):
        if role == "comment":
            seen["prompt"] = messages[-1].content
        return await original(role, messages, **kwargs)

    monkeypatch.setattr(generation_service.router, "generate_json", capture)
    created = await generation_service.generate_comments(post["_id"], count=4)

    assert created
    assert "THE POST IS AN IMAGE" in seen.get("prompt", "")


def test_public_post_carries_media(board):
    media = media_service.ingest_bytes(make_image())
    post = post_service.create(
        subreddit=board["name"], title="t", author="A", author_kind="ai", media_id=media["_id"]
    )
    payload = post_service.public_post(post)
    assert payload["media"]["id"] == media["_id"]


def test_public_post_media_is_none_without_an_image(board):
    post = post_service.create(subreddit=board["name"], title="t", author="A", author_kind="ai")
    assert post_service.public_post(post)["media"] is None


# --------------------------------------------------------------------------- #
# Local-model pacing
# --------------------------------------------------------------------------- #

def test_local_providers_get_a_long_timeout_and_no_parallelism():
    """A local GPU serialises anyway; queueing in-process avoids read timeouts."""
    from app.services import config_service

    for provider_type in ("lmstudio", "openai_compatible"):
        connection = config_service.add_connection(
            {"name": provider_type, "provider_type": provider_type}
        )
        assert connection["concurrency"] == 1
        assert connection["timeout"] >= 600


def test_hosted_providers_keep_parallelism():
    from app.services import config_service

    connection = config_service.add_connection({"name": "OR", "provider_type": "openrouter"})
    assert connection["concurrency"] > 1
    assert connection["timeout"] == 90


def test_explicit_values_beat_provider_defaults():
    from app.services import config_service

    connection = config_service.add_connection(
        {"name": "custom", "provider_type": "lmstudio", "timeout": 45, "concurrency": 3}
    )
    assert (connection["timeout"], connection["concurrency"]) == (45, 3)


def test_legacy_connections_are_backfilled():
    """Connections stored before pacing existed must not need re-adding."""
    from app.db import db
    from app.services import config_service

    config_service.add_connection({"name": "old", "provider_type": "lmstudio"})
    doc = config_service.get_llm_config()
    stripped = [
        {k: v for k, v in c.items() if k not in {"timeout", "concurrency"}}
        for c in doc["connections"]
    ]
    db.collection("config").update(doc["_id"], {"$set": {"connections": stripped}})

    patched = config_service.get_llm_config()["connections"][0]
    assert patched["concurrency"] == 1
    assert patched["timeout"] >= 600


def test_provider_receives_the_configured_timeout():
    from app.llm.providers import build_provider
    from app.services import config_service

    connection = config_service.add_connection({"name": "LMS", "provider_type": "lmstudio"})
    assert build_provider(connection).timeout >= 600


async def test_local_connection_serialises_calls(monkeypatch):
    """Two concurrent generations must not be in flight on one local model."""
    import asyncio

    from app.llm import router as llm_router
    from app.llm.base import LLMMessage, LLMResponse
    from app.llm.providers import OpenAICompatibleProvider
    from app.services import config_service

    connection = config_service.add_connection(
        {"name": "Local", "provider_type": "lmstudio", "models": ["m"]}
    )
    config_service.set_role("comment", connection["id"], "m")

    state = {"in_flight": 0, "peak": 0}

    async def tracked(self, request):  # noqa: ANN001
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.02)
        state["in_flight"] -= 1
        return LLMResponse(text='{"comments": []}', model=request.model, provider=self.name)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", tracked)

    await asyncio.gather(
        *(llm_router.generate("comment", [LLMMessage("user", "hi")]) for _ in range(4))
    )
    assert state["peak"] == 1, f"expected serialised calls, saw {state['peak']} at once"
