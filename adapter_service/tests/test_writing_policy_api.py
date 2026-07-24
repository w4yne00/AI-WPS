import base64
import csv
import asyncio
import gc
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from app.services.writing_policy.imports import (
    CSV_MIME,
    IMPORT_COLUMNS,
    ImportPreviewStore,
    generate_csv_template,
)
from app.services.writing_policy.models import WritingPolicyError, MAX_IMPORT_BYTES
from app.services.writing_policy.service import WritingPolicyService
from app.services.writing_policy.store import WritingPolicyStore


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.api.writing_policies import (
        ImportApplyRequest,
        ImportPreviewRequest,
        WritingPolicyItemRequest,
        apply_import,
        backup_writing_policy,
        create_item,
        delete_item,
        download_csv_template,
        download_xlsx_template,
        export_writing_policy_csv,
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
class WritingPolicyDirectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "writing-policies.db"
        self.store = WritingPolicyStore(self.db_path)
        self.service = WritingPolicyService(self.store)
        self.preview_store = ImportPreviewStore()
        self.service_patch = patch(
            "app.api.writing_policies.get_writing_policy_service",
            return_value=self.service,
        )
        self.preview_patch = patch(
            "app.api.writing_policies.DEFAULT_IMPORT_PREVIEW_STORE",
            self.preview_store,
        )
        self.service_patch.start()
        self.preview_patch.start()

    def tearDown(self):
        self.preview_patch.stop()
        self.service_patch.stop()
        self.temp_dir.cleanup()

    def test_crud_list_query_summary_and_stable_item_fields(self):
        created = create_item(WritingPolicyItemRequest(**term_payload()))
        item = created["data"]["item"]
        self.assertEqual(created["taskType"], "writing_policy")
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
            item["id"], WritingPolicyItemRequest(note="更新备注", enabled=False)
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
        item = WritingPolicyItemRequest(preferred_text="标准名称")
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
            'attachment; filename="writing-policies-import-template.csv"',
        )
        self.assertEqual(
            xlsx_response.headers["content-disposition"],
            'attachment; filename="writing-policies-import-template.xlsx"',
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

        from app.services.writing_policy.imports import (
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

        with patch("app.api.writing_policies.parse_import_file", tracked_parse), patch(
            "app.api.writing_policies.validate_import_rows", tracked_validate
        ), patch("app.api.writing_policies.build_import_preview", tracked_build):
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

        exported = export_writing_policy_csv(scope="global")
        scoped_export = export_writing_policy_csv(scope="word.smart_write")
        backup = backup_writing_policy()
        diagnostics = get_diagnostics()

        self.assertIn("卫星互联网运营管理平台".encode("utf-8"), exported.body)
        self.assertNotIn("结论先行".encode("utf-8"), exported.body)
        self.assertIn("结论先行".encode("utf-8"), scoped_export.body)
        self.assertNotIn(
            "卫星互联网运营管理平台".encode("utf-8"), scoped_export.body
        )
        self.assertEqual(
            exported.headers["content-disposition"],
            'attachment; filename="writing-policies-export.csv"',
        )
        self.assertEqual(backup.body[:16], b"SQLite format 3\x00")
        self.assertEqual(
            backup.headers["content-disposition"],
            'attachment; filename="writing-policies-backup.db"',
        )
        self.assertEqual(backup.headers["content-type"], "application/vnd.sqlite3")
        self.assertEqual(int(backup.headers["content-length"]), len(backup.body))
        self.assertTrue(diagnostics["data"]["writingPolicyApplied"])
        self.assertNotIn("卫星网管平台汇报", str(diagnostics))
        snapshot_path = Path(self.temp_dir.name) / "downloaded-backup.db"
        snapshot_path.write_bytes(backup.body)
        with sqlite3.connect(str(snapshot_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM writing_policy_terms").fetchone()[0],
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
            "app.api.writing_policies.DEFAULT_IMPORT_PREVIEW_STORE", expiring_store
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

    def test_writing_policy_and_storage_errors_map_without_leaking_sensitive_details(self):
        cases = (
            (WritingPolicyError("writing_policy_item_not_found", "missing"), 404),
            (WritingPolicyError("term_text_conflict", "duplicate"), 409),
            (WritingPolicyError("writing_policy_data_corrupt", "/secret/db corrupt"), 503),
            (WritingPolicyError("writing_policy_store_unavailable", "/secret/db denied"), 503),
            (WritingPolicyError("unexpected_rule_failure", "/secret/raw source"), 400),
            (OSError("/secret/db I/O failure"), 503),
        )
        for error, status_code in cases:
            failing_store = SimpleNamespace(summary=lambda error=error: (_ for _ in ()).throw(error))
            failing_service = SimpleNamespace(store=failing_store)
            with self.subTest(error=type(error).__name__, status=status_code), patch(
                "app.api.writing_policies.get_writing_policy_service",
                return_value=failing_service,
            ):
                with self.assertRaises(AdapterError) as raised:
                    get_summary()
                self.assertEqual(raised.exception.status_code, status_code)
                self.assertNotIn("/secret", raised.exception.message)
                self.assertNotIn("raw source", raised.exception.message)


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class WritingPolicyHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "http-writing_policies.db"
        self.service = WritingPolicyService(WritingPolicyStore(self.db_path))
        self.preview_store = ImportPreviewStore()
        self.service_patch = patch(
            "app.api.writing_policies.get_writing_policy_service",
            return_value=self.service,
        )
        self.preview_patch = patch(
            "app.api.writing_policies.DEFAULT_IMPORT_PREVIEW_STORE",
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
        item_path = schema["paths"]["/writing-policies/items/{itemId}"]

        self.assertNotIn(
            "/writing-policies/items/{item_id}", schema["paths"]
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

    def test_read_only_preset_routes_expose_source_version_and_approved_items(self):
        packs = self.client.get("/writing-policies/packs")
        items = self.client.get(
            "/writing-policies/items",
            params={
                "layer": "preset",
                "packId": "yangqi-tech-writing-base",
            },
        )

        self.assertEqual(packs.status_code, 200)
        pack_data = packs.json()["data"]
        self.assertEqual(pack_data["count"], 4)
        base_pack = next(
            pack
            for pack in pack_data["packs"]
            if pack["packId"] == "yangqi-tech-writing-base"
        )
        self.assertEqual(
            base_pack["source"]["version"],
            "v1.1.0",
        )
        self.assertEqual(items.status_code, 200)
        self.assertEqual(items.json()["data"]["count"], 17)
        self.assertEqual(items.json()["data"]["items"][0]["layer"], "preset")

        missing = self.client.get(
            "/writing-policies/items",
            params={"layer": "preset", "packId": "missing-pack"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            missing.json()["errors"][0]["code"],
            "WRITING_POLICY_PACK_NOT_FOUND",
        )
        self.assertEqual(
            missing.json()["errors"][0]["message"],
            "未找到指定预置规范包。",
        )

    def test_testclient_crud_query_binary_and_error_envelopes(self):
        created = self.client.post("/writing-policies/items", json=term_payload())
        self.assertEqual(created.status_code, 200)
        item_id = created.json()["data"]["item"]["id"]

        listed = self.client.get(
            "/writing-policies/items",
            params={"scope": "global", "type": "term", "query": "网管"},
        )
        updated = self.client.patch(
            "/writing-policies/items/%s" % item_id,
            json={"note": "HTTP 更新"},
        )
        exported = self.client.get(
            "/writing-policies/export.csv", params={"scope": "global"}
        )
        backup = self.client.get("/writing-policies/backup")
        deleted = self.client.delete("/writing-policies/items/%s" % item_id)
        missing = self.client.delete("/writing-policies/items/%s" % item_id)

        self.assertEqual(listed.json()["data"]["count"], 1)
        self.assertEqual(updated.json()["data"]["item"]["note"], "HTTP 更新")
        self.assertEqual(exported.headers["content-length"], str(len(exported.content)))
        self.assertEqual(backup.content[:16], b"SQLite format 3\x00")
        self.assertTrue(deleted.json()["data"]["deleted"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["errors"][0]["code"], "WRITING_POLICY_ITEM_NOT_FOUND")
        self.assertEqual(missing.json()["taskType"], "writing_policy")

    def test_testclient_preview_apply_templates_diagnostics_and_conflict(self):
        content = generate_csv_template()
        preview = self.client.post(
            "/writing-policies/imports/preview",
            json={
                "fileName": "terms.csv",
                "mimeType": CSV_MIME,
                "sizeBytes": len(content),
                "contentBase64": base64.b64encode(content).decode("ascii"),
            },
        )
        applied = self.client.post(
            "/writing-policies/imports/apply",
            json={
                "previewToken": preview.json()["data"]["previewToken"],
                "acceptedConflictRows": [],
            },
        )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(self.client.get("/writing-policies/summary").status_code, 200)
        self.assertEqual(self.client.get("/writing-policies/diagnostics").status_code, 200)
        for path, suffix in (
            ("/writing-policies/import-template.csv", ".csv"),
            ("/writing-policies/import-template.xlsx", ".xlsx"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("filename=\"writing-policies-import-template%s\"" % suffix, response.headers["content-disposition"])

    def test_testclient_maps_unique_conflict_and_storage_failure(self):
        first = self.client.post("/writing-policies/items", json=term_payload())
        duplicate = self.client.post(
            "/writing-policies/items",
            json=term_payload("另一标准", ["卫星网管平台"]),
        )
        failing_store = SimpleNamespace(
            summary=lambda: (_ for _ in ()).throw(
                WritingPolicyError("writing_policy_data_corrupt", "/field/secret.db")
            )
        )
        with patch(
            "app.api.writing_policies.get_writing_policy_service",
            return_value=SimpleNamespace(store=failing_store),
        ):
            unavailable = self.client.get("/writing-policies/summary")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["errors"][0]["code"], "TERM_TEXT_CONFLICT")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            unavailable.json()["errors"][0]["code"], "WRITING_POLICY_DATA_CORRUPT"
        )
        self.assertNotIn("/field", json.dumps(unavailable.json(), ensure_ascii=False))

    def test_validation_is_400_and_preview_body_limit_is_path_specific(self):
        invalid = self.client.post("/writing-policies/imports/preview", json={})
        oversized = self.client.post(
            "/writing-policies/imports/preview",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(7 * 1024 * 1024 + 1)},
        )
        other_path = self.client.post(
            "/writing-policies/items",
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
            "/writing-policies/imports/preview",
            content=b"x" * (7 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json", "Content-Length": "2"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            payload["errors"][0]["code"], "IMPORT_REQUEST_TOO_LARGE"
        )
        self.assertEqual(payload["taskType"], "writing_policy")
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
            "path": "/writing-policies/imports/preview",
            "headers": [
                (b"content-length", b"2"),
                (b"x-trace-id", b"trace-chunked-limit"),
            ],
        }
        middleware = app_main.WritingPolicyImportBodyLimitMiddleware(
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
        self.assertEqual(payload["taskType"], "writing_policy")
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
            "path": "/writing-policies/imports/preview",
            "headers": [(b"content-length", str(8 * 1024 * 1024).encode("ascii"))],
        }
        middleware = app_main.WritingPolicyImportBodyLimitMiddleware(
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
                    "path": "/writing-policies/imports/preview",
                    "headers": content_length_headers,
                }
                middleware = app_main.WritingPolicyImportBodyLimitMiddleware(
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
            "path": "/writing-policies/imports/preview",
            "headers": [],
        }
        middleware = app_main.WritingPolicyImportBodyLimitMiddleware(
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
            "/writing-policies/imports/preview",
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
            "/writing-policies/imports/preview",
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
        field_db = Path(self.temp_dir.name) / "field" / "writing-policies.db"
        environment = os.environ.copy()
        environment["AI_WPS_WRITING_POLICY_DB"] = str(field_db)
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


class WritingPolicyStandaloneTests(unittest.TestCase):
    def setUp(self):
        import standalone_adapter

        self.standalone = standalone_adapter
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "standalone-writing_policies.db"
        self.service = WritingPolicyService(WritingPolicyStore(self.db_path))
        self.preview_store = ImportPreviewStore()
        self.service_patch = patch.object(
            self.standalone,
            "get_writing_policy_service",
            return_value=self.service,
            create=True,
        )
        self.preview_patch = patch.object(
            self.standalone,
            "DEFAULT_IMPORT_PREVIEW_STORE",
            self.preview_store,
            create=True,
        )
        self.service_patch.start()
        self.preview_patch.start()

    def tearDown(self):
        self.preview_patch.stop()
        self.service_patch.stop()
        self.temp_dir.cleanup()

    def dispatch(self, method, path, payload=None, query="", body_size=None):
        return self.standalone.dispatch_writing_policy(
            method,
            path,
            query=query,
            payload=payload,
            body_size=body_size,
        )

    def raw_http_request(
        self,
        host,
        port,
        request_bytes,
        shutdown_write=True,
        timeout=3,
    ):
        connection = socket.create_connection((host, port), timeout=timeout)
        connection.settimeout(timeout)
        try:
            connection.sendall(request_bytes)
            if shutdown_write:
                connection.shutdown(socket.SHUT_WR)
            return self.read_raw_http_response(connection)
        finally:
            connection.close()

    @staticmethod
    def read_raw_http_response(connection):
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw_response = b"".join(chunks)
        header_bytes, body = raw_response.split(b"\r\n\r\n", 1)
        header_lines = header_bytes.decode("latin-1").split("\r\n")
        status = int(header_lines[0].split(" ", 2)[1])
        headers = {}
        for line in header_lines[1:]:
            name, value = line.split(":", 1)
            headers[name.lower()] = value.strip()
        return status, headers, json.loads(body.decode("utf-8"))

    def test_standalone_crud_summary_list_and_error_status_parity(self):
        created = self.dispatch("POST", "/writing-policies/items", term_payload())
        item_id = created["body"]["data"]["item"]["id"]
        listed = self.dispatch(
            "GET",
            "/writing-policies/items",
            query="scope=global&type=term&query=%E7%BD%91%E7%AE%A1",
        )
        updated = self.dispatch(
            "PATCH",
            "/writing-policies/items/%s" % item_id,
            {"note": "独立适配器更新"},
        )
        summary = self.dispatch("GET", "/writing-policies/summary")
        duplicate = self.dispatch(
            "POST",
            "/writing-policies/items",
            term_payload("另一标准", ["卫星网管平台"]),
        )
        deleted = self.dispatch("DELETE", "/writing-policies/items/%s" % item_id)
        missing = self.dispatch("DELETE", "/writing-policies/items/%s" % item_id)

        self.assertEqual(created["status"], 200)
        self.assertEqual(created["body"]["taskType"], "writing_policy")
        self.assertTrue(created["body"]["traceId"])
        self.assertEqual(
            created["headers"]["X-Trace-Id"], created["body"]["traceId"]
        )
        self.assertEqual(listed["body"]["data"]["count"], 1)
        self.assertEqual(updated["body"]["data"]["item"]["note"], "独立适配器更新")
        self.assertEqual(summary["body"]["data"]["totalCount"], 1)
        self.assertEqual(duplicate["status"], 409)
        self.assertEqual(duplicate["body"]["errors"][0]["code"], "TERM_TEXT_CONFLICT")
        self.assertTrue(deleted["body"]["data"]["deleted"])
        self.assertEqual(missing["status"], 404)

    def test_standalone_read_only_preset_routes_match_fastapi_contract(self):
        packs = self.dispatch("GET", "/writing-policies/packs")
        items = self.dispatch(
            "GET",
            "/writing-policies/items",
            query="layer=preset&packId=yangqi-tech-writing-base",
        )

        self.assertEqual(packs["status"], 200)
        pack_data = packs["body"]["data"]
        self.assertEqual(pack_data["count"], 4)
        base_pack = next(
            pack
            for pack in pack_data["packs"]
            if pack["packId"] == "yangqi-tech-writing-base"
        )
        self.assertEqual(
            base_pack["source"]["license"],
            "MIT",
        )
        self.assertEqual(items["status"], 200)
        self.assertEqual(items["body"]["data"]["count"], 17)
        self.assertEqual(items["body"]["data"]["items"][0]["packVersion"], "1.0.0")
        missing = self.dispatch(
            "GET",
            "/writing-policies/items",
            query="layer=preset&packId=missing-pack",
        )
        self.assertEqual(missing["status"], 404)
        self.assertEqual(
            missing["body"]["errors"][0]["code"],
            "WRITING_POLICY_PACK_NOT_FOUND",
        )
        self.assertEqual(
            missing["body"]["errors"][0]["message"],
            "未找到指定预置规范包。",
        )

    def test_standalone_preview_apply_is_single_use_and_validates_upload(self):
        content = generate_csv_template()
        preview_payload = {
            "fileName": "terms.csv",
            "mimeType": CSV_MIME,
            "sizeBytes": len(content),
            "contentBase64": base64.b64encode(content).decode("ascii"),
        }
        preview = self.dispatch(
            "POST",
            "/writing-policies/imports/preview",
            preview_payload,
            body_size=len(json.dumps(preview_payload).encode("utf-8")),
        )
        token = preview["body"]["data"]["previewToken"]
        applied = self.dispatch(
            "POST",
            "/writing-policies/imports/apply",
            {"previewToken": token, "acceptedConflictRows": []},
        )
        reused = self.dispatch(
            "POST",
            "/writing-policies/imports/apply",
            {"previewToken": token, "acceptedConflictRows": []},
        )
        invalid_base64 = self.dispatch(
            "POST",
            "/writing-policies/imports/preview",
            dict(preview_payload, contentBase64="not base64"),
        )
        size_mismatch = self.dispatch(
            "POST",
            "/writing-policies/imports/preview",
            dict(preview_payload, sizeBytes=len(content) + 1),
        )
        oversized_body = self.dispatch(
            "POST",
            "/writing-policies/imports/preview",
            preview_payload,
            body_size=7 * 1024 * 1024 + 1,
        )

        self.assertEqual(preview["status"], 200)
        self.assertEqual(applied["status"], 200)
        self.assertEqual(reused["status"], 404)
        self.assertEqual(invalid_base64["status"], 400)
        self.assertEqual(size_mismatch["status"], 400)
        self.assertEqual(oversized_body["status"], 413)
        self.assertEqual(
            oversized_body["body"]["errors"][0]["code"],
            "IMPORT_REQUEST_TOO_LARGE",
        )

    def test_standalone_templates_export_backup_and_diagnostics_are_binary_safe(self):
        self.dispatch("POST", "/writing-policies/items", term_payload())
        csv_template = self.dispatch(
            "GET", "/writing-policies/import-template.csv"
        )
        xlsx_template = self.dispatch(
            "GET", "/writing-policies/import-template.xlsx"
        )
        exported = self.dispatch(
            "GET", "/writing-policies/export.csv", query="scope=global"
        )
        backup = self.dispatch("GET", "/writing-policies/backup")
        diagnostics = self.dispatch("GET", "/writing-policies/diagnostics")

        for response in (csv_template, xlsx_template, exported, backup):
            self.assertEqual(response["status"], 200)
            self.assertTrue(response["headers"]["X-Trace-Id"])
            self.assertEqual(response["headers"]["Content-Length"], str(len(response["content"])))
            self.assertRegex(
                response["headers"]["Content-Disposition"],
                r'^attachment; filename="[\x20-\x7e]+"$',
            )
        self.assertTrue(xlsx_template["content"].startswith(b"PK"))
        self.assertTrue(backup["content"].startswith(b"SQLite format 3\x00"))
        self.assertEqual(diagnostics["status"], 200)
        self.assertEqual(diagnostics["body"]["taskType"], "writing_policy")

    def test_standalone_dispatch_ignores_unrelated_routes_and_hides_storage_paths(self):
        self.assertIsNone(self.dispatch("GET", "/health"))
        self.assertIsNone(self.dispatch("GET", "/writing-policies-legacy"))
        failing_store = SimpleNamespace(
            summary=lambda: (_ for _ in ()).throw(
                WritingPolicyError("writing_policy_data_corrupt", "/secret/field.db")
            )
        )
        with patch.object(
            self.standalone,
            "get_writing_policy_service",
            return_value=SimpleNamespace(store=failing_store),
        ):
            response = self.dispatch("GET", "/writing-policies/summary")

        self.assertEqual(response["status"], 503)
        self.assertEqual(
            response["headers"]["X-Trace-Id"], response["body"]["traceId"]
        )
        self.assertNotIn("/secret", json.dumps(response["body"], ensure_ascii=False))

    def test_standalone_known_wrong_method_is_405_and_unknown_path_is_404(self):
        wrong_method = self.dispatch(
            "GET", "/writing-policies/imports/apply"
        )
        unknown = self.dispatch("GET", "/writing-policies/unknown")

        self.assertEqual(wrong_method["status"], 405)
        self.assertEqual(wrong_method["headers"]["Allow"], "POST")
        self.assertEqual(
            wrong_method["headers"]["X-Trace-Id"],
            wrong_method["body"]["traceId"],
        )
        self.assertEqual(unknown["status"], 404)
        self.assertEqual(unknown["body"]["errors"][0]["code"], "NOT_FOUND")
        self.assertEqual(
            unknown["headers"]["X-Trace-Id"], unknown["body"]["traceId"]
        )

    def test_standalone_chunked_preview_stops_reading_when_actual_body_crosses_limit(self):
        first = b"a" * (4 * 1024 * 1024)
        crossing = b"b" * (3 * 1024 * 1024 + 1)
        unread = b"must-not-be-buffered"
        encoded = (
            ("%x\r\n" % len(first)).encode("ascii")
            + first
            + b"\r\n"
            + ("%x\r\n" % len(crossing)).encode("ascii")
            + crossing
            + b"\r\n"
            + ("%x\r\n" % len(unread)).encode("ascii")
            + unread
            + b"\r\n0\r\n\r\n"
        )
        stream = io.BytesIO(encoded)
        handler = object.__new__(self.standalone.Handler)
        handler.headers = {"Transfer-Encoding": "chunked"}
        handler.rfile = stream

        body, rejection = handler._read_writing_policy_preview_body()

        self.assertIsNone(body)
        self.assertEqual(rejection["status"], 413)
        self.assertEqual(
            rejection["body"]["errors"][0]["code"],
            "IMPORT_REQUEST_TOO_LARGE",
        )
        self.assertLess(stream.tell(), len(encoded) - len(unread))

    def test_standalone_http_handler_wires_json_binary_and_preview_limit(self):
        try:
            server = self.standalone.ThreadingHTTPServer(
                ("127.0.0.1", 0), self.standalone.Handler
            )
        except PermissionError:
            self.skipTest("local sockets are unavailable in this sandbox")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request("GET", "/writing-policies/import-template.csv")
            template = connection.getresponse()
            template_body = template.read()
            self.assertEqual(template.status, 200)
            self.assertTrue(template.getheader("X-Trace-Id"))
            self.assertEqual(template.getheader("Content-Length"), str(len(template_body)))
            self.assertEqual(
                template.getheader("Content-Disposition"),
                'attachment; filename="writing-policies-import-template.csv"',
            )
            connection.close()

            item_body = json.dumps(term_payload(), ensure_ascii=False).encode("utf-8")
            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "POST",
                "/writing-policies/items",
                body=item_body,
                headers={"Content-Type": "application/json"},
            )
            created = connection.getresponse()
            created_payload = json.loads(created.read().decode("utf-8"))
            self.assertEqual(created.status, 200)
            self.assertEqual(created_payload["taskType"], "writing_policy")
            self.assertEqual(
                created.getheader("X-Trace-Id"), created_payload["traceId"]
            )
            connection.close()

            item_id = created_payload["data"]["item"]["id"]
            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "PATCH",
                "/writing-policies/items/%s" % item_id,
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            malformed_patch = connection.getresponse()
            malformed_patch_payload = json.loads(
                malformed_patch.read().decode("utf-8")
            )
            self.assertEqual(malformed_patch.status, 400)
            self.assertEqual(
                malformed_patch_payload["taskType"], "writing_policy"
            )
            self.assertEqual(
                malformed_patch.getheader("X-Trace-Id"),
                malformed_patch_payload["traceId"],
            )
            connection.close()

            update_body = json.dumps(
                {"note": "真实 HTTP 更新", "enabled": False},
                ensure_ascii=False,
            ).encode("utf-8")
            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "PATCH",
                "/writing-policies/items/%s" % item_id,
                body=update_body,
                headers={"Content-Type": "application/json"},
            )
            updated = connection.getresponse()
            updated_payload = json.loads(updated.read().decode("utf-8"))
            self.assertEqual(updated.status, 200)
            self.assertEqual(
                updated.getheader("X-Trace-Id"), updated_payload["traceId"]
            )
            self.assertEqual(updated_payload["data"]["item"]["note"], "真实 HTTP 更新")
            self.assertFalse(updated_payload["data"]["item"]["enabled"])
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "GET",
                "/writing-policies/items?scope=global&type=term",
            )
            listed = connection.getresponse()
            listed_payload = json.loads(listed.read().decode("utf-8"))
            self.assertEqual(listed.status, 200)
            self.assertEqual(listed_payload["data"]["items"][0]["id"], item_id)
            self.assertEqual(
                listed_payload["data"]["items"][0]["note"], "真实 HTTP 更新"
            )
            self.assertFalse(listed_payload["data"]["items"][0]["enabled"])
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "POST",
                "/writing-policies/items",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            malformed = connection.getresponse()
            malformed_payload = json.loads(malformed.read().decode("utf-8"))
            self.assertEqual(malformed.status, 400)
            self.assertEqual(
                malformed_payload["taskType"], "writing_policy"
            )
            self.assertEqual(
                malformed_payload["errors"][0]["code"],
                "REQUEST_VALIDATION_FAILED",
            )
            self.assertEqual(
                malformed.getheader("X-Trace-Id"),
                malformed_payload["traceId"],
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "POST",
                "/writing-policies/summary",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            post_summary = connection.getresponse()
            post_summary_payload = json.loads(
                post_summary.read().decode("utf-8")
            )
            self.assertEqual(post_summary.status, 405)
            self.assertEqual(post_summary.getheader("Allow"), "GET")
            self.assertEqual(
                post_summary_payload["taskType"], "writing_policy"
            )
            self.assertEqual(
                post_summary.getheader("X-Trace-Id"),
                post_summary_payload["traceId"],
            )
            self.assertEqual(
                post_summary.getheader("Access-Control-Allow-Origin"), "*"
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "POST",
                "/writing-policies/items/%s" % item_id,
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            post_item = connection.getresponse()
            post_item_payload = json.loads(post_item.read().decode("utf-8"))
            self.assertEqual(post_item.status, 405)
            self.assertEqual(post_item.getheader("Allow"), "PATCH, DELETE")
            self.assertEqual(post_item_payload["taskType"], "writing_policy")
            self.assertEqual(
                post_item.getheader("X-Trace-Id"), post_item_payload["traceId"]
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "PUT",
                "/writing-policies/summary",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            put_summary = connection.getresponse()
            put_summary_payload = json.loads(
                put_summary.read().decode("utf-8")
            )
            self.assertEqual(put_summary.status, 405)
            self.assertEqual(put_summary.getheader("Allow"), "GET")
            self.assertEqual(
                put_summary_payload["taskType"], "writing_policy"
            )
            self.assertEqual(
                put_summary.getheader("X-Trace-Id"),
                put_summary_payload["traceId"],
            )
            self.assertEqual(
                put_summary.getheader("Access-Control-Allow-Origin"), "*"
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request("PUT", "/health", body=b"{}")
            non_writing_policy_put = connection.getresponse()
            non_writing_policy_put.read()
            self.assertEqual(non_writing_policy_put.status, 501)
            self.assertIsNone(non_writing_policy_put.getheader("X-Trace-Id"))
            self.assertIsNone(
                non_writing_policy_put.getheader("Access-Control-Allow-Origin")
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request("GET", "/writing-policies/imports/apply")
            wrong_method = connection.getresponse()
            wrong_method_payload = json.loads(
                wrong_method.read().decode("utf-8")
            )
            self.assertEqual(wrong_method.status, 405)
            self.assertEqual(wrong_method.getheader("Allow"), "POST")
            self.assertEqual(
                wrong_method.getheader("X-Trace-Id"),
                wrong_method_payload["traceId"],
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request("GET", "/writing-policies/unknown")
            unknown = connection.getresponse()
            unknown_payload = json.loads(unknown.read().decode("utf-8"))
            self.assertEqual(unknown.status, 404)
            self.assertEqual(unknown_payload["errors"][0]["code"], "NOT_FOUND")
            self.assertEqual(
                unknown.getheader("X-Trace-Id"), unknown_payload["traceId"]
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(
                "POST",
                "/writing-policies/imports/preview",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(7 * 1024 * 1024 + 1),
                },
            )
            oversized = connection.getresponse()
            oversized_payload = json.loads(oversized.read().decode("utf-8"))
            self.assertEqual(oversized.status, 413)
            self.assertEqual(
                oversized_payload["errors"][0]["code"],
                "IMPORT_REQUEST_TOO_LARGE",
            )
            connection.close()

            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request("GET", "/health")
            health = connection.getresponse()
            health_payload = json.loads(health.read().decode("utf-8"))
            self.assertEqual(health.status, 200)
            self.assertEqual(health_payload["taskType"], "adapter.health")
            self.assertIsNone(health.getheader("X-Trace-Id"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_standalone_raw_http_rejects_ambiguous_and_unbounded_bodies(self):
        try:
            server = self.standalone.ThreadingHTTPServer(
                ("127.0.0.1", 0), self.standalone.Handler
            )
        except PermissionError:
            self.skipTest("local sockets are unavailable in this sandbox")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        preview_path = "/writing-policies/imports/preview"
        items_path = "/writing-policies/items"

        def request(method, path, headers=b"", body=b"", **kwargs):
            raw = (
                ("%s %s HTTP/1.1\r\n" % (method, path)).encode("ascii")
                + b"Host: 127.0.0.1\r\n"
                + headers
                + b"\r\n"
                + body
            )
            return self.raw_http_request(host, port, raw, **kwargs)

        try:
            framing_cases = (
                (
                    b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n",
                    b"2\r\n{}\r\n0\r\n\r\n",
                ),
                (
                    b"Transfer-Encoding: notchunked\r\n",
                    b"0\r\n\r\n",
                ),
                (
                    b"Transfer-Encoding: gzip, chunked\r\n",
                    b"0\r\n\r\n",
                ),
                (
                    b"Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n",
                    b"0\r\n\r\n",
                ),
                (
                    b"Content-Length: 2\r\nContent-Length: 2\r\n",
                    b"{}",
                ),
            )
            for headers, body in framing_cases:
                with self.subTest(headers=headers):
                    status, response_headers, payload = request(
                        "POST", preview_path, headers, body
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(
                        payload["errors"][0]["code"],
                        "INVALID_REQUEST_FRAMING",
                    )
                    self.assertEqual(
                        response_headers["x-trace-id"], payload["traceId"]
                    )

            non_preview_cases = (
                (b"Transfer-Encoding: chunked\r\n", b"0\r\n\r\n"),
                (b"Content-Length: -1\r\n", b""),
                (b"Content-Length: " + b"9" * 5000 + b"\r\n", b""),
                (
                    b"Content-Length: 2\r\nContent-Length: 2\r\n",
                    b"{}",
                ),
            )
            for headers, body in non_preview_cases:
                with self.subTest(non_preview_headers=headers):
                    status, _, payload = request(
                        "POST", items_path, headers, body
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(
                        payload["errors"][0]["code"],
                        "INVALID_REQUEST_FRAMING",
                    )

            status, _, payload = request(
                "POST",
                items_path,
                b"Content-Length: 1048577\r\n",
            )
            self.assertEqual(status, 413)
            self.assertEqual(
                payload["errors"][0]["code"],
                "WRITING_POLICY_JSON_REQUEST_TOO_LARGE",
            )

            many_chunks = b"1\r\na\r\n" * 1025 + b"0\r\n\r\n"
            status, _, payload = request(
                "POST",
                preview_path,
                b"Transfer-Encoding: chunked\r\n",
                many_chunks,
            )
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["errors"][0]["code"], "INVALID_CHUNKED_BODY"
            )

            invalid_chunk_syntax = (
                b"2;\x00\r\n{}\r\n0\r\n\r\n",
                b"2;\r\n{}\r\n0\r\n\r\n",
                b"2;name=\r\n{}\r\n0\r\n\r\n",
                b"2;name=\"unterminated\r\n{}\r\n0\r\n\r\n",
                b"2;name=\"bad\\\r\n{}\r\n0\r\n\r\n",
                b"2;name=\"bad\x00value\"\r\n{}\r\n0\r\n\r\n",
                b"2;name=\"ok\r\n\tcontinued\"\r\n{}\r\n0\r\n\r\n",
                b"2;" + b"a" * 125 + b"\r\n{}\r\n0\r\n\r\n",
                b"2\r\n{}\r\n0\r\n: value\r\n\r\n",
                b"2\r\n{}\r\n0\r\nBad Name: value\r\n\r\n",
                b"2\r\n{}\r\n0\r\nX-Test: bad\x00value\r\n\r\n",
            )
            for body in invalid_chunk_syntax:
                with self.subTest(invalid_chunk_body=body):
                    status, _, payload = request(
                        "POST",
                        preview_path,
                        b"Transfer-Encoding: chunked\r\n",
                        body,
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(
                        payload["errors"][0]["code"], "INVALID_CHUNKED_BODY"
                    )

            preview_content = generate_csv_template()
            preview_request = json.dumps(
                {
                    "fileName": "terms.csv",
                    "mimeType": CSV_MIME,
                    "sizeBytes": len(preview_content),
                    "contentBase64": base64.b64encode(preview_content).decode("ascii"),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            ordinary_chunked = (
                ("%x\r\n" % len(preview_request)).encode("ascii")
                + preview_request
                + b"\r\n0\r\n\r\n"
            )
            status, _, payload = request(
                "POST",
                preview_path,
                b"Transfer-Encoding: chunked\r\n",
                ordinary_chunked,
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["data"]["previewToken"])

            chunk_size = ("%x" % len(preview_request)).encode("ascii")
            valid_extension_bodies = (
                chunk_size
                + b";mode=token;flag\r\n"
                + preview_request
                + b"\r\n0\r\n\r\n",
                chunk_size
                + b"\t;\tmeta\t=\t\"a\\\"b\\\\c\"\r\n"
                + preview_request
                + b"\r\n0\r\n\r\n",
                chunk_size
                + b"\r\n"
                + preview_request
                + b"\r\n0;done=yes\r\n\r\n",
            )
            for body in valid_extension_bodies:
                with self.subTest(valid_chunk_extension=body[:80]):
                    status, _, payload = request(
                        "POST",
                        preview_path,
                        b"Transfer-Encoding: chunked\r\n",
                        body,
                    )
                    self.assertEqual(status, 200)
                    self.assertTrue(payload["data"]["previewToken"])

            too_many_trailers = (
                b"1\r\n{\r\n0\r\n"
                + b"X-Test: value\r\n" * 65
                + b"\r\n"
            )
            status, _, payload = request(
                "POST",
                preview_path,
                b"Transfer-Encoding: chunked\r\n",
                too_many_trailers,
            )
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["errors"][0]["code"], "INVALID_CHUNKED_BODY"
            )

            status, _, payload = request(
                "POST",
                items_path,
                b"Content-Length: 10\r\n",
                b"{}",
            )
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["errors"][0]["code"], "INCOMPLETE_REQUEST_BODY"
            )

            with patch.object(
                self.standalone,
                "WRITING_POLICY_BODY_READ_TIMEOUT_SECONDS",
                0.1,
                create=True,
            ):
                status, _, payload = request(
                    "POST",
                    items_path,
                    b"Content-Length: 10\r\n",
                    b"{",
                    shutdown_write=False,
                )
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["errors"][0]["code"], "REQUEST_BODY_TIMEOUT"
            )

            with patch.object(
                self.standalone,
                "WRITING_POLICY_BODY_READ_TIMEOUT_SECONDS",
                0.12,
                create=True,
            ):
                connection = socket.create_connection((host, port), timeout=3)
                connection.settimeout(3)
                try:
                    connection.sendall(
                        b"POST /writing-policies/items HTTP/1.1\r\n"
                        b"Host: 127.0.0.1\r\n"
                        b"Content-Length: 4\r\n\r\n"
                        b"{"
                    )
                    for byte in b"  }":
                        time.sleep(0.07)
                        readable, _, _ = select.select([connection], [], [], 0)
                        if readable:
                            break
                        try:
                            connection.sendall(bytes((byte,)))
                        except OSError:
                            break
                    status, _, payload = self.read_raw_http_response(connection)
                finally:
                    connection.close()
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["errors"][0]["code"], "REQUEST_BODY_TIMEOUT"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
