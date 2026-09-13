"""Regression coverage for public format-review selection validation."""
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.core.errors import AdapterError
from app.services.direct_services import DirectServiceStore
from app.services.provider_client import ProviderClient
from app.services.word.format_reviewer import WordFormatReviewer

TASK = 'word.format_review'
ROUTE = '/provider/task-model-selections/' + TASK


class FormatDirectValidationTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DirectServiceStore(Path(self.tmp.name) / 'config.json', Path(self.tmp.name) / 'keys')
        self.api_patch = patch('app.api.provider.get_direct_service_store', return_value=self.store)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.api = TestClient(app)
        self.a = self.service('A')
        self.b = self.service('B')

    def service(self, name):
        service = self.store.create_service(name=name, service_base_url='https://example.com/v1', default_model='vision')
        self.store.replace_api_key(service['id'], 'key-one', expected_revision=1)
        self.store.update_model_list(service['id'], ['vision'], expected_revision=2)
        return self.store.get_service(service['id'])

    def draft(self, service):
        return {'serviceId': service['id'], 'modelName': 'vision', 'imageInputMode': 'disabled'}

    def save(self, service):
        return self.api.post('/provider/direct-services/' + service['id'] + '/activate', json={'taskType': TASK, 'taskModelSelection': self.draft(service)})

    def validate(self, draft, effect=None):
        with patch.object(ProviderClient, '_validate_format_semantic_direct', side_effect=effect, return_value={'success': True}):
            return self.api.post(ROUTE + '/validate', json=draft)

    def test_unvalidated_direct_auth_is_not_semantically_ready(self):
        self.save(self.a)
        auth = ProviderClient(direct_service_store=self.store).resolve_task_auth(TASK)
        self.assertFalse(WordFormatReviewer._semantic_protocol_ready(auth))

    def test_draft_validation_never_marks_saved_other_service_ready(self):
        self.save(self.b)
        self.assertEqual(self.validate(self.draft(self.a)).status_code, 200)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')
        self.assertEqual(self.save(self.a).status_code, 200)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'ready')

    def test_first_draft_can_validate_before_save(self):
        self.assertEqual(self.validate(self.draft(self.a)).status_code, 200)
        self.assertEqual(self.save(self.a).status_code, 200)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'ready')

    def test_failed_revalidation_revokes_success(self):
        self.save(self.a)
        self.assertEqual(self.validate(self.draft(self.a)).status_code, 200)
        self.assertEqual(self.validate(self.draft(self.a), AdapterError('MODEL_RESULT_INVALID', 'invalid', status_code=502)).status_code, 502)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')

    def test_key_rotation_and_same_host_path_change_invalidate(self):
        self.save(self.a)
        self.validate(self.draft(self.a))
        self.store.replace_api_key(self.a['id'], 'key-two', expected_revision=3)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')
        self.validate(self.draft(self.a))
        self.store.update_service(self.a['id'], name='A', service_base_url='https://example.com/v2', expected_revision=4)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')

    def test_task_parameter_change_invalidates(self):
        self.save(self.a)
        self.validate(self.draft(self.a))
        self.store.update_task_model_selection(TASK, service_id=self.a['id'], model_name='vision', temperature=0.5, image_input_mode='disabled')
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')

    def test_key_change_during_validation_rejects_result(self):
        self.save(self.a)
        def rotate(*args):
            self.store.replace_api_key(self.a['id'], 'key-two', expected_revision=3)
            return {'success': True}
        self.assertEqual(self.validate(self.draft(self.a), rotate).status_code, 409)
        self.assertEqual(self.store.get_task_model_selection(TASK)['formatSemanticReadiness']['code'], 'validation_required')

    def image_save(self):
        draft = self.draft(self.a)
        draft['imageInputMode'] = 'openai_image_url'
        result = self.api.post('/provider/direct-services/' + self.a['id'] + '/activate', json={'taskType': TASK, 'taskModelSelection': draft})
        self.assertEqual(result.status_code, 200)

    def standalone(self, action, payload):
        import standalone_adapter
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        raw = json.dumps(payload).encode()
        handler.path = ROUTE + '/' + action
        handler.headers = {'Content-Length': str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)
        with patch.object(standalone_adapter, 'DirectServiceStore', return_value=self.store):
            handler.do_POST()
        return captured

    def test_image_public_authorization_and_real_probe_fastapi_and_standalone(self):
        self.image_save()
        for standalone in (False, True):
            with self.subTest(standalone=standalone):
                def post(action, payload):
                    if standalone:
                        return self.standalone(action, payload)['status']
                    return self.api.post(ROUTE + '/' + action, json=payload).status_code
                self.assertEqual(post('image-authorization', {'authorized': False}), 200)
                self.assertEqual(post('validate-image', {}), 409)
                self.assertEqual(post('image-authorization', {'authorized': True}), 200)
                requests = []
                def transport(req, **kwargs):
                    import base64, struct, zlib
                    body = json.loads(req.data)
                    content = body['messages'][-1]['content']
                    png = base64.b64decode(content[1]['image_url']['url'].split(',')[1])
                    self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
                    offset, compressed = 8, b''
                    while offset < len(png):
                        length = struct.unpack('!I', png[offset:offset+4])[0]
                        if png[offset+4:offset+8] == b'IDAT':
                            compressed += png[offset+8:offset+8+length]
                        offset += length + 12
                    row = zlib.decompress(compressed)
                    palette = {(255, 0, 0): 'red', (0, 255, 0): 'green', (0, 0, 255): 'blue',
                               (255, 255, 0): 'yellow', (0, 255, 255): 'cyan', (255, 0, 255): 'magenta'}
                    color = ' '.join(palette[tuple(row[1 + i * 192:4 + i * 192])] for i in range(8))
                    self.assertNotIn('key-one', json.dumps(body))
                    requests.append(body)
                    response = BytesIO(json.dumps({'choices': [{'message': {'content': color}}]}).encode())
                    return response
                with patch('app.services.provider_client.urllib_request.urlopen', side_effect=transport):
                    self.assertEqual(post('validate-image', {}), 200)
                self.assertEqual(len(requests), 1)
                self.assertEqual(self.store.get_task_model_selection(TASK)['imageSemanticReadiness']['code'], 'ready')

    def test_image_failure_revokes_previous_success(self):
        self.image_save()
        self.api.post(ROUTE + '/image-authorization', json={'authorized': True})
        self.store.record_image_semantic_validation(TASK, {'validated': True})
        with patch.object(ProviderClient, '_post_direct_task', return_value={'answer': 'cannot see image'}):
            result = self.api.post(ROUTE + '/validate-image', json={})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.store.get_task_model_selection(TASK)['imageSemanticReadiness']['code'], 'validation_required')

    def test_authorization_rejects_selection_changed_since_confirmation(self):
        self.image_save()
        old = self.store.get_task_model_selection(TASK)
        self.save(self.b)
        result = self.api.post(ROUTE + '/image-authorization', json={'authorized': True, 'expectedSelection': old})
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(self.store.get_task_model_selection(TASK)['imageExternalAuthorization'])

    def test_image_key_rotation_stays_disabled_in_runtime_policy(self):
        from app.services.word.image_semantics import image_pixel_policy
        self.image_save()
        self.api.post(ROUTE + '/image-authorization', json={'authorized': True})
        self.store.record_image_semantic_validation(TASK, {'validated': True})
        self.store.replace_api_key(self.a['id'], 'key-two', expected_revision=3)
        self.store.update_model_list(self.a['id'], ['vision'], expected_revision=4)
        auth = ProviderClient(direct_service_store=self.store).resolve_task_auth(TASK)
        self.assertFalse(image_pixel_policy({'enabled': True}, auth['modelConfiguration'])['allowed'])

    def test_image_concurrent_selection_change_does_not_validate_replacement(self):
        self.image_save()
        self.api.post(ROUTE + '/image-authorization', json={'authorized': True})
        def change(*args, **kwargs):
            self.save(self.b)
            return {'answer': 'red'}
        with patch('secrets.choice', return_value=('red', (255, 0, 0))), patch.object(ProviderClient, '_post_direct_task', side_effect=change):
            result = self.api.post(ROUTE + '/validate-image', json={})
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(self.store.get_task_model_selection(TASK)['imageSemanticValidation'])

    def test_unready_public_background_job_completes_without_provider_call(self):
        import time
        from app.services.long_task_coordinator import LongTaskCoordinator
        from app.services.word.deterministic_format_review import DeterministicFormatReviewService
        self.save(self.a)
        reviewer = WordFormatReviewer(provider_client=ProviderClient(direct_service_store=self.store))
        service = DeterministicFormatReviewService(staging_root=Path(self.tmp.name) / 'staging', reviewer=reviewer,
                                                   coordinator=LongTaskCoordinator(max_running=1, max_queued=1))
        root = '/word/format-review'
        identity = {'documentIdSha256': 'test-document', 'hostDocumentId': 'test-document'}
        with patch('app.api.word.deterministic_format_review_service', service), patch('app.services.word.deterministic_format_review.get_task_history_store', return_value=None), patch.object(ProviderClient, 'format_semantics', side_effect=AssertionError('unready provider called')):
            response = self.api.post(root + '/snapshots', json={
                'documentId': 'test.docx', 'selectionMode': 'document', 'documentIdentity': identity,
                'formatSnapshotSchemaVersion': 'word.format_review.snapshot.v2', 'formatFactSchemaVersion': 'format_snapshot.v2',
                'editSequence': '1', 'documentSessionId': 'session-test', 'host': 'wps',
            })
            self.assertEqual(response.status_code, 200, response.text)
            session = response.json()['data']
            blocks = service._normalize_format_blocks([{'blockId': 'format-p-1', 'blockType': 'paragraph', 'scope': 'in_scope',
                'paragraphIndex': 1, 'text': '图 1 系统架构', 'format': {'styleName': 'Normal', 'fontName': '楷体', 'fontSize': 14, 'dataStatus': 'verified'}}])
            metrics = service._format_metrics(blocks)
            response = self.api.put(root + '/snapshots/' + session['snapshotId'] + '/batches/0', json={
                'uploadToken': session['uploadToken'], 'batchId': 'format-batch-0', 'blocks': blocks, 'editSequence': '1',
                **{key: metrics[key] for key in ('characterCount', 'contentSha256', 'structureSha256', 'formatSha256')},
            })
            self.assertEqual(response.status_code, 200, response.text)
            verification = {'batchCount': 1, 'blockCount': 1, 'reviewCharacterCount': metrics['characterCount'],
                            'documentIdentity': identity, 'editSequence': '1',
                            **{key: metrics[key] for key in ('contentSha256', 'structureSha256', 'formatSha256', 'coverage')}}
            response = self.api.post(root + '/snapshots/' + session['snapshotId'] + '/commit', json={
                'uploadToken': session['uploadToken'], **verification, 'verification': verification})
            self.assertEqual(response.status_code, 200, response.text)
            committed = response.json()['data']
            response = self.api.post(root + '/jobs', json={'snapshotId': committed['snapshotId'], 'snapshotToken': committed['snapshotToken'],
                'clientJobId': 'job-format-test', 'documentSessionId': 'session-test', 'host': 'wps'})
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()['data']
            for _ in range(100):
                job = self.api.get(root + '/jobs/' + job['jobId']).json()['data']
                if job['status'] in ('completed', 'failed'):
                    break
                time.sleep(0.01)
            self.assertEqual(job['status'], 'completed', job)
            report = self.api.get(root + '/jobs/' + job['jobId'] + '/report').json()['data']
            self.assertIn('format_semantic_protocol_not_ready', json.dumps(report))

    def test_authorization_rejects_service_change_since_confirmation(self):
        self.image_save()
        old = self.store.get_task_model_selection(TASK)
        revision = self.store.get_service(self.a['id'])['revision']
        self.store.update_service(self.a['id'], name='A', service_base_url='https://other.example/v1', expected_revision=revision)
        result = self.api.post(ROUTE + '/image-authorization', json={'authorized': True, 'expectedSelection': old, 'expectedServiceRevision': revision})
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(self.store.get_task_model_selection(TASK)['imageExternalAuthorization'])

    def test_image_probe_rejects_fixed_color_answer_that_ignores_image(self):
        self.image_save()
        self.api.post(ROUTE + '/image-authorization', json={'authorized': True})
        with patch('secrets.choice', return_value=('red', (255, 0, 0))), patch.object(ProviderClient, '_post_direct_task', return_value={'answer': 'red'}):
            result = self.api.post(ROUTE + '/validate-image', json={})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.store.get_task_model_selection(TASK)['imageSemanticReadiness']['code'], 'validation_required')
