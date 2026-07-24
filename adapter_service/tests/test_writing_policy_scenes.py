import unittest

from app.services.writing_policy.models import MAX_PROMPT_CHARS
from app.services.writing_policy.packs import (
    default_pack_directory,
    load_pack_snapshot,
)
from app.services.writing_policy.service import WritingPolicyService


class _EmptyStore:
    def enabled_items(self, _task_scope):
        return [], []


class WritingPolicySceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_pack_snapshot(default_pack_directory())

    def setUp(self):
        self.service = WritingPolicyService(
            store=_EmptyStore(),
            pack_snapshot=self.snapshot,
        )

    def test_explicit_scenes_resolve_expected_pack_combinations(self):
        cases = (
            (
                "yangqi",
                "技术方案应明确验收条件。",
                ["G企技术写作基础", "技术文件文体"],
            ),
            (
                "cybersecurity",
                "等保测评发现秘钥配置不符合访问控制要求。",
                ["G企技术写作基础", "技术文件文体", "网络安全术语"],
            ),
            (
                "official",
                "请将这份请示改写为正式公文。",
                ["G企技术写作基础", "党政公文文体"],
            ),
        )

        for scene, source, expected_packs in cases:
            with self.subTest(scene=scene):
                result = self.service.prepare(
                    "word.smart_write",
                    [source],
                    scene=scene,
                )

                self.assertEqual(result.usage["requestedScene"], scene)
                self.assertEqual(result.usage["scene"], scene)
                self.assertEqual(result.usage["packNames"], expected_packs)
                self.assertFalse(result.usage["autoFallback"])
                self.assertTrue(result.usage["applied"])
                self.assertLessEqual(len(result.prompt_block), MAX_PROMPT_CHARS)

        cybersecurity = self.service.prepare(
            "word.smart_write",
            ["等保测评发现秘钥配置不符合访问控制要求。"],
            scene="cybersecurity",
        )
        self.assertIn("网络安全等级保护", cybersecurity.prompt_block)
        self.assertIn("密钥", cybersecurity.prompt_block)

    def test_auto_matching_is_conservative_and_explainable(self):
        cases = (
            (
                "开展网络安全等级保护测评并修复访问控制漏洞。",
                "cybersecurity",
                False,
                ["G企技术写作基础", "技术文件文体", "网络安全术语"],
            ),
            (
                "请起草关于开展专项检查的通知，明确主送机关和报送要求。",
                "official",
                False,
                ["G企技术写作基础", "党政公文文体"],
            ),
            (
                "技术方案应说明项目验收指标、责任部门和实施边界。",
                "yangqi",
                False,
                ["G企技术写作基础", "技术文件文体"],
            ),
            (
                "请把这段话写得更清楚。",
                "yangqi",
                True,
                ["G企技术写作基础"],
            ),
        )

        for source, scene, fallback, packs in cases:
            with self.subTest(source=source):
                result = self.service.prepare(
                    "word.smart_write",
                    [source],
                    scene="auto",
                )

                self.assertEqual(result.usage["requestedScene"], "auto")
                self.assertEqual(result.usage["scene"], scene)
                self.assertEqual(result.usage["autoFallback"], fallback)
                self.assertEqual(result.usage["packNames"], packs)

    def test_disabled_scene_skips_preset_and_organization_policies(self):
        result = self.service.prepare(
            "word.smart_write",
            ["网络安全等级保护和访问控制。"],
            scene="disabled",
        )

        self.assertEqual(result.prompt_block, "")
        self.assertFalse(result.usage["applied"])
        self.assertFalse(result.usage["degraded"])
        self.assertEqual(result.usage["scene"], "disabled")
        self.assertEqual(result.usage["packNames"], [])
        self.assertEqual(result.matched_item_ids, ())


if __name__ == "__main__":
    unittest.main()
