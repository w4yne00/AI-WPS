import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import threading
import tempfile
from contextlib import nullcontext
from typing import Dict, List, Optional

from app.core.errors import AdapterError
from app.core.runtime_paths import resolve_runtime_paths
from app.services.long_task_coordinator import (
    get_long_task_coordinator,
    LongTaskCoordinator,
)
from app.services.ppt.docx_security import (
    DOCX_MAX_PACKAGE_BYTES,
    DocxSecurityError,
    validate_docx_bytes,
)
from app.services.excel.material_store import ExcelMaterialStore
from app.services.word.material_import import (
    MATERIAL_IMPORT_MAX_DOCUMENTS,
    MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
    MATERIAL_IMPORT_MAX_TABLE_COLUMNS,
    MATERIAL_IMPORT_MAX_TABLE_CELLS,
    CHARACTER_COUNT_METHOD,
    _decode_upload,
    _reject_wrong_type,
    _security_error,
    _read_document,
    _next_fragment_index,
    _updated_at,
    WordMaterialStore,
)


class PptMaterialStore:
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        word_base_dir: Optional[Path] = None,
        excel_base_dir: Optional[Path] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
        word_store: Optional[WordMaterialStore] = None,
        excel_store: Optional[ExcelMaterialStore] = None,
    ) -> None:
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.base_dir = paths.state_dir / "ppt_materials"
                else:
                    self.base_dir = paths.run_dir / "ppt_materials"
            except Exception:
                self.base_dir = Path("run/ppt_materials").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        if word_base_dir is not None:
            self.word_base_dir = Path(word_base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.word_base_dir = paths.state_dir / "word_materials"
                else:
                    self.word_base_dir = paths.run_dir / "word_materials"
            except Exception:
                self.word_base_dir = Path("run/word_materials").resolve()

        if excel_base_dir is not None:
            self.excel_base_dir = Path(excel_base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.excel_base_dir = paths.state_dir / "excel_materials"
                else:
                    self.excel_base_dir = paths.run_dir / "excel_materials"
            except Exception:
                self.excel_base_dir = Path("run/excel_materials").resolve()

        self.word_store = word_store
        if word_store is not None:
            self.word_base_dir = word_store.base_dir
        self.excel_store = excel_store
        if excel_store is not None:
            self.excel_base_dir = excel_store.base_dir
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.RLock()
        self._memory_catalogs: Dict[str, dict] = {}

    def _check_busy(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        if self.coordinator is not None and hasattr(self.coordinator, "has_active_task"):
            if self.coordinator.has_active_task(
                task_type="ppt.material_outline",
                document_session_id=session_id,
            ):
                raise AdapterError(
                    "MATERIAL_COMPOSER_BUSY",
                    "逐页大纲正在生成中，请等待完成或取消任务后再更新/移除资料。",
                    status_code=409,
                )

    def _resolve_dir_name(self, session_id: str, doc_identity: str = "") -> str:
        if doc_identity:
            h = hashlib.sha256(doc_identity.encode("utf-8")).hexdigest()[:16]
            return "doc_{0}".format(h)
        if session_id:
            h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
            return "sess_{0}".format(h)
        return "default"

    def _get_dir_for_session(self, session_id: str, search_dir: Optional[Path] = None) -> Optional[Path]:
        target_root = search_dir or self.base_dir
        if not target_root.exists():
            return None
        index_file = target_root / "sessions.json"
        if index_file.exists():
            try:
                index = json.loads(index_file.read_text(encoding="utf-8"))
                if session_id in index:
                    d = target_root / index[session_id]
                    if d.exists():
                        return d
            except Exception:
                pass
        for d in target_root.iterdir():
            if d.is_dir():
                m_file = d / "manifest.json"
                if m_file.exists():
                    try:
                        data = json.loads(m_file.read_text(encoding="utf-8"))
                        if data.get("documentSessionId") == session_id:
                            return d
                    except Exception:
                        pass
        return None

    def _update_session_index(self, session_id: str, dir_name: str) -> None:
        index_file = self.base_dir / "sessions.json"
        data = {}
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[session_id] = dir_name
        tmp_file = self.base_dir / "sessions.json.tmp"
        tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(index_file)

    def list_reusable_sources(self) -> List[dict]:
        sources: List[dict] = []
        with self._lock:
            roots = [
                (self.word_base_dir, "word"),
                (self.excel_base_dir, "excel"),
                (self.base_dir, "ppt"),
            ]
            for root, host in roots:
                if not root or not root.exists():
                    continue
                for d in root.iterdir():
                    if not d.is_dir():
                        continue
                    m_file = d / "manifest.json"
                    if not m_file.exists():
                        continue
                    try:
                        manifest = json.loads(m_file.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    total_docs = int(manifest.get("totalDocuments", 0))
                    if total_docs <= 0:
                        continue
                    sid = str(manifest.get("documentSessionId") or "").strip()
                    doc_ident = str(manifest.get("documentIdentity") or "").strip()
                    display_name = ""
                    if doc_ident:
                        clean_path = doc_ident.split("full:")[-1]
                        display_name = Path(clean_path).name
                    if not display_name and manifest.get("documents"):
                        display_name = manifest["documents"][0].get("fileName", "参考资料集")
                    sources.append({
                        "sourceSessionId": sid,
                        "documentIdentity": doc_ident,
                        "displayName": display_name or "未命名文档",
                        "host": host,
                        "totalDocuments": total_docs,
                        "totalCharacters": int(manifest.get("totalCharacters", 0)),
                        "updatedAt": manifest.get("updatedAt", ""),
                        "documents": manifest.get("documents", []),
                    })
        sources.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return sources

    def clone_from_source(
        self,
        source_session_id: str,
        target_session_id: str,
        target_doc_identity: str = "",
    ) -> dict:
        if not source_session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "请指定来源资料会话编号。", status_code=422)
        if not target_session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "请指定目标演示文稿会话编号。", status_code=422)

        # Match Excel's Excel -> Word lock order; acquire PPT last.
        with (self.excel_store._lock if self.excel_store is not None else nullcontext()), \
                (self.word_store._lock if self.word_store is not None else nullcontext()), self._lock:
            self._check_busy(target_session_id)
            source_dir = self._get_dir_for_session(source_session_id, self.word_base_dir)
            if not source_dir:
                source_dir = self._get_dir_for_session(source_session_id, self.excel_base_dir)
            if not source_dir:
                source_dir = self._get_dir_for_session(source_session_id, self.base_dir)
            if not source_dir or not source_dir.exists():
                raise AdapterError("MATERIAL_NOT_FOUND", "来源资料不存在或已删除，无法复用。", status_code=404)

            source_m_file = source_dir / "manifest.json"
            if not source_m_file.exists():
                raise AdapterError("MATERIAL_NOT_FOUND", "来源资料清单损坏或不存在。", status_code=404)

            try:
                manifest = json.loads(source_m_file.read_text(encoding="utf-8"))
            except Exception as e:
                raise AdapterError("MATERIAL_NOT_FOUND", "读取来源资料清单失败。", status_code=500) from e

            target_dir_name = self._resolve_dir_name(target_session_id, target_doc_identity)
            target_dir = self.base_dir / target_dir_name
            existing_target = self._get_dir_for_session(target_session_id)
            if existing_target:
                target_dir = existing_target
                target_dir_name = target_dir.name

            if source_dir.resolve() == target_dir.resolve():
                raise AdapterError(
                    "CANNOT_REUSE_SAME_DOCUMENT",
                    "当前演示文稿已包含所选资料，无法重复复用自身。",
                    status_code=409,
                )

            if self.coordinator is not None and hasattr(self.coordinator, "has_active_task"):
                if self.coordinator.has_active_task(task_type="word.material_composer", document_session_id=source_session_id) or \
                   self.coordinator.has_active_task(task_type="excel.material_ledger", document_session_id=source_session_id) or \
                   self.coordinator.has_active_task(task_type="ppt.material_outline", document_session_id=source_session_id):
                    raise AdapterError("MATERIAL_COMPOSER_BUSY", "来源资料正在生成任务，请稍后复用。", status_code=409)

            index_file = self.base_dir / "sessions.json"
            previous_index = index_file.read_bytes() if index_file.exists() else None
            temp_target_dir = Path(tempfile.mkdtemp(prefix=".clone-", dir=str(self.base_dir)))
            backup = None
            published = False
            try:
                source_files = source_dir / "files"
                target_files = temp_target_dir / "files"
                target_files.mkdir(parents=True, exist_ok=True)
                if source_files.exists():
                    for f in source_files.iterdir():
                        if f.is_file():
                            shutil.copy2(f, target_files / f.name)

                source_mats = source_dir / "materials"
                target_mats = temp_target_dir / "materials"
                target_mats.mkdir(parents=True, exist_ok=True)
                if source_mats.exists():
                    for f in source_mats.iterdir():
                        if f.is_file():
                            try:
                                view = json.loads(f.read_text(encoding="utf-8"))
                                view["documentSessionId"] = target_session_id
                                (target_mats / f.name).write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
                            except Exception:
                                shutil.copy2(f, target_mats / f.name)

                now_iso = _updated_at()
                new_manifest = dict(manifest)
                new_manifest["documentSessionId"] = target_session_id
                new_manifest["documentIdentity"] = target_doc_identity
                new_manifest["clonedFromSessionId"] = source_session_id
                new_manifest["updatedAt"] = now_iso
                (temp_target_dir / "manifest.json").write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

                source_cache = source_dir / "catalog_cache.json"
                catalog: dict = {}
                if source_cache.exists():
                    try:
                        catalog = json.loads(source_cache.read_text(encoding="utf-8"))
                        catalog["documentSessionId"] = target_session_id
                        catalog["documentIdentity"] = target_doc_identity
                        catalog["updatedAt"] = now_iso
                    except Exception:
                        catalog = {}
                if not catalog:
                    catalog = {
                        "documentSessionId": target_session_id,
                        "documentIdentity": target_doc_identity,
                        "totalDocuments": new_manifest.get("totalDocuments", 0),
                        "totalCharacters": new_manifest.get("totalCharacters", 0),
                        "totalTableCells": new_manifest.get("totalTableCells", 0),
                        "characterCountMethod": CHARACTER_COUNT_METHOD,
                        "documents": new_manifest.get("documents", []),
                        "toc": [],
                        "blocks": [],
                        "fragmentsList": [],
                        "fragments": {},
                        "limits": {
                            "documentLimit": MATERIAL_IMPORT_MAX_DOCUMENTS,
                            "readableCharacterLimit": MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
                            "tableColumnLimit": MATERIAL_IMPORT_MAX_TABLE_COLUMNS,
                            "tableCellLimit": MATERIAL_IMPORT_MAX_TABLE_CELLS,
                            "productConfirmed": False,
                        },
                        "updatedAt": now_iso,
                    }
                (temp_target_dir / "catalog_cache.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

                if target_dir.exists():
                    backup = self.base_dir / (".previous-" + secrets.token_hex(8))
                    target_dir.rename(backup)
                try:
                    temp_target_dir.rename(target_dir)
                    published = True
                    self._update_session_index(target_session_id, target_dir_name)
                except Exception:
                    if published and target_dir.exists():
                        shutil.rmtree(target_dir)
                    if backup is not None:
                        backup.rename(target_dir)
                        backup = None
                    if previous_index is None:
                        if index_file.exists():
                            index_file.unlink()
                    else:
                        index_file.write_bytes(previous_index)
                    raise
            except Exception as e:
                if temp_target_dir.exists():
                    shutil.rmtree(temp_target_dir, ignore_errors=True)
                raise AdapterError("MATERIAL_CLONE_FAILED", "复用资料失败，未能建立演示文稿资料副本。", status_code=500) from e

            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            self._memory_catalogs.pop(target_session_id, None)
            return self.get_catalog(target_session_id)

    def import_material(
        self,
        session_id: str,
        doc_identity: str,
        file_name: str,
        content_base64: str,
    ) -> dict:
        if not session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效演示文稿会话编号。", status_code=422)

        with self._lock:
            self._check_busy(session_id)
            content = _decode_upload(content_base64)
            _reject_wrong_type(file_name, "")
            catalog = self.get_catalog(session_id)
            if len(catalog.get("documents", [])) >= MATERIAL_IMPORT_MAX_DOCUMENTS:
                raise AdapterError(
                    "MATERIAL_COUNT_OVER_LIMIT",
                    "资料份数超过上限（最多5份），已拒绝导入，未截断内容。",
                    status_code=400,
                )
            try:
                validated = validate_docx_bytes(content)
            except DocxSecurityError as exc:
                raise _security_error(exc) from exc

            existing_cells = catalog.get("totalTableCells", 0)
            start_fragment_index = _next_fragment_index(catalog)

            reading = _read_document(
                validated.document_xml,
                validated.style_names,
                content,
                remaining_table_cells=MATERIAL_IMPORT_MAX_TABLE_CELLS - existing_cells,
                start_fragment_index=start_fragment_index,
            )
            char_count = reading["limits"]["readableCharacterCount"]
            if catalog.get("totalCharacters", 0) + char_count > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
                raise AdapterError(
                    "MATERIAL_TEXT_OVER_LIMIT",
                    "可读取文字超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )

            material_id = "mat_{0}".format(secrets.token_hex(8))
            for frag in reading["fragments"]:
                frag["fileName"] = file_name
                frag["materialId"] = material_id
            for block in reading["blocks"]:
                block["materialId"] = material_id

            now_iso = _updated_at()
            doc_entry = {
                "materialId": material_id,
                "fileName": file_name,
                "fileSha256": hashlib.sha256(content).hexdigest(),
                "characterCount": char_count,
                "readableCharacterCount": char_count,
                "blocksCount": len(reading["blocks"]),
                "fragmentsCount": len(reading["fragments"]),
                "tableCellsCount": reading["limits"].get("extractedTableCells", 0),
                "importedAt": now_iso,
                "updatedAt": now_iso,
            }
            catalog["documents"].append(doc_entry)
            catalog["totalDocuments"] = len(catalog["documents"])
            catalog["totalCharacters"] += char_count
            catalog["totalTableCells"] = catalog.get("totalTableCells", 0) + reading["limits"].get("extractedTableCells", 0)
            catalog["blocks"].extend(reading["blocks"])
            catalog["fragmentsList"].extend(reading["fragments"])
            for frag in reading["fragments"]:
                catalog["fragments"][str(frag["fragmentId"])] = frag

            dir_name = self._resolve_dir_name(session_id, doc_identity)
            d = self._get_dir_for_session(session_id) or self.base_dir / dir_name
            dir_name = d.name
            d.mkdir(parents=True, exist_ok=True)
            files_dir = d / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            mats_dir = d / "materials"
            mats_dir.mkdir(parents=True, exist_ok=True)

            (files_dir / "{0}.docx".format(material_id)).write_bytes(content)

            view = {
                "materialId": material_id,
                "fileName": file_name,
                "characterCount": char_count,
                "readableCharacterCount": char_count,
                "blocks": reading["blocks"],
                "fragments": reading["fragments"],
                "toc": reading.get("headings", reading.get("toc", [])),
                "importedAt": now_iso,
                "updatedAt": now_iso,
                "documentSessionId": session_id,
            }
            (mats_dir / "{0}.json".format(material_id)).write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")

            manifest = {
                "documentSessionId": session_id,
                "documentIdentity": doc_identity,
                "totalDocuments": catalog["totalDocuments"],
                "totalCharacters": catalog["totalCharacters"],
                "totalTableCells": catalog.get("totalTableCells", 0),
                "updatedAt": now_iso,
                "documents": catalog["documents"],
            }
            (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            (d / "catalog_cache.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
            self._update_session_index(session_id, dir_name)
            self._memory_catalogs[session_id] = catalog
            return view

    def update_material(
        self,
        session_id: str,
        material_id: str,
        file_name: str,
        content_base64: str,
    ) -> dict:
        if not session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效演示文稿会话编号。", status_code=422)
        if not material_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少资料编号。", status_code=422)

        with self._lock:
            self._check_busy(session_id)
            content = _decode_upload(content_base64)
            _reject_wrong_type(file_name, "")
            catalog = self.get_catalog(session_id)
            doc_idx = -1
            old_doc = None
            for idx, d in enumerate(catalog.get("documents", [])):
                if d.get("materialId") == material_id:
                    doc_idx = idx
                    old_doc = d
                    break
            if doc_idx < 0 or not old_doc:
                raise AdapterError("MATERIAL_NOT_FOUND", "待更新的资料不存在或已删除。", status_code=404)

            try:
                validated = validate_docx_bytes(content)
            except DocxSecurityError as exc:
                raise _security_error(exc) from exc

            reading = _read_document(
                validated.document_xml,
                validated.style_names,
                content,
                remaining_table_cells=MATERIAL_IMPORT_MAX_TABLE_CELLS - catalog.get("totalTableCells", 0) + old_doc.get("tableCellsCount", old_doc.get("extractedTableCells", 0)),
                start_fragment_index=_next_fragment_index(catalog),
            )
            char_count = reading["limits"]["readableCharacterCount"]
            old_chars = old_doc.get("readableCharacterCount", 0)
            new_total = catalog.get("totalCharacters", 0) - old_chars + char_count
            if new_total > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
                raise AdapterError(
                    "MATERIAL_TEXT_OVER_LIMIT",
                    "更新后可读取文字超过本阶段实施参数上限，已拒绝更新，原资料保持不变。",
                    status_code=413,
                )

            for frag in reading["fragments"]:
                frag["fileName"] = file_name
                frag["materialId"] = material_id
            for block in reading["blocks"]:
                block["materialId"] = material_id

            now_iso = _updated_at(old_doc.get("updatedAt", ""))
            old_cells = old_doc.get("tableCellsCount", old_doc.get("extractedTableCells", 0))
            old_doc["fileName"] = file_name
            old_doc["fileSha256"] = hashlib.sha256(content).hexdigest()
            old_doc["characterCount"] = char_count
            old_doc["readableCharacterCount"] = char_count
            old_doc["blocksCount"] = len(reading["blocks"])
            old_doc["fragmentsCount"] = len(reading["fragments"])
            old_doc["tableCellsCount"] = reading["limits"].get("extractedTableCells", 0)
            old_doc["updatedAt"] = now_iso

            catalog["blocks"] = [b for b in catalog.get("blocks", []) if b.get("materialId") != material_id] + reading["blocks"]
            catalog["fragmentsList"] = [f for f in catalog.get("fragmentsList", []) if f.get("materialId") != material_id] + reading["fragments"]
            catalog["fragments"] = {k: v for k, v in catalog.get("fragments", {}).items() if v.get("materialId") != material_id}
            for frag in reading["fragments"]:
                catalog["fragments"][str(frag["fragmentId"])] = frag
            catalog["totalTableCells"] = catalog.get("totalTableCells", 0) - old_cells + reading["limits"].get("extractedTableCells", 0)
            catalog["totalCharacters"] = new_total
            catalog["totalDocuments"] = len(catalog["documents"])

            d = self._get_dir_for_session(session_id)
            if not d:
                d = self.base_dir / self._resolve_dir_name(session_id)
                d.mkdir(parents=True, exist_ok=True)
            files_dir = d / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            mats_dir = d / "materials"
            mats_dir.mkdir(parents=True, exist_ok=True)

            (files_dir / "{0}.docx".format(material_id)).write_bytes(content)
            view = {
                "materialId": material_id,
                "fileName": file_name,
                "characterCount": char_count,
                "readableCharacterCount": char_count,
                "blocks": reading["blocks"],
                "fragments": reading["fragments"],
                "toc": reading.get("headings", reading.get("toc", [])),
                "importedAt": old_doc.get("importedAt", now_iso),
                "updatedAt": now_iso,
                "documentSessionId": session_id,
            }
            (mats_dir / "{0}.json".format(material_id)).write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")

            manifest_file = d / "manifest.json"
            manifest = {}
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            manifest["totalDocuments"] = catalog["totalDocuments"]
            manifest["totalCharacters"] = catalog["totalCharacters"]
            manifest["totalTableCells"] = catalog["totalTableCells"]
            manifest["documents"] = catalog["documents"]
            manifest["updatedAt"] = now_iso
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            (d / "catalog_cache.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

            self._memory_catalogs[session_id] = catalog
            return view

    def delete_material(self, session_id: str, material_id: str) -> dict:
        if not session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效演示文稿会话编号。", status_code=422)
        if not material_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少资料编号。", status_code=422)

        with self._lock:
            self._check_busy(session_id)
            catalog = self.get_catalog(session_id)
            catalog["documents"] = [d for d in catalog.get("documents", []) if d.get("materialId") != material_id]
            catalog["blocks"] = [b for b in catalog.get("blocks", []) if b.get("materialId") != material_id]
            catalog["fragmentsList"] = [f for f in catalog.get("fragmentsList", []) if f.get("materialId") != material_id]
            catalog["fragments"] = {k: v for k, v in catalog.get("fragments", {}).items() if v.get("materialId") != material_id}
            catalog["totalDocuments"] = len(catalog["documents"])
            catalog["totalCharacters"] = sum(d.get("readableCharacterCount", 0) for d in catalog["documents"])
            catalog["totalTableCells"] = sum(d.get("tableCellsCount", d.get("extractedTableCells", 0)) for d in catalog["documents"])

            d = self._get_dir_for_session(session_id)
            if d and d.exists():
                docx_file = d / "files" / "{0}.docx".format(material_id)
                if docx_file.exists():
                    docx_file.unlink()
                mat_file = d / "materials" / "{0}.json".format(material_id)
                if mat_file.exists():
                    mat_file.unlink()

                now_iso = _updated_at()
                m_file = d / "manifest.json"
                if m_file.exists():
                    try:
                        manifest = json.loads(m_file.read_text(encoding="utf-8"))
                        manifest["documents"] = catalog["documents"]
                        manifest["totalDocuments"] = catalog["totalDocuments"]
                        manifest["totalCharacters"] = catalog["totalCharacters"]
                        manifest["totalTableCells"] = catalog["totalTableCells"]
                        manifest["updatedAt"] = now_iso
                        m_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                (d / "catalog_cache.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

            self._memory_catalogs[session_id] = catalog
            return {
                "deleted": True,
                "materialId": material_id,
                "totalDocuments": catalog["totalDocuments"],
                "totalCharacters": catalog["totalCharacters"],
                "catalogSummary": catalog,
            }

    def get_catalog(self, session_id: str) -> dict:
        if not session_id:
            return self._empty_catalog("")
        with self._lock:
            if session_id in self._memory_catalogs:
                return self._memory_catalogs[session_id]
            session_dir = self._get_dir_for_session(session_id)
            if not session_dir:
                return self._empty_catalog(session_id)
            cat_file = session_dir / "catalog_cache.json"
            if cat_file.exists():
                try:
                    cat = json.loads(cat_file.read_text(encoding="utf-8"))
                    self._memory_catalogs[session_id] = cat
                    return cat
                except Exception:
                    pass
            return self._empty_catalog(session_id)

    def bind_document(
        self,
        old_session_id: str,
        new_session_id: str,
        new_doc_identity: str,
    ) -> dict:
        if not old_session_id or not new_session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "会话编号无效。", status_code=422)

        with self._lock:
            self._check_busy(old_session_id)
            self._check_busy(new_session_id)
            old_dir = self._get_dir_for_session(old_session_id)
            if not old_dir or not old_dir.exists():
                raise AdapterError("MATERIAL_NOT_FOUND", "原会话不存在资料集，无法迁移。", status_code=404)

            new_dir_name = self._resolve_dir_name(new_session_id, new_doc_identity)
            new_dir = self.base_dir / new_dir_name
            if new_dir.exists() and new_dir != old_dir:
                m_file = new_dir / "manifest.json"
                if m_file.exists():
                    raise AdapterError("DOCUMENT_IDENTITY_CONFLICT", "目标演示文稿已存在资料集，无法迁移覆盖。", status_code=409)
            if new_dir != old_dir:
                old_dir.rename(new_dir)

            now_iso = _updated_at()
            m_file = new_dir / "manifest.json"
            manifest = json.loads(m_file.read_text(encoding="utf-8"))
            manifest["documentSessionId"] = new_session_id
            manifest["documentIdentity"] = new_doc_identity
            manifest["updatedAt"] = now_iso
            m_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            c_file = new_dir / "catalog_cache.json"
            catalog = {}
            if c_file.exists():
                catalog = json.loads(c_file.read_text(encoding="utf-8"))
                catalog["documentSessionId"] = new_session_id
                catalog["documentIdentity"] = new_doc_identity
                catalog["updatedAt"] = now_iso
                c_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

            self._update_session_index(new_session_id, new_dir_name)
            self._memory_catalogs.pop(old_session_id, None)
            self._memory_catalogs.pop(new_session_id, None)
            return self.get_catalog(new_session_id)

    def _empty_catalog(self, session_id: str) -> dict:
        return {
            "documentSessionId": session_id,
            "documentIdentity": "",
            "totalDocuments": 0,
            "totalCharacters": 0,
            "totalTableCells": 0,
            "characterCountMethod": CHARACTER_COUNT_METHOD,
            "documents": [],
            "toc": [],
            "blocks": [],
            "fragmentsList": [],
            "fragments": {},
            "limits": {
                "documentLimit": MATERIAL_IMPORT_MAX_DOCUMENTS,
                "readableCharacterLimit": MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
                "tableColumnLimit": MATERIAL_IMPORT_MAX_TABLE_COLUMNS,
                "tableCellLimit": MATERIAL_IMPORT_MAX_TABLE_CELLS,
                "productConfirmed": False,
            },
            "updatedAt": _updated_at(),
        }


ppt_material_store = PptMaterialStore()
