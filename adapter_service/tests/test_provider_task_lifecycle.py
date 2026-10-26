"""Task cancellation and time budgets against a real waiting HTTP service."""
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.config import AppSettings
from app.core.errors import ProviderTimeoutError
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.provider_client import ProviderClient


@contextmanager
def waiting_model(phase):
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if phase != "headers":
                self.send_response(500 if phase == "error" else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.flush()
            entered.set()
            release.wait(3)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{0}".format(server.server_port), entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("task_type", [
    "word.smart_write", "word.smart_imitation", "word.document_review", "word.format_review",
    "excel.analysis", "excel.formula_assistant", "ppt.slide_assistant", "ppt.structure_review",
])
@pytest.mark.parametrize("access_method", ["direct_model", "workflow_platform"])
@pytest.mark.parametrize("phase", ["headers", "body", "error"])
def test_cancel_releases_model_connection_before_any_content(task_type, access_method, phase):
    coordinator = LongTaskCoordinator(max_running=1)
    finished = threading.Event()
    with waiting_model(phase) as (url, entered):
        def runner(snapshot, control):
            try:
                if task_type == "word.format_review" and access_method == "workflow_platform":
                    return ProviderClient(AppSettings())._post_workflow_format_semantics(
                        "classify_role", "cancel-before-content", {},
                        {"accessMethod": access_method, "providerBaseUrl": url, "apiKey": "test"},
                        timeout_seconds=2, progress_callback=control,
                    )
                return ProviderClient(AppSettings()).post_task(
                    task_type, "cancel-before-content", {}, "任务内容", timeout_seconds=2,
                    task_auth={"accessMethod": access_method, "providerBaseUrl": url,
                               "apiKey": "test", "modelName": "test"},
                    progress_callback=control,
                )
            finally:
                finished.set()

        coordinator.submit(
            job_id="cancel-before-content", trace_id="cancel-before-content", task_type=task_type,
            runner=runner, snapshot={}, failure_code="FAILED", failure_message="failed",
            allow_running_cancel=True,
        )
        assert entered.wait(1)
        if task_type == "word.format_review" and access_method == "workflow_platform" and phase == "error":
            assert finished.wait(0.5), "HTTP failure must not wait for a response body"
            assert coordinator.wait("cancel-before-content", task_type=task_type)["status"] == "failed"
            return
        coordinator.request_cancel("cancel-before-content", task_type=task_type)
        assert finished.wait(0.5), "cancel must close the connection before model response/timeout"
        job = coordinator.wait("cancel-before-content", task_type=task_type)
        assert job["status"] == "cancelled"
        assert not job.get("result")
        assert coordinator.diagnostics()["runningCount"] == 0


def test_format_image_upload_keeps_task_cancel_control(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic test image")
    coordinator = LongTaskCoordinator(max_running=1)
    finished = threading.Event()
    with waiting_model("headers") as (url, entered):
        def runner(snapshot, control):
            try:
                return ProviderClient(AppSettings()).format_semantics(
                    "suggest_figure_caption", "cancel-image-upload", {"image_files": [{"path": str(image)}]},
                    "任务内容", task_auth={"accessMethod": "workflow_platform", "providerBaseUrl": url,
                                             "apiKey": "test"}, progress_callback=control,
                )
            finally:
                finished.set()

        coordinator.submit(
            job_id="cancel-image-upload", trace_id="cancel-image-upload", task_type="word.format_review",
            runner=runner, snapshot={}, failure_code="FAILED", failure_message="failed",
            allow_running_cancel=True,
        )
        assert entered.wait(1)
        coordinator.request_cancel("cancel-image-upload", task_type="word.format_review")
        assert finished.wait(0.5), "image upload must remain cancellable before response headers"
        job = coordinator.wait("cancel-image-upload", task_type="word.format_review")
        assert job["status"] == "cancelled"


@pytest.mark.parametrize("access_method", ["direct_model", "workflow_platform"])
@pytest.mark.parametrize("compatibility_retry", [False, True])
def test_headers_and_body_share_one_total_request_timeout(access_method, compatibility_retry):
    attempts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            attempts.append(1)
            time.sleep(0.15)
            retry = compatibility_retry and len(attempts) == 1
            self.send_response(400 if retry else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if retry:
                self.wfile.write(b'{"error":{"message":"response_format is not supported"}}')
                return
            time.sleep(0.15)
            try:
                self.wfile.write(json.dumps({"answer": "结果", "choices": [
                    {"message": {"content": "结果"}}
                ]}).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(ProviderTimeoutError):
            ProviderClient(AppSettings()).post_task(
                "word.smart_write", "total-request-budget", {}, "任务内容", timeout_seconds=0.25,
                task_auth={"accessMethod": access_method,
                           "providerBaseUrl": "http://127.0.0.1:{0}".format(server.server_port),
                           "apiKey": "test", "modelName": "test"},
                response_format={"type": "json_object"} if compatibility_retry else None,
                allow_response_format_fallback=compatibility_retry,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_continuously_dripping_headers_cannot_extend_task_timeout():
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                for byte in b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n":
                    if release.wait(0.02):
                        return
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    coordinator = LongTaskCoordinator(max_running=1)
    try:
        def runner(snapshot, control):
            return ProviderClient(AppSettings()).post_task(
                "word.smart_write", "dripping-headers", {}, "任务内容", timeout_seconds=0.2,
                task_auth={"accessMethod": "direct_model",
                           "providerBaseUrl": "http://127.0.0.1:{0}".format(server.server_port),
                           "apiKey": "test", "modelName": "test"},
                progress_callback=control,
            )

        coordinator.submit(
            job_id="dripping-headers", trace_id="dripping-headers", task_type="word.smart_write",
            runner=runner, snapshot={}, failure_code="FAILED", failure_message="failed",
            safe_failure_codes={"PROVIDER_TIMEOUT"},
        )
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            job = coordinator.get("dripping-headers", task_type="word.smart_write")
            if job["status"] == "failed":
                break
            time.sleep(0.01)
        assert job["status"] == "failed", "HTTP bytes must not restart the total timeout"
        assert job["error"]["code"] == "PROVIDER_TIMEOUT"
        assert coordinator.diagnostics()["runningCount"] == 0
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
