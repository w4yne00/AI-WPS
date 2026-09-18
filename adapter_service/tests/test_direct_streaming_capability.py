import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from app.core.config import AppSettings
from app.core.errors import AdapterError
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


class FakeBlockingResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")

    def close(self):
        pass


class DirectStreamingCapabilityTests(unittest.TestCase):
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

    def _create_service(self, name="流式验证服务", model="gpt-4o"):
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

    def test_streaming_probe_success_marks_validated(self):
        service = self._create_service()
        sse_lines = [
            'data: {"choices": [{"delta": {"content": "系统已完成"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "部署。"}}]}\n\n',
            'data: [DONE]\n\n',
        ]
        sse_resp = FakeSseResponse(sse_lines)

        with patch("urllib.request.urlopen", return_value=sse_resp):
            res = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-streaming-probe-ok",
            )

        self.assertTrue(res["success"])
        self.assertTrue(res["taskContractValidated"])
        self.assertEqual(res["streamingCapability"], "validated")

        # Check stored capability in store
        sel = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(sel["streamingCapability"]["status"], "validated")
        self.assertEqual(sel["streamingCapability"]["serviceId"], service["id"])
        self.assertEqual(sel["streamingCapability"]["modelName"], "gpt-4o")

    def test_streaming_probe_unsupported_falls_back_to_blocking_and_marks_unsupported(self):
        service = self._create_service()
        blocking_resp = FakeBlockingResponse({
            "choices": [{"message": {"role": "assistant", "content": "系统已完成部署。"}}],
        })

        def mock_urlopen(req, timeout=None):
            data = json.loads(req.data.decode("utf-8"))
            if data.get("stream"):
                fp = FakeBlockingResponse({"error": {"message": "Streaming not supported"}})
                raise HTTPError(req.full_url, 400, "Bad Request", {"Content-Type": "application/json"}, fp)
            return blocking_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = self.client.validate_task_model_selection(
                "word.smart_write",
                {"serviceId": service["id"], "modelName": "gpt-4o"},
                "trace-streaming-probe-unsupported",
            )

        self.assertTrue(res["success"])
        self.assertTrue(res["taskContractValidated"])
        self.assertEqual(res["streamingCapability"], "unsupported")

        # Check stored capability in store
        sel = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(sel["streamingCapability"]["status"], "unsupported")

    def test_streaming_probe_auth_failure_raises_adapter_error_and_does_not_record(self):
        service = self._create_service()

        def mock_urlopen(req, timeout=None):
            fp = FakeBlockingResponse({"error": {"message": "Invalid API key"}})
            raise HTTPError(req.full_url, 401, "Unauthorized", {"Content-Type": "application/json"}, fp)

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with self.assertRaises(AdapterError) as ctx:
                self.client.validate_task_model_selection(
                    "word.smart_write",
                    {"serviceId": service["id"], "modelName": "gpt-4o"},
                    "trace-streaming-probe-auth-err",
                )
            self.assertEqual(ctx.exception.code, "PROVIDER_AUTH_FAILED")

        sel = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(sel["streamingCapability"]["status"], "not_checked")

    def test_auth_snapshot_freezes_streaming_capability(self):
        service = self._create_service()
        self.store.record_streaming_capability(service["id"], "gpt-4o", "validated")

        frozen_auth = self.client.resolve_task_auth("word.smart_write")
        self.assertIn("streamingCapability", frozen_auth)
        self.assertEqual(frozen_auth["streamingCapability"]["status"], "validated")

        self.store.update_service(
            service["id"],
            name=service["name"],
            service_base_url="https://api.example.com/v2",
            expected_revision=service["revision"],
        )
        current_svc = self.store.get_service(service["id"])
        self.store.update_model_list(
            service["id"],
            ["gpt-4o"],
            expected_revision=current_svc["revision"],
        )
        current_selection = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(current_selection["streamingCapability"]["status"], "stale")

        self.assertEqual(frozen_auth["streamingCapability"]["status"], "validated")

        new_auth = self.client.resolve_task_auth("word.smart_write")
        self.assertEqual(new_auth["streamingCapability"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
