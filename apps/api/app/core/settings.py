from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCALPAY_", hide_input_in_errors=True)

    database_url: PostgresDsn
    redis_url: RedisDsn
    dependency_timeout_seconds: int = Field(default=2, ge=1, le=10)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+psycopg" or len(value.hosts()) != 1:
            raise ValueError("Use a single-host postgresql+psycopg URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: RedisDsn) -> RedisDsn:
        database = (value.path or "/0").removeprefix("/")
        if not database.isascii() or not database.isdecimal():
            raise ValueError("Redis database must be a nonnegative integer")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
