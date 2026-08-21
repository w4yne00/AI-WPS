#!/usr/bin/env python3
"""Compile a DOCX and an approved structure list into an offline rule pack."""

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET
from zipfile import ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RULE_PACK_SCHEMA_VERSION = 1
ALGORITHM_ADAPTER_VERSION = "ai-wps-wx-doc-format-0.12.15-adapter.1"
ACTIVE_RULE_PACK_ID = "technical-document-template-rules"
ACTIVE_RULE_PACK_NAME = "技术文档模板规则"
ACTIVE_RULE_PACK_VERSION = "1.0.0"
SOURCE_CLASSIFICATION = (
    Path(__file__).resolve().parents[1]
    / "vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json"
)
ALLOWED_CLASSIFICATIONS = {"normative-format", "normative-structure"}
ALL_CLASSIFICATIONS = ALLOWED_CLASSIFICATIONS | {"converter-only"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def qn(name: str) -> str:
    return "{" + W_NS + "}" + name


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(parent: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    if parent is None:
        return None
    return parent.find(qn(name))


def _attr(element: Optional[ET.Element], name: str) -> Optional[str]:
    if element is None:
        return None
    return element.get(qn(name))


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    result.update(override)
    return result


def _extract_style(style: ET.Element, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = dict(base or {})
    name = _attr(_child(style, "name"), "val")
    if name:
        result["styleName"] = name
    rpr = _child(style, "rPr")
    fonts = _child(rpr, "rFonts")
    font_name = _attr(fonts, "eastAsia") or _attr(fonts, "ascii") or _attr(fonts, "hAnsi")
    ascii_font_name = _attr(fonts, "ascii") or _attr(fonts, "hAnsi")
    if font_name:
        result["fontName"] = font_name
    if ascii_font_name:
        result["asciiFontName"] = ascii_font_name
    size = _float(_attr(_child(rpr, "sz"), "val"))
    if size is not None:
        result["fontSize"] = size / 2.0
    bold = _child(rpr, "b")
    if bold is not None:
        result["bold"] = _attr(bold, "val") not in {"0", "false", "off", "none"}

    ppr = _child(style, "pPr")
    alignment = _attr(_child(ppr, "jc"), "val")
    if alignment:
        result["alignment"] = "justify" if alignment == "both" else alignment
    outline = _int(_attr(_child(ppr, "outlineLvl"), "val"))
    if outline is not None:
        result["outlineLevel"] = outline + 1
    spacing = _child(ppr, "spacing")
    line = _int(_attr(spacing, "line"))
    if line is not None:
        result["lineSpacingTwips"] = line
        result["lineSpacing"] = round(line / 240.0, 4)
    line_rule = _attr(spacing, "lineRule")
    if line_rule:
        result["lineRule"] = line_rule
    for attribute, output_key in (
        ("before", "spaceBeforeTwips"),
        ("after", "spaceAfterTwips"),
        ("left", "leftIndentTwips"),
        ("right", "rightIndentTwips"),
        ("firstLine", "firstLineIndentTwips"),
        ("hanging", "hangingIndentTwips"),
    ):
        value = _int(_attr(_child(ppr, "spacing"), attribute))
        if value is None:
            value = _int(_attr(_child(ppr, "ind"), attribute))
        if value is not None:
            result[output_key] = value
    return result


def _parse_styles(xml: bytes) -> Dict[str, Dict[str, Any]]:
    root = ET.fromstring(xml)
    styles = {}
    raw = {}
    for style in root.findall(qn("style")):
        style_id = _attr(style, "styleId")
        if style_id:
            raw[style_id] = style

    def resolve(style_id: str, trail: Optional[List[str]] = None) -> Dict[str, Any]:
        trail = list(trail or [])
        if style_id in trail or style_id not in raw:
            return {}
        base_id = _attr(_child(raw[style_id], "basedOn"), "val")
        parent = resolve(base_id, trail + [style_id]) if base_id else {}
        result = _extract_style(raw[style_id], parent)
        styles[style_id] = result
        return result

    for style_id in raw:
        resolve(style_id)
    return styles


def _parse_page(xml: bytes) -> Dict[str, int]:
    root = ET.fromstring(xml)
    sections = root.findall(".//" + qn("sectPr"))
    if not sections:
        raise ValueError("TEMPLATE_PAGE_SETUP_MISSING")
    section = sections[-1]
    size = _child(section, "pgSz")
    margins = _child(section, "pgMar")
    result = {}
    for source, target in ((size, "widthTwips"), (size, "heightTwips")):
        attribute = "w" if target == "widthTwips" else "h"
        value = _int(_attr(source, attribute))
        if value is not None:
            result[target] = value
    margin_names = {
        "top": "marginTopTwips",
        "bottom": "marginBottomTwips",
        "left": "marginLeftTwips",
        "right": "marginRightTwips",
        "header": "headerTwips",
        "footer": "footerTwips",
    }
    for attribute, target in margin_names.items():
        value = _int(_attr(margins, attribute))
        if value is not None:
            result[target] = value
    return result


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON_OBJECT_REQUIRED {0}".format(path))
    return payload


def _load_source_classification(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    if payload.get("schemaVersion") != 1:
        raise ValueError("SOURCE_CLASSIFICATION_SCHEMA_INVALID")
    if payload.get("sourceName") != "wx-doc-format" or payload.get("sourceVersion") != "0.12.15":
        raise ValueError("SOURCE_CLASSIFICATION_SOURCE_INVALID")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("SOURCE_CLASSIFICATION_EMPTY")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("SOURCE_CLASSIFICATION_RULE_INVALID")
        if not isinstance(rule.get("id"), str) or not rule["id"] or rule["id"] in seen:
            raise ValueError("SOURCE_CLASSIFICATION_RULE_INVALID")
        if rule.get("category") not in ALL_CLASSIFICATIONS:
            raise ValueError("SOURCE_CLASSIFICATION_CATEGORY_INVALID")
        if not isinstance(rule.get("sourcePath"), str) or not rule["sourcePath"]:
            raise ValueError("SOURCE_CLASSIFICATION_SOURCE_PATH_INVALID")
        if not isinstance(rule.get("sourceSha256"), str) or not SHA256_RE.fullmatch(rule["sourceSha256"]):
            raise ValueError("SOURCE_CLASSIFICATION_SOURCE_HASH_INVALID")
        if not isinstance(rule.get("selected"), bool):
            raise ValueError("SOURCE_CLASSIFICATION_SELECTION_INVALID")
        seen.add(rule["id"])
    return payload


def _compile_template(template_docx: Path, template_json: Dict[str, Any]) -> Dict[str, Any]:
    with ZipFile(str(template_docx)) as archive:
        styles = _parse_styles(archive.read("word/styles.xml"))
        page = _parse_page(archive.read("word/document.xml"))
    role_rules = {}
    source_rules = dict(template_json.get("roleRules") or {})
    body_source = dict(template_json.get("body") or {})
    body_style_id = body_source.get("styleId")
    if body_style_id not in styles:
        raise ValueError("TEMPLATE_BODY_STYLE_MISSING")
    body_rule = _merge(styles[body_style_id], body_source)
    body_rule["styleId"] = body_style_id
    body_rule["role"] = "body"
    role_rules["body"] = body_rule
    for role, source_rule in source_rules.items():
        style_id = source_rule.get("styleId")
        if style_id not in styles:
            raise ValueError("TEMPLATE_ROLE_STYLE_MISSING {0}".format(role))
        compiled = _merge(styles[style_id], source_rule)
        compiled["styleId"] = style_id
        compiled["role"] = role
        aliases = source_rule.get("fontAliases")
        if aliases:
            compiled["fontAliases"] = list(aliases)
        role_rules[role] = compiled

    styles_map = copy.deepcopy(template_json.get("styles") or {})
    page = _merge(page, dict(template_json.get("page") or {}))
    return {
        "id": template_json.get("id"),
        "name": template_json.get("name"),
        "version": template_json.get("version"),
        "sourceDocument": template_json.get("sourceDocument"),
        "sourceDocumentSha256": _sha256(template_docx.read_bytes()),
        "page": page,
        "body": body_rule,
        "roleRules": role_rules,
        "headings": copy.deepcopy(template_json.get("headings") or {}),
        "roleMappings": copy.deepcopy(template_json.get("roleMappings") or {}),
        "styles": styles_map,
    }


def compile_rule_pack(
    template_docx: Path,
    template_json_path: Path,
    structure_rules_path: Path,
    output_path: Optional[Path] = None,
    source_classification_path: Optional[Path] = None,
) -> Dict[str, Any]:
    template_docx = Path(template_docx)
    template_json_path = Path(template_json_path)
    structure_rules_path = Path(structure_rules_path)
    template_json = _load_json(template_json_path)
    structure_rules = _load_json(structure_rules_path)
    source_classification = _load_source_classification(
        Path(source_classification_path) if source_classification_path is not None else SOURCE_CLASSIFICATION
    )
    if structure_rules.get("schemaVersion") != 1 or not structure_rules.get("confirmed"):
        raise ValueError("STRUCTURE_RULES_NOT_CONFIRMED")
    if structure_rules.get("id") != template_json.get("id"):
        raise ValueError("STRUCTURE_RULES_TEMPLATE_MISMATCH")
    rules = structure_rules.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("STRUCTURE_RULES_EMPTY")
    source_rules = {
        item["id"]: item for item in source_classification["rules"]
    }
    compiled_rules = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("id") not in source_rules:
            raise ValueError("STRUCTURE_RULE_SOURCE_UNCLASSIFIED")
        source_rule = source_rules[rule["id"]]
        if source_rule.get("category") not in ALLOWED_CLASSIFICATIONS:
            raise ValueError("STRUCTURE_RULE_CONVERTER_ONLY")
        if not source_rule.get("selected"):
            raise ValueError("STRUCTURE_RULE_NOT_ALLOWLISTED")
        compiled_rule = copy.deepcopy(rule)
        compiled_rule["classification"] = source_rule["category"]
        compiled_rule["sourcePath"] = source_rule["sourcePath"]
        compiled_rule["sourceSha256"] = source_rule["sourceSha256"]
        compiled_rules.append(compiled_rule)

    template_id = template_json.get("id")
    template_name = template_json.get("name")
    if template_id != ACTIVE_RULE_PACK_ID or template_name != ACTIVE_RULE_PACK_NAME:
        raise ValueError("ACTIVE_RULE_PACK_IDENTITY_INVALID")
    if template_json.get("version") not in {None, ACTIVE_RULE_PACK_VERSION}:
        raise ValueError("ACTIVE_RULE_PACK_VERSION_INVALID")

    vendor_manifest = Path(__file__).resolve().parents[1] / "vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json"
    vendor_algorithm = Path(__file__).resolve().parents[1] / "vendor/wx_doc_format_algorithm/algorithm.py"
    source_classification_path = (
        Path(source_classification_path).resolve()
        if source_classification_path is not None
        else SOURCE_CLASSIFICATION
    )
    adapter_root = Path(__file__).resolve().parents[1]
    try:
        source_classification_ref = source_classification_path.relative_to(adapter_root).as_posix()
    except ValueError:
        raise ValueError("SOURCE_CLASSIFICATION_PATH_OUTSIDE_ADAPTER")
    algorithm_manifest_hash = _sha256(vendor_manifest.read_bytes())
    pack = {
        "schemaVersion": RULE_PACK_SCHEMA_VERSION,
        "version": ACTIVE_RULE_PACK_VERSION,
        "rulePack": {
            "id": ACTIVE_RULE_PACK_ID,
            "displayName": ACTIVE_RULE_PACK_NAME,
            "version": ACTIVE_RULE_PACK_VERSION,
            "sourceName": source_classification["sourceName"],
            "sourceVersion": "{0} {1}".format(
                source_classification["sourceName"], source_classification["sourceVersion"]
            ),
            "active": True,
        },
        "template": _compile_template(template_docx, template_json),
        "algorithm": {
            "name": "wx-doc-format deterministic recognition",
            "sourceVersion": "0.12.15",
            "adapterVersion": ALGORITHM_ADAPTER_VERSION,
            "sourceManifest": "vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json",
            "sourceManifestSha256": algorithm_manifest_hash,
            "sourceClassification": source_classification_ref,
            "sourceClassificationSha256": _sha256(source_classification_path.read_bytes()),
            "adapterPath": "vendor/wx_doc_format_algorithm/algorithm.py",
            "adapterSha256": _sha256(vendor_algorithm.read_bytes()),
            "writeBack": False,
        },
        "sourceRules": copy.deepcopy(source_classification["rules"]),
        "rules": compiled_rules,
    }
    pack["integrity"] = {"contentSha256": _sha256(_canonical(pack))}
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return pack


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-docx", required=True, type=Path)
    parser.add_argument("--template-json", required=True, type=Path)
    parser.add_argument("--structure-rules", required=True, type=Path)
    parser.add_argument("--source-classification", type=Path, default=SOURCE_CLASSIFICATION)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        compile_rule_pack(
            args.template_docx,
            args.template_json,
            args.structure_rules,
            args.output,
            source_classification_path=args.source_classification,
        )
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print("format_rule_pack_compile=failed {0}".format(exc))
        return 1
    print("format_rule_pack_compile=passed output={0}".format(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
