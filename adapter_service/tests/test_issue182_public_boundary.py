# -*- coding: utf-8 -*-
"""Issue #182：九任务公开边界必须走 FastAPI / standalone，而不是生产常量派生的 Store 直调。"""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.services.long_task_coordinator import LongTaskCancelled, LongTaskCoordinator
from app.services.task_history import TaskHistoryStore
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


SPEC_NINE_TASKS = (
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
    "word.format_review",
    "excel.analysis",
    "excel.formula_assistant",
    "excel.smart_fill",
    "ppt.slide_assistant",
    "ppt.structure_review",
)
SECRET_KEY = "sk-live-issue182-boundary-secret"
HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HISTORY_PATCH_TARGETS = (
    "app.api.history.get_task_history_store",
    "app.services.word.writing_jobs.get_task_history_store",
    "app.services.word.document_review_jobs.get_task_history_store",
    "app.services.word.deterministic_format_review.get_task_history_store",
    "app.services.excel.analysis_jobs.get_task_history_store",
    "app.services.excel.formula_assistant_jobs.get_task_history_store",
    "app.services.excel.smart_fill_jobs.get_task_history_store",
    "app.services.ppt.slide_assistant_jobs.get_task_history_store",
    "app.services.ppt.structure_review_jobs.get_task_history_store",
)


def _catalog_response():
    response = MagicMock()
    payload = {
        "data": [
            {"id": "shared-default"},
            {"id": "write-model"},
            {"id": "review-model"},
        ]
    }
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _assert_no_secret(test_case, payload):
    dumped = json.dumps(payload, ensure_ascii=False)
    test_case.assertNotIn(SECRET_KEY, dumped)


class _OutcomeWorker(object):
    def __init__(self, outcome, result):
        self.outcome = outcome
        self.result = result
        self.started = threading.Event()
        self.release = threading.Event()

    def snapshot_task_auth(self):
        return {
            "serviceName": "企业共享直连",
            "modelName": "shared-default",
            "apiKey": SECRET_KEY,
            "prompt": "用户原始输入不得落盘",
        }

    def _execute(self, *args, **kwargs):
        self.started.set()
        if self.outcome in ("block", "hold"):
            self.release.wait(timeout=5)
            if self.outcome == "block":
                raise LongTaskCancelled(partial_result=None)
        if self.outcome == "fail":
            raise RuntimeError("forced job failure")
        payload = dict(self.result)
        payload["apiKey"] = SECRET_KEY
        payload["prompt"] = "用户原始输入不得落盘"
        return payload

    def smart_write(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def imitate(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def review(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def analyze(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def generate(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def fill_batch(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def assist(self, *args, **kwargs):
        return self._execute(*args, **kwargs)


def _word_payload(job_id, session_id):
    return {
        "documentId": "doc-{0}.docx".format(job_id),
        "documentSessionId": session_id,
        "documentDisplayName": "文档-{0}.docx".format(job_id),
        "clientJobId": job_id,
        "host": "wps",
        "content": {"text": "正文"},
    }


def _analysis_payload(job_id, session_id):
    return {
        "workbookId": "wb-{0}".format(job_id),
        "clientJobId": job_id,
        "documentSessionId": session_id,
        "documentDisplayName": "表-{0}.xlsx".format(job_id),
        "host": "et",
        "scope": {"sheetName": "Sheet1", "address": "A1:C2"},
        "table": {
            "headers": ["项目", "金额"],
            "rows": [["收入", "100"]],
        },
        "options": {"analysisRequirement": "分析趋势"},
    }


def _formula_payload(job_id, session_id):
    return {
        "workbookId": "wb-{0}".format(job_id),
        "clientJobId": job_id,
        "documentSessionId": session_id,
        "documentDisplayName": "公式-{0}.xlsx".format(job_id),
        "host": "et",
        "selection": {"sheetName": "Sheet1", "address": "B2", "value": "100"},
        "options": {"mode": "generate", "requirement": "求和"},
    }


def _smart_fill_payload(job_id, session_id):
    return {
        "workbookId": "wb-{0}".format(job_id),
        "scene": "excel",
        "clientJobId": job_id,
        "documentSessionId": session_id,
        "documentDisplayName": "填写-{0}.xlsx".format(job_id),
        "host": "et",
        "items": [
            {
                "itemId": "sf_{:032x}".format(1),
                "sourceRowIndex": 1,
                "sourceRowLabel": "第 2 行",
            }
        ],
        "source": {
            "sheetName": "Sheet1",
            "address": "A1:C2",
            "snapshotHash": "00000000",
            "headers": ["名称", "说明", "规则"],
            "rows": [["甲", "第一项", "A"]],
            "rowCount": 1,
            "columnCount": 3,
            "truncated": False,
        },
        "userInstruction": "根据来源上下文填写分类。",
    }


def _ppt_slide_payload(job_id, session_id):
    return {
        "presentationId": "ppt-{0}".format(job_id),
        "clientJobId": job_id,
        "documentSessionId": session_id,
        "documentDisplayName": "演示-{0}.pptx".format(job_id),
        "host": "wpp",
        "sourceMode": "slide",
        "slide": {"index": 1, "title": "封面", "textBlocks": ["内容"]},
        "userInstruction": "总结当前页",
    }


def _ppt_structure_payload(job_id, session_id):
    return {
        "presentationId": "ppt-{0}".format(job_id),
        "clientJobId": job_id,
        "documentSessionId": session_id,
        "documentDisplayName": "结构-{0}.pptx".format(job_id),
        "host": "wpp",
        "scope": {"totalSlides": 1, "startSlide": 1, "endSlide": 1},
        "slides": [{"index": 1, "title": "封面", "bodyFallback": "内容"}],
    }


JOB_SPECS = (
    {
        "task_type": "word.smart_write",
        "path": "/word/smart-write/jobs",
        "module": "app.api.word",
        "store_attr": "smart_write_jobs",
        "store_import": ("app.services.word.writing_jobs", "SmartWriteJobStore"),
        "payload": _word_payload,
        "result": {
            "originalText": "正文",
            "rewrittenText": "可归档编写",
            "plainText": "可归档编写",
            "rewriteMode": "smart_write",
        },
        "resume": True,
    },
    {
        "task_type": "word.smart_imitation",
        "path": "/word/smart-imitation/jobs",
        "module": "app.api.word",
        "store_attr": "smart_imitation_jobs",
        "store_import": ("app.services.word.writing_jobs", "SmartImitationJobStore"),
        "payload": _word_payload,
        "result": {
            "originalText": "正文",
            "rewrittenText": "可归档仿写",
            "plainText": "可归档仿写",
            "rewriteMode": "smart_imitation",
        },
        "resume": True,
    },
    {
        "task_type": "word.document_review",
        "path": "/word/document-review/jobs",
        "module": "app.api.word",
        "store_attr": "document_review_jobs",
        "store_import": ("app.services.word.document_review_jobs", "DocumentReviewJobStore"),
        "payload": _word_payload,
        "result": {"summary": "未发现问题", "issues": [], "documentType": "other", "scope": "document"},
        "resume": True,
    },
    {
        "task_type": "excel.analysis",
        "path": "/excel/analysis/jobs",
        "module": "app.api.excel",
        "store_attr": "excel_analysis_jobs",
        "store_import": ("app.services.excel.analysis_jobs", "ExcelAnalysisJobStore"),
        "payload": _analysis_payload,
        "result": {
            "structuredReport": {
                "overview": "趋势良好",
                "findings": ["增长"],
                "risks": [],
                "actions": [],
            },
            "plainText": "可归档分析",
        },
        "resume": True,
    },
    {
        "task_type": "excel.formula_assistant",
        "path": "/excel/formula-assistant/jobs",
        "module": "app.api.excel",
        "store_attr": "excel_formula_assistant_jobs",
        "store_import": ("app.services.excel.formula_assistant_jobs", "ExcelFormulaAssistantJobStore"),
        "payload": _formula_payload,
        "result": {
            "primaryFormula": "=SUM(B2:B10)",
            "copyText": "=SUM(B2:B10)",
            "explanation": "求和",
            "issues": [],
        },
        "resume": True,
    },
    {
        "task_type": "excel.smart_fill",
        "path": "/excel/smart-fill/jobs",
        "module": "app.api.excel",
        "store_attr": "excel_smart_fill_jobs",
        "store_import": ("app.services.excel.smart_fill_jobs", "ExcelSmartFillJobStore"),
        "payload": _smart_fill_payload,
        "result": {
            "schemaVersion": "excel.smart_fill.v2",
            "items": [
                {
                    "itemId": "sf_{:032x}".format(1),
                    "status": "completed",
                    "valueType": "text",
                    "value": "合成标签",
                    "sourceRowIndex": 1,
                }
            ],
            "processedItemCount": 1,
            "provider": "test",
        },
        "resume": True,
    },
    {
        "task_type": "ppt.slide_assistant",
        "path": "/ppt/slide-assistant/jobs",
        "module": "app.api.ppt",
        "store_attr": "ppt_slide_jobs",
        "store_import": ("app.services.ppt.slide_assistant_jobs", "PptSlideAssistantJobStore"),
        "payload": _ppt_slide_payload,
        "result": {"summary": "可归档总结", "plainText": "可归档总结", "actionItems": [], "bulletPoints": []},
        "resume": True,
    },
    {
        "task_type": "ppt.structure_review",
        "path": "/ppt/structure-review/jobs",
        "module": "app.api.ppt",
        "store_attr": "ppt_structure_review_jobs",
        "store_import": ("app.services.ppt.structure_review_jobs", "PptStructureReviewJobStore"),
        "payload": _ppt_structure_payload,
        "result": {
            "reviewedRange": {"startSlide": 1, "endSlide": 1},
            "overallStoryline": "结构清楚",
            "reviewConclusion": "可归档审查",
            "highPriorityIssues": [],
            "generalSuggestions": [],
            "slideRecommendations": [],
        },
        "resume": True,
    },
)


class Issue182PublicBoundaryTests(unittest.TestCase):
    def test_spec_nine_tasks_are_hardcoded_and_match_runtime(self):
        self.assertTrue(set(SPEC_NINE_TASKS).issubset(SUPPORTED_WORKFLOW_TASKS))
        self.assertEqual(len(SPEC_NINE_TASKS), 9)
        self.assertEqual(len(set(SPEC_NINE_TASKS)), 9)


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for public boundary API tests")
class Issue182PublicApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.key_dir = root / "provider_api_keys"
        self.history_dir = root / "history"
        from app.services.direct_services import DirectServiceStore
        from app.services.model_configurations import ModelConfigurationStore

        self.direct = DirectServiceStore(self.config_path, self.key_dir)
        self.models = ModelConfigurationStore(self.config_path, self.key_dir)
        self.history = TaskHistoryStore(self.history_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app)

    def _patch_provider_stores(self):
        return (
            patch("app.api.provider.get_direct_service_store", return_value=self.direct),
            patch("app.api.provider.get_model_configuration_store", return_value=self.models),
            patch("urllib.request.urlopen", return_value=_catalog_response()),
        )

    def test_shared_service_public_api_binds_all_nine_tasks_without_touching_workflow(self):
        self.assertTrue(set(SPEC_NINE_TASKS).issubset(SUPPORTED_WORKFLOW_TASKS))
        patches = self._patch_provider_stores()
        for item in patches:
            item.start()
        try:
            client = self._client()
            workflow = client.post(
                "/provider/model-configurations",
                json={
                    "taskType": "word.smart_write",
                    "name": "编写工作流",
                    "accessMethod": "workflow_platform",
                    "serviceBaseUrl": "https://workflow.example.test/v1",
                },
            )
            self.assertEqual(workflow.status_code, 200, workflow.text)
            _assert_no_secret(self, workflow.json())
            workflow_id = workflow.json()["data"]["configuration"]["id"]
            workflow_url = workflow.json()["data"]["configuration"]["serviceBaseUrl"]

            created = client.post(
                "/provider/direct-services",
                json={
                    "name": "企业共享直连",
                    "serviceBaseUrl": "https://llm.example.test/v1",
                    "defaultModel": "shared-default",
                    "apiKey": SECRET_KEY,
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            _assert_no_secret(self, created.json())
            service = created.json()["data"]["directService"]
            service_id = service["id"]
            revision = int(service["revision"])

            replaced = client.post(
                "/provider/direct-services/{0}/api-key".format(service_id),
                json={"apiKey": SECRET_KEY, "expectedRevision": revision},
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            _assert_no_secret(self, replaced.json())
            revision = int(replaced.json()["data"]["directService"]["revision"])

            refreshed = client.post(
                "/provider/direct-services/{0}/refresh-models".format(service_id),
                json={"expectedRevision": revision},
            )
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            _assert_no_secret(self, refreshed.json())
            self.assertIn("shared-default", refreshed.json()["data"]["models"])
            revision = int(refreshed.json()["data"]["directService"]["revision"])

            overrides = {
                "word.smart_write": "write-model",
                "word.document_review": "review-model",
            }
            for task_type in SPEC_NINE_TASKS:
                activated = client.post(
                    "/provider/direct-services/{0}/activate".format(service_id),
                    json={
                        "taskType": task_type,
                        "taskModelSelection": {
                            "serviceId": service_id,
                            "modelName": overrides.get(task_type, ""),
                        },
                    },
                )
                self.assertEqual(activated.status_code, 200, activated.text)
                _assert_no_secret(self, activated.json())
                selection = activated.json()["data"]["taskModelSelection"]
                self.assertEqual(selection["serviceId"], service_id)
                expected_model = overrides.get(task_type) or "shared-default"
                self.assertEqual(selection["effectiveModel"], expected_model)

                queried = client.get("/provider/task-model-selections/{0}".format(task_type))
                self.assertEqual(queried.status_code, 200, queried.text)
                _assert_no_secret(self, queried.json())
                self.assertEqual(
                    queried.json()["data"]["taskModelSelection"]["effectiveModel"],
                    expected_model,
                )

            stale = client.post(
                "/provider/direct-services/{0}/api-key".format(service_id),
                json={"apiKey": SECRET_KEY, "expectedRevision": max(revision - 1, 1) if revision > 1 else 999},
            )
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(
                stale.json()["errors"][0]["code"],
                "DIRECT_SERVICE_REVISION_CONFLICT",
            )
            _assert_no_secret(self, stale.json())

            listed = client.get("/provider/model-configurations?taskType=word.smart_write")
            self.assertEqual(listed.status_code, 200, listed.text)
            remaining = [
                item
                for item in listed.json()["data"]["configurations"]
                if item.get("id") == workflow_id
            ]
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["accessMethod"], "workflow_platform")
            self.assertEqual(remaining[0]["serviceBaseUrl"], workflow_url)

            current = client.get("/provider/direct-services/{0}".format(service_id))
            self.assertEqual(current.status_code, 200, current.text)
            current_revision = int(current.json()["data"]["directService"]["revision"])
            deleted = client.delete(
                "/provider/direct-services/{0}".format(service_id),
                params={"expectedRevision": current_revision},
            )
            self.assertEqual(deleted.status_code, 409, deleted.text)
            self.assertEqual(deleted.json()["errors"][0]["code"], "DIRECT_SERVICE_IN_USE")
            _assert_no_secret(self, deleted.json())
        finally:
            for item in reversed(patches):
                item.stop()

    def test_history_archives_success_only_via_public_job_and_history_api(self):
        self.assertTrue(set(SPEC_NINE_TASKS).issubset(SUPPORTED_WORKFLOW_TASKS))
        covered = [spec["task_type"] for spec in JOB_SPECS]
        self.assertEqual(
            set(covered) | {"word.format_review"},
            set(SPEC_NINE_TASKS),
        )

        history_patches = [patch(target, return_value=self.history) for target in HISTORY_PATCH_TARGETS]
        for item in history_patches:
            item.start()
        originals = []
        client = self._client()
        try:
            for spec in JOB_SPECS:
                module = __import__(spec["module"], fromlist=[spec["store_attr"]])
                store_module = __import__(spec["store_import"][0], fromlist=[spec["store_import"][1]])
                store_cls = getattr(store_module, spec["store_import"][1])
                originals.append((module, spec["store_attr"], getattr(module, spec["store_attr"])))

                fail_worker = _OutcomeWorker("fail", spec["result"])
                hold_worker = _OutcomeWorker("hold", spec["result"])
                success_store = store_cls(hold_worker, LongTaskCoordinator())
                setattr(module, spec["store_attr"], success_store)

                success_id = "ok-{0}".format(spec["task_type"].replace(".", "-"))
                posted = client.post(
                    spec["path"],
                    json=spec["payload"](success_id, "session-{0}-ok".format(spec["task_type"])),
                )
                self.assertEqual(posted.status_code, 200, posted.text)
                duplicate = client.post(
                    spec["path"],
                    json=spec["payload"](success_id, "session-{0}-ok".format(spec["task_type"])),
                )
                self.assertEqual(duplicate.status_code, 200, duplicate.text)
                self.assertTrue(hold_worker.started.wait(timeout=2), spec["task_type"])
                try:
                    resumed = client.get("{0}/{1}?resume=1".format(spec["path"], success_id))
                    self.assertEqual(resumed.status_code, 200, resumed.text)
                    self.assertIn(
                        resumed.json()["data"]["status"],
                        ("queued", "running"),
                        spec["task_type"],
                    )
                finally:
                    hold_worker.release.set()
                completed = success_store.coordinator.wait(success_id, task_type=spec["task_type"])
                self.assertEqual(completed["status"], "completed", spec["task_type"])

                fail_store = store_cls(fail_worker, LongTaskCoordinator())
                setattr(module, spec["store_attr"], fail_store)
                fail_id = "fail-{0}".format(spec["task_type"].replace(".", "-"))
                failed_post = client.post(
                    spec["path"],
                    json=spec["payload"](fail_id, "session-{0}-fail".format(spec["task_type"])),
                )
                self.assertEqual(failed_post.status_code, 200, failed_post.text)
                failed = fail_store.coordinator.wait(fail_id, task_type=spec["task_type"])
                self.assertEqual(failed["status"], "failed", spec["task_type"])

                blocker = _OutcomeWorker("block", spec["result"])
                cancel_store = store_cls(blocker, LongTaskCoordinator(max_running=1, max_queued=4))
                setattr(module, spec["store_attr"], cancel_store)
                blocker_id = "block-{0}".format(spec["task_type"].replace(".", "-"))
                cancel_id = "cancel-{0}".format(spec["task_type"].replace(".", "-"))
                occupy = client.post(
                    spec["path"],
                    json=spec["payload"](blocker_id, "session-{0}-block".format(spec["task_type"])),
                )
                self.assertEqual(occupy.status_code, 200, occupy.text)
                self.assertTrue(blocker.started.wait(timeout=2), spec["task_type"])
                try:
                    cancel_post = client.post(
                        spec["path"],
                        json=spec["payload"](cancel_id, "session-{0}-cancel".format(spec["task_type"])),
                    )
                    self.assertEqual(cancel_post.status_code, 200, cancel_post.text)
                    self.assertEqual(cancel_post.json()["data"]["status"], "queued", spec["task_type"])
                    cancelled_req = client.delete("{0}/{1}".format(spec["path"], cancel_id))
                    self.assertEqual(cancelled_req.status_code, 200, cancelled_req.text)
                    cancelled = cancel_store.coordinator.wait(cancel_id, task_type=spec["task_type"])
                    self.assertEqual(cancelled["status"], "cancelled", spec["task_type"])
                finally:
                    blocker.release.set()
                    cancel_store.coordinator.wait(blocker_id, task_type=spec["task_type"])

            listed_before_restart = {}
            with patch("app.api.history.get_task_history_store", return_value=self.history):
                for spec in JOB_SPECS:
                    listed = client.get("/history?taskType={0}".format(spec["task_type"]))
                    self.assertEqual(listed.status_code, 200, listed.text)
                    _assert_no_secret(self, listed.json())
                    items = listed.json()["data"]["items"]
                    self.assertEqual(len(items), 1, spec["task_type"])
                    self.assertEqual(
                        items[0]["jobId"],
                        "ok-{0}".format(spec["task_type"].replace(".", "-")),
                    )
                    listed_before_restart[spec["task_type"]] = items[0]

            restarted = TaskHistoryStore(self.history_dir)
            with patch("app.api.history.get_task_history_store", return_value=restarted):
                seen_ids = []
                for spec in JOB_SPECS:
                    listed = client.get("/history?taskType={0}".format(spec["task_type"]))
                    self.assertEqual(listed.status_code, 200, listed.text)
                    _assert_no_secret(self, listed.json())
                    items = listed.json()["data"]["items"]
                    self.assertEqual(len(items), 1, spec["task_type"])
                    success_job_id = "ok-{0}".format(spec["task_type"].replace(".", "-"))
                    self.assertEqual(items[0]["jobId"], success_job_id, spec["task_type"])
                    self.assertEqual(
                        items[0]["id"],
                        listed_before_restart[spec["task_type"]]["id"],
                        spec["task_type"],
                    )
                    job_ids = [item["jobId"] for item in items]
                    self.assertEqual(job_ids, [success_job_id], spec["task_type"])
                    for item in items:
                        self.assertFalse(str(item["jobId"]).startswith("fail-"), spec["task_type"])
                        self.assertFalse(str(item["jobId"]).startswith("cancel-"), spec["task_type"])
                        self.assertFalse(str(item["jobId"]).startswith("block-"), spec["task_type"])
                    seen_ids.append(items[0]["id"])
                self.assertEqual(len(seen_ids), len(set(seen_ids)))

                success_id = listed_before_restart["excel.analysis"]["id"]
                detail = client.get("/history/{0}".format(success_id))
                self.assertEqual(detail.status_code, 200, detail.text)
                _assert_no_secret(self, detail.json())
                self.assertIn("plainText", json.dumps(detail.json(), ensure_ascii=False))

                deleted = client.delete("/history/{0}".format(success_id))
                self.assertEqual(deleted.status_code, 200, deleted.text)
                remaining = client.get("/history?taskType=excel.analysis")
                self.assertEqual(remaining.json()["data"]["total"], 0)
                other = client.get("/history?taskType=excel.smart_fill")
                self.assertEqual(other.json()["data"]["total"], 1)

                cleared = client.delete("/history?taskType=ppt.slide_assistant")
                self.assertEqual(cleared.status_code, 200, cleared.text)
                self.assertEqual(cleared.json()["data"]["clearedCount"], 1)
                self.assertEqual(client.get("/history?taskType=ppt.slide_assistant").json()["data"]["total"], 0)
                self.assertEqual(client.get("/history?taskType=ppt.structure_review").json()["data"]["total"], 1)
        finally:
            for module, attr, original in originals:
                setattr(module, attr, original)
            for item in reversed(history_patches):
                item.stop()

    def _commit_format_snapshot(self, service, doc_id, session_id, display_name):
        identity = {
            "documentIdSha256": "doc-sha-{0}".format(doc_id),
            "hostDocumentId": doc_id,
        }
        session = service.create_snapshot(
            {
                "documentId": doc_id,
                "selectionMode": "document",
                "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                "formatFactSchemaVersion": "format_snapshot.v2",
                "documentIdentity": identity,
                "editSequence": "1",
                "documentSessionId": session_id,
                "documentDisplayName": display_name,
                "host": "wps",
            }
        )
        blocks = service._normalize_format_blocks(
            [
                {
                    "blockId": "format-p-1",
                    "blockType": "heading",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "headingLevel": 3,
                    "text": "测试标题",
                    "format": {
                        "styleName": "Heading 3",
                        "fontName": "黑体",
                        "fontSize": 16,
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
                "characterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": metrics["structureSha256"],
                "formatSha256": metrics["formatSha256"],
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
        return service.commit_snapshot(
            session["snapshotId"],
            {
                "uploadToken": session["uploadToken"],
                "batchCount": 1,
                "blockCount": 1,
                "reviewCharacterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": metrics["structureSha256"],
                "formatSha256": metrics["formatSha256"],
                "coverage": metrics["coverage"],
                "verification": verification,
            },
        )

    def test_format_review_public_job_api_archives_success_only(self):
        from app.api import word as word_api
        from app.services.word.deterministic_format_review import DeterministicFormatReviewService

        format_result = {
            "summary": {
                "scope": "document",
                "templateId": "technical-document-template-rules",
                "provider": "local",
                "semanticStatus": "not_needed",
                "executionStatus": "completed",
                "complianceStatus": "violations_found",
                "coverageStatus": "complete",
            },
            "issues": [],
        }
        history_patches = [patch(target, return_value=self.history) for target in HISTORY_PATCH_TARGETS]
        for item in history_patches:
            item.start()
        original = word_api.deterministic_format_review_service
        env_patch = patch.dict(os.environ, {"AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW": "1"})
        env_patch.start()
        client = self._client()
        try:
            hold_worker = _OutcomeWorker("hold", format_result)
            service = DeterministicFormatReviewService(
                staging_root=Path(self.tmp.name) / "format-staging",
                reviewer=hold_worker,
                coordinator=LongTaskCoordinator(),
            )
            word_api.deterministic_format_review_service = service
            committed = self._commit_format_snapshot(
                service, "format-ok.docx", "session-format-ok", "格式.docx"
            )
            posted = client.post(
                "/word/format-review/jobs",
                json={
                    "snapshotId": committed["snapshotId"],
                    "snapshotToken": committed["snapshotToken"],
                    "clientJobId": "ok-word-format-review",
                    "documentSessionId": "session-format-ok",
                    "documentDisplayName": "格式.docx",
                    "host": "wps",
                },
            )
            self.assertEqual(posted.status_code, 200, posted.text)
            self.assertTrue(hold_worker.started.wait(timeout=2))
            try:
                resumed = client.get("/word/format-review/jobs/ok-word-format-review")
                self.assertEqual(resumed.status_code, 200, resumed.text)
                self.assertIn(resumed.json()["data"]["status"], ("queued", "running"))
            finally:
                hold_worker.release.set()
            completed = service.coordinator.wait(
                "ok-word-format-review", task_type="word.format_review.deterministic"
            )
            self.assertEqual(completed["status"], "completed")
            resumed_done = client.get("/word/format-review/jobs/ok-word-format-review")
            self.assertEqual(resumed_done.status_code, 200, resumed_done.text)
            self.assertEqual(resumed_done.json()["data"]["status"], "completed")

            fail_worker = _OutcomeWorker("fail", {})
            fail_service = DeterministicFormatReviewService(
                staging_root=Path(self.tmp.name) / "format-staging-fail",
                reviewer=fail_worker,
                coordinator=LongTaskCoordinator(),
            )
            word_api.deterministic_format_review_service = fail_service
            fail_committed = self._commit_format_snapshot(
                fail_service, "format-fail.docx", "session-format-fail", "失败.docx"
            )
            failed_post = client.post(
                "/word/format-review/jobs",
                json={
                    "snapshotId": fail_committed["snapshotId"],
                    "snapshotToken": fail_committed["snapshotToken"],
                    "clientJobId": "fail-word-format-review",
                    "documentSessionId": "session-format-fail",
                    "host": "wps",
                },
            )
            self.assertEqual(failed_post.status_code, 200, failed_post.text)
            failed = fail_service.coordinator.wait(
                "fail-word-format-review", task_type="word.format_review.deterministic"
            )
            self.assertEqual(failed["status"], "failed")

            blocker = _OutcomeWorker("block", format_result)
            cancel_service = DeterministicFormatReviewService(
                staging_root=Path(self.tmp.name) / "format-staging-cancel",
                reviewer=blocker,
                coordinator=LongTaskCoordinator(max_running=1, max_queued=4),
            )
            word_api.deterministic_format_review_service = cancel_service
            block_committed = self._commit_format_snapshot(
                cancel_service, "format-block.docx", "session-format-block", "占用.docx"
            )
            cancel_committed = self._commit_format_snapshot(
                cancel_service, "format-cancel.docx", "session-format-cancel", "取消.docx"
            )
            occupy = client.post(
                "/word/format-review/jobs",
                json={
                    "snapshotId": block_committed["snapshotId"],
                    "snapshotToken": block_committed["snapshotToken"],
                    "clientJobId": "block-word-format-review",
                    "documentSessionId": "session-format-block",
                    "host": "wps",
                },
            )
            self.assertEqual(occupy.status_code, 200, occupy.text)
            self.assertTrue(blocker.started.wait(timeout=2))
            try:
                cancel_post = client.post(
                    "/word/format-review/jobs",
                    json={
                        "snapshotId": cancel_committed["snapshotId"],
                        "snapshotToken": cancel_committed["snapshotToken"],
                        "clientJobId": "cancel-word-format-review",
                        "documentSessionId": "session-format-cancel",
                        "host": "wps",
                    },
                )
                self.assertEqual(cancel_post.status_code, 200, cancel_post.text)
                self.assertEqual(cancel_post.json()["data"]["status"], "queued")
                cancelled_req = client.delete("/word/format-review/jobs/cancel-word-format-review")
                self.assertEqual(cancelled_req.status_code, 200, cancelled_req.text)
                cancelled = cancel_service.coordinator.wait(
                    "cancel-word-format-review",
                    task_type="word.format_review.deterministic",
                )
                self.assertEqual(cancelled["status"], "cancelled")
            finally:
                blocker.release.set()
                cancel_service.coordinator.wait(
                    "block-word-format-review",
                    task_type="word.format_review.deterministic",
                )

            with patch("app.api.history.get_task_history_store", return_value=self.history):
                listed = client.get("/history?taskType=word.format_review")
            self.assertEqual(listed.status_code, 200, listed.text)
            _assert_no_secret(self, listed.json())
            items = listed.json()["data"]["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["jobId"], "ok-word-format-review")
            history_id = items[0]["id"]

            restarted = TaskHistoryStore(self.history_dir)
            with patch("app.api.history.get_task_history_store", return_value=restarted):
                listed_after = client.get("/history?taskType=word.format_review")
                self.assertEqual(listed_after.status_code, 200, listed_after.text)
                _assert_no_secret(self, listed_after.json())
                after_items = listed_after.json()["data"]["items"]
                self.assertEqual(len(after_items), 1)
                self.assertEqual(after_items[0]["jobId"], "ok-word-format-review")
                self.assertEqual(after_items[0]["id"], history_id)
                self.assertEqual(
                    [item["jobId"] for item in after_items],
                    ["ok-word-format-review"],
                )
                for item in after_items:
                    self.assertFalse(str(item["jobId"]).startswith("fail-"))
                    self.assertFalse(str(item["jobId"]).startswith("cancel-"))
                    self.assertFalse(str(item["jobId"]).startswith("block-"))
                detail = client.get("/history/{0}".format(history_id))
                self.assertEqual(detail.status_code, 200, detail.text)
                _assert_no_secret(self, detail.json())
        finally:
            env_patch.stop()
            word_api.deterministic_format_review_service = original
            for item in reversed(history_patches):
                item.stop()


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone public boundary tests")
class Issue182StandalonePublicBoundaryTests(unittest.TestCase):
    def setUp(self):
        import standalone_adapter
        from app.services.direct_services import DirectServiceStore
        from app.services.model_configurations import ModelConfigurationStore

        self.standalone = standalone_adapter
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.key_dir = root / "keys"
        self.key_dir.mkdir()
        self.history_dir = root / "history"
        self.history = TaskHistoryStore(self.history_dir)
        self._orig_direct = standalone_adapter.DirectServiceStore
        self._orig_models = standalone_adapter.ModelConfigurationStore
        standalone_adapter.DirectServiceStore = lambda: DirectServiceStore(
            config_path=self.config_path, api_key_dir=self.key_dir
        )
        standalone_adapter.ModelConfigurationStore = lambda: ModelConfigurationStore(
            config_path=self.config_path, key_dir=self.key_dir
        )

    def tearDown(self):
        self.standalone.DirectServiceStore = self._orig_direct
        self.standalone.ModelConfigurationStore = self._orig_models
        self.tmp.cleanup()

    def _invoke(self, method, path, body=None):
        writes = []
        handler = object.__new__(self.standalone.Handler)
        handler.path = path
        handler.command = method
        handler.requestline = "{0} {1} HTTP/1.1".format(method, path)
        handler.request_version = "HTTP/1.1"
        raw = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler.close_connection = False
        handler._reject_operation_block = lambda m, p: False
        handler._reject_writing_policy_route_or_method = lambda m, p: False
        handler.send_error = lambda code, message=None: writes.append((code, {"message": message}))
        handler._write = lambda status, payload: writes.append((status, payload))
        handler._write_bytes = lambda status, payload, headers=None: writes.append(
            (status, json.loads(payload.decode("utf-8")) if payload else {})
        )
        getattr(handler, method)()
        status, resp_body = writes[-1] if writes else (None, None)
        return {"status": status, "body": resp_body}

    def test_standalone_shared_service_binds_all_nine_tasks(self):
        self.assertTrue(set(SPEC_NINE_TASKS).issubset(SUPPORTED_WORKFLOW_TASKS))
        with patch("urllib.request.urlopen", return_value=_catalog_response()):
            created = self._invoke(
                "do_POST",
                "/provider/direct-services",
                {
                    "name": "企业共享直连",
                    "serviceBaseUrl": "https://llm.example.test/v1",
                    "defaultModel": "shared-default",
                    "apiKey": SECRET_KEY,
                },
            )
            self.assertEqual(created["status"], 200, created)
            _assert_no_secret(self, created["body"])
            service_id = created["body"]["data"]["directService"]["id"]
            revision = int(created["body"]["data"]["directService"]["revision"])

            replaced = self._invoke(
                "do_POST",
                "/provider/direct-services/{0}/api-key".format(service_id),
                {"apiKey": SECRET_KEY, "expectedRevision": revision},
            )
            self.assertEqual(replaced["status"], 200, replaced)
            revision = int(replaced["body"]["data"]["directService"]["revision"])

            refreshed = self._invoke(
                "do_POST",
                "/provider/direct-services/{0}/refresh-models".format(service_id),
                {"expectedRevision": revision},
            )
            self.assertEqual(refreshed["status"], 200, refreshed)
            _assert_no_secret(self, refreshed["body"])

            for task_type in SPEC_NINE_TASKS:
                activated = self._invoke(
                    "do_POST",
                    "/provider/direct-services/{0}/activate".format(service_id),
                    {"taskType": task_type, "taskModelSelection": {"serviceId": service_id, "modelName": ""}},
                )
                self.assertEqual(activated["status"], 200, activated)
                _assert_no_secret(self, activated["body"])
                queried = self._invoke("do_GET", "/provider/task-model-selections/{0}".format(task_type))
                self.assertEqual(queried["status"], 200, queried)
                self.assertEqual(
                    queried["body"]["data"]["taskModelSelection"]["serviceId"],
                    service_id,
                )

            current = self._invoke("do_GET", "/provider/direct-services/{0}".format(service_id))
            current_revision = int(current["body"]["data"]["directService"]["revision"])
            deleted = self._invoke(
                "do_DELETE",
                "/provider/direct-services/{0}?expectedRevision={1}".format(service_id, current_revision),
            )
            self.assertEqual(deleted["status"], 409, deleted)
            self.assertEqual(deleted["body"]["errors"][0]["code"], "DIRECT_SERVICE_IN_USE")

    def test_standalone_history_api_reads_restarted_store_without_secrets(self):
        self.history.record_success(
            task_type="word.format_review",
            job_id="ok-word-format-review",
            result={"reportType": "format_review", "plainText": "可归档摘要", "apiKey": SECRET_KEY},
            document_display_name="格式.docx",
            service_name="企业共享直连",
            model_name="shared-default",
        )
        restarted = TaskHistoryStore(self.history_dir)
        with patch.object(self.standalone, "get_task_history_store", return_value=restarted):
            listed = self._invoke("do_GET", "/history?taskType=word.format_review")
        self.assertEqual(listed["status"], 200, listed)
        _assert_no_secret(self, listed["body"])
        self.assertEqual(listed["body"]["data"]["total"], 1)
        self.assertEqual(listed["body"]["data"]["items"][0]["jobId"], "ok-word-format-review")


if __name__ == "__main__":
    unittest.main()
