import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.services.workflow_profiles import WorkflowProfileStore

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from app.core.errors import AdapterError
    from app.api.provider import (
        WorkflowProfileApiKeyRequest,
        WorkflowProfileCreateRequest,
        WorkflowProfileUpdateRequest,
        activate_workflow_profile,
        create_workflow_profile,
        delete_provider_task_api_key,
        delete_workflow_profile,
        get_workflow_profiles,
        replace_workflow_profile_api_key,
        save_provider_task_api_key,
        update_workflow_profile,
        ProviderTaskApiKeyRequest,
    )


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for workflow profile API tests")
class WorkflowProfileApiTests(unittest.TestCase):
    def _store(self, root: Path) -> WorkflowProfileStore:
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        return WorkflowProfileStore(config_path, root / "provider_api_keys")

    def test_crud_routes_return_sanitized_profile_data(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                created = create_workflow_profile(
                    WorkflowProfileCreateRequest(
                        taskType="word.smart_write",
                        name="稳定版",
                        apiKey="app-secret",
                        note="生产",
                        activate=True,
                    )
                )
                profile = created["data"]["profile"]
                listed = get_workflow_profiles(task_type="word.smart_write")
                updated = update_workflow_profile(
                    profile["id"], WorkflowProfileUpdateRequest(name="正式版", note="当前生产")
                )
                replaced = replace_workflow_profile_api_key(
                    profile["id"], WorkflowProfileApiKeyRequest(apiKey="app-replaced")
                )

            self.assertEqual(listed["data"]["profileCount"], 1)
            self.assertEqual(updated["data"]["profile"]["name"], "正式版")
            self.assertTrue(replaced["data"]["profile"]["keyConfigured"])
            self.assertNotIn("app-secret", str(created))
            self.assertNotIn("app-replaced", str(replaced))

    def test_activate_and_delete_routes_enforce_active_profile_protection(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            active = store.create_profile("word.format_review", "当前版", "app-one", activate=True)
            inactive = store.create_profile("word.format_review", "候选版", "app-two")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                activated = activate_workflow_profile(inactive["id"])
                deleted = delete_workflow_profile(active["id"])
                with self.assertRaises(AdapterError) as raised:
                    delete_workflow_profile(inactive["id"])

            self.assertEqual(activated["data"]["activeProfileId"], inactive["id"])
            self.assertEqual(deleted["data"]["profileCount"], 1)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("先切换", raised.exception.message)

    def test_duplicate_name_maps_to_http_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            store.create_profile("excel.analysis", "生产版", "app-one")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                with self.assertRaises(AdapterError) as raised:
                    create_workflow_profile(
                        WorkflowProfileCreateRequest(
                            taskType="excel.analysis", name="生产版", apiKey="app-two"
                        )
                    )

            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("名称已存在", raised.exception.message)

    def test_legacy_task_key_routes_update_only_current_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            historical = store.create_profile("word.document_review", "历史版", "app-old")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                saved = save_provider_task_api_key(
                    ProviderTaskApiKeyRequest(
                        taskType="word.document_review",
                        apiKey="app-current",
                        apiKeyRef="document_review_current",
                    )
                )
                cleared = delete_provider_task_api_key("word.document_review")

            self.assertEqual(saved["data"]["activeProfileName"], "当前配置")
            self.assertFalse(cleared["data"]["taskKeyConfigured"])
            self.assertTrue((store.key_dir / historical["apiKeyRef"]).exists())


if __name__ == "__main__":
    unittest.main()
