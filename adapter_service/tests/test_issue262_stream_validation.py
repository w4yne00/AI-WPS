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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        for line in self.sse_lines:
            yield line.encode("utf-8") if isinstance(line, str) else line

    def read(self):
        out = []
        for line in self.sse_lines:
            out.append(line.encode("utf-8") if isinstance(line, str) else line)
        return b"".join(out)

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
        self.tmp.cleanup()

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
            with patch("urllib.request.urlopen", side_effect=slow_urlopen):
                r = self.client.validate_task_model_selection(
                    "word.smart_write",
                    {"serviceId": service["id"], "modelName": "gpt-4o"},
                    trace_id,
                )
                results.append(r)

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


if __name__ == "__main__":
    unittest.main()
