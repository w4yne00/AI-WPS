import argparse
import csv
import hashlib
import io
import re
import subprocess
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple
from xml.sax.saxutils import escape


UPSTREAM_TAG = "v1.1.0"
UPSTREAM_COMMIT = "d3640165569071251248a5fafb2def6ef2fe2cf4"
UPSTREAM_SOURCE_PATH = "SKILL.md"
REVIEW_COLUMNS = (
    "稳定ID",
    "规范包",
    "类型",
    "分类",
    "名称",
    "规则或术语内容",
    "正例",
    "反例",
    "来源",
    "来源版本",
    "来源提交",
    "来源路径",
    "来源定位",
    "许可证",
    "默认启用",
    "审阅决定",
    "审阅备注",
)
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_NUMBERED_RE = re.compile(r"^([0-9]+)\.\s+\*\*?([^*：]+)\*\*?[：:]\s*(.+)$")
_PLAIN_NUMBERED_RE = re.compile(r"^([0-9]+)\.\s+(.+)$")
_QUALITY_RE = re.compile(r"H([1-6])\s*([^；。]+)")
_SPACE_RE = re.compile(r"\s+")


def _section(markdown: str, heading: str) -> List[Tuple[int, str]]:
    lines = markdown.splitlines()
    result = []
    active = False
    for line_number, line in enumerate(lines, start=1):
        if line.strip() == "## %s" % heading:
            active = True
            continue
        if active and line.startswith("## "):
            break
        if active:
            result.append((line_number, line.strip()))
    return result


def _candidate(
    *,
    index: int,
    category: str,
    name: str,
    content: str,
    line_number: int,
    source_path: str,
    tag: str,
    commit: str,
) -> Dict[str, str]:
    locator = "%s#L%d" % (source_path, line_number)
    return {
        "稳定ID": "rule.yangqi.base.%03d" % index,
        "规范包": "yangqi-tech-writing-base",
        "类型": "style",
        "分类": category,
        "名称": name.strip(" *"),
        "规则或术语内容": content.strip(),
        "正例": "",
        "反例": "",
        "来源": "yangqi-tech-writing",
        "来源版本": tag,
        "来源提交": commit,
        "来源路径": source_path,
        "来源定位": locator,
        "许可证": "MIT",
        "默认启用": "true",
        "审阅决定": "",
        "审阅备注": "",
    }


def build_candidates(
    git_show_reader: Callable[[str, str], str],
    *,
    tag: str = UPSTREAM_TAG,
    commit: str = UPSTREAM_COMMIT,
    source_path: str = UPSTREAM_SOURCE_PATH,
) -> List[Dict[str, str]]:
    markdown = git_show_reader(tag, source_path)
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("clean tag source is empty")
    extracted = []

    protected = _section(markdown, "保护项与证据")
    if not protected:
        protected = _section(markdown, "保护优先级")
    for line_number, line in protected:
        if ">" in line and not line.startswith("#"):
            extracted.append(("保护项", "保持保护项优先级", line, line_number))
            break

    for line_number, line in _section(markdown, "固定执行顺序"):
        match = _NUMBERED_RE.match(line)
        if not match:
            continue
        step = match.group(2).strip()
        if step in ("保护项", "证据", "Tier", "scope", "质量闸门"):
            extracted.append(("执行边界", step, match.group(3), line_number))

    for line_number, line in _section(markdown, "写作与审阅规则"):
        match = _PLAIN_NUMBERED_RE.match(line)
        if not match:
            continue
        content = match.group(2).strip()
        if "references/" in content or "见[" in content:
            continue
        name = content.split("：", 1)[0].split("，", 1)[0].rstrip("。")
        extracted.append(("成文质量", name[:32], content, line_number))

    for line_number, line in _section(markdown, "质量闸门 H1—H6"):
        for gate, content in _QUALITY_RE.findall(line):
            extracted.append(
                ("质量闸门", "H%s %s" % (gate, content.strip()), content.strip(), line_number)
            )

    rows = []
    seen = set()
    for category, name, content, line_number in extracted:
        key = _normalize(content)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            _candidate(
                index=len(rows) + 1,
                category=category,
                name=name,
                content=content,
                line_number=line_number,
                source_path=source_path,
                tag=tag,
                commit=commit,
            )
        )
    return rows


def _normalize(value: object) -> str:
    return _SPACE_RE.sub("", str(value or "")).casefold()


def audit_candidates(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    id_counts = {}
    missing_sources = []
    unreviewed = 0
    for row in rows:
        item_id = str(row.get("稳定ID", ""))
        id_counts[item_id] = id_counts.get(item_id, 0) + 1
        if not all(
            str(row.get(field, "")).strip()
            for field in ("来源", "来源版本", "来源提交", "来源路径", "来源定位", "许可证")
        ):
            missing_sources.append(item_id)
        if str(row.get("审阅决定", "")).strip() not in ("通过", "拒绝"):
            unreviewed += 1

    near_duplicates = []
    conflicts = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            left_text = _normalize(left.get("规则或术语内容"))
            right_text = _normalize(right.get("规则或术语内容"))
            similarity = SequenceMatcher(None, left_text, right_text).ratio()
            if similarity >= 0.72:
                near_duplicates.append([left.get("稳定ID"), right.get("稳定ID")])
            if (
                _normalize(left.get("名称")) == _normalize(right.get("名称"))
                and left_text != right_text
            ):
                conflicts.append([left.get("稳定ID"), right.get("稳定ID")])
    return {
        "duplicateIds": sorted(
            item_id for item_id, count in id_counts.items() if item_id and count > 1
        ),
        "nearDuplicates": near_duplicates,
        "conflicts": conflicts,
        "missingSources": sorted(set(missing_sources)),
        "unreviewedCount": unreviewed,
    }


def _xlsx_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(values, start=1):
            reference = "%s%d" % (_excel_column_name(column_index), row_index)
            cells.append(
                '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                % (reference, escape(str(value)))
            )
        sheet_rows.append('<row r="%d">%s</row>' % (row_index, "".join(cells)))
    parts = (
        (
            "[Content_Types].xml",
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            b"</Types>",
        ),
        (
            "_rels/.rels",
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            b"</Relationships>",
        ),
        (
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="规范审阅清单" sheetId="1" r:id="rId1"/></sheets></workbook>',
        ),
        (
            "xl/_rels/workbook.xml.rels",
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            b"</Relationships>",
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>%s</sheetData></worksheet>" % "".join(sheet_rows),
        ),
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in parts:
            info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, content.encode("utf-8") if isinstance(content, str) else content)
    return output.getvalue()


def _excel_column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_review_files(
    rows: Sequence[Dict[str, str]], output_stem: Path
) -> Tuple[Path, Path]:
    stem = Path(output_stem)
    csv_path = Path(str(stem) + ".csv")
    xlsx_path = Path(str(stem) + ".xlsx")
    csv_output = io.StringIO(newline="")
    writer = csv.DictWriter(csv_output, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_path.write_bytes(b"\xef\xbb\xbf" + csv_output.getvalue().encode("utf-8"))
    xlsx_rows = [REVIEW_COLUMNS]
    xlsx_rows.extend(tuple(str(row.get(column, "")) for column in REVIEW_COLUMNS) for row in rows)
    xlsx_path.write_bytes(_xlsx_bytes(xlsx_rows))
    return csv_path, xlsx_path


def _git_show_reader(repository: Path) -> Callable[[str, str], str]:
    def read(tag: str, path: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), "show", "%s:%s" % (tag, path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.decode("utf-8")

    return read


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tag", default=UPSTREAM_TAG)
    parser.add_argument("--commit", default=UPSTREAM_COMMIT)
    parser.add_argument("--source-path", default=UPSTREAM_SOURCE_PATH)
    args = parser.parse_args(argv)
    actual_commit = subprocess.run(
        ["git", "-C", str(args.repository), "rev-parse", "%s^{commit}" % args.tag],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.decode("ascii").strip()
    if actual_commit != args.commit:
        raise SystemExit("tag commit mismatch")
    rows = build_candidates(
        _git_show_reader(args.repository),
        tag=args.tag,
        commit=args.commit,
        source_path=args.source_path,
    )
    write_review_files(rows, args.output)
    report = audit_candidates(rows)
    digest = hashlib.sha256(
        "\n".join(row["稳定ID"] for row in rows).encode("utf-8")
    ).hexdigest()
    print(
        "generated=%d unreviewed=%d digest=%s"
        % (len(rows), report["unreviewedCount"], digest)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
