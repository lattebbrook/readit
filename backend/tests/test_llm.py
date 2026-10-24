"""Unit tests for the LLM layer: JSON extraction, providers, routing, prompts."""

from __future__ import annotations

import pytest

from app.llm import router as llm_router
from app.llm.base import LLMMessage, LLMRequest, LLMResponse, extract_json, extract_rows
from app.llm.prompts import (
    HARD_FLOOR,
    SERIOUS_FOCUS_HINTS,
    SERIOUS_MODE_POLICY,
    build_system_prompt,
    comments_prompt,
    density_target,
    knob_directives,
    moderation_prompt,
    personas_prompt,
    pick_focus,
    posts_prompt,
)
from app.llm.providers import (
    AnthropicProvider,
    GoogleProvider,
    LMStudioProvider,
    MockProvider,
    OpenAICompatibleProvider,
    OpenRouterProvider,
    build_provider,
)
from app.services import config_service


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fenced_block():
    assert extract_json('here you go:\n```json\n{"a": 1}\n```\nhope that helps') == {"a": 1}


def test_extract_json_from_surrounding_prose():
    assert extract_json('Sure! {"comments": [{"body": "hi"}]} — enjoy') == {
        "comments": [{"body": "hi"}]
    }


def test_extract_json_array():
    assert extract_json('leading text [1, 2, 3] trailing') == [1, 2, 3]


def test_extract_json_ignores_braces_inside_strings():
    assert extract_json('{"body": "use { and } freely"}') == {"body": "use { and } freely"}


def test_extract_json_handles_escaped_quotes():
    assert extract_json('{"body": "he said \\"no\\""}') == {"body": 'he said "no"'}


def test_extract_json_returns_none_for_garbage():
    assert extract_json("") is None
    assert extract_json("no json at all") is None
    assert extract_json("{unterminated") is None


def test_extract_json_repairs_trailing_commas():
    """The single most common malformed-JSON mistake from small local models."""
    assert extract_json('{"a": [1, 2, 3,], "b": 4,}') == {"a": [1, 2, 3], "b": 4}


def test_extract_json_repairs_trailing_comma_inside_a_fenced_block():
    text = '```json\n{"comments": [{"body": "hi"},]}\n```'
    assert extract_json(text) == {"comments": [{"body": "hi"}]}


def test_extract_rows_accepts_wrapped_or_bare_lists():
    assert extract_rows({"posts": [1, 2]}, "posts") == [1, 2]
    assert extract_rows([1, 2], "posts") == [1, 2]
    assert extract_rows({"posts": "not a list"}, "posts") is None
    assert extract_rows({"other_key": [1]}, "posts") is None
    assert extract_rows(None, "posts") is None
    assert extract_rows("garbage", "posts") is None


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #

def _request(**kwargs) -> LLMRequest:
    defaults = {
        "messages": [
            LLMMessage("system", "be a forum"),
            LLMMessage("user", "write comments"),
        ],
        "model": "some-model",
    }
    return LLMRequest(**{**defaults, **kwargs})


def test_openai_payload_and_headers():
    provider = OpenAICompatibleProvider(api_key="sk-test")
    payload = provider.build_payload(_request(json_mode=True))
    assert payload["model"] == "some-model"
    assert payload["messages"][0]["role"] == "system"
    assert payload["response_format"] == {"type": "json_object"}
    assert provider.build_headers()["Authorization"] == "Bearer sk-test"
    assert provider.endpoint(_request()).endswith("/chat/completions")


def test_openai_parses_content_parts():
    provider = OpenAICompatibleProvider()
    text, usage = provider.parse_response(
        {
            "choices": [{"message": {"content": [{"text": "hello"}, {"text": " world"}]}}],
            "usage": {"total_tokens": 5},
        }
    )
    assert text == "hello world"
    assert usage == {"total_tokens": 5}


def test_openai_parse_handles_empty_choices():
    assert OpenAICompatibleProvider().parse_response({}) == ("", {})


def test_openrouter_drops_response_format_and_adds_attribution():
    provider = OpenRouterProvider(api_key="sk-test")
    payload = provider.build_payload(_request(json_mode=True))
    assert "response_format" not in payload
    assert provider.build_headers()["X-Title"] == "ReadIt"
    assert provider.default_base_url.startswith("https://openrouter.ai")


def test_anthropic_hoists_system_and_caps_temperature():
    provider = AnthropicProvider(api_key="sk-ant")
    payload = provider.build_payload(_request(temperature=1.8))
    assert payload["system"] == "be a forum"
    assert payload["temperature"] == 1.0
    assert [m["role"] for m in payload["messages"]] == ["user"]
    assert provider.build_headers()["x-api-key"] == "sk-ant"


def test_anthropic_synthesises_a_user_turn_when_only_system_given():
    payload = AnthropicProvider().build_payload(
        _request(messages=[LLMMessage("system", "only system")])
    )
    assert payload["messages"][0]["content"] == "only system"


def test_anthropic_parses_text_blocks():
    text, _ = AnthropicProvider().parse_response(
        {"content": [{"type": "text", "text": "hi"}, {"type": "thinking", "text": "ignored"}]}
    )
    assert text == "hi"


def test_google_payload_shape():
    provider = GoogleProvider(api_key="key123")
    payload = provider.build_payload(_request(json_mode=True))
    assert payload["contents"][0]["role"] == "user"
    assert payload["systemInstruction"]["parts"][0]["text"] == "be a forum"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["safetySettings"]
    assert "key123" in provider.endpoint(_request())


def test_google_parses_candidates():
    text, _ = GoogleProvider().parse_response(
        {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    )
    assert text == "ab"


def test_build_provider_maps_types():
    assert isinstance(build_provider({"provider_type": "anthropic"}), AnthropicProvider)
    assert isinstance(build_provider({"provider_type": "google"}), GoogleProvider)
    assert isinstance(build_provider({"provider_type": "lmstudio"}), LMStudioProvider)
    assert isinstance(build_provider({"provider_type": "nonsense"}), MockProvider)


def test_build_provider_honours_custom_base_url():
    provider = build_provider(
        {"provider_type": "openai_compatible", "base_url": "http://localhost:1234/v1/"}
    )
    assert provider.base_url == "http://localhost:1234/v1"


def test_lmstudio_defaults_to_the_documented_local_server():
    """https://lmstudio.ai/docs/developer/core/server — default port 1234, /v1 base."""
    provider = build_provider({"provider_type": "lmstudio"})
    assert isinstance(provider, LMStudioProvider)
    assert provider.base_url == "http://localhost:1234/v1"
    assert provider.endpoint(_request()) == "http://localhost:1234/v1/chat/completions"


def test_lmstudio_omits_auth_header_without_a_key():
    provider = LMStudioProvider()
    assert "Authorization" not in provider.build_headers()


def test_lmstudio_sends_auth_header_when_a_key_is_set():
    provider = LMStudioProvider(api_key="local-secret")
    assert provider.build_headers()["Authorization"] == "Bearer local-secret"


def test_lmstudio_respects_a_custom_base_url_for_a_remote_lan_instance():
    provider = build_provider({"provider_type": "lmstudio", "base_url": "http://192.168.1.50:1234/v1"})
    assert provider.base_url == "http://192.168.1.50:1234/v1"


def test_lmstudio_drops_response_format_which_its_server_rejects():
    """LM Studio's server 400s on response_format.type "json_object" with
    'must be json_schema or text' — every JSON-mode call would otherwise fail."""
    payload = LMStudioProvider().build_payload(_request(json_mode=True))
    assert "response_format" not in payload


# --------------------------------------------------------------------------- #
# Mock provider
# --------------------------------------------------------------------------- #

async def test_mock_provider_returns_comment_shape():
    response = await MockProvider().complete(
        _request(messages=[LLMMessage("user", 'Return {"comments": [{"author": ...}]}')])
    )
    payload = response.json()
    assert isinstance(payload["comments"], list)
    assert payload["comments"]
    assert "body" in payload["comments"][0]


async def test_mock_provider_returns_post_shape():
    response = await MockProvider().complete(
        _request(messages=[LLMMessage("user", 'Return {"posts": [{"author": ...}]}')])
    )
    assert all("title" in row for row in response.json()["posts"])


async def test_mock_provider_distinguishes_shapes_despite_shared_vocabulary():
    """The style prompt mentions replies, posts and JSON — detection must not trip."""
    style = "Sometimes reply to the person above rather than the post. Return ONLY JSON."
    system, user = posts_prompt(
        config_service.DEFAULT_WORLD,
        {"name": "funny", "custom_prompt": "", "rules": []},
        [{"username": "A", "traits": ["dry"], "tone": "dry"}],
        count=2,
    )
    response = await MockProvider().complete(
        _request(messages=[LLMMessage("system", system + style), LLMMessage("user", user)])
    )
    assert "posts" in response.json()


async def test_mock_provider_is_deterministic_for_a_given_prompt():
    request = _request(messages=[LLMMessage("user", 'Return {"posts": []} please')])
    first = await MockProvider().complete(request)
    second = await MockProvider().complete(request)
    assert first.text == second.text


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

async def test_router_falls_back_to_mock_with_no_connections():
    response = await llm_router.generate("comment", [LLMMessage("user", "hi")])
    assert response.ok
    assert response.provider == "mock"


async def test_router_logs_calls_and_reports_stats():
    await llm_router.generate("comment", [LLMMessage("user", "hi")])
    stats = llm_router.call_stats()
    assert stats["total"] == 1
    assert stats["ok"] == 1
    assert llm_router.recent_calls()[0]["role"] == "comment"


def test_call_stats_empty():
    assert llm_router.call_stats()["total"] == 0


async def test_router_skips_broken_connection_and_still_answers(monkeypatch):
    config_service.add_connection(
        {"name": "Broken", "provider_type": "openai", "api_key": "bad", "models": ["gpt-4o-mini"]}
    )

    async def failing_complete(self, request):  # noqa: ANN001
        return LLMResponse(text="", model=request.model, provider=self.name, error="HTTP 401")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", failing_complete)

    response = await llm_router.generate("comment", [LLMMessage("user", "hi")])
    assert response.ok
    assert response.provider == "mock"
    assert llm_router.call_stats()["failed"] >= 1


async def test_router_returns_error_when_fallback_disabled(monkeypatch):
    config_service.add_connection(
        {"name": "Broken", "provider_type": "openai", "api_key": "bad", "models": ["m"]}
    )
    config_service.set_llm_flag("fallback_to_mock", False)

    async def failing_complete(self, request):  # noqa: ANN001
        return LLMResponse(text="", model=request.model, provider=self.name, error="HTTP 500")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", failing_complete)

    response = await llm_router.generate("comment", [LLMMessage("user", "hi")])
    assert not response.ok


async def test_router_uses_explicit_connection_when_asked(monkeypatch):
    connection = config_service.add_connection(
        {"name": "Primary", "provider_type": "openai", "api_key": "k", "models": ["chosen-model"]}
    )
    seen: dict[str, str] = {}

    async def capture(self, request):  # noqa: ANN001
        seen["model"] = request.model
        return LLMResponse(text="ok", model=request.model, provider=self.name)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", capture)

    response = await llm_router.generate(
        "comment", [LLMMessage("user", "hi")], connection_id=connection["id"]
    )
    assert response.ok
    assert seen["model"] == "chosen-model"


async def test_generate_json_parses_payload():
    parsed, response = await llm_router.generate_json(
        "comment", [LLMMessage("user", 'Return {"comments": [{"author": "x"}]}')]
    )
    assert response.ok
    assert "comments" in parsed


async def test_generate_json_retries_on_malformed_output(monkeypatch):
    """A resample after a parse failure is often enough to recover — small
    local models produce unusable JSON occasionally, not consistently."""
    config_service.add_connection(
        {"name": "Flaky", "provider_type": "openai", "api_key": "k", "models": ["m"]}
    )
    attempts = {"count": 0}

    async def flaky_complete(self, request):  # noqa: ANN001
        attempts["count"] += 1
        text = "not json at all" if attempts["count"] == 1 else '{"comments": [{"body": "ok"}]}'
        return LLMResponse(text=text, model=request.model, provider=self.name)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", flaky_complete)

    parsed, response = await llm_router.generate_json("comment", [LLMMessage("user", "hi")])
    assert response.ok
    assert parsed == {"comments": [{"body": "ok"}]}
    assert attempts["count"] == 2


async def test_generate_json_gives_up_after_exhausting_retries(monkeypatch):
    config_service.add_connection(
        {"name": "AlwaysBroken", "provider_type": "openai", "api_key": "k", "models": ["m"]}
    )

    async def broken_complete(self, request):  # noqa: ANN001
        return LLMResponse(text="not json, ever", model=request.model, provider=self.name)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", broken_complete)

    parsed, response = await llm_router.generate_json(
        "comment", [LLMMessage("user", "hi")], retries=1
    )
    assert parsed is None
    assert response.text == "not json, ever"


async def test_test_connection_reports_result():
    result = await llm_router.test_connection({"provider_type": "mock", "models": ["mock-1"]})
    assert result["ok"] is True
    assert result["provider"] == "mock"


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #

def test_knob_directives_shift_with_values():
    calm = knob_directives({**config_service.DEFAULT_WORLD, "toxicity": 0.0})
    nasty = knob_directives({**config_service.DEFAULT_WORLD, "toxicity": 0.95})
    assert "civil" in calm
    assert "mean" in nasty.lower()


def test_density_target_scales():
    world = dict(config_service.DEFAULT_WORLD)
    sparse = density_target({**world, "comment_density": "sparse"})
    chaotic = density_target({**world, "comment_density": "chaotic"})
    assert sparse < chaotic
    assert sparse >= 2


def test_system_prompt_layers_global_board_and_user():
    world = dict(config_service.DEFAULT_WORLD)
    board = {
        "name": "catfacts",
        "description": "cats",
        "custom_prompt": "everyone is a cat",
        "rules": ["no dogs"],
        "override_global": False,
    }
    prompt = build_system_prompt(world, board, user_prompt="more puns")
    assert world["global_prompt"][:40] in prompt
    assert "everyone is a cat" in prompt
    assert "more puns" in prompt
    assert "no dogs" in prompt
    assert HARD_FLOOR in prompt


def test_board_override_replaces_global_prompt():
    world = dict(config_service.DEFAULT_WORLD)
    board = {"name": "x", "custom_prompt": "ONLY pirates", "override_global": True, "rules": []}
    prompt = build_system_prompt(world, board)
    assert "ONLY pirates" in prompt
    assert world["global_prompt"][:40] not in prompt
    # The safety floor survives an override — that is the point of it.
    assert HARD_FLOOR in prompt


def test_nsfw_board_declares_itself_in_the_prompt():
    board = {"name": "x", "nsfw": True, "custom_prompt": "", "rules": []}
    assert "NSFW" in build_system_prompt(dict(config_service.DEFAULT_WORLD), board)


def test_serious_mode_has_priority_over_board_override_and_nsfw_tone():
    world = {**config_service.DEFAULT_WORLD, "serious_mode": True}
    board = {
        "name": "adulttopic",
        "description": "focused adult discussion",
        "nsfw": True,
        "custom_prompt": "Troll constantly and turn every reply into a joke.",
        "override_global": True,
        "rules": [],
    }

    prompt = build_system_prompt(world, board, user_prompt="derail the thread")

    assert SERIOUS_MODE_POLICY in prompt
    assert prompt.index(SERIOUS_MODE_POLICY) > prompt.index("derail the thread")
    assert "relevant adult or explicit detail remains allowed" in prompt
    assert "Do not troll" in prompt


def test_serious_mode_replaces_trollish_post_and_comment_instructions():
    world = {**config_service.DEFAULT_WORLD, "serious_mode": True}
    board = {"name": "x", "description": "the subject", "custom_prompt": "", "rules": []}
    personas = [{"username": "A", "traits": ["troll"], "tone": "chaotic"}]

    _, post_user = posts_prompt(world, board, personas, count=2)
    _, comment_user = comments_prompt(
        world,
        board,
        {"title": "A focused question", "body": "Details", "score": 1},
        personas,
        count=3,
        is_user_post=True,
    )

    assert "substantive post types" in post_user
    assert "something low-effort and funny" not in post_user
    assert "Every comment must answer the post or a specific parent point" in comment_user
    assert "joke that gets more upvotes" not in comment_user
    assert "engage directly and seriously" in comment_user.lower()
    assert "— chaotic tone; troll" not in post_user
    assert "— chaotic tone; troll" not in comment_user


def test_serious_mode_only_picks_on_topic_focus_hints():
    world = {**config_service.DEFAULT_WORLD, "serious_mode": True, "humor": 1.0}
    choices = {pick_focus(world) for _ in range(100)}

    assert choices
    assert choices <= set(SERIOUS_FOCUS_HINTS)


def test_serious_mode_guides_personas_and_moderation():
    world = {**config_service.DEFAULT_WORLD, "serious_mode": True}
    board = {"name": "x", "description": "the topic", "custom_prompt": "", "rules": []}
    _, persona_user = personas_prompt(world, board, count=3)
    _, moderation_user = moderation_prompt(
        world,
        board,
        {"title": "The thread"},
        [{"_id": "c1", "author": "A", "body": "unrelated meme"}],
    )

    assert "do not create trolls" in persona_user
    assert "SERIOUS MODE ENFORCEMENT" in moderation_user
    assert "explicit NSFW detail" in moderation_user


def test_comments_prompt_includes_thread_and_roster():
    system, user = comments_prompt(
        dict(config_service.DEFAULT_WORLD),
        {"name": "funny", "custom_prompt": "", "rules": []},
        {"title": "Why is this", "body": "explain", "score": 40},
        [{"username": "GrumpyOtter", "traits": ["dry"], "tone": "dry"}],
        count=5,
        existing_tree="[c1] Someone: first",
        focus="an argument starts",
    )
    assert "GrumpyOtter" in user
    assert "[c1] Someone: first" in user
    assert "an argument starts" in user
    assert "Write 5 new comments" in user
    assert '{"comments":' in user.replace(" ", "")
    assert HARD_FLOOR in system


def test_comments_prompt_flags_human_op():
    _, user = comments_prompt(
        dict(config_service.DEFAULT_WORLD),
        {"name": "funny", "custom_prompt": "", "rules": []},
        {"title": "t", "body": "b", "score": 1},
        [{"username": "A", "traits": [], "tone": "dry"}],
        count=2,
        is_user_post=True,
    )
    assert "real human" in user


def test_posts_prompt_lists_existing_titles_to_avoid():
    _, user = posts_prompt(
        dict(config_service.DEFAULT_WORLD),
        {"name": "funny", "custom_prompt": "", "rules": []},
        [{"username": "A", "traits": [], "tone": "dry"}],
        count=3,
        existing_titles=["An old title"],
    )
    assert "An old title" in user
    assert "do not repeat" in user.lower()


# --------------------------------------------------------------------------- #
# Disabled connections
# --------------------------------------------------------------------------- #

async def test_disabled_connection_is_never_used(monkeypatch):
    """Switching a connection off must actually stop traffic to it.

    Regression: the default-connection fallback skipped the enabled check, so a
    disabled connection kept serving every request.
    """
    connection = config_service.add_connection(
        {"name": "Local", "provider_type": "openai", "api_key": "k", "models": ["m"]}
    )
    config_service.set_role("comment", connection["id"], "m")
    config_service.update_connection(connection["id"], {"enabled": False})

    async def should_not_run(self, request):  # noqa: ANN001
        raise AssertionError("a disabled connection was called")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", should_not_run)

    response = await llm_router.generate("comment", [LLMMessage("user", "hi")])
    assert response.provider == "mock"


async def test_disabled_connection_ignored_even_when_named_explicitly(monkeypatch):
    connection = config_service.add_connection(
        {"name": "Local", "provider_type": "openai", "api_key": "k", "models": ["m"]}
    )
    config_service.update_connection(connection["id"], {"enabled": False})

    async def should_not_run(self, request):  # noqa: ANN001
        raise AssertionError("a disabled connection was called")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", should_not_run)

    response = await llm_router.generate(
        "comment", [LLMMessage("user", "hi")], connection_id=connection["id"]
    )
    assert response.provider == "mock"


async def test_re_enabling_restores_traffic(monkeypatch):
    connection = config_service.add_connection(
        {"name": "Local", "provider_type": "openai", "api_key": "k", "models": ["m"]}
    )
    config_service.set_role("comment", connection["id"], "m")
    config_service.update_connection(connection["id"], {"enabled": False})
    config_service.update_connection(connection["id"], {"enabled": True})

    async def works(self, request):  # noqa: ANN001
        return LLMResponse(text="real output", model=request.model, provider=self.name)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", works)
    response = await llm_router.generate("comment", [LLMMessage("user", "hi")])
    assert response.provider == "openai"


def test_autonomous_generation_gate():
    # Never configured: the offline generator is the intended experience.
    assert config_service.autonomous_generation_allowed() is True

    connection = config_service.add_connection({"name": "A", "provider_type": "mock"})
    assert config_service.autonomous_generation_allowed() is True

    # Deliberately switched off: the world should stop, not fall back to mock.
    config_service.update_connection(connection["id"], {"enabled": False})
    assert config_service.autonomous_generation_allowed() is False


async def test_background_world_stops_when_every_connection_is_off(board):
    from app.db import db
    from app.services import simulation, user_service

    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], board["name"])
    connection = config_service.add_connection({"name": "A", "provider_type": "mock"})
    config_service.update_connection(connection["id"], {"enabled": False})

    result = await simulation.engine.tick()

    assert result["idle_no_model"] is True
    assert result["boards_refreshed"] == 0
    assert db.collection("posts").count() == 0


async def test_background_world_still_runs_on_a_fresh_install(board):
    """No connections at all must not leave the front page permanently empty."""
    from app.db import db
    from app.services import simulation, user_service

    user = user_service.register("sam@example.com", "hunter22", "samwise")
    user_service.subscribe(user["_id"], board["name"])

    result = await simulation.engine.tick()
    assert result["idle_no_model"] is False
    assert db.collection("posts").count() > 0
