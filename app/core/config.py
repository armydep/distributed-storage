"""Centralized, environment-driven application configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "Distributed Storage API"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- PostgreSQL ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "app"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    DATABASE_URL: str | None = None

    # --- JWT / Auth ---
    JWT_SECRET_KEY: str = "dev-secret-key-change-me-please-32chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- Middleware / networking ---
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    TRUSTED_HOSTS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
    MAX_REQUEST_SIZE_BYTES: int = 5 * 1024 * 1024

    # --- Password hashing (Argon2id) ---
    PASSWORD_HASH_TIME_COST: int = 3
    PASSWORD_HASH_MEMORY_COST: int = 65536
    PASSWORD_HASH_PARALLELISM: int = 4

    @field_validator("CORS_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection URL (asyncpg driver)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        """Fail fast on insecure configuration when running in production."""
        if not self.is_production:
            return self

        errors: list[str] = []
        insecure_defaults = {"dev-secret-key-change-me-please-32chars", "", "changeme", "secret"}
        if self.JWT_SECRET_KEY in insecure_defaults or len(self.JWT_SECRET_KEY) < 32:
            errors.append(
                "JWT_SECRET_KEY must be set to a random value of at least 32 characters "
                "in production."
            )
        if self.DEBUG:
            errors.append("DEBUG must be false in production.")
        if "*" in self.TRUSTED_HOSTS:
            errors.append("TRUSTED_HOSTS must not contain '*' in production.")
        if any(origin == "*" for origin in self.CORS_ORIGINS):
            errors.append("CORS_ORIGINS must not contain '*' in production.")
        if self.POSTGRES_PASSWORD in {"postgres", "password", ""} and not self.DATABASE_URL:
            errors.append("POSTGRES_PASSWORD must not use an insecure default in production.")

        if errors:
            raise ValueError(
                "Insecure production configuration detected:\n- " + "\n- ".join(errors)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
