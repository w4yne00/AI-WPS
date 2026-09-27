import base64
import json
from io import BytesIO
import shutil
import tempfile
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
