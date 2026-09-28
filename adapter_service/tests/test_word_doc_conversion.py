from pathlib import Path
import pytest
from app.core.errors import AdapterError
from app.services.word.material_import import WordMaterialImportService
from tests.test_word_material_document import document, p
from tests.test_word_material_import import upload_payload

DOC = bytes.fromhex('d0cf11e0a1b11ae1') + b'conversion-fixture'


def test_native_doc_conversion_uses_temporary_copy_and_session(tmp_path):
    service = WordMaterialImportService(state_dir=tmp_path)
    stage = service.import_material(upload_payload(DOC, file_name='资料.doc'))
    assert stage['conversionRequired'] is True
    source = Path(stage['sourcePath'])
    assert source.read_bytes() == DOC
    Path(stage['targetPath']).write_bytes(document(p('转换后的全文')))
    with pytest.raises(AdapterError):
        service.import_material({'conversionId': stage['conversionId'], 'documentSessionId': 'other'})
    result = service.import_material({'conversionId': stage['conversionId'], 'documentSessionId': 'doc-session-1'})
    assert result['fileName'] == '资料.doc'
    assert result['fullReading']['complete'] is True
    assert not source.exists()
    assert service.read_complete_material(result['materialId'], 'doc-session-1')['blocks'][0]['text'] == '转换后的全文'


def test_conversion_cannot_import_external_path_and_cleans_cancelled_stage(tmp_path):
    service = WordMaterialImportService(state_dir=tmp_path)
    stage = service.import_material(upload_payload(DOC, file_name='资料.doc'))
    result = service.import_material({'conversionId': stage['conversionId'], 'documentSessionId': 'doc-session-1', 'cancelConversion': True})
    assert result['cancelled'] is True
    assert not Path(stage['sourcePath']).exists()
    with pytest.raises(AdapterError):
        service.import_material({'conversionId': stage['conversionId'], 'documentSessionId': 'doc-session-1', 'targetPath': '/tmp/other.docx'})
