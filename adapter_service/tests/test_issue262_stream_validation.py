import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from app.core.config import AppSettings
from app.services.direct_services import DirectServiceStore
from app.services.provider_client import ProviderClient


class FakeSseResponse:
    def __init__(self, sse_lines, headers=None):
        self.sse_lines = sse_lines
        self.headers = headers or {"Content-Type": "text/event-stream"}
        self._raw = b"".join(line.encode("utf-8") if isinstance(line, str) else line for line in sse_lines)
        self._pos = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        for line in self.sse_lines:
            yield line.encode("utf-8") if isinstance(line, str) else line

    def read(self, size=-1, *args, **kwargs):
        if size is None or size < 0:
            res = self._raw[self._pos:]
            self._pos = len(self._raw)
            return res
        res = self._raw[self._pos:self._pos + size]
        self._pos += len(res)
        return res

    def readline(self, *args, **kwargs):
        if self._pos >= len(self._raw):
            return b""
        newline_pos = self._raw.find(b"\n", self._pos)
        if newline_pos == -1:
            res = self._raw[self._pos:]
            self._pos = len(self._raw)
            return res
        res = self._raw[self._pos:newline_pos + 1]
        self._pos = newline_pos + 1
        return res

    def close(self):
        pass


class Issue262StreamValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "adapter.json"
        self.key_dir = self.root / "provider_api_keys"
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.store = DirectServiceStore(self.config_path, self.key_dir)
        self.settings = AppSettings(
            service_port=18100,
            provider_base_url="https://api.example.com/v1",
            timeout_seconds=5,
        )
        self.client = ProviderClient(
            self.settings,
            direct_service_store=self.store,
        )

    def tearDown(self):
        try:
            self.tmp.cleanup()
        except OSError:
            time.sleep(0.05)
            try:
                self.tmp.cleanup()
            except OSError:
                pass

    def _wait_completed(self, store, job_id):
        for _ in range(100):
            job = store.get(job_id)
            if job and job.get("status") in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        return None

    def _create_service(self, name="流式复用测试服务", model="gpt-4o"):
        svc = self.store.create_service(
            name=name,
            service_base_url="https://api.example.com/v1",
            default_model=model,
        )
        self.store.replace_api_key(svc["id"], "sk-secret-token-12345", expected_revision=1)
        svc = self.store.get_service(svc["id"])
        self.store.update_model_list(svc["id"], [model], expected_revision=svc["revision"])
        svc = self.store.get_service(svc["id"])
        self.store.update_task_model_selection(
            "word.smart_write",
            service_id=svc["id"],
            model_name=model,
        )
        self.store.activate_direct_service(svc["id"], "word.smart_write")
        return self.store.get_service(svc["id"])

    def test_validate_task_model_selection_reuses_valid_streaming_capability(self):
        service = self._create_service(model="gpt-4o")
        binding = {
            "serviceRevision": int(service.get("revision", 1)),
            "serviceBaseUrl": "https://api.example.com/v1",
            "apiKeyFingerprint": DirectServiceStore.api_key_fingerprint("sk-secret-token-12345"),
        }
        # Pre-record validated capability
        self.store.record_streaming_capability(
            service["id"],
            "gpt-4o",
            "validated",
            expected_binding=binding,
        )

        with patch("urllib.request.urlopen") as mock_url:
            res = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-reuse-validated",
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["streamingCapability"], "validated")
        # taskCallPerformed must be False since valid record was reused
        self.assertFalse(res.get("taskCallPerformed", True))
        mock_url.assert_not_called()

    def test_validate_task_model_selection_reuses_unsupported_capability(self):
        service = self._create_service(model="gpt-4o")
        binding = {
            "serviceRevision": int(service.get("revision", 1)),
            "serviceBaseUrl": "https://api.example.com/v1",
            "apiKeyFingerprint": DirectServiceStore.api_key_fingerprint("sk-secret-token-12345"),
        }
        # Pre-record unsupported capability
        self.store.record_streaming_capability(
            service["id"],
            "gpt-4o",
            "unsupported",
            expected_binding=binding,
        )

        with patch("urllib.request.urlopen") as mock_url:
            res = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-reuse-unsupported",
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["streamingCapability"], "unsupported")
        self.assertFalse(res.get("taskCallPerformed", True))
        mock_url.assert_not_called()

    def test_validate_task_model_selection_reprobes_when_stale_or_missing(self):
        service = self._create_service(model="gpt-4o")
        # Case 1: missing record -> calls urlopen
        sse_lines = [
            'data: {"choices": [{"delta": {"content": "系统已完成"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "部署。"}}]}\n\n',
            'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen", return_value=FakeSseResponse(sse_lines)) as mock_url:
            res = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-probe-missing",
            )
        self.assertTrue(res["success"])
        self.assertEqual(res["streamingCapability"], "validated")
        self.assertTrue(res.get("taskCallPerformed", False))
        self.assertEqual(mock_url.call_count, 1)

        # Case 2: update service URL -> record becomes stale -> re-probes
        self.store.update_service(
            service["id"],
            name=service["name"],
            service_base_url="https://api-updated.example.com/v1",
            expected_revision=service["revision"],
        )
        service = self.store.get_service(service["id"])
        with patch("urllib.request.urlopen", return_value=FakeSseResponse(sse_lines)) as mock_url2:
            res2 = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-probe-stale",
            )
        self.assertTrue(res2["success"])
        self.assertEqual(res2["streamingCapability"], "validated")
        self.assertTrue(res2.get("taskCallPerformed", False))
        self.assertEqual(mock_url2.call_count, 1)

    def test_validate_task_model_selection_deduplicates_in_flight_probes(self):
        service = self._create_service(model="gpt-4o")
        sse_lines = [
            'data: {"choices": [{"delta": {"content": "系统已完成"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "部署。"}}]}\n\n',
            'data: [DONE]\n\n',
        ]

        urlopen_call_count = [0]
        probe_started_event = threading.Event()
        proceed_event = threading.Event()

        def slow_urlopen(req, timeout=None):
            urlopen_call_count[0] += 1
            probe_started_event.set()
            proceed_event.wait(timeout=2.0)
            return FakeSseResponse(sse_lines)

        results = []

        def worker(trace_id):
            r = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                trace_id,
            )
            results.append(r)

        with patch("urllib.request.urlopen", side_effect=slow_urlopen):
            t1 = threading.Thread(target=worker, args=("trace-concurrent-1",))
            t1.start()

            # Wait until t1 is in slow_urlopen
            probe_started_event.wait(timeout=2.0)

            # Launch concurrent t2
            t2 = threading.Thread(target=worker, args=("trace-concurrent-2",))
            t2.start()

            # Small yield to let t2 hit validate_task_model_selection
            time.sleep(0.05)
            proceed_event.set()

            t1.join(timeout=3.0)
            t2.join(timeout=3.0)

        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r["success"])
            self.assertEqual(r["streamingCapability"], "validated")

        # Network call should only have executed ONCE due to in-flight deduplication
        self.assertEqual(urlopen_call_count[0], 1)

    def test_smart_write_uses_streaming_when_capability_validated(self):
        from app.services.long_task_coordinator import LongTaskCoordinator
        from app.services.word.writing_jobs import SmartWriteJobStore
        from app.core.models import WordDocumentRequest

        worker = MagicMock()
        worker.snapshot_task_auth.return_value = {
            "accessMethod": "direct_model",
            "serviceId": "direct_svc_1",
            "modelName": "gpt-4o",
            "streamingCapability": "validated",
        }
        worker.smart_write.return_value = {
            "text": "改写结果",
            "plainText": "改写结果",
            "rewrittenText": "改写结果",
        }
        from app.services.task_history import TaskHistoryStore
        history_store = TaskHistoryStore(self.root / "history")
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)

        req_payload = {
            "documentId": "doc1.docx",
            "scene": "word",
            "selectionMode": "selection",
            "clientJobId": "client-stream-1",
            "content": {"plainText": "原文字段"},
            "options": {"rewrite_action": "rewrite"},
        }
        req = (
            WordDocumentRequest.model_validate(req_payload)
            if hasattr(WordDocumentRequest, "model_validate")
            else WordDocumentRequest.parse_obj(req_payload)
        )

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), \
             patch("app.services.word.writing_jobs.get_task_history_store", return_value=history_store):
            submitted = store.start(req, "trace-stream-1")
            self.assertTrue(submitted["streamingEnabled"])
            self._wait_completed(store, submitted["jobId"])

    def test_smart_write_uses_blocking_when_capability_unsupported_or_not_checked(self):
        from app.services.long_task_coordinator import LongTaskCoordinator
        from app.services.word.writing_jobs import SmartWriteJobStore
        from app.services.task_history import TaskHistoryStore
        from app.core.models import WordDocumentRequest

        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        history_store = TaskHistoryStore(self.root / "history")

        for status in ["unsupported", "not_checked", None]:
            worker = MagicMock()
            worker.snapshot_task_auth.return_value = {
                "accessMethod": "direct_model",
                "serviceId": "direct_svc_1",
                "modelName": "gpt-4o",
                "streamingCapability": status,
            }
            worker.smart_write.return_value = {
                "text": "阻塞结果",
                "plainText": "阻塞结果",
                "rewrittenText": "阻塞结果",
            }
            store = SmartWriteJobStore(worker=worker, coordinator=coordinator)
            req_payload = {
                "documentId": "doc1.docx",
                "scene": "word",
                "selectionMode": "selection",
                "clientJobId": f"client-block-{status}",
                "content": {"plainText": "原文字段"},
                "options": {"rewrite_action": "rewrite"},
            }
            req = (
                WordDocumentRequest.model_validate(req_payload)
                if hasattr(WordDocumentRequest, "model_validate")
                else WordDocumentRequest.parse_obj(req_payload)
            )

            with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), \
                 patch("app.services.word.writing_jobs.get_task_history_store", return_value=history_store):
                submitted = store.start(req, f"trace-block-{status}")
                self.assertFalse(submitted["streamingEnabled"])
                self._wait_completed(store, submitted["jobId"])

    def test_fastapi_and_standalone_parity_for_validation_and_streaming(self):
        from io import BytesIO
        from fastapi.testclient import TestClient
        import standalone_adapter
        from app.main import app
        from app.services.model_configurations import ModelConfigurationStore

        service = self._create_service(model="gpt-4o")
        binding = {
            "serviceRevision": int(service.get("revision", 1)),
            "serviceBaseUrl": "https://api.example.com/v1",
            "apiKeyFingerprint": DirectServiceStore.api_key_fingerprint("sk-secret-token-12345"),
        }
        self.store.record_streaming_capability(
            service["id"],
            "gpt-4o",
            "validated",
            expected_binding=binding,
        )

        # 1. FastAPI validation
        with patch("app.api.provider.DirectServiceStore", return_value=self.store), \
             patch("app.api.provider.ModelConfigurationStore", return_value=ModelConfigurationStore(self.config_path, self.key_dir)), \
             patch("app.services.provider_client.load_settings", return_value=self.settings):
            fastapi_resp = TestClient(app).post(
                "/provider/task-model-selections/word.smart_write/validate",
                json={"serviceId": service["id"], "modelName": "gpt-4o"},
            )
            self.assertEqual(fastapi_resp.status_code, 200)
            fastapi_data = fastapi_resp.json()
            self.assertTrue(fastapi_data["success"])
            self.assertEqual(fastapi_data["data"]["streamingCapability"], "validated")
            self.assertEqual(fastapi_data["data"]["taskCallPerformed"], False)

        # 2. Standalone validation
        orig_standalone_store = standalone_adapter.DirectServiceStore
        orig_standalone_model = standalone_adapter.ModelConfigurationStore
        try:
            standalone_adapter.DirectServiceStore = lambda: self.store
            standalone_adapter.ModelConfigurationStore = lambda: ModelConfigurationStore(self.config_path, self.key_dir)

            writes = []
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = "/provider/task-model-selections/word.smart_write/validate"
            handler.command = "POST"
            handler.requestline = "POST /provider/task-model-selections/word.smart_write/validate HTTP/1.1"
            handler.request_version = "HTTP/1.1"
            raw = json.dumps({"serviceId": service["id"], "modelName": "gpt-4o"}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler.close_connection = False
            handler._reject_operation_block = lambda m, p: False
            handler._reject_writing_policy_route_or_method = lambda m, p: False
            handler._write = lambda status, payload: writes.append((status, payload))
            handler._write_bytes = lambda status, payload, headers=None: writes.append(
                (status, json.loads(payload.decode("utf-8")) if payload else {})
            )
            handler.do_POST()
            status, standalone_data = writes[-1] if writes else (None, None)
            self.assertEqual(status, 200)
            self.assertTrue(standalone_data["success"])
            self.assertEqual(standalone_data["data"]["streamingCapability"], "validated")
            self.assertEqual(standalone_data["data"]["taskCallPerformed"], False)

            # Both runtimes returned matching data fields
            self.assertEqual(
                fastapi_data["data"]["streamingCapability"],
                standalone_data["data"]["streamingCapability"],
            )
            self.assertEqual(
                fastapi_data["data"]["taskCallPerformed"],
                standalone_data["data"]["taskCallPerformed"],
            )
        finally:
            standalone_adapter.DirectServiceStore = orig_standalone_store
            standalone_adapter.ModelConfigurationStore = orig_standalone_model


if __name__ == "__main__":
    unittest.main()
