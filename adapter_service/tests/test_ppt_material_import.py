import base64
import json
from io import BytesIO
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
import pytest

from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
from app.services.excel.material_store import ExcelMaterialStore
from app.services.word.material_import import WordMaterialStore, WordMaterialImportService


CONTENT_TYPES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" />
</Types>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:outlineLvl w:val="0" /></w:pPr>
      <w:r><w:t>第一章 总体实施方案</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>汇报主题包括新一代系统建设成果与二期规划。由技术部于2026年10月完成初验。</w:t></w:r>
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
def temp_roots():
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_ppt_mat_"))
    word_dir = temp_dir / "word_materials"
    excel_dir = temp_dir / "excel_materials"
    ppt_dir = temp_dir / "ppt_materials"
    word_dir.mkdir(parents=True, exist_ok=True)
    excel_dir.mkdir(parents=True, exist_ok=True)
    ppt_dir.mkdir(parents=True, exist_ok=True)
    yield word_dir, excel_dir, ppt_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_ppt_material_store_import_and_catalog(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)

    raw_bytes = build_docx()
    b64 = base64.b64encode(raw_bytes).decode("ascii")

    res = store.import_material(
        session_id="ppt_sess_1",
        doc_identity="full:/path/to/deck1.pptx",
        file_name="总体实施方案.docx",
        content_base64=b64,
    )
    assert res["materialId"] is not None
    assert res["fileName"] == "总体实施方案.docx"
    assert res["readableCharacterCount"] > 0

    catalog = store.get_catalog("ppt_sess_1")
    assert catalog["totalDocuments"] == 1
    assert catalog["totalCharacters"] == res["readableCharacterCount"]
    assert len(catalog["documents"]) == 1
    assert catalog["documents"][0]["materialId"] == res["materialId"]


def test_ppt_material_store_reusable_sources_and_clone_independence(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    word_store = WordMaterialStore(base_dir=word_dir)
    word_service = WordMaterialImportService(state_dir=word_dir)
    ppt_store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)

    # 1. Prepare word material
    raw_docx = build_docx()
    imported = word_service.import_material({
        "fileName": "方案文档.docx",
        "contentBase64": base64.b64encode(raw_docx).decode("ascii"),
        "documentSessionId": "word_sess_100",
        "documentIdentity": "full:/docs/方案.docx",
    })
    mat_id = imported["materialId"]

    # 2. List reusable sources from PPT
    sources = ppt_store.list_reusable_sources()
    assert len(sources) >= 1
    word_source = next((s for s in sources if s["sourceSessionId"] == "word_sess_100"), None)
    assert word_source is not None
    assert word_source["host"] == "word"
    assert word_source["displayName"] == "方案.docx"
    assert word_source["totalDocuments"] == 1

    # 3. Clone into PPT session
    cloned_catalog = ppt_store.clone_from_source(
        source_session_id="word_sess_100",
        target_session_id="ppt_sess_200",
        target_doc_identity="full:/slides/汇报.pptx",
    )
    assert cloned_catalog["documentSessionId"] == "ppt_sess_200"
    assert cloned_catalog["totalDocuments"] == 1
    cloned_mat_id = cloned_catalog["documents"][0]["materialId"]

    # 4. Delete material in PPT session and verify Word session is completely unaffected!
    ppt_store.delete_material("ppt_sess_200", cloned_mat_id)
    target_catalog = ppt_store.get_catalog("ppt_sess_200")
    assert target_catalog["totalDocuments"] == 0

    # Source word catalog must remain fully intact
    source_catalog = word_store.load_session_catalog("word_sess_100")
    assert source_catalog is not None
    assert source_catalog["totalDocuments"] == 1
    assert word_store.load_material_view(mat_id) is not None


def test_ppt_material_store_update_and_limits(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)

    raw_bytes = build_docx()
    res = store.import_material(
        session_id="ppt_sess_3",
        doc_identity="full:/path/to/test.pptx",
        file_name="初始.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )
    mat_id = res["materialId"]

    # Update with new docx
    new_doc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>更新后的汇报内容：二期预算规划</w:t></w:r></w:p>
  </w:body>
</w:document>""".encode("utf-8")
    new_bytes = build_docx(document_xml=new_doc_xml)

    updated = store.update_material(
        session_id="ppt_sess_3",
        material_id=mat_id,
        file_name="更新版.docx",
        content_base64=base64.b64encode(new_bytes).decode("ascii"),
    )
    assert updated["materialId"] == mat_id
    assert updated["fileName"] == "更新版.docx"
    assert updated["updatedAt"] > res["updatedAt"]

    cat = store.get_catalog("ppt_sess_3")
    assert cat["totalDocuments"] == 1
    assert cat["documents"][0]["fileName"] == "更新版.docx"


def test_ppt_material_store_bind_document(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)

    raw_bytes = build_docx()
    store.import_material(
        session_id="unsaved_ppt_99",
        doc_identity="",
        file_name="资料.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    # Bind to newly saved path
    bound = store.bind_document(
        old_session_id="unsaved_ppt_99",
        new_session_id="saved_ppt_100",
        new_doc_identity="full:/saved/path/演示文稿1.pptx",
    )
    assert bound["totalDocuments"] == 1

    cat = store.get_catalog("saved_ppt_100")
    assert cat["totalDocuments"] == 1
    assert cat["documentSessionId"] == "saved_ppt_100"


def test_clone_self_is_rejected_ppt(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)
    b64 = base64.b64encode(build_docx()).decode("ascii")
    store.import_material("sess_self", "full:/a.pptx", "a.docx", b64)

    with pytest.raises(AdapterError) as exc_info:
        store.clone_from_source("sess_self", "sess_self", "full:/a.pptx")
    assert exc_info.value.code == "CANNOT_REUSE_SAME_DOCUMENT"


@pytest.mark.parametrize("failure_point", ["publish_directory", "publish_index"])
def test_ppt_clone_failure_preserves_existing_materials_and_index(temp_roots, monkeypatch, failure_point):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir, excel_base_dir=excel_dir)
    b64 = base64.b64encode(build_docx()).decode("ascii")
    store.import_material("source", "", "新资料.docx", b64)
    store.import_material("target", "", "已有资料.docx", b64)
    target_dir = store._get_dir_for_session("target")
    before_files = {p.relative_to(target_dir): p.read_bytes() for p in target_dir.rglob("*") if p.is_file()}
    before_catalog = store.get_catalog("target")
    index_file = ppt_dir / "sessions.json"
    index = json.loads(index_file.read_text(encoding="utf-8"))
    del index["target"]  # The manifest fallback still resolves the existing target.
    index_file.write_text(json.dumps(index), encoding="utf-8")
    before_index = index_file.read_bytes()

    if failure_point == "publish_directory":
        rename = Path.rename

        def fail_publish(path, destination):
            if path.name.startswith(".clone-"):
                raise OSError("发布目录失败")
            return rename(path, destination)

        monkeypatch.setattr(Path, "rename", fail_publish)
    else:
        update_index = store._update_session_index

        def fail_index(session_id, dir_name):
            update_index(session_id, dir_name)
            raise OSError("发布索引后失败")

        monkeypatch.setattr(store, "_update_session_index", fail_index)

    with pytest.raises(AdapterError) as exc_info:
        store.clone_from_source("source", "target")
    assert exc_info.value.code == "MATERIAL_CLONE_FAILED"
    assert {p.relative_to(target_dir): p.read_bytes() for p in target_dir.rglob("*") if p.is_file()} == before_files
    assert index_file.read_bytes() == before_index
    assert store.get_catalog("target") == before_catalog
    assert not list(ppt_dir.glob(".clone-*"))
    assert not list(ppt_dir.glob(".previous-*"))


@pytest.mark.parametrize("runtime", ["fastapi", "standalone"])
@pytest.mark.parametrize("source_host", ["word", "excel"])
def test_runtime_ppt_clone_keeps_docx_and_catalog_in_one_source_version(temp_roots, monkeypatch, runtime, source_host):
    if runtime == "fastapi":
        from app.api import word, excel, ppt
        service = word.material_import_service
        excel_store = excel.excel_material_store
        ppt_store = ppt.ppt_material_store
    else:
        import standalone_adapter
        service = standalone_adapter.WORD_MATERIAL_IMPORT_SERVICE
        excel_store = standalone_adapter.EXCEL_MATERIAL_STORE
        ppt_store = standalone_adapter.PPT_MATERIAL_STORE

    word_dir, excel_dir, ppt_dir = temp_roots
    monkeypatch.setattr(service._store, "base_dir", word_dir)
    monkeypatch.setattr(excel_store, "base_dir", excel_dir)
    monkeypatch.setattr(excel_store, "word_base_dir", word_dir)
    monkeypatch.setattr(ppt_store, "base_dir", ppt_dir)
    monkeypatch.setattr(ppt_store, "word_base_dir", word_dir)
    monkeypatch.setattr(ppt_store, "excel_base_dir", excel_dir)
    monkeypatch.setattr(service, "_materials", {})
    monkeypatch.setattr(service, "_session_catalogs", {})
    monkeypatch.setattr(excel_store, "_memory_catalogs", {})
    monkeypatch.setattr(ppt_store, "_memory_catalogs", {})
    b64 = base64.b64encode(build_docx()).decode("ascii")
    if source_host == "word":
        imported = service.import_material({
            "documentSessionId": "source", "fileName": "旧资料.docx", "contentBase64": b64,
        })
    else:
        imported = excel_store.import_material("source", "", "旧资料.docx", b64)
    material_id = imported["materialId"]
    new_bytes = build_docx(DOCUMENT_XML.replace("新一代".encode(), "更新后的".encode()))
    started = threading.Event()
    finished = threading.Event()
    errors = []

    def update_source():
        started.set()
        try:
            payload = {
                "documentSessionId": "source", "fileName": "新资料.docx",
                "contentBase64": base64.b64encode(new_bytes).decode("ascii"),
            }
            if source_host == "word":
                service.update_material(material_id, payload)
            else:
                excel_store.update_material("source", material_id, payload["fileName"], payload["contentBase64"])
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    writer = threading.Thread(target=update_source)
    copy2 = shutil.copy2

    def copy_then_update(source, destination, *args, **kwargs):
        result = copy2(source, destination, *args, **kwargs)
        if Path(source).suffix == ".docx" and not writer.is_alive() and not started.is_set():
            writer.start()
            assert started.wait(2)
            finished.wait(0.2)
        return result

    monkeypatch.setattr(shutil, "copy2", copy_then_update)
    try:
        cloned = ppt_store.clone_from_source("source", "target")
    finally:
        writer.join(timeout=3)
    assert finished.is_set(), "来源更新与克隆发生死锁"
    assert not errors
    target_dir = ppt_store._get_dir_for_session("target")
    assert (target_dir / "files" / (material_id + ".docx")).read_bytes() == base64.b64decode(b64)
    assert cloned["documents"][0]["fileName"] == "旧资料.docx"
    view = json.loads((target_dir / "materials" / (material_id + ".json")).read_text(encoding="utf-8"))
    assert view["fileName"] == "旧资料.docx"


def test_ppt_full_document_requires_original_and_preserves_header(temp_roots):
    word_dir, excel_dir, ppt_dir = temp_roots
    store = PptMaterialStore(ppt_dir, word_dir, excel_dir)
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES_XML)
        archive.writestr('word/document.xml', DOCUMENT_XML)
        archive.writestr('word/header1.xml', DOCUMENT_XML.replace('第一章'.encode(), '页眉独立事实'.encode()))
    result = store.import_request({'documentSessionId': 'full', 'fileName': '材料.docx',
                                   'contentBase64': base64.b64encode(output.getvalue()).decode()})
    whole = store.get_full_document('full', result['materialId'])
    assert whole['complete']
    assert any('页眉独立事实' in b.get('text', '') for b in whole['blocks'])
    (store._get_dir_for_session('full') / 'files' / (result['materialId'] + '.docx')).unlink()
    with pytest.raises(AdapterError) as error:
        store.get_full_document('full', result['materialId'])
    assert error.value.code == 'MATERIAL_NOT_FOUND'


def test_ppt_doc_conversion_is_session_bound_and_cleans_up(temp_roots):
    store = PptMaterialStore(temp_roots[2], temp_roots[0], temp_roots[1])
    stage = store.import_request({'documentSessionId': 'a', 'fileName': '材料.doc',
                                  'contentBase64': base64.b64encode(bytes.fromhex('d0cf11e0a1b11ae1')).decode()})
    with pytest.raises(AdapterError):
        store.import_request({'documentSessionId': 'b', 'conversionId': stage['conversionId']})
    Path(stage['targetPath']).write_bytes(build_docx())
    result = store.import_request({'documentSessionId': 'a', 'conversionId': stage['conversionId']})
    assert result['fileName'] == '材料.doc'
    assert store.get_full_document('a', result['materialId'])['complete']
    assert not Path(stage['sourcePath']).exists()


def test_source_image_is_loaded_on_demand_and_rejects_other_session(temp_roots):
    from tests.test_word_material_document import document, p, PNG
    store = PptMaterialStore(temp_roots[2], temp_roots[0], temp_roots[1])
    raw = document(p('图示') + '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>', {
        'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG})
    imported = store.import_request({'documentSessionId': 'a', 'fileName': '图.docx', 'contentBase64': base64.b64encode(raw).decode()})
    catalog, images = store.prepare_full_catalog('a')
    assert 'imageDataUri' not in json.dumps(catalog)
    mid = imported['materialId']
    version = catalog['documents'][0]['updatedAt']
    image = store.get_source_image('a', mid, images[0]['imageId'], version)
    assert base64.b64decode(image['imageDataUri'].split(',')[1]) == PNG
    with pytest.raises(AdapterError):
        store.get_source_image('other', mid, images[0]['imageId'], version)
    with pytest.raises(AdapterError):
        store.get_source_image('a', mid, images[0]['imageId'], 'old-version')
