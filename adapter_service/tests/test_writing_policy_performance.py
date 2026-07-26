import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.writing_policy.service import WritingPolicyService
from app.services.writing_policy.store import WritingPolicyStore


class WritingPolicyPerformanceTests(unittest.TestCase):
    def test_three_word_policy_paths_stay_within_configured_local_budget(self):
        target_ms = int(
            os.getenv(
                "AI_WPS_WRITING_POLICY_PERFORMANCE_TARGET_MS",
                "100",
            )
        )
        samples_ms = []
        source_text = (
            "网络安全技术方案由运维部门负责实施，计划于2026年8月完成验收。"
        )

        with TemporaryDirectory() as tmp:
            service = WritingPolicyService(
                WritingPolicyStore(Path(tmp) / "writing_policies.db"),
                performance_target_ms=target_ms,
            )
            for task_scope in (
                "word.smart_write",
                "word.smart_imitation",
                "word.document_review",
            ):
                for _ in range(10):
                    started_at = time.perf_counter()
                    prepared = service.prepare(
                        task_scope,
                        [source_text],
                        scene="cybersecurity",
                    )
                    if task_scope == "word.document_review":
                        service.audit_document_review(
                            prepared,
                            source_text,
                        )
                    else:
                        service.audit(
                            prepared,
                            source_text,
                            source_text,
                        )
                    samples_ms.append(
                        (time.perf_counter() - started_at) * 1000
                    )

        self.assertLessEqual(max(samples_ms), target_ms)


if __name__ == "__main__":
    unittest.main()
