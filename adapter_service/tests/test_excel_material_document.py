import base64
from io import BytesIO
import zipfile
import pytest
from app.core.errors import AdapterError
from app.services.excel.material_store import ExcelMaterialStore


def xlsx_bytes():
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('_rels/.rels', '<Relationships><Relationship Id="w" Type="x/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="台账" r:id="a"/><sheet name="隐藏" state="hidden" r:id="b"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="a" Type="x/worksheet" Target="worksheets/a.xml"/><Relationship Id="b" Type="x/worksheet" Target="worksheets/b.xml"/></Relationships>')
        z.writestr('xl/worksheets/a.xml', '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>开头任务</t></is></c><c r="B1"><f>1+2</f><v>3</v></c><c r="C1"><f>SUM(B1)</f></c></row></sheetData><mergeCells><mergeCell ref="A2:B2"/></mergeCells></worksheet>')
        z.writestr('xl/worksheets/b.xml', '<worksheet><sheetData><row r="3" hidden="1"><c r="A3" t="inlineStr"><is><t>文尾任务</t></is></c></row></sheetData></worksheet>')
    return out.getvalue()


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'gb18030'])
def test_csv_full_import_preserves_quoted_lines_and_empty_values(tmp_path, encoding):
    store = ExcelMaterialStore(base_dir=tmp_path)
    raw = '任务,备注,空值\r\n开头,"中间\n事项",\r\n文尾,结束,\r\n'.encode(encoding)
    view = store.import_material('s', '', '材料.csv', base64.b64encode(raw).decode())
    whole = store.get_full_document('s', view['materialId'])
    assert [b['values'] for b in whole['blocks']] == [['任务', '备注', '空值'], ['开头', '中间\n事项', ''], ['文尾', '结束', '']]
    assert whole['complete']


def test_xlsx_full_import_includes_hidden_and_formula_state(tmp_path):
    store = ExcelMaterialStore(base_dir=tmp_path)
    view = store.import_material('s', '', '资料.xlsx', base64.b64encode(xlsx_bytes()).decode())
    whole = store.get_full_document('s', view['materialId'])
    text = '\n'.join(b.get('text', '') for b in whole['blocks'])
    assert all(t in text for t in ['开头任务', '文尾任务', '1+2', 'SUM(B1)', '未计算', 'A2:B2'])
    assert any(b['source'].get('sheetName') == '隐藏' for b in whole['blocks'])
    assert view['fullReading']['hiddenContentIncluded']


def test_retained_original_required_and_corruption_is_not_ignored(tmp_path):
    store = ExcelMaterialStore(base_dir=tmp_path)
    with pytest.raises(AdapterError):
        store.import_material('s', '', '坏.xlsx', base64.b64encode(b'not zip').decode())
    assert store.get_catalog('s')['totalDocuments'] == 0
    view = store.import_material('s', '', '材料.csv', base64.b64encode(b'first,last').decode())
    for path in tmp_path.glob('*/files/*'):
        path.unlink()
    with pytest.raises(AdapterError, match='重新导入'):
        store.get_full_document('s', view['materialId'])


def test_doc_conversion_is_session_bound_and_cleans_up(tmp_path):
    from pathlib import Path
    def build_docx():
        out = BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>任务正文</w:t></w:r></w:p></w:body></w:document>')
        return out.getvalue()
    store = ExcelMaterialStore(base_dir=tmp_path)
    stage = store.import_request({'documentSessionId': 's', 'fileName': '材料.doc',
                                  'contentBase64': base64.b64encode(bytes.fromhex('d0cf11e0a1b11ae1') + b'doc').decode()})
    with pytest.raises(AdapterError):
        store.import_request({'documentSessionId': 'other', 'conversionId': stage['conversionId']})
    Path(stage['targetPath']).write_bytes(build_docx())
    view = store.import_request({'documentSessionId': 's', 'conversionId': stage['conversionId']})
    assert view['fileName'] == '材料.doc'
    assert store.get_full_document('s', view['materialId'])['blocks']
    assert not Path(stage['sourcePath']).exists()
    with pytest.raises(AdapterError):
        store.import_request({'documentSessionId': 's', 'conversionId': stage['conversionId']})


def test_delivery_includes_complete_reader_and_ledger_icon():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sources = (root / 'packaging/delivery-sources-v0260-preview1.json').read_text()
    assert 'adapter_service/app/services/excel/material_document.py' in sources
    assert 'assets/icon-excel-material-ledger.png' in sources


def test_xlsx_dates_keep_display_meaning_and_epoch():
    from app.services.excel.material_document import extract_document
    source = xlsx_bytes()
    for epoch, expected in [('0', '2026-09-29'), ('1', '2030-09-30')]:
        out = BytesIO()
        with zipfile.ZipFile(BytesIO(source)) as old, zipfile.ZipFile(out, 'w') as new:
            for name in old.namelist():
                value = old.read(name)
                if name == 'xl/workbook.xml':
                    value = value.replace(b'<sheets>', ('<workbookPr date1904="'+epoch+'"/><sheets>').encode())
                if name == 'xl/_rels/workbook.xml.rels':
                    value = value.replace(b'</Relationships>', b'<Relationship Id="style" Type="x/styles" Target="styles.xml"/></Relationships>')
                if name == 'xl/worksheets/a.xml':
                    value = value.replace(b'<c r="B1">', b'<c r="B1" s="1">').replace(b'<f>1+2</f><v>3</v>', b'<v>46294</v>')
                new.writestr(name, value)
            new.writestr('xl/styles.xml', '<styleSheet><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        whole = extract_document(out.getvalue(), '日期.xlsx')
        assert expected in '\n'.join(b.get('text','') for b in whole['blocks'])


def test_word_shape_text_is_not_lost_in_text_mode():
    from app.services.excel.material_document import extract_document
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml"><w:body><w:p><w:r><w:pict><v:rect><v:textbox><w:txbxContent><w:p><w:r><w:t>文本框内责任部门</w:t></w:r></w:p></w:txbxContent></v:textbox></v:rect></w:pict></w:r></w:p></w:body></w:document>')
    whole = extract_document(out.getvalue(), '文本框.docx')
    assert any('文本框内责任部门' in b.get('text','') for b in whole['blocks'])


def test_shared_formula_preserves_master_and_coordinates():
    from app.services.excel.material_document import extract_document
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(xlsx_bytes())) as old, zipfile.ZipFile(out, 'w') as new:
        for name in old.namelist():
            value = old.read(name)
            if name == 'xl/worksheets/a.xml':
                value = value.replace(b'<f>1+2</f>', b'<f t="shared" si="0" ref="B1:C1">1+2</f>').replace(b'<f>SUM(B1)</f>', b'<f t="shared" si="0"/>')
            new.writestr(name, value)
    whole = extract_document(out.getvalue(), '公式.xlsx')
    follower = next(b for b in whole['blocks'] if b.get('source',{}).get('address') == 'C1')
    assert all(t in follower['text'] for t in ['1+2', 'B1:C1', '未计算'])


def test_xlsx_images_allow_internal_parent_relationships_but_not_escape():
    from app.services.excel.material_document import extract_document, _resolve_part_path
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(xlsx_bytes())) as old, zipfile.ZipFile(out, 'w') as new:
        for name in old.namelist():
            new.writestr(name, old.read(name))
        new.writestr('xl/worksheets/_rels/a.xml.rels', '<Relationships><Relationship Id="d" Type="x/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
        new.writestr('xl/drawings/drawing1.xml', '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><blip r:embed="img"/></drawing>')
        new.writestr('xl/drawings/_rels/drawing1.xml.rels', '<Relationships><Relationship Id="img" Type="x/image" Target="../media/a.png"/></Relationships>')
        new.writestr('xl/media/a.png', b'\x89PNG\r\n\x1a\nimage')
    whole = extract_document(out.getvalue(), '图片.xlsx')
    assert len(whole['images']) == 1
    assert whole['images'][0]['data'] == b'\x89PNG\r\n\x1a\nimage'
    with pytest.raises(ValueError):
        _resolve_part_path('xl/worksheets/a.xml', '../../../outside')
    with pytest.raises(ValueError):
        _resolve_part_path('xl/worksheets/a.xml', 'https://host/image.png')


def test_xlsx_header_vml_image_is_not_silently_omitted():
    from app.services.excel.material_document import extract_document
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(xlsx_bytes())) as old, zipfile.ZipFile(out, 'w') as new:
        for name in old.namelist():
            new.writestr(name, old.read(name))
        new.writestr('xl/worksheets/_rels/a.xml.rels', '<Relationships><Relationship Id="h" Type="x/vmlDrawing" Target="../drawings/header.vml"/></Relationships>')
        new.writestr('xl/drawings/header.vml', '<xml xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><imagedata r:id="img"/></xml>')
        new.writestr('xl/drawings/_rels/header.vml.rels', '<Relationships><Relationship Id="img" Type="x/image" Target="../media/header.png"/></Relationships>')
        new.writestr('xl/media/header.png', b'\x89PNG\r\n\x1a\nheader')
    whole = extract_document(out.getvalue(), '页眉图.xlsx')
    assert len(whole['images']) == 1
    assert whole['images'][0]['data'].endswith(b'header')
