"""Writing cancellation must interrupt real sockets before releasing document slots."""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from app.core.config import AppSettings
from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.provider_client import ProviderClient
from app.services.task_history import TaskHistoryStore
from app.services.word.rewriter import WordRewriter
from app.services.word.smart_imitator import WordSmartImitator
from app.services.word.writing_jobs import SmartImitationJobStore, SmartWriteJobStore
from app.services.writing_policy import WritingPolicyService
from app.services.writing_policy.store import WritingPolicyStore


@contextmanager
def waiting_model(stage):
    entered, release = threading.Event(), threading.Event()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            first = len(received) == 1
            fallback = stage in ("fallback-json", "fallback-error")
            if (first and stage == "headers") or (fallback and not first):
                entered.set()
                release.wait(5)
            is_error = first and stage == "error"
            status = 422 if is_error else (415 if first and stage == "fallback-error" else 200)
            self.send_response(status)
            self.send_header("Content-Type", "application/json" if is_error or fallback else "text/event-stream")
            error_body = b'{"error":"stream rejected"}'
            if is_error:
                self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.flush()
            if is_error:
                entered.set()
                release.wait(5)
                payload = error_body
            elif fallback:
                payload = json.dumps({"choices": [{"message": {"content": "生成文本。"}}]}).encode()
            else:
                delta = {"choices": [{"delta": {"content": "生成文本。"}}]}
                payload = ("data: " + json.dumps(delta) + "\n\n").encode()
            try:
                self.wfile.write(payload)
                self.wfile.flush()
                if first and stage == "sse":
                    release.wait(5)
                if not is_error and not fallback:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port, received, entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def writing_request(job_id):
    payload = {
        "documentId": "transport-test.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": job_id,
        "documentSessionId": "same-document",
        "content": {"plainText": "示例模板。", "paragraphs": [], "headings": []},
        "options": {"imitationRequirement": "编写新的示例内容"},
    }
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


@pytest.mark.parametrize("task_type,worker_type,store_type", [
    ("word.smart_write", WordRewriter, SmartWriteJobStore),
    ("word.smart_imitation", WordSmartImitator, SmartImitationJobStore),
])
@pytest.mark.parametrize("stage", ["headers", "sse", "error"])
def test_cancel_stops_writing_transport_before_releasing_document_slot(
    tmp_path, task_type, worker_type, store_type, stage
):
    provider = ProviderClient(AppSettings())
    policy = WritingPolicyService(WritingPolicyStore(tmp_path / "policies.db"))
    worker = worker_type(provider_client=provider, writing_policy_service=policy)
    coordinator = LongTaskCoordinator(max_running=1)
    store = store_type(worker=worker, coordinator=coordinator)
    history = TaskHistoryStore(tmp_path / "history")
    transport_finished, runner_release = threading.Event(), threading.Event()
    original_run = store._run

    with waiting_model(stage) as (url, received, entered, server_release):
        auth = {
            "accessMethod": "direct_model", "providerBaseUrl": url,
            "apiKey": "local-test", "modelName": "local-test",
            "streamingCapability": "validated",
        }

        def tracked_run(snapshot, control):
            class Progress:
                def __call__(self, phase):
                    control(phase)
                    if phase == "streaming":
                        entered.set()

                def __getattr__(self, name):
                    return getattr(control, name)

            try:
                return original_run(snapshot, Progress())
            finally:
                if snapshot["jobId"] == "cancel-transport":
                    transport_finished.set()
                    runner_release.wait(5)

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), \
                patch.object(provider, "resolve_task_auth", return_value=auth), \
                patch.object(store, "_run", side_effect=tracked_run), \
                patch("app.services.word.writing_jobs.get_task_history_store", return_value=history):
            store.start(writing_request("cancel-transport"), "cancel-transport")
            try:
                assert entered.wait(2), "the request must reach the controlled wait"
                requested = store.cancel("cancel-transport")
                assert requested["cancelRequested"] is True
                assert requested["phase"] == "stopping"
                assert transport_finished.wait(1), "cancel must end the provider call before the server responds"
                assert not server_release.is_set()
                assert store.get("cancel-transport")["status"] == "running"
                assert coordinator.diagnostics()["runningCount"] == 1
                with pytest.raises(AdapterError) as busy:
                    store.start(writing_request("next-transport"), "next-transport")
                assert busy.value.code == "WORD_WRITING_DOCUMENT_TASK_BUSY"
                assert history.list_history(task_type) == []
                assert len(received) == 1, "cancellation must not retry the generation"

                runner_release.set()
                cancelled = coordinator.wait("cancel-transport", task_type=task_type)
                assert cancelled["status"] == "cancelled"
                assert coordinator.diagnostics()["runningCount"] == 0
                assert history.list_history(task_type) == []

                store.start(writing_request("next-transport"), "next-transport")
                completed = coordinator.wait("next-transport", task_type=task_type)
                assert completed["status"] == "completed"
                assert completed["result"]["rewrittenText"] == "生成文本。"
                assert [entry["jobId"] for entry in history.list_history(task_type)] == ["next-transport"]
                assert len(received) == 2
            finally:
                runner_release.set()
                server_release.set()
                coordinator.wait("cancel-transport", task_type=task_type)


@pytest.mark.parametrize("task_type", ["word.smart_write", "word.smart_imitation"])
@pytest.mark.parametrize("stage", ["fallback-json", "fallback-error"])
def test_stream_fallback_keeps_blocking_request_cancellable(task_type, stage):
    provider = ProviderClient(AppSettings())
    coordinator = LongTaskCoordinator(max_running=1)
    transport_finished = threading.Event()
    with waiting_model(stage) as (url, received, entered, release):
        def runner(snapshot, control):
            try:
                return provider._post_direct_task(
                    task_type, "fallback-transport", "示例内容",
                    {"providerBaseUrl": url, "modelName": "local-test", "apiKey": "local-test",
                     "streamingCapability": "validated", "directStreamingEnabled": True},
                    timeout=5, progress_callback=control,
                )
            finally:
                transport_finished.set()

        coordinator.submit(
            job_id="fallback-transport", trace_id="fallback-transport", task_type=task_type,
            runner=runner, snapshot={}, failure_code="FAILED", failure_message="failed",
            allow_running_cancel=True,
        )
        try:
            assert entered.wait(2)
            assert [body["stream"] for body in received] == [True, False]
            assert coordinator.get("fallback-transport", task_type=task_type)["canCancel"] is True
            requested = coordinator.request_cancel("fallback-transport", task_type=task_type)
            assert requested["cancelRequested"] is True
            assert transport_finished.wait(1), "cancel must interrupt the fallback connection"
            cancelled = coordinator.wait("fallback-transport", task_type=task_type)
            assert cancelled["status"] == "cancelled"
            assert not release.is_set(), "cancel must finish before the server responds"
            assert coordinator.diagnostics()["runningCount"] == 0
            assert len(received) == 2, "cancellation must not start another request"
        finally:
            release.set()
            coordinator.wait("fallback-transport", task_type=task_type)
