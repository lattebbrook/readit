"""Request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

class RegisterRequest(BaseModel):
    email: str
    password: str
    username: str


class LoginRequest(BaseModel):
    email: str
    password: str


class GuestRequest(BaseModel):
    display_hint: str = ""


class PromoteGuestRequest(BaseModel):
    email: str
    password: str
    username: str


class AuthResponse(BaseModel):
    token: str
    user: dict[str, Any]


# --------------------------------------------------------------------------- #
# Profile and settings
# --------------------------------------------------------------------------- #

class ProfileUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    banner_color: str | None = None
    personal_prompt: str | None = None


class PreferencesUpdate(BaseModel):
    preferences: dict[str, Any]


class InterestsUpdate(BaseModel):
    interests: list[str]


class WipeRequest(BaseModel):
    delete_account: bool = False
    confirm: str = Field(default="", description="Must equal 'WIPE' to proceed.")


# --------------------------------------------------------------------------- #
# Boards
# --------------------------------------------------------------------------- #

class BoardCreate(BaseModel):
    name: str
    kind: Literal["text", "photo"] = "text"
    title: str = ""
    description: str = ""
    custom_prompt: str = ""
    override_global: bool = False
    nsfw: bool = False
    rules: list[str] | None = None
    topics: list[str] | None = None
    overrides: dict[str, Any] | None = None
    autofill: bool = True
    generate_metadata: bool = True


class BoardUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    sidebar: str | None = None
    rules: list[str] | None = None
    topics: list[str] | None = None
    custom_prompt: str | None = None
    override_global: bool | None = None
    nsfw: bool | None = None
    color: str | None = None
    banner_color: str | None = None
    icon: str | None = None
    allow_user_posts: bool | None = None
    moderation_enabled: bool | None = None
    activity_level: float | None = None
    kind: Literal["text", "photo"] | None = None
    overrides: dict[str, Any] | None = None


class PersonalPromptUpdate(BaseModel):
    prompt: str = ""


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #

class MediaUrlIngest(BaseModel):
    url: str
    source_page: str = ""
    board: str = ""


class PostCreate(BaseModel):
    subreddit: str
    title: str
    body: str = ""
    kind: Literal["text", "link", "image"] = "text"
    link_url: str = ""
    media_id: str | None = None
    flair: str = ""
    nsfw: bool = False
    spoiler: bool = False
    generate_replies: bool = True


class PostEdit(BaseModel):
    title: str | None = None
    body: str | None = None


class CommentCreate(BaseModel):
    body: str
    parent_id: str | None = None
    generate_replies: bool = True


class CommentEdit(BaseModel):
    body: str


class VoteRequest(BaseModel):
    direction: int = Field(ge=-1, le=1)


class AwardRequest(BaseModel):
    award_id: str
    anonymous: bool = False


class ReportRequest(BaseModel):
    reason: str


class GenerateRequest(BaseModel):
    count: int | None = Field(default=None, ge=1, le=30)
    focus: str | None = None


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #

class WorldUpdate(BaseModel):
    global_prompt: str | None = None
    style_prompt: str | None = None
    site_description: str | None = None
    serious_mode: bool | None = None
    humor: float | None = None
    toxicity: float | None = None
    argument_rate: float | None = None
    wholesomeness: float | None = None
    shitpost_rate: float | None = None
    expertise: float | None = None
    comment_density: str | None = None
    thread_depth: int | None = None
    allow_nsfw: bool | None = None
    moderation_enabled: bool | None = None
    moderation_strictness: float | None = None
    removal_rate: float | None = None
    award_rate: float | None = None
    user_vote_bonus: float | None = None
    vote_volatility: float | None = None
    simulation_enabled: bool | None = None
    background_activity: bool | None = None
    tick_seconds: float | None = None
    max_comments_per_thread: int | None = None
    posts_per_board_target: int | None = None


class ConnectionCreate(BaseModel):
    name: str = ""
    provider_type: Literal[
        "openrouter", "openai", "anthropic", "google", "openai_compatible", "lmstudio", "mock"
    ]
    api_key: str = ""
    base_url: str = ""
    models: list[str] | None = None
    enabled: bool = True
    weight: int = 1
    extra_headers: dict[str, str] | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str | None = None
    models: list[str] | None = None
    enabled: bool | None = None
    weight: int | None = None
    extra_headers: dict[str, str] | None = None


class RoleUpdate(BaseModel):
    connection_id: str | None = None
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None


class LLMFlagUpdate(BaseModel):
    fallback_to_mock: bool | None = None
    multi_model_mixing: bool | None = None
    default_connection_id: str | None = None


class TestConnectionRequest(BaseModel):
    model: str | None = None


class SeedRequest(BaseModel):
    board_limit: int = Field(default=6, ge=1, le=30)
    posts_per_board: int = Field(default=5, ge=1, le=15)
