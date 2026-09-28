"""Full-document extraction must not omit non-body text or original images."""
import base64

import pytest

from tests.test_word_material_import import build_docx

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')


def document(body, parts=None):
    xml = '<w:document xmlns:w="%s" xmlns:r="%s" xmlns:a="%s"><w:body>%s</w:body></w:document>' % (W, R, A, body)
    return build_docx(parts, xml.encode())


def p(text):
    return '<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % text


def extract(content):
    from app.services.word import material_document
    return material_document.extract_document(content, '参考.docx')


def test_extract_all_document_parts():
    parts = {'word/header1.xml': ('<w:hdr xmlns:w="%s">%s</w:hdr>' % (W, p('页眉'))).encode(),
             'word/footnotes.xml': ('<w:footnotes xmlns:w="%s"><w:footnote w:id="1">%s</w:footnote></w:footnotes>' % (W, p('脚注'))).encode()}
    body = p('文首') + '<w:tbl><w:tr><w:tc>' + p('外表') + '<w:tbl><w:tr><w:tc>' + p('内表') + '</w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>'
    body += '<w:p><w:r><w:pict><w:txbxContent>' + p('文本框') + '</w:txbxContent></w:pict></w:r></w:p>' + p('文尾')
    result = extract(document(body, parts))
    texts = [b.get('text', '') for b in result['blocks']]
    for word in ('文首', '文尾', '外表', '内表', '文本框', '页眉', '脚注'):
        assert sum(t.count(word) for t in texts) == 1
    assert result['complete'] is True
    inner = next(b for b in result['blocks'] if b.get('text') == '内表')
    assert inner['source']['tablePath']


def test_image_bytes_and_anchors_preserved():
    image = '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
    parts = {'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG}
    result = extract(document(p('之前') + image + p('之间') + image + p('之后'), parts))
    assert result['complete'] is True
    assert len(result['images']) == 1
    assert result['images'][0]['data'] == PNG
    assert len(result['images'][0]['anchors']) == 2
    assert [b['kind'] for b in result['blocks']] == ['paragraph', 'image', 'paragraph', 'image', 'paragraph']


@pytest.mark.parametrize('body,parts', [
    ('<w:p><w:r><w:drawing><a:blip r:embed="missing"/></w:drawing></w:r></w:p>', {}),
    (p('文字'), {'word/embeddings/object.bin': b'object'}),
    ('<w:p xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath></w:p>', {}),
])
def test_unread_objects_block_readiness(body, parts):
    result = extract(document(body, parts))
    assert result['complete'] is False
    assert result['unreadObjects']


def test_import_reports_complete_reading_and_reload_keeps_original_image(tmp_path):
    from app.services.word.material_import import WordMaterialImportService
    from tests.test_word_material_import import upload_payload
    parts = {'word/header1.xml': ('<w:hdr xmlns:w="%s">%s</w:hdr>' % (W, p('额外页眉'))).encode()}
    service = WordMaterialImportService(state_dir=tmp_path)
    view = service.import_material(upload_payload(document(p('正文'), parts)))
    assert view['fullReading']['complete'] is True
    assert view['limits']['readableCharacterCount'] == 6
    reloaded = WordMaterialImportService(state_dir=tmp_path)
    whole = reloaded.read_complete_material(view['materialId'], 'doc-session-1')
    assert [b['text'] for b in whole['blocks']] == ['正文', '额外页眉']
    from app.core.errors import AdapterError
    with pytest.raises(AdapterError):
        reloaded.read_complete_material(view['materialId'], 'other-session')


def test_table_cell_coordinates_and_span_survive_full_input():
    body = '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' + p('合并列') + '</w:tc><w:tc>' + p('第三列') + '</w:tc></w:tr><w:tr><w:tc>' + p('次行') + '</w:tc></w:tr></w:tbl>'
    result = extract(document(body))
    cells = {b['text']: b['source'] for b in result['blocks']}
    assert cells['合并列']['row'] == 0
    assert cells['合并列']['columnSpan'] == 2
    assert cells['第三列']['column'] == 2
    assert cells['次行']['row'] == 1


def test_vertical_merge_and_footnote_links_are_not_lost():
    parts = {'word/footnotes.xml': ('<w:footnotes xmlns:w="%s"><w:footnote w:id="7">%s</w:footnote></w:footnotes>' % (W, p('附注事实'))).encode()}
    body = '<w:tbl><w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>' + p('责任部门') + '</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr>' + p('事项') + '</w:tc></w:tr></w:tbl><w:p><w:r><w:t>来源</w:t><w:footnoteReference w:id="7"/></w:r></w:p>'
    result = extract(document(body, parts))
    assert next(b for b in result['blocks'] if b.get('text') == '责任部门')['source']['verticalMerge'] == 'restart'
    assert next(b for b in result['blocks'] if b.get('text') == '事项')['source']['verticalMerge'] == 'continue'
    reference = next(b for b in result['blocks'] if b['kind'] == 'note_reference')
    assert reference['noteId'] == '7'
    assert next(b for b in result['blocks'] if b.get('text') == '附注事实')['source']['noteId'] == '7'


def test_grouped_image_does_not_hide_unread_vector_lines():
    image = '<w:p xmlns:v="urn:schemas-microsoft-com:vml"><w:r><w:pict><v:group><v:shape><v:imagedata r:id="rId1"/></v:shape><v:line from="0,0" to="100,100"/></v:group></w:pict></w:r></w:p>'
    parts = {'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG}
    result = extract(document(image, parts))
    assert result['complete'] is False
    assert result['unreadObjects']


def test_inline_picture_retains_text_before_and_after_its_anchor():
    body = '<w:p><w:r><w:t>前文</w:t></w:r><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r><w:r><w:t>后文</w:t></w:r></w:p>'
    parts = {'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG}
    result = extract(document(body, parts))
    assert [b.get('text', b['kind']) for b in result['blocks']] == ['前文', 'image', '后文']


def test_missing_note_and_empty_merged_cell_are_explicit():
    body = '<w:tbl><w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr></w:tbl><w:p><w:r><w:footnoteReference w:id="99"/></w:r></w:p>'
    result = extract(document(body))
    assert any(b['source'].get('verticalMerge') == 'continue' for b in result['blocks'])
    assert result['complete'] is False
    assert any(o['kind'] == 'missing_note' for o in result['unreadObjects'])
