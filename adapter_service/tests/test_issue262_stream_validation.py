import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from app.core.config import AppSettings
from app.core.errors import AdapterError, ProviderUnavailableError
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

    def _start_validation(self, service, trace_id, model="gpt-4o", task_type="word.smart_write"):
        results, errors = [], []

        def worker():
            try:
                results.append(self.client.validate_task_model_selection(
                    task_type,
                    {"serviceId": service["id"], "modelName": model},
                    trace_id,
                ))
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, name=trace_id)
        thread.start()
        return thread, results, errors

    def _observe_follower_registration(self, follower_name):
        registered = threading.Event()
        lock = threading.Lock()

        class ObservedLock:
            def __enter__(self):
                lock.acquire()

            def __exit__(self, *args):
                lock.release()
                if threading.current_thread().name == follower_name:
                    registered.set()

        self.client._streaming_probe_lock = ObservedLock()
        return registered

    def test_validate_task_model_selection_deduplicates_in_flight_probes(self):
        service = self._create_service()
        started, proceed = threading.Event(), threading.Event()
        registered = self._observe_follower_registration("follower")

        def slow_probe(*args):
            started.set()
            if not proceed.wait(3):
                raise RuntimeError("test probe was not released")
            return "系统已完成部署。"

        with patch.object(self.client, "_probe_direct_streaming", side_effect=slow_probe) as probe:
            owner = self._start_validation(service, "owner")
            try:
                self.assertTrue(started.wait(2))
                follower = self._start_validation(service, "follower", task_type="word.smart_imitation")
                self.assertTrue(registered.wait(2))
            finally:
                proceed.set()
                owner[0].join(3)
            follower[0].join(3)

        for thread, results, errors in (owner, follower):
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results[0]["streamingCapability"], "validated")
        self.assertEqual(probe.call_count, 1)

    def test_concurrent_validation_shares_owner_failure_without_retry(self):
        service = self._create_service()
        started, proceed = threading.Event(), threading.Event()
        registered = self._observe_follower_registration("follower")

        def failing_probe(*args):
            started.set()
            if not proceed.wait(3):
                raise RuntimeError("test probe was not released")
            raise ProviderUnavailableError("模型服务暂不可用。")

        with patch.object(self.client, "_probe_direct_streaming", side_effect=failing_probe) as probe:
            owner = self._start_validation(service, "owner")
            try:
                self.assertTrue(started.wait(2))
                follower = self._start_validation(service, "follower")
                self.assertTrue(registered.wait(2))
            finally:
                proceed.set()
                owner[0].join(3)
            follower[0].join(3)

        for thread, results, errors in (owner, follower):
            self.assertFalse(thread.is_alive())
            self.assertEqual(results, [])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].code, "PROVIDER_UNREACHABLE")
        self.assertEqual(probe.call_count, 1)

    def test_waiter_timeout_does_not_repeat_request_or_release_owner(self):
        service = self._create_service()
        started, proceed = threading.Event(), threading.Event()

        def slow_probe(*args):
            if threading.current_thread().name == "owner":
                started.set()
                if not proceed.wait(3):
                    raise RuntimeError("test probe was not released")
            return "系统已完成部署。"

        with patch.object(self.client, "_probe_direct_streaming", side_effect=slow_probe) as probe, \
             patch("app.services.provider_client.INTERACTIVE_WRITING_TIMEOUT_SECONDS", 0.02), \
             patch.object(self.settings, "timeout_seconds", 0.02):
            owner = self._start_validation(service, "owner")
            try:
                self.assertTrue(started.wait(2))
                for name in ("waiter-1", "waiter-2"):
                    thread, results, errors = self._start_validation(service, name)
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(results, [])
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], AdapterError)
                    self.assertEqual(errors[0].code, "PROVIDER_TIMEOUT")
                self.assertEqual(probe.call_count, 1)
            finally:
                proceed.set()
                owner[0].join(3)
        self.assertEqual(owner[2], [])

    def test_updated_service_does_not_join_old_configuration_probe(self):
        for changed_field in ("revision", "url", "key", "model"):
            with self.subTest(changed_field=changed_field):
                service = self._create_service(name="配置隔离-" + changed_field)
                started, proceed, second_started = (threading.Event() for _ in range(3))

                def slow_probe(*args):
                    if threading.current_thread().name == "owner":
                        started.set()
                        if not proceed.wait(3):
                            raise RuntimeError("test probe was not released")
                    else:
                        second_started.set()
                    return "系统已完成部署。"

                follower = None
                with patch.object(self.client, "_probe_direct_streaming", side_effect=slow_probe) as probe:
                    owner = self._start_validation(service, "owner")
                    try:
                        self.assertTrue(started.wait(2))
                        model = "gpt-4o"
                        if changed_field in {"revision", "url"}:
                            self.store.update_service(
                                service["id"], name="更新配置-" + changed_field,
                                service_base_url=("https://updated.example.com/v1"
                                                  if changed_field == "url"
                                                  else service["serviceBaseUrl"]),
                                expected_revision=service["revision"],
                            )
                        elif changed_field == "key":
                            self.store.replace_api_key(
                                service["id"], "sk-updated-key", expected_revision=service["revision"],
                            )
                        else:
                            model = "GPT-4o"
                        follower = self._start_validation(service, "new-config", model)
                        self.assertTrue(second_started.wait(1), "新配置不应等待旧配置探测")
                    finally:
                        proceed.set()
                        owner[0].join(3)
                        if follower is not None:
                            follower[0].join(3)
                    self.assertEqual(follower[2], [])
                    self.assertEqual(follower[1][0]["streamingCapability"], "validated")
                    self.assertEqual(probe.call_count, 2)
                    if changed_field != "model":
                        self.assertEqual(owner[2][0].code, "DIRECT_SERVICE_CONFIG_CHANGED")
                    else:
                        self.assertEqual(owner[2], [])

    def test_capability_created_before_probe_lock_is_reused(self):
        service = self._create_service()
        original_get = self.store.get_streaming_capability
        calls = []

        def racing_get(*args):
            capability = original_get(*args)
            calls.append(capability)
            if len(calls) == 1:
                self.store.record_streaming_capability(
                    service["id"], "gpt-4o", "validated",
                )
            return capability

        with patch.object(self.store, "get_streaming_capability", side_effect=racing_get), \
             patch.object(self.client, "_probe_direct_streaming", return_value="系统已完成部署。") as probe:
            result = self.client.validate_task_model_selection(
                "word.smart_write", {"serviceId": service["id"], "modelName": "gpt-4o"}, "cache-race",
            )
        self.assertEqual(result["streamingCapability"], "validated")
        self.assertFalse(result["taskCallPerformed"])
        probe.assert_not_called()

    def test_other_tasks_still_perform_validation_when_capability_is_cached(self):
        service = self._create_service()
        self.store.record_streaming_capability(service["id"], "gpt-4o", "validated")
        answers = {
            "word.document_review": '{"summary":"通过","issues":[]}',
            "excel.analysis": '{"overview":"完成","findings":[],"risks":[],"actions":[]}',
            "ppt.slide_assistant": '{"suggestedTitle":"进展","summary":"完成","keyPoints":[],"layoutAdvice":[],"plainText":"完成"}',
        }
        for task_type, answer in answers.items():
            with self.subTest(task_type=task_type), patch.object(
                self.client, "_probe_direct_streaming", return_value=answer,
            ) as probe:
                result = self.client.validate_task_model_selection(
                    task_type, {"serviceId": service["id"], "modelName": "gpt-4o"}, "other-task",
                )
                self.assertTrue(result["taskCallPerformed"])
                self.assertEqual(probe.call_count, 1)

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
