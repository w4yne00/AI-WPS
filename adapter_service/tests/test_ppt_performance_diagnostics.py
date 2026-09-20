import base64
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from app.core.errors import AdapterError, ProviderTimeoutError
from app.core.models import (
    PptSlideAssistantRequest,
    PptStructureReviewRequest,
)
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore
from app.services.ppt.structure_review import PptStructureReviewer
from app.services.ppt.structure_review_jobs import PptStructureReviewJobStore


class PptPerformanceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = LongTaskCoordinator()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_history_dir = os.environ.get("AI_WPS_TASK_HISTORY_DIR")
        os.environ["AI_WPS_TASK_HISTORY_DIR"] = os.path.join(self.temp_dir.name, "history")

    def tearDown(self):
        self.temp_dir.cleanup()
        if self._old_history_dir is None:
            os.environ.pop("AI_WPS_TASK_HISTORY_DIR", None)
        else:
            os.environ["AI_WPS_TASK_HISTORY_DIR"] = self._old_history_dir

    def test_ppt_slide_assistant_slide_success_records_millisecond_metrics_and_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_slide_assistant(context, user_instruction, mode, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 105,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 380,
                    "parseMs": 15,
                })
            return {
                "suggestedTitle": "优化标题",
                "bullets": ["要点一", "要点二"],
                "conclusion": "结论部分",
                "plainText": "优化标题\n- 要点一\n- 要点二\n结论部分",
                "provider": "direct-model",
            }

        fake_provider_client.ppt_slide_assistant.side_effect = fake_slide_assistant

        assistant = PptSlideAssistant(provider_client=fake_provider_client)
        store = PptSlideAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req = PptSlideAssistantRequest.parse_obj({
            "presentationId": "pres-perf-1",
            "scene": "ppt",
            "sourceMode": "slide",
            "slide": {
                "index": 1,
                "title": "原标题",
                "subtitle": "副标题",
                "textBlocks": ["正文块一包含足够的字符数以触发优化模式。这一段文本超过了二十个字符门槛。"],
            },
            "userInstruction": "精简语句",
            "clientJobId": "ppt-slide-perf-1",
            "documentSessionId": "session-ppt-1",
        })

        res = store.start(req, trace_id="trace-ppt-slide-1")
        self.assertEqual(res["jobId"], "ppt-slide-perf-1")

        completed = self.coordinator.wait("ppt-slide-perf-1", task_type="ppt.slide_assistant")
        self.assertEqual(completed["status"], "completed")

        # 毫秒级总耗时与阶段耗时
        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseElapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)
        self.assertIsInstance(completed.get("terminalAgeMs"), int)
        self.assertGreaterEqual(completed["terminalAgeMs"], 0)

        # 秒级兼容字段保留
        self.assertIn("elapsedSeconds", completed)
        self.assertIn("phaseElapsedSeconds", completed)
        self.assertIn("phaseDurations", completed)

        # 真实阶段记录
        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)

        # 阻塞调用首包时间为 None
        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 105)
        self.assertEqual(metrics.get("providerCompleteMs"), 380)
        self.assertEqual(metrics.get("parseMs"), 15)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")

        # 终态诊断
        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "ppt-slide-perf-1"][0]
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "success")
        self.assertEqual(recent.get("errorCode"), "")
        self.assertIn("phaseDurationsMs", recent)

    def test_ppt_slide_assistant_document_success_records_uploading_and_metrics(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_document_summary(staged, slide_count, user_instruction, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback:
                progress_callback("provider_processing")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 150,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 600,
                    "parseMs": 25,
                })
            return {
                "resultType": "document",
                "deckTitle": "文档总结方案",
                "documentSummary": "文档概要",
                "recommendedSlideCount": 5,
                "slides": [{"index": 1, "title": "第一页", "bulletPoints": ["要点1"]}],
                "plainText": "文档总结方案",
                "provider": "direct-model",
            }

        fake_provider_client.ppt_document_summary.side_effect = fake_document_summary

        assistant = PptSlideAssistant(provider_client=fake_provider_client)
        store = PptSlideAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        content_bytes = b"# Document Content\nSome detailed text"
        b64 = base64.b64encode(content_bytes).decode("ascii")
        stored = store.document_file_store.store("方案.md", "text/markdown", len(content_bytes), b64)
        token = stored["fileToken"]

        req = PptSlideAssistantRequest.parse_obj({
            "presentationId": "pres-perf-doc-1",
            "scene": "ppt",
            "sourceMode": "document",
            "fileToken": token,
            "requestedSlideCount": 5,
            "userInstruction": "提炼要点",
            "clientJobId": "ppt-doc-perf-1",
            "documentSessionId": "session-ppt-doc-1",
        })

        res = store.start(req, trace_id="trace-ppt-doc-1")
        self.assertEqual(res["jobId"], "ppt-doc-perf-1")

        completed = self.coordinator.wait("ppt-doc-perf-1", task_type="ppt.slide_assistant")
        self.assertEqual(completed["status"], "completed")

        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("uploading", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))

    def test_ppt_slide_assistant_timeout_records_provider_timeout_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_timeout(context, user_instruction, mode, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 200,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": None,
                    "parseMs": None,
                })
            raise ProviderTimeoutError("智能总结请求超时。")

        fake_provider_client.ppt_slide_assistant.side_effect = fake_timeout

        assistant = PptSlideAssistant(provider_client=fake_provider_client)
        store = PptSlideAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req = PptSlideAssistantRequest.parse_obj({
            "presentationId": "pres-perf-timeout",
            "scene": "ppt",
            "sourceMode": "slide",
            "slide": {
                "index": 1,
                "title": "原标题",
                "subtitle": "副标题",
                "textBlocks": ["正文文本超过二十个字符以便触发优化模式。"],
            },
            "userInstruction": "精简语句",
            "clientJobId": "ppt-slide-timeout-1",
            "documentSessionId": "session-ppt-timeout",
        })

        store.start(req, trace_id="trace-ppt-timeout-1")
        completed = self.coordinator.wait("ppt-slide-timeout-1", task_type="ppt.slide_assistant")
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["metrics"].get("providerOutcome"), "provider_timeout")
        self.assertEqual(completed.get("providerOutcome"), "provider_timeout")

        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "ppt-slide-timeout-1"][0]
        self.assertEqual(recent.get("providerOutcome"), "provider_timeout")
        self.assertEqual(recent.get("errorCode"), "PROVIDER_TIMEOUT")

    def test_ppt_slide_assistant_unconfigured_records_not_attempted_for_both_sources(self):
        for source_mode in ("slide", "document"):
            with self.subTest(source_mode=source_mode):
                coordinator = LongTaskCoordinator()
                fake_provider_client = MagicMock()
                fake_provider_client.resolve_task_auth.return_value = {
                    "accessMethod": "direct_model",
                    "providerBaseUrl": "",
                    "apiKey": "",
                    "modelName": "",
                }
                unconfigured = AdapterError(
                    "MODEL_CONFIG_INCOMPLETE",
                    "未配置模型",
                    status_code=400,
                )
                fake_provider_client.ppt_slide_assistant.side_effect = unconfigured
                fake_provider_client.ppt_document_summary.side_effect = unconfigured

                assistant = PptSlideAssistant(provider_client=fake_provider_client)
                store = PptSlideAssistantJobStore(
                    assistant=assistant,
                    coordinator=coordinator,
                )
                payload = {
                    "presentationId": "pres-perf-unconfigured-" + source_mode,
                    "scene": "ppt",
                    "sourceMode": source_mode,
                    "clientJobId": "ppt-unconfigured-" + source_mode,
                    "documentSessionId": "session-unconfigured-" + source_mode,
                }
                if source_mode == "slide":
                    payload.update({
                        "slide": {
                            "index": 1,
                            "title": "原标题",
                            "subtitle": "副标题",
                            "textBlocks": ["正文文本超过二十个字符以便触发优化模式。"],
                        },
                        "userInstruction": "精简语句",
                    })
                else:
                    content_bytes = b"# Document Content\nSome detailed text"
                    stored = store.document_file_store.store(
                        "方案.md",
                        "text/markdown",
                        len(content_bytes),
                        base64.b64encode(content_bytes).decode("ascii"),
                    )
                    payload.update({
                        "fileToken": stored["fileToken"],
                        "requestedSlideCount": 5,
                        "userInstruction": "提炼要点",
                    })

                request = PptSlideAssistantRequest.parse_obj(payload)
                store.start(request, trace_id="trace-unconfigured-" + source_mode)
                completed = coordinator.wait(
                    payload["clientJobId"],
                    task_type="ppt.slide_assistant",
                )

                self.assertEqual(completed["status"], "failed")
                self.assertEqual(
                    completed["metrics"].get("providerOutcome"),
                    "not_attempted",
                )
                self.assertEqual(completed.get("providerOutcome"), "not_attempted")

    def test_ppt_structure_review_success_records_millisecond_metrics_and_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_structure_review(request, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 120,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 450,
                    "parseMs": 18,
                })
            return {
                "overallStoryline": "结构清晰完整",
                "inferredChapters": [{"title": "第一章", "startSlide": 1, "endSlide": 3}],
                "highPriorityIssues": [],
                "generalSuggestions": [],
                "slideRecommendations": [],
                "recommendedOutline": [],
                "provider": "direct-model",
            }

        fake_provider_client.ppt_structure_review.side_effect = fake_structure_review

        reviewer = PptStructureReviewer(provider_client=fake_provider_client)
        store = PptStructureReviewJobStore(reviewer=reviewer, coordinator=self.coordinator)

        req = PptStructureReviewRequest.parse_obj({
            "presentationId": "pres-perf-struct-1",
            "scene": "ppt",
            "clientJobId": "ppt-structure-perf-1",
            "documentSessionId": "session-ppt-struct-1",
            "scope": {
                "totalSlides": 3,
                "startSlide": 1,
                "endSlide": 3,
            },
            "slides": [
                {"index": 1, "title": "封面", "subtitle": "汇报", "bodyFallback": ""},
                {"index": 2, "title": "进展", "subtitle": "", "bodyFallback": ""},
                {"index": 3, "title": "总结", "subtitle": "", "bodyFallback": ""},
            ],
        })

        res = store.start(req, trace_id="trace-ppt-struct-1")
        self.assertEqual(res["jobId"], "ppt-structure-perf-1")

        completed = self.coordinator.wait("ppt-structure-perf-1", task_type="ppt.structure_review")
        self.assertEqual(completed["status"], "completed")

        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)

        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 120)
        self.assertEqual(metrics.get("providerCompleteMs"), 450)
        self.assertEqual(metrics.get("parseMs"), 18)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")

    def test_ppt_structure_review_unconfigured_records_not_attempted_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = False
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "",
            "apiKey": "",
            "modelName": "",
        }
        fake_provider_client.ppt_structure_review.side_effect = AdapterError(
            "MODEL_CONFIG_INCOMPLETE",
            "未配置模型",
            status_code=400,
        )

        reviewer = PptStructureReviewer(provider_client=fake_provider_client)
        store = PptStructureReviewJobStore(reviewer=reviewer, coordinator=self.coordinator)

        req = PptStructureReviewRequest.parse_obj({
            "presentationId": "pres-perf-struct-unconf",
            "scene": "ppt",
            "clientJobId": "ppt-structure-unconf-1",
            "documentSessionId": "session-ppt-struct-unconf",
            "scope": {
                "totalSlides": 2,
                "startSlide": 1,
                "endSlide": 2,
            },
            "slides": [
                {"index": 1, "title": "封面", "subtitle": "", "bodyFallback": ""},
                {"index": 2, "title": "结束", "subtitle": "", "bodyFallback": ""},
            ],
        })

        store.start(req, trace_id="trace-ppt-unconf-1")
        completed = self.coordinator.wait("ppt-structure-unconf-1", task_type="ppt.structure_review")
        self.assertEqual(completed["status"], "completed")

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerOutcome"), "not_attempted")
        self.assertEqual(completed.get("providerOutcome"), "not_attempted")


if __name__ == "__main__":
    unittest.main()
