#!/usr/bin/env python3
"""Reject production annotations that fail when evaluated by Python 3.8."""

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional


PY39_BUILTIN_GENERICS = {
    "dict": "Dict",
    "frozenset": "FrozenSet",
    "list": "List",
    "set": "Set",
    "tuple": "Tuple",
    "type": "Type",
}


class Finding(NamedTuple):
    path: Path
    line: int
    column: int
    code: str
    detail: str


def iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    seen = set()
    for candidate in paths:
        if candidate.is_file():
            files = [candidate] if candidate.suffix == ".py" else []
        elif candidate.is_dir():
            files = sorted(candidate.rglob("*.py"))
        else:
            raise FileNotFoundError(str(candidate))
        for path in files:
            resolved = path.resolve()
            if resolved in seen or "__pycache__" in resolved.parts:
                continue
            seen.add(resolved)
            yield resolved


def annotation_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                yield node.returns


def parsed_annotation(annotation: ast.AST) -> ast.AST:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return annotation
    return annotation


def scan_file(path: Path) -> List[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        line = int(getattr(exc, "lineno", 1) or 1)
        column = int(getattr(exc, "offset", 1) or 1)
        return [
            Finding(path, line, column, "PY38_SYNTAX", str(exc).splitlines()[0])
        ]

    findings = []
    reported = set()
    for annotation in annotation_nodes(tree):
        annotation = parsed_annotation(annotation)
        for node in ast.walk(annotation):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in PY39_BUILTIN_GENERICS
            ):
                key = (node.lineno, node.col_offset, "PY38_BUILTIN_GENERIC")
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.col_offset + 1,
                            "PY38_BUILTIN_GENERIC",
                            "use typing.{0} instead of {1}[...]".format(
                                PY39_BUILTIN_GENERICS[node.value.id], node.value.id
                            ),
                        )
                    )
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                key = (node.lineno, node.col_offset, "PY38_UNION_OPERATOR")
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.col_offset + 1,
                            "PY38_UNION_OPERATOR",
                            "use typing.Optional/Union instead of the | annotation operator",
                        )
                    )
    return findings


def relative_label(path: Path, base: Optional[Path]) -> str:
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan production Python annotations for Python 3.8 compatibility."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    findings = []
    try:
        files = list(iter_python_files(args.paths))
    except FileNotFoundError as exc:
        print("PY38_SCAN_PATH_MISSING {0}".format(exc))
        return 2

    if not files:
        print("PY38_SCAN_EMPTY no Python files found")
        return 2

    common_base = Path(
        __import__("os").path.commonpath([str(path.parent) for path in files])
    )
    for path in files:
        findings.extend(scan_file(path))

    for finding in sorted(findings):
        print(
            "{0}:{1}:{2} {3} {4}".format(
                relative_label(finding.path, common_base),
                finding.line,
                finding.column,
                finding.code,
                finding.detail,
            )
        )
    if findings:
        print("python38_compatibility_scan=failed findings={0}".format(len(findings)))
        return 1

    print("python38_compatibility_scan=passed files={0}".format(len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
