from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration. Every value is overridable via env vars,
    so nothing about a specific battle/character/gift ever needs to be
    hardcoded here -- this file only holds infra-level defaults."""

    app_name: str = "TikTok Battle Arena"
    database_url: str = "postgresql+asyncpg://battle:battle@postgres:5432/battle"
    sync_database_url: str = "postgresql+psycopg2://battle:battle@postgres:5432/battle"
    redis_url: str = "redis://redis:6379/0"

    max_players_default: int = 500
    default_xp_max: int = 100_000

    cors_origins: list[str] = ["*"]

    upload_dir: str = "/app/uploads"

    class Config:
        env_prefix = "BATTLE_"


settings = Settings()
