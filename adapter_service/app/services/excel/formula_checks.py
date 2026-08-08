import re
from typing import Dict, List


MAX_FORMULA_LENGTH = 8192
MAX_EXCEL_ROW = 1048576
MAX_EXCEL_COLUMN = 16384

NETWORK_FUNCTIONS = {
    "FILTERXML",
    "HYPERLINK",
    "IMAGE",
    "RTD",
    "STOCKHISTORY",
    "WEBSERVICE",
}

VERSION_SENSITIVE_FUNCTIONS = {
    "BYCOL",
    "BYROW",
    "CHOOSECOLS",
    "CHOOSEROWS",
    "DROP",
    "FILTER",
    "HSTACK",
    "LAMBDA",
    "LET",
    "MAKEARRAY",
    "MAP",
    "REDUCE",
    "SCAN",
    "SEQUENCE",
    "SORT",
    "SORTBY",
    "TAKE",
    "TEXTAFTER",
    "TEXTBEFORE",
    "TEXTSPLIT",
    "TOCOL",
    "TOROW",
    "UNIQUE",
    "VSTACK",
    "WRAPCOLS",
    "WRAPROWS",
    "XLOOKUP",
    "XMATCH",
}

FUNCTION_PATTERN = re.compile(r"(?i)(?<![A-Z0-9_.])([A-Z][A-Z0-9_.]*)\s*\(")
CELL_REFERENCE_PATTERN = re.compile(
    r"(?i)(?<![A-Z0-9_])\$?([A-Z]{1,3})\$?([0-9]{1,7})(?![A-Z0-9_])"
)
URL_PATTERN = re.compile(r"(?i)(?:https?|ftp)://|\bwww\.")
EXTERNAL_WORKBOOK_PATTERN = re.compile(r"(?i)'?\[[^\]\r\n]+\][^!\r\n]*!")


def _risk(code: str, message: str, evidence: str) -> Dict[str, str]:
    return {"code": code, "message": message, "evidence": evidence}


def _quote_and_parenthesis_state(formula: str) -> Dict[str, object]:
    in_string = False
    depth = 0
    parenthesis_invalid = False
    index = 0
    while index < len(formula):
        character = formula[index]
        if character == '"':
            if in_string and index + 1 < len(formula) and formula[index + 1] == '"':
                index += 2
                continue
            in_string = not in_string
        elif not in_string and character == "(":
            depth += 1
        elif not in_string and character == ")":
            depth -= 1
            if depth < 0:
                parenthesis_invalid = True
                depth = 0
        index += 1
    return {
        "unbalancedQuotes": in_string,
        "unbalancedParentheses": parenthesis_invalid or depth != 0,
    }


def _column_number(column_letters: str) -> int:
    value = 0
    for character in column_letters.upper():
        value = value * 26 + (ord(character) - ord("A") + 1)
    return value


def _out_of_bounds_references(formula: str) -> List[str]:
    references = []
    for match in CELL_REFERENCE_PATTERN.finditer(formula):
        column = _column_number(match.group(1))
        row = int(match.group(2))
        if column > MAX_EXCEL_COLUMN or row < 1 or row > MAX_EXCEL_ROW:
            reference = match.group(0)
            if reference not in references:
                references.append(reference)
    return references


def _selection_bounds(selection_address: str):
    matches = list(CELL_REFERENCE_PATTERN.finditer(str(selection_address or "")))
    if not matches:
        return None
    start = matches[0]
    end = matches[1] if len(matches) > 1 else start
    start_column = _column_number(start.group(1))
    end_column = _column_number(end.group(1))
    start_row = int(start.group(2))
    end_row = int(end.group(2))
    return (
        min(start_column, end_column),
        min(start_row, end_row),
        max(start_column, end_column),
        max(start_row, end_row),
    )


def _references_outside_selection(formula: str, selection_address: str) -> List[str]:
    bounds = _selection_bounds(selection_address)
    if not bounds:
        return []
    min_column, min_row, max_column, max_row = bounds
    references = []
    for match in CELL_REFERENCE_PATTERN.finditer(formula):
        column = _column_number(match.group(1))
        row = int(match.group(2))
        if column > MAX_EXCEL_COLUMN or row < 1 or row > MAX_EXCEL_ROW:
            continue
        if not (min_column <= column <= max_column and min_row <= row <= max_row):
            reference = match.group(0)
            if reference not in references:
                references.append(reference)
    return references


def inspect_formula(formula: str, selection_address: str = "") -> Dict:
    """Run non-executing checks against formula text without touching a workbook."""

    text = str(formula or "").strip()
    risks = []
    if not text.startswith("="):
        risks.append(
            _risk(
                "MISSING_EQUALS_PREFIX",
                "公式应以等号开头。",
                text[:80] or "未提供公式文本",
            )
        )

    state = _quote_and_parenthesis_state(text)
    if state["unbalancedQuotes"]:
        risks.append(
            _risk(
                "UNBALANCED_QUOTES",
                "公式中的双引号未成对闭合。",
                "检测到未闭合的字符串边界",
            )
        )
    if state["unbalancedParentheses"]:
        risks.append(
            _risk(
                "UNBALANCED_PARENTHESES",
                "公式中的括号未成对闭合或闭合顺序异常。",
                "检测到括号层级不平衡",
            )
        )
    if len(text) > MAX_FORMULA_LENGTH:
        risks.append(
            _risk(
                "FORMULA_TOO_LONG",
                "公式长度超过 8192 个字符，可能超出兼容上限。",
                "当前长度：{0}".format(len(text)),
            )
        )
    if EXTERNAL_WORKBOOK_PATTERN.search(text):
        risks.append(
            _risk(
                "EXTERNAL_WORKBOOK_REFERENCE",
                "公式包含外部工作簿引用，源文件不可用时结果会受影响。",
                EXTERNAL_WORKBOOK_PATTERN.search(text).group(0),
            )
        )

    functions = sorted({match.group(1).upper() for match in FUNCTION_PATTERN.finditer(text)})
    network_functions = sorted(set(functions).intersection(NETWORK_FUNCTIONS))
    url_match = URL_PATTERN.search(text)
    if network_functions or url_match:
        evidence = ", ".join(network_functions)
        if url_match:
            evidence = (evidence + "; " if evidence else "") + url_match.group(0)
        risks.append(
            _risk(
                "NETWORK_FUNCTION_OR_URL",
                "公式包含 URL 或可能访问外部资源的函数，需核对网络与安全策略。",
                evidence,
            )
        )

    invalid_references = _out_of_bounds_references(text)
    if invalid_references:
        risks.append(
            _risk(
                "OUT_OF_BOUNDS_REFERENCE",
                "公式包含明显超出工作表边界的单元格引用。",
                ", ".join(invalid_references),
            )
        )

    outside_selection = _references_outside_selection(text, selection_address)
    if outside_selection:
        risks.append(
            _risk(
                "OUTSIDE_SELECTION_REFERENCE",
                "公式引用超出本次明确选区，当前上下文无法完整核对。",
                ", ".join(outside_selection),
            )
        )

    version_sensitive = sorted(set(functions).intersection(VERSION_SENSITIVE_FUNCTIONS))
    if version_sensitive:
        risks.append(
            _risk(
                "COMPATIBILITY_REVIEW_REQUIRED",
                "公式包含需要结合 WPS/Excel 版本核对的函数。",
                ", ".join(version_sensitive),
            )
        )

    return {
        "status": "risks" if risks else "passed",
        "summary": "发现 {0} 项基础风险".format(len(risks)) if risks else "基础检查通过",
        "checkedFormula": text,
        "risks": risks,
    }
