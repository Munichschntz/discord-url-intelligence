"""Validated environment-backed settings for the application."""

from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _snowflake(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Discord IDs must be decimal strings or integers")
    normalized = str(value)
    if not normalized.isascii() or not normalized.isdecimal() or int(normalized) <= 0:
        raise ValueError("Discord IDs must be positive decimal values")
    return normalized


class Settings(BaseSettings):
    """Configuration shared by the collector, worker, and web processes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    discord_bot_token: SecretStr | None = None
    discord_guild_id: str | None = None
    allowed_source_channel_ids: list[str] = Field(default_factory=list)
    web_visible_channel_ids: list[str] = Field(default_factory=list)
    discord_oauth_client_id: str | None = None
    discord_oauth_client_secret: SecretStr | None = None
    discord_oauth_redirect_uri: str | None = None
    web_session_secret: SecretStr | None = None
    database_path: Path = Path("data/discord-intel.sqlite3")
    github_token: SecretStr | None = None
    hf_token: SecretStr | None = None
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    worker_max_attempts: int = Field(default=5, ge=1, le=20)
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=4710, ge=1, le=65535)
    mcp_host: str = "127.0.0.1"
    mcp_port: int = Field(default=4711, ge=1, le=65535)

    @field_validator("discord_guild_id", "discord_oauth_client_id", mode="before")
    @classmethod
    def validate_optional_ids(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        return _snowflake(value)

    @field_validator("allowed_source_channel_ids", "web_visible_channel_ids")
    @classmethod
    def validate_channel_ids(cls, values: list[str]) -> list[str]:
        return [_snowflake(value) for value in values]

    @field_validator("lm_studio_base_url")
    @classmethod
    def validate_lm_studio_base_url(cls, value: str) -> str:
        TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("discord_oauth_redirect_uri")
    @classmethod
    def validate_oauth_redirect_uri(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path != "/auth/callback"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OAuth redirect URI must be an exact HTTPS /auth/callback URL")
        return value

    @field_validator("web_host", "mcp_host")
    @classmethod
    def validate_loopback_host(cls, value: str) -> str:
        try:
            address = ip_address(value)
        except ValueError as error:
            raise ValueError("Web and MCP hosts must be loopback IP addresses") from error
        if not address.is_loopback:
            raise ValueError("Web and MCP hosts must be loopback IP addresses")
        return str(address)

    @model_validator(mode="after")
    def validate_web_visibility(self) -> "Settings":
        if not set(self.web_visible_channel_ids).issubset(self.allowed_source_channel_ids):
            raise ValueError("Web-visible channels must also be in the source-channel allowlist")
        return self


def load_settings() -> Settings:
    """Load validated settings from the process environment and optional .env file."""
    return Settings()