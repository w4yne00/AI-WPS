import json
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from tests.test_word_material_import import build_docx, upload_payload


def test_composer_api_resolves_sources_and_preserves_missing_information():
    client = TestClient(app)
    material = client.post('/word/materials', json=upload_payload(build_docx())).json()['data']
    request = dict(materialId=material['materialId'], documentSessionId='doc-session-1',
                   clientJobId='composer-test-0001', sectionTitle='实施安排', instruction='整理责任和时间')
    answer = {'paragraphs': [{'text': '信息化处负责。', 'fragmentIds': ['frag-5'],
                               'missingItems': ['完成时间']}]}
    with patch('app.services.provider_client.ProviderClient.resolve_task_auth', return_value={'providerBaseUrl':'https://model.invalid','apiKey':'test'}), patch('app.services.provider_client.ProviderClient.post_task', return_value={'answer': json.dumps(answer)}):
        response = client.post('/word/material-composer/jobs', json=request)
        assert response.status_code == 200, response.text
        job_id = response.json()['data']['jobId']
        for _ in range(100):
            job = client.get('/word/material-composer/jobs/' + job_id, params={'documentSessionId':'doc-session-1'}).json()['data']
            if job['status'] in ('completed','failed'):
                break
            time.sleep(.01)
        assert job['status'] == 'completed', job
        result = job['result']
        assert '〔待补充：完成时间〕' in result['plainText']
        assert result['paragraphs'][0]['sources'][0]['quote'] == '信息化处'
        assert result['paragraphs'][0]['sources'][0]['fileName'] == '资料.docx'
        assert client.get('/word/material-composer/jobs/' + job_id, params={'documentSessionId':'other'}).status_code == 404
        assert client.post('/word/material-composer/jobs', json=request).json()['data']['jobId'] == job_id
        request['instruction'] = 'changed'
        assert client.post('/word/material-composer/jobs', json=request).status_code == 409


def test_standalone_composer_creation_and_session_guard():
    import standalone_adapter as standalone
    from tests.test_word_material_import import _invoke_standalone
    imported = _invoke_standalone(standalone, 'do_POST', '/word/materials', upload_payload(build_docx()))
    material = imported['body']['data']
    payload = dict(materialId=material['materialId'], documentSessionId='other',
                   clientJobId='standalone-compose-0001', sectionTitle='范围', instruction='编写')
    response = _invoke_standalone(standalone, 'do_POST', '/word/material-composer/jobs', payload)
    assert response['status'] == 404
    assert response['body']['errors'][0]['code'] == 'MATERIAL_NOT_FOUND'


def test_over_budget_rejected_before_model_call():
    client = TestClient(app)
    material = client.post('/word/materials', json=upload_payload(build_docx())).json()['data']
    payload = dict(materialId=material['materialId'], documentSessionId='doc-session-1',
                   clientJobId='composer-budget-0001', sectionTitle='范围', instruction='编写' * 3000)
    with patch('app.services.provider_client.ProviderClient.resolve_task_auth', return_value={'providerBaseUrl':'https://model.invalid','apiKey':'test','contextWindowTokens':1000, 'maxOutputTokens':500}):
        response = client.post('/word/material-composer/jobs', json=payload)
    assert response.status_code == 413
    assert response.json()['errors'][0]['code'] == 'MODEL_INPUT_OVER_BUDGET'


def test_composer_api_rejects_oversized_body_before_parsing():
    response = TestClient(app).post(
        '/word/material-composer/jobs',
        content=b'{}',
        headers={
            'Content-Type': 'application/json',
            'Content-Length': str(64 * 1024 + 1),
        },
    )
    assert response.status_code == 413
    assert response.json()['errors'][0]['code'] == 'MATERIAL_COMPOSER_REQUEST_TOO_LARGE'


def test_standalone_composer_rejects_oversized_body_before_parsing():
    import standalone_adapter as standalone
    from tests.test_word_material_import import _invoke_standalone
    response = _invoke_standalone(
        standalone,
        'do_POST',
        '/word/material-composer/jobs',
        {},
        headers={'Content-Length': str(64 * 1024 + 1)},
    )
    assert response['status'] == 413
    assert response['body']['errors'][0]['code'] == 'MATERIAL_COMPOSER_REQUEST_TOO_LARGE'


def test_standalone_completed_result_and_cancel_are_session_isolated():
    import standalone_adapter as standalone
    from tests.test_word_material_import import _invoke_standalone
    import threading
    started, release = threading.Event(), threading.Event()
    def provider(*args, **kwargs):
        started.set()
        release.wait(3)
        return {'answer': json.dumps({'paragraphs':[{'text':'信息化处负责。', 'fragmentIds':['frag-5'],'missingItems':[]}]})}
    material = _invoke_standalone(standalone, 'do_POST', '/word/materials', upload_payload(build_docx()))['body']['data']
    payload = dict(materialId=material['materialId'], documentSessionId='doc-session-1', clientJobId='standalone-cancel-0001', sectionTitle='范围', instruction='编写')
    with patch('app.services.provider_client.ProviderClient.resolve_task_auth', return_value={'providerBaseUrl':'https://model.invalid','apiKey':'test'}), patch('app.services.provider_client.ProviderClient.post_task', side_effect=provider):
        response = _invoke_standalone(standalone, 'do_POST', '/word/material-composer/jobs', payload)
        assert response['status'] == 200, response
        assert started.wait(1)
        url = '/word/material-composer/jobs/' + response['body']['data']['jobId']
        assert _invoke_standalone(standalone, 'do_POST', url+'/cancel', {'documentSessionId':'other'})['status'] == 404
        cancelled = _invoke_standalone(standalone, 'do_POST', url+'/cancel', {'documentSessionId':'doc-session-1'})
        assert cancelled['status'] == 200
        release.set()
        for _ in range(100):
            job = _invoke_standalone(standalone, 'do_GET', url+'?documentSessionId=doc-session-1')['body']['data']
            if job['status'] == 'cancelled':
                break
            time.sleep(.01)
        assert job['status'] == 'cancelled'
        assert job.get('result') is None


def test_invalid_model_sources_never_become_completed_result():
    import uuid
    client = TestClient(app)
    material = client.post('/word/materials', json=upload_payload(build_docx())).json()['data']
    for paragraph in [
        {'text':'信息化处负责', 'fragmentIds':['invented'], 'missingItems':[]},
        {'text':'2027年投资100万元。', 'fragmentIds':[], 'missingItems':[]},
        {'text':'2027年投资100万元。', 'fragmentIds':[], 'missingItems':['时间']},
    ]:
        payload = dict(materialId=material['materialId'], documentSessionId='doc-session-1', clientJobId='invalid-'+uuid.uuid4().hex, sectionTitle='范围', instruction='编写')
        with patch('app.services.provider_client.ProviderClient.resolve_task_auth', return_value={'providerBaseUrl':'https://model.invalid','apiKey':'test'}), patch('app.services.provider_client.ProviderClient.post_task', return_value={'answer':json.dumps({'paragraphs':[paragraph]})}):
            job_id = client.post('/word/material-composer/jobs', json=payload).json()['data']['jobId']
            for _ in range(100):
                job = client.get('/word/material-composer/jobs/'+job_id, params={'documentSessionId':'doc-session-1'}).json()['data']
                if job['status'] in ('completed','failed'):
                    break
                time.sleep(.01)
            assert job['status'] == 'failed', job
            assert job['error']['code'] == 'MATERIAL_COMPOSER_INVALID_RESULT'
            assert job.get('result') is None


def test_composer_uses_its_own_model_configuration_and_system_prompt(tmp_path):
    from app.services.model_configurations import ModelConfigurationStore, ACCESS_DIRECT_MODEL
    from app.services.provider_client import ProviderClient
    from app.services.word.material_import import WordMaterialImportService
    from app.services.word.material_composer import MaterialComposerJobs
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.core.config import AppSettings
    from tests.test_direct_model_provider import FakeResponse
    config_path = tmp_path / 'adapter.json'
    config_path.write_text('{}')
    store = ModelConfigurationStore(config_path, tmp_path / 'keys')
    for task, model in [('word.smart_write','write-model'), ('word.material_composer','composer-model')]:
        config = store.create_configuration(task, task, ACCESS_DIRECT_MODEL, service_base_url='http://1.1.1.1:1111/v1', model_name=model, allow_direct=True)
        store.replace_api_key(config['id'], model+'-secret', allow_direct=True)
        store.activate_configuration(config['id'])
    provider = ProviderClient(AppSettings(), model_configuration_store=store)
    assert 'word.material_composer' in provider.build_task_api_key_status()
    materials = WordMaterialImportService()
    material = materials.import_material(upload_payload(build_docx()))
    jobs = MaterialComposerJobs(materials, provider, LongTaskCoordinator())
    captured = []
    def respond(request, *args, **kwargs):
        captured.append(json.loads(request.data))
        return FakeResponse({'choices':[{'message':{'content':json.dumps({'paragraphs':[{'text':'信息化处负责。', 'fragmentIds':['frag-5'], 'missingItems':[]}]})}}]})
    with patch('app.services.provider_client.urllib_request.urlopen', side_effect=respond):
        assert provider.validate_model_configuration(config['id'], 'validate-composer')['success'] is True
        job = jobs.start(dict(materialId=material['materialId'], documentSessionId='doc-session-1', clientJobId='own-model-0001', sectionTitle='范围', instruction='编写'), 'own-model-trace')
        terminal = jobs.coordinator.wait(job['jobId'], task_type='word.material_composer')
    assert terminal['status'] == 'completed', terminal
    assert captured[0]['model'] == 'composer-model'
    assert 'fragmentId' in captured[0]['messages'][0]['content']


def test_extract_relevant_fragments_within_budget_returns_all():
    from app.services.word.material_composer import extract_relevant_fragments

    catalog = {
        "fragmentsList": [
            {"fragmentId": "f1", "text": "普通正文A", "blockId": "b1", "section": "第一章"},
            {"fragmentId": "f2", "text": "普通正文B", "blockId": "b2", "section": "第二章"},
        ],
        "toc": [
            {"sectionTitle": "第一章", "blockId": "b1"},
            {"sectionTitle": "第二章", "blockId": "b2"},
        ],
    }
    selected = extract_relevant_fragments(catalog, "第一章", "要求A", max_tokens=10000)
    assert len(selected) == 2
    assert [f["fragmentId"] for f in selected] == ["f1", "f2"]


def test_extract_relevant_fragments_over_budget_prioritizes_matching_heading_and_keywords():
    from app.services.word.material_composer import extract_relevant_fragments

    fragments = []
    for i in range(100):
        fragments.append({
            "fragmentId": "f_norm_{0}".format(i),
            "text": "不相关的历史背景正文段落文字内容序号{0}。".format(i) * 10,
            "blockId": "b_norm_{0}".format(i),
            "section": "无关章节",
        })
    fragments.append({
        "fragmentId": "f_target_1",
        "text": "本章节重点说明系统总体架构与业务子系统的划分原则。",
        "blockId": "b_target_1",
        "section": "第三章 总体架构设计",
    })
    fragments.append({
        "fragmentId": "f_target_2",
        "text": "系统总体架构包括数据中台、业务中台以及应用微服务集群。",
        "blockId": "b_target_2",
        "section": "第三章 总体架构设计",
    })
    catalog = {
        "fragmentsList": fragments,
        "toc": [
            {"sectionTitle": "无关章节", "blockId": "b_norm_0"},
            {"sectionTitle": "第三章 总体架构设计", "blockId": "b_target_1"},
        ],
    }
    # 限制预算只能容纳 2~3 个片段
    selected = extract_relevant_fragments(catalog, "总体架构", "列出总体架构与子系统", max_tokens=400)
    selected_ids = [f["fragmentId"] for f in selected]
    assert "f_target_1" in selected_ids
    assert "f_target_2" in selected_ids
    # 验证选出的片段为原始文本，且在结果中保持物理顺序
    assert all(isinstance(f["text"], str) and not f["text"].startswith("摘要：") for f in selected)
    # 物理顺序检查：f_target_1 在 f_target_2 之前
    idx1 = selected_ids.index("f_target_1")
    idx2 = selected_ids.index("f_target_2")
    assert idx1 < idx2

