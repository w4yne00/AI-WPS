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


class UnconfiguredProvider:
    def ppt_structure_review(self, request, trace_id, task_auth=None, progress_callback=None):
        raise AdapterError(
            "MODEL_CONFIG_INCOMPLETE",
            "结构审查尚未配置可用的模型配置，请先前往设置完成配置。",
            status_code=400,
        )


def findings_with_code(result, code):
    return [
        item
        for item in result["highPriorityIssues"] + result["generalSuggestions"]
        if item["code"] == code
    ]


def pages_with_code(result, code):
    pages = []
    for item in findings_with_code(result, code):
        pages.extend(item["slideNumbers"])
    return pages


def roles_by_page(result):
    return {item["slideNumber"]: item["role"] for item in result["pageRoles"]}


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
        with self.assertRaises(AdapterError) as raised:
            parse_ppt_structure_review_answer(
                "<think>未闭合的内部推理不得展示"
            )

        self.assertEqual(raised.exception.code, "MODEL_FINAL_CONTENT_MISSING")
        self.assertNotIn("内部推理", raised.exception.message)

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


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required")
class PptStructurePageRoleTests(unittest.TestCase):
    def _review(self, slides, total_slides=None, start_slide=None, end_slide=None, provider=None):
        last = slides[-1]["index"]
        first = slides[0]["index"]
        return PptStructureReviewer(
            provider_client=provider or RecordingProvider()
        ).review(
            parse_request(
                request_payload(
                    slides=slides,
                    total_slides=total_slides if total_slides is not None else last,
                    start_slide=start_slide if start_slide is not None else first,
                    end_slide=end_slide if end_slide is not None else last,
                )
            ),
            trace_id="trace-page-roles",
        )

    def test_toc_and_ending_empty_titles_do_not_report_missing_title(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报", "subtitle": "2026年度"},
                {
                    "index": 2,
                    "title": "",
                    "bodyFallback": "一、建设背景\n二、总体目标\n三、实施计划",
                },
                {"index": 3, "title": "一、建设背景"},
                {"index": 4, "title": "（一）政策依据"},
                {"index": 5, "title": "二、总体目标"},
                {"index": 6, "title": "", "bodyFallback": "汇报结束，请批评指正！"},
            ]
        )

        roles = roles_by_page(result)
        self.assertEqual(roles[1], "封面页")
        self.assertEqual(roles[2], "目录页")
        self.assertEqual(roles[6], "结束页")
        self.assertNotIn(2, pages_with_code(result, "missing_title"))
        self.assertNotIn(6, pages_with_code(result, "missing_title"))
        self.assertTrue(all(item.get("reason") for item in result["pageRoles"]))

    def test_cover_without_title_still_reports_missing_title(self):
        result = self._review(
            [
                {"index": 1, "title": "", "bodyFallback": "密级：内部"},
                {"index": 2, "title": "一、建设背景"},
                {"index": 3, "title": "二、总体目标"},
            ]
        )

        self.assertEqual(roles_by_page(result)[1], "封面页")
        self.assertIn(1, pages_with_code(result, "missing_title"))

    def test_single_empty_slide_is_cover_not_ending(self):
        result = self._review(
            [{"index": 1, "title": "", "bodyFallback": "密级：内部"}]
        )

        self.assertEqual(roles_by_page(result)[1], "封面页")
        self.assertIn(1, pages_with_code(result, "missing_title"))

    def test_first_page_directory_is_toc_not_cover(self):
        result = self._review(
            [
                {
                    "index": 1,
                    "title": "",
                    "bodyFallback": "目录\n一、建设背景\n二、总体目标",
                },
                {"index": 2, "title": "一、建设背景"},
                {"index": 3, "title": "二、总体目标"},
            ]
        )

        self.assertEqual(roles_by_page(result)[1], "目录页")
        self.assertNotIn(1, pages_with_code(result, "missing_title"))

    def test_transition_from_chapter_title_and_following_subsection_still_reports_duplicate_title(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、实施计划"},
                {"index": 3, "title": "（一）阶段一"},
                {"index": 4, "title": "一、实施计划"},
                {"index": 5, "title": "（一）阶段二"},
            ]
        )

        roles = roles_by_page(result)
        self.assertEqual(roles[2], "过渡页")
        self.assertEqual(roles[4], "过渡页")
        duplicate_pages = pages_with_code(result, "duplicate_title")
        self.assertIn(2, duplicate_pages)
        self.assertIn(4, duplicate_pages)

    def test_partial_range_does_not_promote_first_or_last_page_to_cover_or_ending(self):
        result = self._review(
            [
                {"index": 8, "title": ""},
                {"index": 9, "title": "一、实施计划"},
                {"index": 10, "title": "（一）阶段安排"},
                {"index": 11, "title": "二、保障措施"},
                {"index": 12, "title": "三、进度安排"},
                {"index": 13, "title": "四、风险清单"},
                {"index": 14, "title": "五、下一步工作"},
                {"index": 15, "title": ""},
            ],
            total_slides=20,
            start_slide=8,
            end_slide=15,
        )

        roles = roles_by_page(result)
        self.assertNotIn("封面页", roles.values())
        self.assertNotIn("结束页", roles.values())
        self.assertEqual(roles[8], "未确认页角色")
        self.assertEqual(roles[15], "未确认页角色")
        self.assertEqual(roles[9], "过渡页")
        self.assertIn(8, pages_with_code(result, "missing_title"))
        self.assertIn(15, pages_with_code(result, "missing_title"))

    def test_unconfirmed_role_follows_body_rules_and_is_not_exempted(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、建设背景"},
                {"index": 3, "title": ""},
                {"index": 4, "title": "二、总体目标"},
            ]
        )

        self.assertEqual(roles_by_page(result)[3], "未确认页角色")
        self.assertIn(3, pages_with_code(result, "missing_title"))

    def test_unconfigured_model_still_returns_page_roles_and_local_rules(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {
                    "index": 2,
                    "title": "",
                    "bodyFallback": "一、建设背景\n二、总体目标",
                },
                {"index": 3, "title": "一、建设背景"},
                {"index": 4, "title": "二、总体目标"},
                {"index": 5, "title": ""},
                {"index": 6, "title": "", "bodyFallback": "汇报结束，请批评指正！"},
            ],
            provider=UnconfiguredProvider(),
        )

        roles = roles_by_page(result)
        self.assertEqual(roles[1], "封面页")
        self.assertEqual(roles[2], "目录页")
        self.assertEqual(roles[6], "结束页")
        self.assertEqual(roles[5], "未确认页角色")
        self.assertNotIn(2, pages_with_code(result, "missing_title"))
        self.assertNotIn(6, pages_with_code(result, "missing_title"))
        self.assertIn(5, pages_with_code(result, "missing_title"))

    def test_model_cannot_override_determined_roles_or_reintroduce_exempted_missing_title(self):
        provider = RecordingProvider()
        original_review = provider.ppt_structure_review

        def review_with_role_override(*args, **kwargs):
            result = original_review(*args, **kwargs)
            result["pageRoles"] = [
                {"slideNumber": 1, "role": "目录页", "reason": "模型口述不得覆盖"},
                {"slideNumber": 2, "role": "封面页", "reason": "模型口述不得覆盖"},
            ]
            result["highPriorityIssues"].append(
                {
                    "code": "missing_title",
                    "message": "第 2 页缺少主标题。",
                    "slideNumbers": [2],
                }
            )
            return result

        provider.ppt_structure_review = review_with_role_override
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {
                    "index": 2,
                    "title": "",
                    "bodyFallback": "一、建设背景\n二、总体目标",
                },
                {"index": 3, "title": "一、建设背景"},
                {"index": 4, "title": "二、总体目标"},
                {"index": 5, "title": "", "bodyFallback": "汇报结束，请批评指正！"},
            ],
            provider=provider,
        )

        roles = roles_by_page(result)
        self.assertEqual(roles[1], "封面页")
        self.assertEqual(roles[2], "目录页")
        self.assertEqual(roles[5], "结束页")
        self.assertNotIn(2, pages_with_code(result, "missing_title"))

    def test_shape_names_identify_mid_deck_toc_without_reading_titled_body(self):
        result = self._review(
            [
                {"index": 8, "title": "七、组织保障"},
                {
                    "index": 9,
                    "title": "",
                    "bodyFallback": "",
                    "shapeNames": ["目录", "文本框 2"],
                },
                {"index": 10, "title": "八、进度安排"},
                {"index": 11, "title": "（一）里程碑"},
            ],
            total_slides=20,
            start_slide=8,
            end_slide=11,
        )

        self.assertEqual(roles_by_page(result)[9], "目录页")
        self.assertNotIn(9, pages_with_code(result, "missing_title"))
        self.assertEqual(roles_by_page(result)[10], "过渡页")

    def test_body_empty_title_still_reports_missing_title(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、建设背景"},
                {"index": 3, "title": "（一）政策依据"},
                {"index": 4, "title": ""},
                {"index": 5, "title": "二、总体目标"},
            ]
        )

        self.assertEqual(roles_by_page(result)[4], "未确认页角色")
        self.assertIn(4, pages_with_code(result, "missing_title"))
        self.assertNotIn(1, pages_with_code(result, "missing_title"))

    def test_untitled_numbered_body_is_unconfirmed_not_toc(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、建设背景"},
                {
                    "index": 3,
                    "title": "",
                    "bodyFallback": "（一）政策依据\n（二）工作要求",
                },
                {"index": 4, "title": "二、总体目标"},
            ]
        )

        self.assertEqual(roles_by_page(result)[3], "未确认页角色")
        self.assertIn(3, pages_with_code(result, "missing_title"))

    def test_last_empty_slide_without_ending_phrase_is_not_ending(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、建设背景"},
                {"index": 3, "title": "", "bodyFallback": "密级：内部"},
            ]
        )

        self.assertEqual(roles_by_page(result)[3], "未确认页角色")
        self.assertIn(3, pages_with_code(result, "missing_title"))

    def test_chapter_title_containing_toc_word_is_transition_not_toc(self):
        result = self._review(
            [
                {"index": 1, "title": "零信任体系建设汇报"},
                {"index": 2, "title": "一、目录体系建设"},
                {"index": 3, "title": "（一）编制说明"},
            ]
        )

        self.assertEqual(roles_by_page(result)[2], "过渡页")
        self.assertNotEqual(roles_by_page(result)[2], "目录页")


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
