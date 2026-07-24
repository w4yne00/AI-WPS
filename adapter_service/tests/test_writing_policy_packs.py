import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from app.services.writing_policy.models import WritingPolicyError
from app.services.writing_policy.packs import (
    WritingPolicyPackSnapshot,
    entry_content_sha256,
    load_pack_snapshot,
    validate_pack_data,
)


def _pack(pack_id="yangqi-tech-writing-base", entry_id="rule.yangqi.responsibility"):
    return {
        "schemaVersion": 1,
        "packId": pack_id,
        "version": "1.0.0",
        "name": "G企技术写作基础",
        "sceneIds": ["yangqi"],
        "source": {
            "name": "yangqi-tech-writing",
            "version": "v1.1.0",
            "commit": "d3640165569071251248a5fafb2def6ef2fe2cf4",
            "license": "MIT",
        },
        "review": {
            "reviewedAt": "2026-07-24",
            "reviewedBy": "Wayne",
            "manifest": "yangqi-tech-writing-base.review.json",
        },
        "entries": [
            {
                "id": entry_id,
                "type": "style",
                "category": "责任表达",
                "name": "明确责任主体",
                "ruleText": "涉及实施、检查或整改时，应明确责任主体。",
                "positiveExample": "运维部门负责完成整改并复核。",
                "negativeExample": "相关部门做好整改。",
                "taskTypes": ["smart_write"],
                "sceneIds": ["yangqi"],
                "contextKeywords": ["负责", "整改"],
                "priority": 70,
                "defaultEnabled": True,
                "sourceRefs": ["yangqi-tech-writing:v1.1.0:SKILL.md#保护项与证据"],
            }
        ],
    }


def _review(pack_id, entry_id, entry=None):
    reviewed_entry = entry or _pack(pack_id, entry_id)["entries"][0]
    return {
        "packId": pack_id,
        "packVersion": "1.0.0",
        "reviewedAt": "2026-07-24",
        "reviewedBy": "Wayne",
        "decisions": [
            {
                "id": entry_id,
                "decision": "approved",
                "note": "",
                "contentSha256": entry_content_sha256(reviewed_entry),
            }
        ],
    }


class WritingPolicyPackTests(unittest.TestCase):
    def test_strict_validation_rejects_unknown_fields_and_unreviewed_enabled_entries(self):
        unknown = _pack()
        unknown["unexpected"] = True
        with self.assertRaises(WritingPolicyError) as raised:
            validate_pack_data(unknown, "unknown.json")
        self.assertEqual(raised.exception.code, "invalid_writing_policy_pack")

        unreviewed = _pack()
        del unreviewed["review"]
        with self.assertRaises(WritingPolicyError) as raised:
            validate_pack_data(unreviewed, "unreviewed.json")
        self.assertEqual(raised.exception.code, "unreviewed_writing_policy_pack")

    def test_snapshot_is_frozen_and_exposes_traceable_read_only_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema-v1.json").write_text("{}", encoding="utf-8")
            (root / "yangqi-tech-writing-base.json").write_text(
                json.dumps(_pack(), ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "yangqi-tech-writing-base.review.json").write_text(
                json.dumps(
                    _review(
                        "yangqi-tech-writing-base",
                        "rule.yangqi.responsibility",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            snapshot = load_pack_snapshot(root)

        self.assertEqual(snapshot.packs[0].pack_id, "yangqi-tech-writing-base")
        with self.assertRaises(FrozenInstanceError):
            snapshot.packs[0].version = "2.0.0"
        self.assertEqual(
            snapshot.public_packs(),
            [
                {
                    "packId": "yangqi-tech-writing-base",
                    "name": "G企技术写作基础",
                    "version": "1.0.0",
                    "sceneIds": ["yangqi"],
                    "entryCount": 1,
                    "source": {
                        "name": "yangqi-tech-writing",
                        "version": "v1.1.0",
                        "commit": "d3640165569071251248a5fafb2def6ef2fe2cf4",
                        "license": "MIT",
                    },
                }
            ],
        )
        item = snapshot.public_items("yangqi-tech-writing-base")[0]
        self.assertEqual(item["id"], "rule.yangqi.responsibility")
        self.assertEqual(item["packVersion"], "1.0.0")
        self.assertEqual(item["source"]["license"], "MIT")
        self.assertNotIn("review", item)

    def test_loader_rejects_duplicate_ids_and_conflicting_rule_names_across_packs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema-v1.json").write_text("{}", encoding="utf-8")
            (root / "a.json").write_text(
                json.dumps(_pack("pack-a", "rule.shared"), ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "yangqi-tech-writing-base.review.json").write_text(
                json.dumps(_review("pack-a", "rule.shared"), ensure_ascii=False),
                encoding="utf-8",
            )
            duplicate = _pack("pack-b", "rule.shared")
            duplicate["name"] = "另一个规范包"
            duplicate["review"]["manifest"] = "pack-b.review.json"
            (root / "b.json").write_text(
                json.dumps(duplicate, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "pack-b.review.json").write_text(
                json.dumps(_review("pack-b", "rule.shared"), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(WritingPolicyError) as raised:
                load_pack_snapshot(root)
            self.assertEqual(raised.exception.code, "duplicate_writing_policy_id")

            duplicate["entries"][0]["id"] = "rule.other"
            duplicate["entries"][0]["ruleText"] = "同名规则给出相反要求。"
            (root / "b.json").write_text(
                json.dumps(duplicate, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "pack-b.review.json").write_text(
                json.dumps(
                    _review("pack-b", "rule.other", duplicate["entries"][0]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(WritingPolicyError) as raised:
                load_pack_snapshot(root)
            self.assertEqual(raised.exception.code, "conflicting_writing_policy_rule")

    def test_matcher_uses_existing_word_scope_names(self):
        pack = _pack()
        pack["entries"][0]["taskTypes"] = ["smart_imitate", "document_review"]
        pack["entries"][0]["sceneIds"] = ["yangqi"]
        model = validate_pack_data(pack, "scope.json")

        frozen = WritingPolicyPackSnapshot((model,))
        _terms, imitate_styles = frozen.matcher_items(
            model.pack_id,
            "smart_imitate",
            "yangqi",
        )
        _terms, review_styles = frozen.matcher_items(
            model.pack_id,
            "document_review",
            "yangqi",
        )

        self.assertEqual(imitate_styles[0]["scope"], "word.smart_imitation")
        self.assertEqual(review_styles[0]["scope"], "word.document_review")

    def test_loader_rejects_review_manifest_with_mismatched_reviewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = _pack()
            (root / "yangqi-tech-writing-base.json").write_text(
                json.dumps(pack, ensure_ascii=False),
                encoding="utf-8",
            )
            review = _review(
                "yangqi-tech-writing-base",
                "rule.yangqi.responsibility",
            )
            review["reviewedBy"] = "Another reviewer"
            (root / "yangqi-tech-writing-base.review.json").write_text(
                json.dumps(review, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(WritingPolicyError) as raised:
                load_pack_snapshot(root)

        self.assertEqual(raised.exception.code, "unreviewed_writing_policy_pack")

    def test_loader_rejects_content_changed_after_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = _pack()
            review = _review(
                "yangqi-tech-writing-base",
                "rule.yangqi.responsibility",
                pack["entries"][0],
            )
            pack["entries"][0]["ruleText"] = "审批后被替换的规则。"
            (root / "yangqi-tech-writing-base.json").write_text(
                json.dumps(pack, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "yangqi-tech-writing-base.review.json").write_text(
                json.dumps(review, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(WritingPolicyError) as raised:
                load_pack_snapshot(root)

        self.assertEqual(raised.exception.code, "unreviewed_writing_policy_pack")

    def test_loader_rejects_duplicate_pack_ids_across_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _pack()
            second = _pack(entry_id="rule.yangqi.other")
            first["review"]["manifest"] = "first.review.json"
            second["review"]["manifest"] = "second.review.json"
            (root / "first.json").write_text(
                json.dumps(first, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "second.json").write_text(
                json.dumps(second, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "first.review.json").write_text(
                json.dumps(
                    _review(
                        first["packId"],
                        first["entries"][0]["id"],
                        first["entries"][0],
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "second.review.json").write_text(
                json.dumps(
                    _review(
                        second["packId"],
                        second["entries"][0]["id"],
                        second["entries"][0],
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaises(WritingPolicyError) as raised:
                load_pack_snapshot(root)

        self.assertEqual(raised.exception.code, "duplicate_writing_policy_pack_id")


if __name__ == "__main__":
    unittest.main()
