"""Public generation APIs distinguish new actions from transport retries."""
import base64
import json
import time
from io import BytesIO

import pytest

from app.services.long_task_coordinator import LongTaskCoordinator
from app.services import task_history
from app.services.task_history import TaskHistoryStore
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.material_outline import PptMaterialOutlineCoordinator
from app.services.ppt.template_page import PptTemplatePageCoordinator
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore
from app.services.ppt.structure_review import PptStructureReviewer
from app.services.ppt.structure_review_jobs import PptStructureReviewJobStore
from tests.test_ppt_slide_assistant import RecordingPptProvider, RecordingPptDocumentProvider
from app.services.ppt.document_files import PptDocumentFileStore
from tests.test_ppt_structure_review import RecordingProvider, request_payload
from tests.test_ppt_material_outline_api import build_docx
from tests.test_ppt_template_page_api import SAMPLE_PAGE_RESPONSE


@pytest.fixture(params=['fastapi', 'standalone'])
def api(request, monkeypatch):
    if request.param == 'fastapi':
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api import ppt
        client = TestClient(app)

        def invoke(method, path, payload=None):
            response = client.request(method, path, json=payload)
            return response.status_code, response.json()

        def install(name, value):
            monkeypatch.setattr(ppt, name, value)
    else:
        import standalone_adapter as standalone

        def invoke(method, path, payload=None):
            raw = json.dumps(payload).encode() if payload is not None else b''
            result = {}
            handler = object.__new__(standalone.Handler)
            handler.path = path
            handler.headers = {'Content-Length': str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: result.update(status=status, body=body)
            getattr(handler, 'do_' + method)()
            return result['status'], result['body']

        names = {'ppt_slide_jobs': 'PPT_SLIDE_ASSISTANT_JOB_STORE',
                 'ppt_structure_review_jobs': 'PPT_STRUCTURE_REVIEW_JOB_STORE',
                 'ppt_material_outline': 'PPT_MATERIAL_OUTLINE_COORDINATOR',
                 'ppt_template_page': 'PPT_TEMPLATE_PAGE_COORDINATOR'}

        def install(name, value):
            monkeypatch.setattr(standalone, names[name], value)
    return invoke, install


@pytest.fixture(params=['slide-assistant', 'document-summary', 'structure-review', 'material-outline', 'template-page'])
def generation(request, api, tmp_path, monkeypatch):
    invoke, install = api
    kind = request.param
    coordinator = LongTaskCoordinator()
    monkeypatch.setattr(task_history, '_TASK_HISTORY_STORE', TaskHistoryStore(tmp_path / 'history'))
    payload = {'documentSessionId': 'identity-session', 'clientJobId': 'identity-first'}
    calls = []
    if kind in ('slide-assistant', 'document-summary'):
        provider = RecordingPptDocumentProvider() if kind == 'document-summary' else RecordingPptProvider()
        files = PptDocumentFileStore(root_dir=tmp_path / 'uploads')
        jobs = PptSlideAssistantJobStore(PptSlideAssistant(provider_client=provider, document_file_store=files), coordinator)
        install('ppt_slide_jobs', jobs)
        calls = provider.calls
        payload.update(presentationId='deck.pptx', slide={'index': 1, 'title': '进展', 'textBlocks': ['方案已完成']}, userInstruction='总结进展')
    elif kind == 'structure-review':
        provider = RecordingProvider()
        jobs = PptStructureReviewJobStore(PptStructureReviewer(provider_client=provider), coordinator)
        install('ppt_structure_review_jobs', jobs)
        calls = provider.calls
        payload.update(request_payload(document_session_id='identity-session', client_job_id='identity-first'))
    else:
        store = PptMaterialStore(tmp_path / 'ppt', word_base_dir=tmp_path / 'word', excel_base_dir=tmp_path / 'excel')
        if kind == 'material-outline':
            store.import_material('identity-session', 'full:/deck.pptx', '资料.docx', base64.b64encode(build_docx()).decode())
            jobs = PptMaterialOutlineCoordinator(store=store, coordinator=coordinator)
            install('ppt_material_outline', jobs)
            payload.update(slideCount=3)
            answer = json.dumps({'schemaVersion': 'ppt.material_outline.v1', 'audience': '高管', 'slideCount': 3, 'slides': [
                {'pageIndex': i, 'pageRole': role, 'title': '进展', 'keyPoints': [], 'missingItems': [], 'fragmentIds': []}
                for i, role in [(1, 'cover'), (2, 'content'), (3, 'backcover')]]})
        else:
            jobs = PptTemplatePageCoordinator(store=store, coordinator=coordinator)
            install('ppt_template_page', jobs)
            payload.update(pageIndex=2, pageRole='content', outlineTitle='核心架构设计')
            answer = SAMPLE_PAGE_RESPONSE

        def model(*args, **kwargs):
            calls.append('model')
            return answer
        monkeypatch.setattr(jobs, '_call_provider_model', model)
    if kind == 'document-summary':
        payload.update(sourceMode='document', requestedSlideCount=10)
        original_invoke = invoke
        uploaded = set()

        def invoke(method, path, data=None):
            if method == 'POST' and data and data['clientJobId'] not in uploaded:
                content = b'# Project\n\nCompleted project design.'
                staged = files.store('project.md', 'text/markdown', len(content), base64.b64encode(content).decode())
                data['fileToken'] = staged['fileToken']
                uploaded.add(data['clientJobId'])
            return original_invoke(method, path, data)
        kind = 'slide-assistant'
    return invoke, '/ppt/' + kind + '/jobs', payload, calls


def wait_completed(invoke, path, session):
    for _ in range(200):
        status, body = invoke('GET', path + '?documentSessionId=' + session)
        assert status == 200, body
        if body['data']['status'] in ('completed', 'failed'):
            assert body['data']['status'] == 'completed', body
            return body['data']
        time.sleep(.01)
    pytest.fail('generation did not complete')


def model_count(calls):
    return sum(1 for call in calls if not isinstance(call, dict) or 'snapshotTaskType' not in call)


def test_new_action_runs_again_but_retry_and_result_reads_do_not(generation):
    invoke, path, payload, calls = generation
    for job_id, expected in [('identity-first', 1), ('identity-second', 2)]:
        payload['clientJobId'] = job_id
        status, body = invoke('POST', path, payload)
        assert status == 200, body
        assert body['data']['jobId'] == job_id
        status, in_flight_retry = invoke('POST', path, payload)
        assert status == 200, in_flight_retry
        assert in_flight_retry['data']['jobId'] == job_id
        wait_completed(invoke, path + '/' + job_id, payload['documentSessionId'])
        status, retry = invoke('POST', path, payload)
        assert status == 200, retry
        assert retry['data']['jobId'] == job_id
        wait_completed(invoke, path + '/' + job_id, payload['documentSessionId'])
        assert model_count(calls) == expected


def test_same_id_cannot_return_another_document_result(generation):
    invoke, path, payload, calls = generation
    status, body = invoke('POST', path, payload)
    assert status == 200, body
    wait_completed(invoke, path + '/' + payload['clientJobId'], payload['documentSessionId'])
    payload['documentSessionId'] = 'another-document'
    status, body = invoke('POST', path, payload)
    assert status == 409, body
    assert model_count(calls) == 1
