import importlib.util
import hashlib
import json
import os
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.errors import AdapterError
from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationStore,
)


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.word.full_document_review import FullDocumentReviewService


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class FullDocumentReviewFeatureGateTests(unittest.TestCase):
    def test_disabled_feature_is_disclosed_and_rejects_before_staging(self) -> None:
        with TemporaryDirectory() as tmp:
            staging_root = Path(tmp) / "full-review"
            with patch.dict(
                os.environ,
                {
                    "AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "0",
                    "AI_WPS_FULL_DOCUMENT_REVIEW_DIR": str(staging_root),
                },
                clear=False,
            ):
                client = TestClient(app)
                config_response = client.get("/config")
                create_response = client.post(
                    "/word/document-review/full/snapshots",
                    json={
                        "documentId": "document-1",
                        "documentType": "technical_solution",
                        "reviewPrompt": "重点检查边界。",
                        "writingPolicyScene": "auto",
                        "coverage": {
                            "includedRegions": ["body"],
                            "excludedRegions": ["headers", "footers"],
                        },
                    },
                )
                disabled_job_responses = [
                    client.get("/word/document-review/full/jobs/missing-job"),
                    client.delete("/word/document-review/full/jobs/missing-job"),
                    client.get(
                        "/word/document-review/full/jobs/missing-job/report"
                    ),
                ]

            self.assertEqual(config_response.status_code, 200)
            self.assertFalse(
                config_response.json()["data"]["features"][
                    "fullDocumentReviewEnabled"
                ]
            )
            self.assertEqual(create_response.status_code, 403)
            self.assertEqual(
                create_response.json()["errors"][0]["code"],
                "FULL_DOCUMENT_REVIEW_DISABLED",
            )
            for response in disabled_job_responses:
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json()["errors"][0]["code"],
                    "FULL_DOCUMENT_REVIEW_DISABLED",
                )
            self.assertFalse(staging_root.exists())

    def test_enabled_session_creation_removes_expired_staging_directory(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            root = Path(tmp) / "full-review"
            stale = root / "full-review-stale"
            stale.mkdir(parents=True)
            os.utime(str(stale), (1, 1))
            service = FullDocumentReviewService(
                staging_root=root,
                provider_client=StrictFullReviewProvider(),
                coordinator=LongTaskCoordinator(),
                staging_ttl_seconds=60,
            )
            service.create_session(
                {
                    "documentId": "document-cleanup",
                    "coverage": {
                        "includedRegions": ["body"],
                        "excludedRegions": [],
                    },
                }
            )

            self.assertFalse(stale.exists())

    def test_disabled_startup_and_periodic_cleanup_remove_expired_staging(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "0"}, clear=False
        ):
            root = Path(tmp) / "full-review"
            stale_at_start = root / "full-review-stale-start"
            stale_at_start.mkdir(parents=True)
            os.utime(str(stale_at_start), (1, 1))
            service = FullDocumentReviewService(
                staging_root=root,
                provider_client=StrictFullReviewProvider(),
                coordinator=LongTaskCoordinator(),
                staging_ttl_seconds=1,
            )
            self.assertFalse(stale_at_start.exists())

            stale_later = root / "full-review-stale-periodic"
            stale_later.mkdir()
            os.utime(str(stale_later), (1, 1))
            service.start_periodic_cleanup(interval_seconds=0.01)
            for _ in range(100):
                if not stale_later.exists():
                    break
                time.sleep(0.01)
            service.stop_periodic_cleanup()

            self.assertFalse(stale_later.exists())

    def test_full_review_paths_are_traced_as_an_independent_task_type(self) -> None:
        from app.main import _task_type_from_path

        self.assertEqual(
            _task_type_from_path("/word/document-review/full/jobs/job-1/report"),
            "word.document_review.full",
        )

    def test_full_review_request_body_is_bounded_before_route_parsing(self) -> None:
        with patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            response = TestClient(app).post(
                "/word/document-review/full/snapshots",
                content=b"{}",
                headers={"Content-Length": str(2 * 1024 * 1024 + 1)},
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "FULL_DOCUMENT_REVIEW_REQUEST_TOO_LARGE",
        )

    def test_chunked_full_review_body_is_bounded_by_actual_bytes(self) -> None:
        with patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            response = TestClient(app).post(
                "/word/document-review/full/snapshots",
                content=iter([b"x" * (1024 * 1024), b"y" * (1024 * 1024 + 1)]),
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "FULL_DOCUMENT_REVIEW_REQUEST_TOO_LARGE",
        )


class FullDocumentReviewReadinessTests(unittest.TestCase):
    def _store(self, root: Path) -> ModelConfigurationStore:
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        return ModelConfigurationStore(config_path, root / "provider_api_keys")

    def _complete(self, store, access_method, max_output_tokens):
        configuration = store.create_configuration(
            "word.document_review",
            "审查配置",
            access_method,
            service_base_url="https://model.example/v1",
            model_name="review-model" if access_method == ACCESS_DIRECT_MODEL else "",
            max_output_tokens=max_output_tokens,
            context_window_tokens=40000,
        )
        return store.replace_api_key(configuration["id"], "secret")

    def test_direct_model_with_explicit_capacity_is_full_review_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            configuration = self._complete(
                self._store(Path(tmp)), ACCESS_DIRECT_MODEL, 2048
            )

        self.assertTrue(configuration["limitedReviewReady"])
        self.assertTrue(configuration["fullDocumentReviewReady"])
        self.assertEqual(
            configuration["fullDocumentReviewReadiness"]["code"], "ready"
        )

    def test_workflow_and_implicit_output_remain_limited_review_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workflow = self._complete(
                self._store(Path(tmp)), ACCESS_WORKFLOW_PLATFORM, None
            )
        with TemporaryDirectory() as tmp:
            direct = self._complete(
                self._store(Path(tmp)), ACCESS_DIRECT_MODEL, None
            )

        self.assertTrue(workflow["limitedReviewReady"])
        self.assertFalse(workflow["fullDocumentReviewReady"])
        self.assertEqual(
            workflow["fullDocumentReviewReadiness"]["code"],
            "direct_model_required",
        )
        self.assertTrue(direct["limitedReviewReady"])
        self.assertFalse(direct["fullDocumentReviewReady"])
        self.assertEqual(
            direct["fullDocumentReviewReadiness"]["code"],
            "explicit_output_tokens_required",
        )

    def test_implicit_context_remains_limited_review_only(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "word.document_review",
                "未显式设置上下文",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="review-model",
                max_output_tokens=2048,
                context_window_tokens=None,
            )
            configuration = store.replace_api_key(configuration["id"], "secret")

        self.assertTrue(configuration["limitedReviewReady"])
        self.assertFalse(configuration["fullDocumentReviewReady"])
        self.assertEqual(
            configuration["fullDocumentReviewReadiness"]["code"],
            "explicit_context_tokens_required",
        )


class StrictFullReviewProvider:
    def __init__(self, answers=None) -> None:
        self.answers = list(answers or [])
        self.calls = []

    def resolve_task_auth(self, task_type):
        return {
            "accessMethod": ACCESS_DIRECT_MODEL,
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "secret",
            "modelName": "review-model",
            "contextWindowTokens": 40000,
            "contextWindowTokensExplicit": True,
            "maxOutputTokens": 2048,
            "modelConfigurationId": "config-review",
        }

    def full_document_review_chunk(
        self,
        source_text,
        trace_id,
        chunk_id,
        document_type,
        review_prompt,
        task_auth,
        correction=False,
        blocks=None,
    ):
        self.calls.append(
            {
                "sourceText": source_text,
                "traceId": trace_id,
                "chunkId": chunk_id,
                "taskAuth": task_auth,
                "correction": correction,
            }
        )
        if self.answers:
            return self.answers.pop(0)
        return json.dumps(
            {
                "schemaVersion": "word.document_review.full.chunk.v1",
                "chunkId": chunk_id,
                "summary": "发现 1 项表达问题。",
                "enumerationStatus": "complete",
                "issues": [
                    {
                        "category": "expression",
                        "severity": "medium",
                        "anchorId": "paragraph-1",
                        "originalText": "尽快",
                        "problem": "时间要求不可验收。",
                        "suggestion": "补充明确完成日期。",
                        "suggestedRewrite": "于 2026 年 8 月 31 日前完成",
                    }
                ],
            },
            ensure_ascii=False,
        )


class PaginatedFullReviewProvider(StrictFullReviewProvider):
    def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                   document_type, review_prompt, task_auth,
                                   correction=False, blocks=None):
        self.calls.append({
            "sourceText": source_text,
            "traceId": trace_id,
            "chunkId": chunk_id,
            "taskAuth": task_auth,
            "correction": correction,
        })
        issues = [
            {
                "category": "expression",
                "severity": "high",
                "anchorId": "paragraph-1",
                "originalText": "尽快",
                "problem": "时间要求不可验收。",
                "suggestion": "补充明确完成日期。",
                "suggestedRewrite": "于 2026 年 8 月 31 日前完成",
            },
            {
                "category": "logic",
                "severity": "medium",
                "anchorId": "paragraph-1",
                "originalText": "尽快",
                "problem": "缺少责任主体。",
                "suggestion": "补充责任部门或责任人。",
                "suggestedRewrite": "由项目组于 2026 年 8 月 31 日前完成",
            },
            {
                "category": "fluency",
                "severity": "low",
                "anchorId": "paragraph-1",
                "originalText": "尽快",
                "problem": "表达过于笼统。",
                "suggestion": "改用可执行的时间表达。",
                "suggestedRewrite": "按计划完成",
            },
        ]
        return json.dumps({
            "schemaVersion": "word.document_review.full.chunk.v1",
            "chunkId": chunk_id,
            "summary": "发现 3 项问题。",
            "enumerationStatus": "complete",
            "issues": issues,
        }, ensure_ascii=False)


class BlockingStrictFullReviewProvider(StrictFullReviewProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def full_document_review_chunk(self, *args, **kwargs):
        self.started.set()
        self.release.wait(timeout=2)
        return super().full_document_review_chunk(*args, **kwargs)


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class FullDocumentReviewApiTests(unittest.TestCase):
    @staticmethod
    def _character_count(text):
        return len(text.encode("utf-16-le")) // 2

    def _service(self, root: Path, provider=None):
        return FullDocumentReviewService(
            staging_root=root,
            provider_client=provider or StrictFullReviewProvider(),
            coordinator=LongTaskCoordinator(max_running=2, max_queued=2),
        )

    def _stage_snapshot(self, client, text="系统应尽快完成联调。"):
        created = client.post(
            "/word/document-review/full/snapshots",
            json={
                "documentId": "document-1",
                "documentType": "technical_solution",
                "reviewPrompt": "重点检查可验收性。",
                "writingPolicyScene": "auto",
                "coverage": {
                    "includedRegions": ["body"],
                    "excludedRegions": [
                        "headers",
                        "footers",
                        "footnotes",
                        "endnotes",
                        "comments",
                        "revisions",
                        "textBoxes",
                        "shapes",
                        "images",
                        "formulas",
                        "charts",
                        "attachments",
                        "hiddenText",
                    ],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        session = created.json()["data"]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        character_count = self._character_count(text)
        uploaded = client.put(
            "/word/document-review/full/snapshots/{0}/batches/0".format(
                session["sessionId"]
            ),
            json={
                "uploadToken": session["uploadToken"],
                "blocks": [
                    {
                        "blockId": "paragraph-1",
                        "blockType": "paragraph",
                        "paragraphIndex": 1,
                        "text": text,
                    }
                ],
                "characterCount": character_count,
                "contentSha256": digest,
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        committed = client.post(
            "/word/document-review/full/snapshots/{0}/commit".format(
                session["sessionId"]
            ),
            json={
                "uploadToken": session["uploadToken"],
                "batchCount": 1,
                "reviewCharacterCount": character_count,
                "contentSha256": digest,
                "verificationSha256": digest,
            },
        )
        self.assertEqual(committed.status_code, 200, committed.text)
        return committed.json()["data"]

    def _wait_job(self, client, job_id):
        job = None
        for _ in range(100):
            response = client.get(
                "/word/document-review/full/jobs/{0}".format(job_id)
            )
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()["data"]
            if job["status"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.01)
        self.fail("full document review job did not finish: {0}".format(job))

    def test_single_chunk_api_produces_traceable_read_only_report(self) -> None:
        provider = StrictFullReviewProvider()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                unauthorized_delete = client.request(
                    "DELETE",
                    "/word/document-review/full/snapshots/{0}".format(
                        snapshot["snapshotId"]
                    ),
                    json={},
                )
                self.assertEqual(unauthorized_delete.status_code, 403)
                self.assertTrue(
                    service.snapshot_path(snapshot["snapshotId"]).exists()
                )
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                self.assertEqual(started.status_code, 200, started.text)
                job_id = started.json()["data"]["jobId"]
                terminal = self._wait_job(client, job_id)
                report_response = client.get(
                    "/word/document-review/full/jobs/{0}/report".format(job_id)
                )
                issues_response = client.get(
                    "/word/document-review/full/jobs/{0}/issues".format(job_id)
                )

            self.assertEqual(terminal["status"], "completed")
            self.assertEqual(report_response.status_code, 200, report_response.text)
            report = report_response.json()["data"]
            self.assertEqual(report["schemaVersion"], "word.document_review.full.report.v1")
            self.assertEqual(report["snapshot"]["snapshotId"], snapshot["snapshotId"])
            self.assertEqual(report["coverage"]["status"], "complete")
            self.assertEqual(report["coverage"]["reviewedCharacterCount"], 10)
            self.assertIn("headers", report["coverage"]["excludedRegions"])
            self.assertIn("tables", report["coverage"]["excludedRegions"])
            self.assertEqual(report["enumerationStatus"], "complete")
            self.assertIn("不承诺检出全部问题", report["disclaimer"])
            self.assertNotIn("issues", report)
            self.assertEqual(
                issues_response.json()["data"]["items"][0]["anchorId"],
                "paragraph-1",
            )
            self.assertNotIn("rawAnswer", report)
            self.assertEqual(len(provider.calls), 1)
            self.assertFalse(service.snapshot_path(snapshot["snapshotId"]).exists())

    def test_completed_review_paginates_by_issue_id_and_tracks_status(self) -> None:
        provider = PaginatedFullReviewProvider()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                terminal = self._wait_job(client, started.json()["data"]["jobId"])
                job_id = started.json()["data"]["jobId"]
                report = client.get(
                    "/word/document-review/full/jobs/{0}/report".format(job_id)
                )
                first_page = client.get(
                    "/word/document-review/full/jobs/{0}/issues?pageSize=2&sort=severity".format(
                        job_id
                    )
                )
                first_data = first_page.json()["data"]
                second_page = client.get(
                    "/word/document-review/full/jobs/{0}/issues?pageSize=2&sort=severity&cursor={1}".format(
                        job_id, first_data["nextCursor"]
                    )
                )
                issue_id = first_data["items"][0]["issueId"]
                marked = client.patch(
                    "/word/document-review/full/jobs/{0}/issues/{1}".format(
                        job_id, issue_id
                    ),
                    json={"status": "processed"},
                )
                processed = client.get(
                    "/word/document-review/full/jobs/{0}/issues?status=processed".format(
                        job_id
                    )
                )
                deleted = client.delete(
                    "/word/document-review/full/jobs/{0}/result".format(job_id)
                )
                missing_report = client.get(
                    "/word/document-review/full/jobs/{0}/report".format(job_id)
                )

        self.assertEqual(terminal["status"], "completed")
        self.assertNotIn("result", terminal)
        self.assertNotIn("issues", report.json()["data"])
        self.assertEqual(report.json()["data"]["issueCount"], 3)
        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(first_data["total"], 3)
        self.assertEqual(len(first_data["items"]), 2)
        self.assertTrue(first_data["nextCursor"])
        self.assertEqual(second_page.status_code, 200, second_page.text)
        self.assertEqual(len(second_page.json()["data"]["items"]), 1)
        self.assertNotEqual(
            first_data["items"][0]["issueId"],
            second_page.json()["data"]["items"][0]["issueId"],
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertEqual(marked.json()["data"]["status"], "processed")
        self.assertEqual(processed.json()["data"]["items"][0]["issueId"], issue_id)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(missing_report.status_code, 404)

    def test_non_bmp_characters_use_the_same_count_as_wps(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp))
            with patch("app.api.word.full_document_review_service", service):
                snapshot = self._stage_snapshot(TestClient(app), "A😀B")

        self.assertEqual(snapshot["reviewCharacterCount"], 4)

    def test_wrong_json_field_types_fail_after_one_correction(self) -> None:
        invalid = json.dumps(
            {
                "schemaVersion": "word.document_review.full.chunk.v1",
                "chunkId": "chunk-1",
                "summary": "格式错误",
                "enumerationStatus": "complete",
                "issues": [
                    {
                        "category": "expression",
                        "severity": "medium",
                        "anchorId": "paragraph-1",
                        "originalText": "尽快",
                        "problem": 123,
                        "suggestion": 456,
                        "suggestedRewrite": "",
                    }
                ],
            },
            ensure_ascii=False,
        )
        provider = StrictFullReviewProvider([invalid, invalid])
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                terminal = self._wait_job(client, started.json()["data"]["jobId"])

        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(len(provider.calls), 2)

    def test_request_field_types_are_rejected_without_string_coercion(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp))
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                invalid_session = client.post(
                    "/word/document-review/full/snapshots",
                    json={
                        "documentId": 123,
                        "coverage": {"includedRegions": ["body"], "excludedRegions": []},
                    },
                )
                invalid_root = client.post(
                    "/word/document-review/full/snapshots", json=[]
                )
                session = client.post(
                    "/word/document-review/full/snapshots",
                    json={
                        "documentId": "document-strict",
                        "coverage": {"includedRegions": ["body"], "excludedRegions": []},
                    },
                ).json()["data"]
                invalid_block = client.put(
                    "/word/document-review/full/snapshots/{0}/batches/0".format(
                        session["sessionId"]
                    ),
                    json={
                        "uploadToken": session["uploadToken"],
                        "blocks": [{
                            "blockId": "paragraph-1", "blockType": "paragraph",
                            "paragraphIndex": True, "text": 456,
                        }],
                        "characterCount": True,
                        "contentSha256": "0" * 64,
                    },
                )

        self.assertEqual(invalid_session.status_code, 400)
        self.assertEqual(invalid_root.status_code, 422)
        self.assertEqual(invalid_block.status_code, 400)

    def test_snapshot_submit_is_single_use_and_client_job_id_is_snapshot_bound(self) -> None:
        provider = BlockingStrictFullReviewProvider()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                first_snapshot = self._stage_snapshot(client, "第一份正文。")
                first_payload = {
                    "snapshotId": first_snapshot["snapshotId"],
                    "snapshotToken": first_snapshot["snapshotToken"],
                    "clientJobId": "client-bound-job",
                }
                first = client.post("/word/document-review/full/jobs", json=first_payload)
                self.assertTrue(provider.started.wait(timeout=1))
                duplicate_snapshot = client.post(
                    "/word/document-review/full/jobs", json=first_payload
                )
                second_snapshot = self._stage_snapshot(client, "第二份正文。")
                conflicting = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": second_snapshot["snapshotId"],
                        "snapshotToken": second_snapshot["snapshotToken"],
                        "clientJobId": "client-bound-job",
                    },
                )
                provider.release.set()
                self._wait_job(client, first.json()["data"]["jobId"])

        self.assertEqual(duplicate_snapshot.status_code, 409)
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(
            conflicting.json()["errors"][0]["code"],
            "FULL_DOCUMENT_REVIEW_JOB_ID_CONFLICT",
        )

    def test_malformed_model_output_retries_once_without_report_fallback(self) -> None:
        provider = StrictFullReviewProvider(["not-json", "still-not-json"])
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                terminal = self._wait_job(
                    client, started.json()["data"]["jobId"]
                )
                report_response = client.get(
                    "/word/document-review/full/jobs/{0}/report".format(
                        started.json()["data"]["jobId"]
                    )
                )

            self.assertEqual(terminal["status"], "failed")
            self.assertEqual(
                terminal["error"]["code"], "FULL_DOCUMENT_REVIEW_RESULT_INVALID"
            )
            self.assertEqual(len(provider.calls), 2)
            self.assertFalse(provider.calls[0]["correction"])
            self.assertTrue(provider.calls[1]["correction"])
            self.assertEqual(report_response.status_code, 409)
            serialized = json.dumps(report_response.json(), ensure_ascii=False)
            self.assertNotIn("not-json", serialized)
            self.assertNotIn("still-not-json", serialized)

    def test_cancellation_after_invalid_result_skips_correction_request(self) -> None:
        provider = StrictFullReviewProvider(["not-json"])
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            parse_result = service._parse_strict_result

            def cancel_while_parsing(answer, snapshot):
                try:
                    return parse_result(answer, snapshot)
                except AdapterError:
                    service.cancel_job(snapshot["jobId"])
                    raise

            service._parse_strict_result = cancel_while_parsing
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                terminal = self._wait_job(client, started.json()["data"]["jobId"])

        self.assertEqual(terminal["status"], "cancelled")
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(provider.calls[0]["correction"])

    def test_queued_full_review_can_be_cancelled_and_snapshot_is_removed(self) -> None:
        provider = BlockingStrictFullReviewProvider()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
            )
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                first_snapshot = self._stage_snapshot(client, "第一份文档应尽快完成。")
                first = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": first_snapshot["snapshotId"],
                        "snapshotToken": first_snapshot["snapshotToken"],
                    },
                )
                self.assertTrue(provider.started.wait(timeout=1))
                second_snapshot = self._stage_snapshot(client, "第二份文档应尽快完成。")
                second = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": second_snapshot["snapshotId"],
                        "snapshotToken": second_snapshot["snapshotToken"],
                    },
                )
                self.assertEqual(second.json()["data"]["status"], "queued")

                cancelled = client.delete(
                    "/word/document-review/full/jobs/{0}".format(
                        second.json()["data"]["jobId"]
                    )
                )
                provider.release.set()
                self._wait_job(client, first.json()["data"]["jobId"])

            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
            self.assertFalse(
                service.snapshot_path(second_snapshot["snapshotId"]).exists()
            )

    def test_running_full_review_can_be_cancelled_without_generating_report(self) -> None:
        provider = BlockingStrictFullReviewProvider()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp), provider)
            with patch("app.api.word.full_document_review_service", service):
                client = TestClient(app)
                snapshot = self._stage_snapshot(client)
                started = client.post(
                    "/word/document-review/full/jobs",
                    json={
                        "snapshotId": snapshot["snapshotId"],
                        "snapshotToken": snapshot["snapshotToken"],
                    },
                )
                job_id = started.json()["data"]["jobId"]
                self.assertTrue(provider.started.wait(timeout=1))
                cancellation = client.delete(
                    "/word/document-review/full/jobs/{0}".format(job_id)
                )
                provider.release.set()
                terminal = self._wait_job(client, job_id)
                report = client.get(
                    "/word/document-review/full/jobs/{0}/report".format(job_id)
                )

        self.assertEqual(cancellation.status_code, 200)
        self.assertTrue(cancellation.json()["data"]["cancelRequested"])
        self.assertEqual(terminal["status"], "cancelled")
        self.assertEqual(report.status_code, 409)

    def test_standalone_routes_match_the_independent_full_review_protocol(self) -> None:
        import standalone_adapter

        def invoke(method, path, payload=None):
            captured = {}
            raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: captured.update(
                status=status, body=body
            )
            getattr(handler, method)()
            return captured

        missing_length = {}
        missing_length_handler = object.__new__(standalone_adapter.Handler)
        missing_length_handler.path = "/word/document-review/full/snapshots"
        missing_length_handler.headers = {}
        missing_length_handler.rfile = BytesIO(b"{}")
        missing_length_handler._write = lambda status, body: missing_length.update(
            status=status, body=body
        )
        missing_length_handler.do_POST()
        self.assertEqual(missing_length["status"], 411)
        self.assertEqual(
            missing_length["body"]["errors"][0]["code"],
            "CONTENT_LENGTH_REQUIRED",
        )

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = self._service(Path(tmp))
            original_service = standalone_adapter.FULL_DOCUMENT_REVIEW_SERVICE
            standalone_adapter.FULL_DOCUMENT_REVIEW_SERVICE = service
            try:
                created = invoke(
                    "do_POST",
                    "/word/document-review/full/snapshots",
                    {
                        "documentId": "standalone-document",
                        "documentType": "technical_solution",
                        "reviewPrompt": "重点检查可验收性。",
                        "writingPolicyScene": "auto",
                        "coverage": {
                            "includedRegions": ["body"],
                            "excludedRegions": ["headers", "footers"],
                        },
                    },
                )
                session = created["body"]["data"]
                text = "系统应尽快完成联调。"
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                uploaded = invoke(
                    "do_PUT",
                    "/word/document-review/full/snapshots/{0}/batches/0".format(
                        session["sessionId"]
                    ),
                    {
                        "uploadToken": session["uploadToken"],
                        "blocks": [
                            {
                                "blockId": "paragraph-1",
                                "blockType": "paragraph",
                                "paragraphIndex": 1,
                                "text": text,
                            }
                        ],
                        "characterCount": len(text),
                        "contentSha256": digest,
                    },
                )
                committed = invoke(
                    "do_POST",
                    "/word/document-review/full/snapshots/{0}/commit".format(
                        session["sessionId"]
                    ),
                    {
                        "uploadToken": session["uploadToken"],
                        "batchCount": 1,
                        "reviewCharacterCount": len(text),
                        "contentSha256": digest,
                        "verificationSha256": digest,
                    },
                )
                started = invoke(
                    "do_POST",
                    "/word/document-review/full/jobs",
                    {
                        "snapshotId": committed["body"]["data"]["snapshotId"],
                        "snapshotToken": committed["body"]["data"]["snapshotToken"],
                    },
                )
                job_id = started["body"]["data"]["jobId"]
                terminal = None
                for _ in range(100):
                    terminal = invoke(
                        "do_GET",
                        "/word/document-review/full/jobs/{0}".format(job_id),
                    )
                    if terminal["body"]["data"]["status"] in {
                        "completed",
                        "failed",
                    }:
                        break
                    time.sleep(0.01)
                report = invoke(
                    "do_GET",
                    "/word/document-review/full/jobs/{0}/report".format(job_id),
                )
            finally:
                standalone_adapter.FULL_DOCUMENT_REVIEW_SERVICE = original_service

        self.assertEqual(created["status"], 200)
        self.assertEqual(uploaded["status"], 200)
        self.assertEqual(committed["status"], 200)
        self.assertEqual(started["status"], 200)
        self.assertEqual(terminal["body"]["taskType"], "word.document_review.full")
        self.assertEqual(terminal["body"]["data"]["status"], "completed")
        self.assertEqual(report["status"], 200)
        self.assertEqual(
            report["body"]["data"]["schemaVersion"],
            "word.document_review.full.report.v1",
        )


if __name__ == "__main__":
    unittest.main()
