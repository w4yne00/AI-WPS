import unittest
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import socket
import threading
import sys
import os
import importlib.util
from urllib.error import HTTPError, URLError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import AppSettings, load_settings, save_provider_base_url, save_task_api_key_ref, task_routes_to_dict
from app.core.errors import ProviderAuthError, ProviderTimeoutError, ProviderUnavailableError
from app.core.models import ExcelAnalysisRequest, PptSlideAssistantRequest, WordDocumentRequest
from app.services import provider_client
from app.services.provider_client import (
    ProviderClient,
    build_excel_analysis_prompt,
    build_document_review_prompt,
    build_ppt_slide_prompt,
    build_provider_request_payload,
    build_route_request_payload,
    build_rewrite_prompt,
    build_smart_imitation_prompt,
    build_smart_write_prompt,
    extract_answer,
    get_last_provider_debug,
    get_default_document_review_prompt,
    get_route_api_key_path,
    save_local_api_key,
    save_route_api_key,
    clear_local_api_key,
    clear_route_api_key,
    parse_document_review_answer,
    parse_excel_analysis_answer,
    parse_ppt_slide_answer,
    record_provider_debug,
    reset_provider_debug,
)
from app.services.template_loader import TemplateLoader
from app.services.workflow_profiles import WorkflowProfileStore


class FakeProviderResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def make_http_error(status, body):
    return HTTPError(
        "https://aibot.example/v1/chat-messages",
        status,
        "Bad Request",
        {},
        BytesIO(json.dumps(body, ensure_ascii=False).encode("utf-8")),
    )


class EnterpriseProviderTests(unittest.TestCase):
    def _configured_provider_client(
        self,
        base_url="https://aibot.example/v1",
        path="/chat-messages",
        task_api_key_refs=None,
    ):
        return ProviderClient(
            AppSettings(
                provider_base_url=base_url,
                provider_chat_path=path,
                provider_mode="blocking",
                task_api_key_refs=task_api_key_refs or {},
            )
        )

    def test_active_workflow_profile_key_precedes_legacy_and_unified_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            key_dir = root / "provider_api_keys"
            store = WorkflowProfileStore(config_path, key_dir)
            profile = store.create_profile("word.smart_write", "生产版", "app-profile", activate=True)
            save_route_api_key("legacy_ref", "app-legacy", root)
            save_local_api_key("app-unified", root / "provider_api_key")
            settings = AppSettings(
                provider_base_url="https://aibot.example/v1",
                task_api_key_refs={"word.smart_write": "legacy_ref"},
            )
            client = ProviderClient(settings, workflow_profile_store=store)

            key = client.get_api_key_for_task("word.smart_write", root)

            self.assertEqual(key, "app-profile")
            self.assertEqual(client.get_task_api_key_ref("word.smart_write"), profile["apiKeyRef"])

    def test_workflow_profile_status_and_debug_are_sanitized(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = WorkflowProfileStore(config_path, root / "provider_api_keys")
            profile = store.create_profile("excel.analysis", "表格生产版", "app-excel-secret", activate=True)
            client = ProviderClient(
                AppSettings(provider_base_url="https://aibot.example/v1"),
                workflow_profile_store=store,
            )

            status = client.build_task_api_key_status(root)["excel.analysis"]
            debug = client.build_debug_metadata("excel.analysis")

            self.assertEqual(status["activeProfileId"], profile["id"])
            self.assertEqual(status["activeProfileName"], "表格生产版")
            self.assertEqual(status["profileCount"], 1)
            self.assertEqual(debug["workflowProfileId"], profile["id"])
            self.assertEqual(debug["workflowProfileName"], "表格生产版")
            self.assertNotIn("app-excel-secret", json.dumps({"status": status, "debug": debug}, ensure_ascii=False))

    def test_build_provider_request_payload_keeps_legacy_inputs_query(self) -> None:
        self.assertEqual(
            getattr(provider_client, "DIFY_INPUT_MODE_LEGACY", None),
            "legacy-input-query",
        )
        settings = AppSettings(provider_mode="blocking")

        payload = build_provider_request_payload(
            settings,
            {},
            "完整提示词",
            input_mode=provider_client.DIFY_INPUT_MODE_LEGACY,
        )

        self.assertEqual(payload["inputs"], {"query": "完整提示词"})
        self.assertEqual(payload["query"], "完整提示词")
        self.assertEqual(payload["files"], [])

    def test_build_provider_request_payload_supports_user_input_node(self) -> None:
        self.assertEqual(
            getattr(provider_client, "DIFY_INPUT_MODE_USER_INPUT", None),
            "user-input-node",
        )
        settings = AppSettings(provider_mode="blocking")

        payload = build_provider_request_payload(
            settings,
            {},
            "完整提示词",
            input_mode=provider_client.DIFY_INPUT_MODE_USER_INPUT,
        )

        self.assertEqual(payload["inputs"], {})
        self.assertEqual(payload["query"], "完整提示词")
        self.assertEqual(payload["files"], [])

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_uses_and_caches_legacy_mode_on_first_success(
        self,
        urlopen,
    ) -> None:
        urlopen.return_value = FakeProviderResponse({"answer": "旧版工作流结果"})
        client = self._configured_provider_client()
        input_mode_cache = {}

        with patch.object(
            provider_client,
            "_PROVIDER_INPUT_MODE_CACHE",
            input_mode_cache,
            create=True,
        ):
            result = client.post_task(
                "word.smart_write",
                "trace-legacy-success",
                {},
                "完整提示词",
            )

        request_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(result["answer"], "旧版工作流结果")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(request_body["inputs"], {"query": "完整提示词"})
        self.assertEqual(
            list(input_mode_cache.values()),
            [provider_client.DIFY_INPUT_MODE_LEGACY],
        )

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_retries_http_400_with_user_input_node(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(
                400,
                {
                    "code": "invalid_param",
                    "message": "query is not allowed in inputs",
                },
            ),
            FakeProviderResponse({"answer": "新版工作流结果"}),
        ]
        client = self._configured_provider_client()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            result = client.post_task(
                "word.smart_write",
                "trace-new-dify",
                {},
                "完整提示词",
            )

        self.assertEqual(result["answer"], "新版工作流结果")
        first_body = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        second_body = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual(first_body["inputs"], {"query": "完整提示词"})
        self.assertEqual(second_body["inputs"], {})
        self.assertEqual(urlopen.call_count, 2)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_reuses_cached_user_input_mode(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param"}),
            FakeProviderResponse({"answer": "第一次"}),
            FakeProviderResponse({"answer": "第二次"}),
        ]
        client = self._configured_provider_client()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client.post_task("word.smart_write", "trace-first", {}, "第一次提示词")
            client.post_task("word.smart_write", "trace-second", {}, "第二次提示词")

        third_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(third_body["inputs"], {})
        self.assertEqual(urlopen.call_count, 3)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_input_mode_cache_is_isolated_by_task_type(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param"}),
            FakeProviderResponse({"answer": "智能编写"}),
            FakeProviderResponse({"answer": "文档审查"}),
        ]
        client = self._configured_provider_client()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client.post_task("word.smart_write", "trace-write", {}, "智能编写提示词")
            client.post_task("word.document_review", "trace-review", {}, "文档审查提示词")

        review_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(review_body["inputs"], {"query": "文档审查提示词"})

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_input_mode_cache_is_isolated_by_provider_url(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param"}),
            FakeProviderResponse({"answer": "地址 A"}),
            FakeProviderResponse({"answer": "地址 B"}),
        ]
        client_a = self._configured_provider_client(base_url="https://a.example/v1")
        client_b = self._configured_provider_client(base_url="https://b.example/v1")

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client_a.post_task("word.smart_write", "trace-a", {}, "地址 A 提示词")
            client_b.post_task("word.smart_write", "trace-b", {}, "地址 B 提示词")

        second_url_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(second_url_body["inputs"], {"query": "地址 B 提示词"})

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_input_mode_cache_is_isolated_by_provider_path(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param"}),
            FakeProviderResponse({"answer": "路径 A"}),
            FakeProviderResponse({"answer": "路径 B"}),
        ]
        client_a = self._configured_provider_client(path="/chat-messages")
        client_b = self._configured_provider_client(path="/alternate-chat-messages")

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client_a.post_task("word.smart_write", "trace-path-a", {}, "路径 A 提示词")
            client_b.post_task("word.smart_write", "trace-path-b", {}, "路径 B 提示词")

        second_path_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(second_path_body["inputs"], {"query": "路径 B 提示词"})

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_input_mode_cache_is_isolated_by_task_api_key_ref(self, urlopen) -> None:
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param"}),
            FakeProviderResponse({"answer": "密钥引用 A"}),
            FakeProviderResponse({"answer": "密钥引用 B"}),
        ]
        client_a = self._configured_provider_client(
            task_api_key_refs={"word.smart_write": "smart_write_a"}
        )
        client_b = self._configured_provider_client(
            task_api_key_refs={"word.smart_write": "smart_write_b"}
        )

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client_a.post_task("word.smart_write", "trace-ref-a", {}, "引用 A 提示词")
            client_b.post_task("word.smart_write", "trace-ref-b", {}, "引用 B 提示词")

        second_ref_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(second_ref_body["inputs"], {"query": "引用 B 提示词"})

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_does_not_retry_non_400_http_errors(self, urlopen) -> None:
        client = self._configured_provider_client()
        cases = (
            (401, ProviderAuthError),
            (403, ProviderAuthError),
            (500, ProviderUnavailableError),
        )

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            for status, expected_error in cases:
                with self.subTest(status=status):
                    urlopen.reset_mock()
                    urlopen.side_effect = make_http_error(status, {"message": "provider error"})
                    with self.assertRaises(expected_error):
                        client.post_task(
                            "word.smart_write",
                            "trace-http-{0}".format(status),
                            {},
                            "完整提示词",
                        )
                    self.assertEqual(urlopen.call_count, 1)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_does_not_retry_network_errors_or_timeouts(self, urlopen) -> None:
        client = self._configured_provider_client()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            urlopen.side_effect = URLError("connection reset")
            with self.assertRaises(ProviderUnavailableError):
                client.post_task("word.smart_write", "trace-network", {}, "完整提示词")
            self.assertEqual(urlopen.call_count, 1)

            urlopen.reset_mock()
            urlopen.side_effect = socket.timeout("timed out")
            with self.assertRaises(ProviderTimeoutError):
                client.post_task("word.smart_write", "trace-timeout", {}, "完整提示词")
            self.assertEqual(urlopen.call_count, 1)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_records_sanitized_compatibility_fallback_diagnostics(
        self,
        urlopen,
    ) -> None:
        prompt = "完整提示词-绝密"
        urlopen.side_effect = [
            make_http_error(
                400,
                {
                    "code": "invalid_param",
                    "message": "输入错误：{0}{1}".format(prompt, "X" * 1000),
                    "query": prompt,
                    "authorization": "Bearer task-secret",
                },
            ),
            FakeProviderResponse({"answer": "新版工作流结果"}),
        ]
        client = self._configured_provider_client()
        reset_provider_debug()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client.post_task("word.smart_write", "trace-debug-fallback", {}, prompt)

        debug = get_last_provider_debug()
        self.assertEqual(debug.get("inputMode"), "user-input-node")
        self.assertTrue(debug.get("compatibilityFallback"))
        self.assertEqual(debug.get("attemptCount"), 2)
        self.assertEqual(debug["response"]["status"], 200)
        self.assertNotIn("error", debug)
        compatibility_error = debug.get("compatibilityError")
        self.assertIsInstance(compatibility_error, dict)
        self.assertEqual(compatibility_error["status"], 400)
        body_preview = compatibility_error.get("bodyPreview")
        self.assertIsInstance(body_preview, str)
        self.assertIn("invalid_param", body_preview)
        self.assertLessEqual(len(body_preview), 480)
        self.assertNotIn(prompt, body_preview)
        self.assertNotIn("task-secret", body_preview)
        self.assertNotIn(prompt, json.dumps(debug, ensure_ascii=False))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_redacts_long_query_fragments_from_compatibility_error(
        self,
        urlopen,
    ) -> None:
        prompt = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-完整提示词"
        echoed_fragment = prompt[5:31]
        urlopen.side_effect = [
            make_http_error(
                400,
                {
                    "code": "invalid_param",
                    "message": "输入片段：" + echoed_fragment,
                },
            ),
            FakeProviderResponse({"answer": "新版工作流结果"}),
        ]
        client = self._configured_provider_client()
        reset_provider_debug()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client.post_task("word.smart_write", "trace-fragment-redaction", {}, prompt)

        body_preview = get_last_provider_debug()["compatibilityError"]["bodyPreview"]
        self.assertIn("invalid_param", body_preview)
        for index in range(len(prompt) - 15):
            self.assertNotIn(prompt[index : index + 16], body_preview)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_redacts_non_aligned_query_fragment_from_error_message(
        self,
        urlopen,
    ) -> None:
        prompt = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        echoed_fragment = prompt[1:9]
        urlopen.side_effect = [
            make_http_error(
                400,
                {
                    "code": "invalid_param",
                    "message": "输入片段：" + echoed_fragment,
                },
            ),
            FakeProviderResponse({"answer": "新版工作流结果"}),
        ]
        client = self._configured_provider_client()
        reset_provider_debug()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            client.post_task("word.smart_write", "trace-unaligned-redaction", {}, prompt)

        body_preview = get_last_provider_debug()["compatibilityError"]["bodyPreview"]
        self.assertIn("invalid_param", body_preview)
        self.assertNotIn(echoed_fragment, body_preview)

    def test_provider_debug_record_and_get_are_atomic(self) -> None:
        cleared = threading.Event()
        allow_update = threading.Event()
        reader_started = threading.Event()
        reader_done = threading.Event()
        reader_results = []

        class BlockingDebugDict(dict):
            def clear(self):
                super().clear()
                cleared.set()
                allow_update.wait(timeout=2)

        shared_debug = BlockingDebugDict(
            {
                "traceId": "trace-old",
                "taskType": "old.task",
                "url": "https://old.example",
            }
        )

        def write_debug():
            record_provider_debug(
                {
                    "traceId": "trace-new",
                    "taskType": "word.smart_write",
                    "url": "https://new.example/v1/chat-messages",
                }
            )

        def read_debug():
            reader_started.set()
            reader_results.append(get_last_provider_debug())
            reader_done.set()

        with patch.object(provider_client, "_LAST_PROVIDER_DEBUG", shared_debug):
            writer = threading.Thread(target=write_debug)
            reader = threading.Thread(target=read_debug)
            writer.start()
            self.assertTrue(cleared.wait(timeout=1))
            reader.start()
            self.assertTrue(reader_started.wait(timeout=1))
            reader_finished_before_update = reader_done.wait(timeout=0.2)
            allow_update.set()
            writer.join(timeout=1)
            reader.join(timeout=1)

        self.assertFalse(reader_finished_before_update)
        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(reader_results[0]["traceId"], "trace-new")
        self.assertEqual(reader_results[0]["taskType"], "word.smart_write")

    def test_read_http_error_body_limits_source_read_to_4096_bytes(self) -> None:
        class RecordingBody:
            def __init__(self):
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return b'{"code":"invalid_param","message":"bad request"}'

            def close(self):
                return None

        response_body = RecordingBody()
        http_error = HTTPError(
            "https://aibot.example/v1/chat-messages",
            400,
            "Bad Request",
            {},
            response_body,
        )

        body_preview = provider_client._read_http_error_body(http_error)

        self.assertEqual(response_body.read_sizes, [4096])
        self.assertIn("invalid_param", body_preview)

    def test_truncated_non_json_error_body_never_echoes_escaped_query_fragment(
        self,
    ) -> None:
        prompt = "甲敏感信息不得进入诊断输出乙"
        query_fragment = prompt[1:9]
        escaped_fragment = json.dumps(
            query_fragment,
            ensure_ascii=True,
        )[1:-1]
        raw_body = (
            '{"code":"invalid_param","message":"'
            + escaped_fragment
            + ("X" * 5000)
        ).encode("utf-8")

        class TruncatedBody:
            def read(self, size=-1):
                return raw_body[:size]

            def close(self):
                return None

        http_error = HTTPError(
            "https://aibot.example/v1/chat-messages",
            400,
            "Bad Request",
            {},
            TruncatedBody(),
        )

        body_preview = provider_client._read_http_error_body(
            http_error,
            query=prompt,
        )

        self.assertNotIn(query_fragment, body_preview)
        self.assertNotIn(escaped_fragment, body_preview)
        self.assertIn("redacted", body_preview)

    def test_provider_error_body_only_preserves_safe_identifier_fields(
        self,
    ) -> None:
        body_preview = provider_client._sanitize_provider_error_body(
            json.dumps(
                {
                    "code": "invalid_param",
                    "status": "bad status",
                    "type": "X" * 65,
                    "message": "provider echoed sensitive content",
                    "details": "more sensitive content",
                }
            )
        )

        sanitized = json.loads(body_preview)
        self.assertEqual(sanitized["code"], "invalid_param")
        self.assertEqual(sanitized["message"], "[redacted]")
        self.assertNotIn("status", sanitized)
        self.assertNotIn("type", sanitized)
        self.assertNotIn("details", sanitized)
        self.assertNotIn("sensitive content", body_preview)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_post_task_records_limited_sanitized_body_after_both_modes_fail(
        self,
        urlopen,
    ) -> None:
        prompt = "完整提示词-绝密"
        urlopen.side_effect = [
            make_http_error(400, {"code": "invalid_param", "message": "旧模式失败"}),
            make_http_error(
                400,
                {
                    "code": "invalid_param",
                    "message": "输入错误：{0}{1}".format(prompt, "X" * 1000),
                    "query": prompt,
                    "authorization": "Bearer task-secret",
                },
            ),
        ]
        client = self._configured_provider_client()
        reset_provider_debug()

        with patch.object(provider_client, "_PROVIDER_INPUT_MODE_CACHE", {}, create=True):
            with self.assertRaises(ProviderUnavailableError):
                client.post_task("word.smart_write", "trace-debug-failed", {}, prompt)

        debug = get_last_provider_debug()
        self.assertEqual(debug.get("inputMode"), "user-input-node")
        self.assertTrue(debug.get("compatibilityFallback"))
        self.assertEqual(debug.get("attemptCount"), 2)
        self.assertEqual(debug["error"]["status"], 400)
        body_preview = debug["error"].get("bodyPreview")
        self.assertIsInstance(body_preview, str)
        self.assertIn("invalid_param", body_preview)
        self.assertLessEqual(len(body_preview), 480)
        self.assertNotIn(prompt, body_preview)
        self.assertNotIn("task-secret", body_preview)
        self.assertEqual(urlopen.call_count, 2)

    def test_excel_analysis_request_accepts_table_payload(self):
        request = ExcelAnalysisRequest.parse_obj(
            {
                "workbookId": "analysis.xlsx",
                "scene": "excel",
                "scope": {
                    "type": "selection",
                    "sheetName": "经营数据",
                    "address": "A1:D4",
                },
                "table": {
                    "headers": ["月份", "部门", "金额", "状态"],
                    "rows": [
                        ["2026-01", "市场部", "120000", "已完成"],
                        ["2026-02", "市场部", "98000", "进行中"],
                    ],
                    "rowCount": 2,
                    "columnCount": 4,
                    "truncated": False,
                },
                "options": {"analysisRequirement": "关注金额变化和异常项。"},
            }
        )

        self.assertEqual(request.scene, "excel")
        self.assertEqual(request.scope.sheet_name, "经营数据")
        self.assertEqual(request.scope.address, "A1:D4")
        self.assertEqual(request.table.headers[0], "月份")
        self.assertEqual(request.options.analysis_requirement, "关注金额变化和异常项。")

    def test_build_excel_analysis_prompt_includes_range_headers_requirement_and_constraints(self):
        request = ExcelAnalysisRequest.parse_obj(
            {
                "workbookId": "analysis.xlsx",
                "scene": "excel",
                "scope": {"type": "usedRange", "sheetName": "Sheet1", "address": "A1:C3"},
                "table": {
                    "headers": ["项目", "金额", "状态"],
                    "rows": [["项目A", "100", "正常"], ["项目B", "300", "异常"]],
                    "rowCount": 2,
                    "columnCount": 3,
                    "truncated": True,
                },
                "options": {"analysisRequirement": "生成经营分析。"},
            }
        )

        prompt = build_excel_analysis_prompt(request)

        self.assertIn("企业表格数据分析助手", prompt)
        self.assertIn("工作表：Sheet1", prompt)
        self.assertIn("范围：A1:C3", prompt)
        self.assertIn("项目, 金额, 状态", prompt)
        self.assertIn("生成经营分析", prompt)
        self.assertIn("数据已截断", prompt)
        self.assertIn("不要声称已经修改单元格", prompt)
        self.assertIn("只基于表格数据", prompt)

    def test_parse_excel_analysis_answer_accepts_json_and_falls_back_to_text(self):
        parsed = parse_excel_analysis_answer(
            """
            ```json
            {
              "structuredReport": {
                "overview": "共 2 行数据。",
                "findings": ["金额集中在项目B。"],
                "risks": ["项目B状态异常。"],
                "actions": ["建议核查项目B。"]
              },
              "plainText": "本表显示项目B金额较高且状态异常，建议优先核查。"
            }
            ```
            """
        )

        self.assertEqual(parsed["structuredReport"]["overview"], "共 2 行数据。")
        self.assertEqual(parsed["structuredReport"]["findings"], ["金额集中在项目B。"])
        self.assertIn("项目B金额较高", parsed["plainText"])

        fallback = parse_excel_analysis_answer("### 分析结果\n项目B存在异常，建议核查。")
        self.assertIn("模型后台已返回表格分析结果", fallback["structuredReport"]["overview"])
        self.assertEqual(fallback["structuredReport"]["findings"], [])
        self.assertIn("项目B存在异常", fallback["plainText"])

    def test_excel_analysis_uses_independent_task_type_and_task_key(self):
        class CapturingProviderClient(ProviderClient):
            def __init__(self):
                super().__init__(AppSettings())
                self.calls = []

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
                self.calls.append(
                    {
                        "taskType": task_type,
                        "traceId": trace_id,
                        "inputData": input_data,
                        "query": query,
                        "timeoutSeconds": timeout_seconds,
                    }
                )
                return {
                    "answer": '{"structuredReport":{"overview":"概览","findings":["发现"],"risks":[],"actions":["建议"]},"plainText":"汇报段落"}'
                }

        request = ExcelAnalysisRequest.parse_obj(
            {
                "workbookId": "analysis.xlsx",
                "scene": "excel",
                "scope": {"type": "selection", "sheetName": "Sheet1", "address": "A1:B2"},
                "table": {
                    "headers": ["名称", "金额"],
                    "rows": [["A", "1"]],
                    "rowCount": 1,
                    "columnCount": 2,
                    "truncated": False,
                },
                "options": {"analysisRequirement": "生成简要分析。"},
            }
        )
        provider = CapturingProviderClient()

        result = provider.excel_analysis(request, trace_id="trace-excel-analysis")

        self.assertEqual(provider.calls[0]["taskType"], "excel.analysis")
        self.assertIn("生成简要分析", provider.calls[0]["query"])
        self.assertEqual(provider.calls[0]["timeoutSeconds"], 1800)
        self.assertEqual(result["plainText"], "汇报段落")

    def test_ppt_slide_assistant_request_accepts_camel_case_payload(self):
        request = PptSlideAssistantRequest.parse_obj(
            {
                "presentationId": "汇报材料.pptx",
                "scene": "ppt",
                "clientJobId": "client-ppt-slide-12345678",
                "slide": {
                    "index": 2,
                    "title": "项目进展",
                    "subtitle": "阶段成果与当前重点",
                    "textBlocks": ["总体方案设计已完成", "正在开展接口联调"],
                    "previousTitle": "项目背景",
                    "nextTitle": "风险与措施",
                    "truncated": False,
                },
                "userInstruction": "面向管理层，突出进展和风险。",
            }
        )

        self.assertEqual(request.presentation_id, "汇报材料.pptx")
        self.assertEqual(request.scene, "ppt")
        self.assertEqual(request.client_job_id, "client-ppt-slide-12345678")
        self.assertEqual(request.slide.subtitle, "阶段成果与当前重点")
        self.assertEqual(request.slide.text_blocks[0], "总体方案设计已完成")
        self.assertEqual(request.user_instruction, "面向管理层，突出进展和风险。")

    def test_ppt_slide_assistant_request_discards_host_object_values(self):
        request = PptSlideAssistantRequest.parse_obj(
            {
                "presentationId": {"Value": "不应进入提示词"},
                "clientJobId": {"Value": "不应进入任务号"},
                "slide": {
                    "index": {"Value": 9},
                    "title": {"Text": "不应进入标题"},
                    "subtitle": {"Text": "不应进入副标题"},
                    "textBlocks": ["有效正文", {"Text": "不应进入正文"}],
                    "previousTitle": {"Text": "不应进入相邻标题"},
                    "truncated": {"Value": True},
                },
                "userInstruction": {"Text": "不应进入要求"},
            }
        )

        self.assertEqual(request.presentation_id, "active-presentation")
        self.assertEqual(request.client_job_id, "")
        self.assertEqual(request.slide.index, 1)
        self.assertEqual(request.slide.title, "")
        self.assertEqual(request.slide.subtitle, "")
        self.assertEqual(request.slide.text_blocks, ["有效正文", ""])
        self.assertEqual(request.slide.previous_title, "")
        self.assertEqual(request.slide.truncated, False)
        self.assertEqual(request.user_instruction, "")

    def test_build_ppt_slide_prompt_keeps_subtitle_separate_and_limits_output(self):
        context = {
            "index": 2,
            "title": "项目进展",
            "subtitle": "阶段成果与当前重点",
            "textBlocks": ["总体方案设计已完成", "正在开展接口联调"],
            "previousTitle": "项目背景",
            "nextTitle": "风险与措施",
            "truncated": False,
        }

        prompt = build_ppt_slide_prompt(
            context,
            "面向管理层，突出进展和风险。",
            "optimize",
        )

        self.assertIn("当前页主标题：项目进展", prompt)
        self.assertIn("当前页副标题：阶段成果与当前重点", prompt)
        self.assertIn("当前页正文：\n总体方案设计已完成\n正在开展接口联调", prompt)
        self.assertIn("核心要点必须为 3 至 5 条", prompt)
        self.assertIn("不输出配色、版式、图标、图片、动画或页面操作建议", prompt)
        self.assertIn("不声称已经修改 PPT", prompt)
        self.assertIn("前后页标题只用于避免重复和保持衔接", prompt)

    def test_parse_ppt_slide_answer_accepts_json_markdown_think_and_raw_fallback(self):
        parsed_json = parse_ppt_slide_answer(
            """
            {"suggestedTitle":"项目总体进展","bullets":["完成总体方案设计","进入接口联调","关注接口稳定性"],"conclusion":"项目按计划推进。"}
            """
        )
        self.assertEqual(parsed_json["suggestedTitle"], "项目总体进展")
        self.assertEqual(len(parsed_json["bullets"]), 3)
        self.assertEqual(parsed_json["rawAnswer"], None)

        markdown = """## 建议标题
项目总体进展

## 核心要点
- 总体方案设计已完成
- 系统进入联调阶段
- 重点关注接口稳定性

## 本页结论
项目按计划推进，应集中完成联调和风险收敛。
"""
        parsed_markdown = parse_ppt_slide_answer(markdown)
        self.assertEqual(parsed_markdown["suggestedTitle"], "项目总体进展")
        self.assertEqual(len(parsed_markdown["bullets"]), 3)
        self.assertEqual(parsed_markdown["rawAnswer"], None)
        self.assertIn("1. 总体方案设计已完成", parsed_markdown["plainText"])

        parsed_think = parse_ppt_slide_answer("<think>内部推理</think>\n" + markdown)
        self.assertNotIn("内部推理", parsed_think["plainText"])
        self.assertEqual(parsed_think["conclusion"], "项目按计划推进，应集中完成联调和风险收敛。")

        fallback = parse_ppt_slide_answer("模型返回了一段无法分区的最终内容。")
        self.assertIn("无法分区", fallback["rawAnswer"])
        self.assertEqual(fallback["parseFallbackReason"], "ppt_output_not_structured")
        self.assertEqual(fallback["bullets"], [])

    def test_ppt_slide_assistant_uses_independent_task_type_and_timeout(self):
        class CapturingProviderClient(ProviderClient):
            def __init__(self):
                super().__init__(AppSettings(timeout_seconds=75))
                self.calls = []

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
                self.calls.append(
                    {
                        "taskType": task_type,
                        "traceId": trace_id,
                        "inputData": input_data,
                        "query": query,
                        "timeoutSeconds": timeout_seconds,
                    }
                )
                return {
                    "answer": '{"suggestedTitle":"项目总体进展","bullets":["完成方案设计","进入接口联调","关注接口稳定性"],"conclusion":"项目按计划推进。"}'
                }

        provider = CapturingProviderClient()
        context = {
            "index": 2,
            "title": "项目进展",
            "subtitle": "阶段成果与当前重点",
            "textBlocks": ["总体方案设计已完成", "正在开展接口联调"],
            "previousTitle": "项目背景",
            "nextTitle": "风险与措施",
            "truncated": False,
        }

        result = provider.ppt_slide_assistant(
            context,
            "面向管理层，突出进展和风险。",
            "optimize",
            "trace-ppt-slide",
        )

        self.assertEqual(provider.calls[0]["taskType"], "ppt.slide_assistant")
        self.assertEqual(provider.calls[0]["timeoutSeconds"], 1800)
        self.assertEqual(
            provider.calls[0]["inputData"],
            {"scene": "ppt", "slideIndex": 2, "mode": "optimize", "truncated": False},
        )
        self.assertEqual(result["modeUsed"], "optimize")
        self.assertEqual(result["suggestedTitle"], "项目总体进展")
        self.assertTrue(result["provider"].startswith("enterprise-dify-chat/"))

    def test_ppt_slide_assistant_returns_structured_unconfigured_result(self):
        class UnconfiguredProviderClient(ProviderClient):
            def __init__(self):
                super().__init__(AppSettings())
                self.debug_task_type = ""

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return False

            def record_unconfigured_debug(self, task_type: str, trace_id: str, query: str) -> None:
                self.debug_task_type = task_type

        provider = UnconfiguredProviderClient()
        result = provider.ppt_slide_assistant(
            {
                "index": 4,
                "title": "项目进展",
                "subtitle": "",
                "textBlocks": [],
                "previousTitle": "项目背景",
                "nextTitle": "风险与措施",
                "truncated": False,
            },
            "生成本页内容。",
            "generate",
            "trace-ppt-unconfigured",
        )

        self.assertEqual(provider.debug_task_type, "ppt.slide_assistant")
        self.assertEqual(result["provider"], "mock")
        self.assertEqual(result["modeUsed"], "generate")
        self.assertEqual(result["suggestedTitle"], "项目进展")
        self.assertEqual(len(result["bullets"]), 3)
        self.assertIn("尚未配置", result["plainText"])

    def test_word_request_accepts_smart_imitation_options(self):
        payload = {
            "documentId": "imitate.docx",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "模板段落。",
                "paragraphs": [],
                "headings": [],
            },
            "options": {
                "imitationRequirement": "仿写成安全整改通知。",
                "imitationReferenceMaterial": "整改对象：核心系统。",
            },
        }
        if hasattr(WordDocumentRequest, "model_validate"):
            request = WordDocumentRequest.model_validate(payload)
        else:
            request = WordDocumentRequest.parse_obj(payload)

        self.assertEqual(request.options.imitation_requirement, "仿写成安全整改通知。")
        self.assertEqual(request.options.imitation_reference_material, "整改对象：核心系统。")

    def test_build_smart_imitation_prompt_includes_template_requirement_reference_and_constraints(self):
        prompt = build_smart_imitation_prompt(
            template_text="本项目坚持问题导向，持续完善闭环机制。",
            requirement="仿写成网络安全整改说明。",
            reference_material="整改范围：终端账号、日志审计、漏洞修复。",
        )

        self.assertIn("企业办公文档智能仿写助手", prompt)
        self.assertIn("本项目坚持问题导向", prompt)
        self.assertIn("仿写成网络安全整改说明", prompt)
        self.assertIn("终端账号、日志审计、漏洞修复", prompt)
        self.assertIn("不编造事实", prompt)
        self.assertIn("只输出仿写后的正文", prompt)

    def test_smart_imitation_uses_independent_task_type_and_task_key(self):
        class CapturingProviderClient(ProviderClient):
            def __init__(self):
                super().__init__(AppSettings())
                self.calls = []

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
                self.calls.append(
                    {
                        "taskType": task_type,
                        "traceId": trace_id,
                        "inputData": input_data,
                        "query": query,
                        "timeoutSeconds": timeout_seconds,
                    }
                )
                return {"answer": "仿写后的正文。"}

        provider = CapturingProviderClient()

        result = provider.smart_imitation(
            template_text="模板正文。",
            requirement="仿写成技术风险提示。",
            reference_material="风险：接口超时。",
            trace_id="trace-smart-imitation",
        )

        self.assertEqual(result["rewrittenText"], "仿写后的正文。")
        self.assertEqual(provider.calls[0]["taskType"], "word.smart_imitation")
        self.assertIn("仿写成技术风险提示", provider.calls[0]["query"])

    def test_load_settings_reads_provider_fields(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "servicePort": 19100,
              "providerType": "enterprise-chat-api",
              "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
              "providerApiKeyEnv": "ENTERPRISE_AI_API_KEY",
              "providerChatPath": "/chat-messages",
              "providerMode": "blocking"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.service_port, 19100)
        self.assertEqual(settings.provider_type, "enterprise-chat-api")
        self.assertEqual(settings.provider_base_url, "https://aibot.chinasatnet.com.cn/v1")
        self.assertEqual(settings.provider_api_key_env, "ENTERPRISE_AI_API_KEY")
        self.assertEqual(settings.provider_chat_path, "/chat-messages")
        self.assertEqual(settings.provider_mode, "blocking")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_format_review_roles_uses_slow_model_timeout_budget(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self, settings: AppSettings) -> None:
                super().__init__(settings)
                self.captured_timeout = None

            def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
                self.captured_timeout = timeout_seconds
                return {"answer": "[]"}

        settings = AppSettings(timeout_seconds=75)
        client = CapturingProviderClient(settings)

        client.format_review_roles("trace-format-timeout", {}, "请识别段落角色")

        self.assertEqual(client.captured_timeout, 60)

    def test_document_review_uses_longer_timeout_budget(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self, settings: AppSettings) -> None:
                super().__init__(settings)
                self.captured_timeout = None

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
                self.captured_timeout = timeout_seconds
                return {"answer": "{\"summary\":\"未发现问题。\",\"issues\":[]}"}

        settings = AppSettings(timeout_seconds=75)
        client = CapturingProviderClient(settings)

        client.document_review("需要审查的较长文档。", "trace-doc-timeout", "technical_solution", "检查表达。")

        self.assertEqual(client.captured_timeout, 1800)

    def test_post_task_treats_socket_timeout_as_provider_timeout(self) -> None:
        settings = AppSettings(
            provider_base_url="https://aibot.example.com/v1",
            timeout_seconds=75,
        )
        client = ProviderClient(settings)

        with patch("app.services.provider_client.urllib_request.urlopen", side_effect=socket.timeout("timed out")):
            with self.assertRaises(ProviderTimeoutError):
                client.post_task("word.document_review", "trace-timeout", {}, "请审查文档。", timeout_seconds=150)

    def test_load_settings_reads_task_api_key_refs(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "taskApiKeyRefs": {
                "word.format_review": "format_key"
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.task_api_key_refs["word.format_review"], "format_key")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_reads_task_routes(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerType": "enterprise-dify-workflow",
              "providerChatPath": "/workflows/run",
              "taskRoutes": {
                "word.document_review": {
                  "taskId": "word.document_review",
                  "enabled": true
                },
                "word.format_review": {
                  "taskId": "word.format_review",
                  "enabled": false
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.task_routes["word.document_review"].task_id, "word.document_review")
        self.assertTrue(settings.task_routes["word.document_review"].enabled)
        self.assertFalse(settings.task_routes["word.format_review"].enabled)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_reads_task_route_transport_fields(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerType": "enterprise-dify-workflow",
              "providerBaseUrl": "https://aibot.example/v1",
              "taskRoutes": {
                "word.document_review": {
                  "taskId": "word.document_review",
                  "path": "/workflows/run",
                  "apiKeyRef": "document_review",
                  "payloadStyle": "workflow",
                  "responseMode": "blocking",
                  "outputKey": "result",
                  "enabled": true
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)
        route = settings.task_routes["word.document_review"]

        self.assertEqual(route.path, "/workflows/run")
        self.assertEqual(route.api_key_ref, "document_review")
        self.assertEqual(route.payload_style, "workflow")
        self.assertEqual(route.response_mode, "blocking")
        self.assertEqual(route.output_key, "result")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_does_not_inject_default_task_routes_into_old_config(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "目标机旧配置",
              "providerBaseUrl": "https://aibot.example/v1"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "目标机旧配置")
        self.assertEqual(settings.task_routes, {})

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_preserves_user_task_route_over_default_route(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerBaseUrl": "https://aibot.example/v1",
              "taskRoutes": {
                "word.smart_write": {
                  "taskId": "word.smart_write",
                  "path": "/chat-messages",
                  "apiKeyRef": "custom_smart_write",
                  "payloadStyle": "chat",
                  "responseMode": "blocking",
                  "outputKey": "answer",
                  "enabled": true
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)
        route = settings.task_routes["word.smart_write"]

        self.assertEqual(route.path, "/chat-messages")
        self.assertEqual(route.api_key_ref, "custom_smart_write")
        self.assertEqual(route.payload_style, "chat")
        self.assertEqual(route.output_key, "answer")
        self.assertNotIn("word.document_review", settings.task_routes)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_provider_client_resolves_default_task_route(self) -> None:
        client = ProviderClient(load_settings())

        route = client.resolve_task_route("word.smart_write")

        self.assertEqual(route.task_id, "word.smart_write")
        self.assertTrue(route.enabled)

    def test_task_routes_to_dict_exposes_safe_summary(self) -> None:
        settings = load_settings()
        settings.task_routes = {
            "word.document_review": type(
                "Route",
                (),
                {
                    "task_id": "word.document_review",
                    "enabled": True,
                    "path": "/workflows/run",
                    "api_key_ref": "document_review",
                    "payload_style": "workflow",
                    "response_mode": "blocking",
                    "output_key": "result",
                },
            )()
        }

        summary = task_routes_to_dict(settings)

        self.assertEqual(summary["word.document_review"]["taskId"], "word.document_review")
        self.assertTrue(summary["word.document_review"]["enabled"])
        self.assertEqual(summary["word.document_review"]["path"], "/workflows/run")
        self.assertEqual(summary["word.document_review"]["apiKeyRef"], "document_review")
        self.assertEqual(summary["word.document_review"]["payloadStyle"], "workflow")
        self.assertNotIn("apiKey", summary["word.document_review"])

    def test_build_route_request_payload_uses_unified_chat_query_shape(self) -> None:
        settings = load_settings()
        settings.provider_mode = "blocking"
        settings.provider_chat_path = "/chat-messages"
        route = type(
            "Route",
            (),
            {
                "task_id": "word.document_review",
                "payload_style": "workflow",
                "response_mode": "streaming",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {"task_id": "word.document_review", "document_text": "正文"},
            "检查正文",
        )

        self.assertEqual(payload["query"], "检查正文")
        self.assertEqual(payload["inputs"], {"query": "检查正文"})
        self.assertEqual(payload["response_mode"], "streaming")
        self.assertEqual(payload["conversation_id"], "")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_route_request_payload_ignores_custom_start_variables(self) -> None:
        settings = load_settings()
        settings.provider_mode = "blocking"
        route = type(
            "Route",
            (),
            {
                "task_id": "word.rewrite",
                "payload_style": "chat",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {
                "task_id": "word.rewrite",
                "source_text": "原文",
                "text": "原文",
                "mode": "rewrite",
                "rewrite_mode": "rewrite",
            },
            "请改写原文",
        )

        self.assertEqual(payload["query"], "请改写原文")
        self.assertEqual(payload["inputs"], {"query": "请改写原文"})
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)
        self.assertEqual(payload["conversation_id"], "")

    def test_build_route_request_payload_keeps_legacy_chat_fields_when_requested(self) -> None:
        settings = load_settings()
        route = type(
            "Route",
            (),
            {
                "task_id": "word.rewrite",
                "payload_style": "legacy-chat",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {"task_id": "word.rewrite", "source_text": "原文"},
            "请改写原文",
        )

        self.assertEqual(payload["inputs"], {"query": "请改写原文"})
        self.assertEqual(payload["query"], "请改写原文")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_route_request_payload_does_not_send_smart_write_workflow_inputs(self) -> None:
        settings = load_settings()
        route = type(
            "Route",
            (),
            {
                "task_id": "word.smart_write",
                "payload_style": "workflow",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {
                "source_text": "原文",
                "write_action": "rewrite",
                "style": "formal",
                "focus": "default",
                "length": "same",
                "user_prompt": "补充要求",
                "selection_mode": "selection",
                "trace_id": "trace-smart",
            },
            "内部提示词",
        )

        self.assertEqual(payload["query"], "内部提示词")
        self.assertEqual(payload["inputs"], {"query": "内部提示词"})
        self.assertNotIn("input_data", payload)
        self.assertNotIn("source_text", payload["inputs"])
        self.assertNotIn("write_action", payload["inputs"])
        self.assertNotIn("user_prompt", payload["inputs"])

    def test_rewrite_sends_full_prompt_as_unified_query_only(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type: str, trace_id: str, input_data: dict, query: str) -> dict:
                self.captured_input_data = input_data
                self.captured_query = query
                return {"answer": "这是改写后的文本。"}

        client = CapturingProviderClient()

        result = client.rewrite(
            "原文内容",
            "rewrite",
            "trace-001",
            user_instruction="更正式",
            style="formal",
            focus="risk",
            length="same",
        )

        self.assertEqual(result["rewrittenText"], "这是改写后的文本。")
        self.assertEqual(client.captured_input_data, {})
        self.assertIn("待处理内容：\n原文内容", client.captured_query)
        self.assertIn("不要原样返回待处理内容", client.captured_query)

    def test_smart_write_sends_full_prompt_as_unified_query_only(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type: str, trace_id: str, input_data: dict, query: str) -> dict:
                self.captured_input_data = input_data
                self.captured_query = query
                return {"data": {"outputs": {"result": "智能编写后的文本。"}}}

        client = CapturingProviderClient()

        result = client.smart_write(
            "原文内容",
            "rewrite",
            "trace-smart",
            user_prompt="更正式",
            style="formal",
            focus="risk",
            length="same",
            selection_mode="selection",
        )

        self.assertEqual(result["rewrittenText"], "智能编写后的文本。")
        self.assertEqual(client.captured_input_data, {})
        self.assertIn("待处理原文：\n原文内容", client.captured_query)
        self.assertIn("不允许原样返回原文", client.captured_query)

    def test_route_api_key_uses_ref_file_before_default_key(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "env-secret"
        try:
            save_route_api_key("document_review", "route-secret", tmp_dir)
            client = ProviderClient(load_settings())
            client.settings.provider_base_url = "https://aibot.example/v1"
            self.assertEqual(client.get_api_key("document_review", tmp_dir), "route-secret")
            clear_route_api_key("document_review", tmp_dir)
            self.assertEqual(client.get_api_key("document_review", tmp_dir), "env-secret")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous
            if default_key.exists():
                default_key.unlink()
            route_key = tmp_dir / "provider_api_keys" / "document_review"
            if route_key.exists():
                route_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_task_api_key_overrides_unified_key_for_matching_task(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        try:
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            settings.task_api_key_refs = {"word.format_review": "format_review"}
            client = ProviderClient(settings)
            self.assertEqual(client.get_api_key_for_task("word.format_review", tmp_dir), "default-secret")
            save_route_api_key("format_review", "format-secret", tmp_dir)
            self.assertEqual(client.get_api_key_for_task("word.format_review", tmp_dir), "format-secret")
            self.assertEqual(client.get_api_key_for_task("word.smart_write", tmp_dir), "default-secret")
        finally:
            clear_route_api_key("format_review", tmp_dir)
            if default_key.exists():
                default_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_named_task_configuration_uses_unified_env_or_default_key(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "env-secret"
        try:
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            client = ProviderClient(settings)

            self.assertTrue(client.is_task_configured("word.smart_write", tmp_dir))
            save_route_api_key("word_smart_write", "smart-secret", tmp_dir)
            self.assertTrue(client.is_task_configured("word.smart_write", tmp_dir))
            self.assertEqual(client.get_auth_source_for_task("word.smart_write", tmp_dir), "task-file")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous
            clear_route_api_key("word_smart_write", tmp_dir)
            if default_key.exists():
                default_key.unlink()
            route_key = get_route_api_key_path("word_smart_write", tmp_dir)
            if route_key.exists():
                route_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_route_diagnostics_exposes_unified_chat_endpoint_without_secret(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        try:
            save_local_api_key("smart-secret", tmp_dir / "provider_api_key")
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            client = ProviderClient(settings)

            diagnostics = client.build_route_diagnostics(key_base_path=tmp_dir)
            self.assertEqual(diagnostics["version"], "0.17.0-alpha")
            self.assertEqual(diagnostics["url"], "https://aibot.example/v1/chat-messages")
            self.assertEqual(diagnostics["path"], "/chat-messages")
            self.assertEqual(diagnostics["payloadStyle"], "chat")
            self.assertTrue(diagnostics["configured"])
            self.assertEqual(diagnostics["authSource"], "file")
            self.assertIn("word.format_review", diagnostics["taskApiKeys"])
            self.assertEqual(diagnostics["routes"], {})
            self.assertNotIn("smart-secret", str(diagnostics))
        finally:
            clear_local_api_key(tmp_dir / "provider_api_key")
            clear_route_api_key("word_smart_write", tmp_dir)
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_provider_debug_records_sanitized_request_and_response(self) -> None:
        full_prompt = "请改写这段很长的原文，包含不应该完整暴露在调试接口里的内容。"
        reset_provider_debug()

        record_provider_debug(
            {
                "traceId": "trace-debug",
                "taskType": "word.smart_write",
                "url": "https://aibot.example/v1/chat-messages",
                "provider": "enterprise-dify-chat",
                "providerName": "企业大模型接口",
                "providerType": "enterprise-dify-chat",
                "providerBaseUrlConfigured": True,
                "authSource": "task-file",
                "taskAuthSource": "task-file",
                "taskApiKeyRef": "word_smart_write",
                "request": {
                    "body": build_provider_request_payload(load_settings(), {}, full_prompt),
                },
                "response": {
                    "status": 200,
                    "body": {
                        "answer": "# 标题\n\n1. 第一项\n2. 第二项\n\n**重点内容**",
                        "conversation_id": "conv-1",
                    },
                },
            }
        )

        debug = get_last_provider_debug()

        self.assertEqual(debug["traceId"], "trace-debug")
        self.assertEqual(debug["taskType"], "word.smart_write")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["providerName"], "企业大模型接口")
        self.assertEqual(debug["providerType"], "enterprise-dify-chat")
        self.assertTrue(debug["providerBaseUrlConfigured"])
        self.assertEqual(debug["authSource"], "task-file")
        self.assertEqual(debug["taskAuthSource"], "task-file")
        self.assertEqual(debug["taskApiKeyRef"], "word_smart_write")
        self.assertEqual(debug["request"]["bodyKeys"], ["conversation_id", "files", "inputs", "query", "response_mode", "user"])
        self.assertEqual(debug["request"]["inputsKeys"], ["query"])
        self.assertEqual(debug["request"]["queryLength"], len(full_prompt))
        self.assertIn("queryPreview", debug["request"])
        self.assertEqual(debug["response"]["status"], 200)
        self.assertEqual(debug["response"]["bodyKeys"], ["answer", "conversation_id"])
        self.assertEqual(debug["response"]["answerLength"], len("# 标题\n\n1. 第一项\n2. 第二项\n\n**重点内容**"))
        self.assertEqual(
            debug["response"]["answerFormat"],
            {
                "containsMarkdown": True,
                "containsHeading": True,
                "containsOrderedList": True,
                "containsUnorderedList": False,
                "containsBold": True,
                "containsParagraphBreak": True,
            },
        )
        self.assertNotIn("Authorization", str(debug))
        self.assertNotIn(full_prompt, str(debug))

    def test_provider_debug_records_sanitized_error(self) -> None:
        reset_provider_debug()

        record_provider_debug(
            {
                "traceId": "trace-error",
                "taskType": "word.smart_write",
                "url": "https://aibot.example/v1/chat-messages",
                "request": {
                    "body": build_provider_request_payload(load_settings(), {}, "请改写原文"),
                },
                "error": {
                    "type": "HTTPError",
                    "status": 400,
                    "message": "Bad Request: missing query",
                },
            }
        )

        debug = get_last_provider_debug()

        self.assertEqual(debug["error"]["type"], "HTTPError")
        self.assertEqual(debug["error"]["status"], 400)
        self.assertIn("Bad Request", debug["error"]["message"])
        self.assertNotIn("请改写原文", str(debug))

    def test_smart_write_mock_records_debug_skip_reason(self) -> None:
        settings = load_settings()
        settings.provider_base_url = ""
        client = ProviderClient(settings)
        reset_provider_debug()

        result = client.smart_write("待改写原文", "rewrite", "trace-mock-debug")
        debug = get_last_provider_debug()

        self.assertEqual(result["provider"], "mock")
        self.assertEqual(debug["traceId"], "trace-mock-debug")
        self.assertEqual(debug["taskType"], "word.smart_write")
        self.assertEqual(debug["provider"], "mock")
        self.assertEqual(debug["skipReason"], "provider_not_configured")
        self.assertFalse(debug["providerBaseUrlConfigured"])
        self.assertEqual(debug["authSource"], "none")
        self.assertGreater(debug["request"]["queryLength"], len("待改写原文"))
        self.assertNotIn("待改写原文", str(debug))

    def test_record_skipped_debug_records_format_review_skip_reason(self) -> None:
        settings = load_settings()
        settings.provider_base_url = "https://aibot.example/v1"
        client = ProviderClient(settings)
        reset_provider_debug()

        client.record_skipped_debug(
            "word.format_review",
            "trace-format-skip",
            "格式审查未读取到正文段落，未调用模型后台。",
            "no_paragraphs",
            provider="local",
        )
        debug = get_last_provider_debug()

        self.assertEqual(debug["traceId"], "trace-format-skip")
        self.assertEqual(debug["taskType"], "word.format_review")
        self.assertEqual(debug["provider"], "local")
        self.assertEqual(debug["skipReason"], "no_paragraphs")
        self.assertTrue(debug["providerBaseUrlConfigured"])
        self.assertEqual(debug["taskAuthSource"], "none")
        self.assertEqual(debug["taskApiKeyRef"], "word_format_review")
        self.assertIn("request", debug)

    def test_load_settings_defaults_provider_base_url_to_empty(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "仅配置名称"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.provider_base_url, "")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_updates_config_file(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "servicePort": 19100,
              "providerType": "enterprise-chat-api",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("https://new.example/v1", config_file)
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_base_url, "https://new.example/v1")
        self.assertEqual(settings.service_port, 19100)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_task_api_key_ref_updates_config_file(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_task_api_key_ref("word.format_review", "format_key", config_file)
        settings = load_settings(config_file)

        self.assertEqual(settings.task_api_key_refs["word.format_review"], "format_key")
        self.assertEqual(settings.provider_base_url, "https://old.example/v1")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_updates_provider_name(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "旧名称",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("https://new.example/v1", config_file, provider_name="新名称")
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "新名称")
        self.assertEqual(settings.provider_base_url, "https://new.example/v1")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_allows_empty_url_and_updates_name(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "旧名称",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("", config_file, provider_name="自定义供应商")
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "自定义供应商")
        self.assertEqual(settings.provider_base_url, "")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_provider_requires_key_and_base_url_to_be_configured(self) -> None:
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "secret"
        try:
            empty_url_client = ProviderClient(load_settings())
            empty_url_client.settings.provider_base_url = ""
            self.assertFalse(empty_url_client.is_configured())

            configured_client = ProviderClient(load_settings())
            configured_client.settings.provider_base_url = "https://new.example/v1"
            self.assertTrue(configured_client.is_configured())
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous

    def test_default_provider_client_refreshes_settings_before_task_configuration(self) -> None:
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "secret"
        try:
            with patch(
                "app.services.provider_client.load_settings",
                side_effect=[
                    AppSettings(provider_base_url=""),
                    AppSettings(provider_base_url="https://aibot.example/v1"),
                ],
            ):
                client = ProviderClient()

                self.assertTrue(client.is_task_configured("word.smart_write"))
                self.assertEqual(client.settings.provider_base_url, "https://aibot.example/v1")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous

    def test_template_loader_resolves_default_root_from_package_base(self) -> None:
        previous_cwd = Path.cwd()
        os.chdir(ROOT)
        try:
            loader = TemplateLoader()
            template_ids = {item["id"] for item in loader.list_templates()}
        finally:
            os.chdir(previous_cwd)

        self.assertIn("general-office", template_ids)
        self.assertIn("technical-file-format-requirements", template_ids)

    def test_build_rewrite_prompt_includes_user_instruction(self) -> None:
        prompt = build_rewrite_prompt(
            text="项目进展总体正常，但风险项较多。",
            mode="rewrite",
            user_instruction="请突出风险和下一步计划，压缩到200字以内。",
            style="formal",
            focus="risk",
            length="concise",
        )

        self.assertIn("保留原意，不编造事实", prompt)
        self.assertIn("不要原样返回待处理内容", prompt)
        self.assertIn("用户附加要求", prompt)
        self.assertIn("请突出风险和下一步计划，压缩到200字以内。", prompt)
        self.assertIn("项目进展总体正常，但风险项较多。", prompt)

    def test_build_smart_write_prompt_requires_changed_output(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目进展总体正常。",
            action="rewrite",
            user_prompt="更正式",
            style="formal",
            focus="risk",
            length="same",
        )

        self.assertIn("企业办公文档智能编写助手", prompt)
        self.assertIn("不允许原样返回原文", prompt)
        self.assertIn("保持待处理原文的段落数量和换行结构", prompt)
        self.assertIn("如果原文有多个段落，输出也应保留相近分段", prompt)
        self.assertIn("原文已有标题、列表、序号、表格或强调格式时", prompt)
        self.assertIn("不要额外新增原文没有、用户也未要求的 Markdown 标题、项目符号、编号列表或表格", prompt)
        self.assertIn("待处理原文：\n项目进展总体正常。", prompt)

    def test_build_smart_write_prompt_uses_soetech_option_text(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目已经完成初步建设。",
            action="rewrite",
            user_prompt="语言适合技术方案正文",
            style="standard",
            focus="acceptance",
            length="expanded",
        )

        self.assertIn("国企技术方案常用的正式、准确、克制表达", prompt)
        self.assertIn("交付物、验收标准、问题闭环、证据材料", prompt)
        self.assertIn("不编造事实", prompt)
        self.assertIn("语言适合技术方案正文", prompt)

    def test_build_smart_write_prompt_preserves_legacy_option_aliases(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目进展总体正常。",
            action="rewrite",
            style="formal",
            focus="next_step",
            length="default",
        )

        self.assertIn("国企技术方案常用的正式、准确、克制表达", prompt)
        self.assertIn("解决措施、实施路径、责任分工、时间节点", prompt)
        self.assertIn("保持与原文相近的篇幅", prompt)

    def test_extract_answer_reads_enterprise_chat_response(self) -> None:
        body = {
            "event": "message",
            "conversation_id": "abc",
            "message_id": "msg-1",
            "answer": "这是改写后的文档内容。",
        }

        self.assertEqual(extract_answer(body), "这是改写后的文档内容。")

    def test_extract_answer_removes_think_tag_content(self) -> None:
        body = {
            "answer": "<think>这里是深度思考过程，不应出现在预览中。</think>\n这是最终输出。"
        }

        result = extract_answer(body)

        self.assertEqual(result, "这是最终输出。")
        self.assertNotIn("think", result.lower())
        self.assertNotIn("深度思考", result)

    def test_extract_answer_reads_workflow_outputs(self) -> None:
        body = {
            "data": {
                "outputs": {
                    "result": "<think>{\"draft\":true}</think>\n{\"issues\":[]}"
                }
            }
        }

        self.assertEqual(extract_answer(body, output_key="result"), "{\"issues\":[]}")

    def test_default_document_review_prompt_changes_by_document_type(self) -> None:
        solution_prompt = get_default_document_review_prompt("technical_solution")
        acceptance_prompt = get_default_document_review_prompt("contract_acceptance")
        test_outline_prompt = get_default_document_review_prompt("test_outline")

        self.assertIn("架构边界", solution_prompt)
        self.assertIn("验收证据", acceptance_prompt)
        self.assertIn("测试范围", test_outline_prompt)
        self.assertNotEqual(acceptance_prompt, solution_prompt)
        self.assertNotEqual(test_outline_prompt, solution_prompt)

    def test_document_review_prompt_and_parser_use_markdown_json(self) -> None:
        prompt = build_document_review_prompt(
            "这是一个技术文挡。",
            "technical_solution",
            "重点检查错别字和表达逻辑。",
        )
        parsed = parse_document_review_answer(
            extract_answer({
                "answer": """
            <think>先分析错别字和表达问题。</think>
            ```json
            {
              "summary": "发现一项问题。",
              "issues": [
                {
                  "category": "错别字",
                  "severity": "高",
                  "location": "第 1 段",
                  "originalText": "文挡",
                  "problem": "疑似错别字。",
                  "suggestion": "改为“文档”。",
                  "suggestedRewrite": "文档"
                }
              ]
            }
            ```
            """
            })
        )

        self.assertIn("重点检查错别字和表达逻辑。", prompt)
        self.assertIn("typo、expression、logic、fluency、professional", prompt)
        self.assertEqual(parsed["summary"], "发现一项问题。")
        self.assertEqual(parsed["issues"][0]["category"], "typo")
        self.assertEqual(parsed["issues"][0]["severity"], "high")

    @unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is required for model parsing")
    def test_document_structure_is_accepted_in_word_request(self) -> None:
        from app.core.models import WordDocumentRequest

        request = WordDocumentRequest.parse_obj(
            {
                "documentId": "doc-structure",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "一、总体要求\n正文内容",
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "一、总体要求",
                            "styleName": "Heading 1",
                            "fontName": "黑体",
                            "fontSize": 12,
                            "outlineLevel": 1,
                        }
                    ],
                    "headings": [{"level": 1, "text": "一、总体要求"}],
                    "documentStructure": {
                        "doc_name": "安全运行方案.docx",
                        "template_id": "technical-file-format-requirements",
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "一、总体要求",
                                "style_name": "Heading 1",
                                "font_family": "黑体",
                            }
                        ],
                        "capabilities": {
                            "paragraph_style_extracted": True,
                            "table_extracted": False,
                        },
                    },
                },
            }
        )

        self.assertEqual(request.content.document_structure["doc_name"], "安全运行方案.docx")
        self.assertTrue(request.content.document_structure["capabilities"]["paragraph_style_extracted"])

    @unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is required for model parsing")
    def test_word_request_coerces_host_object_shaped_values(self) -> None:
        from app.core.models import WordDocumentRequest

        payload = {
            "scene": "word",
            "selectionMode": "unexpected",
            "content": {
                "plainText": {"bad": "host-object"},
                "paragraphs": [
                    {
                        "index": "1",
                        "text": {"bad": "host-object"},
                        "styleName": {"bad": "style-object"},
                        "fontName": {"bad": "font-object"},
                        "fontSize": {"bad": "size-object"},
                        "outlineLevel": {"bad": "level-object"},
                        "lineSpacing": {"bad": "spacing-object"},
                        "bold": -1,
                        "italic": "0",
                        "underline": -4142,
                    }
                ],
                "headings": {"bad": "not-list"},
                "documentStructure": "not-dict",
            },
        }

        if hasattr(WordDocumentRequest, "model_validate"):
            request = WordDocumentRequest.model_validate(payload)
        else:
            request = WordDocumentRequest.parse_obj(payload)

        self.assertEqual(request.document_id, "unnamed.docx")
        self.assertEqual(request.selection_mode, "document")
        self.assertEqual(request.content.plain_text, "")
        self.assertEqual(len(request.content.paragraphs), 1)
        paragraph = request.content.paragraphs[0]
        self.assertEqual(paragraph.index, 1)
        self.assertEqual(paragraph.text, "")
        self.assertEqual(paragraph.style_name, "")
        self.assertIsNone(paragraph.font_size)
        self.assertTrue(paragraph.bold)
        self.assertFalse(paragraph.italic)
        self.assertEqual(paragraph.underline, -4142)
        self.assertEqual(request.content.headings, [])
        self.assertEqual(request.content.document_structure, {})

    def test_build_provider_request_payload_uses_unified_chat_sys_query_shape(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-dify-chat"
        settings.provider_chat_path = "/chat-messages"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.document_review", "taskType": "word.document_review"},
            query="请审校文档。",
        )

        self.assertEqual(payload["inputs"], {"query": "请审校文档。"})
        self.assertEqual(payload["query"], "请审校文档。")
        self.assertEqual(payload["conversation_id"], "")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_provider_request_payload_ignores_input_data_for_chat_message_shape(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-chat-api"
        settings.provider_chat_path = "/chat-messages"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.rewrite", "taskType": "word.rewrite"},
            query="请改写。",
        )

        self.assertEqual(payload["inputs"], {"query": "请改写。"})
        self.assertEqual(payload["query"], "请改写。")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertEqual(payload["conversation_id"], "")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

if __name__ == "__main__":
    unittest.main()
