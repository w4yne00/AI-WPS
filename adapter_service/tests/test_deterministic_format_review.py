import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import (
    DeterministicFormatReviewService,
)
import app.api.word as word_api


class DeterministicFormatReviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_flag = os.environ.pop(
            "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = DeterministicFormatReviewService(
            staging_root=Path(self.temp_dir.name),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
        )
        self.previous_service = word_api.deterministic_format_review_service
        word_api.deterministic_format_review_service = self.service
        self.client = TestClient(app)

    def tearDown(self) -> None:
        word_api.deterministic_format_review_service = self.previous_service
        self.client.close()
        self.temp_dir.cleanup()
        if self.previous_flag is not None:
            os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = self.previous_flag

    @staticmethod
    def _payload() -> dict:
        return {
            "documentId": "format-review-contract.docx",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "正文内容",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "正文内容",
                        "styleName": "Normal",
                        "fontName": "楷体",
                        "fontSize": 14,
                        "alignment": "left",
                        "lineSpacing": 1.0,
                        "firstLineIndent": 0,
                    }
                ],
                "headings": [],
                "documentStructure": {},
            },
            "options": {"templateId": "technical-file-format-requirements"},
        }

    def test_disabled_protocol_is_rejected_without_creating_staging_data(self) -> None:
        response = self.client.post("/word/format-review/snapshots", json=self._payload())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "DETERMINISTIC_FORMAT_REVIEW_DISABLED",
        )
        self.assertFalse(list(Path(self.temp_dir.name).iterdir()))
        config = self.client.get("/config")
        self.assertFalse(config.json()["data"]["features"]["deterministicFormatReviewEnabled"])

    def test_enabled_protocol_runs_read_only_deterministic_rule(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"

        snapshot_response = self.client.post(
            "/word/format-review/snapshots", json=self._payload()
        )
        self.assertEqual(snapshot_response.status_code, 200)
        snapshot = snapshot_response.json()["data"]
        self.assertEqual(snapshot["status"], "staged")
        self.assertEqual(snapshot["paragraphCount"], 1)
        self.assertTrue(list(Path(self.temp_dir.name).iterdir()))

        job_response = self.client.post(
            "/word/format-review/jobs",
            json={
                "snapshotId": snapshot["snapshotId"],
                "snapshotToken": snapshot["snapshotToken"],
                "clientJobId": "format-contract-job-1",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        job_id = job_response.json()["data"]["jobId"]

        job = None
        for _ in range(50):
            job = self.client.get("/word/format-review/jobs/" + job_id).json()["data"]
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["summary"]["provider"], "local")
        self.assertEqual(job["result"]["summary"]["executionStatus"], "completed")
        self.assertGreaterEqual(job["result"]["summary"]["issueCount"], 1)
        self.assertNotIn("changes", job["result"])
        self.assertFalse(list(Path(self.temp_dir.name).iterdir()))

        config = self.client.get("/config")
        self.assertTrue(config.json()["data"]["features"]["deterministicFormatReviewEnabled"])


if __name__ == "__main__":
    unittest.main()
