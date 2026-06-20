from app.config import Settings
from app.services.panel_api import PANEL_API_BASE_URL_KEY, resolve_panel_base_url


def test_resolve_panel_base_url_prefers_env() -> None:
    settings = Settings(
        panel_api_base_url="https://env.example.com",
        upstream_base_url="https://fallback.example.com",
    )
    assert (
        resolve_panel_base_url(settings, "https://db.example.com")
        == "https://env.example.com"
    )


def test_resolve_panel_base_url_uses_repository() -> None:
    settings = Settings(upstream_base_url="https://fallback.example.com")
    assert (
        resolve_panel_base_url(settings, "https://db.example.com")
        == "https://db.example.com"
    )


def test_panel_api_base_url_key_constant() -> None:
    assert PANEL_API_BASE_URL_KEY == "panel_api_base_url"