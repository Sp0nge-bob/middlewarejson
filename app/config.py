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
    db_path: str = Field(
        default="data/middleware.db",
        validation_alias="DB_PATH",
    )

    def resolved_agent_json_path(self) -> str:
        explicit = self.agent_json_path.strip()
        if explicit:
            return explicit.rstrip("/")
        return self.upstream_json_path.rstrip("/")

    def resolved_upstream_base_url(self) -> str:
        return self.upstream_base_url.strip().rstrip("/")


settings = Settings()
