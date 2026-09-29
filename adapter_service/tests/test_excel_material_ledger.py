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
from app.services.excel.material_store import ExcelMaterialStore
from app.services.excel.material_ledger import ExcelMaterialLedgerCoordinator
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
      <w:r><w:t>第一章 建设任务</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>信息化部负责基础网络改造，于2026年10月完成，交付验收报告。安全组负责安全审计整改，交付整改台账。</w:t></w:r>
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
def ledger_setup():
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_ledger_"))
    store = ExcelMaterialStore(base_dir=temp_dir / "excel", word_base_dir=temp_dir / "word")
    coordinator = ExcelMaterialLedgerCoordinator(store=store)

    raw_bytes = build_docx()
    store.import_material(
        session_id="excel_test_sess",
        doc_identity="full:/test/doc.xlsx",
        file_name="建设任务.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    yield store, coordinator
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel_material_ledger_header_mapping_and_rows(ledger_setup):
    store, coordinator = ledger_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "excel.material_ledger.v1",
        "rows": [
            {
                "values": {
                    "工作事项": "基础网络改造",
                    "责任部门": "信息化部",
                    "完成时间": "2026年10月",
                    "交付物验收": "验收报告",
                },
                "missingFields": [],
                "isDuplicate": False,
                "duplicateOfIndex": None,
                "duplicateReason": "",
                "fragmentIds": [1],
            },
            {
                "values": {
                    "工作事项": "安全审计整改",
                    "责任部门": "安全组",
                    "完成时间": "",
                    "交付物验收": "整改台账",
                },
                "missingFields": ["完成时间"],
                "isDuplicate": True,
                "duplicateOfIndex": 0,
                "duplicateReason": "与第一项网络任务同属安全配套",
                "fragmentIds": [1],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_job_1",
            "headers": ["工作事项", "责任部门", "完成时间", "交付物验收"],
            "instruction": "按章节提取任务",
        })
        job_id = res["jobId"]
        job = coordinator.wait_job(job_id, "excel_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["headers"] == ["工作事项", "责任部门", "完成时间", "交付物验收"]
        assert len(result["rows"]) == 2
        # Check first row
        row1 = result["rows"][0]
        assert row1["values"]["工作事项"] == "基础网络改造"
        assert row1["missingFields"] == []
        assert row1["isDuplicate"] is False
        # Check second row (missing field and duplicate not merged)
        row2 = result["rows"][1]
        assert row2["values"]["工作事项"] == "安全审计整改"
        assert row2["values"]["完成时间"] == ""
        assert row2["missingFields"] == ["完成时间"]
        assert row2["isDuplicate"] is True
        assert row2["duplicateOfIndex"] == 0
        assert "安全配套" in row2["duplicateReason"]
        assert len(row2["sources"]) > 0
        assert row2["sources"][0]["fileName"] == "建设任务.docx"
        # Check basis materials
        assert len(result["basisMaterials"]) == 1
        assert result["basisMaterials"][0]["fileName"] == "建设任务.docx"


def test_excel_material_ledger_empty_materials_rejected():
    temp_dir = Path(tempfile.mkdtemp())
    store = ExcelMaterialStore(base_dir=temp_dir / "excel", word_base_dir=temp_dir / "word")
    coordinator = ExcelMaterialLedgerCoordinator(store=store)

    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({
            "documentSessionId": "empty_session",
            "clientJobId": "job_empty",
            "headers": ["工作事项"],
        })
    assert exc_info.value.code in ("MATERIAL_NOT_FOUND", "EMPTY_MATERIAL")
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel_material_ledger_invalid_fragment_rejected(ledger_setup):
    store, coordinator = ledger_setup

    invalid_fragment_response = json.dumps({
        "schemaVersion": "excel.material_ledger.v1",
        "rows": [
            {
                "values": {"工作事项": "伪造任务"},
                "missingFields": [],
                "isDuplicate": False,
                "duplicateOfIndex": None,
                "duplicateReason": "",
                "fragmentIds": [99999],  # Does not exist
            }
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=invalid_fragment_response):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_job_invalid",
            "headers": ["工作事项"],
        })
        job = coordinator.wait_job(res["jobId"], "excel_test_sess")
        assert job["status"] == "failed"
        err_msg = str(job.get("error", ""))
        assert "出处" in err_msg or "片段" in err_msg or "MATERIAL_LEDGER_INVALID_SOURCE" in err_msg


def test_excel_material_ledger_cancel_job(ledger_setup):
    import time
    store, coordinator = ledger_setup

    def slow_call(*args, **kwargs):
        time.sleep(2.0)
        return "{}"

    with patch.object(coordinator, "_call_provider_model", side_effect=slow_call):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_cancel",
            "headers": ["工作事项"],
        })
        job_id = res["jobId"]
        cancelled = coordinator.cancel_job(job_id, "excel_test_sess")
        assert cancelled["cancelRequested"] is True or cancelled["status"] == "cancelled"
        terminal = coordinator.wait_job(job_id, "excel_test_sess")
        assert terminal["status"] in ("cancelled", "failed")


@pytest.mark.parametrize("fragment_ids", [[], ["user-fact-999"]])
def test_ledger_rejects_absent_or_invented_sources(ledger_setup, fragment_ids):
    store, ledger = ledger_setup
    response = json.dumps({"schemaVersion": "excel.material_ledger.v1", "rows": [
        {"values": {"工作事项": "无依据任务"}, "fragmentIds": fragment_ids}
    ]})
    with pytest.raises(AdapterError) as error:
        ledger._parse_and_validate_ledger(response, ["工作事项"], store.get_catalog("excel_test_sess"))
    assert error.value.code == "MATERIAL_LEDGER_INVALID_SOURCE"


def test_ledger_model_configuration_is_available(tmp_path):
    from app.services.model_configurations import ModelConfigurationStore
    store = ModelConfigurationStore(config_path=tmp_path / "config.json", key_dir=tmp_path / "keys")
    assert store.list_for_task("excel.material_ledger")["taskType"] == "excel.material_ledger"


def test_ledger_rejects_second_job_in_same_workbook(ledger_setup):
    import threading
    store, ledger = ledger_setup
    release = threading.Event()
    entered = threading.Event()
    def wait_for_release(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return json.dumps({"schemaVersion": "excel.material_ledger.v1", "rows": []})
    first_id = "busy_first"
    try:
        with patch.object(ledger, "_call_provider_model", side_effect=wait_for_release):
            first = ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": first_id})
            assert entered.wait(2)
            assert ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": first_id})["jobId"] == first["jobId"]
            with pytest.raises(AdapterError) as error:
                ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": "busy_second"})
            assert error.value.code == "MATERIAL_COMPOSER_BUSY"
    finally:
        release.set()
        ledger.wait_job(first_id, "excel_test_sess")


@pytest.mark.parametrize("method,image_mode", [("direct_model", "disabled"), ("direct_model", "openai_image_url"), ("workflow_platform", "disabled")])
def test_ledger_runs_through_real_provider_transport(ledger_setup, method, image_mode):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    store, ledger = ledger_setup
    answer = json.dumps({"schemaVersion": "excel.material_ledger.v1", "rows": [
        {"values": {"工作事项": "基础网络改造"}, "fragmentIds": [1]}
    ]})
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())))
            body = {"choices": [{"message": {"content": answer}}]} if method == "direct_model" else {"answer": answer}
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    auth = {"accessMethod": method, "providerBaseUrl": "http://127.0.0.1:{0}".format(server.server_port),
            "providerChatPath": "/chat-messages", "providerMode": "blocking", "apiKey": "test-key",
            "modelName": "test-model", "temperature": 0.35, "maxOutputTokens": 8000, "contextWindowTokens": 40000, "imageInputMode": image_mode}
    original = store.get_full_document
    def whole(session, mid):
        data = original(session, mid)
        data['images'] = [{'imageId':'image-1','data':b'\x89PNG\r\n\x1a\nimage','mimeType':'image/png'}]
        data['blocks'].append({'kind':'image','blockId':'img','imageId':'image-1','source':{'part':'word/document.xml'}})
        return data
    try:
        with patch.object(ledger.provider, "resolve_task_auth", return_value=auth), patch.object(store, "get_full_document", side_effect=whole):
            job = ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": "transport_" + method + image_mode})
            result = ledger.wait_job(job["jobId"], "excel_test_sess")
        assert result["status"] == "completed", result.get("error")
        assert result["result"]["rows"][0]["values"]["工作事项"] == "基础网络改造"
        assert len(received) == 1
        assert received[0][0] == ("/chat/completions" if method == "direct_model" else "/chat-messages")
        if method == "direct_model":
            payload = received[0][1]
            assert payload['temperature'] == 0.35
            assert payload['max_tokens'] == 8000
            content = payload['messages'][-1]['content']
            if image_mode == 'openai_image_url':
                assert any(p.get('type') == 'image_url' and p['image_url']['url'].startswith('data:image/png;base64,') for p in content)
            else:
                assert isinstance(content, str)
                assert result['result']['inputCoverage']['omittedImageCount'] == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_ledger_sources_include_original_chapter_and_user_fact_text(ledger_setup):
    store, ledger = ledger_setup
    raw = json.dumps({"schemaVersion": "excel.material_ledger.v1", "rows": [
        {"values": {"工作事项": "网络改造"}, "fragmentIds": [2, "user-fact-1"]}
    ]})
    result = ledger._parse_and_validate_ledger(raw, ["工作事项"], store.get_catalog("excel_test_sess"), user_facts="一期由信息化部监督")
    assert result["rows"][0]["sources"][0]["chapter"] == "第一章 建设任务"
    assert result["rows"][0]["sources"][1]["text"] == "一期由信息化部监督"


def test_ledger_conflict_choices_are_validated_against_current_materials(ledger_setup):
    store, ledger = ledger_setup
    raw = json.dumps({"schemaVersion": "excel.material_ledger.v1", "rows": []})
    conflicts = [{"conflictId": "conflict-1", "topic": "预算", "options": [
        {"optionId": "opt-1-1", "value": "100万元", "sourceId": "m1", "sourceType": "material"}
    ]}]
    with patch("app.services.excel.material_ledger.detect_material_conflicts", return_value=conflicts):
        with pytest.raises(AdapterError) as error:
            ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": "conflict_missing"})
        assert error.value.code == "MATERIAL_LEDGER_CONFLICT_UNRESOLVED"
        with pytest.raises(AdapterError) as error:
            ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": "conflict_invalid", "conflictResolutions": [
                {"conflictId": "conflict-1", "chosenCandidateId": "opt-1-1", "chosenValue": "200万元"}
            ]})
        assert error.value.code == "REQUEST_VALIDATION_FAILED"
        with patch.object(ledger, "_call_provider_model", return_value=raw):
            job = ledger.submit_job({"documentSessionId": "excel_test_sess", "clientJobId": "conflict_valid", "conflictResolutions": [
                {"conflictId": "conflict-1", "chosenCandidateId": "opt-1-1", "chosenValue": "100万元"}
            ]})
            assert ledger.wait_job(job["jobId"], "excel_test_sess")["status"] == "completed"


@pytest.mark.parametrize('image_mode, expected_images', [('openai_image_url', 1), ('disabled', 0)])
def test_full_material_and_image_mode_reach_provider(ledger_setup, image_mode, expected_images):
    store, coordinator = ledger_setup
    original = store.get_full_document if hasattr(store, 'get_full_document') else None
    def whole(session, mid):
        data = original(session, mid)
        data['blocks'].extend([
            {'blockId':'last', 'kind':'text', 'text':'全文尾部唯一事实', 'source':{'part':'word/footer1.xml'}},
            {'blockId':'img', 'kind':'image', 'imageId':'image-1', 'source':{'part':'word/document.xml'}},
        ])
        data['images'] = [{'imageId':'image-1', 'mimeType':'image/png', 'data':b'\x89PNG\r\n\x1a\nimage'}]
        return data
    auth = {'accessMethod':'direct_model', 'imageInputMode':image_mode, 'providerBaseUrl':'http://model', 'apiKey':'test', 'temperature':0.2, 'maxOutputTokens':1200, 'contextWindowTokens':32000}
    captured = {}
    def post(*args, **kwargs):
        captured['query'] = args[3]
        captured.update(kwargs)
        return {'answer':json.dumps({'schemaVersion':'excel.material_ledger.v1','rows':[{'values':{'工作事项':'任务'},'fragmentIds':[1]}]})}
    with patch.object(store, 'get_full_document', side_effect=whole, create=True), patch.object(coordinator.provider, 'resolve_task_auth', return_value=auth), patch.object(coordinator.provider, 'post_task', side_effect=post):
        coordinator.submit_job({'documentSessionId':'excel_test_sess', 'clientJobId':'full-'+image_mode, 'headers':['工作事项']})
        job = coordinator.wait_job('full-'+image_mode, 'excel_test_sess')
    assert job['status'] == 'completed', job
    assert '全文尾部唯一事实' in captured['query']
    assert len(captured.get('image_files') or []) == expected_images
    assert captured['task_auth']['temperature'] == 0.2
    assert job['result']['inputCoverage']['omittedImageCount'] == 1 - expected_images


def test_missing_retained_original_rejected_even_with_cached_fragments(ledger_setup):
    store, coordinator = ledger_setup
    for path in store.base_dir.glob('*/files/*'):
        path.unlink()
    with pytest.raises(AdapterError, match='重新导入'):
        coordinator.submit_job({'documentSessionId':'excel_test_sess','clientJobId':'missing-original'})


def test_ledger_image_mode_can_be_explicitly_configured():
    from app.services.direct_services import DirectServiceStore
    assert DirectServiceStore._validate_image_input_mode('excel.material_ledger', 'openai_image_url') == 'openai_image_url'
    assert DirectServiceStore._validate_image_input_mode('excel.material_ledger', None) == 'disabled'


def test_truncated_model_output_never_becomes_completed(ledger_setup):
    _, coordinator = ledger_setup
    auth = {'accessMethod':'direct_model', 'providerBaseUrl':'http://model', 'apiKey':'test'}
    body = {'finishReason':'length', 'answer':json.dumps({'schemaVersion':'excel.material_ledger.v1','rows':[{'values':{'工作事项':'任务'},'fragmentIds':[1]}]})}
    with patch.object(coordinator.provider, 'resolve_task_auth', return_value=auth), patch.object(coordinator.provider, 'post_task', return_value=body):
        coordinator.submit_job({'documentSessionId':'excel_test_sess','clientJobId':'truncated','headers':['工作事项']})
        job = coordinator.wait_job('truncated','excel_test_sess')
    assert job['status'] == 'failed'
