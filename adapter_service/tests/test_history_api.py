import importlib.util
import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.direct_services import DirectServiceStore
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryStore

HAS_PYDANTIC = bool(importlib.util.find_spec("pydantic"))
HAS_FASTAPI = bool(importlib.util.find_spec("fastapi"))


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone adapter tests")
class StandaloneHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.history_dir = Path(self.tmp.name) / "history"
        self.store = TaskHistoryStore(self.history_dir)

        import standalone_adapter

        self.standalone = standalone_adapter

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _invoke(self, method: str, path: str, body: dict = None) -> dict:
        writes = []
        handler = object.__new__(self.standalone.Handler)
        handler.path = path
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        raw = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler.close_connection = False
        handler._reject_operation_block = lambda m, p: False
        handler._reject_writing_policy_route_or_method = lambda m, p: False
        handler.send_error = lambda code, message=None: writes.append(
            (code, {"message": message})
        )
        handler._write = lambda status, payload: writes.append((status, payload))

        with patch.object(self.standalone, "get_task_history_store", return_value=self.store):
            getattr(handler, method)()

        status, resp_body = writes[-1] if writes else (None, None)
        return {"status": status, "body": resp_body, "writes": writes}

    def test_standalone_history_api_lifecycle(self) -> None:
        # 1. Initial list should be empty
        res = self._invoke("do_GET", "/history?taskType=ppt.slide_assistant")
        self.assertEqual(res["status"], 200)
        self.assertTrue(res["body"]["success"])
        self.assertEqual(res["body"]["data"]["items"], [])
        self.assertEqual(res["body"]["data"]["total"], 0)

        # 2. Add an item directly via store
        entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-ppt-001",
            result={"resultType": "slide", "suggestedTitle": "总结标题"},
            document_display_name="演示.pptx",
            service_name="网关",
            model_name="qwen",
        )
        entry_id = entry["id"]

        # 3. List should return the item
        res = self._invoke("do_GET", "/history?taskType=ppt.slide_assistant")
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["data"]["total"], 1)
        self.assertEqual(res["body"]["data"]["items"][0]["id"], entry_id)

        # 4. Get single item
        res = self._invoke("do_GET", f"/history/{entry_id}")
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["data"]["item"]["id"], entry_id)
        self.assertEqual(res["body"]["data"]["item"]["result"]["suggestedTitle"], "总结标题")

        # 5. Get non-existent or malicious item returns 404
        res = self._invoke("do_GET", "/history/hist_not_found")
        self.assertEqual(res["status"], 404)
        res = self._invoke("do_GET", "/history/*")
        self.assertEqual(res["status"], 404)
        res = self._invoke("do_GET", "/history/..%2F..%2Fconfig%2Fadapter")
        self.assertEqual(res["status"], 404)

        # 5.1 Delete with wildcard/traversal returns 404 and does not delete
        res = self._invoke("do_DELETE", "/history/*")
        self.assertEqual(res["status"], 404)
        res = self._invoke("do_DELETE", "/history/..%2F..%2Fconfig%2Fadapter")
        self.assertEqual(res["status"], 404)

        # 6. Delete single item
        res = self._invoke("do_DELETE", f"/history/{entry_id}")
        self.assertEqual(res["status"], 200)
        self.assertTrue(res["body"]["data"]["deleted"])

        # 7. List should now be empty
        res = self._invoke("do_GET", "/history?taskType=ppt.slide_assistant")
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["data"]["total"], 0)

        # 8. Clear history
        self.store.record_success("ppt.slide_assistant", "j1", {"a": 1}, "d1.pptx", "s", "m")
        self.store.record_success("ppt.slide_assistant", "j2", {"a": 2}, "d2.pptx", "s", "m")
        res = self._invoke("do_DELETE", "/history?taskType=ppt.slide_assistant")
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["data"]["clearedCount"], 2)


@unittest.skipUnless(HAS_PYDANTIC and HAS_FASTAPI, "fastapi and pydantic are required for FastApi history API tests")
class FastApiHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.history_dir = Path(self.tmp.name) / "history"
        self.store = TaskHistoryStore(self.history_dir)

        from fastapi.testclient import TestClient
        from app.main import app

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fastapi_history_api_lifecycle(self) -> None:
        with patch("app.api.history.get_task_history_store", return_value=self.store):
            # 1. Initial list empty
            res = self.client.get("/history?taskType=ppt.slide_assistant")
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertEqual(data["items"], [])
            self.assertEqual(data["total"], 0)

            # 2. Add entry
            entry = self.store.record_success(
                task_type="ppt.slide_assistant",
                job_id="job-fastapi-001",
                result={"resultType": "slide", "suggestedTitle": "FastAPI总结"},
                document_display_name="汇报.pptx",
                service_name="企业网关",
                model_name="qwen-max",
            )
            entry_id = entry["id"]

            # 3. List contains item
            res = self.client.get("/history?taskType=ppt.slide_assistant")
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["id"], entry_id)

            # 4. Get item
            res = self.client.get(f"/history/{entry_id}")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["data"]["item"]["id"], entry_id)

            # 5. Get 404 on invalid ID / traversal / not found
            res = self.client.get("/history/non_existent_id")
            self.assertEqual(res.status_code, 404)
            res = self.client.get("/history/*")
            self.assertEqual(res.status_code, 404)

            # 5.1 Delete 404 on invalid ID / wildcard
            res = self.client.delete("/history/*")
            self.assertEqual(res.status_code, 404)

            # 6. Delete item
            res = self.client.delete(f"/history/{entry_id}")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["data"]["deleted"])

            # 7. Clear history
            self.store.record_success("ppt.slide_assistant", "j1", {"v": 1}, "1.pptx", "s", "m")
            self.store.record_success("ppt.slide_assistant", "j2", {"v": 2}, "2.pptx", "s", "m")
            res = self.client.delete("/history?taskType=ppt.slide_assistant")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["data"]["clearedCount"], 2)

    def test_completed_history_remains_visible_after_key_rotation(self) -> None:
        coordinator = LongTaskCoordinator()
        service_id = "direct_history_service"
        old_fingerprint = DirectServiceStore.api_key_fingerprint("sk-history")
        coordinator.submit(
            job_id="history-rotation-job",
            trace_id="history-rotation-trace",
            task_type="ppt.slide_assistant",
            runner=lambda _snapshot, _progress: {"summary": "已完成结果"},
            snapshot={
                "taskAuth": {
                    "directService": {"id": service_id, "revision": 5},
                    "apiKeyFingerprint": old_fingerprint,
                }
            },
            failure_code="FAILED",
            failure_message="failed",
            success_committer=lambda _snapshot, result: self.store.record_success(
                task_type="ppt.slide_assistant",
                job_id="history-rotation-job",
                result=result,
                document_display_name="轮换前完成.pptx",
                service_name="共享直连",
                model_name="model-a",
            ),
        )
        completed = coordinator.wait(
            "history-rotation-job", task_type="ppt.slide_assistant"
        )
        coordinator.invalidate_by_auth(
            service_id, old_fingerprint, service_revision=5
        )

        with patch("app.api.history.get_task_history_store", return_value=self.store):
            response = self.client.get(
                "/history?taskType=ppt.slide_assistant"
            )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)
        self.assertEqual(
            response.json()["data"]["items"][0]["jobId"],
            "history-rotation-job",
        )


if __name__ == "__main__":
    unittest.main()
