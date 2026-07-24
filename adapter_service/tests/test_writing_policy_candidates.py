import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_writing_policy_candidates import (
    REVIEW_COLUMNS,
    audit_candidates,
    build_candidates,
    write_review_files,
)


SOURCE = """
# G 企网络安全与信息化技术写作

## 保护项与证据

用户指定原文 > 正式结论、招标原文与责任条款 > 法规标准、参数数据。

## 写作与审阅规则

1. 每段承担明确作用：依据、现状、问题、方案、约束、责任、结论或待决事项。
2. 具体化时优先写对象、动作、条件、边界和验证方式，不追求口号或金句。
3. 正式文件可保留必要重复、并列结构和规范用语；不要为了句式变化牺牲可执行性。

## 质量闸门 H1—H6

- H1 保护项完整；H2 证据状态合规；H3 规范强度一致。
"""


class WritingPolicyCandidateTests(unittest.TestCase):
    def test_generator_reads_injected_clean_tag_and_never_auto_approves(self):
        calls = []

        def git_show_reader(tag, path):
            calls.append((tag, path))
            return SOURCE

        rows = build_candidates(
            git_show_reader,
            tag="v1.1.0",
            commit="d3640165569071251248a5fafb2def6ef2fe2cf4",
            source_path="SKILL.md",
        )

        self.assertEqual(calls, [("v1.1.0", "SKILL.md")])
        self.assertGreaterEqual(len(rows), 4)
        self.assertTrue(all(row["审阅决定"] == "" for row in rows))
        self.assertTrue(all(row["来源版本"] == "v1.1.0" for row in rows))
        self.assertTrue(all(row["来源提交"] == "d3640165569071251248a5fafb2def6ef2fe2cf4" for row in rows))
        self.assertTrue(all(row["许可证"] == "MIT" for row in rows))
        self.assertEqual(audit_candidates(rows)["unreviewedCount"], len(rows))

    def test_csv_and_xlsx_use_identical_review_columns(self):
        rows = build_candidates(
            lambda _tag, _path: SOURCE,
            tag="v1.1.0",
            commit="d3640165569071251248a5fafb2def6ef2fe2cf4",
            source_path="SKILL.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            csv_path, xlsx_path = write_review_files(rows, Path(directory) / "review")
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            csv_header = next(csv.reader(io.StringIO(csv_text)))
            with zipfile.ZipFile(xlsx_path) as archive:
                sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertEqual(csv_header, list(REVIEW_COLUMNS))
        for column in REVIEW_COLUMNS:
            self.assertIn(column, sheet)
        self.assertNotIn(">通过<", sheet)

    def test_audit_reports_duplicates_near_duplicates_conflicts_missing_sources_and_unreviewed(self):
        base = {
            "稳定ID": "rule.yangqi.one",
            "规范包": "yangqi-tech-writing-base",
            "类型": "style",
            "分类": "表达",
            "名称": "明确责任",
            "规则或术语内容": "应明确责任主体。",
            "正例": "运维部门负责整改。",
            "反例": "做好整改。",
            "来源": "yangqi-tech-writing",
            "来源版本": "v1.1.0",
            "来源提交": "d3640165569071251248a5fafb2def6ef2fe2cf4",
            "来源路径": "SKILL.md",
            "来源定位": "SKILL.md#写作与审阅规则-1",
            "许可证": "MIT",
            "默认启用": "true",
            "审阅决定": "",
            "审阅备注": "",
        }
        rows = [
            dict(base),
            dict(base, **{"规则或术语内容": "应当明确责任主体。"}),
            dict(
                base,
                **{
                    "稳定ID": "rule.yangqi.other",
                    "规则或术语内容": "无需明确责任主体。",
                },
            ),
            dict(
                base,
                **{
                    "稳定ID": "rule.yangqi.missing",
                    "名称": "缺少来源",
                    "来源": "",
                    "来源定位": "",
                },
            ),
        ]

        report = audit_candidates(rows)

        self.assertEqual(report["duplicateIds"], ["rule.yangqi.one"])
        self.assertTrue(report["nearDuplicates"])
        self.assertTrue(report["conflicts"])
        self.assertEqual(report["missingSources"], ["rule.yangqi.missing"])
        self.assertEqual(report["unreviewedCount"], 4)


if __name__ == "__main__":
    unittest.main()
