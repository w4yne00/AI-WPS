import json
from unittest.mock import patch

import pytest

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.material_composer import MaterialComposerJobs
from app.services.word.material_import import WordMaterialImportService
from tests.test_word_material_document import document, p, PNG
from tests.test_word_material_import import upload_payload


def setup_job(tmp_path, body, parts=None):
    materials = WordMaterialImportService(state_dir=tmp_path)
    materials.import_material(upload_payload(document(body, parts)))
    coordinator = LongTaskCoordinator()
    return MaterialComposerJobs(materials, coordinator=coordinator), coordinator


def test_full_materials_used_without_relevance_filter_and_no_title(tmp_path):
    jobs, coordinator = setup_job(tmp_path, p('文首甲') + p('文中乙') + p('文尾丙'))
    seen = []
    def respond(task_type, trace, data, prompt, **kw):
        seen.append((json.loads(prompt.splitlines()[-1]), kw))
        return {'answer': json.dumps({'paragraphs': [{'text': '文首甲', 'fragmentIds': ['frag-1'], 'missingItems': []}]})}
    with patch.object(jobs.provider, 'resolve_task_auth', return_value={'providerBaseUrl': 'https://model.invalid', 'apiKey': 'test'}), \
         patch.object(jobs.provider, 'post_task', side_effect=respond), \
         patch('app.services.word.material_composer.extract_relevant_fragments', side_effect=AssertionError('must not select excerpts')):
        job = jobs.start({'documentSessionId': 'doc-session-1', 'clientJobId': 'full-document-0001',
                          'instruction': '编写整篇', 'writingPolicyScene': 'disabled'}, 'full-test')
        result = coordinator.wait(job['jobId'], task_type='word.material_composer')
    assert result['status'] == 'completed', result
    assert [x['text'] for x in seen[0][0]['materials']] == ['文首甲', '文中乙', '文尾丙']
    assert result['result']['writingPolicyUsage']['applied'] is False


def test_over_budget_full_document_rejected_before_model_call(tmp_path):
    jobs, _ = setup_job(tmp_path, p('事实' * 4000))
    with patch.object(jobs.provider, 'resolve_task_auth', return_value={'providerBaseUrl': 'https://model.invalid', 'apiKey': 'test', 'contextWindowTokens': 2500, 'maxOutputTokens': 500}), \
         patch.object(jobs.provider, 'post_task', side_effect=AssertionError('over-budget request sent')):
        with pytest.raises(AdapterError) as caught:
            jobs.start({'documentSessionId': 'doc-session-1', 'clientJobId': 'full-budget-0001', 'instruction': '编写', 'writingPolicyScene': 'disabled'}, 'full-test')
    assert caught.value.code == 'MODEL_INPUT_OVER_BUDGET'


def test_unread_image_prevents_claiming_full_input(tmp_path):
    jobs, _ = setup_job(tmp_path, '<w:p><w:r><w:drawing><a:blip r:embed="missing"/></w:drawing></w:r></w:p>')
    with pytest.raises(AdapterError) as caught:
        jobs.start({'documentSessionId': 'doc-session-1', 'clientJobId': 'full-unread-0001', 'instruction': '编写'}, 'full-test')
    assert caught.value.code == 'MATERIAL_READ_INCOMPLETE'


def test_truncated_model_output_is_not_accepted_as_complete(tmp_path):
    jobs, coordinator = setup_job(tmp_path, p('原文'))
    answer = {'answer': json.dumps({'paragraphs': [{'text': '原文', 'fragmentIds': ['frag-1'], 'missingItems': []}]}), 'finishReason': 'length'}
    with patch.object(jobs.provider, 'resolve_task_auth', return_value={'providerBaseUrl': 'https://model.invalid', 'apiKey': 'test'}), patch.object(jobs.provider, 'post_task', return_value=answer):
        job = jobs.start({'documentSessionId': 'doc-session-1', 'clientJobId': 'full-truncated-0001', 'instruction': '编写'}, 'full-test')
        terminal = coordinator.wait(job['jobId'], task_type='word.material_composer')
    assert terminal['status'] == 'failed'
    assert terminal['error']['code'] == 'MATERIAL_COMPOSER_INCOMPLETE'


def test_instruction_facts_have_an_explicit_verifiable_source(tmp_path):
    jobs, coordinator = setup_job(tmp_path, p('背景'))
    answer = {'answer': json.dumps({'paragraphs': [{'text': '预算500万元。', 'fragmentIds': ['user-instruction'], 'missingItems': []}]})}
    with patch.object(jobs.provider, 'resolve_task_auth', return_value={'providerBaseUrl':'https://model.invalid','apiKey':'test'}), patch.object(jobs.provider, 'post_task', return_value=answer):
        job = jobs.start({'documentSessionId':'doc-session-1','clientJobId':'instruction-fact-0001','instruction':'补充事实：预算500万元。请编写。'}, 'test')
        result = coordinator.wait(job['jobId'], task_type='word.material_composer')
    assert result['status'] == 'completed', result
    assert result['result']['paragraphs'][0]['sources'][0]['sourceType'] == 'user'
    assert '预算500万元' in result['result']['paragraphs'][0]['sources'][0]['quote']
