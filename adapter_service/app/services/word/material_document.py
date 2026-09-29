"""Read complete Word text and original images without selecting relevant excerpts."""
import io
import posixpath
from typing import Dict, List
from xml.etree import ElementTree as ET
import zipfile

from app.services.ppt.docx_security import validate_docx_bytes

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
V = 'urn:schemas-microsoft-com:vml'


def extract_document(content: bytes, file_name: str, read_shape_text: bool = False) -> dict:
    """Return ordered blocks, original image bytes and explicit unread objects.

    Package security is checked before reading any XML or image. DOC conversion
    belongs to the import boundary; this reader accepts the converted DOCX.
    """
    validated = validate_docx_bytes(content)
    blocks: List[dict] = []
    images: Dict[str, dict] = {}
    unread: List[dict] = []
    note_definitions = set()

    def missing(part, path, kind):
        unread.append({'part': part, 'path': list(path), 'kind': kind})

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        parts = ['word/document.xml'] + sorted(n for n in names if
            n.startswith('word/') and n.endswith('.xml') and
            (posixpath.basename(n).startswith(('header', 'footer')) or
             posixpath.basename(n) in ('footnotes.xml', 'endnotes.xml')))
        for name in sorted(names):
            if '/embeddings/' in name:
                missing(name, (), 'embedded_attachment')
        for part in parts:
            rel_path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            relationships = {}
            if rel_path in names:
                relationships = {e.get('Id'): e.attrib for e in ET.fromstring(archive.read(rel_path))}

            def walk(node, path=(), table_path=(), cell=None):
                tag = node.tag.rsplit('}', 1)[-1]
                source = {'part': part, 'path': list(path), 'tablePath': list(table_path)}
                if tag in ('footnote', 'endnote'):
                    note_definitions.add((tag, node.get('{%s}id' % W, '')))
                    cell = dict(cell or {}, noteId=node.get('{%s}id' % W, ''), noteType=tag)
                if cell:
                    source.update(cell)
                if tag in ('footnoteReference', 'endnoteReference'):
                    blocks.append({'kind': 'note_reference', 'noteId': node.get('{%s}id' % W, ''),
                                   'noteType': tag.replace('Reference', ''), 'source': source})
                    return
                if tag in ('group', 'line', 'arc', 'curve', 'polyline', 'rect', 'oval', 'roundrect', 'wsp', 'cxnSp', 'sp', 'grpSp'):
                    missing(part, path, 'vector_drawing')
                    if read_shape_text:
                        for index, child in enumerate(node):
                            walk(child, path + (index,), table_path, cell)
                    return
                if tag in ('oMath', 'object', 'chart', 'altChunk', 'del', 'ins'):
                    missing(part, path, tag)
                    return
                if tag == 'AlternateContent':
                    # Choosing a representation without checking support can hide
                    # content; disclose it until a reliable renderer is available.
                    missing(part, path, tag)
                    return
                if read_shape_text and node.tag == '{%s}p' % A:
                    text = ''.join(child.text or '' for child in node.iter() if child.tag == '{%s}t' % A)
                    if text:
                        blocks.append({'kind': 'paragraph', 'text': text, 'source': source})
                    return
                if tag == 'tbl':
                    from app.services.word.material_import import _grid_span, MATERIAL_IMPORT_MAX_TABLE_COLUMNS, MATERIAL_IMPORT_MAX_TABLE_CELLS
                    from app.core.errors import AdapterError
                    rows = [e for e in node if e.tag == '{%s}tr' % W]
                    for row_index, row in enumerate(rows):
                        column = 0
                        for cell_index, table_cell in enumerate(e for e in row if e.tag == '{%s}tc' % W):
                            span = _grid_span(table_cell)
                            if column + span > MATERIAL_IMPORT_MAX_TABLE_COLUMNS or (column + span) * (row_index + 1) > MATERIAL_IMPORT_MAX_TABLE_CELLS:
                                raise AdapterError('MATERIAL_TABLE_OVER_LIMIT', '表格展开规模超过当前上限，未截断内容。', status_code=413)
                            merge = table_cell.find('{%s}tcPr/{%s}vMerge' % (W, W))
                            properties = dict(cell or {}, row=row_index, column=column, columnSpan=span)
                            if merge is not None:
                                properties['verticalMerge'] = merge.get('{%s}val' % W, 'continue')
                            before = len(blocks)
                            walk(table_cell, path + (row_index, cell_index), path, properties)
                            if len(blocks) == before:
                                blocks.append({'kind': 'table_cell', 'text': '', 'source': dict(properties, part=part, path=list(path + (row_index, cell_index)), tablePath=list(path))})
                            column += span
                    return
                if node.tag in ('{%s}blip' % A, '{%s}imagedata' % V):
                    rid = node.get('{%s}embed' % R) or node.get('{%s}id' % R)
                    rel = relationships.get(rid, {})
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(part), rel.get('Target', '')))
                    if not rid or not rel.get('Type', '').endswith('/image') or target not in names:
                        missing(part, path, 'image')
                        return
                    data = archive.read(target)
                    mime = _image_mime(data)
                    if not mime:
                        missing(part, path, 'unsupported_image')
                        return
                    if target not in images:
                        images[target] = {'imageId': 'image-%d' % (len(images) + 1), 'mimeType': mime,
                                          'data': data, 'anchors': []}
                    image = images[target]
                    image['anchors'].append(source)
                    blocks.append({'kind': 'image', 'imageId': image['imageId'], 'source': source})
                    return
                if tag == 'p' and node.tag == '{%s}p' % W:
                    from app.services.word.material_import import _heading_level
                    level = _heading_level(node, validated.style_names)
                    text = []
                    def flush():
                        if text:
                            block = {'kind': 'heading' if level else 'paragraph', 'text': ''.join(text), 'source': dict(source)}
                            if level:
                                block['level'] = level
                            blocks.append(block)
                            text.clear()
                    def inline(element, inline_path):
                        for index, child in enumerate(element):
                            child_path = inline_path + (index,)
                            child_tag = child.tag.rsplit('}', 1)[-1]
                            if child_tag in ('p', 'txbxContent', 'drawing', 'pict', 'object', 'oMath', 'AlternateContent', 'del', 'ins', 'footnoteReference', 'endnoteReference'):
                                flush()
                                walk(child, child_path, table_path, cell)
                            elif child.tag == '{%s}t' % W:
                                text.append(child.text or '')
                            elif child.tag in ('{%s}br' % W, '{%s}cr' % W):
                                text.append('\n')
                            elif child.tag == '{%s}tab' % W:
                                text.append('\t')
                            else:
                                inline(child, child_path)
                    inline(node, path)
                    flush()
                    return
                if tag in ('drawing', 'pict'):
                    known = any(e.tag in ('{%s}blip' % A, '{%s}imagedata' % V, '{%s}txbxContent' % W) for e in node.iter())
                    if not known:
                        missing(part, path, 'drawing')
                for index, child in enumerate(node):
                    walk(child, path + (index,), table_path, cell)

            walk(ET.fromstring(archive.read(part)))
    for block in blocks:
        if block['kind'] == 'note_reference' and (block['noteType'], block['noteId']) not in note_definitions:
            missing(block['source']['part'], block['source']['path'], 'missing_note')
    for index, block in enumerate(blocks):
        block['blockId'] = 'full-block-%d' % (index + 1)
    return {'blocks': blocks, 'images': list(images.values()), 'unreadObjects': unread,
            'complete': not unread}


def _image_mime(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return ''
