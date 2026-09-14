# -*- coding: utf-8 -*-
"""Issue #182：公开合同、操作文档、验收清单与交付白名单必须对齐父规格 #164。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "packaging" / "v0260-preview1-target-machine-acceptance.md"
DELIVERY = ROOT / "packaging" / "v0260-preview1-delivery.md"
WORKFLOW_OPS = ROOT / "docs" / "operations" / "workflow-profile-management.md"
SHARED_OPS = ROOT / "docs" / "operations" / "shared-direct-service.md"
HISTORY_OPS = ROOT / "docs" / "operations" / "task-result-lifecycle.md"
CATALOG_OPS = ROOT / "docs" / "operations" / "direct-service-model-catalog.md"
FORMAT_OPS = ROOT / "docs" / "operations" / "word-format-review-direct-validation.md"
CONTEXT = ROOT / "CONTEXT.md"
ALLOWLIST = ROOT / "packaging" / "delivery-sources-v0260-preview1.json"
ADR_DIR = ROOT / "docs" / "adr"

NINE_TASKS = (
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

REQUIRED_ACCEPTANCE_MARKERS = (
    "共享直连服务",
    "模型目录",
    "Key 替换",
    "多文档隔离",
    "窗格恢复",
    "历史跨重启",
    "320×700",
    "420×900",
    "manual-pending",
    "candidate",
)

FORBIDDEN_ACCEPTANCE_STATUS = (
    "当前记录状态：`target-accepted`",
    "当前记录状态：`passed`",
)

REQUIRED_OPS_MARKERS = (
    "共享直连服务",
    "只录入一次",
    "工作流平台",
    "按功能独立",
    "修订冲突",
    "引用删除",
    "Key 轮换",
)

REQUIRED_HISTORY_MARKERS = (
    "活动任务结果",
    "文档会话",
    "二十四小时",
    "20",
    "5 MiB",
    "100 MiB",
    "不得再次写回",
    "专用报告",
    "API Key",
)

REQUIRED_ALLOWLIST_SOURCES = (
    "docs/operations/shared-direct-service.md",
    "docs/operations/task-result-lifecycle.md",
    "docs/operations/direct-service-model-catalog.md",
    "docs/operations/word-format-review-direct-validation.md",
)


def _read(path):
    return path.read_text(encoding="utf-8")


class Issue182DeliveryEvidenceTests(unittest.TestCase):
    def test_acceptance_checklist_covers_kylin_scenarios_and_stays_candidate(self):
        text = _read(ACCEPTANCE)
        for marker in REQUIRED_ACCEPTANCE_MARKERS:
            self.assertIn(marker, text, "验收清单缺少：{0}".format(marker))
        for forbidden in FORBIDDEN_ACCEPTANCE_STATUS:
            self.assertNotIn(forbidden, text, "未完成目标机验收不得写成：{0}".format(forbidden))
        self.assertIn("Issue #164", text)
        self.assertIn("不宣称", text)

    def test_delivery_readme_describes_shared_direct_not_per_task_keys(self):
        text = _read(DELIVERY)
        self.assertIn("共享直连服务", text)
        self.assertIn("工作流平台继续按功能独立配置", text)
        self.assertNotIn(
            "分别隔离服务地址、API Key 与接入参数",
            text,
            "交付说明不得把模型直连写成按任务隔离完整 URL/Key",
        )
        self.assertIn("candidate", text)
        self.assertIn("manual-pending", text)

    def test_workflow_ops_doc_no_longer_treats_direct_as_per_task_double_key(self):
        text = _read(WORKFLOW_OPS)
        self.assertIn("共享直连服务", text)
        self.assertIn("shared-direct-service.md", text)
        self.assertNotIn(
            "API Key 需输入两次；也可以先保存不完整配置，稍后补充。",
            text,
            "直连不得再要求输入两次 Key 作为通用步骤",
        )
        self.assertNotIn(
            "每个配置独立保存：",
            text.split("### 模型直连", 1)[-1][:400] if "### 模型直连" in text else text,
            "模型直连段落不得继续写成每个任务配置独立保存地址和 Key",
        )

    def test_shared_direct_and_history_ops_docs_match_public_contract(self):
        shared = _read(SHARED_OPS)
        history = _read(HISTORY_OPS)
        catalog = _read(CATALOG_OPS)
        format_doc = _read(FORMAT_OPS)
        for marker in REQUIRED_OPS_MARKERS:
            self.assertIn(marker, shared, "共享直连操作文档缺少：{0}".format(marker))
        for marker in REQUIRED_HISTORY_MARKERS:
            self.assertIn(marker, history, "结果生命周期操作文档缺少：{0}".format(marker))
        self.assertIn("/models", catalog)
        self.assertIn("word.format_review", format_doc)
        for task in NINE_TASKS:
            self.assertIn(task, shared)

    def test_domain_vocabulary_and_adrs_remain_aligned(self):
        context = _read(CONTEXT)
        for term in (
            "直连服务配置",
            "任务模型选择",
            "活动任务结果",
            "文档会话",
            "活动任务槽位",
            "历史结果列表",
            "历史结果快照",
            "新任务",
            "活动任务恢复",
        ):
            self.assertIn("**{0}**".format(term), context)
        for name in (
            "0128-share-direct-model-services-across-hosts.md",
            "0129-invalidate-unfinished-tasks-on-shared-key-rotation.md",
            "0130-merge-legacy-direct-configurations-by-endpoint-and-key.md",
            "0131-isolate-active-results-and-archive-read-only-history.md",
        ):
            self.assertTrue((ADR_DIR / name).is_file(), "缺少 ADR：{0}".format(name))

    def test_preview_allowlist_ships_issue164_operations_docs(self):
        policy = json.loads(_read(ALLOWLIST))
        sources = set()
        for entry in policy.get("entries", []):
            source = str(entry.get("source") or "")
            sources.add(source)
        for required in REQUIRED_ALLOWLIST_SOURCES:
            self.assertIn(required, sources, "交付白名单未纳入：{0}".format(required))


if __name__ == "__main__":
    unittest.main()
