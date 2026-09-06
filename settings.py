import os
from dataclasses import dataclass


def load_environment() -> None:
    """Load .env when python-dotenv is installed; real environment variables still work without it."""
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv()


load_environment()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not configured")
    return value


@dataclass(frozen=True)
class BrokerSettings:
    host: str
    port: int
    tube: str


@dataclass(frozen=True)
class StorageSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str
    auto_create_bucket: bool


def get_broker_settings() -> BrokerSettings:
    return BrokerSettings(
        host=os.getenv("BEANSTALKD_HOST", "127.0.0.1"),
        port=env_int("BEANSTALKD_PORT", 11300),
        tube=os.getenv("BEANSTALKD_TUBE", "raw-data"),
    )


def get_storage_settings() -> StorageSettings:
    return StorageSettings(
        endpoint=required_env("S3_ENDPOINT"),
        access_key=required_env("MINIO_ACCESS_KEY"),
        secret_key=required_env("MINIO_SECRET_KEY"),
        bucket=required_env("MINIO_BUCKET_NAME"),
        region=os.getenv("S3_REGION", "us-east-1"),
        auto_create_bucket=env_bool("S3_AUTO_CREATE_BUCKET", True),
    )
