import os
import unittest

from app.core.features import (
    deterministic_format_review_enabled,
    direct_streaming_enabled,
)


class FeatureAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_flag = os.environ.pop(
            "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None
        )
        self.previous_streaming_flag = os.environ.pop(
            "AI_WPS_ENABLE_DIRECT_STREAMING", None
        )

    def tearDown(self) -> None:
        if self.previous_flag is None:
            os.environ.pop("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None)
        else:
            os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = (
                self.previous_flag
            )
        if self.previous_streaming_flag is None:
            os.environ.pop("AI_WPS_ENABLE_DIRECT_STREAMING", None)
        else:
            os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = (
                self.previous_streaming_flag
            )

    def test_format_review_v2_is_available_without_legacy_feature_flag(self) -> None:
        self.assertTrue(deterministic_format_review_enabled())

    def test_format_review_v2_can_be_disabled_explicitly_for_operations(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "0"

        self.assertFalse(deterministic_format_review_enabled())

    def test_format_review_v2_accepts_explicit_enabled_value(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"

        self.assertTrue(deterministic_format_review_enabled())

    def test_direct_streaming_enabled_by_default(self) -> None:
        self.assertTrue(direct_streaming_enabled())

    def test_direct_streaming_can_be_disabled_explicitly(self) -> None:
        os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = "1"
        self.assertTrue(direct_streaming_enabled())
        os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = "true"
        self.assertFalse(direct_streaming_enabled())
        os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = "0"
        self.assertFalse(direct_streaming_enabled())

    def test_config_endpoint_reports_direct_streaming_feature(self) -> None:
        import json
        from io import BytesIO
        from fastapi.testclient import TestClient
        from app.main import app
        import standalone_adapter

        def invoke_standalone():
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = "/config"
            handler.headers = {"Content-Length": "0"}
            handler.rfile = BytesIO(b"")
            handler._write = lambda status, body: captured.update(status=status, body=body)
            handler.do_GET()
            return captured

        os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = "1"
        client = TestClient(app)
        response = client.get("/config")
        self.assertEqual(response.status_code, 200)
        features = response.json().get("data", {}).get("features", {})
        self.assertIn("directStreamingEnabled", features)
        self.assertTrue(features["directStreamingEnabled"])

        sa_res = invoke_standalone()
        self.assertEqual(sa_res["status"], 200)
        sa_body = sa_res["body"]
        if isinstance(sa_body, bytes):
            sa_body = json.loads(sa_body.decode("utf-8"))
        sa_features = sa_body["data"]["features"]
        self.assertIn("directStreamingEnabled", sa_features)
        self.assertTrue(sa_features["directStreamingEnabled"])

        os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"] = "0"
        response2 = client.get("/config")
        self.assertEqual(response2.status_code, 200)
        features2 = response2.json().get("data", {}).get("features", {})
        self.assertFalse(features2["directStreamingEnabled"])

        sa_res2 = invoke_standalone()
        self.assertEqual(sa_res2["status"], 200)
        sa_body2 = sa_res2["body"]
        if isinstance(sa_body2, bytes):
            sa_body2 = json.loads(sa_body2.decode("utf-8"))
        sa_features2 = sa_body2["data"]["features"]
        self.assertFalse(sa_features2["directStreamingEnabled"])

if __name__ == "__main__":
    unittest.main()
