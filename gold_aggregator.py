import argparse
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from s3_utils import create_s3_client, ensure_bucket
from settings import get_storage_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_data_timezone() -> ZoneInfo:
    name = os.getenv("DATA_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown DATA_TIMEZONE: {name}") from exc


def silver_prefix(target_date: date, platform: str = "x") -> str:
    return (
        f"silver/platform={platform}/year={target_date:%Y}/"
        f"month={target_date:%m}/day={target_date:%d}/"
    )


def iter_silver_posts(client, bucket: str, prefix: str):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            response = client.get_object(Bucket=bucket, Key=item["Key"])
            body = response["Body"]
            try:
                payload = json.loads(body.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.warning("Skipping malformed Silver object: %s", item["Key"])
                continue
            finally:
                body.close()
            if isinstance(payload, dict):
                yield payload


def _metric(post: dict, name: str) -> int:
    try:
        return int(post.get("metrics", {}).get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def build_summary(posts: list[dict], target_date: date, data_timezone: ZoneInfo) -> dict:
    trend_stats = defaultdict(lambda: {"posts": 0, "engagement": 0, "views": 0})
    hashtags = Counter()
    hourly_volume = Counter()
    authors = set()
    totals = Counter()

    for post in posts:
        author = str(post.get("author_username", "unknown"))
        if author and author != "unknown":
            authors.add(author.casefold())

        likes = _metric(post, "likes")
        comments = _metric(post, "comments")
        shares = _metric(post, "shares")
        views = _metric(post, "views")
        engagement = likes + comments + shares

        totals.update(
            posts=1,
            likes=likes,
            comments=comments,
            shares=shares,
            views=views,
            engagement=engagement,
        )

        trend = str(post.get("trend_topic") or "Unknown")
        trend_stats[trend]["posts"] += 1
        trend_stats[trend]["engagement"] += engagement
        trend_stats[trend]["views"] += views

        for hashtag in post.get("hashtags", []):
            if isinstance(hashtag, str) and hashtag.strip():
                hashtags[hashtag.casefold()] += 1

        timestamp = post.get("timestamp")
        if timestamp is not None:
            try:
                event_time = datetime.fromtimestamp(int(timestamp), tz=data_timezone)
                hourly_volume[f"{event_time:%H}:00"] += 1
            except (TypeError, ValueError, OSError):
                pass

    narratives = [
        {"trend_topic": topic, **values}
        for topic, values in trend_stats.items()
    ]
    narratives.sort(key=lambda item: (-item["posts"], -item["engagement"], item["trend_topic"].casefold()))

    return {
        "schema_version": 1,
        "date": target_date.isoformat(),
        "timezone": str(data_timezone),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "posts": totals["posts"],
            "unique_authors": len(authors),
            "likes": totals["likes"],
            "comments": totals["comments"],
            "shares": totals["shares"],
            "views": totals["views"],
            "engagement": totals["engagement"],
        },
        "narratives": narratives,
        "top_hashtags": [
            {"hashtag": hashtag, "posts": count}
            for hashtag, count in hashtags.most_common(20)
        ],
        "hourly_volume": [
            {"hour": f"{hour:02d}:00", "posts": hourly_volume[f"{hour:02d}:00"]}
            for hour in range(24)
        ],
    }


def aggregate_date(target_date: date) -> str:
    storage = get_storage_settings()
    client = create_s3_client(storage)
    ensure_bucket(client, storage)

    prefix = silver_prefix(target_date)
    posts = list(iter_silver_posts(client, storage.bucket, prefix))
    summary = build_summary(posts, target_date, get_data_timezone())
    object_key = f"gold/narrative-trends/date={target_date.isoformat()}/summary.json"
    client.put_object(
        Bucket=storage.bucket,
        Key=object_key,
        Body=json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(
        "Gold summary stored at s3://%s/%s (%d posts)",
        storage.bucket,
        object_key,
        len(posts),
    )
    return object_key


def parse_target_date(value: str | None) -> date:
    if not value:
        return datetime.now(get_data_timezone()).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format") from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a daily Gold narrative summary")
    parser.add_argument("--date", help="Data date in YYYY-MM-DD format; defaults to today")
    arguments = parser.parse_args()
    aggregate_date(parse_target_date(arguments.date))
