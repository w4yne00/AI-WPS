"""Complete ledger materials with source coordinates; never execute workbook code."""
import csv
import io
import json
import re
import posixpath
import unicodedata
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
import zipfile
from pathlib import Path

from app.core.errors import AdapterError
from app.services.word.material_document import extract_document as read_word, _image_mime
from app.services.word.material_import import MATERIAL_IMPORT_MAX_TABLE_COLUMNS, MATERIAL_IMPORT_MAX_TABLE_CELLS
from app.services.ppt.docx_security import DOCX_MAX_PACKAGE_BYTES, DocxSecurityError
MAX_XLSX_WORKSHEET_ELEMENTS = 200000
MAX_XLSX_WORKSHEET_DEPTH = 32


def _read_xml(archive, name):
    content = archive.read(name)
    if b'<!doctype' in content.lower() or b'<!entity' in content.lower():
        raise ValueError('XLSX 包含不安全的 XML 声明。')
    root = ET.fromstring(content)
    pending, count = [(root, 1)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_XLSX_WORKSHEET_ELEMENTS or depth > MAX_XLSX_WORKSHEET_DEPTH:
            raise ValueError('XLSX XML 结构超过安全预算。')
        pending.extend((child, depth + 1) for child in node)
    return root


def _resolve_part_path(base, target):
    parsed = urlsplit(target)
    if not target or "\\" in target or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('XLSX 包含外部或无效的关系。')
    path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(base), target))
    if path == '..' or path.startswith('../') or path.startswith('/'):
        raise ValueError('XLSX 关系超出文件包范围。')
    return path


def _relationship_part_path(part):
    return posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')


def _office_document_path(root, names):
    paths = [_resolve_part_path('', r.get('Target', '')) for r in root if r.get('Type', '').endswith('/officeDocument')]
    if len(paths) != 1 or paths[0] not in names:
        raise ValueError('XLSX 主工作簿关系无效。')
    return paths[0]


def _validate_package(archive):
    entries = archive.infolist()
    if len(entries) > 256:
        raise ValueError('XLSX 包含过多内部文件。')
    seen, expanded = set(), 0
    for entry in entries:
        name = entry.filename
        normalized = unicodedata.normalize('NFKC', name)
        if (not name or name.startswith('/') or "\\" in name or ':' in name
                or any(p in ('', '.', '..') for p in name.split('/'))
                or normalized != name or normalized.casefold() in seen or entry.flag_bits & 1):
            raise ValueError('XLSX 包含不安全的内部文件路径。')
        seen.add(normalized.casefold())
        expanded += entry.file_size
        if expanded > 20 * 1024 * 1024 or (entry.file_size > 1024 * 1024 and entry.file_size > 100 * max(entry.compress_size, 1)):
            raise ValueError('XLSX 解压内容超过安全容量。')
        with archive.open(entry) as stream:
            read = 0
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                read += len(chunk)
                if read > entry.file_size or read > 20 * 1024 * 1024:
                    raise ValueError('XLSX 实际解压内容超过安全容量。')
        if read != entry.file_size:
            raise ValueError('XLSX 内部文件长度无效。')
        lower = name.lower()
        if 'vbaproject' in lower or lower.startswith(('xl/macrosheets/', 'xl/dialogsheets/', 'xl/externallinks/')):
            raise ValueError('XLSX 含宏或外部链接，不能安全读取。')
        if lower.endswith('.rels'):
            for relationship in _read_xml(archive, name):
                if relationship.get('TargetMode', '').lower() == 'external':
                    raise ValueError('XLSX 含外部链接，不能安全读取。')
    types = archive.read('[Content_Types].xml').lower()
    if b'macroenabled' in types or b'vbaproject' in types:
        raise ValueError('XLSX 含宏，不能安全读取。')
    _read_xml(archive, '[Content_Types].xml')


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def extract_document(content: bytes, file_name: str) -> dict:
    if len(content) > DOCX_MAX_PACKAGE_BYTES:
        raise AdapterError('MATERIAL_FILE_TOO_LARGE', '资料文件超过上传容量。', status_code=413)
    suffix = Path(file_name).suffix.lower()
    try:
        if suffix in ('.docx', '.doc'):
            return read_word(content, file_name, read_shape_text=True)
        if suffix == '.csv':
            result = _read_csv(content)
        elif suffix == '.xlsx':
            result = _read_xlsx(content)
        else:
            raise AdapterError('MATERIAL_FILE_TYPE_REJECTED', '请选择 DOCX、DOC、CSV 或 XLSX 资料。', status_code=400)
        for index, block in enumerate(result['blocks']):
            block['blockId'] = 'full-block-%d' % (index + 1)
        result['complete'] = not result['unreadObjects']
        return result
    except (DocxSecurityError, UnicodeError, csv.Error, zipfile.BadZipFile, KeyError, ValueError, IndexError, OverflowError, ET.ParseError) as exc:
        raise AdapterError('MATERIAL_FILE_REJECTED', '资料无法完整读取：' + str(exc), status_code=422) from exc


def _read_csv(content):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('gb18030')
    if '\x00' in text or '\ufffd' in text:
        raise ValueError('CSV 含无效字符，请使用 UTF-8 或 GB18030 编码。')
    blocks, cells = [], 0
    for index, row in enumerate(csv.reader(io.StringIO(text, newline=''), strict=True), 1):
        cells += len(row)
        if len(row) > MATERIAL_IMPORT_MAX_TABLE_COLUMNS or cells > MATERIAL_IMPORT_MAX_TABLE_CELLS:
            raise ValueError('表格行列超过读取上限，未截断。')
        blocks.append({'kind': 'table_row', 'values': row,
                       'text': json.dumps(row, ensure_ascii=False),
                       'source': {'part': 'csv', 'row': index}})
    return {'blocks': blocks, 'images': [], 'unreadObjects': [], 'tableCellsCount': cells}


def _relationships(archive, part):
    path = _relationship_part_path(part)
    if path not in archive.namelist():
        return {}
    return {r.get('Id'): (r.get('Type', ''), _resolve_part_path(part, r.get('Target', '')))
            for r in _read_xml(archive, path) if _local(r.tag) == 'Relationship'}


def _read_xlsx(content):
    blocks, images, unread = [], [], []
    count, hidden = 0, False
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        _validate_package(archive)
        workbook_path = _office_document_path(_read_xml(archive, '_rels/.rels'), archive.namelist())
        workbook = _read_xml(archive, workbook_path)
        relationships = _relationships(archive, workbook_path)
        strings, formats, styles = [], {}, []
        date1904 = any(_local(n.tag) == 'workbookPr' and n.get('date1904') in ('1', 'true') for n in workbook)
        for kind, path in relationships.values():
            if kind.endswith('/styles'):
                style_root = _read_xml(archive, path)
                formats = {int(n.get('numFmtId')): n.get('formatCode', '') for n in style_root.iter() if _local(n.tag) == 'numFmt'}
                for n in style_root:
                    if _local(n.tag) == 'cellXfs':
                        styles = [int(x.get('numFmtId', '0')) for x in n]
            if kind.endswith('/sharedStrings'):
                strings = [''.join(n.text or '' for n in item.iter() if _local(n.tag) == 't')
                           for item in _read_xml(archive, path)]
        for sheet in workbook.iter():
            if _local(sheet.tag) != 'sheet':
                continue
            rid = next((v for k, v in sheet.attrib.items() if _local(k) == 'id'), '')
            kind, part = relationships[rid]
            if not kind.endswith('/worksheet'):
                raise ValueError('不支持的工作表类型。')
            root = _read_xml(archive, part)
            pending, element_count = [(root, 1)], 0
            while pending:
                element, depth = pending.pop()
                element_count += 1
                if depth > MAX_XLSX_WORKSHEET_DEPTH or element_count > MAX_XLSX_WORKSHEET_ELEMENTS:
                    raise ValueError('工作表 XML 结构超过安全预算。')
                pending.extend((child, depth + 1) for child in element)
            sheet_hidden = sheet.get('state', 'visible') != 'visible'
            hidden = hidden or sheet_hidden or any(n.get('hidden') in ('1', 'true') for n in root.iter())
            source = {'part': part, 'sheetName': sheet.get('name', ''), 'hidden': sheet_hidden}
            blocks.append({'kind': 'heading', 'text': '工作表：' + sheet.get('name', '') + ('（隐藏）' if sheet_hidden else ''), 'source': source})
            shared_formulas = {}
            for node in root.iter():
                if _local(node.tag) == 'c':
                    for formula in node:
                        if _local(formula.tag) == 'f' and formula.get('t') == 'shared' and formula.text:
                            shared_formulas[formula.get('si')] = {'formula': formula.text, 'address': node.get('r'), 'range': formula.get('ref')}
            for cell in root.iter():
                tag = _local(cell.tag)
                if tag == 'c':
                    count += 1
                    if count > MATERIAL_IMPORT_MAX_TABLE_CELLS:
                        raise ValueError('表格单元格超过读取上限，未截断。')
                    data = {_local(n.tag): n for n in cell}
                    value = data['v'].text or '' if 'v' in data else ''
                    if cell.get('t') == 's':
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(n.text or '' for n in cell.iter() if _local(n.tag) == 't')
                    fmt_id = styles[int(cell.get('s', '0'))] if styles else 0
                    number_format = formats.get(fmt_id, 'builtin:%d' % fmt_id)
                    if value and cell.get('t', 'n') == 'n':
                        # Keep raw values and formatting alongside an unambiguous date.
                        cleaned_format = re.sub(r'"[^"]*"|\\.|\[[^]]*\]', '', number_format).lower()
                        if fmt_id in range(14, 23) or (fmt_id >= 164 and re.search(r'[ydhs]', cleaned_format)):
                            days = float(value)
                            base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
                            if not date1904 and days < 60:
                                base = datetime(1899, 12, 31)
                            date = base + timedelta(days=days)
                            value = date.isoformat(sep=' ') + '（原值 ' + value + '）'
                    if 'f' in data:
                        formula = data['f']
                        expression = formula.text or ''
                        if formula.get('t') == 'shared':
                            master = shared_formulas.get(formula.get('si'))
                            if not master:
                                raise ValueError('共享公式缺少主公式，无法完整读取。')
                            expression += ' [共享公式 ' + json.dumps(dict(master, index=formula.get('si')), ensure_ascii=False) + ']'
                        elif not expression:
                            raise ValueError('公式表达式缺失，无法完整读取。')
                        value = '公式=' + expression + '；缓存值=' + (value if value else '未计算')
                    address = cell.get('r', '')
                    blocks.append({'kind': 'table_cell', 'text': address + ': ' + value,
                                   'source': dict(source, address=address, numberFormat=number_format, date1904=date1904)})
                elif tag == 'mergeCell':
                    blocks.append({'kind': 'table_merge', 'text': '合并单元格：' + cell.get('ref', ''), 'source': source})
                elif tag in ('oddHeader', 'evenHeader', 'firstHeader', 'oddFooter', 'evenFooter', 'firstFooter') and cell.text:
                    blocks.append({'kind': 'text', 'text': cell.text, 'source': dict(source, region=tag)})
            # Follow drawing relationships, keeping source sheet and image identities.
            for rel_kind, target in _relationships(archive, part).values():
                if rel_kind.endswith(('/drawing', '/vmlDrawing')):
                    drawing = _read_xml(archive, target)
                    drawing_rels = _relationships(archive, target)
                    for node in drawing.iter():
                        tag = _local(node.tag)
                        if tag in ('blip', 'imagedata'):
                            rid = next((v for k, v in node.attrib.items() if _local(k) in ('embed', 'id')), '')
                            image_path = drawing_rels[rid][1]
                            raw = archive.read(image_path)
                            mime = _image_mime(raw)
                            if not mime:
                                unread.append(dict(source, kind='unsupported_image'))
                                continue
                            image_id = 'image-%d' % (len(images) + 1)
                            images.append({'imageId': image_id, 'data': raw, 'mimeType': mime})
                            blocks.append({'kind': 'image', 'imageId': image_id, 'source': dict(source, part=target)})
                        elif tag == 't' and node.text:
                            blocks.append({'kind': 'text', 'text': node.text, 'source': source})
                        elif tag in ('sp', 'cxnSp', 'grpSp'):
                            unread.append(dict(source, kind='vector_drawing'))
                        elif tag == 'chart':
                            rid = next((v for k, v in node.attrib.items() if _local(k) == 'id'), '')
                            chart = _read_xml(archive, drawing_rels[rid][1])
                            values = [n.text for n in chart.iter() if _local(n.tag) in ('v', 't', 'f') and n.text]
                            blocks.append({'kind': 'text', 'text': '图表数据：' + '\n'.join(values), 'source': source})
                            unread.append(dict(source, kind='chart'))
                elif rel_kind.endswith('/comments'):
                    for node in _read_xml(archive, target).iter():
                        if _local(node.tag) == 'comment':
                            blocks.append({'kind': 'text', 'text': ''.join(n.text or '' for n in node.iter() if _local(n.tag) == 't'),
                                           'source': dict(source, address=node.get('ref', ''))})
                elif rel_kind.endswith(('/oleObject', '/package')):
                    unread.append(dict(source, kind='embedded_attachment'))
                elif not rel_kind.endswith(('/table', '/printerSettings', '/hyperlink')):
                    unread.append(dict(source, kind='unsupported_object', relationship=rel_kind))
    return {'blocks': blocks, 'images': images, 'unreadObjects': unread,
            'tableCellsCount': count, 'hiddenContentIncluded': hidden}
