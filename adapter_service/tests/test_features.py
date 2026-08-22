import os
import unittest

from app.core.features import deterministic_format_review_enabled


class FeatureAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_flag = os.environ.pop(
            "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None
        )

    def tearDown(self) -> None:
        if self.previous_flag is None:
            os.environ.pop("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None)
        else:
            os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = (
                self.previous_flag
            )

    def test_format_review_v2_is_available_without_legacy_feature_flag(self) -> None:
        self.assertTrue(deterministic_format_review_enabled())

    def test_format_review_v2_can_be_disabled_explicitly_for_operations(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "0"

        self.assertFalse(deterministic_format_review_enabled())

    def test_format_review_v2_accepts_explicit_enabled_value(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"

        self.assertTrue(deterministic_format_review_enabled())


if __name__ == "__main__":
    unittest.main()
