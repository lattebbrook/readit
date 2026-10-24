"""Provider-agnostic chat completion interface."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings


@dataclass
class LLMImage:
    """An image attached to a message.

    Held as raw bytes rather than a URL because the models that matter here are
    local — a self-hosted runtime cannot fetch an ``http://localhost`` link from
    inside its own sandbox, and remote providers would need the file to be
    publicly reachable, which a local-only forum never is.
    """

    data: bytes
    mime: str = "image/jpeg"

    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.b64()}"


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str
    images: list[LLMImage] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """OpenAI-shaped serialisation.

        Text-only messages keep the plain-string ``content`` form; some
        OpenAI-compatible servers are stricter about that than the spec is.
        """
        if not self.images:
            return {"role": self.role, "content": self.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": self.content}]
        parts.extend(
            {"type": "image_url", "image_url": {"url": image.data_uri()}}
            for image in self.images
        )
        return {"role": self.role, "content": parts}


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str
    temperature: float = 0.95
    max_tokens: int = 2048
    json_mode: bool = False
    top_p: float = 0.95
    stop: list[str] | None = None


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    latency_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def json(self) -> Any:
        """Best-effort structured parse of the response body."""
        return extract_json(self.text)


class LLMError(RuntimeError):
    """Raised when a provider call fails in a way the caller should handle."""


_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _loads_lenient(candidate: str) -> Any:
    """``json.loads`` with one repair attempt for the most common small-model
    mistake: a trailing comma before a closing brace or bracket."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _TRAILING_COMMA.sub(r"\1", candidate)
        if repaired == candidate:
            raise
        return json.loads(repaired)


def extract_json(text: str) -> Any:
    """Pull the first JSON value out of a model response.

    Models wrap JSON in prose or fences more often than not, so try the cheap
    parse first, then a fenced block, then a brace/bracket scan.
    """
    if not text:
        return None
    stripped = text.strip()
    try:
        return _loads_lenient(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", stripped, re.DOTALL)
    if fenced:
        try:
            return _loads_lenient(fenced.group(1).strip())
        except json.JSONDecodeError:
            stripped = fenced.group(1).strip()

    # Scan from whichever delimiter appears first. Trying "[" unconditionally
    # would pull the inner array out of `{"comments": [...]}` and lose the object.
    candidates = [
        (index, opener, closer)
        for opener, closer in (("[", "]"), ("{", "}"))
        if (index := stripped.find(opener)) != -1
    ]
    for start, opener, closer in sorted(candidates):
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : index + 1]
                    try:
                        return _loads_lenient(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def extract_rows(parsed: Any, key: str) -> list[Any] | None:
    """Pull a list of rows out of a parsed JSON response.

    Every prompt asks for an object like ``{"posts": [...]}``, but smaller and
    local models — the exact case a self-hosted LM Studio/Ollama connection
    exists for — routinely drop the wrapper and return the bare array instead.
    Accept both shapes rather than silently discarding an otherwise good
    response just because the wrapper key is missing.
    """
    if isinstance(parsed, dict):
        rows = parsed.get(key)
        return rows if isinstance(rows, list) else None
    if isinstance(parsed, list):
        return parsed
    return None


class BaseProvider:
    """Common HTTP plumbing shared by the hosted providers."""

    name: str = "base"
    default_base_url: str = ""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.extra_headers = extra_headers or {}
        self.timeout = timeout or settings.request_timeout_seconds

    # -- to implement in subclasses ----------------------------------------- #

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        raise NotImplementedError

    def build_headers(self) -> dict[str, str]:
        raise NotImplementedError

    def endpoint(self, request: LLMRequest) -> str:
        raise NotImplementedError

    def parse_response(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    # -- shared -------------------------------------------------------------- #

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint(request),
                    headers={**self.build_headers(), **self.extra_headers},
                    json=self.build_payload(request),
                )
            elapsed = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return LLMResponse(
                    text="",
                    model=request.model,
                    provider=self.name,
                    latency_ms=elapsed,
                    error=f"HTTP {response.status_code}: {response.text[:400]}",
                )
            text, usage = self.parse_response(response.json())
            return LLMResponse(
                text=text,
                model=request.model,
                provider=self.name,
                latency_ms=elapsed,
                usage=usage,
            )
        except Exception as exc:  # network, timeout, malformed body
            elapsed = int((time.perf_counter() - started) * 1000)
            return LLMResponse(
                text="",
                model=request.model,
                provider=self.name,
                latency_ms=elapsed,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def list_models(self) -> list[str]:
        """Optional capability; providers that can enumerate models override this."""
        return []
