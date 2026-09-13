import secrets

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration. Every value is overridable via env vars,
    so nothing about a specific battle/character/gift ever needs to be
    hardcoded here -- this file only holds infra-level defaults."""

    app_name: str = "TikTok Battle Arena"
    database_url: str = "postgresql+asyncpg://battle:battle@postgres:5432/battle"
    redis_url: str = "redis://redis:6379/0"

    max_players_default: int = 500
    default_xp_max: int = 100_000

    cors_origins: list[str] = ["*"]

    upload_dir: str = "/app/uploads"

    # Admin panel auth. Change these via env vars in any real deployment --
    # the defaults exist only so a fresh checkout boots without extra setup.
    admin_username: str = "admin"
    admin_password: str = "changeme"
    # Signs admin session tokens. If left unset, a random key is generated
    # per process start, which means every running backend instance issues
    # tokens only it can verify and existing sessions are invalidated on
    # restart -- fine for a single container, but set BATTLE_SECRET_KEY
    # explicitly for multi-instance or persistent-session deployments.
    secret_key: str = secrets.token_hex(32)

    # Image generation for the sprite studio (Admin -> Gerar sprites). The key
    # lives only in the environment: it is never written to the database and
    # never sent back to the browser. Leave it unset and the studio simply
    # reports itself as not configured -- everything else keeps working.
    image_api_key: str = ""
    image_api_base: str = "https://api.openai.com/v1"
    image_model: str = "gpt-image-1"
    # Generating a handful of poses takes a while; each call gets this long.
    image_timeout_seconds: float = 180.0

    @property
    def migration_database_url(self) -> str:
        """Alembic runs synchronously, so the async driver is stripped off
        whatever the app itself connects with -- BATTLE_DATABASE_URL stays
        the single source of truth for where the data lives."""
        return self.database_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")

    class Config:
        env_prefix = "BATTLE_"


settings = Settings()
