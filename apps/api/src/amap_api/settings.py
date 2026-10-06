"""Runtime configuration from environment variables (and the repo-root ``.env``)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Path or http(s) URL of graph.geojson (pipeline output, served as an asset).
    graph_source: str = Field(default="data/out/graph.geojson")
    # Comma-separated list, e.g. "http://localhost:3000,https://x.vercel.app".
    cors_origins: str = "http://localhost:3000"
    asset_base_url: str = ""
    # Development only: serve data/out (panoramas, buildings) at /assets.
    # Production assets live on Cloudflare Pages (ADR-0004); leave empty there.
    asset_dir: str = ""
    weather_ttl_s: int = 600
    groq_api_key: str = ""
    gemini_api_key: str = ""
    # Transaction-pooler URL of the least-privilege `amap_api` role
    # (`amap db api-role`); empty = run without a database.
    amap_api_database_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
