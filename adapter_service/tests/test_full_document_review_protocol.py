import hashlib
import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskContinuation, LongTaskCoordinator
from app.services.model_configurations import ACCESS_DIRECT_MODEL
from app.services.word.full_document_review import (
    FullDocumentReviewService,
    classify_review_capacity,
)


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _auth_provider():
    class Provider:
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

    return Provider()


class FullDocumentReviewProtocolTests(unittest.TestCase):
    @staticmethod
    def _snapshot(text, call_limit=8):
        return {
            "jobId": "protocol-job",
            "snapshotId": "protocol-snapshot",
            "documentType": "technical_solution",
            "reviewPrompt": "检查",
            "traceId": "protocol-trace",
            "taskAuth": {},
            "capacity": {"callLimit": call_limit},
            "reviewCharacterCount": len(text),
            "contentSha256": _digest(text),
            "committedAt": 1,
            "coverage": {"includedRegions": ["body"], "excludedRegions": []},
            "blocks": [{
                "blockId": "paragraph-1",
                "blockType": "paragraph",
                "paragraphIndex": 1,
                "text": text,
            }],
        }

    @staticmethod
    def _answer(chunk_id, blocks, saturated=False):
        if saturated:
            return json.dumps({
                "schemaVersion": "word.document_review.full.chunk.v1",
                "chunkId": chunk_id,
                "summary": "枚举受限。",
                "enumerationStatus": "limited",
                "hasMoreIssues": True,
                "issues": [],
            }, ensure_ascii=False)
        block = blocks[0]
        original = block["text"][:2] or "正文"
        return json.dumps({
            "schemaVersion": "word.document_review.full.chunk.v1",
            "chunkId": chunk_id,
            "summary": "发现 1 项问题。",
            "enumerationStatus": "complete",
            "issues": [{
                "category": "expression",
                "severity": "medium",
                "anchorId": block["blockId"],
                "originalText": original,
                "problem": "表达需要进一步明确。",
                "suggestion": "补充可验收的限定条件。",
                "suggestedRewrite": original + "（已明确）",
            }],
        }, ensure_ascii=False)

    @staticmethod
    def _run_to_completion(service, snapshot):
        phases = []
        while True:
            result = service._run_job(snapshot, phases.append)
            if isinstance(result, LongTaskContinuation):
                snapshot = result.snapshot
                continue
            return result, phases

    def _stage_public_snapshot(self, service, text, document_id="document-1"):
        created = service.create_session({
            "documentId": document_id,
            "documentType": "technical_solution",
            "reviewPrompt": "检查",
            "writingPolicyScene": "auto",
            "coverage": {"includedRegions": ["body"], "excludedRegions": []},
        })
        digest = _digest(text)
        uploaded = service.upload_batch(
            created["sessionId"],
            0,
            {
                "uploadToken": created["uploadToken"],
                "blocks": [{
                    "blockId": "paragraph-1",
                    "blockType": "paragraph",
                    "paragraphIndex": 1,
                    "text": text,
                }],
                "characterCount": len(text),
                "contentSha256": digest,
                "batchId": "batch-1",
                "range": {"start": "paragraph-1", "end": "paragraph-1"},
                "editSequence": 1,
            },
        )
        self.assertEqual(uploaded["status"], "uploaded")
        return service.commit_snapshot(
            created["sessionId"],
            {
                "uploadToken": created["uploadToken"],
                "batchCount": 1,
                "reviewCharacterCount": len(text),
                "contentSha256": digest,
                "verificationSha256": digest,
                "structureSha256": uploaded["structureSha256"],
            },
        )

    def test_saturation_splits_parent_and_keeps_call_count_across_continuations(self):
        class Provider:
            def __init__(self):
                self.calls = []

            def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                           document_type, review_prompt, task_auth,
                                           correction=False, blocks=None):
                self.calls.append((source_text, chunk_id))
                return FullDocumentReviewProtocolTests._answer(
                    chunk_id,
                    blocks,
                    saturated=len(self.calls) == 1,
                )

            def full_document_review_aggregate(self, payload, trace_id, task_auth,
                                               correction=False):
                return json.dumps({
                    "schemaVersion": "word.document_review.full.aggregate.v1",
                    "summary": "跨片汇总。",
                    "findings": [],
                }, ensure_ascii=False)

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = Provider()
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            report, phases = self._run_to_completion(
                service, self._snapshot("甲" * 18000)
            )

        self.assertEqual([len(item[0]) for item in provider.calls], [18000, 9000, 9000])
        self.assertEqual(report["issueCount"], 2)
        self.assertIn("splitting", phases)

    def test_persisted_checkpoint_resumes_after_service_restart_without_repeating_completed_chunk(self):
        class RestartProvider:
            def __init__(self, fail_on_call=0, api_key="secret"):
                self.calls = []
                self.fail_on_call = fail_on_call
                self.api_key = api_key

            def resolve_task_auth(self, task_type):
                return {
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "providerBaseUrl": "https://model.example/v1",
                    "apiKey": self.api_key,
                    "modelName": "review-model",
                    "contextWindowTokens": 40000,
                    "contextWindowTokensExplicit": True,
                    "maxOutputTokens": 2048,
                    "modelConfigurationId": "config-review",
                }

            def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                           document_type, review_prompt, task_auth,
                                           correction=False, blocks=None):
                self.calls.append((chunk_id, (blocks or [{}])[0].get("blockId", "")))
                if self.fail_on_call and len(self.calls) == self.fail_on_call:
                    raise AdapterError("PROVIDER_TIMEOUT", "模型超时。", 504)
                usable = next(
                    (block for block in (blocks or []) if block.get("core", True)),
                    (blocks or [{}])[0],
                )
                return FullDocumentReviewProtocolTests._answer(chunk_id, [usable])

            def full_document_review_aggregate(self, payload, trace_id, task_auth,
                                               correction=False):
                return json.dumps({
                    "schemaVersion": "word.document_review.full.aggregate.v1",
                    "summary": "跨片汇总。",
                    "findings": [],
                }, ensure_ascii=False)

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            root = Path(tmp) / "full-review"
            first_provider = RestartProvider(fail_on_call=2)
            first_service = FullDocumentReviewService(
                staging_root=root,
                provider_client=first_provider,
                coordinator=LongTaskCoordinator(),
            )
            snapshot = self._stage_public_snapshot(first_service, "甲" * 22000)
            first_service.start_job(
                {
                    "snapshotId": snapshot["snapshotId"],
                    "snapshotToken": snapshot["snapshotToken"],
                    "clientJobId": "restart-job",
                },
                "restart-trace",
            )
            failed = first_service.coordinator.wait(
                "restart-job", task_type="word.document_review.full"
            )
            self.assertEqual(failed["status"], "failed")
            job_path = root / "job-restart-job" / "job.json"
            self.assertTrue(job_path.exists(), (failed, first_provider.calls))
            persisted = json.loads(job_path.read_text(encoding="utf-8"))
            second_provider = RestartProvider()
            second_service = FullDocumentReviewService(
                staging_root=root,
                provider_client=second_provider,
                coordinator=LongTaskCoordinator(),
            )
            resumed = second_service.coordinator.wait(
                "restart-job", task_type="word.document_review.full"
            )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(resumed["status"], "completed", (resumed, second_provider.calls))
        self.assertEqual(len(second_provider.calls), 1)
        self.assertNotIn('"apiKey":', json.dumps(persisted, ensure_ascii=False))
        self.assertFalse(job_path.exists())

    def test_key_rotation_rejects_persisted_task_before_provider_call(self):
        class AuthProvider:
            def __init__(self, api_key):
                self.api_key = api_key
                self.calls = 0

            def resolve_task_auth(self, task_type):
                return {
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "providerBaseUrl": "https://model.example/v1",
                    "apiKey": self.api_key,
                    "modelName": "review-model",
                    "contextWindowTokens": 40000,
                    "contextWindowTokensExplicit": True,
                    "maxOutputTokens": 2048,
                    "modelConfigurationId": "config-review",
                }

            def full_document_review_chunk(self, *args, **kwargs):
                self.calls += 1
                if self.api_key == "old-secret":
                    raise AdapterError("PROVIDER_TIMEOUT", "模型超时。", 504)
                return FullDocumentReviewProtocolTests._answer(
                    args[2], kwargs.get("blocks")
                )

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            root = Path(tmp) / "full-review"
            provider = AuthProvider("old-secret")
            service = FullDocumentReviewService(
                staging_root=root,
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            snapshot = self._stage_public_snapshot(service, "甲" * 20)
            service.start_job(
                {
                    "snapshotId": snapshot["snapshotId"],
                    "snapshotToken": snapshot["snapshotToken"],
                    "clientJobId": "rotated-job",
                },
                "rotated-trace",
            )
            service.coordinator.wait("rotated-job", task_type="word.document_review.full")
            restarted_provider = AuthProvider("new-secret")
            restarted = FullDocumentReviewService(
                staging_root=root,
                provider_client=restarted_provider,
                coordinator=LongTaskCoordinator(),
            )
            rejected = restarted.get_job("rotated-job")

        self.assertIsNotNone(rejected)
        self.assertEqual(rejected["status"], "failed")
        self.assertEqual(
            rejected["error"]["code"], "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH"
        )
        self.assertEqual(restarted_provider.calls, 0)

    def test_identical_active_task_reuses_original_job_id(self):
        class Provider:
            def __init__(self):
                self.calls = []
                self.started = threading.Event()
                self.release = threading.Event()

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

            def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                           document_type, review_prompt, task_auth,
                                           correction=False, blocks=None):
                self.started.set()
                self.release.wait(timeout=2)
                self.calls.append(chunk_id)
                return FullDocumentReviewProtocolTests._answer(chunk_id, blocks)

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = Provider()
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            first = self._stage_public_snapshot(service, "相同正文")
            first_job = service.start_job(
                {
                    "snapshotId": first["snapshotId"],
                    "snapshotToken": first["snapshotToken"],
                    "clientJobId": "active-job",
                },
                "active-trace",
            )
            self.assertTrue(provider.started.wait(timeout=1))
            duplicate = self._stage_public_snapshot(service, "相同正文")
            reused = service.start_job(
                {
                    "snapshotId": duplicate["snapshotId"],
                    "snapshotToken": duplicate["snapshotToken"],
                },
                "duplicate-trace",
            )
            provider.release.set()
            service.coordinator.wait("active-job", task_type="word.document_review.full")

        self.assertEqual(first_job["jobId"], reused["jobId"])
        self.assertEqual(provider.calls, ["chunk-1"])

    def test_corrupt_persisted_task_is_removed_at_startup_and_private_files_are_restricted(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            root = Path(tmp) / "full-review"
            corrupt = root / "job-corrupt"
            corrupt.mkdir(parents=True)
            (corrupt / "job.json").write_text("not-json", encoding="utf-8")
            service = FullDocumentReviewService(
                staging_root=root,
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            snapshot = self._snapshot("私有正文")
            snapshot.update({
                "_persistentJob": True,
                "jobId": "permission-job",
                "snapshotId": "permission-snapshot",
                "taskAuth": _auth_provider().resolve_task_auth("word.document_review"),
            })
            service._persist_job_state(snapshot, {
                "pendingChunks": service._build_review_chunks(snapshot),
                "parsedChunks": [],
                "limitedRanges": [],
                "callCount": 0,
                "aggregateScheduled": False,
                "aggregateRetried": False,
                "aggregateResult": None,
            })
            job_dir = root / "job-permission-job"
            job_mode = job_dir.stat().st_mode & 0o777
            file_mode = (job_dir / "job.json").stat().st_mode & 0o777
            (job_dir / "checkpoint.json").write_text("not-json", encoding="utf-8")
            restarted = FullDocumentReviewService(
                staging_root=root,
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )

        self.assertFalse(corrupt.exists())
        self.assertEqual(job_mode, 0o700)
        self.assertEqual(file_mode, 0o600)
        self.assertFalse(job_dir.exists())

    def test_review_chunks_keep_semantic_boundaries_and_bounded_overlap(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            snapshot = self._snapshot("甲。乙！丙？" * 5000)
            snapshot["blocks"] = [
                {
                    "blockId": "heading-1",
                    "blockType": "heading",
                    "paragraphIndex": 1,
                    "headingLevel": 1,
                    "text": "第一章 总则",
                },
                {
                    "blockId": "paragraph-1",
                    "blockType": "paragraph",
                    "paragraphIndex": 2,
                    "text": "甲。乙！丙？" * 5000,
                },
            ]
            chunks = service._build_review_chunks(snapshot)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(item["reviewCharacterCount"] <= 20000 for item in chunks))
        self.assertEqual(chunks[0]["overlapCharacterCount"], 0)
        self.assertTrue(all(500 <= item["overlapCharacterCount"] <= 1000 for item in chunks[1:]))
        self.assertTrue(all(
            item["coreCharacterCount"] <= 18000 for item in chunks
        ))
        self.assertTrue(all(
            block.get("isOverlap") is False
            for chunk in chunks
            for block in chunk["blocks"]
            if block.get("isOverlap") is not True
        ))

    def test_large_table_splits_by_rows_and_marks_repeated_header_as_overlap(self):
        rows = [
            {
                "rowIndex": 1,
                "cells": [{
                    "cellId": "header-cell",
                    "rowIndex": 1,
                    "columnIndex": 1,
                    "rowSpan": 1,
                    "columnSpan": 1,
                    "text": "字段",
                }],
            }
        ]
        rows.extend(
            {
                "rowIndex": index,
                "cells": [{
                    "cellId": "cell-{0}".format(index),
                    "rowIndex": index,
                    "columnIndex": 1,
                    "rowSpan": 1,
                    "columnSpan": 1,
                    "text": "数据。" * 4000,
                }],
            }
            for index in range(2, 5)
        )
        block = {
            "blockId": "table-1",
            "blockType": "table",
            "paragraphIndex": 1,
            "tableId": "table-1",
            "tableIndex": 1,
            "rows": rows,
            "nestedTables": [],
        }
        fragments = FullDocumentReviewService._split_table_block(block, 18000)
        self.assertGreaterEqual(len(fragments), 2)
        self.assertTrue(all(
            FullDocumentReviewService._block_character_count(item) <= 18000
            for item in fragments
        ))
        self.assertTrue(all(
            any(row.get("isOverlap") for row in item["rows"])
            for item in fragments[1:]
        ))

    def test_nested_table_content_is_counted_when_splitting_parent_rows(self):
        block = {
            "blockId": "table-parent",
            "blockType": "table",
            "paragraphIndex": 1,
            "tableId": "table-parent",
            "rows": [
                {
                    "rowIndex": 1,
                    "cells": [{
                        "cellId": "header",
                        "rowIndex": 1,
                        "columnIndex": 1,
                        "text": "字段",
                    }],
                },
                {
                    "rowIndex": 2,
                    "cells": [{
                        "cellId": "body",
                        "rowIndex": 2,
                        "columnIndex": 1,
                        "text": "正文。" * 10000,
                        "nestedTableIds": ["table-child"],
                    }],
                },
            ],
            "nestedTables": [{
                "tableId": "table-child",
                "parentCellId": "body",
                "rows": [{
                    "rowIndex": 1,
                    "cells": [{
                        "cellId": "child-cell",
                        "rowIndex": 1,
                        "columnIndex": 1,
                        "text": "子表内容",
                    }],
                }],
                "nestedTables": [],
            }],
        }
        fragments = FullDocumentReviewService._split_table_block(block, 18000)
        self.assertGreaterEqual(len(fragments), 2)
        self.assertTrue(all(
            FullDocumentReviewService._block_character_count(item) <= 18000
            for item in fragments
        ))
        self.assertTrue(all(
            any("table-child" in cell.get("nestedTableIds", [])
                for row in item["rows"] for cell in row.get("cells", []))
            for item in fragments
        ))

    def test_v2_anchor_start_identifies_repeated_occurrence_and_preserves_source_anchor(self):
        service = FullDocumentReviewService(
            staging_root=Path("/tmp/full-document-review-test"),
            provider_client=_auth_provider(),
            coordinator=LongTaskCoordinator(),
        )
        text = "重复，重复。"
        snapshot = self._snapshot(text)
        chunk = {
            "chunkId": "chunk-1",
            "blocks": [{
                "blockId": "paragraph-1",
                "blockType": "paragraph",
                "paragraphIndex": 1,
                "text": text,
                "sourceBlockId": "paragraph-source",
                "sourceOffsetStart": 20,
                "sourceOffsetEnd": 26,
                "range": {"start": 100, "end": 106},
            }],
        }
        answer = json.dumps({
            "schemaVersion": "word.document_review.full.chunk.v2",
            "chunkId": "chunk-1",
            "summary": "重复词项。",
            "enumerationStatus": "complete",
            "hasMoreIssues": False,
            "facts": [],
            "crossChecks": [],
            "issues": [{
                "category": "expression",
                "severity": "low",
                "anchorId": "paragraph-1",
                "anchorStart": 3,
                "originalText": "重复",
                "problem": "第二处重复词项需要确认。",
                "suggestion": "核对术语。",
                "suggestedRewrite": "",
            }],
        }, ensure_ascii=False)
        parsed = service._parse_strict_result(answer, snapshot, chunk)
        issue = parsed["issues"][0]
        self.assertEqual(issue["sourceOffset"], 23)
        self.assertEqual(issue["sourceAnchor"]["start"], 23)
        self.assertEqual(issue["sourceAnchor"]["end"], 25)
        self.assertTrue(issue["issueId"].startswith("issue-"))

    def test_aggregate_input_budget_is_checked_before_provider_request(self):
        snapshot = self._snapshot("甲。")
        parsed = [{
            "chunkId": "chunk-1",
            "summary": "摘要",
            "facts": [],
            "crossChecks": [],
            "issues": [{
                "issueId": "issue-{0}".format(index),
                "category": "logic",
                "severity": "high",
                "anchorId": "paragraph-1",
                "problem": "问题" * 240,
            } for index in range(500)],
        }]
        with self.assertRaises(AdapterError) as context:
            FullDocumentReviewService._build_aggregate_input(snapshot, parsed)
        self.assertEqual(
            context.exception.code,
            "FULL_DOCUMENT_REVIEW_AGGREGATE_INPUT_TOO_LARGE",
        )

    def test_multi_chunk_review_aggregates_compact_facts_and_rejects_unknown_references(self):
        class Provider:
            def __init__(self, aggregate_answer):
                self.aggregate_answer = aggregate_answer
                self.chunk_calls = []
                self.aggregate_calls = []

            def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                           document_type, review_prompt, task_auth,
                                           correction=False, blocks=None):
                self.chunk_calls.append({
                    "sourceText": source_text,
                    "chunkId": chunk_id,
                    "blocks": blocks,
                })
                anchor = next(block for block in blocks if not block.get("isOverlap"))
                return json.dumps({
                    "schemaVersion": "word.document_review.full.chunk.v1",
                    "chunkId": chunk_id,
                    "summary": "分片摘要。",
                    "enumerationStatus": "complete",
                    "hasMoreIssues": False,
                    "facts": [{
                        "factId": "fact-1",
                        "kind": "definition",
                        "statement": "系统应完成联调。",
                        "anchorIds": [anchor["blockId"]],
                    }],
                    "crossChecks": [{
                        "checkId": "check-1",
                        "statement": "前后章节应保持一致。",
                        "anchorIds": [anchor["blockId"]],
                    }],
                    "issues": [],
                }, ensure_ascii=False)

            def full_document_review_aggregate(self, payload, trace_id, task_auth,
                                               correction=False):
                self.aggregate_calls.append(payload)
                return self.aggregate_answer

        aggregate = json.dumps({
            "schemaVersion": "word.document_review.full.aggregate.v1",
            "summary": "跨片结论。",
            "findings": [],
        }, ensure_ascii=False)
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = Provider(aggregate)
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            snapshot = self._snapshot("甲。" * 10000)
            report, _ = self._run_to_completion(service, snapshot)

        self.assertEqual(report["globalSummary"], "跨片结论。")
        self.assertEqual(len(provider.aggregate_calls), 1)
        self.assertNotIn("sourceText", provider.aggregate_calls[0])
        self.assertIn("facts", provider.aggregate_calls[0])

        invalid_provider = Provider(json.dumps({
            "schemaVersion": "word.document_review.full.aggregate.v1",
            "summary": "无效。",
            "findings": [{
                "findingId": "finding-1",
                "kind": "contradiction",
                "severity": "high",
                "summary": "引用不存在。",
                "issueIds": ["issue-unknown"],
                "factIds": [],
                "anchorIds": [],
            }],
        }, ensure_ascii=False))
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=invalid_provider,
                coordinator=LongTaskCoordinator(),
            )
            with self.assertRaises(AdapterError) as context:
                self._run_to_completion(service, self._snapshot("乙。" * 10000))
        self.assertEqual(context.exception.code, "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID")

    def test_provider_timeout_is_not_retried_but_connection_failure_is(self):
        class Provider:
            def __init__(self, error):
                self.error = error
                self.calls = 0

            def full_document_review_chunk(self, source_text, trace_id, chunk_id,
                                           document_type, review_prompt, task_auth,
                                           correction=False, blocks=None):
                self.calls += 1
                if self.calls == 1:
                    raise self.error
                return FullDocumentReviewProtocolTests._answer(chunk_id, blocks)

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = Provider(AdapterError("PROVIDER_UNREACHABLE", "down", 502))
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            report, phases = self._run_to_completion(service, self._snapshot("乙" * 20))
        self.assertEqual(report["issueCount"], 1)
        self.assertEqual(provider.calls, 2)
        self.assertIn("retrying", phases)

        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = Provider(AdapterError("PROVIDER_TIMEOUT", "timeout", 504))
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            with self.assertRaises(AdapterError) as context:
                self._run_to_completion(service, self._snapshot("丙" * 20))
        self.assertEqual(context.exception.code, "PROVIDER_TIMEOUT")
        self.assertEqual(provider.calls, 1)

    def test_capacity_tiers_expose_confirmation_and_call_limits(self):
        self.assertEqual(classify_review_capacity(20000)["tier"], "single_chunk")
        self.assertEqual(classify_review_capacity(20001)["tier"], "standard")
        self.assertEqual(classify_review_capacity(60000)["tier"], "standard")
        large = classify_review_capacity(60001)
        self.assertEqual(large["tier"], "large")
        self.assertTrue(large["requiresConfirmation"])
        self.assertEqual(large["callLimit"], 24)
        with self.assertRaises(AdapterError) as context:
            classify_review_capacity(120001)
        self.assertEqual(context.exception.code, "FULL_DOCUMENT_REVIEW_TOO_LARGE")

    def test_call_limit_rejects_before_provider_request(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            provider = _auth_provider()
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=provider,
                coordinator=LongTaskCoordinator(),
            )
            with self.assertRaises(AdapterError) as context:
                service._run_job(
                    {
                        "jobId": "job-1",
                        "snapshotId": "snapshot-1",
                        "documentType": "technical_solution",
                        "reviewPrompt": "检查",
                        "traceId": "trace-1",
                        "taskAuth": {},
                        "capacity": {"callLimit": 0},
                        "blocks": [{
                            "blockId": "paragraph-1",
                            "blockType": "paragraph",
                            "paragraphIndex": 1,
                            "text": "正文",
                        }],
                    },
                    lambda _phase: None,
                )
            self.assertEqual(
                context.exception.code, "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED"
            )

    def test_structured_table_batch_preserves_merge_and_nested_relationships(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            session = service.create_session(
                {
                    "documentId": "doc-1",
                    "coverage": {
                        "includedRegions": ["body", "tables"],
                        "excludedRegions": [],
                    },
                }
            )
            text = "金额"
            block = {
                "blockId": "table-1",
                "blockType": "table",
                "tableId": "table-1",
                "tableIndex": 1,
                "rows": [
                    {
                        "rowIndex": 1,
                        "cells": [
                            {
                                "cellId": "cell-1",
                                "rowIndex": 1,
                                "columnIndex": 1,
                                "rowSpan": 1,
                                "columnSpan": 2,
                                "mergeId": "merge-1",
                                "text": text,
                                "nestedTableIds": ["table-1-1"],
                            }
                        ],
                    }
                ],
                "nestedTables": [
                    {
                        "tableId": "table-1-1",
                        "parentCellId": "cell-1",
                        "rows": [
                            {
                                "rowIndex": 1,
                                "cells": [
                                    {
                                        "cellId": "cell-1-1",
                                        "rowIndex": 1,
                                        "columnIndex": 1,
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                        "text": "子表",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            source_text = "\n".join([text, "子表"])
            uploaded = service.upload_batch(
                session["sessionId"],
                0,
                {
                    "uploadToken": session["uploadToken"],
                    "batchId": "batch-0",
                    "blocks": [block],
                    "characterCount": len(text) + len("子表"),
                    "contentSha256": _digest(source_text),
                },
            )
            self.assertEqual(uploaded["tableCount"], 2)
            self.assertEqual(uploaded["cellCount"], 2)
            committed = service.commit_snapshot(
                session["sessionId"],
                {
                    "uploadToken": session["uploadToken"],
                    "batchCount": 1,
                    "reviewCharacterCount": len(text) + len("子表"),
                    "contentSha256": _digest(source_text),
                    "verification": {
                        "batchCount": 1,
                        "reviewCharacterCount": len(text) + len("子表"),
                        "contentSha256": _digest(source_text),
                        "structureSha256": uploaded["structureSha256"],
                        "blockCount": 1,
                        "tableCount": 2,
                        "cellCount": 2,
                    },
                },
            )
            self.assertEqual(committed["capacity"]["tier"], "single_chunk")
            self.assertEqual(committed["tableCount"], 2)
            self.assertEqual(committed["cellCount"], 2)

    def test_retrying_same_batch_is_idempotent_but_conflicting_retry_is_rejected(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            session = service.create_session(
                {
                    "documentId": "doc-1",
                    "coverage": {"includedRegions": ["body"], "excludedRegions": []},
                }
            )
            payload = {
                "uploadToken": session["uploadToken"],
                "batchId": "batch-0",
                "blocks": [
                    {
                        "blockId": "paragraph-1",
                        "blockType": "heading",
                        "paragraphIndex": 1,
                        "headingLevel": 1,
                        "text": "标题",
                    }
                ],
                "characterCount": 2,
                "contentSha256": _digest("标题"),
            }
            first = service.upload_batch(session["sessionId"], 0, payload)
            retry = service.upload_batch(session["sessionId"], 0, payload)
            self.assertEqual(first["reviewCharacterCount"], retry["reviewCharacterCount"])
            self.assertTrue(retry["idempotent"])
            payload["contentSha256"] = _digest("改写")
            with self.assertRaises(AdapterError) as context:
                service.upload_batch(session["sessionId"], 0, payload)
            self.assertEqual(
                context.exception.code, "FULL_DOCUMENT_REVIEW_BATCH_IDEMPOTENCY_CONFLICT"
            )

    def test_second_pass_metric_mismatch_deletes_staging(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            session = service.create_session(
                {
                    "documentId": "doc-1",
                    "coverage": {"includedRegions": ["body"], "excludedRegions": []},
                }
            )
            service.upload_batch(
                session["sessionId"],
                0,
                {
                    "uploadToken": session["uploadToken"],
                    "blocks": [
                        {
                            "blockId": "paragraph-1",
                            "blockType": "paragraph",
                            "paragraphIndex": 1,
                            "text": "首遍正文",
                        }
                    ],
                    "characterCount": 4,
                    "contentSha256": _digest("首遍正文"),
                },
            )
            with self.assertRaises(AdapterError) as context:
                service.commit_snapshot(
                    session["sessionId"],
                    {
                        "uploadToken": session["uploadToken"],
                        "batchCount": 1,
                        "reviewCharacterCount": 4,
                        "contentSha256": _digest("首遍正文"),
                        "verification": {
                            "batchCount": 1,
                            "reviewCharacterCount": 5,
                            "contentSha256": _digest("次遍正文"),
                            "blockCount": 1,
                        },
                    },
                )
            self.assertEqual(context.exception.code, "FULL_DOCUMENT_REVIEW_SNAPSHOT_MISMATCH")
            self.assertFalse(service.snapshot_path(session["sessionId"]).exists())

    def test_standard_snapshot_accepts_multiple_contiguous_batches(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW": "1"}, clear=False
        ):
            service = FullDocumentReviewService(
                staging_root=Path(tmp),
                provider_client=_auth_provider(),
                coordinator=LongTaskCoordinator(),
            )
            session = service.create_session(
                {
                    "documentId": "doc-1",
                    "coverage": {"includedRegions": ["body"], "excludedRegions": []},
                }
            )
            first = "甲" * 11000
            second = "乙" * 11000
            for sequence, block_id, text in ((0, "paragraph-1", first), (1, "paragraph-2", second)):
                service.upload_batch(
                    session["sessionId"],
                    sequence,
                    {
                        "uploadToken": session["uploadToken"],
                        "batchId": "batch-{0}".format(sequence),
                        "blocks": [{
                            "blockId": block_id,
                            "blockType": "paragraph",
                            "paragraphIndex": sequence + 1,
                            "text": text,
                        }],
                        "characterCount": len(text),
                        "contentSha256": _digest(text),
                    },
                )
            digest = _digest(first + "\n" + second)
            committed = service.commit_snapshot(
                session["sessionId"],
                {
                    "uploadToken": session["uploadToken"],
                    "batchCount": 2,
                    "reviewCharacterCount": len(first) + len(second),
                    "contentSha256": digest,
                    "verification": {
                        "batchCount": 2,
                        "reviewCharacterCount": len(first) + len(second),
                        "contentSha256": digest,
                        "blockCount": 2,
                        "tableCount": 0,
                        "cellCount": 0,
                    },
                },
            )
            self.assertEqual(committed["capacity"]["tier"], "standard")
            self.assertEqual(committed["capacity"]["initialChunkCount"], 2)


if __name__ == "__main__":
    unittest.main()
