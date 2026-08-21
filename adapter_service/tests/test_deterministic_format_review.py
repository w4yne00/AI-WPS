import os
import importlib.util
import json
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path

from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import (
    DeterministicFormatReviewService,
)

HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app
    import app.api.word as word_api


class RecordingFormatReviewer:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.review_calls = []

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "review-model",
            "maxOutputTokens": 4096,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-1",
            "modelConfigurationName": "格式审查主配置",
            "modelConfiguration": {"configVersion": 7, "taskType": "word.format_review"},
        }

    def review(self, request, trace_id="", task_auth=None):
        self.review_calls.append({"traceId": trace_id, "taskAuth": task_auth})
        return {
            "summary": {
                "scope": request.selection_mode,
                "templateId": "technical-file-format-requirements",
                "provider": "local",
                "semanticStatus": "not_needed",
            },
            "issues": [],
        }


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
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

    def test_old_synchronous_format_review_endpoint_is_retired(self) -> None:
        response = self.client.post("/word/format-review", json=self._payload())

        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "WORD_FORMAT_REVIEW_SYNC_RETIRED",
        )
        self.assertIn("后台格式审查任务", response.json()["message"])
        self.assertFalse(list(Path(self.temp_dir.name).iterdir()))

    def test_enabled_protocol_rejects_the_old_snapshot_shape(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"

        response = self.client.post(
            "/word/format-review/snapshots", json=self._payload()
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_VERSION_UNSUPPORTED",
        )
        self.assertFalse(list(Path(self.temp_dir.name).iterdir()))

    def _start_v2_job(self, service, job_id: str):
        identity = {
            "documentIdSha256": "document-fingerprint",
            "hostDocumentId": "host-document-1",
        }
        session = service.create_snapshot(
            {
                "documentId": "format-review-contract.docx",
                "selectionMode": "document",
                "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                "formatFactSchemaVersion": "format_snapshot.v2",
                "documentIdentity": identity,
                "editSequence": "1",
            }
        )
        blocks = service._normalize_format_blocks(
            [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "paragraph",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "text": "正文内容",
                    "format": {
                        "styleName": "Normal",
                        "fontName": "楷体",
                        "fontSize": 14,
                        "alignment": "left",
                        "lineSpacing": 1.0,
                        "firstLineIndent": 0,
                        "dataStatus": "verified",
                    },
                }
            ]
        )
        metrics = service._format_metrics(blocks)
        service.upload_batch(
            session["snapshotId"],
            0,
            {
                "uploadToken": session["uploadToken"],
                "batchId": "format-batch-0",
                "blocks": blocks,
                "editSequence": "1",
                **{key: metrics[key] for key in (
                    "characterCount", "contentSha256", "structureSha256", "formatSha256"
                )},
            },
        )
        verification = {
            "batchCount": 1,
            "blockCount": 1,
            "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "coverage": metrics["coverage"],
            "documentIdentity": identity,
            "editSequence": "1",
        }
        committed = service.commit_snapshot(
            session["snapshotId"],
            {
                "uploadToken": session["uploadToken"],
                **{key: verification[key] for key in (
                    "batchCount", "blockCount", "reviewCharacterCount",
                    "contentSha256", "structureSha256", "formatSha256", "coverage"
                )},
                "verification": verification,
            },
        )
        return service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": job_id,
            },
            "format-auth-freeze-trace",
        )

    def test_job_freezes_format_review_auth_at_submission(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"
        reviewer = RecordingFormatReviewer()
        self.service = DeterministicFormatReviewService(
            staging_root=Path(self.temp_dir.name),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
            reviewer=reviewer,
        )
        word_api.deterministic_format_review_service = self.service

        job_response = self._start_v2_job(self.service, "format-auth-freeze-job")
        self.assertIn(job_response["status"], {"queued", "running", "completed"})

        for _ in range(50):
            job = self.service.get_job("format-auth-freeze-job")
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)

        self.assertEqual(job["status"], "completed")
        self.assertEqual(reviewer.snapshot_calls, 1)
        self.assertEqual(len(reviewer.review_calls), 1)
        self.assertEqual(
            reviewer.review_calls[0]["taskAuth"]["modelConfigurationId"],
            "config-format-1",
        )
        report = self.service.get_report("format-auth-freeze-job")
        self.assertEqual(report["summary"]["modelConfigurationName"], "格式审查主配置")
        self.assertEqual(report["summary"]["modelConfigurationId"], "config-format-1")
        self.assertEqual(report["summary"]["modelConfigurationVersion"], 7)
        self.assertEqual(report["summary"]["accessMethod"], "direct_model")
        self.assertNotIn("apiKey", report["summary"])


class StandaloneFormatReviewRetirementTests(unittest.TestCase):
    def test_standalone_sync_format_review_returns_retirement_envelope(self) -> None:
        import standalone_adapter

        captured = {}
        raw = json.dumps({"content": {"plainText": "旧同步正文"}}).encode("utf-8")
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/word/format-review"
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)

        handler.do_POST()

        self.assertEqual(captured["status"], 410)
        self.assertEqual(
            captured["body"]["errors"][0]["code"],
            "WORD_FORMAT_REVIEW_SYNC_RETIRED",
        )
        self.assertIn("后台格式审查任务", captured["body"]["message"])

    def test_standalone_v2_issue_report_and_lifecycle_routes_use_the_v2_service(self) -> None:
        import standalone_adapter

        class FakeService:
            def __init__(self):
                self.calls = []

            def list_issues(self, job_id, **kwargs):
                self.calls.append(("list_issues", job_id, kwargs))
                return {"issues": [], "nextCursor": ""}

            def get_report(self, job_id):
                self.calls.append(("get_report", job_id))
                return {"schemaVersion": "word.format_review.report.v2", "jobId": job_id}

            def update_issue(self, job_id, issue_id, **kwargs):
                self.calls.append(("update_issue", job_id, issue_id, kwargs))
                return {"issueId": issue_id, "status": kwargs.get("status")}

            def delete_report(self, job_id):
                self.calls.append(("delete_report", job_id))
                return {"jobId": job_id, "deleted": True}

            def cancel_job(self, job_id):
                self.calls.append(("cancel_job", job_id))
                return {"jobId": job_id, "status": "cancelled"}

        def invoke(method, path, body=None):
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            raw = json.dumps(body or {}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, payload: captured.update(status=status, body=payload)
            handler._write_bytes = lambda status, content, headers: captured.update(
                status=status, body=content, headers=headers
            )
            getattr(handler, method)()
            return captured

        fake_service = FakeService()
        previous_service = standalone_adapter.DETERMINISTIC_FORMAT_REVIEW_SERVICE
        standalone_adapter.DETERMINISTIC_FORMAT_REVIEW_SERVICE = fake_service
        try:
            issues = invoke(
                "do_GET",
                "/word/format-review/jobs/job-1/issues?pageSize=10&status=open",
            )
            report = invoke("do_GET", "/word/format-review/jobs/job-1/report?format=summary")
            updated = invoke(
                "do_PATCH",
                "/word/format-review/jobs/job-1/issues/issue-1",
                {"status": "processed"},
            )
            deleted_report = invoke("do_DELETE", "/word/format-review/jobs/job-1/report")
            cancelled = invoke("do_DELETE", "/word/format-review/jobs/job-1")
        finally:
            standalone_adapter.DETERMINISTIC_FORMAT_REVIEW_SERVICE = previous_service

        self.assertEqual(issues["status"], 200)
        self.assertEqual(report["status"], 200)
        self.assertEqual(updated["status"], 200)
        self.assertEqual(deleted_report["status"], 200)
        self.assertEqual(cancelled["status"], 200)
        self.assertEqual(
            [call[0] for call in fake_service.calls],
            ["list_issues", "get_report", "update_issue", "delete_report", "cancel_job"],
        )


if __name__ == "__main__":
    unittest.main()
