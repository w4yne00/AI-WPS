import asyncio
import base64
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import PptSlideAssistantRequest
    from app.services.ppt.document_files import PptDocumentFileStore
    from app.services.ppt.slide_assistant import (
        PptSlideAssistant,
        determine_ppt_slide_mode,
        normalize_ppt_slide_request,
    )
    from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore

if HAS_PYDANTIC and HAS_FASTAPI:
    from app.api import ppt as ppt_api
    from app import main as app_main
    from fastapi.responses import JSONResponse
    from starlette.requests import Request


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

    def assist(self, request, trace_id, progress_callback=None):
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


class RecordingPptDocumentProvider:
    def __init__(self, fail_message=""):
        self.calls = []
        self.fail_message = fail_message
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def ppt_document_summary(
        self,
        staged_document,
        requested_slide_count,
        user_instruction,
        trace_id,
        progress_callback=None,
    ):
        self.calls.append(
            {
                "path": str(staged_document.path),
                "requestedSlideCount": requested_slide_count,
                "userInstruction": user_instruction,
                "traceId": trace_id,
            }
        )
        self.started.set()
        if self.block:
            self.release.wait(timeout=2)
        if self.fail_message:
            raise RuntimeError(self.fail_message)
        if progress_callback:
            progress_callback("模型后台正在解析文档并生成 PPT 建议。")
        return {
            "resultType": "document",
            "deckTitle": "项目汇报建议",
            "documentSummary": "文档围绕项目进展与风险展开。",
            "recommendedSlideCount": requested_slide_count,
            "slides": [
                {
                    "index": 1,
                    "role": "封面",
                    "title": "项目进展汇报",
                    "subtitle": "阶段成果与下一步计划",
                    "bullets": ["总体方案已完成"],
                    "conclusion": "项目总体可控。",
                    "layoutSuggestion": "标题居中",
                    "visualSuggestion": "使用进度图",
                }
            ],
            "globalStyleAdvice": "采用简洁商务风格。",
            "plainText": "项目汇报建议",
            "rawAnswer": None,
            "parseFallbackReason": None,
            "provider": "provider-test",
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

    def _document_request(
        self,
        file_token="",
        requested_slide_count=10,
        client_job_id="client-ppt-document",
    ):
        return parse_ppt_request(
            {
                "presentationId": "汇报材料.pptx",
                "scene": "ppt",
                "sourceMode": "document",
                "clientJobId": client_job_id,
                "fileToken": file_token,
                "requestedSlideCount": requested_slide_count,
                "userInstruction": "突出风险与计划",
            }
        )

    @staticmethod
    def _stage_markdown(store, file_name="现场方案.md", content=b"# Project\n\nContent"):
        return store.store(
            file_name,
            "text/markdown",
            len(content),
            base64.b64encode(content).decode("ascii"),
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

    def test_document_mode_requires_uploaded_file_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = PptSlideAssistant(
                provider_client=RecordingPptDocumentProvider(),
                document_file_store=PptDocumentFileStore(Path(temp_dir)),
            )

            with self.assertRaises(AdapterError) as error:
                assistant.assist(self._document_request(), trace_id="trace-ppt-document-missing")

        self.assertEqual(error.exception.code, "PPT_DOCUMENT_FILE_REQUIRED")

    def test_document_mode_calls_provider_and_deletes_staged_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            staged = self._stage_markdown(store)
            provider = RecordingPptDocumentProvider()
            messages = []
            assistant = PptSlideAssistant(provider_client=provider, document_file_store=store)

            result = assistant.assist(
                self._document_request(staged["fileToken"], requested_slide_count=15),
                trace_id="trace-ppt-document",
                progress_callback=messages.append,
            )

            provider_path = Path(provider.calls[0]["path"])
            self.assertEqual(result["resultType"], "document")
            self.assertEqual(provider.calls[0]["requestedSlideCount"], 15)
            self.assertFalse(provider_path.exists())
            self.assertIn("正在上传文档到模型后台。", messages)
            self.assertIn("模型后台正在解析文档并生成 PPT 建议。", messages)

    def test_document_mode_deletes_staged_file_after_provider_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            staged = self._stage_markdown(store)
            provider = RecordingPptDocumentProvider(fail_message="provider failed")
            assistant = PptSlideAssistant(provider_client=provider, document_file_store=store)

            with self.assertRaises(RuntimeError):
                assistant.assist(
                    self._document_request(staged["fileToken"]),
                    trace_id="trace-ppt-document-failed",
                )

            self.assertFalse(Path(provider.calls[0]["path"]).exists())

    def test_document_mode_rejects_expired_or_consumed_token(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir), now=lambda: now[0])
            staged = self._stage_markdown(store)
            now[0] += 1801
            assistant = PptSlideAssistant(
                provider_client=RecordingPptDocumentProvider(),
                document_file_store=store,
            )

            with self.assertRaises(AdapterError) as error:
                assistant.assist(
                    self._document_request(staged["fileToken"]),
                    trace_id="trace-ppt-document-expired",
                )

        self.assertEqual(error.exception.code, "PPT_DOCUMENT_FILE_EXPIRED")

    def test_document_job_duplicate_client_id_calls_provider_once_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            staged = self._stage_markdown(store)
            provider = RecordingPptDocumentProvider()
            provider.block = True
            assistant = PptSlideAssistant(provider_client=provider, document_file_store=store)
            jobs = PptSlideAssistantJobStore(assistant=assistant)
            request = self._document_request(
                staged["fileToken"], client_job_id="client-ppt-document-duplicate"
            )

            started = jobs.start(request, trace_id="trace-ppt-document-first")
            duplicate = jobs.start(request, trace_id="trace-ppt-document-second")

            self.assertTrue(provider.started.wait(timeout=1))
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(duplicate["traceId"], started["traceId"])
            self.assertIn("模型后台", duplicate["runningMessage"])
            provider.release.set()
            completed = self._wait_for_job(jobs, "client-ppt-document-duplicate")
            self.assertEqual(completed["status"], "completed")
            self.assertFalse(Path(provider.calls[0]["path"]).exists())

    def test_document_job_failure_does_not_expose_file_details(self):
        original_name = "内部绝密方案.md"
        encoded_content = base64.b64encode(b"secret body").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            staged = store.store(original_name, "text/markdown", 11, encoded_content)
            provider = RecordingPptDocumentProvider()
            assistant = PptSlideAssistant(provider_client=provider, document_file_store=store)
            provider.fail_message = "failed {0} {1} {2}".format(
                original_name, encoded_content, str(store.root_dir)
            )
            jobs = PptSlideAssistantJobStore(assistant=assistant)
            jobs.start(
                self._document_request(
                    staged["fileToken"], client_job_id="client-ppt-document-secret"
                ),
                trace_id="trace-ppt-document-secret",
            )

            failed = self._wait_for_job(jobs, "client-ppt-document-secret")
            error_text = json.dumps(failed["error"], ensure_ascii=False)
            self.assertEqual(failed["status"], "failed")
            self.assertNotIn(original_name, error_text)
            self.assertNotIn(encoded_content, error_text)
            self.assertNotIn(str(store.root_dir), error_text)
            self.assertFalse(Path(provider.calls[0]["path"]).exists())

    @staticmethod
    def _wait_for_job(store, job_id):
        job = None
        for _ in range(100):
            job = store.get(job_id)
            if job and job["status"] != "running":
                return job
            time.sleep(0.02)
        return job

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

    def test_job_store_rejects_new_job_without_evicting_running_job_at_capacity(self):
        assistant = BlockingPptAssistant()
        store = PptSlideAssistantJobStore(assistant=assistant, max_jobs=1)

        store.start(
            self._request(client_job_id="client-ppt-running-first"),
            trace_id="trace-ppt-running-first",
        )
        self.assertTrue(assistant.started.wait(timeout=1))
        with self.assertRaises(AdapterError) as error:
            store.start(
                self._request(client_job_id="client-ppt-running-second"),
                trace_id="trace-ppt-running-second",
            )

        self.assertIsNotNone(store.get("client-ppt-running-first"))
        self.assertIsNone(store.get("client-ppt-running-second"))
        self.assertEqual(error.exception.code, "PPT_SLIDE_JOB_CAPACITY")
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(assistant.call_count, 1)
        assistant.release.set()

    def test_job_store_keeps_safe_slide_validation_message(self):
        store = PptSlideAssistantJobStore(assistant=PptSlideAssistant())
        request = parse_ppt_request(
            {
                "sourceMode": "slide",
                "clientJobId": "client-ppt-slide-required",
            }
        )
        request.slide = None

        store.start(request, trace_id="trace-ppt-slide-required")
        failed = self._wait_for_job(store, "client-ppt-slide-required")

        self.assertEqual(failed["error"]["code"], "PPT_SLIDE_REQUIRED")
        self.assertIn("当前幻灯片", failed["error"]["message"])

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

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for PPT route tests")
    def test_fastapi_upload_and_document_result_serialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            provider = RecordingPptDocumentProvider()
            assistant = PptSlideAssistant(provider_client=provider, document_file_store=store)
            jobs = PptSlideAssistantJobStore(assistant=assistant)
            original_files = ppt_api.ppt_document_files
            original_jobs = ppt_api.ppt_slide_jobs
            ppt_api.ppt_document_files = store
            ppt_api.ppt_slide_jobs = jobs
            try:
                content = b"# Summary"
                uploaded = ppt_api.upload_ppt_document_file(
                    ppt_api.PptDocumentFileUploadRequest(
                        fileName="summary.md",
                        mimeType="text/markdown",
                        sizeBytes=len(content),
                        contentBase64=base64.b64encode(content).decode("ascii"),
                    )
                )
                ppt_api.start_ppt_slide_assistant_job(
                    self._document_request(
                        uploaded["data"]["fileToken"],
                        client_job_id="client-ppt-document-fastapi",
                    )
                )
                completed = self._wait_for_job(jobs, "client-ppt-document-fastapi")
                response = ppt_api.get_ppt_slide_assistant_job("client-ppt-document-fastapi")
            finally:
                ppt_api.ppt_document_files = original_files
                ppt_api.ppt_slide_jobs = original_jobs

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(uploaded["data"]["expiresInSeconds"], 1800)
        self.assertEqual(response["data"]["result"]["resultType"], "document")
        self.assertEqual(response["data"]["result"]["slides"][0]["subtitle"], "阶段成果与下一步计划")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for PPT middleware tests")
    def test_fastapi_rejects_oversized_document_upload_before_call_next(self):
        calls = []

        async def call_next(_request):
            calls.append(True)
            return JSONResponse({"unexpected": True})

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ppt/document-files",
                "headers": [
                    (
                        b"content-length",
                        str(app_main.PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES + 1).encode("ascii"),
                    )
                ],
            }
        )

        response = asyncio.run(app_main.log_requests(request, call_next))
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 413)
        self.assertEqual(payload["errors"][0]["code"], "PPT_DOCUMENT_TOO_LARGE")
        self.assertEqual(calls, [])

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for PPT middleware tests")
    def test_fastapi_upload_body_limit_rejects_invalid_length_but_ignores_other_routes(self):
        calls = []

        async def call_next(request):
            calls.append(request.url.path)
            return JSONResponse({"ok": True})

        invalid_length_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ppt/document-files",
                "headers": [(b"content-length", b"invalid")],
            }
        )
        missing_length_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ppt/document-files",
                "headers": [],
            }
        )
        other_route_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/word/smart-write",
                "headers": [(b"content-length", b"999999999")],
            }
        )

        invalid_response = asyncio.run(app_main.log_requests(invalid_length_request, call_next))
        missing_response = asyncio.run(app_main.log_requests(missing_length_request, call_next))
        other_response = asyncio.run(app_main.log_requests(other_route_request, call_next))

        self.assertEqual(invalid_response.status_code, 411)
        self.assertEqual(missing_response.status_code, 411)
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(calls, ["/word/smart-write"])

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for PPT handler tests")
    def test_fastapi_adapter_error_uses_ppt_task_type_for_upload(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ppt/document-files",
                "headers": [],
            }
        )
        response = asyncio.run(
            app_main.handle_adapter_error(
                request,
                AdapterError("PPT_DOCUMENT_INVALID", "文件无效。", status_code=400),
            )
        )
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(payload["taskType"], "ppt.slide_assistant")

    def test_standalone_parses_request_and_serializes_job_result(self):
        import standalone_adapter

        request = standalone_adapter.parse_ppt_request(
            {
                "presentationId": "汇报材料.pptx",
                "scene": "ppt",
                "clientJobId": "client-ppt-standalone",
                "slide": {
                    "index": 2,
                    "title": "项目进展",
                    "subtitle": "阶段成果",
                    "textBlocks": ["正文内容达到二十个非空白字符用于模式判断测试"],
                },
                "userInstruction": "突出风险。",
            }
        )
        completed_assistant = BlockingPptAssistant()
        completed_assistant.release.set()
        payload = standalone_adapter.ppt_slide_assistant_job_payload(
            {
                "jobId": "client-ppt-standalone",
                "traceId": "trace-ppt-standalone",
                "status": "completed",
                "result": completed_assistant.assist(request, "trace-ppt-standalone"),
            }
        )

        self.assertEqual(request.slide.subtitle, "阶段成果")
        self.assertEqual(payload["result"]["modeUsed"], "optimize")
        self.assertEqual(payload["result"]["suggestedTitle"], "后台任务完成")

    def test_standalone_post_get_and_not_found_routes(self):
        import standalone_adapter

        assistant = BlockingPptAssistant()
        store = PptSlideAssistantJobStore(assistant=assistant)
        original_store = standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE
        standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE = store

        def invoke(method, path, payload=None):
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: captured.update(status=status, body=body)
            getattr(handler, method)()
            return captured

        request_payload = {
            "presentationId": "汇报材料.pptx",
            "scene": "ppt",
            "clientJobId": "client-ppt-route-standalone",
            "slide": {
                "index": 2,
                "title": "项目进展",
                "subtitle": "阶段成果",
                "textBlocks": ["正文内容达到二十个非空白字符用于模式判断测试"],
            },
            "userInstruction": "突出风险。",
        }
        try:
            submitted = invoke("do_POST", "/ppt/slide-assistant/jobs", request_payload)
            running = invoke("do_GET", "/ppt/slide-assistant/jobs/client-ppt-route-standalone")
            missing = invoke("do_GET", "/ppt/slide-assistant/jobs/missing-ppt-job")
        finally:
            assistant.release.set()
            standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE = original_store

        self.assertEqual(submitted["status"], 200)
        self.assertEqual(submitted["body"]["taskType"], "ppt.slide_assistant")
        self.assertEqual(running["body"]["data"]["status"], "running")
        self.assertEqual(missing["status"], 404)
        self.assertEqual(missing["body"]["errors"][0]["code"], "PPT_SLIDE_JOB_NOT_FOUND")

    def test_standalone_upload_and_document_result_routes(self):
        import standalone_adapter

        with tempfile.TemporaryDirectory() as temp_dir:
            store = PptDocumentFileStore(Path(temp_dir))
            provider = RecordingPptDocumentProvider()
            jobs = PptSlideAssistantJobStore(
                assistant=PptSlideAssistant(provider_client=provider, document_file_store=store)
            )
            original_files = standalone_adapter.PPT_DOCUMENT_FILE_STORE
            original_jobs = standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE
            standalone_adapter.PPT_DOCUMENT_FILE_STORE = store
            standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE = jobs
            try:
                content = b"# Summary"
                uploaded = self._invoke_standalone(
                    standalone_adapter,
                    "do_POST",
                    "/ppt/document-files",
                    {
                        "fileName": "summary.md",
                        "mimeType": "text/markdown",
                        "sizeBytes": len(content),
                        "contentBase64": base64.b64encode(content).decode("ascii"),
                    },
                )
                submitted = self._invoke_standalone(
                    standalone_adapter,
                    "do_POST",
                    "/ppt/slide-assistant/jobs",
                    {
                        "sourceMode": "document",
                        "fileToken": uploaded["body"]["data"]["fileToken"],
                        "requestedSlideCount": 10,
                        "clientJobId": "client-ppt-document-standalone",
                    },
                )
                completed = self._wait_for_job(jobs, "client-ppt-document-standalone")
                response = self._invoke_standalone(
                    standalone_adapter,
                    "do_GET",
                    "/ppt/slide-assistant/jobs/client-ppt-document-standalone",
                )
            finally:
                standalone_adapter.PPT_DOCUMENT_FILE_STORE = original_files
                standalone_adapter.PPT_SLIDE_ASSISTANT_JOB_STORE = original_jobs

        self.assertEqual(uploaded["status"], 200)
        self.assertEqual(submitted["status"], 200)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(response["body"]["data"]["result"]["resultType"], "document")
        self.assertEqual(response["body"]["data"]["result"]["slides"][0]["title"], "项目进展汇报")

    def test_standalone_rejects_oversized_document_upload_before_reading_body(self):
        import standalone_adapter

        class FailOnRead:
            def read(self, _length):
                raise AssertionError("request body must not be read")

        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/ppt/document-files"
        handler.headers = {
            "Content-Length": str(standalone_adapter.PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES + 1)
        }
        handler.rfile = FailOnRead()
        handler._write = lambda status, body: captured.update(status=status, body=body)

        handler.do_POST()

        self.assertEqual(captured["status"], 413)
        self.assertEqual(captured["body"]["errors"][0]["code"], "PPT_DOCUMENT_TOO_LARGE")

    def test_standalone_rejects_invalid_document_upload_length_before_reading_body(self):
        import standalone_adapter

        class FailOnRead:
            def read(self, _length):
                raise AssertionError("request body must not be read")

        for value in (None, "invalid", "0", "-1"):
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = "/ppt/document-files"
            handler.headers = {} if value is None else {"Content-Length": value}
            handler.rfile = FailOnRead()
            handler._write = lambda status, body: captured.update(status=status, body=body)

            handler.do_POST()

            self.assertEqual(captured["status"], 411)
            self.assertEqual(captured["body"]["errors"][0]["code"], "CONTENT_LENGTH_REQUIRED")

        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/ppt/document-files"
        handler.headers = {"Content-Length": "1", "Transfer-Encoding": "chunked"}
        handler.rfile = FailOnRead()
        handler._write = lambda status, body: captured.update(status=status, body=body)

        handler.do_POST()

        self.assertEqual(captured["status"], 411)
        self.assertEqual(captured["body"]["errors"][0]["code"], "CONTENT_LENGTH_REQUIRED")

    def test_standalone_upload_returns_validation_envelope_for_malformed_json(self):
        import standalone_adapter

        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/ppt/document-files"
        handler.headers = {"Content-Length": "1"}
        handler.rfile = BytesIO(b"{")
        handler._write = lambda status, body: captured.update(status=status, body=body)

        handler.do_POST()

        self.assertEqual(captured["status"], 400)
        self.assertEqual(captured["body"]["errors"][0]["code"], "REQUEST_VALIDATION_FAILED")

    def test_standalone_ppt_job_returns_validation_envelope_for_invalid_slide(self):
        import standalone_adapter

        response = self._invoke_standalone(
            standalone_adapter,
            "do_POST",
            "/ppt/slide-assistant/jobs",
            {"sourceMode": "slide", "slide": "invalid-host-value"},
        )

        self.assertEqual(response["status"], 400)
        self.assertEqual(response["body"]["errors"][0]["code"], "REQUEST_VALIDATION_FAILED")

    @staticmethod
    def _invoke_standalone(module, method, path, payload=None):
        captured = {}
        handler = object.__new__(module.Handler)
        handler.path = path
        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)
        getattr(handler, method)()
        return captured


if __name__ == "__main__":
    unittest.main()
