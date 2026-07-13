import importlib.util
import threading
import time
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import PptSlideAssistantRequest
    from app.services.ppt.slide_assistant import (
        PptSlideAssistant,
        determine_ppt_slide_mode,
        normalize_ppt_slide_request,
    )
    from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore

if HAS_PYDANTIC and HAS_FASTAPI:
    from app.api import ppt as ppt_api


def parse_ppt_request(payload):
    if hasattr(PptSlideAssistantRequest, "model_validate"):
        return PptSlideAssistantRequest.model_validate(payload)
    return PptSlideAssistantRequest.parse_obj(payload)


class RecordingPptProvider:
    def __init__(self):
        self.calls = []

    def ppt_slide_assistant(self, context, user_instruction, mode, trace_id):
        self.calls.append(
            {
                "context": context,
                "userInstruction": user_instruction,
                "mode": mode,
                "traceId": trace_id,
            }
        )
        return {
            "modeUsed": mode,
            "suggestedTitle": "项目总体进展",
            "bullets": ["完成总体方案设计", "进入接口联调", "关注接口稳定性"],
            "conclusion": "项目按计划推进。",
            "plainText": "项目总体进展\n\n1. 完成总体方案设计",
            "rawAnswer": None,
            "parseFallbackReason": None,
            "provider": "provider-test",
        }


class BlockingPptAssistant:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def assist(self, request, trace_id):
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {
            "modeUsed": "optimize",
            "suggestedTitle": "后台任务完成",
            "bullets": ["要点一", "要点二", "要点三"],
            "conclusion": "处理完成。",
            "plainText": "后台任务完成",
            "rawAnswer": None,
            "parseFallbackReason": None,
            "provider": "job-test",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for PPT slide assistant tests")
class PptSlideAssistantTests(unittest.TestCase):
    def _request(
        self,
        title="项目进展",
        subtitle="阶段成果与当前重点",
        text_blocks=None,
        previous_title="项目背景",
        next_title="风险与措施",
        instruction="面向管理层，突出进展和风险。",
        client_job_id="",
    ):
        return parse_ppt_request(
            {
                "presentationId": "汇报材料.pptx",
                "scene": "ppt",
                "clientJobId": client_job_id,
                "slide": {
                    "index": 2,
                    "title": title,
                    "subtitle": subtitle,
                    "textBlocks": text_blocks
                    if text_blocks is not None
                    else ["总体方案设计已完成", "正在开展接口联调"],
                    "previousTitle": previous_title,
                    "nextTitle": next_title,
                    "truncated": False,
                },
                "userInstruction": instruction,
            }
        )

    def test_normalize_ppt_slide_request_enforces_all_budgets(self):
        result = normalize_ppt_slide_request(
            self._request(
                title="题" * 250,
                subtitle="副" * 400,
                text_blocks=["甲" * 1200, "乙" * 1800, "丙" * 1800],
                previous_title="前" * 250,
                next_title="后" * 250,
                instruction="要求" * 700,
            )
        )

        self.assertEqual(len(result["title"]), 200)
        self.assertEqual(len(result["subtitle"]), 300)
        self.assertEqual(max(map(len, result["textBlocks"])), 1000)
        self.assertLessEqual(len(result["subtitle"]) + sum(map(len, result["textBlocks"])), 3000)
        self.assertEqual(len(result["previousTitle"]), 200)
        self.assertEqual(len(result["nextTitle"]), 200)
        self.assertEqual(len(result["userInstruction"]), 1000)
        self.assertTrue(result["truncated"])

    def test_determine_mode_counts_only_body_non_whitespace(self):
        self.assertEqual(
            determine_ppt_slide_mode({"textBlocks": ["有效正文达到二十个非空白字符用于优化模式判定"]}),
            "optimize",
        )
        self.assertEqual(determine_ppt_slide_mode({"textBlocks": ["短内容"]}), "generate")
        self.assertEqual(
            determine_ppt_slide_mode({"subtitle": "只有副标题", "textBlocks": []}),
            "generate",
        )

    def test_assistant_requires_instruction_for_generate_mode(self):
        assistant = PptSlideAssistant(provider_client=RecordingPptProvider())

        with self.assertRaises(AdapterError) as error:
            assistant.assist(
                self._request(text_blocks=[], instruction=""),
                trace_id="trace-ppt-empty-instruction",
            )

        self.assertEqual(error.exception.code, "PPT_SLIDE_INSTRUCTION_REQUIRED")

    def test_assistant_requires_current_slide(self):
        assistant = PptSlideAssistant(provider_client=RecordingPptProvider())
        request = self._request()
        request.slide = None

        with self.assertRaises(AdapterError) as error:
            assistant.assist(request, trace_id="trace-ppt-no-slide")

        self.assertEqual(error.exception.code, "PPT_SLIDE_REQUIRED")

    def test_assistant_sends_normalized_optimize_request_to_provider(self):
        provider = RecordingPptProvider()
        assistant = PptSlideAssistant(provider_client=provider)

        result = assistant.assist(
            self._request(
                text_blocks=["总体方案设计已经完成并通过评审", "当前正在开展跨系统接口联调工作"]
            ),
            trace_id="trace-ppt-assist",
        )

        self.assertEqual(provider.calls[0]["mode"], "optimize")
        self.assertEqual(provider.calls[0]["context"]["subtitle"], "阶段成果与当前重点")
        self.assertEqual(provider.calls[0]["traceId"], "trace-ppt-assist")
        self.assertEqual(result["suggestedTitle"], "项目总体进展")

    def test_job_store_is_idempotent_and_completes_in_background(self):
        assistant = BlockingPptAssistant()
        store = PptSlideAssistantJobStore(assistant=assistant)
        request = self._request(client_job_id="client-ppt-slide-recovery")

        started = store.start(request, trace_id="trace-ppt-first")
        duplicate = store.start(request, trace_id="trace-ppt-second")

        self.assertEqual(started["jobId"], "client-ppt-slide-recovery")
        self.assertEqual(duplicate["traceId"], "trace-ppt-first")
        self.assertEqual(duplicate["status"], "running")
        self.assertEqual(duplicate["providerTimeoutSeconds"], 1800)
        self.assertIn("模型后台", duplicate["runningMessage"])
        self.assertTrue(assistant.started.wait(timeout=1))
        self.assertEqual(assistant.call_count, 1)

        assistant.release.set()
        completed = None
        for _ in range(50):
            completed = store.get("client-ppt-slide-recovery")
            if completed and completed["status"] == "completed":
                break
            time.sleep(0.02)

        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["suggestedTitle"], "后台任务完成")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for PPT route tests")
    def test_route_submit_status_and_not_found_envelopes(self):
        assistant = BlockingPptAssistant()
        store = PptSlideAssistantJobStore(assistant=assistant)
        original_store = ppt_api.ppt_slide_jobs
        ppt_api.ppt_slide_jobs = store
        try:
            submitted = ppt_api.start_ppt_slide_assistant_job(
                self._request(client_job_id="client-ppt-route-recovery")
            )
            running = ppt_api.get_ppt_slide_assistant_job("client-ppt-route-recovery")
            missing = ppt_api.get_ppt_slide_assistant_job("missing-ppt-job")
        finally:
            assistant.release.set()
            ppt_api.ppt_slide_jobs = original_store

        self.assertTrue(submitted["success"])
        self.assertEqual(submitted["taskType"], "ppt.slide_assistant")
        self.assertEqual(running["data"]["status"], "running")
        self.assertEqual(missing.status_code, 404)
        self.assertIn(b"PPT_SLIDE_JOB_NOT_FOUND", missing.body)


if __name__ == "__main__":
    unittest.main()
