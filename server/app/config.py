from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model_primary: str = "openai/gpt-5.4-mini"
    openrouter_model_secondary: str = "deepseek/deepseek-v3.2"
    openrouter_active_model: str = "primary"
    openrouter_force_online: bool = True
    openrouter_web_max_results: int = 5
    openalex_base_url: str = "https://api.openalex.org"
    openalex_api_key: str = ""
    exa_api_key: str = ""
    database_url: str = "sqlite:///./server/collab_atlas.db"
    cache_ttl_seconds: int = 86_400
    search_cache_ttl_seconds: int = 86_400
    search_cache_version: int = 2
    snapshot_ttl_seconds: int = 43_200
    refresh_interval_seconds: int = 86_400
    openalex_mailto: str = ""
    openalex_max_work_pages: int = 8
    openalex_per_page: int = 200
    geocode_enabled: bool = True
    geocode_timeout_seconds: float = 1.5
    geocode_max_lookups_per_snapshot: int = 5
    llm_geocode_enabled: bool = True
    llm_geocode_timeout_seconds: float = 15.0
    openrouter_cheap_model: str = "google/gemma-3-12b-it"
    unplaced_online_resolution_enabled: bool = True
    unplaced_online_max_per_snapshot: int = 120
    unplaced_online_min_confidence: float = 0.72
    unplaced_online_timeout_seconds: float = 12.0

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_openrouter_model(settings: Settings) -> str:
    active = (settings.openrouter_active_model or "primary").strip().lower()
    model = settings.openrouter_model_primary if active == "primary" else settings.openrouter_model_secondary
    model = model.strip()
    if settings.openrouter_force_online and not model.endswith(":online"):
        return f"{model}:online"
    return model


def resolve_openrouter_cheap_model(settings: Settings) -> str:
    model = (settings.openrouter_cheap_model or "").strip() or (settings.openrouter_model_secondary or "").strip()
    if settings.openrouter_force_online and model and not model.endswith(":online"):
        return f"{model}:online"
    return model
