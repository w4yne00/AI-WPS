import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.writing_policy.models import WritingPolicyError
from app.services.writing_policy import service as service_module
from app.services.writing_policy.service import (
    WritingPolicyService,
    default_database_path,
    get_writing_policy_service,
)


def term_item(item_id="term-1"):
    return {
        "id": item_id,
        "type": "term",
        "scope": "global",
        "category": "system",
        "preferredText": "标准平台",
        "aliases": ["旧平台"],
        "forbiddenVariants": [],
        "definition": "",
        "contextKeywords": [],
        "priority": "high",
        "enabled": True,
        "note": "",
    }


def style_item(item_id="style-1"):
    return {
        "id": item_id,
        "type": "style",
        "scope": "word.smart_write",
        "name": "结论先行",
        "ruleText": "先写结论。",
        "positiveExample": "",
        "negativeExample": "",
        "contextKeywords": [],
        "alwaysApply": True,
        "priority": "medium",
        "enabled": True,
        "note": "",
    }


class StaticStore:
    def __init__(self, terms=None, styles=None):
        self.terms = list(terms or [])
        self.styles = list(styles or [])
        self.task_scopes = []

    def enabled_items(self, task_scope):
        self.task_scopes.append(task_scope)
        return list(self.terms), list(self.styles)


class BrokenStore:
    def __init__(self, error):
        self.error = error

    def enabled_items(self, task_scope):
        raise self.error


class SequenceClock:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


class MutableClock:
    def __init__(self, value):
        self.value = value
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.value

    def advance(self, seconds):
        with self.lock:
            self.value += seconds


class WritingPolicyServiceTests(unittest.TestCase):
    def setUp(self):
        service_module._reset_writing_policy_services()

    def tearDown(self):
        service_module._reset_writing_policy_services()

    def test_default_database_path_prefers_trimmed_environment_value(self):
        with patch.dict(
            os.environ,
            {"AI_WPS_WRITING_POLICY_DB": "  runtime/custom.db  "},
        ):
            self.assertEqual(default_database_path(), Path("runtime/custom.db"))

    def test_default_database_path_falls_back_to_repository_run_directory(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_WPS_WRITING_POLICY_DB", None)
            expected = (
                Path(service_module.__file__).resolve().parents[4]
                / "run"
                / "writing_policies.db"
            )

            self.assertEqual(default_database_path(), expected)

    def test_prepare_success_returns_match_statistics_and_safe_diagnostics(self):
        store = StaticStore([term_item()], [style_item()])
        service = WritingPolicyService(
            store=store,
            clock=SequenceClock(10.0, 10.125),
        )

        result = service.prepare("word.smart_write", ["请把旧平台写得更正式"])

        self.assertEqual(store.task_scopes, ["word.smart_write"])
        self.assertTrue(result.usage["applied"])
        self.assertFalse(result.usage["degraded"])
        self.assertEqual(result.usage["termMatchCount"], 1)
        self.assertEqual(result.usage["styleRuleCount"], 1)
        self.assertEqual(result.matched_item_ids, ("term-1", "style-1"))
        self.assertIn("写作规范", result.prompt_block)
        self.assertEqual(
            result.diagnostic_patch(),
            {
                "writingPolicyApplied": True,
                "writingPolicyDegraded": False,
                "writingPolicyErrorCode": "",
                "writingPolicyTermCount": 1,
                "writingPolicyStyleCount": 1,
                "writingPolicyTruncatedCount": 0,
                "writingPolicyElapsedMs": 125,
                "writingPolicyItemIds": ["term-1", "style-1"],
            },
        )
        diagnostics = service.diagnostics()
        self.assertEqual(diagnostics["stage"], "prepared")
        self.assertEqual(diagnostics["writingPolicyElapsedMs"], 125)
        self.assertNotIn("旧平台", json.dumps(diagnostics, ensure_ascii=False))

    def test_prepare_degrades_stably_for_writing_policy_os_and_unknown_errors(self):
        sensitive_source = "公司绝密原文"
        cases = (
            (
                WritingPolicyError("writing_policy_data_corrupt", "原文泄漏 /secret/db.sqlite"),
                "writing_policy_data_corrupt",
            ),
            (OSError("database unavailable at /secret/db.sqlite"), "writing_policy_io_error"),
            (RuntimeError("unexpected 公司绝密原文 /secret/path"), "writing_policy_internal_error"),
        )

        for error, expected_code in cases:
            with self.subTest(error=type(error).__name__):
                service = WritingPolicyService(
                    store=BrokenStore(error),
                    clock=SequenceClock(1.0, 1.01),
                )

                result = service.prepare("word.smart_write", [sensitive_source])

                self.assertEqual(result.prompt_block, "")
                self.assertFalse(result.usage["applied"])
                self.assertTrue(result.usage["degraded"])
                self.assertTrue(result.usage["degradedReason"])
                self.assertEqual(result.usage["termMatchCount"], 0)
                self.assertEqual(result.usage["styleRuleCount"], 0)
                self.assertEqual(result.usage["truncatedCount"], 0)
                self.assertEqual(result.usage["matchedItems"], [])
                self.assertEqual(result.matched_item_ids, ())
                self.assertEqual(
                    result.diagnostic_patch()["writingPolicyErrorCode"],
                    expected_code,
                )
                serialized = json.dumps(
                    {
                        "usage": result.usage,
                        "resultDiagnostic": result.diagnostic_patch(),
                        "serviceDiagnostic": service.diagnostics(),
                    },
                    ensure_ascii=False,
                )
                self.assertNotIn(sensitive_source, serialized)
                self.assertNotIn("/secret", serialized)
                self.assertNotIn(str(error), serialized)

    def test_prepare_replaces_invalid_writing_policy_error_code(self):
        service = WritingPolicyService(
            store=BrokenStore(WritingPolicyError("../../secret-path", "sensitive"))
        )

        result = service.prepare("word.smart_write", ["source"])

        self.assertEqual(
            result.diagnostic_patch()["writingPolicyErrorCode"],
            "writing_policy_error",
        )

    def test_clock_failure_or_negative_elapsed_never_breaks_preparation(self):
        class BrokenClock:
            def __call__(self):
                raise RuntimeError("clock unavailable /secret/time")

        for clock in (BrokenClock(), SequenceClock(5.0, 4.0)):
            with self.subTest(clock=type(clock).__name__):
                service = WritingPolicyService(
                    store=StaticStore([term_item()], []),
                    clock=clock,
                )

                result = service.prepare("word.smart_write", ["旧平台"])

                self.assertTrue(result.usage["applied"])
                self.assertFalse(result.usage["degraded"])
                self.assertEqual(
                    result.diagnostic_patch()["writingPolicyElapsedMs"], 0
                )
                self.assertNotIn("secret", str(service.diagnostics()))

    def test_diagnostics_returns_defensive_deep_copy(self):
        service = WritingPolicyService(
            store=StaticStore([term_item()], []),
        )
        service.prepare("word.smart_write", ["旧平台"])

        first = service.diagnostics()
        first["writingPolicyItemIds"].append("mutated")
        first["stage"] = "mutated"

        second = service.diagnostics()
        self.assertEqual(second["writingPolicyItemIds"], ["term-1"])
        self.assertEqual(second["stage"], "prepared")

    def test_singleton_is_keyed_by_resolved_path_and_changes_with_environment(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "one" / "writing_policies.db"
            equivalent_first_path = root / "one" / ".." / "one" / "writing_policies.db"
            second_path = root / "two" / "writing_policies.db"

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(first_path)},
            ):
                first = get_writing_policy_service()
            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(equivalent_first_path)},
            ):
                same = get_writing_policy_service()
            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(second_path)},
            ):
                second = get_writing_policy_service()

            self.assertIs(first, same)
            self.assertIsNot(first, second)
            self.assertEqual(first.store.db_path.resolve(), first_path.resolve())
            self.assertEqual(second.store.db_path.resolve(), second_path.resolve())

    def test_failed_store_construction_is_not_cached_and_later_success_is_reused(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_policies.db"
            successful_store = StaticStore([term_item()], [])
            clock = MutableClock(100.0)
            sensitive_error = OSError(
                "database unavailable at /secret/writing-policies.db"
            )

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=[sensitive_error, successful_store],
            ) as store_constructor, patch.object(
                service_module,
                "_INITIALIZATION_CLOCK",
                clock,
                create=True,
            ):
                failed = get_writing_policy_service()
                failed_result = failed.prepare("word.smart_write", ["公司原文"])
                in_backoff = get_writing_policy_service()
                clock.advance(5.0)
                recovered = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertTrue(failed_result.usage["degraded"])
            self.assertEqual(
                failed_result.diagnostic_patch()["writingPolicyErrorCode"],
                "writing_policy_io_error",
            )
            self.assertNotIn("/secret", str(failed.diagnostics()))
            self.assertIs(failed, in_backoff)
            self.assertIsNot(failed, recovered)
            self.assertIs(recovered, reused)
            self.assertEqual(store_constructor.call_count, 2)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )

    def test_invalid_expanduser_path_degrades_without_cache_and_recovers(self):
        invalid_path = "~ai_wps_codex_missing_user_42/secret/writing_policies.db"

        with patch.dict(
            os.environ,
            {"AI_WPS_WRITING_POLICY_DB": invalid_path},
        ):
            failed = get_writing_policy_service()
            failed_result = failed.prepare("word.smart_write", ["公司原文"])

        self.assertTrue(failed_result.usage["degraded"])
        self.assertEqual(
            failed_result.diagnostic_patch()["writingPolicyErrorCode"],
            "writing_policy_internal_error",
        )
        self.assertNotIn(invalid_path, str(failed_result.diagnostic_patch()))
        self.assertNotIn(invalid_path, str(failed.diagnostics()))
        self.assertEqual(service_module._SERVICES_BY_PATH, {})

        with TemporaryDirectory() as tmp:
            valid_path = Path(tmp) / "writing_policies.db"
            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(valid_path)},
            ):
                recovered = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertIsNot(failed, recovered)
            self.assertIs(recovered, reused)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["公司原文"]).usage["degraded"]
            )

    def test_concurrent_failure_backoff_and_recovery_are_singleflight(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_policies.db"
            clock = MutableClock(200.0)
            state_lock = threading.Lock()
            state = {"calls": 0, "failing": True}
            retry_entered = threading.Event()
            release_retry = threading.Event()
            successful_store = StaticStore([term_item()], [])

            def construct_store(path):
                with state_lock:
                    state["calls"] += 1
                    failing = state["failing"]
                if failing:
                    raise OSError("database unavailable at /secret/writing_policies.db")
                retry_entered.set()
                release_retry.wait(timeout=2)
                return successful_store

            def run_wave(wait_for_retry=False):
                barrier = threading.Barrier(12)
                results = []
                errors = []
                result_lock = threading.Lock()
                followers_done = threading.Event()

                def load_service():
                    try:
                        barrier.wait(timeout=2)
                        result = get_writing_policy_service()
                        with result_lock:
                            results.append(result)
                            if len(results) >= 11:
                                followers_done.set()
                    except Exception as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=load_service) for _ in range(12)]
                for thread in threads:
                    thread.start()
                followers_returned = True
                if wait_for_retry:
                    self.assertTrue(retry_entered.wait(timeout=1))
                    followers_returned = followers_done.wait(timeout=1)
                    release_retry.set()
                for thread in threads:
                    thread.join(timeout=2)
                self.assertEqual(errors, [])
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                return results, followers_returned

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=construct_store,
            ), patch.object(
                service_module,
                "_INITIALIZATION_CLOCK",
                clock,
                create=True,
            ):
                failed_results, _ = run_wave()
                calls_after_failure = state["calls"]
                backoff_results = [
                    get_writing_policy_service() for _ in range(5)
                ]
                calls_during_backoff = state["calls"]

                with state_lock:
                    state["failing"] = False
                clock.advance(5.0)
                retry_results, retry_followers_returned = run_wave(
                    wait_for_retry=True
                )
                recovered = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertEqual(len(failed_results), 12)
            self.assertTrue(
                all(result.prepare("word.smart_write", [""]).usage["degraded"] for result in failed_results)
            )
            self.assertEqual(calls_after_failure, 1)
            self.assertEqual(calls_during_backoff, 1)
            self.assertTrue(all(result is failed_results[0] for result in backoff_results))
            self.assertTrue(retry_followers_returned)
            self.assertEqual(len(retry_results), 12)
            self.assertEqual(state["calls"], 2)
            self.assertIs(recovered, reused)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )

    def test_slow_initialization_returns_initializing_degradation_to_followers(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_policies.db"
            constructor_entered = threading.Event()
            release_constructor = threading.Event()
            follower_done = threading.Event()
            initializer_results = []
            follower_results = []

            def construct_store(path):
                constructor_entered.set()
                release_constructor.wait(timeout=2)
                return StaticStore([term_item()], [])

            def initialize():
                initializer_results.append(get_writing_policy_service())

            def follow():
                follower_results.append(get_writing_policy_service())
                follower_done.set()

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=construct_store,
            ) as store_constructor:
                initializer = threading.Thread(target=initialize)
                follower = threading.Thread(target=follow)
                initializer.start()
                self.assertTrue(constructor_entered.wait(timeout=1))
                follower.start()
                follower_returned_before_release = follower_done.wait(timeout=1)
                release_constructor.set()
                initializer.join(timeout=2)
                follower.join(timeout=2)

            self.assertTrue(follower_returned_before_release)
            self.assertFalse(initializer.is_alive())
            self.assertFalse(follower.is_alive())
            self.assertEqual(store_constructor.call_count, 1)
            self.assertFalse(
                initializer_results[0].prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )
            follower_result = follower_results[0].prepare(
                "word.smart_write", ["公司原文"]
            )
            self.assertTrue(follower_result.usage["degraded"])
            self.assertEqual(
                follower_result.diagnostic_patch()["writingPolicyErrorCode"],
                "writing_policy_initializing",
            )

    def test_slow_initialization_for_one_path_does_not_block_another_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = (root / "first.db").resolve()
            second_path = (root / "second.db").resolve()
            first_entered = threading.Event()
            release_first = threading.Event()
            second_done = threading.Event()
            results = {}

            def configured_path():
                if threading.current_thread().name == "writing_policy-path-first":
                    return first_path
                return second_path

            def construct_store(path):
                if path == first_path:
                    first_entered.set()
                    release_first.wait(timeout=2)
                return StaticStore([], [])

            def load(name):
                results[name] = get_writing_policy_service()
                if name == "second":
                    second_done.set()

            with patch.object(
                service_module,
                "default_database_path",
                side_effect=configured_path,
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=construct_store,
            ) as store_constructor:
                first = threading.Thread(
                    target=load,
                    args=("first",),
                    name="writing_policy-path-first",
                )
                second = threading.Thread(
                    target=load,
                    args=("second",),
                    name="writing_policy-path-second",
                )
                first.start()
                self.assertTrue(first_entered.wait(timeout=1))
                second.start()
                second_returned_before_release = second_done.wait(timeout=1)
                release_first.set()
                first.join(timeout=2)
                second.join(timeout=2)

            self.assertTrue(second_returned_before_release)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(store_constructor.call_count, 2)
            self.assertIsNot(results["first"], results["second"])

    def test_failure_backoff_is_isolated_by_resolved_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed_path = (root / "failed.db").resolve()
            healthy_path = (root / "healthy.db").resolve()
            configured_paths = [failed_path, healthy_path]

            def construct_store(path):
                if path == failed_path:
                    raise OSError("database unavailable at /secret/failed.db")
                return StaticStore([term_item()], [])

            with patch.object(
                service_module,
                "default_database_path",
                side_effect=configured_paths,
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=construct_store,
            ) as store_constructor:
                failed = get_writing_policy_service()
                healthy = get_writing_policy_service()

            self.assertTrue(
                failed.prepare("word.smart_write", ["公司原文"]).usage["degraded"]
            )
            self.assertFalse(
                healthy.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )
            self.assertEqual(store_constructor.call_args_list[0].args, (failed_path,))
            self.assertEqual(store_constructor.call_args_list[1].args, (healthy_path,))

    def test_base_exception_during_construction_releases_inflight_state(self):
        class InitializationAbort(BaseException):
            pass

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_policies.db"
            successful_store = StaticStore([term_item()], [])

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=[InitializationAbort(), successful_store],
            ) as store_constructor:
                with self.assertRaises(InitializationAbort):
                    get_writing_policy_service()
                recovered = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertEqual(store_constructor.call_count, 2)
            self.assertIs(recovered, reused)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )

    def test_base_exception_from_retry_clock_releases_inflight_and_recovers(self):
        class RetryClockAbort(BaseException):
            pass

        class FailingRetryClock:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                if self.calls == 1:
                    return 300.0
                raise RetryClockAbort()

        with TemporaryDirectory() as tmp:
            db_path = (Path(tmp) / "writing_policies.db").resolve()
            successful_store = StaticStore([term_item()], [])
            failing_clock = FailingRetryClock()

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=[OSError("database unavailable"), successful_store],
            ) as store_constructor:
                with patch.object(
                    service_module,
                    "_INITIALIZATION_CLOCK",
                    failing_clock,
                ):
                    with self.assertRaises(RetryClockAbort):
                        get_writing_policy_service()

                self.assertNotIn(db_path, service_module._INITIALIZING_BY_PATH)
                self.assertNotIn(db_path, service_module._INITIALIZATION_FAILURES)

                with patch.object(
                    service_module,
                    "_INITIALIZATION_CLOCK",
                    MutableClock(400.0),
                ):
                    recovered = get_writing_policy_service()
                    reused = get_writing_policy_service()

            self.assertEqual(store_constructor.call_count, 2)
            self.assertIs(recovered, reused)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )

    def test_base_exception_during_success_publish_releases_inflight(self):
        class PublishAbort(BaseException):
            pass

        class FailingServiceCache(dict):
            def __init__(self):
                super().__init__()
                self.fail_next_publish = True

            def __setitem__(self, key, value):
                if self.fail_next_publish:
                    self.fail_next_publish = False
                    raise PublishAbort()
                super().__setitem__(key, value)

        with TemporaryDirectory() as tmp:
            db_path = (Path(tmp) / "writing_policies.db").resolve()
            service_cache = FailingServiceCache()

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "_SERVICES_BY_PATH",
                service_cache,
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=[StaticStore(), StaticStore([term_item()], [])],
            ) as store_constructor:
                with self.assertRaises(PublishAbort):
                    get_writing_policy_service()

                self.assertNotIn(db_path, service_module._INITIALIZING_BY_PATH)
                self.assertEqual(service_cache, {})

                recovered = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertEqual(store_constructor.call_count, 2)
            self.assertIs(recovered, reused)
            self.assertFalse(
                recovered.prepare("word.smart_write", ["旧平台"]).usage["degraded"]
            )

    def test_reset_clears_success_failure_and_inflight_states(self):
        path = Path("/tmp/writing-policies-reset.db").resolve()
        service_module._SERVICES_BY_PATH[path] = WritingPolicyService(
            StaticStore()
        )
        service_module._INITIALIZATION_FAILURES[path] = object()
        service_module._INITIALIZING_BY_PATH[path] = object()

        service_module._reset_writing_policy_services()

        self.assertEqual(service_module._SERVICES_BY_PATH, {})
        self.assertEqual(service_module._INITIALIZATION_FAILURES, {})
        self.assertEqual(service_module._INITIALIZING_BY_PATH, {})

    def test_singleton_concurrent_access_constructs_one_instance(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_policies.db"
            barrier = threading.Barrier(12)
            services = []
            errors = []
            real_store_class = service_module.WritingPolicyStore
            constructed_paths = []

            def construct_store(path):
                constructed_paths.append(path)
                return real_store_class(path)

            def load_service():
                try:
                    barrier.wait(timeout=2)
                    services.append(get_writing_policy_service())
                except Exception as exc:
                    errors.append(exc)

            with patch.dict(
                os.environ,
                {"AI_WPS_WRITING_POLICY_DB": str(db_path)},
            ), patch.object(
                service_module,
                "WritingPolicyStore",
                side_effect=construct_store,
            ):
                threads = [threading.Thread(target=load_service) for _ in range(12)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
                cached = get_writing_policy_service()
                reused = get_writing_policy_service()

            self.assertEqual(errors, [])
            self.assertEqual(len(services), 12)
            self.assertEqual(constructed_paths, [db_path.resolve()])
            self.assertIs(cached, reused)
            for service in services:
                result = service.prepare("word.smart_write", ["公司原文"])
                if service is cached:
                    self.assertFalse(result.usage["degraded"])
                else:
                    self.assertTrue(result.usage["degraded"])
                    self.assertEqual(
                        result.diagnostic_patch()["writingPolicyErrorCode"],
                        "writing_policy_initializing",
                    )


if __name__ == "__main__":
    unittest.main()
