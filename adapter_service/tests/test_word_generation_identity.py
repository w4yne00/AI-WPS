"""Generation requests execute per client action; retries retain their identity."""
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryStore
from app.services.word.writing_jobs import SmartWriteJobStore, SmartImitationJobStore
from tests.test_word_writing_jobs import BlockingWritingWorker, make_request


@pytest.fixture(params=["fastapi", "standalone"])
def submit(request):
    if request.param == "fastapi":
        with TestClient(app) as client:
            def post(path, payload):
                response = client.post(path, json=payload)
                return response.status_code, response.json()
            yield post
    else:
        import standalone_adapter

        def post(path, payload):
            raw = json.dumps(payload).encode("utf-8")
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: captured.update(status=status, body=body)
            handler.do_POST()
            return captured["status"], captured["body"]
        yield post


@pytest.fixture(params=[("smart_write", SmartWriteJobStore), ("smart_imitation", SmartImitationJobStore)])
def writing(request, monkeypatch, tmp_path):
    import app.api.word as word_api
    import standalone_adapter

    task, store_type = request.param
    worker = BlockingWritingWorker()
    worker.release.set()
    coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
    store = store_type(worker=worker, coordinator=coordinator)
    history = TaskHistoryStore(tmp_path / "history")
    monkeypatch.setattr("app.services.word.writing_jobs.get_task_history_store", lambda: history)
    monkeypatch.setattr(word_api, task + "_jobs", store)
    monkeypatch.setattr(standalone_adapter, task.upper() + "_JOB_STORE", store)
    return "/word/" + task.replace("_", "-") + "/jobs", task, worker, coordinator


def payload(job_id):
    return make_request(job_id, document_session_id="document-a").model_dump(by_alias=True)


def test_new_action_executes_again_but_completed_retry_does_not(submit, writing):
    path, task, worker, coordinator = writing
    first = payload("generation-action-one")
    for request in (first, first, payload("generation-action-two")):
        status, body = submit(path, request)
        assert status == 200, body
        terminal = coordinator.wait(body["data"]["jobId"], task_type="word." + task)
        assert terminal["status"] == "completed", terminal
        assert terminal["result"]["rewrittenText"] == "处理完成。"
    assert [call[0] for call in worker.calls] == ["generation-action-one", "generation-action-two"]


@pytest.mark.parametrize("changed", [{"documentSessionId": "document-b"}, {"host": "et"}])
def test_retry_cannot_reuse_result_from_another_document_or_host(submit, writing, changed):
    path, task, worker, coordinator = writing
    first = payload("generation-isolated-action")
    status, body = submit(path, first)
    assert status == 200, body
    assert coordinator.wait(body["data"]["jobId"], task_type="word." + task)["status"] == "completed"
    status, body = submit(path, dict(first, **changed))
    assert status == 409, body
    assert body["success"] is False
    assert len(worker.calls) == 1


def test_document_review_new_action_and_completed_retry(submit, monkeypatch, tmp_path):
    import app.api.word as word_api
    import standalone_adapter
    from app.services.word.document_review_jobs import DocumentReviewJobStore
    from app.services.word.document_reviewer import WordDocumentReviewer
    from tests.test_word_document_review import RecordingDocumentReviewProvider, FakeWritingPolicyService

    provider = RecordingDocumentReviewProvider()
    coordinator = LongTaskCoordinator()
    store = DocumentReviewJobStore(
        WordDocumentReviewer(provider_client=provider, writing_policy_service=FakeWritingPolicyService()),
        coordinator=coordinator,
    )
    history = TaskHistoryStore(tmp_path / "history")
    monkeypatch.setattr("app.services.word.document_review_jobs.get_task_history_store", lambda: history)
    monkeypatch.setattr(word_api, "document_review_jobs", store)
    monkeypatch.setattr(standalone_adapter, "DOCUMENT_REVIEW_JOB_STORE", store)
    first = payload("review-generation-one")
    for request in (first, first, payload("review-generation-two")):
        status, body = submit("/word/document-review/jobs", request)
        assert status == 200, body
        terminal = coordinator.wait(body["data"]["jobId"], task_type="word.document_review")
        assert terminal["status"] == "completed", terminal.get("error", terminal)
    assert len(provider.calls) == 2
    assert provider.calls[0]["text"] == provider.calls[1]["text"] == "待处理文本。"


def test_material_composer_new_action_and_completed_retry(submit, monkeypatch, tmp_path):
    import app.api.word as word_api
    import standalone_adapter
    from tests.test_word_composer_full_document import setup_job, p

    jobs, coordinator = setup_job(tmp_path, p("相同原文"))
    calls = []

    def respond(task_type, trace, data, prompt, **kwargs):
        calls.append(prompt)
        return {"answer": json.dumps({"paragraphs": [{
            "text": "相同原文", "fragmentIds": ["frag-1"], "missingItems": [],
        }]})}

    monkeypatch.setattr(jobs.provider, "resolve_task_auth", lambda task: {
        "providerBaseUrl": "https://model.invalid", "apiKey": "test",
    })
    monkeypatch.setattr(jobs.provider, "post_task", respond)
    monkeypatch.setattr(word_api, "material_composer_jobs", jobs)
    monkeypatch.setattr(standalone_adapter, "MATERIAL_COMPOSER_JOBS", jobs)
    first = {"documentSessionId": "doc-session-1", "clientJobId": "composer-generation-one",
             "instruction": "编写", "writingPolicyScene": "disabled"}
    for request in (first, first, dict(first, clientJobId="composer-generation-two")):
        status, body = submit("/word/material-composer/jobs", request)
        assert status == 200, body
        terminal = coordinator.wait(body["data"]["jobId"], task_type="word.material_composer")
        assert terminal["status"] == "completed", terminal
        assert terminal["result"]["paragraphs"][0]["text"] == "相同原文"
    assert len(calls) == 2


@pytest.mark.parametrize("first_fails", [False, True])
def test_full_review_new_action_and_running_retry(submit, monkeypatch, tmp_path, first_fails):
    import app.api.word as word_api
    import standalone_adapter
    from tests import test_word_full_document_review as fixtures

    monkeypatch.setenv("AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW", "1")
    helper = fixtures.FullDocumentReviewApiTests()
    class BlockingProvider(fixtures.BlockingStrictFullReviewProvider):
        attempts = 0

        def full_document_review_chunk(self, *args, progress_callback=None, **kwargs):
            self.attempts += 1
            self.started.set()
            self.release.wait(2)
            if first_fails and self.attempts <= 2:
                from app.core.errors import AdapterError
                raise AdapterError("PROVIDER_UNREACHABLE", "模型服务暂时不可达。", status_code=502)
            return super().full_document_review_chunk(*args, **kwargs)

    provider = BlockingProvider()
    service = helper._service(tmp_path, provider)
    monkeypatch.setattr(word_api, "full_document_review_service", service)
    monkeypatch.setattr(standalone_adapter, "FULL_DOCUMENT_REVIEW_SERVICE", service)
    with TestClient(app) as client:
        first_snapshot = helper._stage_snapshot(client)
        first = {"snapshotId": first_snapshot["snapshotId"], "snapshotToken": first_snapshot["snapshotToken"],
                 "clientJobId": "full-review-generation-one"}
        second_snapshot = helper._stage_snapshot(client)
        second = {"snapshotId": second_snapshot["snapshotId"], "snapshotToken": second_snapshot["snapshotToken"],
                  "clientJobId": "full-review-generation-two"}
        try:
            status, body = submit("/word/document-review/full/jobs", first)
            assert status == 200, body
            assert provider.started.wait(1)
            retry_status, retry = submit("/word/document-review/full/jobs", first)
            assert retry_status == 200, retry
            assert retry["data"]["jobId"] == body["data"]["jobId"]
            for changed in ({"documentSessionId": "other-document"}, {"host": "et"}):
                conflict_status, conflict = submit("/word/document-review/full/jobs", dict(first, **changed))
                assert conflict_status == 409, conflict
        finally:
            provider.release.set()
        terminal = helper._wait_job(client, body["data"]["jobId"])
        assert terminal["status"] == ("failed" if first_fails else "completed"), terminal
        status, body = submit("/word/document-review/full/jobs", second)
        assert status == 200, body
        terminal = helper._wait_job(client, body["data"]["jobId"])
        assert terminal["status"] == "completed", terminal.get("error", terminal)
    assert provider.attempts == (3 if first_fails else 2)
    assert len(provider.calls) == (1 if first_fails else 2)
    assert all(call["sourceText"] == "系统应尽快完成联调。" for call in provider.calls)


def test_format_review_new_action_and_completed_retry(submit, monkeypatch, tmp_path):
    import app.api.word as word_api
    import standalone_adapter
    from app.services.word.deterministic_format_review import DeterministicFormatReviewService, TASK_TYPE
    from tests import test_word_format_review_history as fixtures

    monkeypatch.setenv("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", "1")
    helper = fixtures.WordFormatReviewHistoryTests()
    coordinator = LongTaskCoordinator()
    reviewer = fixtures.MockFormatReviewer()
    calls = []
    review = reviewer.review

    def counted_review(*args, **kwargs):
        calls.append(args[0])
        return review(*args, **kwargs)

    monkeypatch.setattr(reviewer, "review", counted_review)
    service = DeterministicFormatReviewService(staging_root=tmp_path / "staging",
                                             reviewer=reviewer, coordinator=coordinator)
    helper.service = service
    history = TaskHistoryStore(tmp_path / "history")
    monkeypatch.setattr("app.services.word.deterministic_format_review.get_task_history_store", lambda: history)
    monkeypatch.setattr(word_api, "deterministic_format_review_service", service)
    monkeypatch.setattr(standalone_adapter, "DETERMINISTIC_FORMAT_REVIEW_SERVICE", service)
    # Format snapshots are consumed by submission; each POST uploads fresh facts.
    for job_id in ("format-generation-one", "format-generation-one", "format-generation-two"):
        snapshot = helper._create_and_commit_snapshot()
        status, body = submit("/word/format-review/jobs", dict(snapshot, clientJobId=job_id))
        assert status == 200, body
        terminal = coordinator.wait(body["data"]["jobId"], task_type=TASK_TYPE)
        assert terminal["status"] == "completed", terminal
    assert len(calls) == 2
