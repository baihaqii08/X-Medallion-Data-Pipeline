import unittest

from validator import is_content_valid, validate_content


class ValidatorTests(unittest.TestCase):
    def test_balanced_mode_retains_legitimate_sensitive_reporting(self):
        result = validate_content(
            "Pemerintah menindak judi online yang sedang viral di Indonesia.",
            mode="balanced",
        )
        self.assertTrue(result.valid)
        self.assertIn("gambling_reference", result.flags)
        self.assertIn("ambiguous_spam_reference", result.flags)

    def test_balanced_mode_blocks_strong_promotion(self):
        result = validate_content("Daftar slot gacor sekarang, pasti maxwin!", mode="balanced")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "gambling_promotion")

    def test_strict_mode_blocks_any_sensitive_category(self):
        self.assertFalse(is_content_valid("Berita penindakan judi online", mode="strict"))

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_content("valid text", mode="unsupported")


if __name__ == "__main__":
    unittest.main()
