import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.writing_policy.packs import (
    default_pack_directory,
    entry_content_sha256,
    load_pack_snapshot,
)
from app.services.writing_policy.service import WritingPolicyService


HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


class _EmptyStore:
    def enabled_items(self, _task_scope):
        return [], []


def _write_approved_pack(root: Path):
    pack = {
        "schemaVersion": 1,
        "packId": "yangqi-tech-writing-base",
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
                "id": "rule.yangqi.base.001",
                "type": "style",
                "category": "保护项",
                "name": "保护事实和责任边界",
                "ruleText": "保留原文中的事实、数字、责任主体和规范性强度。",
                "positiveExample": "",
                "negativeExample": "",
                "taskTypes": ["smart_write"],
                "sceneIds": ["yangqi"],
                "contextKeywords": [],
                "priority": 90,
                "defaultEnabled": True,
                "sourceRefs": ["yangqi-tech-writing:v1.1.0:SKILL.md#L57"],
            }
        ],
    }
    review = {
        "packId": "yangqi-tech-writing-base",
        "packVersion": "1.0.0",
        "reviewedAt": "2026-07-24",
        "reviewedBy": "Wayne",
        "decisions": [
            {
                "id": "rule.yangqi.base.001",
                "decision": "approved",
                "note": "",
                "contentSha256": entry_content_sha256(pack["entries"][0]),
            }
        ],
    }
    (root / "schema-v1.json").write_text("{}", encoding="utf-8")
    (root / "yangqi-tech-writing-base.json").write_text(
        json.dumps(pack, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "yangqi-tech-writing-base.review.json").write_text(
        json.dumps(review, ensure_ascii=False),
        encoding="utf-8",
    )


class WritingPolicyBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        _write_approved_pack(root)
        self.snapshot = load_pack_snapshot(root)
        self.service = WritingPolicyService(
            store=_EmptyStore(),
            pack_snapshot=self.snapshot,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_smart_write_auto_applies_base_pack_but_other_tasks_do_not(self):
        smart_write = self.service.prepare(
            "word.smart_write",
            ["请改写这段材料。"],
            scene="auto",
        )
        imitation = self.service.prepare(
            "word.smart_imitation",
            ["请仿写这段材料。"],
            scene="auto",
        )
        disabled = self.service.prepare(
            "word.smart_write",
            ["请改写这段材料。"],
            scene="disabled",
        )

        self.assertIn("保护事实和责任边界", smart_write.prompt_block)
        self.assertEqual(smart_write.usage["scene"], "yangqi")
        self.assertEqual(smart_write.usage["presetVersion"], "1.0.0")
        self.assertEqual(smart_write.usage["packName"], "G企技术写作基础")
        self.assertEqual(smart_write.usage["styleRuleCount"], 1)
        self.assertEqual(imitation.prompt_block, "")
        self.assertEqual(disabled.prompt_block, "")

    def test_bundled_base_pack_contains_the_17_human_approved_entries(self):
        snapshot = load_pack_snapshot(default_pack_directory())
        packs = snapshot.public_packs()
        review = json.loads(
            (
                default_pack_directory()
                / "yangqi-tech-writing-base.review.json"
            ).read_text(encoding="utf-8")
        )

        base_pack = next(
            pack
            for pack in packs
            if pack["packId"] == "yangqi-tech-writing-base"
        )
        self.assertEqual(base_pack["version"], "1.0.0")
        self.assertEqual(base_pack["entryCount"], 17)
        self.assertEqual(
            {item["id"] for item in snapshot.public_items("yangqi-tech-writing-base")},
            {"rule.yangqi.base.%03d" % index for index in range(1, 18)},
        )
        self.assertEqual(review["reviewedBy"], "Wayne")
        self.assertEqual(review["reviewedAt"], "2026-07-25")
        self.assertEqual(len(review["decisions"]), 17)
        self.assertTrue(
            all(item["decision"] == "approved" for item in review["decisions"])
        )
        items = snapshot.public_items("yangqi-tech-writing-base")
        self.assertEqual(
            {item["id"]: item["contentSha256"] for item in review["decisions"]},
            {
                item["id"]: entry_content_sha256(
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        not in {
                            "packId",
                            "packName",
                            "packVersion",
                            "layer",
                            "source",
                        }
                    }
                )
                for item in items
            },
        )

    def test_bundled_snapshot_contains_four_traceable_reviewed_packs(self):
        root = default_pack_directory()
        snapshot = load_pack_snapshot(root)
        packs = {pack["packId"]: pack for pack in snapshot.public_packs()}

        self.assertEqual(
            set(packs),
            {
                "yangqi-tech-writing-base",
                "technical-document-style",
                "official-document-style",
                "cybersecurity-terminology",
            },
        )
        for pack_id, pack in packs.items():
            with self.subTest(pack_id=pack_id):
                self.assertEqual(pack["version"], "1.0.0")
                self.assertTrue(pack["source"]["name"])
                self.assertTrue(pack["source"]["version"])
                self.assertTrue(pack["source"]["license"])
                self.assertGreater(pack["entryCount"], 0)

                review = json.loads(
                    (root / ("%s.review.json" % pack_id)).read_text(
                        encoding="utf-8"
                    )
                )
                items = snapshot.public_items(pack_id)
                self.assertEqual(review["packId"], pack_id)
                self.assertEqual(review["packVersion"], pack["version"])
                self.assertEqual(len(review["decisions"]), len(items))
                self.assertTrue(
                    all(
                        decision["decision"] == "approved"
                        for decision in review["decisions"]
                    )
                )
                self.assertEqual(
                    {
                        decision["id"]: decision["contentSha256"]
                        for decision in review["decisions"]
                    },
                    {
                        item["id"]: entry_content_sha256(
                            {
                                key: value
                                for key, value in item.items()
                                if key
                                not in {
                                    "packId",
                                    "packName",
                                    "packVersion",
                                    "layer",
                                    "source",
                                }
                            }
                        )
                        for item in items
                    },
                )
        self.assertEqual(
            packs["yangqi-tech-writing-base"]["source"]["commit"],
            "d3640165569071251248a5fafb2def6ef2fe2cf4",
        )
        self.assertEqual(
            packs["technical-document-style"]["source"]["commit"],
            "d3640165569071251248a5fafb2def6ef2fe2cf4",
        )
        self.assertEqual(
            packs["official-document-style"]["source"]["commit"],
            "",
        )
        self.assertEqual(
            packs["cybersecurity-terminology"]["source"]["commit"],
            "",
        )

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI dependency is not installed")
    def test_read_only_api_lists_pack_source_version_and_items(self):
        from app.api.writing_policies import get_packs, list_items

        with patch(
            "app.api.writing_policies.get_writing_policy_service",
            return_value=self.service,
        ):
            packs = get_packs()
            items = list_items(layer="preset", pack_id="yangqi-tech-writing-base")

        self.assertEqual(packs["data"]["packs"][0]["version"], "1.0.0")
        self.assertEqual(
            packs["data"]["packs"][0]["source"]["commit"],
            "d3640165569071251248a5fafb2def6ef2fe2cf4",
        )
        self.assertEqual(items["data"]["count"], 1)
        self.assertEqual(items["data"]["items"][0]["layer"], "preset")
        self.assertEqual(items["data"]["items"][0]["source"]["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
