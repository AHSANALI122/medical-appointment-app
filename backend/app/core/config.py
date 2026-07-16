from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://medbook:medbook@localhost:5432/medbook"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    encryption_key: str = ""

    gemini_api_key: str = ""
    openai_api_key: str = ""
    llm_primary: str = "gemini"
    llm_fallback: str = "openai"
    llm_daily_token_budget: int = 200_000

    langsmith_api_key: str = ""
    langsmith_project: str = "medbook"
    sentry_dsn: str = ""

    cloudinary_url: str = ""
    resend_api_key: str = ""
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""
    sms_gateway_key: str = ""

    frontend_origin: str = "http://localhost:3000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
