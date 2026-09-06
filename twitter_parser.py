import gzip
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from settings import get_broker_settings
from validator import validate_content


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def find_tweets(obj, results: list[tuple[dict, str]], trend_context: str = "Unknown") -> None:
    """Recursively extract tweet nodes while preserving their wrapper trend context."""
    if isinstance(obj, dict):
        current_trend = obj.get("trend", trend_context)
        if not isinstance(current_trend, str) or not current_trend.strip():
            current_trend = trend_context

        legacy = obj.get("legacy")
        if (
            isinstance(legacy, dict)
            and legacy.get("full_text")
            and obj.get("rest_id")
        ):
            results.append((obj, current_trend))

        for value in obj.values():
            find_tweets(value, results, current_trend)
    elif isinstance(obj, list):
        for item in obj:
            find_tweets(item, results, trend_context)


def get_pending_batch_files(raw_dir: str | Path | None = None) -> list[Path]:
    project_dir = Path(__file__).resolve().parent
    directory = Path(raw_dir) if raw_dir is not None else project_dir / "raw_batches"
    return sorted(
        directory.glob("twitter-batch-*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_author(tweet: dict) -> str:
    user_result = (
        tweet.get("core", {})
        .get("user_results", {})
        .get("result", {})
    )
    return (
        user_result.get("core", {}).get("screen_name")
        or user_result.get("legacy", {}).get("screen_name")
        or "unknown"
    )


def _extract_hashtags(legacy: dict, text: str) -> list[str]:
    entities = legacy.get("entities", {})
    entity_tags = entities.get("hashtags", []) if isinstance(entities, dict) else []
    tags = [
        item.get("text", "").strip()
        for item in entity_tags
        if isinstance(item, dict) and item.get("text")
    ]
    if not tags:
        tags = re.findall(r"(?<!\w)#([\w_]+)", text, flags=re.UNICODE)

    unique_tags = []
    seen = set()
    for tag in tags:
        normalized = tag.casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique_tags.append(f"#{tag}")
    return unique_tags


def _parse_timestamp(created_at: str) -> tuple[int | None, str | None]:
    try:
        parsed = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        return int(parsed.timestamp()), None
    except (TypeError, ValueError):
        return None, "invalid_event_timestamp"


def normalize_tweet(
    tweet: dict,
    trend_topic: str,
    validation_mode: str = "balanced",
    parsed_at: int | None = None,
) -> dict | None:
    legacy = tweet.get("legacy", {})
    text = legacy.get("full_text", "")
    validation = validate_content(text, mode=validation_mode)
    if not validation.valid:
        return None

    tweet_id = str(tweet["rest_id"])
    author = _extract_author(tweet)
    timestamp, timestamp_flag = _parse_timestamp(legacy.get("created_at", ""))
    flags = list(validation.flags)
    if timestamp_flag:
        flags.append(timestamp_flag)

    views_data = tweet.get("views", {})
    views = _safe_int(views_data.get("count")) if isinstance(views_data, dict) else 0

    return {
        "schema_version": 1,
        "platform": "x",
        "post_id": tweet_id,
        "author_username": author,
        "caption": text,
        "metrics": {
            "likes": _safe_int(legacy.get("favorite_count")),
            "comments": _safe_int(legacy.get("reply_count")),
            "views": views,
            "shares": _safe_int(legacy.get("retweet_count")),
        },
        "timestamp": timestamp,
        "url": f"https://x.com/{author}/status/{tweet_id}",
        "parsed_at": parsed_at if parsed_at is not None else int(time.time()),
        "trend_topic": trend_topic or "Unknown",
        "hashtags": _extract_hashtags(legacy, text),
        "quality_flags": flags,
    }


def archive_batch(batch_file: Path) -> Path:
    compressed_path = batch_file.with_suffix(batch_file.suffix + ".gz")
    temporary_path = compressed_path.with_suffix(compressed_path.suffix + ".tmp")

    with batch_file.open("rb") as source, gzip.open(temporary_path, "wb") as target:
        shutil.copyfileobj(source, target)
    os.replace(temporary_path, compressed_path)
    batch_file.unlink()
    return compressed_path


def process_batch(batch_file: Path, queue_client, validation_mode: str) -> int:
    logger.info("Processing Bronze batch: %s", batch_file)
    with batch_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    extracted: list[tuple[dict, str]] = []
    find_tweets(data, extracted)

    unique_tweets: dict[str, tuple[dict, str]] = {}
    for tweet, trend in extracted:
        unique_tweets.setdefault(str(tweet["rest_id"]), (tweet, trend))

    published = 0
    filtered = 0
    parsed_at = int(time.time())
    for tweet, trend in unique_tweets.values():
        normalized = normalize_tweet(
            tweet,
            trend_topic=trend,
            validation_mode=validation_mode,
            parsed_at=parsed_at,
        )
        if normalized is None:
            filtered += 1
            continue
        queue_client.put(json.dumps(normalized, ensure_ascii=False))
        published += 1

    archived_path = archive_batch(batch_file)
    logger.info(
        "Batch complete: extracted=%d published=%d filtered=%d archive=%s",
        len(unique_tweets),
        published,
        filtered,
        archived_path,
    )
    return published


def parse_and_publish(raw_dir: str | Path | None = None) -> int:
    import greenstalk

    pending_files = get_pending_batch_files(raw_dir)
    if not pending_files:
        logger.info("No pending Bronze batch files found.")
        return 0

    broker = get_broker_settings()
    validation_mode = os.getenv("CONTENT_FILTER_MODE", "balanced").strip().lower()
    logger.info(
        "Connecting to Beanstalkd at %s:%d (tube=%s)",
        broker.host,
        broker.port,
        broker.tube,
    )

    try:
        queue_client = greenstalk.Client((broker.host, broker.port), use=broker.tube)
    except Exception as exc:
        raise RuntimeError(f"Could not connect to Beanstalkd: {exc}") from exc

    total_published = 0
    try:
        for batch_file in pending_files:
            try:
                total_published += process_batch(batch_file, queue_client, validation_mode)
            except json.JSONDecodeError:
                logger.exception("Invalid JSON retained for investigation: %s", batch_file)
            except Exception:
                logger.exception("Batch failed and was retained for retry: %s", batch_file)
                break
    finally:
        queue_client.close()

    logger.info(
        "Parser run complete: batches_discovered=%d payloads_published=%d",
        len(pending_files),
        total_published,
    )
    return total_published


if __name__ == "__main__":
    parse_and_publish()
