import unittest

from auto_pipeline import parse_schedule


class SchedulerTests(unittest.TestCase):
    def test_schedule_is_normalized_and_deduplicated(self):
        self.assertEqual(parse_schedule("9:30, 09:30,14:00"), {"09:30", "14:00"})

    def test_invalid_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_schedule("25:90")


if __name__ == "__main__":
    unittest.main()
