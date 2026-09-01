import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from twitter_parser import (
    archive_batch,
    find_tweets,
    get_pending_batch_files,
    normalize_tweet,
    parse_and_publish,
)


def sample_tweet():
    return {
        "rest_id": "12345",
        "legacy": {
            "full_text": "Karhutla sedang viral #Karhutla #Indonesia",
            "created_at": "Mon Aug 31 17:00:00 +0000 2026",
            "favorite_count": 10,
            "reply_count": 2,
            "retweet_count": 3,
            "entities": {
                "hashtags": [{"text": "Karhutla"}, {"text": "Indonesia"}]
            },
        },
        "views": {"count": "100"},
        "core": {
            "user_results": {"result": {"core": {"screen_name": "example_user"}}}
        },
    }


class ParserTests(unittest.TestCase):
    def test_find_tweets_keeps_wrapper_trend_context(self):
        results = []
        find_tweets({"trend": "Karhutla", "raw_json": {"item": sample_tweet()}}, results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "Karhutla")

    def test_normalize_tweet_preserves_event_time_and_quality_flags(self):
        normalized = normalize_tweet(sample_tweet(), "Karhutla", parsed_at=99)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["post_id"], "12345")
        self.assertEqual(normalized["author_username"], "example_user")
        self.assertEqual(normalized["timestamp"], 1788195600)
        self.assertEqual(normalized["hashtags"], ["#Karhutla", "#Indonesia"])
        self.assertIn("ambiguous_spam_reference", normalized["quality_flags"])

    def test_pending_batches_are_oldest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_file = root / "twitter-batch-1.json"
            new_file = root / "twitter-batch-2.json"
            old_file.write_text("[]", encoding="utf-8")
            new_file.write_text("[]", encoding="utf-8")
            self.assertEqual(get_pending_batch_files(root), [old_file, new_file])

    def test_archive_batch_is_lossless(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "twitter-batch-1.json"
            payload = {"hello": "Indonesia"}
            source.write_text(json.dumps(payload), encoding="utf-8")
            archive = archive_batch(source)
            self.assertFalse(source.exists())
            with gzip.open(archive, "rt", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), payload)

    def test_parse_and_publish_processes_every_pending_batch(self):
        class FakeQueue:
            def __init__(self):
                self.payloads = []
                self.closed = False

            def put(self, payload):
                self.payloads.append(json.loads(payload))

            def close(self):
                self.closed = True

        queue = FakeQueue()
        fake_greenstalk = SimpleNamespace(Client=lambda *args, **kwargs: queue)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (1, 2):
                tweet = sample_tweet()
                tweet["rest_id"] = str(index)
                batch = [{"trend": "Karhutla", "raw_json": {"tweet": tweet}}]
                (root / f"twitter-batch-{index}.json").write_text(
                    json.dumps(batch),
                    encoding="utf-8",
                )

            with patch.dict(sys.modules, {"greenstalk": fake_greenstalk}):
                published = parse_and_publish(root)

            self.assertEqual(published, 2)
            self.assertEqual({item["post_id"] for item in queue.payloads}, {"1", "2"})
            self.assertTrue(queue.closed)
            self.assertEqual(list(root.glob("*.json")), [])
            self.assertEqual(len(list(root.glob("*.json.gz"))), 2)


if __name__ == "__main__":
    unittest.main()
