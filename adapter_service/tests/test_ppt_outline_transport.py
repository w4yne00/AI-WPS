"""Exercise outline transport against a real local HTTP service, not a mocked opener."""
import json
import threading
import pytest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.core.config import AppSettings
from app.services.provider_client import ProviderClient, record_provider_debug, get_last_provider_debug


@contextmanager
def model_server(streaming=True, status=200, delay=0, header_delay=0):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if header_delay:
                import time
                time.sleep(header_delay)
            self.send_response(status)
            if streaming and received[-1].get('stream'):
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                if delay:
                    import time
                    time.sleep(delay)
                for delta in ({'reasoning_content': 'private reasoning'}, {'content': '{"slides":[]}'}):
                    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\n').encode())
                    self.wfile.flush()
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            else:
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"{\\"slides\\":[]}"},"finish_reason":"stop"}]}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d' % server.server_port, received
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


def test_outline_streams_single_request_and_does_not_publish_unvalidated_json():
    phases, published = [], []
    class Control:
        def __call__(self, phase): phases.append(phase)
        def publish_text(self, text): published.append(text)
        def cancel_requested(self): return False
        def set_cancel_callback(self, cb): self.cancel_callback = cb
        def clear_cancel_callback(self, cb=None): self.cancel_callback = None
    with model_server() as (url, received):
        provider = ProviderClient(AppSettings())
        body = provider.post_task('ppt.material_outline', 'outline-stream', {}, '完整材料',
            task_auth={'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test','directStreamingEnabled':True},
            progress_callback=Control())
    assert received[0]['stream'] is True
    assert received[0]['max_tokens'] == 8000
    assert body['answer'] == '{"slides":[]}'
    assert 'provider_reasoning' in phases
    assert published == []
    assert len(received) == 1


def test_outline_accepts_json_from_stream_request_without_generating_twice():
    with model_server(streaming=False) as (url, received):
        body = ProviderClient(AppSettings()).post_task('ppt.material_outline', 'outline-json', {}, '全文',
            task_auth={'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test','maxOutputTokens':12000})
    assert received[0]['stream'] is True
    assert received[0]['max_tokens'] == 12000
    assert len(received) == 1
    assert body['answer'] == '{"slides":[]}'


def test_timeout_diagnostics_retain_redacted_request_shape():
    record_provider_debug({'traceId':'outline-debug','taskType':'ppt.material_outline',
        'request':{'body':{'model':'test','messages':[{'role':'user','content':'私密正文'}],'stream':True,'max_tokens':8000}}})
    record_provider_debug({'traceId':'outline-debug','taskType':'ppt.material_outline','error':{'type':'TimeoutError','message':'timeout'}})
    debug = get_last_provider_debug()
    assert debug['request']['queryLength'] == 4
    assert debug['request']['stream'] is True
    assert debug['request']['maxOutputTokens'] == 8000
    assert '私密正文' not in json.dumps(debug, ensure_ascii=False)


def test_outline_uses_submitted_prompt_snapshot_in_the_actual_request():
    from app.services.ppt.material_outline import PptMaterialOutlineCoordinator
    with model_server(streaming=False) as (url, received):
        provider = ProviderClient(AppSettings())
        coordinator = PptMaterialOutlineCoordinator(provider=provider)
        coordinator._call_provider_model('已提交提示词', '全文', task_auth={
            'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test'})
    assert received[0]['messages'][0]['content'] == '已提交提示词'


@pytest.mark.parametrize("after_headers", ["headers", "reasoning", "partial", "error"])
def test_outline_cancel_interrupts_real_waiting_socket(after_headers):
    from app.services.long_task_coordinator import LongTaskCoordinator
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    class SlowHandler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if after_headers in ("reasoning", "partial"):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                delta = {'reasoning_content':'private'} if after_headers == 'reasoning' else {'content':'{"unvalidated":'}
                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\n').encode())
                self.wfile.flush()
            else:
                if after_headers == 'error':
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', '100')
                    self.end_headers()
                    self.wfile.flush()
                entered.set()
            release.wait(3)
    server = ThreadingHTTPServer(('127.0.0.1',0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    coordinator = LongTaskCoordinator(max_running=1)
    provider = ProviderClient(AppSettings())
    def runner(snapshot, control):
        class Progress:
            def __call__(self, phase):
                control(phase)
                if phase == ('streaming' if after_headers == 'partial' else 'provider_reasoning'): entered.set()
            def __getattr__(self, name): return getattr(control, name)
        try:
            return provider.post_task('ppt.material_outline','cancel-socket',{},'全文', task_auth={
                'accessMethod':'direct_model','providerBaseUrl':'http://127.0.0.1:%d'%server.server_port,
                'apiKey':'test','modelName':'test'},progress_callback=Progress())
        finally:
            finished.set()
    try:
        coordinator.submit(job_id='cancel-socket',trace_id='cancel-socket',task_type='ppt.material_outline',
            runner=runner,snapshot={},failure_code='FAILED',failure_message='failed',allow_running_cancel=True)
        assert entered.wait(2)
        if after_headers == 'reasoning':
            assert coordinator.get('cancel-socket',task_type='ppt.material_outline')['phase'] == 'provider_reasoning'
        coordinator.request_cancel('cancel-socket',task_type='ppt.material_outline')
        assert finished.wait(1), 'cancel must release the waiting connection before the server responds'
        result=coordinator.wait('cancel-socket',task_type='ppt.material_outline')
        assert result['status']=='cancelled'
        assert not result.get('result'), 'cancelled outlines must not publish unvalidated JSON'
    finally:
        release.set();server.shutdown();server.server_close();thread.join(2)


@pytest.mark.parametrize('status', [400, 422])
def test_outline_does_not_repeat_a_rejected_generation(status):
    from app.core.errors import AdapterError
    with model_server(streaming=False, status=status) as (url, received):
        with pytest.raises(AdapterError):
            ProviderClient(AppSettings()).post_task('ppt.material_outline', 'outline-http-error', {}, '全文',
                task_auth={'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test'})
    assert len(received) == 1


def test_cancelled_outline_does_not_return_a_partial_json_document():
    from app.services.long_task_coordinator import LongTaskCancelled
    class Control:
        cancelled = False
        def __call__(self, phase):
            if phase == 'streaming': self.cancelled = True
        def cancel_requested(self): return self.cancelled
        def set_cancel_callback(self, callback): pass
        def clear_cancel_callback(self, callback=None): pass
    with model_server() as (url, received):
        with pytest.raises(LongTaskCancelled) as error:
            ProviderClient(AppSettings()).post_task('ppt.material_outline','cancel-partial',{},'全文',
                task_auth={'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test'},progress_callback=Control())
    assert error.value.partial_result is None


def test_outline_first_output_timing_is_not_counted_twice():
    from app.services.long_task_coordinator import LongTaskCoordinator
    jobs = LongTaskCoordinator()
    with model_server(delay=0.03) as (url, received):
        provider = ProviderClient(AppSettings())
        def runner(snapshot, control):
            return provider.post_task('ppt.material_outline','timing-once',{},'全文',task_auth={
                'accessMethod':'direct_model','providerBaseUrl':url,'apiKey':'test','modelName':'test'},progress_callback=control)
        jobs.submit(job_id='timing-once',trace_id='timing-once',task_type='ppt.material_outline',runner=runner,
                    snapshot={},failure_code='FAILED',failure_message='failed')
        result=jobs.wait('timing-once',task_type='ppt.material_outline')
    assert result['status'] == 'completed'
    timing=get_last_provider_debug('timing-once')['performance']['providerFirstVisibleMs']
    assert timing > 0
    assert result['metrics']['providerFirstVisibleMs'] == timing


def test_outline_connection_and_stream_share_one_total_wait_budget():
    from app.core.errors import ProviderTimeoutError
    with model_server(header_delay=0.15, delay=0.15) as (url, received):
        with pytest.raises(ProviderTimeoutError):
            ProviderClient(AppSettings())._post_direct_task('ppt.material_outline','total-deadline','全文',
                {'providerBaseUrl':url,'apiKey':'test','modelName':'test'},timeout=0.25)
