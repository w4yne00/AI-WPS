import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.services.workflow_profiles import (
    MAX_PROFILES_PER_TASK,
    WorkflowProfileError,
    WorkflowProfileStore,
)


class WorkflowProfileStoreTests(unittest.TestCase):
    def _paths(self, root: Path):
        config_path = root / "adapter.json"
        key_dir = root / "provider_api_keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}\n", encoding="utf-8")
        return config_path, key_dir

    def test_list_migrates_legacy_task_key_without_moving_secret(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, key_dir = self._paths(root)
            config_path.write_text(
                json.dumps({"taskApiKeyRefs": {"word.smart_write": "smart_write_old"}}),
                encoding="utf-8",
            )
            legacy_key = key_dir / "smart_write_old"
            legacy_key.write_text("app-old-secret\n", encoding="utf-8")

            result = WorkflowProfileStore(config_path, key_dir).list_for_task("word.smart_write")

            self.assertEqual(result["activeProfileId"], result["profiles"][0]["id"])
            self.assertEqual(result["profiles"][0]["name"], "当前配置")
            self.assertTrue(result["profiles"][0]["keyConfigured"])
            self.assertNotIn('"apiKey":', json.dumps(result))
            self.assertEqual(legacy_key.read_text(encoding="utf-8").strip(), "app-old-secret")

    def test_list_does_not_migrate_example_when_runtime_config_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "missing-adapter.json"
            store = WorkflowProfileStore(config_path, root / "provider_api_keys")

            result = store.list_for_task("word.smart_write")

            self.assertEqual(result["profiles"], [])
            self.assertFalse(config_path.exists())

    def test_create_and_list_profiles_are_isolated_by_task(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            word = store.create_profile("word.smart_write", "智能编写稳定版", "app-word", activate=True)
            store.create_profile("excel.analysis", "表格分析稳定版", "app-excel", activate=True)

            result = store.list_for_task("word.smart_write")

            self.assertEqual([item["id"] for item in result["profiles"]], [word["id"]])
            self.assertEqual(result["profileCount"], 1)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("app-word", serialized)
            self.assertNotIn("app-excel", serialized)

    def test_activate_updates_current_profile_and_legacy_ref(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            store.create_profile("word.smart_write", "稳定版", "app-stable", activate=True)
            candidate = store.create_profile("word.smart_write", "候选版", "app-next")

            result = store.activate_profile(candidate["id"])
            payload = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(result["activeProfileId"], candidate["id"])
            self.assertEqual(payload["activeWorkflowProfiles"]["word.smart_write"], candidate["id"])
            self.assertEqual(payload["taskApiKeyRefs"]["word.smart_write"], candidate["apiKeyRef"])

    def test_duplicate_name_is_rejected_case_insensitively(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            store.create_profile("word.smart_write", "Stable V1", "app-one")

            with self.assertRaisesRegex(WorkflowProfileError, "名称已存在"):
                store.create_profile("word.smart_write", " stable v1 ", "app-two")

    def test_update_profile_renames_without_replacing_key(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            profile = store.create_profile("word.document_review", "旧名称", "app-review")

            updated = store.update_profile(profile["id"], "正式版", "长文本审查")

            self.assertEqual(updated["name"], "正式版")
            self.assertEqual(updated["note"], "长文本审查")
            self.assertEqual((key_dir / profile["apiKeyRef"]).read_text(encoding="utf-8").strip(), "app-review")

    def test_replace_api_key_uses_private_file_permissions(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            profile = store.create_profile("word.format_review", "普通模式", "app-old")

            store.replace_api_key(profile["id"], "app-new")
            key_path = key_dir / profile["apiKeyRef"]

            self.assertEqual(key_path.read_text(encoding="utf-8").strip(), "app-new")
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)

    def test_active_profile_cannot_be_deleted(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            profile = store.create_profile("excel.analysis", "生产版", "app-excel", activate=True)

            with self.assertRaisesRegex(WorkflowProfileError, "先切换"):
                store.delete_profile(profile["id"])

    def test_deleting_inactive_profile_removes_only_its_key_file(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            active = store.create_profile("word.format_review", "当前版", "app-current", activate=True)
            inactive = store.create_profile("word.format_review", "历史版", "app-old")

            store.delete_profile(inactive["id"])

            self.assertTrue((key_dir / active["apiKeyRef"]).exists())
            self.assertFalse((key_dir / inactive["apiKeyRef"]).exists())

    def test_missing_key_prevents_activation(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            store.create_profile("word.smart_imitation", "当前版", "app-current", activate=True)
            candidate = store.create_profile("word.smart_imitation", "缺失密钥", "app-missing")
            (key_dir / candidate["apiKeyRef"]).unlink()

            with self.assertRaisesRegex(WorkflowProfileError, "尚未配置 API Key"):
                store.activate_profile(candidate["id"])

    def test_validation_rejects_unsupported_task_and_profile_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path, key_dir = self._paths(Path(tmp))
            store = WorkflowProfileStore(config_path, key_dir)
            with self.assertRaisesRegex(WorkflowProfileError, "不支持的任务类型"):
                store.create_profile("word.unknown", "测试", "app-test")
            for index in range(MAX_PROFILES_PER_TASK):
                store.create_profile("word.smart_write", "版本-{0}".format(index), "app-{0}".format(index))

            with self.assertRaisesRegex(WorkflowProfileError, "最多保存"):
                store.create_profile("word.smart_write", "超出限制", "app-overflow")


if __name__ == "__main__":
    unittest.main()
