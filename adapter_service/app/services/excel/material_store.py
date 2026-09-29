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
import time
from contextlib import nullcontext
from typing import Dict, List, Optional

from copy import deepcopy
from app.services.excel.material_document import extract_document
from app.core.errors import AdapterError
from app.core.runtime_paths import resolve_runtime_paths
from app.services.long_task_coordinator import (
    get_long_task_coordinator,
    LongTaskCoordinator,
)
from app.services.ppt.docx_security import (
    DOCX_MAX_PACKAGE_BYTES,
    validate_docx_bytes,
)
from app.services.word.material_import import (
    MATERIAL_IMPORT_MAX_DOCUMENTS,
    MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
    MATERIAL_IMPORT_MAX_TABLE_COLUMNS,
    MATERIAL_IMPORT_MAX_TABLE_CELLS,
    CHARACTER_COUNT_METHOD,
    _decode_upload,
    _read_document,
    _next_fragment_index,
    _updated_at,
    WordMaterialStore,
)


class ExcelMaterialStore:
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        word_base_dir: Optional[Path] = None,
        ppt_base_dir: Optional[Path] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
        word_store: Optional[WordMaterialStore] = None,
    ) -> None:
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.base_dir = paths.state_dir / "excel_materials"
                else:
                    self.base_dir = paths.run_dir / "excel_materials"
            except Exception:
                self.base_dir = Path("run/excel_materials").resolve()
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

        if ppt_base_dir is not None:
            self.ppt_base_dir = Path(ppt_base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.ppt_base_dir = paths.state_dir / "ppt_materials"
                else:
                    self.ppt_base_dir = paths.run_dir / "ppt_materials"
            except Exception:
                self.ppt_base_dir = Path("run/ppt_materials").resolve()

        self.word_store = word_store
        if word_store is not None:
            self.word_base_dir = word_store.base_dir
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.RLock()
        self._conversions = {}
        self._memory_catalogs: Dict[str, dict] = {}

    def _check_busy(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        if self.coordinator is not None and hasattr(self.coordinator, "has_active_task"):
            if self.coordinator.has_active_task(
                task_type="excel.material_ledger",
                document_session_id=session_id,
            ):
                raise AdapterError(
                    "MATERIAL_COMPOSER_BUSY",
                    "任务台账正在生成中，请等待完成或取消任务后再更新/移除资料。",
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
                (self.base_dir, "excel"),
                (self.ppt_base_dir, "ppt"),
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
            raise AdapterError("REQUEST_VALIDATION_FAILED", "请指定目标工作簿会话编号。", status_code=422)

        with self._lock, (self.word_store._lock if self.word_store is not None else nullcontext()):
            self._check_busy(target_session_id)
            source_dir = self._get_dir_for_session(source_session_id, self.word_base_dir)
            if not source_dir:
                source_dir = self._get_dir_for_session(source_session_id, self.ppt_base_dir)
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
            if source_session_id == target_session_id or source_dir.resolve() == target_dir.resolve():
                raise AdapterError("MATERIAL_SOURCE_EQUALS_TARGET", "不能复用当前工作簿自身的资料。", status_code=409)
            if self.coordinator.has_active_task(task_type="word.material_composer", document_session_id=source_session_id):
                raise AdapterError("MATERIAL_COMPOSER_BUSY", "来源资料正在生成任务，请稍后复用。", status_code=409)
            self._check_busy(source_session_id)
            final_target = target_dir
            target_dir = Path(tempfile.mkdtemp(prefix=".clone-", dir=str(self.base_dir)))
            backup = None
            published = False

            try:
                # Copy files directory
                source_files = source_dir / "files"
                target_files = target_dir / "files"
                target_files.mkdir(parents=True, exist_ok=True)
                if source_files.exists():
                    for f in source_files.iterdir():
                        if f.is_file():
                            shutil.copy2(f, target_files / f.name)

                # Copy materials directory
                source_mats = source_dir / "materials"
                target_mats = target_dir / "materials"
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
                manifest["documentSessionId"] = target_session_id
                manifest["documentIdentity"] = target_doc_identity
                manifest["updatedAt"] = now_iso
                (target_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

                # Copy and rebind catalog_cache.json
                catalog: dict = {}
                source_cache = source_dir / "catalog_cache.json"
                if source_cache.exists():
                    try:
                        catalog = json.loads(source_cache.read_text(encoding="utf-8"))
                        catalog["documentSessionId"] = target_session_id
                    except Exception:
                        catalog = {}
                if not catalog:
                    catalog = {
                        "documentSessionId": target_session_id,
                        "totalDocuments": manifest.get("totalDocuments", 0),
                        "totalCharacters": manifest.get("totalCharacters", 0),
                        "totalTableCells": manifest.get("totalTableCells", 0),
                        "characterCountMethod": CHARACTER_COUNT_METHOD,
                        "documents": manifest.get("documents", []),
                        "toc": [],
                        "blocks": [],
                        "fragmentsList": [],
                        "fragments": {},
                    }
                (target_dir / "catalog_cache.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

                if final_target.exists():
                    backup = self.base_dir / (".previous-" + secrets.token_hex(8))
                    final_target.rename(backup)
                try:
                    target_dir.rename(final_target)
                    self._update_session_index(target_session_id, target_dir_name)
                    published = True
                except Exception:
                    if final_target.exists():
                        shutil.rmtree(final_target)
                    if backup is not None:
                        backup.rename(final_target)
                        backup = None
                    raise
            finally:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                if published and backup is not None and backup.exists():
                    shutil.rmtree(backup)

            self._memory_catalogs[target_session_id] = catalog
            return catalog

    def get_catalog(self, session_id: str) -> dict:
        with self._lock:
            if session_id in self._memory_catalogs:
                return self._memory_catalogs[session_id]
            d = self._get_dir_for_session(session_id)
            if not d:
                return {
                    "documentSessionId": session_id,
                    "totalDocuments": 0,
                    "totalCharacters": 0,
                    "totalTableCells": 0,
                    "characterCountMethod": CHARACTER_COUNT_METHOD,
                    "documents": [],
                    "toc": [],
                    "blocks": [],
                    "fragmentsList": [],
                    "fragments": {},
                }
            cache_file = d / "catalog_cache.json"
            if cache_file.exists():
                try:
                    cat = json.loads(cache_file.read_text(encoding="utf-8"))
                    self._memory_catalogs[session_id] = cat
                    return cat
                except Exception:
                    pass
            m_file = d / "manifest.json"
            if m_file.exists():
                try:
                    manifest = json.loads(m_file.read_text(encoding="utf-8"))
                    cat = {
                        "documentSessionId": session_id,
                        "totalDocuments": manifest.get("totalDocuments", 0),
                        "totalCharacters": manifest.get("totalCharacters", 0),
                        "totalTableCells": manifest.get("totalTableCells", 0),
                        "characterCountMethod": CHARACTER_COUNT_METHOD,
                        "documents": manifest.get("documents", []),
                        "toc": [],
                        "blocks": [],
                        "fragmentsList": [],
                        "fragments": {},
                    }
                    self._memory_catalogs[session_id] = cat
                    return cat
                except Exception:
                    pass
            return {
                "documentSessionId": session_id,
                "totalDocuments": 0,
                "totalCharacters": 0,
                "totalTableCells": 0,
                "characterCountMethod": CHARACTER_COUNT_METHOD,
                "documents": [],
                "toc": [],
                "blocks": [],
                "fragmentsList": [],
                "fragments": {},
            }

    def import_request(self, payload: dict, material_id: str = "") -> dict:
        """Import/update, or finish a session-bound native DOC conversion."""
        with self._lock:
            for token, entry in list(self._conversions.items()):
                if time.monotonic() - entry["created"] > 600:
                    entry["directory"].cleanup()
                    del self._conversions[token]
            session_id = str(payload.get("documentSessionId") or "").strip()
            if not session_id:
                raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少工作簿会话。", status_code=422)
            self._check_busy(session_id)
            token = payload.get("conversionId")
            if token:
                entry = self._conversions.get(token) if isinstance(token, str) else None
                if not entry or entry["payload"]["documentSessionId"] != session_id or entry["materialId"] != material_id:
                    raise AdapterError("MATERIAL_CONVERSION_EXPIRED", "转换会话已失效，请重新选择文件。", status_code=409)
                try:
                    if payload.get("cancelConversion") is True:
                        return {"cancelled": True}
                    path = Path(entry["directory"].name) / "converted.docx"
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > DOCX_MAX_PACKAGE_BYTES:
                        raise AdapterError("MATERIAL_CONVERSION_FAILED", "WPS 未生成有效 DOCX 副本。", status_code=422)
                    request = entry["payload"]
                    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                    if material_id:
                        return self.update_material(session_id, material_id, request["fileName"], encoded)
                    return self.import_material(session_id, request.get("documentIdentity", ""), request["fileName"], encoded)
                finally:
                    entry["directory"].cleanup()
                    del self._conversions[token]
            file_name = str(payload.get("fileName") or "").strip()
            encoded = str(payload.get("contentBase64") or "")
            if file_name.lower().endswith(".doc"):
                content = _decode_upload(encoded)
                if not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
                    raise AdapterError("MATERIAL_FILE_REJECTED", "DOC 文件格式无效。", status_code=422)
                for old_token, entry in list(self._conversions.items()):
                    if entry["payload"]["documentSessionId"] == session_id:
                        entry["directory"].cleanup()
                        del self._conversions[old_token]
                directory = tempfile.TemporaryDirectory(prefix="ai-wps-ledger-doc-")
                source = Path(directory.name) / "source.doc"
                source.write_bytes(content)
                token = secrets.token_urlsafe(24)
                self._conversions[token] = {"directory": directory, "created": time.monotonic(),
                                           "payload": dict(payload, documentSessionId=session_id), "materialId": material_id}
                return {"conversionRequired": True, "conversionId": token, "documentSessionId": session_id,
                        "sourcePath": str(source), "targetPath": str(Path(directory.name) / "converted.docx")}
            if material_id:
                return self.update_material(session_id, material_id, file_name, encoded)
            return self.import_material(session_id, str(payload.get("documentIdentity") or ""), file_name, encoded)

    def get_full_document(self, session_id: str, material_id: str) -> dict:
        with self._lock:
            doc = next((d for d in self.get_catalog(session_id)["documents"] if d["materialId"] == material_id), None)
            if not doc or not re.fullmatch(r"mat_[a-f0-9]{16}", material_id):
                raise AdapterError("MATERIAL_NOT_FOUND", "当前工作簿没有该资料。", status_code=404)
            directory = self._get_dir_for_session(session_id)
            suffix = Path(doc["fileName"]).suffix.lower()
            suffix = ".docx" if suffix == ".doc" else suffix
            path = directory / "files" / (material_id + suffix) if directory else None
            if path is None or path.is_symlink() or not path.is_file():
                raise AdapterError("MATERIAL_NOT_FOUND", "资料原始副本缺失，请重新导入。", status_code=404)
            return extract_document(path.read_bytes(), doc["fileName"])

    def _read_material(self, content, file_name, remaining_table_cells, start_fragment_index):
        whole = extract_document(content, file_name)
        if Path(file_name).suffix.lower() in (".docx", ".doc"):
            validated = validate_docx_bytes(content)
            reading = _read_document(validated.document_xml, validated.style_names, content,
                                     remaining_table_cells=remaining_table_cells,
                                     start_fragment_index=start_fragment_index)
        else:
            cells = whole.get("tableCellsCount", 0)
            if cells > remaining_table_cells:
                raise AdapterError("MATERIAL_TABLE_OVER_LIMIT", "表格单元格超过上限，未截断。", status_code=413)
            blocks = whole["blocks"]
            reading = {"blocks": blocks,
                       "fragments": [dict(b, fragmentId="frag-%d" % (start_fragment_index + i))
                                     for i, b in enumerate(blocks) if b.get("text")],
                       "limits": {"readableCharacterCount": sum(len(b.get("text", "")) for b in blocks),
                                  "extractedTableCells": cells}}
        reading["limits"]["readableCharacterCount"] = sum(len(b.get("text", "")) for b in whole["blocks"])
        reading["fullReading"] = {"complete": whole["complete"], "imageCount": len(whole["images"]),
                                  "unreadObjects": whole["unreadObjects"],
                                  "hiddenContentIncluded": whole.get("hiddenContentIncluded", False)}
        return reading

    def import_material(
        self,
        session_id: str,
        doc_identity: str,
        file_name: str,
        content_base64: str,
    ) -> dict:
        with self._lock:
            self._check_busy(session_id)
            content = _decode_upload(content_base64)
            catalog = deepcopy(self.get_catalog(session_id))
            if len(catalog.get("documents", [])) >= MATERIAL_IMPORT_MAX_DOCUMENTS:
                raise AdapterError(
                    "MATERIAL_COUNT_OVER_LIMIT",
                    "资料份数超过上限（最多5份），已拒绝导入，未截断内容。",
                    status_code=400,
                )
            existing_cells = catalog.get("totalTableCells", 0)
            start_fragment_index = _next_fragment_index(catalog)

            reading = self._read_material(
                content, file_name,
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
                "readableCharacterCount": char_count,
                "blocksCount": len(reading["blocks"]),
                "fullReading": reading["fullReading"],
                "fragmentsCount": len(reading["fragments"]),
                "tableCellsCount": reading["limits"].get("extractedTableCells", 0),
                "importedAt": now_iso,
                "updatedAt": now_iso,
            }
            catalog["documents"].append(doc_entry)
            catalog["totalDocuments"] = len(catalog["documents"])
            catalog["totalCharacters"] += char_count
            catalog["totalTableCells"] += reading["limits"].get("extractedTableCells", 0)
            catalog["blocks"].extend(reading["blocks"])
            catalog["fragmentsList"].extend(reading["fragments"])
            for frag in reading["fragments"]:
                catalog["fragments"][str(frag["fragmentId"])] = frag

            # Save on disk
            dir_name = self._resolve_dir_name(session_id, doc_identity)
            d = self._get_dir_for_session(session_id) or self.base_dir / dir_name
            dir_name = d.name
            d.mkdir(parents=True, exist_ok=True)
            files_dir = d / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            mats_dir = d / "materials"
            mats_dir.mkdir(parents=True, exist_ok=True)

            (files_dir / "{0}{1}".format(material_id, ".docx" if file_name.lower().endswith(".doc") else Path(file_name).suffix.lower())).write_bytes(content)

            view = {
                "materialId": material_id,
                "fileName": file_name,
                "readableCharacterCount": char_count,
                "blocks": reading["blocks"],
                "fullReading": reading["fullReading"],
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
                "totalTableCells": catalog["totalTableCells"],
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
        with self._lock:
            self._check_busy(session_id)
            content = _decode_upload(content_base64)
            catalog = deepcopy(self.get_catalog(session_id))
            doc_idx = -1
            old_doc = None
            for idx, d in enumerate(catalog.get("documents", [])):
                if d.get("materialId") == material_id:
                    doc_idx = idx
                    old_doc = d
                    break
            if doc_idx < 0 or not old_doc:
                raise AdapterError("MATERIAL_NOT_FOUND", "待更新的资料不存在或已删除。", status_code=404)

            reading = self._read_material(
                content, file_name,
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
            old_doc["fullReading"] = reading["fullReading"]
            old_doc["fileName"] = file_name
            old_doc["fileSha256"] = hashlib.sha256(content).hexdigest()
            old_doc["readableCharacterCount"] = char_count
            old_doc["blocksCount"] = len(reading["blocks"])
            old_doc["fragmentsCount"] = len(reading["fragments"])
            old_doc["tableCellsCount"] = reading["limits"].get("extractedTableCells", 0)
            old_doc["updatedAt"] = now_iso

            # Rebuild blocks and fragments
            catalog["blocks"] = [b for b in catalog.get("blocks", []) if b.get("materialId") != material_id] + reading["blocks"]
            catalog["fragmentsList"] = [f for f in catalog.get("fragmentsList", []) if f.get("materialId") != material_id] + reading["fragments"]
            catalog["fragments"] = {k: v for k, v in catalog.get("fragments", {}).items() if v.get("materialId") != material_id}
            for frag in reading["fragments"]:
                catalog["fragments"][str(frag["fragmentId"])] = frag
            catalog["totalTableCells"] = catalog.get("totalTableCells", 0) - old_cells + reading["limits"].get("extractedTableCells", 0)
            catalog["totalCharacters"] = new_total
            catalog["totalDocuments"] = len(catalog["documents"])

            # Write to disk
            d = self._get_dir_for_session(session_id)
            if not d:
                d = self.base_dir / self._resolve_dir_name(session_id)
                d.mkdir(parents=True, exist_ok=True)
            files_dir = d / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            mats_dir = d / "materials"
            mats_dir.mkdir(parents=True, exist_ok=True)

            (files_dir / "{0}{1}".format(material_id, ".docx" if file_name.lower().endswith(".doc") else Path(file_name).suffix.lower())).write_bytes(content)
            view = {
                "materialId": material_id,
                "fileName": file_name,
                "readableCharacterCount": char_count,
                "blocks": reading["blocks"],
                "fullReading": reading["fullReading"],
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
        with self._lock:
            self._check_busy(session_id)
            catalog = deepcopy(self.get_catalog(session_id))
            catalog["documents"] = [d for d in catalog.get("documents", []) if d.get("materialId") != material_id]
            catalog["blocks"] = [b for b in catalog.get("blocks", []) if b.get("materialId") != material_id]
            catalog["fragmentsList"] = [f for f in catalog.get("fragmentsList", []) if f.get("materialId") != material_id]
            catalog["fragments"] = {k: v for k, v in catalog.get("fragments", {}).items() if v.get("materialId") != material_id}
            catalog["totalDocuments"] = len(catalog["documents"])
            catalog["totalCharacters"] = sum(d.get("readableCharacterCount", 0) for d in catalog["documents"])
            catalog["totalTableCells"] = sum(d.get("tableCellsCount", d.get("extractedTableCells", 0)) for d in catalog["documents"])

            d = self._get_dir_for_session(session_id)
            if d and d.exists():
                if not re.fullmatch(r"mat_[a-f0-9]{16}", material_id):
                    raise AdapterError("MATERIAL_NOT_FOUND", "资料编号无效。", status_code=404)
                for suffix in (".docx", ".csv", ".xlsx"):
                    original = d / "files" / (material_id + suffix)
                    if original.exists():
                        original.unlink()
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
                "totalDocuments": catalog["totalDocuments"],
                "totalCharacters": catalog["totalCharacters"],
                "catalogSummary": catalog,
            }

    def bind_document(
        self,
        old_session_id: str,
        new_session_id: str,
        new_doc_identity: str,
    ) -> dict:
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
                    raise AdapterError("DOCUMENT_IDENTITY_CONFLICT", "目标工作簿已存在资料集，无法迁移覆盖。", status_code=409)
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
                c_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

            for mat_file in (new_dir / "materials").glob("*.json"):
                try:
                    view = json.loads(mat_file.read_text(encoding="utf-8"))
                    view["documentSessionId"] = new_session_id
                    mat_file.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass

            self._update_session_index(new_session_id, new_dir_name)
            self._memory_catalogs[new_session_id] = catalog
            self._memory_catalogs.pop(old_session_id, None)
            return {
                "totalDocuments": manifest.get("totalDocuments", 0),
                "totalCharacters": manifest.get("totalCharacters", 0),
                "catalogSummary": catalog,
            }
