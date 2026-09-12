import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.services.direct_services import (
    DirectServiceError,
    DirectServiceStore,
)
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryStore


class DirectServiceRevisionAndReferenceTests(unittest.TestCase):
    def _store(self, root: Path) -> DirectServiceStore:
        config_path = root / "adapter.json"
        if not config_path.exists():
            config_path.write_text("{}\n", encoding="utf-8")
        return DirectServiceStore(config_path, root / "provider_api_keys")

    def test_service_exposes_referenced_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="共享直连", service_base_url="https://api.openai.com/v1"
            )
            # Initially unreferenced
            svc = store.get_service(service["id"])
            self.assertEqual(svc.get("referencedTasks"), [])

            # Reference via taskModelSelections
            store.update_task_model_selection(
                task_type="excel.analysis",
                service_id=service["id"],
                model_name="gpt-4o",
            )
            svc = store.get_service(service["id"])
            self.assertEqual(svc.get("referencedTasks"), ["excel.analysis"])

            # Reference via activeModelConfigurations as well
            payload = json.loads(store.config_path.read_text(encoding="utf-8"))
            payload.setdefault("activeModelConfigurations", {})["word.smart_write"] = service["id"]
            store.config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            svc = store.get_service(service["id"])
            self.assertEqual(sorted(svc.get("referencedTasks", [])), ["excel.analysis", "word.smart_write"])

    def test_delete_service_blocked_when_referenced_by_selection_or_active(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="共享直连", service_base_url="https://api.openai.com/v1"
            )

            # Blocked by activeModelConfigurations
            payload = json.loads(store.config_path.read_text(encoding="utf-8"))
            payload.setdefault("activeModelConfigurations", {})["ppt.slide_assistant"] = service["id"]
            store.config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(DirectServiceError) as ctx:
                store.delete_service(service["id"], expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")
            self.assertIn("ppt.slide_assistant", ctx.exception.referenced_tasks)

    def test_revision_conflict_on_all_mutation_operations(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="版本测试", service_base_url="https://api.openai.com/v1"
            )
            service_id = service["id"]
            store.replace_api_key(service_id, "sk-initial", expected_revision=1)
            # Current revision is now 2

            # update with stale revision 1
            with self.assertRaises(DirectServiceError) as ctx:
                store.update_service(service_id, name="新名称", expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

            # replace key with stale revision 1
            with self.assertRaises(DirectServiceError) as ctx:
                store.replace_api_key(service_id, "sk-newer", expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

            # clear key with stale revision 1
            with self.assertRaises(DirectServiceError) as ctx:
                store.clear_api_key(service_id, expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

            # delete with stale revision 1
            with self.assertRaises(DirectServiceError) as ctx:
                store.delete_service(service_id, expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")


class LongTaskCoordinatorAuthInvalidationTests(unittest.TestCase):
    def test_coordinator_invalidates_queued_task_on_key_rotation(self) -> None:
        coordinator = LongTaskCoordinator(max_running=1, max_queued=5)
        service_id = "direct_svc_test_1"
        old_key = "sk-old-secret"
        old_fp = DirectServiceStore.api_key_fingerprint(old_key)

        # Occupy running slot with a blocking dummy job
        release_blocker = False
        def blocker_runner(snapshot, progress):
            while not release_blocker:
                time.sleep(0.01)
            return {"status": "ok"}

        coordinator.submit(
            job_id="blocker_job",
            trace_id="t1",
            task_type="excel.analysis",
            runner=blocker_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        # Submit job that will wait in queue
        task_auth = {
            "directServiceId": service_id,
            "apiKeyFingerprint": old_fp,
        }
        queued_job = coordinator.submit(
            job_id="queued_target_job",
            trace_id="t2",
            task_type="excel.analysis",
            runner=lambda s, p: {"data": "should_not_run"},
            snapshot={"taskAuth": task_auth},
            failure_code="FAILED",
            failure_message="failed",
        )
        self.assertEqual(queued_job["status"], "queued")

        # Invalidate jobs referencing (service_id, old_fp)
        count = coordinator.invalidate_by_auth(service_id, old_fp)
        self.assertEqual(count, 1)

        # Verify queued job immediately transitioned to failed
        target = coordinator.get("queued_target_job", task_type="excel.analysis")
        self.assertIsNotNone(target)
        self.assertEqual(target["status"], "failed")
        self.assertEqual(target["error"]["code"], "DIRECT_SERVICE_KEY_ROTATED")
        self.assertIn("服务 API Key 已更换或清除", target["error"]["message"])

        # Release blocker
        release_blocker = True
        coordinator.wait_result("blocker_job", task_type="excel.analysis", not_found_code="NOT_FOUND", not_found_message="not found", cancelled_message="cancelled", failure_code="FAILED", failure_message="failed", safe_error_statuses=set())

    def test_coordinator_invalidates_running_task_on_key_rotation(self) -> None:
        coordinator = LongTaskCoordinator(max_running=1, max_queued=5)
        service_id = "direct_svc_test_2"
        old_key = "sk-running-secret"
        old_fp = DirectServiceStore.api_key_fingerprint(old_key)

        running_started = False
        allow_runner_to_exit = False

        def worker_runner(snapshot, progress):
            nonlocal running_started
            running_started = True
            while not allow_runner_to_exit:
                time.sleep(0.01)
            return {"data": "unwanted_completed_data"}

        task_auth = {
            "directServiceId": service_id,
            "apiKeyFingerprint": old_fp,
        }
        running_job = coordinator.submit(
            job_id="running_target_job",
            trace_id="t3",
            task_type="word.smart_write",
            runner=worker_runner,
            snapshot={"taskAuth": task_auth},
            failure_code="FAILED",
            failure_message="failed",
            allow_running_cancel=True,
        )
        self.assertEqual(running_job["status"], "running")

        # Wait until runner starts
        while not running_started:
            time.sleep(0.005)

        # Rotate key and invalidate
        count = coordinator.invalidate_by_auth(service_id, old_fp)
        self.assertEqual(count, 1)

        # Even while worker has not exited yet, get() reveals failure
        res = coordinator.get("running_target_job", task_type="word.smart_write")
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error"]["code"], "DIRECT_SERVICE_KEY_ROTATED")

        # Let worker complete
        allow_runner_to_exit = True
        time.sleep(0.05)

        # After worker exits, final status must still be failed (result suppressed)
        final_res = coordinator.get("running_target_job", task_type="word.smart_write")
        self.assertEqual(final_res["status"], "failed")
        self.assertEqual(final_res["error"]["code"], "DIRECT_SERVICE_KEY_ROTATED")
        self.assertIsNone(final_res.get("result"))

    def test_completed_job_and_history_preserved_on_key_rotation(self) -> None:
        coordinator = LongTaskCoordinator(max_running=2, max_queued=5)
        service_id = "direct_svc_test_3"
        old_key = "sk-completed-secret"
        old_fp = DirectServiceStore.api_key_fingerprint(old_key)

        task_auth = {
            "directServiceId": service_id,
            "apiKeyFingerprint": old_fp,
        }
        coordinator.submit(
            job_id="completed_target_job",
            trace_id="t4",
            task_type="ppt.slide_assistant",
            runner=lambda s, p: {"summary": "valid_presentation_summary"},
            snapshot={"taskAuth": task_auth},
            failure_code="FAILED",
            failure_message="failed",
        )
        res = coordinator.wait_result("completed_target_job", task_type="ppt.slide_assistant", not_found_code="NOT_FOUND", not_found_message="not found", cancelled_message="cancelled", failure_code="FAILED", failure_message="failed", safe_error_statuses=set())
        self.assertEqual(res["summary"], "valid_presentation_summary")

        # Key rotation invalidation
        coordinator.invalidate_by_auth(service_id, old_fp)

        # Completed job MUST still be completed!
        checked = coordinator.get("completed_target_job", task_type="ppt.slide_assistant")
        self.assertEqual(checked["status"], "completed")
        self.assertEqual(checked["result"]["summary"], "valid_presentation_summary")

    def test_new_job_with_new_key_succeeds_after_rotation(self) -> None:
        coordinator = LongTaskCoordinator(max_running=2, max_queued=5)
        service_id = "direct_svc_test_4"
        old_fp = DirectServiceStore.api_key_fingerprint("sk-old")
        new_fp = DirectServiceStore.api_key_fingerprint("sk-new")

        # Invalidate old fingerprint
        coordinator.invalidate_by_auth(service_id, old_fp)

        # Submit new job with new fingerprint
        new_job = coordinator.submit(
            job_id="new_post_rotation_job",
            trace_id="t5",
            task_type="excel.formula_assistant",
            runner=lambda s, p: {"formula": "=SUM(A1:A10)"},
            snapshot={"taskAuth": {"directServiceId": service_id, "apiKeyFingerprint": new_fp}},
            failure_code="FAILED",
            failure_message="failed",
        )
        res = coordinator.wait_result("new_post_rotation_job", task_type="excel.formula_assistant", not_found_code="NOT_FOUND", not_found_message="not found", cancelled_message="cancelled", failure_code="FAILED", failure_message="failed", safe_error_statuses=set())
        self.assertEqual(res["formula"], "=SUM(A1:A10)")


class CrossHostTaskCoordinatorKeyRotationTests(unittest.TestCase):
    """Verifies that Key rotation in DirectServiceStore invalidates tasks across Word, Excel, PPT."""

    def _setup_env(self, root: Path):
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        store = DirectServiceStore(config_path, root / "provider_api_keys")
        coordinator = LongTaskCoordinator(max_running=1, max_queued=10)
        history_store = TaskHistoryStore(root / "history")
        return store, coordinator, history_store

    def test_all_nine_tasks_auth_association_and_key_rotation_invalidation(self) -> None:
        """Verifies Word (4 tasks), Excel (3 tasks), PPT (2 tasks) in coordinator."""
        nine_tasks = [
            # Word tasks
            "word.smart_write",
            "word.smart_imitation",
            "word.document_review",
            "word.format_review",
            # Excel tasks
            "excel.analysis",
            "excel.formula_assistant",
            "excel.smart_fill",
            # PPT tasks
            "ppt.slide_assistant",
            "ppt.structure_review",
        ]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store, coordinator, history_store = self._setup_env(root)

            # Create shared direct service and set initial key
            service = store.create_service(
                name="全宿主直连",
                service_base_url="https://api.openai.com/v1",
                default_model="gpt-4o",
            )
            svc_id = service["id"]
            store.replace_api_key(svc_id, "sk-initial-secret", expected_revision=1)
            initial_fp = DirectServiceStore.api_key_fingerprint("sk-initial-secret")

            # Connect coordinator invalidation listener to store
            store.register_key_rotation_listener(
                lambda sid, old_fp: coordinator.invalidate_by_auth(sid, old_fp)
            )

            # Block running slot so subsequent jobs stay in queue
            unblock_event = False
            def blocker(s, p):
                while not unblock_event:
                    time.sleep(0.01)
                return {"done": True}

            coordinator.submit(
                job_id="root_blocker",
                trace_id="t_block",
                task_type="excel.analysis",
                runner=blocker,
                snapshot={},
                failure_code="FAILED",
                failure_message="failed",
            )

            # Submit queued tasks for each of the 9 task types referencing initial key
            for task_type in nine_tasks:
                job_id = f"job_{task_type.replace('.', '_')}"
                auth = {
                    "directServiceId": svc_id,
                    "apiKeyFingerprint": initial_fp,
                }
                sub = coordinator.submit(
                    job_id=job_id,
                    trace_id="trace_" + job_id,
                    task_type=task_type,
                    runner=lambda s, p: {"result": "unexpected"},
                    snapshot={"taskAuth": auth},
                    failure_code="FAILED",
                    failure_message="failed",
                )
                self.assertEqual(sub["status"], "queued")

            # Perform Key Replacement on the store!
            # Current revision is 2
            store.replace_api_key(svc_id, "sk-rotated-new-secret", expected_revision=2)

            # Verify all 9 tasks in coordinator failed with DIRECT_SERVICE_KEY_ROTATED
            for task_type in nine_tasks:
                job_id = f"job_{task_type.replace('.', '_')}"
                job = coordinator.get(job_id, task_type=task_type)
                self.assertIsNotNone(job, f"Job {job_id} should exist")
                self.assertEqual(job["status"], "failed", f"Job {job_id} should be failed")
                self.assertEqual(
                    job["error"]["code"],
                    "DIRECT_SERVICE_KEY_ROTATED",
                    f"Job {job_id} code should be DIRECT_SERVICE_KEY_ROTATED",
                )
                self.assertIn("服务 API Key 已更换或清除", job["error"]["message"])

            # Clean up blocker
            unblock_event = True
            coordinator.wait_result("root_blocker", task_type="excel.analysis", not_found_code="NOT_FOUND", not_found_message="not found", cancelled_message="cancelled", failure_code="FAILED", failure_message="failed", safe_error_statuses=set())


if __name__ == "__main__":
    unittest.main()
