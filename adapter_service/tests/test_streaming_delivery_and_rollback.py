import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.features import direct_streaming_enabled
from app.core.models import WordDocumentRequest
from app.services.direct_services import DirectServiceStore
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.writing_jobs import SmartWriteJobStore


def make_request(
    client_job_id,
    document_session_id="",
    document_display_name="",
    host="wps",
):
    payload = {
        "documentId": "writing-test.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": client_job_id,
        "documentSessionId": document_session_id,
        "documentDisplayName": document_display_name,
        "host": host,
        "content": {
            "plainText": "待处理文本。",
            "paragraphs": [],
            "headings": [],
        },
        "options": {},
    }
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class FakeWorker:
    def __init__(self, streaming_capability=None):
        self.streaming_capability = streaming_capability or {
            "status": "validated",
            "serviceId": "direct_svc_test",
            "serviceRevision": 1,
            "serviceBaseUrl": "https://api.openai.com/v1",
            "apiKeyFingerprint": "sha256:test",
            "modelName": "gpt-4o",
            "testedAt": "2026-09-20T00:00:00Z",
        }
        self.calls = []

    def snapshot_task_auth(self):
        return {
            "configurationId": "test-config",
            "streamingCapability": self.streaming_capability,
        }

    def smart_write(self, request, **kwargs):
        self.calls.append((request, kwargs))
        return {
            "originalText": request.content.plain_text,
            "rewrittenText": "处理完成。",
            "rewriteMode": "rewrite",
        }


class StreamingDeliveryAndRollbackTests(unittest.TestCase):
    def test_feature_flag_enabled_by_default_and_explicit_zero_rolls_back(self):
        """Streaming is on by default, while explicit zero keeps the rollback path."""
        with patch.dict(os.environ, {}, clear=True):
            if "AI_WPS_ENABLE_DIRECT_STREAMING" in os.environ:
                del os.environ["AI_WPS_ENABLE_DIRECT_STREAMING"]
            self.assertTrue(direct_streaming_enabled())

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "0"}):
            self.assertFalse(direct_streaming_enabled())

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "false"}):
            self.assertFalse(direct_streaming_enabled())

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            self.assertTrue(direct_streaming_enabled())

    def test_flag_disabled_forces_blocking_and_queued_only_cancellation(self):
        """When feature flag is disabled, new writing jobs use blocking execution without running cancellation."""
        coordinator = LongTaskCoordinator()
        worker = FakeWorker()
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)
        request = make_request("client-job-flag-off-123")

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "0"}):
            job = store.start(request, "trace-flag-off")
            self.assertIsNotNone(job)
            self.assertFalse(job["streamingEnabled"])
            internal_job = coordinator._jobs.get(("word.smart_write", job["jobId"]))
            self.assertIsNotNone(internal_job)
            # allow_running_cancel must be False when feature flag is off
            self.assertFalse(internal_job["_allowRunningCancel"])

    def test_running_job_preserves_submission_snapshot_if_flag_toggled_mid_run(self):
        """A running job submitted with streaming keeps its cancellation capability even if flag is disabled mid-run."""
        coordinator = LongTaskCoordinator()
        worker = FakeWorker()
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)
        request = make_request("client-job-snapshot-test-123")

        # Start with streaming enabled
        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            job = store.start(request, "trace-snapshot-test")
            self.assertTrue(job["streamingEnabled"])
            internal_job = coordinator._jobs.get(("word.smart_write", job["jobId"]))
            self.assertIsNotNone(internal_job)
            self.assertTrue(internal_job["_allowRunningCancel"])
            self.assertTrue(
                internal_job["_snapshot"]["taskAuth"]["directStreamingEnabled"]
            )

        # Now flag is toggled to 0
        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "0"}):
            # The existing slot still retains _allowRunningCancel = True
            internal_job_after = coordinator._jobs.get(("word.smart_write", job["jobId"]))
            self.assertTrue(internal_job_after["_allowRunningCancel"])

    def test_older_config_without_streaming_capability_loads_cleanly(self):
        """Configs without streaming capability records load cleanly and default safely."""
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "adapter.json"
            legacy_config = {
                "schemaVersion": "provider.direct_service.v1",
                "directServices": {
                    "direct_svc_test": {
                        "id": "direct_svc_test",
                        "name": "Test Service",
                        "serviceBaseUrl": "https://api.openai.com/v1",
                        "apiKeyFingerprint": "sha256:abcd1234",
                        "defaultModel": "gpt-4o",
                        "revision": 1,
                        "updatedAt": "2026-09-10T12:00:00Z",
                    }
                },
                "taskModelSelections": {
                    "word.smart_write": {
                        "taskType": "word.smart_write",
                        "serviceId": "direct_svc_test",
                        "modelName": "gpt-4o",
                        "updatedAt": "2026-09-10T12:00:00Z",
                    }
                },
            }
            config_path.write_text(json.dumps(legacy_config), encoding="utf-8")

            store = DirectServiceStore(config_path)
            selections = store.list_task_model_selections()
            smart_write_sel = selections["selections"]["word.smart_write"]

            # Defaults safely to not_checked status when no probe has been executed
            self.assertEqual(smart_write_sel["streamingCapability"]["status"], "not_checked")

            # Updating another property doesn't corrupt older structures
            store.update_task_model_selection("word.smart_write", service_id="direct_svc_test", model_name="gpt-4o-mini")
            updated = store.get_task_model_selection("word.smart_write")
            self.assertEqual(updated["modelName"], "gpt-4o-mini")
            self.assertEqual(updated["streamingCapability"]["status"], "not_checked")

    def test_assembled_delivery_tree_direct_text_stream_importable(self):
        """direct_text_stream can be imported and executed standalone without extraneous dependencies."""
        from app.services.direct_text_stream import StreamingThinkFilter, read_direct_text_stream

        filter_inst = StreamingThinkFilter()
        self.assertIsNotNone(filter_inst)
        self.assertEqual(filter_inst.feed("hello world"), "hello world")
        self.assertEqual(filter_inst.feed("<think>ignore</think>ok"), "ok")

    def test_wps_addon_prototype_contains_no_streaming_implementation(self):
        """The legacy wps-addon prototype contains NO streaming implementation or /events endpoints."""
        repo_root = Path(__file__).resolve().parents[2]
        wps_addon_src = repo_root / "wps-addon" / "src"
        if not wps_addon_src.exists():
            self.skipTest("wps-addon directory not present")

        prohibited_keywords = [
            "direct_text_stream",
            "/events?afterSequence",
            "streamingCapability",
            "previewSnapshot",
            "pollWritingJobEvents",
        ]

        found = []
        for p in wps_addon_src.rglob("*"):
            if p.is_file() and p.suffix in (".js", ".ts", ".html", ".vue", ".json"):
                text = p.read_text(encoding="utf-8", errors="ignore")
                for kw in prohibited_keywords:
                    if kw in text:
                        found.append(f"{p.relative_to(repo_root)}: {kw}")

        self.assertEqual(found, [], f"wps-addon must not contain streaming implementations: {found}")
