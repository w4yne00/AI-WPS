import importlib.util
from io import BytesIO
import time
import unittest


HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import PptStructureReviewRequest
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.ppt.structure_review import PptStructureReviewer
    from app.services.ppt.structure_review_jobs import PptStructureReviewJobStore
    from app.services.provider_client import (
        build_ppt_structure_review_prompt,
        parse_ppt_structure_review_answer,
    )

if HAS_PYDANTIC and HAS_FASTAPI:
    from app import main as app_main
    from app.api import ppt as ppt_api
    from fastapi.testclient import TestClient


def parse_request(payload):
    if hasattr(PptStructureReviewRequest, "model_validate"):
        return PptStructureReviewRequest.model_validate(payload)
    return PptStructureReviewRequest.parse_obj(payload)


def request_payload(
    slides=None,
    total_slides=5,
    start_slide=1,
    end_slide=5,
    client_job_id="client-ppt-structure-01",
):
    return {
        "presentationId": "项目汇报.pptx",
        "scene": "ppt",
        "clientJobId": client_job_id,
        "scope": {
            "totalSlides": total_slides,
            "startSlide": start_slide,
            "endSlide": end_slide,
        },
        "slides": slides
        if slides is not None
        else [
            {"index": 1, "title": "1. 项目背景", "subtitle": "建设依据"},
            {"index": 2, "title": "2. 建设目标", "subtitle": "总体目标"},
            {"index": 3, "title": "", "subtitle": "", "bodyFallback": "系统总体架构"},
            {"index": 4, "title": "4. 实施计划", "subtitle": "里程碑"},
            {"index": 5, "title": "4. 实施计划", "subtitle": "保障措施"},
        ],
    }


class RecordingProvider:
    def __init__(self):
        self.calls = []
        self.auth = {
            "providerBaseUrl": "https://model.example.test/v1",
            "providerChatPath": "/chat-messages",
            "providerMode": "blocking",
            "providerInputMode": "legacy-input-query",
            "apiKey": "structure-review-secret",
            "authSource": "workflow-profile:structure-v1",
        }

    def resolve_task_auth(self, task_type):
        self.calls.append({"snapshotTaskType": task_type})
        return dict(self.auth)

    def ppt_structure_review(
        self,
        request,
        trace_id,
        task_auth=None,
        progress_callback=None,
    ):
        self.calls.append(
            {
                "request": request,
                "traceId": trace_id,
                "taskAuth": task_auth,
            }
        )
        if progress_callback:
            progress_callback("parsing")
        return {
            "overallStoryline": "从建设背景进入目标与实施安排，但方案章节存在缺口。",
            "inferredChapters": [
                {"title": "背景与目标", "startSlide": 1, "endSlide": 2},
                {"title": "实施安排", "startSlide": 3, "endSlide": 5},
            ],
            "highPriorityIssues": [
                {
                    "code": "missing_title",
                    "message": "第 3 页缺少主标题。",
                    "slideNumbers": [3],
                },
                {
                    "code": "content_gap",
                    "message": "缺少总体方案章节。",
                    "slideNumbers": [2, 3],
                },
            ],
            "generalSuggestions": [
                {
                    "code": "ordering",
                    "message": "先说明总体方案，再进入实施计划。",
                    "slideNumbers": [3, 4],
                }
            ],
            "slideRecommendations": [
                {"slideNumber": 3, "suggestion": "补充总体方案标题并明确本页角色。"}
            ],
            "recommendedOutline": [
                {"order": 1, "title": "项目背景", "slideNumbers": [1]},
                {"order": 2, "title": "建设目标", "slideNumbers": [2]},
                {"order": 3, "title": "总体方案", "slideNumbers": [3]},
                {"order": 4, "title": "实施计划", "slideNumbers": [4, 5]},
            ],
            "rawAnswer": None,
            "parseFallbackReason": None,
            "provider": "provider-test",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required")
class PptStructureReviewTests(unittest.TestCase):
    def test_full_deck_over_sixty_slides_is_rejected_before_provider_call(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)
        slides = [
            {"index": index, "title": "第 {0} 页".format(index)}
            for index in range(1, 62)
        ]

        with self.assertRaises(AdapterError) as error:
            reviewer.review(
                parse_request(
                    request_payload(
                        slides=slides,
                        total_slides=61,
                        start_slide=1,
                        end_slide=61,
                    )
                ),
                trace_id="trace-structure-too-large",
            )

        self.assertEqual(error.exception.code, "PPT_STRUCTURE_RANGE_TOO_LARGE")
        self.assertEqual(
            [call for call in provider.calls if "request" in call],
            [],
        )

    def test_invalid_page_ranges_have_specific_chinese_feedback(self):
        cases = [
            (
                {"totalSlides": 5, "startSlide": 1.5, "endSlide": 5},
                "PPT_STRUCTURE_PAGE_INVALID",
                "起始页和结束页必须为正整数。",
            ),
            (
                {"totalSlides": 5, "startSlide": "nan", "endSlide": 5},
                "PPT_STRUCTURE_PAGE_INVALID",
                "起始页和结束页必须为正整数。",
            ),
            (
                {"totalSlides": 5, "startSlide": 5, "endSlide": 4},
                "PPT_STRUCTURE_RANGE_REVERSED",
                "结束页不能小于起始页。",
            ),
            (
                {"totalSlides": 5, "startSlide": 1, "endSlide": 6},
                "PPT_STRUCTURE_PAGE_OUT_OF_RANGE",
                "起止页必须在 1 至 5 页之间。",
            ),
        ]
        for scope, code, message in cases:
            with self.subTest(code=code):
                provider = RecordingProvider()
                reviewer = PptStructureReviewer(provider_client=provider)
                payload = request_payload()
                payload["scope"] = scope

                with self.assertRaises(AdapterError) as error:
                    reviewer.review(
                        parse_request(payload),
                        trace_id="trace-structure-invalid-range",
                    )

                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.message, message)
                self.assertFalse(any("request" in call for call in provider.calls))

    def test_explicit_range_within_sixty_slides_is_reviewed_and_disclosed(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)
        slides = [
            {"index": index, "title": "第 {0} 页".format(index)}
            for index in range(21, 61)
        ]

        result = reviewer.review(
            parse_request(
                request_payload(
                    slides=slides,
                    total_slides=80,
                    start_slide=21,
                    end_slide=60,
                )
            ),
            trace_id="trace-structure-range",
        )

        self.assertEqual(
            result["reviewedRange"],
            {
                "startSlide": 21,
                "endSlide": 60,
                "totalSlides": 80,
                "isFullDeck": False,
            },
        )
        self.assertEqual(len([call for call in provider.calls if "request" in call]), 1)
        self.assertIn("本次审查第 21–60 页", result["reviewConclusion"])
        self.assertNotIn("score", result)
        self.assertNotIn("numericScore", result)

    def test_local_findings_are_merged_with_model_findings_without_duplicates(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)

        result = reviewer.review(
            parse_request(request_payload()),
            trace_id="trace-structure-merge",
        )

        high_codes = [item["code"] for item in result["highPriorityIssues"]]
        general_codes = [item["code"] for item in result["generalSuggestions"]]
        self.assertEqual(high_codes.count("missing_title"), 1)
        self.assertIn("duplicate_title", high_codes)
        self.assertIn("numbering_gap", general_codes)
        self.assertEqual(len([call for call in provider.calls if "request" in call]), 1)
        self.assertIn("本次审查第 1–5 页", result["reviewConclusion"])
        self.assertIn("推荐目录", result["outlineText"])

    def test_findings_are_deduplicated_by_pages_and_problem_semantics(self):
        provider = RecordingProvider()
        original_review = provider.ppt_structure_review

        def review_with_rephrased_missing_title(*args, **kwargs):
            result = original_review(*args, **kwargs)
            result["generalSuggestions"].append(
                {
                    "code": "model_heading_absent",
                    "message": "第3页没有主标题，请补充页面标题。",
                    "slideNumbers": [3],
                }
            )
            result["generalSuggestions"].append(
                {
                    "code": "title_needed",
                    "message": "第3页需要补充页面标题。",
                    "slideNumbers": [3],
                }
            )
            return result

        provider.ppt_structure_review = review_with_rephrased_missing_title
        result = PptStructureReviewer(provider_client=provider).review(
            parse_request(request_payload()),
            trace_id="trace-structure-semantic-dedupe",
        )

        missing_title_findings = [
            item
            for item in result["highPriorityIssues"]
            if item["code"] in {"missing_title", "model_heading_absent"}
        ]
        self.assertEqual(len(missing_title_findings), 1)
        self.assertEqual(missing_title_findings[0]["source"], "local")
        self.assertFalse(
            any(
                item["code"] in {"model_heading_absent", "title_needed"}
                for item in result["generalSuggestions"]
            )
        )

    def test_body_fallback_budget_is_enforced_by_adapter(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)
        slides = [
            {
                "index": index,
                "title": "",
                "bodyFallback": "正文" * 100,
            }
            for index in range(1, 12)
        ]

        result = reviewer.review(
            parse_request(
                request_payload(
                    slides=slides,
                    total_slides=11,
                    end_slide=11,
                )
            ),
            trace_id="trace-structure-fallback",
        )

        sent = next(call["request"] for call in provider.calls if "request" in call)
        fallbacks = [slide.body_fallback for slide in sent.slides if slide.body_fallback]
        self.assertEqual(len(fallbacks), 10)
        self.assertTrue(all(len(value) <= 120 for value in fallbacks))
        self.assertTrue(sent.slides[10].body_fallback_omitted)
        omitted_finding = next(
            item
            for item in result["highPriorityIssues"]
            if item["code"] == "missing_title_information_insufficient"
        )
        self.assertEqual(omitted_finding["slideNumbers"], [11])
        self.assertEqual(
            omitted_finding["message"],
            "第 11 页无主标题，且已达到 10 页正文兜底上限，信息不足。",
        )

    def test_omitted_fallback_page_only_reports_information_insufficient(self):
        provider = RecordingProvider()
        original_review = provider.ppt_structure_review

        def review_with_unsupported_page_inferences(*args, **kwargs):
            result = original_review(*args, **kwargs)
            result["highPriorityIssues"].append(
                {
                    "code": "model_content_gap",
                    "message": "第 11 页应补充项目收益。",
                    "slideNumbers": [11],
                }
            )
            result["slideRecommendations"].append(
                {"slideNumber": 11, "suggestion": "补充收益数据。"}
            )
            result["inferredChapters"].append(
                {"title": "项目收益", "startSlide": 11, "endSlide": 11}
            )
            result["recommendedOutline"].append(
                {"order": 9, "title": "项目收益", "slideNumbers": [11]}
            )
            return result

        provider.ppt_structure_review = review_with_unsupported_page_inferences
        slides = [
            {"index": index, "title": "", "bodyFallback": "有限正文"}
            for index in range(1, 12)
        ]
        result = PptStructureReviewer(provider_client=provider).review(
            parse_request(
                request_payload(
                    slides=slides,
                    total_slides=11,
                    end_slide=11,
                )
            ),
            trace_id="trace-structure-omitted-page",
        )

        page_eleven_findings = [
            item
            for item in result["highPriorityIssues"] + result["generalSuggestions"]
            if item["slideNumbers"] == [11]
        ]
        self.assertEqual(
            [item["code"] for item in page_eleven_findings],
            ["missing_title_information_insufficient"],
        )
        self.assertFalse(
            any(item["slideNumber"] == 11 for item in result["slideRecommendations"])
        )
        self.assertFalse(
            any(
                item["startSlide"] <= 11 <= item["endSlide"]
                for item in result["inferredChapters"]
            )
        )
        self.assertFalse(
            any(11 in item["slideNumbers"] for item in result["recommendedOutline"])
        )
        sent = next(call["request"] for call in provider.calls if "request" in call)
        self.assertIn(
            "正文兜底：未读取（已达 10 页上限，仅报告信息不足）",
            build_ppt_structure_review_prompt(sent),
        )

    def test_job_uses_independent_task_auth_snapshot_and_is_idempotent(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        jobs = PptStructureReviewJobStore(reviewer=reviewer, coordinator=coordinator)
        request = parse_request(request_payload(client_job_id="client-ppt-structure-auth"))

        first = jobs.start(request, trace_id="trace-structure-auth-1")
        duplicate = jobs.start(request, trace_id="trace-structure-auth-2")
        deadline = time.time() + 2
        terminal = first
        while time.time() < deadline:
            terminal = jobs.get(first["jobId"])
            if terminal and terminal["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)

        self.assertEqual(first["jobId"], duplicate["jobId"])
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(
            [call["snapshotTaskType"] for call in provider.calls if "snapshotTaskType" in call],
            ["ppt.structure_review"],
        )
        provider_calls = [call for call in provider.calls if "request" in call]
        self.assertEqual(len(provider_calls), 1)
        self.assertEqual(provider_calls[0]["taskAuth"]["apiKey"], "structure-review-secret")
        self.assertNotIn("structure-review-secret", str(terminal))

    def test_provider_prompt_and_parser_enforce_read_only_non_scoring_contract(self):
        request = parse_request(request_payload())

        prompt = build_ppt_structure_review_prompt(request)
        parsed = parse_ppt_structure_review_answer(
            """<think>内部推理不得展示</think>
            {"overallStoryline":"先背景后实施", "inferredChapters":[],
             "highPriorityIssues":[], "generalSuggestions":[],
             "slideRecommendations":[], "recommendedOutline":[]}"""
        )

        self.assertIn("审查范围：第 1-5 页；演示文稿共 5 页", prompt)
        self.assertIn("不返回数值总分", prompt)
        self.assertIn("不声称已经创建、删除、重排或修改幻灯片", prompt)
        self.assertEqual(parsed["overallStoryline"], "先背景后实施")
        self.assertNotIn("内部推理", str(parsed))
        self.assertIsNone(parsed["rawAnswer"])

    def test_unstructured_provider_result_is_preserved_without_think_content(self):
        parsed = parse_ppt_structure_review_answer(
            "<think>不要泄露</think>请先补齐总体方案，再进入实施计划。"
        )

        self.assertEqual(
            parsed["rawAnswer"],
            "请先补齐总体方案，再进入实施计划。",
        )
        self.assertEqual(
            parsed["parseFallbackReason"],
            "ppt_structure_output_not_structured",
        )

    def test_unclosed_think_content_is_not_exposed_in_fallback(self):
        parsed = parse_ppt_structure_review_answer(
            "<think>未闭合的内部推理不得展示"
        )

        self.assertEqual(parsed["rawAnswer"], "")
        self.assertNotIn("内部推理", str(parsed))

    def test_model_page_references_are_limited_to_the_reviewed_range(self):
        provider = RecordingProvider()
        original_review = provider.ppt_structure_review

        def review_with_out_of_range_pages(*args, **kwargs):
            result = original_review(*args, **kwargs)
            result["inferredChapters"] = [
                {"title": "有效章节", "startSlide": 1, "endSlide": 2},
                {"title": "越界章节", "startSlide": 4, "endSlide": 80},
            ]
            result["highPriorityIssues"] = [
                {"code": "mixed_pages", "message": "保留有效定位。", "slideNumbers": [2, 80]},
                {"code": "invalid_pages", "message": "仅越界定位。", "slideNumbers": [80]},
            ]
            result["slideRecommendations"] = [
                {"slideNumber": 3, "suggestion": "有效建议"},
                {"slideNumber": 80, "suggestion": "越界建议"},
            ]
            result["recommendedOutline"] = [
                {"order": 1, "title": "有效目录", "slideNumbers": [1, 80]},
                {"order": 2, "title": "越界目录", "slideNumbers": [80]},
            ]
            return result

        provider.ppt_structure_review = review_with_out_of_range_pages
        result = PptStructureReviewer(provider_client=provider).review(
            parse_request(request_payload()),
            trace_id="trace-structure-page-range",
        )

        mixed = next(item for item in result["highPriorityIssues"] if item["code"] == "mixed_pages")
        self.assertEqual(mixed["slideNumbers"], [2])
        self.assertFalse(any(item["code"] == "invalid_pages" for item in result["highPriorityIssues"]))
        self.assertEqual(result["inferredChapters"], [
            {"title": "有效章节", "startSlide": 1, "endSlide": 2}
        ])
        self.assertEqual(result["slideRecommendations"], [
            {"slideNumber": 3, "suggestion": "有效建议"}
        ])
        self.assertEqual(result["recommendedOutline"], [
            {"order": 1, "title": "有效目录", "slideNumbers": [1]}
        ])

    def test_standalone_malformed_json_keeps_structure_review_task_type(self):
        import standalone_adapter

        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/ppt/structure-review/jobs"
        handler.headers = {"Content-Length": "1"}
        handler.rfile = BytesIO(b"{")
        handler._write = lambda status, body: captured.update(status=status, body=body)

        handler.do_POST()

        self.assertEqual(captured["status"], 422)
        self.assertEqual(captured["body"]["taskType"], "ppt.structure_review")
        self.assertEqual(captured["body"]["data"]["validation"]["errorCount"], 1)
        self.assertEqual(
            captured["body"]["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )


@unittest.skipUnless(HAS_PYDANTIC and HAS_FASTAPI, "fastapi is required")
class PptStructureReviewApiTests(unittest.TestCase):
    def test_start_poll_and_missing_resume_use_structure_review_contract(self):
        provider = RecordingProvider()
        reviewer = PptStructureReviewer(provider_client=provider)
        jobs = PptStructureReviewJobStore(
            reviewer=reviewer,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
        )
        original = ppt_api.ppt_structure_review_jobs
        ppt_api.ppt_structure_review_jobs = jobs
        try:
            client = TestClient(app_main.app)
            started = client.post(
                "/ppt/structure-review/jobs",
                json=request_payload(client_job_id="client-ppt-structure-api"),
            )
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["taskType"], "ppt.structure_review")
            polled = client.get(
                "/ppt/structure-review/jobs/client-ppt-structure-api"
            )
            self.assertEqual(polled.status_code, 200)
            self.assertEqual(polled.json()["taskType"], "ppt.structure_review")

            missing = client.get(
                "/ppt/structure-review/jobs/client-ppt-structure-missing?resume=1"
            )
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(
                missing.json()["errors"][0]["code"],
                "PPT_STRUCTURE_JOB_INTERRUPTED",
            )
        finally:
            ppt_api.ppt_structure_review_jobs = original


if __name__ == "__main__":
    unittest.main()
