import math
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.features.allowlist_balancer import (
    PROFILE_NAME, normalize_profile_flag, normalize_profile_name, normalize_profile_description,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    upstream_base_url: str = Field(
        default="",
        validation_alias="UPSTREAM_BASE_URL",
    )
    upstream_json_path: str = Field(
        default="/json",
        validation_alias="UPSTREAM_JSON_PATH",
    )
    agent_json_path: str = Field(
        default="",
        validation_alias="AGENT_JSON_PATH",
    )
    request_timeout_sec: float = Field(
        default=15.0,
        validation_alias="REQUEST_TIMEOUT_SEC",
    )
    upstream_verify_ssl: bool = Field(
        default=True,
        validation_alias="UPSTREAM_VERIFY_SSL",
    )
    upstream_host_header: str = Field(
        default="",
        validation_alias="UPSTREAM_HOST_HEADER",
    )
    agent_host: str = Field(default="127.0.0.1", validation_alias="AGENT_HOST")
    agent_port: int = Field(default=8080, validation_alias="AGENT_PORT")
    transform_mode: str = Field(
        default="ios-fix",
        validation_alias="TRANSFORM_MODE",
    )
    allowlist_balancer_enabled: bool = Field(
        default=True, validation_alias="ALLOWLIST_BALANCER_ENABLED",
    )
    allowlist_balancer_name: str = Field(
        default=PROFILE_NAME, validation_alias="ALLOWLIST_BALANCER_NAME",
    )
    allowlist_balancer_flag: str = Field(
        default="", validation_alias="ALLOWLIST_BALANCER_FLAG",
    )
    allowlist_balancer_description: str = Field(
        default="auto", validation_alias="ALLOWLIST_BALANCER_DESCRIPTION",
    )
    allowlist_probe_url: str = Field(
        default="https://www.gstatic.com/generate_204", validation_alias="ALLOWLIST_PROBE_URL",
    )
    allowlist_probe_interval_sec: float = Field(
        default=20.0, ge=1, le=3600, validation_alias="ALLOWLIST_PROBE_INTERVAL_SEC",
    )
    db_path: str = Field(
        default="data/middleware.db",
        validation_alias="DB_PATH",
    )

    @field_validator("allowlist_balancer_name")
    @classmethod
    def validate_balancer_name(cls, value: str) -> str:
        return normalize_profile_name(value)

    @field_validator("allowlist_balancer_flag")
    @classmethod
    def validate_balancer_flag(cls, value: str) -> str:
        return normalize_profile_flag(value)

    @field_validator("allowlist_balancer_description")
    @classmethod
    def validate_balancer_description(cls, value: str) -> str:
        return normalize_profile_description(value)

    @field_validator("allowlist_probe_url")
    @classmethod
    def validate_probe_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if any(c.isspace() for c in value) or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("ALLOWLIST_PROBE_URL must be HTTPS without credentials or fragment")
        parsed.port  # Also reject malformed/out-of-range ports.
        return value

    @field_validator("allowlist_probe_interval_sec")
    @classmethod
    def validate_probe_interval(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("probe interval must be finite")
        return value

    def resolved_agent_json_path(self) -> str:
        explicit = self.agent_json_path.strip()
        if explicit:
            return explicit.rstrip("/")
        return self.upstream_json_path.rstrip("/")

    def resolved_upstream_base_url(self) -> str:
        return self.upstream_base_url.strip().rstrip("/")


settings = Settings()
