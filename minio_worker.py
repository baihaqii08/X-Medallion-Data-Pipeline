import json
import logging
import os
import re
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from s3_utils import create_s3_client, ensure_bucket
from settings import get_broker_settings, get_storage_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _data_timezone(name: str | None = None) -> ZoneInfo:
    timezone_name = name or os.getenv("DATA_TIMEZONE", "UTC")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown DATA_TIMEZONE: {timezone_name}") from exc


def _safe_partition_value(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-")
    return normalized or "unknown"


def build_object_key(data: dict, timezone_name: str | None = None) -> str:
    """Build a stable Silver key from immutable identity and event time."""
    platform = _safe_partition_value(str(data.get("platform", "unknown")))
    post_id = data.get("post_id")
    if post_id is None or not str(post_id).strip():
        raise ValueError("Payload is missing post_id")

    encoded_post_id = quote(str(post_id).strip(), safe="")
    timestamp = data.get("timestamp")
    if timestamp is None:
        partition = "event_date=unknown"
    else:
        try:
            event_time = datetime.fromtimestamp(int(timestamp), tz=_data_timezone(timezone_name))
        except (TypeError, ValueError, OSError) as exc:
            raise ValueError(f"Invalid payload timestamp: {timestamp!r}") from exc
        partition = (
            f"year={event_time:%Y}/month={event_time:%m}/day={event_time:%d}"
        )

    return f"silver/platform={platform}/{partition}/{encoded_post_id}.json"


def validate_payload(data: dict) -> None:
    required_fields = ("platform", "post_id", "caption", "metrics")
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise ValueError(f"Payload is missing required fields: {', '.join(missing)}")
    if not isinstance(data["metrics"], dict):
        raise ValueError("Payload metrics must be an object")


def process_job(job, s3_client, bucket_name: str) -> str:
    data = json.loads(job.body)
    if not isinstance(data, dict):
        raise ValueError("Queue payload must be a JSON object")
    validate_payload(data)

    object_key = build_object_key(data)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=payload,
        ContentType="application/json",
    )
    return object_key


def start_worker() -> None:
    import greenstalk

    broker = get_broker_settings()
    storage = get_storage_settings()
    retry_delay = int(os.getenv("WORKER_RETRY_DELAY_SECONDS", "5"))

    s3_client = create_s3_client(storage)
    ensure_bucket(s3_client, storage)

    logger.info(
        "Connecting to Beanstalkd at %s:%d (tube=%s)",
        broker.host,
        broker.port,
        broker.tube,
    )
    with greenstalk.Client((broker.host, broker.port), watch=broker.tube) as client:
        logger.info("Worker online. Silver destination: s3://%s/silver/", storage.bucket)
        while True:
            job = None
            try:
                job = client.reserve()
                object_key = process_job(job, s3_client, storage.bucket)
                client.delete(job)
                logger.info("Stored s3://%s/%s", storage.bucket, object_key)
            except KeyboardInterrupt:
                logger.info("Worker stopped by user.")
                break
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error("Burying invalid queue job %s: %s", getattr(job, "id", "?"), exc)
                if job is not None:
                    client.bury(job)
            except Exception:
                logger.exception("Worker failed while processing job %s", getattr(job, "id", "?"))
                if job is not None:
                    try:
                        client.release(job, delay=retry_delay)
                    except Exception:
                        logger.exception("Could not release failed queue job %s", job.id)
                time.sleep(retry_delay)


if __name__ == "__main__":
    start_worker()
