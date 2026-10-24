"""Concrete LLM providers: OpenRouter, OpenAI-compatible, Anthropic, Google, mock."""

from __future__ import annotations

import hashlib
import random
from typing import Any

import httpx

from app.llm.base import BaseProvider, LLMMessage, LLMRequest, LLMResponse


class OpenAICompatibleProvider(BaseProvider):
    """Any endpoint that speaks the OpenAI ``/chat/completions`` schema."""

    name = "openai_compatible"
    default_base_url = "https://api.openai.com/v1"

    def endpoint(self, request: LLMRequest) -> str:
        return f"{self.base_url}/chat/completions"

    def build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [message.as_dict() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
        }
        if request.stop:
            payload["stop"] = request.stop
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def parse_response(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        choices = data.get("choices") or []
        if not choices:
            return "", data.get("usage", {})
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # some gateways return content parts
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return content or "", data.get("usage", {})

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self.build_headers()
                )
            if response.status_code >= 400:
                return []
            payload = response.json()
            return sorted(
                item.get("id", "") for item in payload.get("data", []) if item.get("id")
            )
        except Exception:
            return []


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"


class LMStudioProvider(OpenAICompatibleProvider):
    """A local LM Studio server.

    LM Studio speaks the same OpenAI-compatible schema — its server defaults
    to ``http://localhost:1234/v1``, with chat completions at
    ``/v1/chat/completions`` (see https://lmstudio.ai/docs/developer/core/server
    and https://lmstudio.ai/docs/developer/openai-compat). The local server
    does not enforce an API key, so one is only sent if the admin set one.
    """

    name = "lmstudio"
    default_base_url = "http://localhost:1234/v1"

    def build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload = super().build_payload(request)
        # LM Studio's server rejects response_format.type "json_object" outright
        # ("must be 'json_schema' or 'text'"), which would fail every call that
        # asks for JSON. Every prompt already instructs the model to return JSON
        # directly, so the API-level hint isn't needed — drop it instead.
        payload.pop("response_format", None)
        return payload


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter: a single endpoint fronting many vendors' models."""

    name = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"

    def build_headers(self) -> dict[str, str]:
        return {
            **super().build_headers(),
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "ReadIt",
        }

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload = super().build_payload(request)
        # OpenRouter rejects json_object mode on models that do not support it,
        # and the prompts already demand JSON, so leave routing free.
        payload.pop("response_format", None)
        return payload


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"

    def endpoint(self, request: LLMRequest) -> str:
        return f"{self.base_url}/messages"

    def build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _message_dict(message: LLMMessage) -> dict[str, Any]:
        """Anthropic wraps images in a ``source`` block rather than a data URI."""
        if not message.images:
            return message.as_dict()
        parts: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.mime,
                    "data": image.b64(),
                },
            }
            for image in message.images
        ]
        # Images before text reads better to the model when the text is a
        # question about the picture.
        parts.append({"type": "text", "text": message.content})
        return {"role": message.role, "content": parts}

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        system_chunks = [m.content for m in request.messages if m.role == "system"]
        conversation = [
            self._message_dict(m) for m in request.messages if m.role in {"user", "assistant"}
        ]
        if not conversation:
            conversation = [{"role": "user", "content": "\n".join(system_chunks) or "Hello"}]
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": conversation,
            "max_tokens": request.max_tokens,
            "temperature": min(request.temperature, 1.0),
        }
        if system_chunks:
            payload["system"] = "\n\n".join(system_chunks)
        if request.stop:
            payload["stop_sequences"] = request.stop
        return payload

    def parse_response(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        blocks = data.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return text, data.get("usage", {})


class GoogleProvider(BaseProvider):
    """Google AI Studio (Gemini) generateContent endpoint."""

    name = "google"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def endpoint(self, request: LLMRequest) -> str:
        return f"{self.base_url}/models/{request.model}:generateContent?key={self.api_key}"

    def build_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        system_chunks = [m.content for m in request.messages if m.role == "system"]
        contents = [
            {
                "role": "model" if message.role == "assistant" else "user",
                # Gemini calls it inline_data with a raw base64 payload.
                "parts": [
                    *(
                        {"inline_data": {"mime_type": image.mime, "data": image.b64()}}
                        for image in message.images
                    ),
                    {"text": message.content},
                ],
            }
            for message in request.messages
            if message.role in {"user", "assistant"}
        ]
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "\n".join(system_chunks)}]}]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                "topP": request.top_p,
            },
        }
        if system_chunks:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_chunks)}]}
        if request.json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        # The forum deliberately hosts heated argument and edgy humour; relax the
        # default filters so ordinary satire is not silently dropped.
        payload["safetySettings"] = [
            {"category": category, "threshold": "BLOCK_ONLY_HIGH"}
            for category in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]
        return payload

    def parse_response(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        candidates = data.get("candidates") or []
        if not candidates:
            return "", data.get("usageMetadata", {})
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return text, data.get("usageMetadata", {})

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/models?key={self.api_key}")
            if response.status_code >= 400:
                return []
            return sorted(
                item.get("name", "").removeprefix("models/")
                for item in response.json().get("models", [])
                if item.get("name")
            )
        except Exception:
            return []


class MockProvider(BaseProvider):
    """Offline fallback so the forum stays alive without any API key.

    It produces structurally valid JSON for every prompt shape the app asks for,
    seeded off the prompt text so output is varied but reproducible.
    """

    name = "mock"

    OPINIONS = [
        "honestly this is the most reasonable take I've seen all week",
        "hard disagree, and I'll die on this hill",
        "ok but nobody's going to say the obvious thing here so I will",
        "this reads like it was written by someone who has never actually tried it",
        "wait, everyone in this thread is missing the point entirely",
        "source: I do this for a living and OP is about 70% right",
        "I was fully with you until the last paragraph",
        "the fact that this needs saying is the real story",
    ]
    SNARK = [
        "lmao the confidence",
        "brave of you to post this",
        "found the person who read the headline only",
        "this is the funniest thing I've read today, unironically",
        "bold strategy Cotton",
    ]
    TITLES = [
        "Am I the only one who thinks this is completely backwards?",
        "After 6 years I finally figured out the thing everyone told me was obvious",
        "Unpopular opinion: the 'good old days' were mostly survivorship bias",
        "This tiny detail has been driving me insane for months",
        "PSA: the advice everyone repeats here is actively wrong",
        "I tracked this for a year and the results surprised me",
        "What's the smallest hill you'll die on?",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    # Keyed off the JSON skeleton each contract asks for, which is unique per
    # task. Matching on loose keywords misfires — the style prompt alone
    # mentions replies, posts and JSON.
    _SHAPES = (
        ('{"comments":', "_mock_comments"),
        ('{"posts":', "_mock_posts"),
        ('{"decisions":', "_mock_moderation"),
        ('{"personas":', "_mock_personas"),
        # Must precede the board-meta probe: both contracts open with
        # `{"caption"` / `{"description"` and the image one is more specific.
        ('{"caption":', "_mock_image_analysis"),
        ('{"description":', "_mock_board_meta"),
    )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        prompt = "\n".join(message.content for message in request.messages)
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        compact = prompt.replace(" ", "")

        text = rng.choice(self.OPINIONS)
        for marker, handler in self._SHAPES:
            if marker in compact:
                text = getattr(self, handler)(rng)
                break

        return LLMResponse(text=text, model=request.model or "mock-1", provider=self.name)

    def _mock_moderation(self, rng: random.Random) -> str:
        import json as _json

        return _json.dumps({"decisions": []})

    def _mock_board_meta(self, rng: random.Random) -> str:
        import json as _json

        return _json.dumps(
            {
                "description": "A board that has been arguing about this since 2011.",
                "sidebar": "Read the rules. Nobody reads the rules. Post anyway.",
                "rules": ["Stay on topic", "Don't be a jerk", "No reposts from last week"],
                "topics": ["daily threads", "long-running feuds", "newcomer questions"],
                "nsfw": False,
            }
        )

    def _mock_image_analysis(self, rng: random.Random) -> str:
        import json as _json

        subject = rng.choice(["photo", "screenshot", "artwork", "meme"])
        return _json.dumps(
            {
                "caption": "An image somebody posted without much explanation.",
                "detailed_description": (
                    "The offline generator cannot actually see images. Connect a vision-capable "
                    "model in Admin to get real descriptions."
                ),
                "visible_text": "",
                "subject_type": subject,
                "tags": rng.sample(
                    ["untagged", "offline", "placeholder", "unsorted", "queued"], 3
                ),
                "mood": rng.choice(["ambiguous", "flat", "unclear"]),
                "technical_notes": "No vision model was available when this was ingested.",
                "discussion_hooks": [
                    "whether the thing in the picture is actually what OP claims",
                    "someone insisting the composition is off",
                    "a tangent about the gear that shot it",
                ],
                "suggested_titles": [
                    "found this earlier, thoughts?",
                    "no idea what I'm looking at here",
                ],
                "nsfw": False,
                "depicts_identifiable_person": False,
            }
        )

    def _mock_comments(self, rng: random.Random) -> str:
        import json as _json

        count = rng.randint(6, 14)
        rows = []
        for index in range(count):
            body = rng.choice(self.OPINIONS if rng.random() > 0.35 else self.SNARK)
            # Leaving `author` unset lets the caller pick from the real roster.
            rows.append(
                {
                    "body": body,
                    "reply_to": f"n{rng.randint(0, index - 1)}"
                    if index > 1 and rng.random() > 0.45
                    else None,
                    "tone": rng.choice(["funny", "serious", "angry", "supportive", "sarcastic"]),
                    "quality": round(rng.uniform(0.15, 0.95), 2),
                    "controversy": round(rng.uniform(0.05, 0.85), 2),
                }
            )
        return _json.dumps({"comments": rows})

    def _mock_posts(self, rng: random.Random) -> str:
        import json as _json

        count = rng.randint(3, 5)
        return _json.dumps(
            {
                "posts": [
                    {
                        "title": rng.choice(self.TITLES),
                        "body": f"{rng.choice(self.OPINIONS)}. {rng.choice(self.OPINIONS)}.",
                        "kind": "text",
                        "flair": rng.choice(["Discussion", "Rant", "Question", ""]),
                        "quality": round(rng.uniform(0.2, 0.95), 2),
                        "controversy": round(rng.uniform(0.05, 0.85), 2),
                    }
                    for _ in range(count)
                ]
            }
        )

    def _mock_personas(self, rng: random.Random) -> str:
        import json as _json

        adjectives = ["Grumpy", "Tired", "Chaotic", "Mild", "Loud", "Quiet", "Feral"]
        nouns = ["Otter", "Toaster", "Barnacle", "Comet", "Pigeon", "Kettle", "Moss"]
        return _json.dumps(
            {
                "personas": [
                    {
                        "username": f"{rng.choice(adjectives)}{rng.choice(nouns)}{rng.randint(10, 99)}",
                        "bio": "posts too much, regrets little",
                        "traits": rng.sample(
                            ["sarcastic", "earnest", "pedantic", "warm", "blunt", "anxious"], 2
                        ),
                        "tone": rng.choice(["dry", "chaotic", "academic", "casual"]),
                    }
                    for _ in range(6)
                ]
            }
        )

    def endpoint(self, request: LLMRequest) -> str:  # pragma: no cover - unused
        return ""

    def build_headers(self) -> dict[str, str]:  # pragma: no cover - unused
        return {}

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:  # pragma: no cover
        return {}

    def parse_response(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:  # pragma: no cover
        return "", {}


PROVIDER_TYPES: dict[str, type[BaseProvider]] = {
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "lmstudio": LMStudioProvider,
    "mock": MockProvider,
}

PROVIDER_DEFAULT_MODELS: dict[str, list[str]] = {
    "openrouter": [
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-4o-mini",
        "google/gemini-2.5-flash",
        "meta-llama/llama-3.3-70b-instruct",
        "mistralai/mistral-nemo",
    ],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    "anthropic": ["claude-sonnet-4-5", "claude-haiku-4-5-20251001"],
    "google": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "openai_compatible": ["local-model"],
    # Left empty on purpose — the real list depends on whatever is loaded in
    # LM Studio right now. Use "Fetch models" after adding the connection.
    "lmstudio": [],
    "mock": ["mock-1"],
}


def build_provider(config: dict[str, Any]) -> BaseProvider:
    """Instantiate a provider from a stored connection document."""
    provider_type = config.get("provider_type", "mock")
    provider_class = PROVIDER_TYPES.get(provider_type, MockProvider)
    return provider_class(
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url") or None,
        extra_headers=config.get("extra_headers") or {},
        timeout=config.get("timeout") or None,
    )
