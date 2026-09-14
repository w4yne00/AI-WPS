# -*- coding: utf-8 -*-
"""Issue #182：九类任务在公开存储合同上共享直连服务，并遵守历史/安全边界。"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.direct_services import DirectServiceError, DirectServiceStore
from app.services.model_configurations import (
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationStore,
)
from app.services.task_history import TaskHistoryError, TaskHistoryStore
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


NINE_TASKS = SUPPORTED_WORKFLOW_TASKS
SECRET_KEY = "sk-issue182-secret-key"
SENSITIVE_RESULT = {
    "plainText": "可归档输出",
    "apiKey": SECRET_KEY,
    "api_key": SECRET_KEY,
    "prompt": "用户原始输入不得落盘",
    "userInstruction": "机密指令",
    "fullPath": "/Users/someone/secret/report.docx",
    "requestBody": {"headers": {"Authorization": "Bearer {0}".format(SECRET_KEY)}},
}


class Issue182PublicBoundaryTests(unittest.TestCase):
    def test_one_shared_service_binds_all_nine_tasks_without_touching_workflow(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            key_dir = root / "provider_api_keys"
            direct = DirectServiceStore(config_path, key_dir)
            models = ModelConfigurationStore(config_path, key_dir)

            workflow = models.create_configuration(
                task_type="word.smart_write",
                name="编写工作流",
                access_method=ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://workflow.example.test/v1",
            )
            self.assertEqual(workflow["accessMethod"], ACCESS_WORKFLOW_PLATFORM)
            workflow_id = workflow["id"]
            workflow_url = workflow["serviceBaseUrl"]

            service = direct.create_service(
                name="企业共享直连",
                service_base_url="https://llm.example.test/v1",
                default_model="shared-default",
            )
            service_id = service["id"]
            direct.replace_api_key(service_id, SECRET_KEY, expected_revision=1)
            direct.update_model_list(
                service_id,
                ["shared-default", "write-model", "review-model"],
                expected_revision=2,
                trusted=True,
            )

            overrides = {
                "word.smart_write": "write-model",
                "word.document_review": "review-model",
            }
            for task_type in NINE_TASKS:
                activated = direct.activate_direct_service(
                    service_id,
                    task_type,
                    task_model_selection={
                        "serviceId": service_id,
                        "modelName": overrides.get(task_type, ""),
                    },
                )
                selection = activated.get("taskModelSelection") or direct.get_task_model_selection(
                    task_type
                )
                self.assertEqual(selection["serviceId"], service_id)
                expected_model = overrides.get(task_type) or "shared-default"
                self.assertEqual(selection["effectiveModel"], expected_model)

            listed = models.list_for_task("word.smart_write")
            workflow_after = [
                item
                for item in listed.get("configurations", [])
                if item.get("id") == workflow_id
            ]
            self.assertEqual(len(workflow_after), 1)
            self.assertEqual(workflow_after[0]["accessMethod"], ACCESS_WORKFLOW_PLATFORM)
            self.assertEqual(workflow_after[0]["serviceBaseUrl"], workflow_url)

            raw = config_path.read_text(encoding="utf-8")
            self.assertNotIn(SECRET_KEY, raw)
            key_files = list(key_dir.glob("*"))
            self.assertTrue(key_files)
            self.assertTrue(any(SECRET_KEY in path.read_text(encoding="utf-8") for path in key_files))

            current = direct.get_service(service_id)
            with self.assertRaises(DirectServiceError) as ctx:
                direct.delete_service(service_id, expected_revision=int(current["revision"]))
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")

    def test_history_archives_success_only_for_nine_tasks_and_strips_secrets(self):
        with TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / "history"
            store = TaskHistoryStore(history_dir)
            ids = {}
            for index, task_type in enumerate(NINE_TASKS):
                entry = store.record_success(
                    task_type=task_type,
                    job_id="job-{0}".format(index),
                    result=dict(SENSITIVE_RESULT),
                    document_display_name="文档{0}.docx".format(index),
                    service_name="企业共享直连",
                    model_name="shared-default",
                )
                ids[task_type] = entry["id"]

            for task_type in NINE_TASKS:
                items = store.list_history(task_type)
                self.assertEqual(len(items), 1, task_type)
                self.assertEqual(items[0]["id"], ids[task_type])
                raw = (history_dir / task_type / "{0}.json".format(items[0]["id"])).read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(SECRET_KEY, raw)
                self.assertNotIn("/Users/someone/secret", raw)
                self.assertNotIn("Authorization", raw)
                self.assertNotIn("用户原始输入不得落盘", raw)

            deleted = store.delete_history(ids["excel.analysis"])
            self.assertTrue(deleted)
            self.assertEqual(store.list_history("excel.analysis"), [])
            self.assertEqual(len(store.list_history("excel.smart_fill")), 1)

            cleared = store.clear_history("ppt.slide_assistant")
            self.assertEqual(cleared, 1)
            self.assertEqual(store.list_history("ppt.slide_assistant"), [])
            self.assertEqual(len(store.list_history("ppt.structure_review")), 1)

            huge = "x" * (5 * 1024 * 1024 + 64)
            with self.assertRaises(TaskHistoryError) as ctx:
                store.record_success(
                    task_type="word.smart_write",
                    job_id="job-too-large",
                    result={"plainText": huge},
                    document_display_name="huge.docx",
                    service_name="企业共享直连",
                    model_name="shared-default",
                )
            self.assertEqual(ctx.exception.code, "HISTORY_ENTRY_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
