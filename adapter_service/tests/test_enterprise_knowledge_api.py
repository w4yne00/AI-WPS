import base64
import csv
import asyncio
import gc
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from app.services.enterprise_knowledge.imports import (
    CSV_MIME,
    IMPORT_COLUMNS,
    ImportPreviewStore,
    generate_csv_template,
)
from app.services.enterprise_knowledge.models import KnowledgeError, MAX_IMPORT_BYTES
from app.services.enterprise_knowledge.service import EnterpriseKnowledgeService
from app.services.enterprise_knowledge.store import EnterpriseKnowledgeStore


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.api.enterprise_knowledge import (
        ImportApplyRequest,
        ImportPreviewRequest,
        KnowledgeItemRequest,
        apply_import,
        backup_knowledge,
        create_item,
        delete_item,
        download_csv_template,
        download_xlsx_template,
        export_knowledge_csv,
        get_diagnostics,
        get_summary,
        list_items,
        preview_import,
        update_item,
    )
    from app.core.errors import AdapterError
    app = app_main.app


def term_payload(preferred_text="卫星互联网运营管理平台", aliases=None, **overrides):
    payload = {
        "type": "term",
        "scope": "global",
        "category": "系统",
        "preferredText": preferred_text,
        "aliases": list(aliases or ["卫星网管平台"]),
        "forbiddenVariants": ["卫星网管系统"],
        "definition": "公司统一系统名称。",
        "contextKeywords": ["平台", "运营"],
        "priority": "high",
        "enabled": True,
        "note": "测试条目",
    }
    payload.update(overrides)
    return payload


def style_payload(name="结论先行", **overrides):
    payload = {
        "type": "style",
        "scope": "word.smart_write",
        "name": name,
        "ruleText": "先给出结论，再说明依据。",
        "positiveExample": "总体方案已完成。",
        "negativeExample": "经过大量工作，终于完成总体方案。",
        "contextKeywords": ["汇报", "进展"],
        "alwaysApply": False,
        "priority": "medium",
        "enabled": True,
        "note": "测试规则",
    }
    payload.update(overrides)
    return payload


def import_csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(IMPORT_COLUMNS)
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class EnterpriseKnowledgeDirectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "enterprise-knowledge.db"
        self.store = EnterpriseKnowledgeStore(self.db_path)
        self.service = EnterpriseKnowledgeService(self.store)
        self.preview_store = ImportPreviewStore()
        self.service_patch = patch(
            "app.api.enterprise_knowledge.get_enterprise_knowledge_service",
            return_value=self.service,
        )
        self.preview_patch = patch(
            "app.api.enterprise_knowledge.DEFAULT_IMPORT_PREVIEW_STORE",
            self.preview_store,
        )
        self.service_patch.start()
        self.preview_patch.start()

    def tearDown(self):
        self.preview_patch.stop()
        self.service_patch.stop()
        self.temp_dir.cleanup()

    def test_crud_list_query_summary_and_stable_item_fields(self):
        created = create_item(KnowledgeItemRequest(**term_payload()))
        item = created["data"]["item"]
        self.assertEqual(created["taskType"], "enterprise.knowledge")
        self.assertTrue(created["traceId"])
        self.assertEqual(
            set(item),
            {
                "id",
                "type",
                "scope",
                "category",
                "preferredText",
                "aliases",
                "forbiddenVariants",
                "definition",
                "contextKeywords",
                "priority",
                "enabled",
                "note",
                "createdAt",
                "updatedAt",
            },
        )

        listed = list_items(scope="global", item_type="term", query="网管")
        missing = list_items(scope="global", item_type="term", query="不存在")
        updated = update_item(
            item["id"], KnowledgeItemRequest(note="更新备注", enabled=False)
        )
        summary = get_summary()
        deleted = delete_item(item["id"])

        self.assertEqual(listed["data"]["items"][0]["id"], item["id"])
        self.assertEqual(listed["data"]["count"], 1)
        self.assertEqual(missing["data"]["items"], [])
        self.assertEqual(updated["data"]["item"]["note"], "更新备注")
        self.assertFalse(updated["data"]["item"]["enabled"])
        self.assertEqual(summary["data"]["totalCount"], 1)
        self.assertEqual(deleted["data"]["item"]["id"], item["id"])
        self.assertTrue(deleted["data"]["deleted"])

    def test_models_accept_alias_and_field_name_on_pydantic_v1_and_v2(self):
        aliased = ImportPreviewRequest(
            fileName="terms.csv",
            mimeType=CSV_MIME,
            sizeBytes=3,
            contentBase64="YWJj",
        )
        named = ImportPreviewRequest(
            file_name="terms.csv",
            mime_type=CSV_MIME,
            size_bytes=3,
            content_base64="YWJj",
        )
        item = KnowledgeItemRequest(preferred_text="标准名称")
        apply_request = ImportApplyRequest(
            preview_token="token",
            accepted_conflict_rows=[{"rowNumber": 2, "decision": "skip"}],
        )

        self.assertEqual(aliased.file_name, named.file_name)
        self.assertEqual(item.preferred_text, "标准名称")
        self.assertEqual(apply_request.preview_token, "token")

    def test_template_downloads_have_deterministic_binary_headers(self):
        csv_response = download_csv_template()
        xlsx_response = download_xlsx_template()

        self.assertEqual(csv_response.body, generate_csv_template())
        self.assertTrue(xlsx_response.body.startswith(b"PK"))
        self.assertTrue(csv_response.headers["content-type"].startswith("text/csv"))
        self.assertEqual(
            xlsx_response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(
            csv_response.headers["content-disposition"],
            'attachment; filename="enterprise-knowledge-import-template.csv"',
        )
        self.assertEqual(
            xlsx_response.headers["content-disposition"],
            'attachment; filename="enterprise-knowledge-import-template.xlsx"',
        )
        self.assertEqual(int(csv_response.headers["content-length"]), len(csv_response.body))
        self.assertEqual(int(xlsx_response.headers["content-length"]), len(xlsx_response.body))

    def test_preview_calls_parse_validate_build_in_order_then_apply_is_single_use(self):
        content = generate_csv_template()
        request = ImportPreviewRequest(
            fileName="terms.csv",
            mimeType=CSV_MIME,
            sizeBytes=len(content),
            contentBase64=base64.b64encode(content).decode("ascii"),
        )
        call_order = []

        from app.services.enterprise_knowledge.imports import (
            build_import_preview as real_build,
            parse_import_file as real_parse,
            validate_import_rows as real_validate,
        )

        def tracked_parse(*args, **kwargs):
            call_order.append("parse")
            return real_parse(*args, **kwargs)

        def tracked_validate(*args, **kwargs):
            call_order.append("validate")
            return real_validate(*args, **kwargs)

        def tracked_build(*args, **kwargs):
            call_order.append("build")
            return real_build(*args, **kwargs)

        with patch("app.api.enterprise_knowledge.parse_import_file", tracked_parse), patch(
            "app.api.enterprise_knowledge.validate_import_rows", tracked_validate
        ), patch("app.api.enterprise_knowledge.build_import_preview", tracked_build):
            preview = preview_import(request)

        token = preview["data"]["previewToken"]
        applied = apply_import(
            ImportApplyRequest(previewToken=token, acceptedConflictRows=[])
        )

        self.assertEqual(call_order, ["parse", "validate", "build"])
        self.assertEqual(preview["data"]["newCount"], 1)
        self.assertEqual(applied["data"]["createdCount"], 1)
        with self.assertRaises(AdapterError) as raised:
            apply_import(ImportApplyRequest(previewToken=token, acceptedConflictRows=[]))
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "IMPORT_PREVIEW_NOT_FOUND")

    def test_apply_accepts_conflict_decisions_without_overwriting_existing_item(self):
        existing = self.store.create_item(term_payload("已有标准", ["已有别名"]))
        content = import_csv_bytes(
            [
                [
                    "术语",
                    "全局",
                    "系统",
                    "新标准",
                    "别名:已有别名",
                    "",
                    "",
                    "平台",
                    "高",
                    "否",
                    "是",
                    "冲突测试",
                ]
            ]
        )
        preview = preview_import(
            ImportPreviewRequest(
                fileName="conflicts.csv",
                mimeType=CSV_MIME,
                sizeBytes=len(content),
                contentBase64=base64.b64encode(content).decode("ascii"),
            )
        )
        conflict = preview["data"]["conflicts"][0]
        applied = apply_import(
            ImportApplyRequest(
                previewToken=preview["data"]["previewToken"],
                acceptedConflictRows=[
                    {"rowNumber": conflict["rowNumber"], "decision": "skip"}
                ],
            )
        )

        self.assertEqual(preview["data"]["conflictCount"], 1)
        self.assertNotIn("overwrite", conflict["allowedDecisions"])
        self.assertEqual(applied["data"]["createdCount"], 0)
        self.assertEqual(self.store.get_item(existing["id"])["preferredText"], "已有标准")

    def test_export_backup_and_diagnostics(self):
        self.store.create_item(term_payload())
        self.store.create_item(style_payload())
        self.service.prepare("word.smart_write", ["卫星网管平台汇报"])

        exported = export_knowledge_csv(scope="global")
        scoped_export = export_knowledge_csv(scope="word.smart_write")
        backup = backup_knowledge()
        diagnostics = get_diagnostics()

        self.assertIn("卫星互联网运营管理平台".encode("utf-8"), exported.body)
        self.assertNotIn("结论先行".encode("utf-8"), exported.body)
        self.assertIn("结论先行".encode("utf-8"), scoped_export.body)
        self.assertNotIn(
            "卫星互联网运营管理平台".encode("utf-8"), scoped_export.body
        )
        self.assertEqual(
            exported.headers["content-disposition"],
            'attachment; filename="enterprise-knowledge-export.csv"',
        )
        self.assertEqual(backup.body[:16], b"SQLite format 3\x00")
        self.assertEqual(
            backup.headers["content-disposition"],
            'attachment; filename="enterprise-knowledge-backup.db"',
        )
        self.assertEqual(backup.headers["content-type"], "application/vnd.sqlite3")
        self.assertEqual(int(backup.headers["content-length"]), len(backup.body))
        self.assertTrue(diagnostics["data"]["knowledgeApplied"])
        self.assertNotIn("卫星网管平台汇报", str(diagnostics))
        snapshot_path = Path(self.temp_dir.name) / "downloaded-backup.db"
        snapshot_path.write_bytes(backup.body)
        with sqlite3.connect(str(snapshot_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM knowledge_terms").fetchone()[0],
                1,
            )

    def test_invalid_base64_size_mismatch_unsupported_and_oversized_map_to_http_errors(self):
        cases = (
            (
                ImportPreviewRequest(
                    fileName="terms.csv",
                    mimeType=CSV_MIME,
                    sizeBytes=3,
                    contentBase64="***not-base64***",
                ),
                400,
                "INVALID_IMPORT_BASE64",
            ),
            (
                ImportPreviewRequest(
                    fileName="terms.csv",
                    mimeType=CSV_MIME,
                    sizeBytes=4,
                    contentBase64="YWJj",
                ),
                400,
                "IMPORT_SIZE_MISMATCH",
            ),
            (
                ImportPreviewRequest(
                    fileName="terms.xls",
                    mimeType="application/vnd.ms-excel",
                    sizeBytes=1,
                    contentBase64="eA==",
                ),
                400,
                "UNSUPPORTED_IMPORT_TYPE",
            ),
            (
                ImportPreviewRequest(
                    fileName="terms.csv",
                    mimeType=CSV_MIME,
                    sizeBytes=MAX_IMPORT_BYTES + 1,
                    contentBase64=base64.b64encode(b"x" * (MAX_IMPORT_BYTES + 1)).decode(
                        "ascii"
                    ),
                ),
                413,
                "IMPORT_FILE_TOO_LARGE",
            ),
        )
        for request, status_code, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(AdapterError) as raised:
                    preview_import(request)
                self.assertEqual(raised.exception.status_code, status_code)
                self.assertEqual(raised.exception.code, code)

    def test_expired_preview_token_maps_to_404(self):
        now = [0.0]
        expiring_store = ImportPreviewStore(clock=lambda: now[0], ttl_seconds=600)
        content = generate_csv_template()
        with patch(
            "app.api.enterprise_knowledge.DEFAULT_IMPORT_PREVIEW_STORE", expiring_store
        ):
            preview = preview_import(
                ImportPreviewRequest(
                    fileName="terms.csv",
                    mimeType=CSV_MIME,
                    sizeBytes=len(content),
                    contentBase64=base64.b64encode(content).decode("ascii"),
                )
            )
            now[0] = 601.0
            with self.assertRaises(AdapterError) as raised:
                apply_import(
                    ImportApplyRequest(
                        previewToken=preview["data"]["previewToken"],
                        acceptedConflictRows=[],
                    )
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "IMPORT_PREVIEW_EXPIRED")

    def test_knowledge_and_storage_errors_map_without_leaking_sensitive_details(self):
        cases = (
            (KnowledgeError("knowledge_item_not_found", "missing"), 404),
            (KnowledgeError("term_text_conflict", "duplicate"), 409),
            (KnowledgeError("knowledge_data_corrupt", "/secret/db corrupt"), 503),
            (KnowledgeError("knowledge_store_unavailable", "/secret/db denied"), 503),
            (KnowledgeError("unexpected_rule_failure", "/secret/raw source"), 400),
            (OSError("/secret/db I/O failure"), 503),
        )
        for error, status_code in cases:
            failing_store = SimpleNamespace(summary=lambda error=error: (_ for _ in ()).throw(error))
            failing_service = SimpleNamespace(store=failing_store)
            with self.subTest(error=type(error).__name__, status=status_code), patch(
                "app.api.enterprise_knowledge.get_enterprise_knowledge_service",
                return_value=failing_service,
            ):
                with self.assertRaises(AdapterError) as raised:
                    get_summary()
                self.assertEqual(raised.exception.status_code, status_code)
                self.assertNotIn("/secret", raised.exception.message)
                self.assertNotIn("raw source", raised.exception.message)


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class EnterpriseKnowledgeHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "http-knowledge.db"
        self.service = EnterpriseKnowledgeService(EnterpriseKnowledgeStore(self.db_path))
        self.preview_store = ImportPreviewStore()
        self.service_patch = patch(
            "app.api.enterprise_knowledge.get_enterprise_knowledge_service",
            return_value=self.service,
        )
        self.preview_patch = patch(
            "app.api.enterprise_knowledge.DEFAULT_IMPORT_PREVIEW_STORE",
            self.preview_store,
        )
        self.service_patch.start()
        self.preview_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.preview_patch.stop()
        self.service_patch.stop()
        self.temp_dir.cleanup()

    def test_openapi_uses_camel_case_item_id_path_parameter(self):
        schema = app.openapi()
        item_path = schema["paths"]["/enterprise-knowledge/items/{itemId}"]

        self.assertNotIn(
            "/enterprise-knowledge/items/{item_id}", schema["paths"]
        )
        for method in ("patch", "delete"):
            path_parameters = [
                parameter
                for parameter in item_path[method]["parameters"]
                if parameter["in"] == "path"
            ]
            self.assertEqual(
                [parameter["name"] for parameter in path_parameters], ["itemId"]
            )

    def test_testclient_crud_query_binary_and_error_envelopes(self):
        created = self.client.post("/enterprise-knowledge/items", json=term_payload())
        self.assertEqual(created.status_code, 200)
        item_id = created.json()["data"]["item"]["id"]

        listed = self.client.get(
            "/enterprise-knowledge/items",
            params={"scope": "global", "type": "term", "query": "网管"},
        )
        updated = self.client.patch(
            "/enterprise-knowledge/items/%s" % item_id,
            json={"note": "HTTP 更新"},
        )
        exported = self.client.get(
            "/enterprise-knowledge/export.csv", params={"scope": "global"}
        )
        backup = self.client.get("/enterprise-knowledge/backup")
        deleted = self.client.delete("/enterprise-knowledge/items/%s" % item_id)
        missing = self.client.delete("/enterprise-knowledge/items/%s" % item_id)

        self.assertEqual(listed.json()["data"]["count"], 1)
        self.assertEqual(updated.json()["data"]["item"]["note"], "HTTP 更新")
        self.assertEqual(exported.headers["content-length"], str(len(exported.content)))
        self.assertEqual(backup.content[:16], b"SQLite format 3\x00")
        self.assertTrue(deleted.json()["data"]["deleted"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["errors"][0]["code"], "KNOWLEDGE_ITEM_NOT_FOUND")
        self.assertEqual(missing.json()["taskType"], "enterprise.knowledge")

    def test_testclient_preview_apply_templates_diagnostics_and_conflict(self):
        content = generate_csv_template()
        preview = self.client.post(
            "/enterprise-knowledge/imports/preview",
            json={
                "fileName": "terms.csv",
                "mimeType": CSV_MIME,
                "sizeBytes": len(content),
                "contentBase64": base64.b64encode(content).decode("ascii"),
            },
        )
        applied = self.client.post(
            "/enterprise-knowledge/imports/apply",
            json={
                "previewToken": preview.json()["data"]["previewToken"],
                "acceptedConflictRows": [],
            },
        )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(self.client.get("/enterprise-knowledge/summary").status_code, 200)
        self.assertEqual(self.client.get("/enterprise-knowledge/diagnostics").status_code, 200)
        for path, suffix in (
            ("/enterprise-knowledge/import-template.csv", ".csv"),
            ("/enterprise-knowledge/import-template.xlsx", ".xlsx"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("filename=\"enterprise-knowledge-import-template%s\"" % suffix, response.headers["content-disposition"])

    def test_testclient_maps_unique_conflict_and_storage_failure(self):
        first = self.client.post("/enterprise-knowledge/items", json=term_payload())
        duplicate = self.client.post(
            "/enterprise-knowledge/items",
            json=term_payload("另一标准", ["卫星网管平台"]),
        )
        failing_store = SimpleNamespace(
            summary=lambda: (_ for _ in ()).throw(
                KnowledgeError("knowledge_data_corrupt", "/field/secret.db")
            )
        )
        with patch(
            "app.api.enterprise_knowledge.get_enterprise_knowledge_service",
            return_value=SimpleNamespace(store=failing_store),
        ):
            unavailable = self.client.get("/enterprise-knowledge/summary")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["errors"][0]["code"], "TERM_TEXT_CONFLICT")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            unavailable.json()["errors"][0]["code"], "KNOWLEDGE_DATA_CORRUPT"
        )
        self.assertNotIn("/field", json.dumps(unavailable.json(), ensure_ascii=False))

    def test_validation_is_400_and_preview_body_limit_is_path_specific(self):
        invalid = self.client.post("/enterprise-knowledge/imports/preview", json={})
        oversized = self.client.post(
            "/enterprise-knowledge/imports/preview",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(7 * 1024 * 1024 + 1)},
        )
        other_path = self.client.post(
            "/enterprise-knowledge/items",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(7 * 1024 * 1024 + 1)},
        )
        ppt_limit = self.client.post(
            "/ppt/document-files",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(16 * 1024 * 1024)},
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["errors"][0]["code"], "REQUEST_VALIDATION_FAILED")
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["errors"][0]["code"], "IMPORT_REQUEST_TOO_LARGE")
        self.assertNotEqual(other_path.status_code, 413)
        self.assertEqual(ppt_limit.status_code, 413)
        self.assertEqual(ppt_limit.json()["errors"][0]["code"], "PPT_DOCUMENT_TOO_LARGE")

    def test_preview_body_limit_checks_actual_body_when_length_is_forged(self):
        response = self.client.post(
            "/enterprise-knowledge/imports/preview",
            content=b"x" * (7 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json", "Content-Length": "2"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            payload["errors"][0]["code"], "IMPORT_REQUEST_TOO_LARGE"
        )
        self.assertEqual(payload["taskType"], "enterprise.knowledge")
        self.assertEqual(payload["traceId"], response.headers["X-Trace-Id"])

    def test_asgi_body_limiter_preflights_overflow_before_downstream_response(self):
        first_chunk = b"a" * (4 * 1024 * 1024)
        crossing_chunk = b"b" * (3 * 1024 * 1024 + 1)
        incoming = [
            {"type": "http.request", "body": first_chunk, "more_body": True},
            {"type": "http.request", "body": crossing_chunk, "more_body": True},
            {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
        ]
        sent = []
        receive_calls = []
        downstream_calls = []

        async def receive():
            receive_calls.append(len(receive_calls))
            return incoming[len(receive_calls) - 1]

        async def send(message):
            sent.append(message)

        async def downstream(scope, limited_receive, downstream_send):
            del scope
            downstream_calls.append(True)
            await downstream_send(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            while True:
                message = await limited_receive()
                if not message.get("more_body", False):
                    break
            await downstream_send({"type": "http.response.body", "body": b"ok"})

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/enterprise-knowledge/imports/preview",
            "headers": [
                (b"content-length", b"2"),
                (b"x-trace-id", b"trace-chunked-limit"),
            ],
        }
        middleware = app_main.EnterpriseKnowledgeImportBodyLimitMiddleware(
            downstream,
            max_bytes=7 * 1024 * 1024,
        )

        asyncio.run(middleware(scope, receive, send))

        self.assertEqual(len(receive_calls), 2)
        self.assertEqual(downstream_calls, [])
        starts = [message for message in sent if message["type"] == "http.response.start"]
        self.assertEqual(len(starts), 1)
        start = starts[0]
        body = b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] == "http.response.body"
        )
        headers = dict(start["headers"])
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(start["status"], 413)
        self.assertEqual(headers[b"x-trace-id"], b"trace-chunked-limit")
        self.assertEqual(payload["traceId"], "trace-chunked-limit")
        self.assertEqual(payload["taskType"], "enterprise.knowledge")
        self.assertEqual(payload["errors"][0]["code"], "IMPORT_REQUEST_TOO_LARGE")

    def test_asgi_body_limiter_replays_early_disconnect_without_rejecting(self):
        incoming = [
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ]
        forwarded = []
        sent = []
        receive_index = [0]

        async def receive():
            index = receive_index[0]
            receive_index[0] += 1
            return incoming[index]

        async def send(message):
            sent.append(message)

        async def downstream(scope, replay_receive, downstream_send):
            del scope, downstream_send
            forwarded.append(await replay_receive())
            forwarded.append(await replay_receive())
            forwarded.append(await replay_receive())

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/enterprise-knowledge/imports/preview",
            "headers": [(b"content-length", str(8 * 1024 * 1024).encode("ascii"))],
        }
        middleware = app_main.EnterpriseKnowledgeImportBodyLimitMiddleware(
            downstream,
            max_bytes=7 * 1024 * 1024,
        )

        asyncio.run(middleware(scope, receive, send))

        self.assertEqual(receive_index[0], 2)
        self.assertEqual(forwarded, incoming + [{"type": "http.disconnect"}])
        self.assertEqual(sent, [])

    def test_asgi_body_limiter_forwards_legal_chunks_with_missing_or_invalid_length(self):
        for content_length_headers in ([], [(b"content-length", b"invalid")]):
            with self.subTest(headers=content_length_headers):
                incoming = [
                    {"type": "http.request", "body": b'{"ok":', "more_body": True},
                    {"type": "http.request", "body": b"true}", "more_body": False},
                ]
                forwarded = []
                sent = []
                receive_index = [0]

                async def receive():
                    index = receive_index[0]
                    receive_index[0] += 1
                    return incoming[index]

                async def send(message):
                    sent.append(message)

                async def downstream(scope, limited_receive, downstream_send):
                    del scope
                    while True:
                        message = await limited_receive()
                        forwarded.append(message)
                        if not message.get("more_body", False):
                            break
                    await downstream_send(
                        {"type": "http.response.start", "status": 204, "headers": []}
                    )
                    await downstream_send({"type": "http.response.body", "body": b""})

                scope = {
                    "type": "http",
                    "method": "POST",
                    "path": "/enterprise-knowledge/imports/preview",
                    "headers": content_length_headers,
                }
                middleware = app_main.EnterpriseKnowledgeImportBodyLimitMiddleware(
                    downstream,
                    max_bytes=7 * 1024 * 1024,
                )

                asyncio.run(middleware(scope, receive, send))

                self.assertEqual(
                    forwarded,
                    [
                        {
                            "type": "http.request",
                            "body": b'{"ok":true}',
                            "more_body": False,
                        }
                    ],
                )
                self.assertEqual(receive_index[0], 2)
                self.assertEqual(sent[0]["status"], 204)

    def test_asgi_body_limiter_aggregates_many_empty_chunks_without_retaining_messages(self):
        class TrackableMessage(dict):
            __slots__ = ("__weakref__",)

        empty_chunk_count = 5000
        receive_calls = [0]
        original_message_refs = []
        replayed = []
        retained_counts = []

        async def receive():
            index = receive_calls[0]
            receive_calls[0] += 1
            if index < empty_chunk_count:
                message = TrackableMessage(
                    type="http.request",
                    body=b"",
                    more_body=True,
                )
            else:
                message = TrackableMessage(
                    type="http.request",
                    body=b"legal-body",
                    more_body=False,
                )
            original_message_refs.append(weakref.ref(message))
            return message

        async def send(message):
            del message

        async def downstream(scope, replay_receive, downstream_send):
            del scope, downstream_send
            replayed.append(await replay_receive())
            gc.collect()
            retained_counts.append(
                sum(ref() is not None for ref in original_message_refs)
            )

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/enterprise-knowledge/imports/preview",
            "headers": [],
        }
        middleware = app_main.EnterpriseKnowledgeImportBodyLimitMiddleware(
            downstream,
            max_bytes=7 * 1024 * 1024,
        )

        asyncio.run(middleware(scope, receive, send))

        self.assertEqual(receive_calls[0], empty_chunk_count + 1)
        self.assertEqual(
            replayed,
            [{"type": "http.request", "body": b"legal-body", "more_body": False}],
        )
        self.assertEqual(retained_counts, [0])

    def test_invalid_content_length_does_not_create_a_new_411_regression(self):
        content = generate_csv_template()
        response = self.client.post(
            "/enterprise-knowledge/imports/preview",
            json={
                "fileName": "terms.csv",
                "mimeType": CSV_MIME,
                "sizeBytes": len(content),
                "contentBase64": base64.b64encode(content).decode("ascii"),
            },
            headers={"Content-Length": "invalid"},
        )
        self.assertEqual(response.status_code, 200)

    def test_preview_body_limit_413_includes_cors_headers(self):
        response = self.client.post(
            "/enterprise-knowledge/imports/preview",
            content=b"x" * (7 * 1024 * 1024 + 1),
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
                "Origin": "https://wps.example.test",
            },
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")

    def test_importing_app_does_not_initialize_default_or_field_database(self):
        field_db = Path(self.temp_dir.name) / "field" / "enterprise-knowledge.db"
        environment = os.environ.copy()
        environment["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = str(field_db)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import app.main; print('exists=' + str(__import__('pathlib').Path(%r).exists()))"
                % str(field_db),
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exists=False", result.stdout)
        self.assertFalse(field_db.exists())


if __name__ == "__main__":
    unittest.main()
