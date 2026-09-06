import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from gold_aggregator import build_summary, silver_prefix
from minio_worker import build_object_key


class StorageLayerTests(unittest.TestCase):
    def test_silver_key_uses_event_date_and_immutable_post_id(self):
        timestamp = int(datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc).timestamp())
        payload = {
            "platform": "x",
            "post_id": "12345",
            "author_username": "old_name",
            "timestamp": timestamp,
        }
        first_key = build_object_key(payload, timezone_name="Asia/Jakarta")
        payload["author_username"] = "new_name"
        second_key = build_object_key(payload, timezone_name="Asia/Jakarta")
        self.assertEqual(
            first_key,
            "silver/platform=x/year=2026/month=09/day=01/12345.json",
        )
        self.assertEqual(second_key, first_key)

    def test_missing_event_timestamp_gets_stable_unknown_partition(self):
        self.assertEqual(
            build_object_key({"platform": "x", "post_id": "abc", "timestamp": None}),
            "silver/platform=x/event_date=unknown/abc.json",
        )

    def test_gold_summary_aggregates_narratives_hashtags_and_hours(self):
        jakarta = ZoneInfo("Asia/Jakarta")
        timestamp = int(datetime(2026, 9, 1, 8, 15, tzinfo=jakarta).timestamp())
        posts = [
            {
                "author_username": "user1",
                "trend_topic": "Karhutla",
                "hashtags": ["#Karhutla"],
                "timestamp": timestamp,
                "metrics": {"likes": 10, "comments": 2, "shares": 3, "views": 100},
            },
            {
                "author_username": "user2",
                "trend_topic": "Karhutla",
                "hashtags": ["#karhutla", "#Indonesia"],
                "timestamp": timestamp,
                "metrics": {"likes": 5, "comments": 1, "shares": 1, "views": 50},
            },
        ]
        summary = build_summary(posts, date(2026, 9, 1), jakarta)
        self.assertEqual(summary["totals"]["posts"], 2)
        self.assertEqual(summary["totals"]["unique_authors"], 2)
        self.assertEqual(summary["totals"]["engagement"], 22)
        self.assertEqual(summary["narratives"][0]["posts"], 2)
        self.assertEqual(
            summary["top_hashtags"][0],
            {"hashtag": "#karhutla", "posts": 2},
        )
        self.assertEqual(summary["hourly_volume"][8], {"hour": "08:00", "posts": 2})

    def test_silver_prefix_matches_partition_layout(self):
        self.assertEqual(
            silver_prefix(date(2026, 9, 1)),
            "silver/platform=x/year=2026/month=09/day=01/",
        )


if __name__ == "__main__":
    unittest.main()
