import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.task_history import (
    MAX_HISTORY_ENTRIES_PER_TASK,
    MAX_HISTORY_ENTRY_BYTES,
    MAX_TOTAL_HISTORY_BYTES,
    TaskHistoryError,
    TaskHistoryStore,
    sanitize_audit_for_history,
    sanitize_usage_for_history,
)


class TaskHistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()
        self.history_dir = Path(self.tmp_dir.name) / "history"
        self.store = TaskHistoryStore(self.history_dir)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_record_and_list_history(self) -> None:
        result_payload = {
            "resultType": "slide",
            "suggestedTitle": "测试幻灯片总结",
            "bullets": ["要点一", "要点二"],
            "conclusion": "测试结论",
            "plainText": "测试纯文本",
        }
        entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-test-001",
            result=result_payload,
            document_display_name="汇报材料.pptx",
            service_name="企业大模型",
            model_name="qwen-max",
        )
        self.assertTrue(entry["id"].startswith("hist_"))
        self.assertEqual(entry["taskType"], "ppt.slide_assistant")
        self.assertEqual(entry["jobId"], "job-test-001")
        self.assertEqual(entry["documentDisplayName"], "汇报材料.pptx")
        self.assertEqual(entry["serviceName"], "企业大模型")
        self.assertEqual(entry["modelName"], "qwen-max")
        self.assertEqual(entry["result"], result_payload)
        self.assertIn("completedAt", entry)

        items = self.store.list_history("ppt.slide_assistant")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], entry["id"])

    def test_sanitization_no_sensitive_fields_persisted(self) -> None:
        result_payload = {
            "resultType": "slide",
            "suggestedTitle": "总结",
            "apiKey": "sk-secret-123456",
            "api_key": "sk-secret-123456",
            "fullPath": "/Users/someone/secret/docs/plan.docx",
            "rawInput": "用户机密输入正文...",
            "requestBody": {"headers": {"Authorization": "Bearer secret"}},
        }
        entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-test-002",
            result=result_payload,
            document_display_name="方案.pptx",
            service_name="网关",
            model_name="glm-4",
        )
        entry_file = self.history_dir / "ppt.slide_assistant" / f"{entry['id']}.json"
        self.assertTrue(entry_file.exists())
        raw_text = entry_file.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-123456", raw_text)
        self.assertNotIn("/Users/someone/secret", raw_text)
        self.assertNotIn("Authorization", raw_text)

    def test_directory_and_file_permissions(self) -> None:
        entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-test-perm",
            result={"resultType": "slide", "suggestedTitle": "安全测试"},
            document_display_name="安全.pptx",
            service_name="网关",
            model_name="model-1",
        )
        task_dir = self.history_dir / "ppt.slide_assistant"
        entry_file = task_dir / f"{entry['id']}.json"
        dir_mode = stat.S_IMODE(os.stat(task_dir).st_mode)
        file_mode = stat.S_IMODE(os.stat(entry_file).st_mode)
        self.assertEqual(dir_mode & 0o777, 0o700)
        self.assertEqual(file_mode & 0o777, 0o600)

    def test_per_task_limit_20_evicts_oldest(self) -> None:
        base_time = datetime.now(timezone.utc) - timedelta(hours=5)
        for i in range(25):
            t = (base_time + timedelta(minutes=i)).isoformat()
            self.store.record_success(
                task_type="ppt.slide_assistant",
                job_id=f"job-{i}",
                result={"index": i},
                document_display_name=f"doc-{i}.pptx",
                service_name="svc",
                model_name="m1",
                completed_at=t,
            )
        items = self.store.list_history("ppt.slide_assistant")
        self.assertEqual(len(items), MAX_HISTORY_ENTRIES_PER_TASK)
        indices = [it["result"]["index"] for it in items]
        self.assertNotIn(0, indices)
        self.assertNotIn(4, indices)
        self.assertIn(5, indices)
        self.assertIn(24, indices)
        self.assertEqual(indices[0], 24)

    def test_ttl_24_hours_eviction(self) -> None:
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        fresh_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        old_entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-old",
            result={"text": "old"},
            document_display_name="old.pptx",
            service_name="svc",
            model_name="m1",
            completed_at=old_time,
        )
        fresh_entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-fresh",
            result={"text": "fresh"},
            document_display_name="fresh.pptx",
            service_name="svc",
            model_name="m1",
            completed_at=fresh_time,
        )
        items = self.store.list_history("ppt.slide_assistant")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], fresh_entry["id"])

    def test_single_item_5mib_limit_rejected(self) -> None:
        large_text = "x" * (MAX_HISTORY_ENTRY_BYTES + 1024)
        with self.assertRaises(TaskHistoryError) as ctx:
            self.store.record_success(
                task_type="ppt.slide_assistant",
                job_id="job-huge",
                result={"large": large_text},
                document_display_name="large.pptx",
                service_name="svc",
                model_name="m1",
            )
        self.assertEqual(ctx.exception.code, "HISTORY_ENTRY_TOO_LARGE")

    def test_delete_and_clear_history(self) -> None:
        e1 = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-1",
            result={"val": 1},
            document_display_name="1.pptx",
            service_name="svc",
            model_name="m1",
        )
        e2 = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-2",
            result={"val": 2},
            document_display_name="2.pptx",
            service_name="svc",
            model_name="m1",
        )
        self.assertEqual(len(self.store.list_history("ppt.slide_assistant")), 2)

        deleted = self.store.delete_history(e1["id"])
        self.assertTrue(deleted)
        items = self.store.list_history("ppt.slide_assistant")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], e2["id"])

        cleared_count = self.store.clear_history("ppt.slide_assistant")
        self.assertEqual(cleared_count, 1)
        self.assertEqual(len(self.store.list_history("ppt.slide_assistant")), 0)

    def test_wildcard_and_path_traversal_rejected(self) -> None:
        e1 = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-sec-1",
            result={"val": "protected"},
            document_display_name="sec.pptx",
            service_name="svc",
            model_name="m1",
        )
        # Attempt wildcard deletion
        self.assertFalse(self.store.delete_history("*"))
        self.assertIsNone(self.store.get_history("*"))
        # Verify legitimate entry was not deleted
        self.assertIsNotNone(self.store.get_history(e1["id"]))

        # Attempt path traversal
        traversal_id = "../../config/adapter"
        self.assertFalse(self.store.delete_history(traversal_id))
        self.assertIsNone(self.store.get_history(traversal_id))
        self.assertFalse(self.store.delete_history("..\\..\\config\\adapter"))
        self.assertIsNone(self.store.get_history("..\\..\\config\\adapter"))

        # Verify legitimate entry still exists
        self.assertEqual(len(self.store.list_history("ppt.slide_assistant")), 1)

    def test_get_history_ttl_eviction(self) -> None:
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        old_entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-old-direct",
            result={"text": "expired"},
            document_display_name="expired.pptx",
            service_name="svc",
            model_name="m1",
            completed_at=old_time,
        )
        # Directly fetching single entry older than 24h must return None and unlink
        self.assertIsNone(self.store.get_history(old_entry["id"]))
        file_path = self.history_dir / "ppt.slide_assistant" / f"{old_entry['id']}.json"
        self.assertFalse(file_path.exists(), "Expired history file must be unlinked on get_history")

    def test_sanitization_strips_prompt_and_user_instruction(self) -> None:
        result_payload = {
            "resultType": "document",
            "deckTitle": "安全测试",
            "prompt": "系统提示词以及用户的原始敏感输入信息",
            "userInstruction": "请重点总结第二章财务细节",
            "plainText": "测试输出",
        }
        entry = self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-prompt-strip",
            result=result_payload,
            document_display_name="prompt_test.pptx",
            service_name="svc",
            model_name="m1",
        )
        fetched = self.store.get_history(entry["id"])
        self.assertIsNotNone(fetched)
        self.assertNotIn("prompt", fetched["result"])
        self.assertNotIn("userInstruction", fetched["result"])
        self.assertEqual(fetched["result"]["deckTitle"], "安全测试")

    def test_root_dir_permissions(self) -> None:
        self.store.record_success(
            task_type="ppt.slide_assistant",
            job_id="job-perm-root",
            result={"text": "perm"},
            document_display_name="test.pptx",
            service_name="svc",
            model_name="m1",
        )
    def test_sanitization_writing_policy_audit_evidence_not_persisted(self) -> None:
        raw_audit = {
            "enabled": True,
            "passed": False,
            "degraded": False,
            "summary": "发现 2 项需人工核对",
            "needsReview": [
                {
                    "code": "protected_date_changed",
                    "severity": "warning",
                    "message": "原文中的重要截止日期被改动",
                    "evidence": "2026年7月25日涉密现场施工期限",
                },
                {
                    "code": "responsibility_subject_changed",
                    "severity": "warning",
                    "message": "原文中的责任单位被修改",
                    "evidence": "安全保密办公室责任人张三",
                },
            ],
            "expressionSuggestions": [
                {
                    "code": "term_standardization",
                    "message": "建议使用规范术语",
                    "suggestion": "请使用'安全审计'",
                    "evidence": "违规词原文片段",
                }
            ],
        }

        # 1. Test whitelist sanitization helper
        cleaned = sanitize_audit_for_history(raw_audit)
        self.assertTrue(cleaned["enabled"])
        self.assertFalse(cleaned["passed"])
        self.assertEqual(len(cleaned["needsReview"]), 2)
        for item in cleaned["needsReview"]:
            self.assertIn("code", item)
            self.assertIn("severity", item)
            self.assertIn("message", item)
            self.assertNotIn("evidence", item)
        self.assertEqual(len(cleaned["expressionSuggestions"]), 1)
        self.assertNotIn("evidence", cleaned["expressionSuggestions"][0])

        # 2. Test persistence end-to-end to disk
        archived_payload = {
            "rewrittenText": "经规范化处理的公文改写结果。",
            "plainText": "经规范化处理的公文改写结果。",
            "writingPolicyAudit": cleaned,
        }
        entry = self.store.record_success(
            task_type="word.smart_write",
            job_id="job-audit-sanitize",
            result=archived_payload,
            document_display_name="红头文件初稿.docx",
            service_name="企业模型网关",
            model_name="deepseek-v3",
        )
        task_dir = self.history_dir / "word.smart_write"
        entry_file = task_dir / f"{entry['id']}.json"
        self.assertTrue(entry_file.exists())
        file_content = entry_file.read_text(encoding="utf-8")

        # Must not leak evidence key or raw input substrings anywhere in persisted file
        self.assertNotIn('"evidence"', file_content)
        self.assertNotIn("2026年7月25日涉密现场施工期限", file_content)
        self.assertNotIn("安全保密办公室责任人张三", file_content)
        self.assertNotIn("违规词原文片段", file_content)
        self.assertIn("经规范化处理的公文改写结果", file_content)

        # 3. Defense-in-depth: even if uncleaned audit is directly passed to record_success
        entry2 = self.store.record_success(
            task_type="word.smart_write",
            job_id="job-raw-audit-sanitize",
            result={"rawAudit": raw_audit},
            document_display_name="红头文件初稿.docx",
            service_name="网关",
            model_name="m1",
        )
        file2 = task_dir / f"{entry2['id']}.json"
        file2_content = file2.read_text(encoding="utf-8")
        self.assertNotIn('"evidence"', file2_content)
        self.assertNotIn("2026年7月25日涉密现场施工期限", file2_content)


if __name__ == "__main__":
    unittest.main()
