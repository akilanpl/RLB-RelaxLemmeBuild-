"""Application configuration management using Pydantic Settings."""

import os
from functools import lru_cache
from typing import List, Optional, Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized environment configuration.
    Secrets and sensitive URLs are strictly loaded from environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=os.environ.get("RLB_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    PROJECT_NAME: str = "Cloud AI Software Engineering Workspace"
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = Field(default="development", description="Runtime environment: development | staging | production")
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
    DATABASE_SSL_CA_FILE: Optional[str] = None
    DATABASE_SSL_CA_PEM: Optional[str] = None
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
    SUPABASE_QUEUE_NAME: str = "task_execution"
    SUPABASE_STORAGE_BUCKET: str = "workspace-artifacts"
    DAYTONA_API_URL: Optional[str] = None
    DAYTONA_API_KEY: Optional[str] = None
    DAYTONA_SANDBOX_IMAGE: Optional[str] = None
    DAYTONA_TARGET: Optional[str] = None
    SANDBOX_ALLOWED_DOMAINS: List[str] = Field(default_factory=lambda: ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"])
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
    RUN_EMBEDDED_WORKER: Optional[bool] = None
    WORKER_POLL_SECONDS: float = Field(default=1.0, gt=0)

    MAX_WORKFLOW_STAGE_SECONDS: int = Field(default=1800, ge=1, le=7200)
    ARTIFACT_RETENTION_DAYS: int = Field(default=7, ge=1)
    ARTIFACT_CLEANUP_INTERVAL_SECONDS: int = Field(default=3600, ge=60)

    MAX_REPAIR_ATTEMPTS: int = Field(default=3, ge=0, le=20)
    MAX_TASKS_PER_USER_PER_HOUR: int = Field(default=30, ge=1)

    MAX_AI_CALLS_PER_TASK: int = Field(default=20, ge=1)
    MAX_AI_OUTPUT_TOKENS: int = Field(default=8192, ge=1)

    def __repr__(self) -> str:
        return (
            f"Settings(PROJECT_NAME={self.PROJECT_NAME!r}, "
            f"ENVIRONMENT={self.ENVIRONMENT!r}, DEBUG={self.DEBUG!r})"
        )

    @model_validator(mode="after")
    def require_production_database(self) -> "Settings":
        if self.ENVIRONMENT in {"staging", "production"} and not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is required for staging and production.")
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
