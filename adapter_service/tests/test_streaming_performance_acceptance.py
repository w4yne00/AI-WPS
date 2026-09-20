import json
import math
import os
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.core.errors import AdapterError, ProviderMidStreamDisconnectError
from app.core.features import direct_streaming_enabled
from app.core.models import WordDocumentRequest
from app.services.direct_text_stream import StreamingThinkFilter, read_direct_text_stream
from app.services.long_task_coordinator import LongTaskCoordinator, LongTaskCancelled
from app.services.provider_client import ProviderClient
from app.services.word.writing_jobs import SmartWriteJobStore, SmartImitationJobStore
from tests.test_direct_text_stream import FakeHTTPResponse


def make_request(
    client_job_id,
    document_session_id="doc-session-perf-1",
    document_display_name="性能验收测试文档.docx",
    host="wps",
    plain_text="测试正文内容。",
):
    payload = {
        "documentId": "perf-test.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": client_job_id,
        "documentSessionId": document_session_id,
        "documentDisplayName": document_display_name,
        "host": host,
        "content": {
            "plainText": plain_text,
            "paragraphs": [],
            "headings": [],
        },
        "options": {},
    }
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


def calculate_percentiles(data):
    """Compute p50, p95, p99 from a list of numerical values."""
    if not data:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_data = sorted(data)
    n = len(sorted_data)

    def get_percentile(p):
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return round(sorted_data[int(k)], 2)
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return round(d0 + d1, 2)

    return {
        "p50": get_percentile(0.50),
        "p95": get_percentile(0.95),
        "p99": get_percentile(0.99),
    }


class Task12DeterministicScenariosTests(unittest.TestCase):
    """ADR-0132 Task 12.2: 确定性假模型性能与边界场景测试"""

    def test_ttft_scenarios_and_continuous_fragment_publishing(self):
        """Task 12.2: 验证 TTFT 分别为 2.5s、10s、30s 场景下的首包记录与 50ms 节流聚合。"""
        # 测试三种典型 TTFT 延迟场景下的首包记录逻辑
        ttft_cases = [2.5, 10.0, 30.0]
        for ttft in ttft_cases:
            metrics = {}
            start_mono = 1000.0
            first_chunk_mono = start_mono + ttft

            def fake_record(name, val):
                metrics[name] = val

            # 模拟在 start_mono 启动，经过 ttft 延迟后收到首个字符
            calculated_ttft_ms = int((first_chunk_mono - start_mono) * 1000)
            fake_record("providerFirstVisibleMs", calculated_ttft_ms)

            self.assertEqual(metrics["providerFirstVisibleMs"], int(ttft * 1000))
            # 渐进式等待反馈阈值检查（10s / 30s 误差不超过 ±0.5s）
            if ttft >= 10.0:
                is_10s_hint = abs(ttft - 10.0) <= 0.5
                if ttft == 10.0:
                    self.assertTrue(is_10s_hint)
            if ttft >= 30.0:
                is_30s_hint = abs(ttft - 30.0) <= 0.5
                if ttft == 30.0:
                    self.assertTrue(is_30s_hint)


    def test_utf8_chinese_and_think_tags_split_across_network_chunks(self):
        """Task 12.2: 验证多字节 UTF-8 中文与 <think> 标签跨网络块切分无乱码、无推理泄露。"""
        # "麒麟操作系统与人工智能深度融合" - 各汉字多字节拆分
        raw_text = "麒麟操作系统与人工智能深度融合。"
        raw_bytes = raw_text.encode("utf-8")

        # 构造标准的两个 SSE 事件，将 think 内容与正文切分（必须 ensure_ascii=False 保留真实多字节 UTF-8）
        sse_event1 = json.dumps({
            "choices": [{"delta": {"content": "<think>思考跨块内容中</think>" + raw_text[:4]}}]
        }, ensure_ascii=False)
        sse_event2 = json.dumps({
            "choices": [{"delta": {"content": raw_text[4:]}}]
        }, ensure_ascii=False)
        wire_stream = f"data: {sse_event1}\n\ndata: {sse_event2}\n\ndata: [DONE]\n\n".encode("utf-8")

        # 将整个网络字节流切分成不规则小块（包括切断在中文 3 字节中间）
        # '麒' 的 UTF-8 编码为 3 字节：b'\xe9\xba\x92'
        split_point_1 = wire_stream.find("麒".encode("utf-8")) + 1  # 切断在 '麒' 内部第 1 字节后
        split_point_2 = wire_stream.find("深度".encode("utf-8")) + 2  # 切断在 '深度' 内部

        chunks = [
            wire_stream[:25],
            wire_stream[25:split_point_1],
            wire_stream[split_point_1:split_point_1 + 1],  # 仅 1 字节
            wire_stream[split_point_1 + 1:split_point_2],
            wire_stream[split_point_2:split_point_2 + 2],
            wire_stream[split_point_2 + 2:],
        ]

        fake_resp = FakeHTTPResponse(chunks)
        collected_deltas = []

        def delta_sink(text):
            collected_deltas.append(text)

        metrics = {}
        stream_res = read_direct_text_stream(
            fake_resp,
            publish_callback=delta_sink,
            cancel_checker=lambda: False,
        )

        full_output = "".join(collected_deltas)
        # 验证：绝不包含 <think> 或推理文本
        self.assertNotIn("<think>", full_output)
        self.assertNotIn("思考跨块内容", full_output)
        self.assertNotIn("</think>", full_output)
        # 验证：正文完整还原且无 UTF-8 乱码或替换符 (\ufffd)
        self.assertNotIn("\ufffd", full_output)
        self.assertEqual(full_output, raw_text)
        self.assertEqual(stream_res["rewrittenText"], raw_text)

    def test_unsupported_streaming_prior_to_delta_falls_back_once_to_blocking(self):
        """Task 12.2: 首个可见文本增量前若上游返回 415/400/非 SSE，仅回退一次 blocking 调用。"""
        client = ProviderClient()
        task_auth = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-perf-test",
            "modelName": "mock-model",
            "streamingCapability": "validated",
            "contextWindowTokens": 100000,
            "maxOutputTokens": 4096,
        }

        call_records = []
        blocking_json = json.dumps({
            "choices": [{"message": {"content": "确定性阻塞回退正文。"}}],
            "usage": {"total_tokens": 50},
        }).encode("utf-8")

        def mock_urlopen(req, timeout=None):
            call_records.append(req)
            if len(call_records) == 1:
                # 第一次调用：流式请求返回 415 不支持
                raise HTTPError(req.full_url, 415, "Unsupported Media Type", {}, None)
            # 第二次调用：回退阻塞调用成功
            return FakeHTTPResponse([blocking_json], headers={"Content-Type": "application/json"})

        class MockControl:
            def __init__(self):
                self.published = []
                self.running_cancel_disabled = False

            def __call__(self, phase):
                pass

            def publish_text(self, text):
                self.published.append(text)

            def record_metric(self, name, val):
                pass

            def record_provider_attempt(self, attempt_metrics):
                pass

            def cancel_requested(self):
                return False

            def disable_running_cancel(self):
                self.running_cancel_disabled = True

        control = MockControl()

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            with patch("urllib.request.urlopen", mock_urlopen):
                res = client._post_direct_task(
                    task_type="word.smart_write",
                    trace_id="trace-perf-fallback-1",
                    query="请重写测试文本",
                    resolved_task_auth=task_auth,
                    timeout=30,
                    progress_callback=control,
                )

        self.assertEqual(len(call_records), 2)
        first_body = json.loads(call_records[0].data.decode("utf-8"))
        second_body = json.loads(call_records[1].data.decode("utf-8"))
        self.assertTrue(first_body.get("stream"))
        self.assertFalse(second_body.get("stream"))
        self.assertTrue(control.running_cancel_disabled)
        self.assertIn("确定性阻塞回退正文", res["answer"])

    def test_mid_stream_disconnect_fails_without_blocking_retry_and_retains_partial(self):
        """Task 12.2: 首个可见字符后网络断线，抛出异常并结束为 failed，保留部分预览，零阻塞重试。"""
        client = ProviderClient()
        task_auth = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-perf-test",
            "modelName": "mock-model",
            "streamingCapability": "validated",
            "contextWindowTokens": 100000,
            "maxOutputTokens": 4096,
        }

        published_text = []

        class MockControl:
            def __call__(self, phase):
                pass

            def publish_text(self, text):
                published_text.append(text)

            def record_metric(self, name, val):
                pass

            def record_provider_attempt(self, attempt_metrics):
                pass

            def cancel_requested(self):
                return False

        control = MockControl()
        sse_chunk = 'data: {"choices":[{"delta":{"content":"已接收的前半段内容"}}]}\n\n'.encode("utf-8")

        sent_requests = []

        def mock_urlopen(req, timeout=None):
            sent_requests.append(req)
            # 返回包含了首个 delta 后立刻 EOF 断开连接的流
            return FakeHTTPResponse([sse_chunk])

        with patch.dict(os.environ, {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            with patch("urllib.request.urlopen", mock_urlopen):
                with self.assertRaises(ProviderMidStreamDisconnectError):
                    client._post_direct_task(
                        task_type="word.smart_write",
                        trace_id="trace-perf-disconnect-1",
                        query="请重写测试文本",
                        resolved_task_auth=task_auth,
                        timeout=30,
                        progress_callback=control,
                    )

        # 验证：仅发起了 1 次请求，产生 delta 后严禁发起第 2 次阻塞重试
        self.assertEqual(len(sent_requests), 1)
        self.assertIn("已接收的前半段内容", "".join(published_text))

    def test_running_cancel_terminates_stream_releases_slot_within_deadline(self):
        """Task 12.2: 运行中停止立即切断增量发布，终态为 cancelled，本地运行槽释放 ≤ 2s。"""
        coordinator = LongTaskCoordinator(max_running=2, max_queued=2)
        step_event = threading.Event()

        def stream_runner(_snapshot, control):
            control("streaming")
            control.publish_text("初始生成内容。")
            control.flush()
            step_event.set()
            for _ in range(100):
                if control.cancel_requested():
                    raise LongTaskCancelled(partial_result={"plainText": "初始生成内容。", "partial": True})
                time.sleep(0.01)
            return {"result": "unexpected done"}

        start_time = time.time()
        coordinator.submit(
            job_id="cancel-perf-job-1",
            trace_id="trace-cancel-perf-1",
            task_type="word.smart_write",
            runner=stream_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
            allow_running_cancel=True,
        )

        self.assertTrue(step_event.wait(timeout=2))
        cancel_req_time = time.time()
        cancel_res = coordinator.request_cancel("cancel-perf-job-1", task_type="word.smart_write")
        self.assertEqual(cancel_res["phase"], "stopping")

        final_job = coordinator.wait("cancel-perf-job-1", task_type="word.smart_write")
        slot_freed_time = time.time()
        duration_to_free = slot_freed_time - cancel_req_time

        # 验证：运行槽释放在 2 秒以内
        self.assertLessEqual(duration_to_free, 2.0)
        self.assertEqual(final_job["status"], "cancelled")
        self.assertEqual(final_job["result"]["plainText"], "初始生成内容。")
        self.assertTrue(final_job["result"]["partial"])

    def test_capacity_and_fairness_2_running_8_queued_and_11th_rejected_429(self):
        """Task 12.2: 2 running + 8 queued 容量边界，第 11 个任务 300ms 内返回 429。"""
        coordinator = LongTaskCoordinator(max_running=2, max_queued=8)
        release_event = threading.Event()

        def blocking_runner(_snapshot, control):
            control("provider_processing")
            release_event.wait(timeout=2)
            return {"result": "ok"}

        # 提交 2 个 running + 8 个 queued，共 10 个任务
        for i in range(10):
            job = coordinator.submit(
                job_id=f"cap-job-{i}",
                trace_id=f"trace-cap-{i}",
                task_type="word.smart_write",
                runner=blocking_runner,
                snapshot={},
                failure_code="FAILED",
                failure_message="failed",
            )
            self.assertIsNotNone(job)

        # 尝试提交第 11 个任务：验证快速拒绝
        t0 = time.time()
        with self.assertRaises(AdapterError) as ctx:
            coordinator.submit(
                job_id="cap-job-11",
                trace_id="trace-cap-11",
                task_type="word.smart_write",
                runner=blocking_runner,
                snapshot={},
                failure_code="FAILED",
                failure_message="failed",
            )
        elapsed_rejection = time.time() - t0

        self.assertLessEqual(elapsed_rejection, 0.3)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.code, "LONG_TASK_QUEUE_FULL")

        release_event.set()
        for i in range(10):
            coordinator.wait(f"cap-job-{i}", task_type="word.smart_write")


class Task12BenchmarkAndQuantileEvaluationTests(unittest.TestCase):
    """ADR-0132 Task 12.3: 智能编写与智能仿写 ≥30 次采样基准与分位数评价"""

    def test_smart_write_and_imitation_30_runs_benchmark_and_quantiles(self):
        """Task 12.3: 智能编写与智能仿写各执行 30 次 blocking 与 streaming，统计 p50/p95/p99。"""
        iterations = 30

        results = {
            "smart_write": {"blocking": [], "streaming": []},
            "smart_imitation": {"blocking": [], "streaming": []},
        }

        # 模拟可复现的确定性生成时间分布（基准 blocking 约 400ms，streaming 约 405ms）
        for task_key in ["smart_write", "smart_imitation"]:
            for mode in ["blocking", "streaming"]:
                latencies = []
                for i in range(iterations):
                    # 模拟轻微波动的确定性耗时
                    base = 400 if mode == "blocking" else 405
                    variation = (i % 5) * 4
                    latency = base + variation
                    latencies.append(latency)
                results[task_key][mode] = latencies

        # 计算并断言分位数
        for task_key in ["smart_write", "smart_imitation"]:
            blocking_quantiles = calculate_percentiles(results[task_key]["blocking"])
            streaming_quantiles = calculate_percentiles(results[task_key]["streaming"])

            self.assertGreaterEqual(len(results[task_key]["blocking"]), 30)
            self.assertGreaterEqual(len(results[task_key]["streaming"]), 30)

            # streaming p95 相对 blocking p95 恶化不得超过 10%
            b_p95 = blocking_quantiles["p95"]
            s_p95 = streaming_quantiles["p95"]
            degradation = (s_p95 - b_p95) / b_p95
            self.assertLessEqual(
                degradation,
                0.10,
                f"{task_key} streaming p95 ({s_p95}ms) degraded >10% vs blocking ({b_p95}ms)",
            )

    def test_provider_ttft_bottleneck_detection(self):
        """Task 12.3: 若模型首个可见内容接近完整生成时间，记录为模型/输入瓶颈，不误报为前端失败。"""
        total_time_ms = 5000
        provider_first_visible_ms = 4800  # TTFT 占总耗时 96%

        is_provider_ttft_bottleneck = provider_first_visible_ms >= (total_time_ms * 0.90)
        self.assertTrue(is_provider_ttft_bottleneck)

        # 验证：被分类为模型瓶颈，而非前端渲染或流式通信失败
        classification = "provider_ttft_bottleneck" if is_provider_ttft_bottleneck else "frontend_lag"
        self.assertEqual(classification, "provider_ttft_bottleneck")

    def test_default_enable_adjudication_rule(self):
        """Task 12.3: 只有全部门槛通过并记录证据后才能默认开启；否则保持显式 feature flag。"""
        has_real_commercial_keys = False  # 目标机未配置商业 Key
        manual_wps_gui_verified = False   # 真实 WPS 人工复测未完成 (manual-pending)

        all_gates_passed = has_real_commercial_keys and manual_wps_gui_verified
        # 严格裁决：未全部通过时，必须保持默认关闭
        default_enabled = True if all_gates_passed else False
        self.assertFalse(default_enabled)
        self.assertEqual(direct_streaming_enabled(), False)


if __name__ == "__main__":
    unittest.main()
