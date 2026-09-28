import base64
import json
from unittest.mock import patch

import pytest

from app.core.errors import AdapterError
from app.services.provider_client import ProviderClient
from tests.test_word_material_document import PNG


def test_request_contains_every_original_image():
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
    def respond(req, *args):
        seen.append(json.loads(req.data))
        return Response()
    with patch('app.services.provider_client._open_task_response', side_effect=respond):
        ProviderClient().post_task('word.material_composer', 'image-test', {}, '全部资料',
            task_auth={'accessMethod': 'direct_model', 'providerBaseUrl': 'https://model.invalid', 'apiKey': 'test',
                       'modelName': 'test-vision', 'contextWindowTokens': 40000},
            image_files=[{'imageId': 'picture-1', 'data': PNG, 'mimeType': 'image/png'},
                         {'imageId': 'picture-2', 'data': PNG, 'mimeType': 'image/png'}])
    content = seen[0]['messages'][1]['content']
    images = [c for c in content if c['type'] == 'image_url']
    assert len(images) == 2
    assert base64.b64decode(images[0]['image_url']['url'].split(',')[1]) == PNG
    assert any(c.get('text') == 'picture-2' for c in content)


def test_unknown_image_token_cost_is_not_reported_as_full_budget_verified():
    from app.services.provider_client import validate_composer_multimodal_input
    result = validate_composer_multimodal_input({'contextWindowTokens': 40000}, 'system', 'text',
        [{'data': PNG, 'mimeType': 'image/png'}])
    assert result['imageBudgetKnown'] is False
    assert result['warning']


def test_over_budget_full_text_is_rejected():
    from app.services.provider_client import validate_composer_multimodal_input
    with pytest.raises(AdapterError) as caught:
        validate_composer_multimodal_input({'contextWindowTokens': 100, 'maxOutputTokens': 80}, 'sys', '很长' * 100, [])
    assert caught.value.code == 'MODEL_INPUT_OVER_BUDGET'
