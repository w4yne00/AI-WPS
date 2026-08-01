import importlib.util
import threading
import unittest


HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_FASTAPI and HAS_PYDANTIC:
    from fastapi.testclient import TestClient

    from app.api import excel as excel_api
    from app.api import ppt as ppt_api
    from app.api import provider as provider_api
    from app.api import word as word_api
    from app.main import app
    from app.services.long_task_coordinator import LongTaskCoordinator


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, snapshot, progress):
        progress("provider_processing")
        self.started.set()
        self.release.wait(timeout=3)
        progress("parsing")
        return {"taskType": snapshot["taskType"]}


class RouteJobStore:
    def __init__(self, task_type, coordinator, runners):
        self.task_type = task_type
        self.coordinator = coordinator
        self.runners = runners

    def start(self, request, trace_id):
        job_id = request.client_job_id
        runner = BlockingRunner()
        self.runners[job_id] = runner
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type=self.task_type,
            runner=runner,
            snapshot={"taskType": self.task_type},
            failure_code="LONG_TASK_FAILED",
            failure_message="后台任务执行失败。",
        )

    def get(self, job_id):
        return self.coordinator.get(job_id, task_type=self.task_type)

    def cancel(self, job_id):
        return self.coordinator.cancel(job_id, task_type=self.task_type)

    def run_sync(self, request, trace_id):
        job = self.start(request, trace_id)
        terminal = self.coordinator.wait(job["jobId"], task_type=self.task_type)
        return terminal["result"]


@unittest.skipUnless(
    HAS_FASTAPI and HAS_PYDANTIC,
    "fastapi and pydantic are required for cross-host route tests",
)
class CrossHostLongTaskRouteTests(unittest.TestCase):
    @staticmethod
    def _word_payload(job_id):
        return {
            "documentId": "cross-host.docx",
            "scene": "word",
            "selectionMode": "selection",
            "clientJobId": job_id,
            "content": {
                "plainText": "跨宿主文档审查内容。",
                "paragraphs": [],
                "headings": [],
            },
            "options": {
                "technicalDocumentType": "technical_solution",
                "technicalReviewPrompt": "检查表达。",
            },
        }

    @staticmethod
    def _excel_payload(job_id):
        return {
            "workbookId": "cross-host.xlsx",
            "scene": "excel",
            "clientJobId": job_id,
            "scope": {
                "type": "selection",
                "sheetName": "Sheet1",
                "address": "A1:B2",
            },
            "table": {
                "headers": ["项目", "金额"],
                "rows": [["项目A", "100"]],
                "rowCount": 1,
                "columnCount": 2,
                "truncated": False,
            },
            "options": {"analysisRequirement": "检查异常。"},
        }

    @staticmethod
    def _ppt_payload(job_id):
        return {
            "presentationId": "cross-host.pptx",
            "scene": "ppt",
            "sourceMode": "slide",
            "clientJobId": job_id,
            "slide": {
                "index": 1,
                "title": "跨宿主测试",
                "subtitle": "共享队列",
                "textBlocks": ["正文内容达到二十个非空白字符，用于验证共享队列外部契约。"],
                "previousTitle": "",
                "nextTitle": "",
                "truncated": False,
            },
            "userInstruction": "总结共享队列状态。",
        }

    def test_three_hosts_share_two_running_eight_queued_fifo_contract(self):
        coordinator = LongTaskCoordinator()
        runners = {}
        stores = {
            "word": RouteJobStore("word.document_review", coordinator, runners),
            "excel": RouteJobStore("excel.analysis", coordinator, runners),
            "ppt": RouteJobStore("ppt.slide_assistant", coordinator, runners),
        }
        original_stores = (
            word_api.document_review_jobs,
            excel_api.excel_analysis_jobs,
            ppt_api.ppt_slide_jobs,
            provider_api.get_long_task_coordinator,
        )
        word_api.document_review_jobs = stores["word"]
        excel_api.excel_analysis_jobs = stores["excel"]
        ppt_api.ppt_slide_jobs = stores["ppt"]
        provider_api.get_long_task_coordinator = lambda: coordinator
        client = TestClient(app)
        jobs = []
        endpoints = {
            "word": "/word/document-review/jobs",
            "excel": "/excel/analysis/jobs",
            "ppt": "/ppt/slide-assistant/jobs",
        }
        payloads = {
            "word": self._word_payload,
            "excel": self._excel_payload,
            "ppt": self._ppt_payload,
        }
        try:
            for index in range(10):
                host = ("word", "excel", "ppt")[index % 3]
                job_id = "client-cross-route-{0:02d}".format(index)
                response = client.post(endpoints[host], json=payloads[host](job_id))
                self.assertEqual(response.status_code, 200)
                jobs.append((host, job_id, response.json()["data"]))

            self.assertTrue(runners[jobs[0][1]].started.wait(timeout=1))
            self.assertTrue(runners[jobs[1][1]].started.wait(timeout=1))
            self.assertEqual([job[2]["status"] for job in jobs[:2]], ["running", "running"])
            self.assertEqual(
                [job[2]["queuePosition"] for job in jobs[2:]],
                list(range(1, 9)),
            )

            full = client.post(
                endpoints["excel"],
                json=self._excel_payload("client-cross-route-full"),
            )
            self.assertEqual(full.status_code, 429)
            self.assertEqual(full.json()["errors"][0]["code"], "LONG_TASK_QUEUE_FULL")
            self.assertIn("排队已满", full.json()["message"])

            word_sync = client.post(
                "/word/document-review",
                json=self._word_payload("client-cross-route-word-sync-full"),
            )
            excel_sync = client.post(
                "/excel/analysis",
                json=self._excel_payload("client-cross-route-excel-sync-full"),
            )
            self.assertEqual(word_sync.status_code, 429)
            self.assertEqual(excel_sync.status_code, 429)
            self.assertEqual(
                word_sync.json()["errors"][0]["code"], "LONG_TASK_QUEUE_FULL"
            )
            self.assertEqual(
                excel_sync.json()["errors"][0]["code"], "LONG_TASK_QUEUE_FULL"
            )

            cancelled = client.delete(
                "/excel/analysis/jobs/client-cross-route-04"
            )
            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
            shifted = client.get(
                "/ppt/slide-assistant/jobs/client-cross-route-05"
            )
            self.assertEqual(shifted.json()["data"]["queuePosition"], 3)

            runners[jobs[0][1]].release.set()
            self.assertTrue(runners[jobs[2][1]].started.wait(timeout=1))

            diagnostics = client.get("/provider/route-diagnostics").json()["data"]
            queue = diagnostics["longTaskCoordinator"]
            self.assertEqual(queue["maxRunning"], 2)
            self.assertEqual(queue["maxQueued"], 8)
            self.assertEqual(queue["runningCount"], 2)
            self.assertEqual(queue["queuedCount"], 6)
            self.assertEqual(queue["cancelledCount"], 1)
            self.assertEqual(queue["rejectedCount"], 3)
        finally:
            for runner in runners.values():
                runner.release.set()
            (
                word_api.document_review_jobs,
                excel_api.excel_analysis_jobs,
                ppt_api.ppt_slide_jobs,
                provider_api.get_long_task_coordinator,
            ) = original_stores


if __name__ == "__main__":
    unittest.main()
