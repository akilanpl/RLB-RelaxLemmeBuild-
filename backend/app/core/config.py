"""Application configuration management using Pydantic Settings."""

from functools import lru_cache
from typing import List, Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized environment configuration.
    Secrets and sensitive URLs are strictly loaded from environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Cloud AI Software Engineering Workspace"
    ENVIRONMENT: str = Field(default="development", description="Runtime environment: development | staging | production")
    DEBUG: bool = Field(default=False)
    API_V1_PREFIX: str = "/api/v1"

    # CORS configuration
    BACKEND_CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed origins for frontend CORS",
    )

    # Database & Supabase connection
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="PostgreSQL / Supabase connection string (e.g. postgresql+asyncpg://user:pass@host:5432/db)",
    )
    SUPABASE_URL: Optional[str] = Field(
        default=None,
        description="Supabase API project URL",
    )
    SUPABASE_ANON_KEY: Optional[str] = Field(
        default=None,
        description="Supabase anonymous client public key",
    )
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(
        default=None,
        description="Supabase service role secret key (backend only)",
    )
    SUPABASE_QUEUE_NAME: str = "task-execution"
    SUPABASE_STORAGE_BUCKET: str = "workspace-artifacts"
    DAYTONA_API_URL: Optional[str] = None
    DAYTONA_API_KEY: Optional[str] = None
    SUPABASE_JWT_ISSUER: Optional[str] = Field(
        default=None,
        description="JWT issuer; defaults to the Supabase project's /auth/v1 issuer",
    )
    SUPABASE_JWT_AUDIENCE: str = Field(
        default="authenticated",
        description="JWT audience accepted for API access",
    )
    SUPABASE_JWKS_CACHE_TTL_SECONDS: int = Field(
        default=3600,
        ge=0,
        description="How long the Supabase JWKS document is cached",
    )
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Backend-only Groq API key")
    GROQ_MODEL: Optional[str] = Field(default=None, description="Configured Groq Planner model")

    # Encryption secret for provider credentials (AES-256)
    CREDENTIAL_ENCRYPTION_KEY: Optional[str] = Field(
        default=None,
        description="32-byte base64 encoded master key for encrypting provider credentials",
    )
    MAX_AI_CALLS_PER_TASK: int = Field(default=20, ge=1)
    MAX_AI_OUTPUT_TOKENS: int = Field(default=8192, ge=1)

    def __repr__(self) -> str:
        return (
            f"Settings(PROJECT_NAME={self.PROJECT_NAME!r}, "
            f"ENVIRONMENT={self.ENVIRONMENT!r}, DEBUG={self.DEBUG!r})"
        )

    @model_validator(mode="after")
    def require_production_database(self) -> "Settings":
        if self.ENVIRONMENT == "production" and not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is required when ENVIRONMENT=production.")
        if self.SUPABASE_URL:
            url = self.SUPABASE_URL.strip().rstrip("/")
            for suffix in ("/rest/v1", "/auth/v1", "/storage/v1"):
                if url.endswith(suffix):
                    url = url[: -len(suffix)]
            self.SUPABASE_URL = url
        return self


@lru_cache
def get_settings() -> Settings:
    """Singleton getter for cached application settings."""
    return Settings()
