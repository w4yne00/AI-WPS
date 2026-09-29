import base64
import json
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import zipfile
import pytest

from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.material_outline import PptMaterialOutlineCoordinator
from app.services.long_task_coordinator import get_long_task_coordinator


CONTENT_TYPES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" />
</Types>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:outlineLvl w:val="0" /></w:pPr>
      <w:r><w:t>第一章 项目建设成果</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>新一代系统一期已全面上线运行，覆盖12个网点。二期规划于2027年启动，建设智能风控。</w:t></w:r>
    </w:p>
  </w:body>
</w:document>""".encode("utf-8")


def build_docx(document_xml=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("word/document.xml", document_xml or DOCUMENT_XML)
    return output.getvalue()


@pytest.fixture
def outline_setup():
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_ppt_outline_"))
    store = PptMaterialStore(base_dir=temp_dir / "ppt", word_base_dir=temp_dir / "word", excel_base_dir=temp_dir / "excel")
    coordinator = PptMaterialOutlineCoordinator(store=store)

    raw_bytes = build_docx()
    store.import_material(
        session_id="ppt_test_sess",
        doc_identity="full:/test/deck.pptx",
        file_name="项目建设成果.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    yield store, coordinator
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.parametrize("fact_id, expected_text", [
    ("user-fact-1", "一期已验收"),
    ("user-fact-2", "二期预算500万元"),
    ("user", "一期已验收；二期预算500万元"),
    ("USER", "一期已验收；二期预算500万元"),
])
def test_outline_resolves_only_the_referenced_user_fact(outline_setup, fact_id, expected_text):
    store, coordinator = outline_setup
    raw = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "slides": [{"title": "补充事实", "fragmentIds": [fact_id]}],
    })
    result = coordinator._parse_and_validate_outline(
        raw, "高管", 1, "", store.get_catalog("ppt_test_sess"),
        user_facts="一期已验收；二期预算500万元",
    )
    assert result["slides"][0]["fragmentIds"] == [fact_id]
    assert result["slides"][0]["sources"] == [{
        "sourceId": fact_id, "sourceType": "user", "fileName": "用户补充事实",
        "chapter": "用户补充", "text": expected_text,
    }]


@pytest.mark.parametrize("fact_id, user_facts", [
    ("user-fact-99", "一期已验收"),
    ("user-fact-1", ""),
    ("user", ""),
    ("user-fact", ""),
    ("user_fact", ""),
])
def test_outline_rejects_user_sources_without_corresponding_facts(outline_setup, fact_id, user_facts):
    store, coordinator = outline_setup
    raw = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "slides": [{"title": "伪造事实", "fragmentIds": [fact_id]}],
    })
    with pytest.raises(AdapterError) as exc_info:
        coordinator._parse_and_validate_outline(
            raw, "高管", 1, "", store.get_catalog("ppt_test_sess"), user_facts=user_facts,
        )
    assert exc_info.value.code == "MATERIAL_OUTLINE_INVALID_SOURCE"


def test_ppt_material_outline_submission_validation(outline_setup):
    store, coordinator = outline_setup
    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({})
    assert exc_info.value.code == "REQUEST_VALIDATION_FAILED"

    # Missing slideCount or invalid range
    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "audience": "高管汇报",
            "slideCount": 2,  # min is 3
        })
    assert exc_info.value.code == "REQUEST_VALIDATION_FAILED"


def test_ppt_material_outline_generation_and_roles(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "突出成效与规划",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目建设阶段汇报",
                "keyPoints": ["汇报主题与目标", "汇报部门与日期"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "一期建设核心成效",
                "keyPoints": ["业务网点全覆盖", "系统零故障稳定运行"],
                "missingItems": ["具体投资预算未提及"],
                "fragmentIds": [2],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "致谢与Q&A",
                "keyPoints": ["Q&A 交流环节"],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_1",
            "audience": "公司高管",
            "slideCount": 3,
            "instruction": "突出成效与规划",
        })
        assert res["jobId"] is not None
        job_id = res["jobId"]

        job = coordinator.wait_job(job_id, document_session_id="ppt_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["schemaVersion"] == "ppt.material_outline.v1"
        assert result["slideCount"] == 3
        assert len(result["slides"]) == 3
        assert result["slides"][0]["pageRole"] == "cover"
        assert result["slides"][1]["pageRole"] == "content"
        assert len(result["slides"][1]["sources"]) >= 1
        assert result["slides"][1]["sources"][0]["fileName"] == "项目建设成果.docx"
        assert "二期规划" in result["slides"][1]["sources"][0]["text"]
        assert result["slides"][1]["missingItems"] == ["具体投资预算未提及"]
        assert result["slides"][2]["pageRole"] == "backcover"
        assert "basisMaterials" in result
        assert len(result["basisMaterials"]) == 1


def test_ppt_material_outline_slide_count_mismatch_rejected(outline_setup):
    store, coordinator = outline_setup

    # Model returned 2 slides when 3 requested
    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "突出成效与规划",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目建设阶段汇报",
                "keyPoints": ["汇报主题与目标"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "一期建设核心成效",
                "keyPoints": ["业务网点全覆盖"],
                "missingItems": [],
                "fragmentIds": [1],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_mismatch",
            "audience": "公司高管",
            "slideCount": 3,
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "failed"
        assert "页数不匹配" in job["error"]["message"]


def test_ppt_material_outline_invalid_fragment_id_rejected(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "封面",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [9999],  # Non-existent fragment ID!
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "正文",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "封底",
                "keyPoints": [],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_invalid_frag",
            "audience": "公司高管",
            "slideCount": 3,
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "failed"
        assert "出处" in job["error"]["message"]


def test_ppt_material_outline_job_id_conflict(outline_setup):
    store, coordinator = outline_setup
    payload = {
        "documentSessionId": "ppt_test_sess",
        "clientJobId": "ppt_job_dup",
        "audience": "受众A",
        "slideCount": 3,
    }
    with patch.object(coordinator, "_call_provider_model", return_value="{}"):
        coordinator.submit_job(payload)
        # Same job id with different slide count
        payload2 = dict(payload, slideCount=5)
        with pytest.raises(AdapterError) as exc_info:
            coordinator.submit_job(payload2)
        assert exc_info.value.code == "MATERIAL_OUTLINE_JOB_CONFLICT"


def test_ppt_material_outline_with_user_facts(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "技术评审",
        "slideCount": 3,
        "instruction": "包含补充事实",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目汇报",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": ["user-fact"],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "架构内容",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "结束",
                "keyPoints": [],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_job_user_facts",
            "audience": "技术评审",
            "slideCount": 3,
            "userFacts": "【事实】预算为500万元",
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["slides"][0]["sources"][0]["sourceType"] == "user"
        assert result["slides"][0]["sources"][0]["fileName"] == "用户补充事实"
        assert "500万元" in result["slides"][0]["sources"][0]["text"]


def test_outline_submission_reads_original_header_and_keeps_full_sources(outline_setup):
    store, coordinator = outline_setup
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES_XML)
        archive.writestr('word/document.xml', DOCUMENT_XML)
        archive.writestr('word/header1.xml', DOCUMENT_XML.replace('第一章'.encode(), '页眉事实不可遗漏'.encode()))
    doc = store.get_catalog('ppt_test_sess')['documents'][0]
    store.update_material('ppt_test_sess', doc['materialId'], '完整.docx', base64.b64encode(output.getvalue()).decode())
    coordinator.coordinator = MagicMock()
    coordinator.coordinator.get.return_value = None
    coordinator.provider.resolve_task_auth = MagicMock(return_value={})
    coordinator.submit_job({'documentSessionId': 'ppt_test_sess', 'slideCount': 3})
    snapshot = coordinator.coordinator.submit.call_args.kwargs['snapshot']
    fragments = snapshot['catalog']['fragmentsList']
    assert any('页眉事实不可遗漏' in f.get('text', '') for f in fragments)
    assert all(f['fragmentId'] in store.get_catalog('ppt_test_sess')['fragments'] for f in fragments)


def test_outline_preserves_core_message_and_presentation_advice(outline_setup):
    store, coordinator = outline_setup
    raw = json.dumps({'schemaVersion': 'ppt.material_outline.v1', 'slides': [{'title': '成果', 'coreMessage': '强调覆盖范围',
                                  'presentationAdvice': '用对比图呈现', 'keyPoints': ['覆盖12个网点']} ]})
    result = coordinator._parse_and_validate_outline(raw, '高管', 1, '', store.get_catalog('ppt_test_sess'))
    assert result['slides'][0]['coreMessage'] == '强调覆盖范围'
    assert result['slides'][0]['presentationAdvice'] == '用对比图呈现'


def test_outline_calls_real_provider_signature_and_rejects_truncation(outline_setup):
    from app.services.provider_client import ProviderClient
    from unittest.mock import create_autospec
    _, coordinator = outline_setup
    coordinator.provider = create_autospec(ProviderClient, instance=True)
    coordinator.provider.post_task.return_value = {'answer': '{}', 'finishReason': 'length'}
    with pytest.raises(AdapterError) as error:
        coordinator._call_provider_model('system', 'whole document',
                                        task_auth={'providerBaseUrl': 'http://localhost', 'apiKey': 'test'})
    assert error.value.code == 'MATERIAL_OUTLINE_INCOMPLETE'


def test_outline_original_images_reach_http_request_without_id_collisions(outline_setup):
    from tests.test_word_material_document import document, p, PNG
    store, coordinator = outline_setup
    image = '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
    parts = {'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG}
    for name in ('甲.docx', '乙.docx'):
        store.import_material('ppt_test_sess', '', name, base64.b64encode(document(p('文首') + image + p('文尾'), parts)).decode())
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            catalog = store.get_catalog('ppt_test_sess')
            fid = next(f['fragmentId'] for f in catalog['fragmentsList'] if f.get('imageId'))
            answer = {'schemaVersion': 'ppt.material_outline.v1', 'slides': [
                {'title': str(i), 'fragmentIds': [fid], 'coreMessage': '观点', 'presentationAdvice': '建议'} for i in range(3)]}
            return json.dumps({'choices': [{'message': {'content': json.dumps(answer)}, 'finish_reason': 'stop'}]}).encode()
    def respond(req, *args):
        captured.append(json.loads(req.data))
        return Response()
    auth = {'accessMethod': 'direct_model', 'providerBaseUrl': 'https://model.invalid', 'apiKey': 'test',
            'modelName': 'vision', 'contextWindowTokens': 40000, 'temperature': 0, 'maxOutputTokens': 2000,
            'imageInputMode': 'openai_image_url'}
    with patch.object(coordinator.provider, 'resolve_task_auth', return_value=auth), patch('app.services.provider_client._open_task_response', side_effect=respond):
        submitted = coordinator.submit_job({'documentSessionId': 'ppt_test_sess', 'slideCount': 3})
        job = coordinator.wait_job(submitted['jobId'], document_session_id='ppt_test_sess')
    assert job['status'] == 'completed', job.get('error')
    content = captured[0]['messages'][1]['content']
    pictures = [x for x in content if x['type'] == 'image_url']
    assert len(pictures) == 2
    assert all(base64.b64decode(x['image_url']['url'].split(',')[1]) == PNG for x in pictures)
    assert captured[0]['temperature'] == 0
    assert '文首' in content[0]['text'] and '文尾' in content[0]['text']
    image_ids = [f['imageId'] for f in store.get_catalog('ppt_test_sess')['fragmentsList'] if f.get('imageId')]
    assert len(set(image_ids)) == 2
    assert job['result']['slides'][0]['sources'][0]['imageId'] in image_ids
    assert 'imageDataUri' not in json.dumps(job['result'])
    assert job['result']['capacity']['imageBudgetKnown'] is False


def test_conflict_preview_and_submit_use_the_same_complete_material(outline_setup):
    from tests.test_word_material_document import document, p, W
    store, coordinator = outline_setup
    raw = document(p('项目预算为100万元。'), {'word/header1.xml': ('<w:hdr xmlns:w="%s">%s</w:hdr>' % (W, p('项目预算为200万元。'))).encode()})
    doc = store.get_catalog('ppt_test_sess')['documents'][0]
    store.update_material('ppt_test_sess', doc['materialId'], '预算.docx', base64.b64encode(raw).decode())
    conflicts = coordinator.detect_conflicts('ppt_test_sess')
    assert conflicts, '页眉冲突必须在提交前可见'
    with pytest.raises(AdapterError) as error:
        coordinator.submit_job({'documentSessionId': 'ppt_test_sess', 'slideCount': 3})
    assert error.value.code == 'MATERIAL_OUTLINE_CONFLICT_UNRESOLVED'
