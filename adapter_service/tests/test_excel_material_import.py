import base64
import json
from io import BytesIO
import shutil
import tempfile
import zipfile
from pathlib import Path
import pytest

from app.core.errors import AdapterError
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
      <w:r><w:t>第一章 总体实施计划</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>工作事项包括系统设计与安全加固。由架构组于2026年10月完成，交付总体设计方案。</w:t></w:r>
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
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_excel_mat_"))
    word_dir = temp_dir / "word_materials"
    excel_dir = temp_dir / "excel_materials"
    word_dir.mkdir(parents=True, exist_ok=True)
    excel_dir.mkdir(parents=True, exist_ok=True)
    yield word_dir, excel_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel_material_store_import_and_catalog(temp_roots):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)

    raw_bytes = build_docx()
    b64 = base64.b64encode(raw_bytes).decode("ascii")

    res = store.import_material(
        session_id="excel_sess_1",
        doc_identity="full:/path/to/sheet1.xlsx",
        file_name="总体实施计划.docx",
        content_base64=b64,
    )
    assert res["materialId"] is not None
    assert res["fileName"] == "总体实施计划.docx"
    assert res["readableCharacterCount"] > 0

    catalog = store.get_catalog("excel_sess_1")
    assert catalog["totalDocuments"] == 1
    assert catalog["totalCharacters"] == res["readableCharacterCount"]
    assert len(catalog["documents"]) == 1
    assert catalog["documents"][0]["materialId"] == res["materialId"]


def test_excel_material_store_reusable_sources_and_clone_independence(temp_roots):
    word_dir, excel_dir = temp_roots
    word_store = WordMaterialStore(base_dir=word_dir)
    word_service = WordMaterialImportService(state_dir=word_dir)
    excel_store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)

    # 1. Prepare word material
    raw_docx = build_docx()
    imported = word_service.import_material({
        "fileName": "方案文档.docx",
        "contentBase64": base64.b64encode(raw_docx).decode("ascii"),
        "documentSessionId": "word_sess_100",
        "documentIdentity": "full:/docs/方案.docx",
    })
    mat_id = imported["materialId"]

    # 2. List reusable sources
    sources = excel_store.list_reusable_sources()
    assert len(sources) >= 1
    word_source = next((s for s in sources if s["sourceSessionId"] == "word_sess_100"), None)
    assert word_source is not None
    assert word_source["host"] == "word"
    assert word_source["displayName"] == "方案.docx"
    assert word_source["totalDocuments"] == 1

    # 3. Clone into Excel session
    cloned_catalog = excel_store.clone_from_source(
        source_session_id="word_sess_100",
        target_session_id="excel_sess_200",
        target_doc_identity="full:/sheets/台账.xlsx",
    )
    assert cloned_catalog["documentSessionId"] == "excel_sess_200"
    assert cloned_catalog["totalDocuments"] == 1
    cloned_mat_id = cloned_catalog["documents"][0]["materialId"]

    # 4. Modify / Delete in Excel session and verify Word session is completely unaffected!
    excel_store.delete_material("excel_sess_200", cloned_mat_id)
    target_catalog = excel_store.get_catalog("excel_sess_200")
    assert target_catalog["totalDocuments"] == 0

    # Source word catalog must be fully intact
    source_catalog = word_store.load_session_catalog("word_sess_100")
    assert source_catalog is not None
    assert source_catalog["totalDocuments"] == 1
    assert word_store.load_material_view(mat_id) is not None


def test_excel_material_store_update_and_limits(temp_roots):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)

    raw_bytes = build_docx()
    res = store.import_material(
        session_id="excel_sess_3",
        doc_identity="full:/path/to/test.xlsx",
        file_name="初始.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )
    mat_id = res["materialId"]

    # Update with new docx
    new_doc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>更新后的内容：工作事项A与B</w:t></w:r></w:p>
  </w:body>
</w:document>""".encode("utf-8")
    new_bytes = build_docx(document_xml=new_doc_xml)

    updated = store.update_material(
        session_id="excel_sess_3",
        material_id=mat_id,
        file_name="更新版.docx",
        content_base64=base64.b64encode(new_bytes).decode("ascii"),
    )
    assert updated["materialId"] == mat_id
    assert updated["fileName"] == "更新版.docx"
    assert updated["updatedAt"] > res["updatedAt"]

    cat = store.get_catalog("excel_sess_3")
    assert cat["totalDocuments"] == 1
    assert cat["documents"][0]["fileName"] == "更新版.docx"


def test_excel_material_store_bind_document(temp_roots):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)

    raw_bytes = build_docx()
    store.import_material(
        session_id="unsaved_sess_99",
        doc_identity="",
        file_name="资料.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    # Bind to newly saved path
    bound = store.bind_document(
        old_session_id="unsaved_sess_99",
        new_session_id="saved_sess_100",
        new_doc_identity="full:/saved/path/工作簿1.xlsx",
    )
    assert bound["totalDocuments"] == 1

    cat = store.get_catalog("saved_sess_100")
    assert cat["totalDocuments"] == 1
    assert cat["documentSessionId"] == "saved_sess_100"


def test_update_keeps_other_material_fragment_sources(temp_roots):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)
    b64 = base64.b64encode(build_docx()).decode("ascii")
    first = store.import_material("sources", "", "first.docx", b64)
    second = store.import_material("sources", "", "second.docx", b64)
    first_ids = {f["fragmentId"] for f in first["fragments"]}
    store.update_material("sources", second["materialId"], "updated.docx", b64)
    catalog = store.get_catalog("sources")
    assert len({f["fragmentId"] for f in catalog["fragmentsList"]}) == len(catalog["fragmentsList"])
    assert all(catalog["fragments"][fid]["materialId"] == first["materialId"] for fid in first_ids)


def test_clone_self_is_rejected_without_removing_files(temp_roots):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)
    raw = build_docx()
    imported = store.import_material("self", "", "source.docx", base64.b64encode(raw).decode("ascii"))
    source = store._get_dir_for_session("self") / "files" / (imported["materialId"] + ".docx")
    with pytest.raises(AdapterError):
        store.clone_from_source("self", "self")
    assert source.read_bytes() == raw


def test_clone_copy_failure_keeps_target_materials(temp_roots, monkeypatch):
    word_dir, excel_dir = temp_roots
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)
    raw = build_docx()
    b64 = base64.b64encode(raw).decode("ascii")
    store.import_material("source", "", "source.docx", b64)
    target = store.import_material("target", "", "target.docx", b64)
    target_file = store._get_dir_for_session("target") / "files" / (target["materialId"] + ".docx")
    def fail_copy(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(shutil, "copy2", fail_copy)
    with pytest.raises(OSError):
        store.clone_from_source("source", "target")
    assert target_file.read_bytes() == raw
    assert store.get_catalog("target")["documents"][0]["fileName"] == "target.docx"


def test_word_source_clone_waits_for_source_store_write(temp_roots):
    import threading
    word_dir, excel_dir = temp_roots
    word = WordMaterialImportService(state_dir=word_dir)
    word.import_material({"documentSessionId": "word-lock", "fileName": "source.docx",
                          "contentBase64": base64.b64encode(build_docx()).decode("ascii")})
    store = ExcelMaterialStore(base_dir=excel_dir, word_base_dir=word_dir)
    store.word_store = word._store
    done = threading.Event()
    errors = []
    def clone():
        try:
            store.clone_from_source("word-lock", "target-lock")
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()
    worker = threading.Thread(target=clone)
    with word._store._lock:
        worker.start()
        completed_while_writing = done.wait(0.1)
    worker.join(2)
    assert not completed_while_writing
    assert not errors
    assert done.is_set()
    assert store.get_catalog("target-lock")["totalDocuments"] == 1
