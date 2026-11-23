from functools import lru_cache
from re import fullmatch

from cryptography.fernet import Fernet
from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCALPAY_", hide_input_in_errors=True)

    database_url: PostgresDsn
    redis_url: RedisDsn
    admin_token: SecretStr | None = None
    webhook_encryption_key: SecretStr | None = None
    dependency_timeout_seconds: int = Field(default=2, ge=1, le=10)

    @field_validator("admin_token", mode="before")
    @classmethod
    def validate_admin_token(cls, value: object) -> object:
        if value == "":
            return None
        token = value.get_secret_value() if isinstance(value, SecretStr) else value
        if token is not None and (
            not isinstance(token, str) or fullmatch(r"[0-9a-f]{64}", token) is None
        ):
            raise ValueError("Admin token must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("webhook_encryption_key", mode="before")
    @classmethod
    def validate_webhook_key(cls, value: object) -> object:
        if value is None or value == "":
            return None
        key = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(key, str):
            raise ValueError("Webhook encryption key is invalid")
        try:
            Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("Webhook encryption key is invalid") from None
        return value

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
