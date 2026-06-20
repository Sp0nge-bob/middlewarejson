from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        default="passthrough",
        validation_alias="TRANSFORM_MODE",
    )
    rules_path: str = Field(
        default="config/rules.yaml",
        validation_alias="RULES_PATH",
    )
    db_path: str = Field(
        default="data/middleware.db",
        validation_alias="DB_PATH",
    )
    panel_api_base_url: str = Field(
        default="",
        validation_alias="PANEL_API_BASE_URL",
    )
    panel_web_base_path: str = Field(
        default="",
        validation_alias="PANEL_WEB_BASE_PATH",
    )
    panel_api_token: str = Field(
        default="",
        validation_alias="PANEL_API_TOKEN",
    )
    panel_verify_ssl: bool | None = Field(
        default=None,
        validation_alias="PANEL_VERIFY_SSL",
    )
    panel_sync_on_startup: bool = Field(
        default=True,
        validation_alias="PANEL_SYNC_ON_STARTUP",
    )
    panel_sync_at: str = Field(
        default="04:00",
        validation_alias="PANEL_SYNC_AT",
    )
    panel_sync_timezone: str = Field(
        default="",
        validation_alias="PANEL_SYNC_TZ",
    )

    def resolved_panel_base_url(self) -> str:
        return (self.panel_api_base_url or self.upstream_base_url).rstrip("/")

    def resolved_panel_verify_ssl(self) -> bool:
        if self.panel_verify_ssl is not None:
            return self.panel_verify_ssl
        return self.upstream_verify_ssl


settings = Settings()