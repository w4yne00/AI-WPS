import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import threading
import tempfile
import time
import zipfile
from typing import Dict, List, Optional
from xml.etree import ElementTree

from app.core.errors import AdapterError
from app.core.runtime_paths import resolve_runtime_paths
from app.services.long_task_coordinator import get_long_task_coordinator, LongTaskCoordinator
from app.services.ppt.docx_security import (
    DOCX_MAX_PACKAGE_BYTES,
    DocxSecurityError,
    validate_docx_bytes,
)


TASK_TYPE = "word.material_composer"
MATERIAL_IMPORT_MAX_DOCUMENTS = 5
MATERIAL_IMPORT_MAX_READABLE_CHARACTERS = 100000
MATERIAL_IMPORT_MAX_TABLE_COLUMNS = 256
MATERIAL_IMPORT_MAX_TABLE_CELLS = 100000
CHARACTER_COUNT_METHOD = "unicode_codepoints_of_extracted_readable_text"
_MAX_FRAGMENT_CHARACTERS = 256
_PART = "word/document.xml"
_HEADING_NAME = re.compile(r"^(?:Heading|标题)\s*([1-6])$", re.IGNORECASE)


class WordMaterialStore:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        else:
            try:
                paths = resolve_runtime_paths()
                if paths.shared_state_enabled:
                    self.base_dir = paths.state_dir / "word_materials"
                else:
                    self.base_dir = paths.run_dir / "word_materials"
            except Exception:
                self.base_dir = Path("run/word_materials").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if not self.base_dir.exists():
                return
            import shutil
            if session_id:
                d = self._get_dir_for_session(session_id)
                if d and d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                index_file = self.base_dir / "sessions.json"
                if index_file.exists():
                    try:
                        index = json.loads(index_file.read_text(encoding="utf-8"))
                        if session_id in index:
                            del index[session_id]
                            index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
            else:
                for item in self.base_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    elif item.is_file():
                        item.unlink()


    def _resolve_dir_name(self, session_id: str, doc_identity: str = "") -> str:
        if doc_identity:
            h = hashlib.sha256(doc_identity.encode("utf-8")).hexdigest()[:16]
            return "doc_{0}".format(h)
        if session_id:
            h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
            return "sess_{0}".format(h)
        return "default"

    def _get_dir_for_session(self, session_id: str) -> Optional[Path]:
        if not self.base_dir.exists():
            return None
        index_file = self.base_dir / "sessions.json"
        if index_file.exists():
            try:
                index = json.loads(index_file.read_text(encoding="utf-8"))
                if session_id in index:
                    d = self.base_dir / index[session_id]
                    if d.exists():
                        return d
            except Exception:
                pass
        for d in self.base_dir.iterdir():
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

    def save_material(
        self,
        session_id: str,
        doc_identity: str,
        material_id: str,
        file_name: str,
        raw_docx_bytes: bytes,
        reading: dict,
        view: dict,
        catalog: dict,
    ) -> None:
        with self._lock:
            existing_dir = self._get_dir_for_session(session_id)
            if existing_dir is not None:
                d = existing_dir
                dir_name = d.name
            else:
                dir_name = self._resolve_dir_name(session_id, doc_identity)
                d = self.base_dir / dir_name
                d.mkdir(parents=True, exist_ok=True)

            files_dir = d / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            mats_dir = d / "materials"
            mats_dir.mkdir(parents=True, exist_ok=True)

            docx_path = files_dir / "{0}.docx".format(material_id)
            docx_path.write_bytes(raw_docx_bytes)

            mat_path = mats_dir / "{0}.json".format(material_id)
            mat_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")

            now_iso = view["updatedAt"]
            manifest_file = d / "manifest.json"
            manifest = {
                "documentSessionId": session_id,
                "documentIdentity": doc_identity,
                "totalDocuments": catalog["totalDocuments"],
                "totalCharacters": catalog["totalCharacters"],
                "totalTableCells": catalog.get("totalTableCells", 0),
                "updatedAt": now_iso,
                "documents": list(catalog["documents"]),
            }
            sha = hashlib.sha256(raw_docx_bytes).hexdigest()
            for doc in manifest["documents"]:
                if doc["materialId"] == material_id:
                    doc["fileSha256"] = sha
                    doc.setdefault("importedAt", now_iso)
                    doc["updatedAt"] = now_iso
            tmp_m = d / "manifest.json.tmp"
            tmp_m.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_m.replace(manifest_file)

            cache_file = d / "catalog_cache.json"
            tmp_c = d / "catalog_cache.json.tmp"
            tmp_c.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_c.replace(cache_file)

            if session_id:
                self._update_session_index(session_id, dir_name)

    def load_session_catalog(self, session_id: str) -> Optional[dict]:
        with self._lock:
            d = self._get_dir_for_session(session_id)
            if not d:
                return None
            cache_file = d / "catalog_cache.json"
            if cache_file.exists():
                try:
                    return json.loads(cache_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return None

    def load_material_view(self, material_id: str) -> Optional[dict]:
        with self._lock:
            if not self.base_dir.exists():
                return None
            for d in self.base_dir.iterdir():
                if d.is_dir():
                    m_file = d / "materials" / "{0}.json".format(material_id)
                    if m_file.exists():
                        try:
                            return json.loads(m_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass
            return None

    def bind_document(self, old_session_id: str, new_session_id: str, new_doc_identity: str) -> dict:
        with self._lock:
            old_dir = self._get_dir_for_session(old_session_id)
            if not old_dir:
                raise AdapterError("MATERIAL_NOT_FOUND", "原会话不存在资料集，无法迁移。", status_code=404)
            new_dir_name = self._resolve_dir_name(new_session_id, new_doc_identity)
            new_dir = self.base_dir / new_dir_name
            if new_dir.exists() and new_dir != old_dir:
                m_file = new_dir / "manifest.json"
                if m_file.exists():
                    raise AdapterError("DOCUMENT_IDENTITY_CONFLICT", "目标文档已存在资料集，无法迁移覆盖。", status_code=409)
            if new_dir != old_dir:
                old_dir.rename(new_dir)
            m_file = new_dir / "manifest.json"
            manifest = json.loads(m_file.read_text(encoding="utf-8"))
            manifest["documentSessionId"] = new_session_id
            manifest["documentIdentity"] = new_doc_identity
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            manifest["updatedAt"] = now_iso
            m_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            c_file = new_dir / "catalog_cache.json"
            catalog = {}
            if c_file.exists():
                catalog = json.loads(c_file.read_text(encoding="utf-8"))
                catalog["documentSessionId"] = new_session_id
                c_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

            for mat_file in (new_dir / "materials").glob("*.json"):
                view = json.loads(mat_file.read_text(encoding="utf-8"))
                view["documentSessionId"] = new_session_id
                tmp_file = mat_file.with_suffix(".json.tmp")
                tmp_file.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_file.replace(mat_file)

            self._update_session_index(new_session_id, new_dir_name)
            return {
                "totalDocuments": manifest["totalDocuments"],
                "totalCharacters": manifest["totalCharacters"],
                "documents": manifest["documents"],
                "toc": catalog.get("toc", []) if c_file.exists() else []
            }

    def delete_material(
        self,
        session_id: str,
        material_id: str,
        catalog: Optional[dict] = None,
    ) -> None:
        with self._lock:
            d = self._get_dir_for_session(session_id) if session_id else None
            if not d and self.base_dir.exists():
                for sub_d in self.base_dir.iterdir():
                    if sub_d.is_dir() and (sub_d / "files" / "{0}.docx".format(material_id)).exists():
                        d = sub_d
                        break
            if not d or not d.exists():
                return

            docx_file = d / "files" / "{0}.docx".format(material_id)
            if docx_file.exists():
                docx_file.unlink()

            mat_file = d / "materials" / "{0}.json".format(material_id)
            if mat_file.exists():
                mat_file.unlink()

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            manifest_file = d / "manifest.json"
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    manifest["documents"] = [
                        doc for doc in manifest.get("documents", [])
                        if doc.get("materialId") != material_id
                    ]
                    manifest["totalDocuments"] = len(manifest["documents"])
                    manifest["totalCharacters"] = sum(
                        doc.get("readableCharacterCount", 0)
                        for doc in manifest["documents"]
                    )
                    if catalog is not None:
                        manifest["totalTableCells"] = catalog.get("totalTableCells", 0)
                    manifest["updatedAt"] = now_iso
                    tmp_m = d / "manifest.json.tmp"
                    tmp_m.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp_m.replace(manifest_file)
                except Exception:
                    pass

            cache_file = d / "catalog_cache.json"
            if catalog is not None:
                tmp_c = d / "catalog_cache.json.tmp"
                tmp_c.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_c.replace(cache_file)
            elif cache_file.exists():
                try:
                    cat = json.loads(cache_file.read_text(encoding="utf-8"))
                    cat["documents"] = [
                        doc for doc in cat.get("documents", [])
                        if doc.get("materialId") != material_id
                    ]
                    cat["toc"] = [
                        t for t in cat.get("toc", [])
                        if t.get("materialId") != material_id
                    ]
                    cat["blocks"] = [
                        b for b in cat.get("blocks", [])
                        if b.get("materialId") != material_id
                    ]
                    cat["fragmentsList"] = [
                        f for f in cat.get("fragmentsList", [])
                        if f.get("materialId") != material_id
                    ]
                    cat["fragments"] = {
                        k: v for k, v in cat.get("fragments", {}).items()
                        if v.get("materialId") != material_id
                    }
                    cat["totalDocuments"] = len(cat["documents"])
                    cat["totalCharacters"] = sum(
                        doc.get("readableCharacterCount", 0)
                        for doc in cat["documents"]
                    )
                    tmp_c = d / "catalog_cache.json.tmp"
                    tmp_c.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp_c.replace(cache_file)
                except Exception:
                    pass


class WordMaterialImportService:
    def __init__(
        self,
        state_dir: Optional[Path] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self._conversions = {}
        self._materials = {}
        self._session_catalogs = {}
        self._import_lock = threading.RLock()
        self._store = WordMaterialStore(base_dir=state_dir)
        self._coordinator = (
            coordinator if coordinator is not None else get_long_task_coordinator()
        )

    def _check_composer_busy(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        if self._coordinator is not None and hasattr(self._coordinator, "has_active_task"):
            if self._coordinator.has_active_task(
                task_type="word.material_composer",
                document_session_id=session_id,
            ):
                raise AdapterError(
                    "MATERIAL_COMPOSER_BUSY",
                    "章节草稿正在生成中，请等待完成或取消任务后再更新/移除资料。",
                    status_code=409,
                )

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._import_lock:
            if session_id:
                self._session_catalogs.pop(session_id, None)
                self._store.clear(session_id)
            else:
                self._session_catalogs.clear()
                self._materials.clear()
                self._store.clear()

    def import_material(self, request: dict) -> dict:
        with self._import_lock:
            self._expire_conversions()
            if isinstance(request, dict) and request.get("conversionId"):
                return self._finish_conversion(request)
            return self._import_material(request)

    def _expire_conversions(self):
        for token, entry in list(self._conversions.items()):
            if time.monotonic() - entry["created"] > 600:
                entry["directory"].cleanup()
                del self._conversions[token]

    def _stage_conversion(self, payload: dict, content: bytes, material_id: str = "") -> dict:
        session_id = str(payload.get("documentSessionId") or "").strip()
        if not session_id or not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise AdapterError("MATERIAL_FILE_REJECTED", "DOC 文件无效或缺少文档会话。", status_code=400)
        self._expire_conversions()
        # One pending conversion per document avoids leaking copies on retries.
        for token, entry in list(self._conversions.items()):
            if entry["payload"].get("documentSessionId") == session_id:
                entry["directory"].cleanup()
                del self._conversions[token]
        directory = tempfile.TemporaryDirectory(prefix="ai-wps-doc-")
        source = Path(directory.name) / "source.doc"
        target = Path(directory.name) / "converted.docx"
        source.write_bytes(content)
        token = secrets.token_urlsafe(24)
        self._conversions[token] = {"directory": directory, "created": time.monotonic(),
                                   "payload": dict(payload), "materialId": material_id}
        return {"conversionRequired": True, "conversionId": token,
                "documentSessionId": session_id, "sourcePath": str(source), "targetPath": str(target)}

    def _finish_conversion(self, payload: dict) -> dict:
        token = payload.get("conversionId")
        entry = self._conversions.get(token) if isinstance(token, str) else None
        if not entry or entry["payload"].get("documentSessionId") != payload.get("documentSessionId"):
            raise AdapterError("MATERIAL_CONVERSION_EXPIRED", "转换会话已失效，请重新选择文件。", status_code=409)
        try:
            if payload.get("cancelConversion") is True:
                return {"cancelled": True}
            target = Path(entry["directory"].name) / "converted.docx"
            if target.is_symlink() or not target.is_file() or target.stat().st_size > DOCX_MAX_PACKAGE_BYTES:
                raise AdapterError("MATERIAL_CONVERSION_FAILED", "WPS 未生成有效的 DOCX 临时副本。", status_code=422)
            converted = target.read_bytes()
            try:
                validate_docx_bytes(converted)
            except DocxSecurityError as exc:
                raise _security_error(exc) from exc
            request = dict(entry["payload"], contentBase64=base64.b64encode(converted).decode("ascii"), sizeBytes=len(converted))
            if entry["materialId"]:
                return self._update_material(entry["materialId"], request, converted_doc=True)
            return self._import_material(request, converted_doc=True)
        finally:
            entry["directory"].cleanup()
            del self._conversions[token]

    def _import_material(self, request: dict, converted_doc: bool = False) -> dict:
        payload = request or {}
        session_id = str(
            payload.get("documentSessionId") or payload.get("document_session_id") or ""
        ).strip()
        self._check_composer_busy(session_id)
        file_name = str(payload.get("fileName") or payload.get("file_name") or "")
        content = _decode_upload(payload.get("contentBase64") or payload.get("content_base64"))
        if file_name.lower().endswith(".doc") and not converted_doc:
            return self._stage_conversion(payload, content)
        if not converted_doc:
            _reject_wrong_type(file_name, str(payload.get("mimeType") or payload.get("mime_type") or ""))
        doc_identity = str(
            payload.get("documentIdentity") or payload.get("document_identity") or ""
        ).strip()

        if session_id:
            existing_cat = self.get_session_catalog(session_id)
            if existing_cat and len(existing_cat["documents"]) >= MATERIAL_IMPORT_MAX_DOCUMENTS:
                raise AdapterError(
                    "MATERIAL_COUNT_OVER_LIMIT",
                    "资料份数超过上限（最多5份），已拒绝导入，未截断内容。",
                    status_code=400,
                )

        try:
            validated = validate_docx_bytes(content)
        except DocxSecurityError as exc:
            raise _security_error(exc) from exc

        existing_cells = 0
        start_fragment_index = 1
        if session_id and self.get_session_catalog(session_id):
            cat = self._session_catalogs[session_id]
            existing_cells = cat.get("totalTableCells", 0)
            start_fragment_index = _next_fragment_index(cat)

        reading = _read_document(
            validated.document_xml,
            validated.style_names,
            content,
            remaining_table_cells=MATERIAL_IMPORT_MAX_TABLE_CELLS - existing_cells,
            start_fragment_index=start_fragment_index,
        )
        char_count = reading["limits"]["readableCharacterCount"]
        doc_cells = reading["limits"].get("extractedTableCells", 0)

        if session_id and session_id in self._session_catalogs:
            current_total = self._session_catalogs[session_id]["totalCharacters"]
            if current_total + char_count > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
                raise AdapterError(
                    "MATERIAL_TEXT_OVER_LIMIT",
                    "可读取文字超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )
        elif char_count > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
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
            block["fileName"] = file_name
            block["materialId"] = material_id

        now_iso = _updated_at()
        doc_summary = {
            "materialId": material_id,
            "fileName": file_name,
            "readableCharacterCount": char_count,
            "extractedTableCells": doc_cells,
            "blocksCount": len(reading["blocks"]),
            "fragmentsCount": len(reading["fragments"]),
            "fullReading": reading["fullReading"],
            "importedAt": now_iso,
            "updatedAt": now_iso,
        }

        doc_toc = []
        for block in reading["blocks"]:
            if block.get("kind") == "heading":
                doc_toc.append({
                    "materialId": material_id,
                    "fileName": file_name,
                    "headingLevel": block.get("level", 1),
                    "sectionTitle": block.get("text", ""),
                    "blockId": block.get("blockId", ""),
                })

        if session_id:
            if session_id not in self._session_catalogs:
                self._session_catalogs[session_id] = {
                    "documentSessionId": session_id,
                    "documents": [],
                    "toc": [],
                    "blocks": [],
                    "fragments": {},
                    "fragmentsList": [],
                    "totalCharacters": 0,
                    "totalDocuments": 0,
                    "totalTableCells": 0,
                }
            cat = self._session_catalogs[session_id]
            cat["documents"].append(doc_summary)
            cat["toc"].extend(doc_toc)
            cat["blocks"].extend(reading["blocks"])
            for frag in reading["fragments"]:
                f_item = dict(frag)
                f_item["fileName"] = file_name
                cat["fragments"][frag["fragmentId"]] = f_item
                cat["fragmentsList"].append(f_item)
            cat["totalCharacters"] += char_count
            cat["totalTableCells"] += doc_cells
            cat["totalDocuments"] = len(cat["documents"])

            catalog_summary = {
                "totalDocuments": cat["totalDocuments"],
                "totalCharacters": cat["totalCharacters"],
                "documents": list(cat["documents"]),
                "toc": list(cat["toc"]),
            }
        else:
            catalog_summary = {
                "totalDocuments": 1,
                "totalCharacters": char_count,
                "documents": [doc_summary],
                "toc": doc_toc,
            }

        view = {
            "materialId": material_id,
            "taskType": TASK_TYPE,
            "fileName": file_name,
            "documentSessionId": session_id,
            "sourceFileUnchanged": True,
            "targetDocumentUnchanged": True,
            "understandsAllContent": False,
            "fullReading": reading["fullReading"],
            "limits": reading["limits"],
            "disclosure": reading["disclosure"],
            "unreadRegions": reading["unreadRegions"],
            "blocks": reading["blocks"],
            "fragments": reading["fragments"],
            "importedAt": now_iso,
            "updatedAt": now_iso,
            "catalogSummary": catalog_summary,
        }
        self._materials[material_id] = view
        cat_for_store = cat if session_id else {
            "documentSessionId": session_id,
            "totalDocuments": 1,
            "totalCharacters": char_count,
            "totalTableCells": doc_cells,
            "documents": [doc_summary],
            "toc": doc_toc,
            "blocks": reading["blocks"],
            "fragments": {frag["fragmentId"]: frag for frag in reading["fragments"]},
            "fragmentsList": reading["fragments"],
        }
        self._store.save_material(
            session_id=session_id,
            doc_identity=doc_identity,
            material_id=material_id,
            file_name=file_name,
            raw_docx_bytes=content,
            reading=reading,
            view=view,
            catalog=cat_for_store,
        )
        return view

    def get_catalog(self, document_session_id: str) -> dict:
        cat = self.get_session_catalog(document_session_id)
        if cat is None:
            return {
                "totalDocuments": 0,
                "totalCharacters": 0,
                "documents": [],
                "toc": [],
            }
        return {
            "totalDocuments": cat["totalDocuments"],
            "totalCharacters": cat["totalCharacters"],
            "documents": list(cat["documents"]),
            "toc": list(cat["toc"]),
        }

    def get_session_catalog(self, document_session_id: str) -> Optional[dict]:
        cat = self._session_catalogs.get(document_session_id)
        if cat is not None:
            return cat
        loaded = self._store.load_session_catalog(document_session_id)
        if loaded is not None:
            self._session_catalogs[document_session_id] = loaded
            for frag in loaded.get("fragmentsList", []):
                mid = frag.get("materialId")
                if mid and mid not in self._materials:
                    mat_view = self._store.load_material_view(mid)
                    if mat_view:
                        self._materials[mid] = mat_view
            return loaded
        return None

    def view_material(self, material_id: str) -> dict:
        view = self._materials.get(material_id)
        if view is not None:
            return view
        loaded = self._store.load_material_view(material_id)
        if loaded is not None:
            self._materials[material_id] = loaded
            return loaded
        raise AdapterError(
            "MATERIAL_NOT_FOUND",
            "资料不存在或已过期，请重新导入。",
            status_code=404,
        )

    def read_complete_material(self, material_id: str, document_session_id: str) -> dict:
        """Re-read the retained local package, including legacy imports."""
        with self._import_lock:
            view = self.view_material(material_id)
            if view.get("documentSessionId") != document_session_id:
                raise AdapterError("MATERIAL_NOT_FOUND", "当前文档没有该资料。", status_code=404)
            if not re.fullmatch(r"mat_[a-f0-9]{16}", material_id):
                raise AdapterError("MATERIAL_NOT_FOUND", "资料编号无效。", status_code=404)
            directory = self._store._get_dir_for_session(document_session_id)
            path = directory / "files" / (material_id + ".docx") if directory else None
            if path is None or path.is_symlink() or not path.is_file():
                raise AdapterError("MATERIAL_NOT_FOUND", "资料原始副本缺失，请重新导入。", status_code=404)
            from app.services.word.material_document import extract_document
            return extract_document(path.read_bytes(), view.get("fileName", ""))

    def bind_document(self, request: dict) -> dict:
        with self._import_lock:
            payload = request or {}
            old_sid = str(payload.get("oldDocumentSessionId") or payload.get("old_document_session_id") or "").strip()
            new_sid = str(payload.get("newDocumentSessionId") or payload.get("new_document_session_id") or "").strip()
            new_ident = str(payload.get("newDocumentIdentity") or payload.get("new_document_identity") or "").strip()
            if not old_sid or not new_sid:
                raise AdapterError("REQUEST_VALIDATION_FAILED", "迁移需提供旧文档会话编号与新文档会话编号。", status_code=422)
            self._check_composer_busy(old_sid)
            self._check_composer_busy(new_sid)
            summary = self._store.bind_document(old_sid, new_sid, new_ident)
            if old_sid in self._session_catalogs:
                cat = self._session_catalogs.pop(old_sid)
                cat["documentSessionId"] = new_sid
                self._session_catalogs[new_sid] = cat
            for view in self._materials.values():
                if view.get("documentSessionId") == old_sid:
                    view["documentSessionId"] = new_sid
            return summary

    def update_material(self, material_id: str, request: dict) -> dict:
        with self._import_lock:
            return self._update_material(material_id, request)

    def _update_material(self, material_id: str, request: dict, converted_doc: bool = False) -> dict:
        old_view = self._materials.get(material_id)
        if old_view is None:
            old_view = self._store.load_material_view(material_id)
            if old_view is not None:
                self._materials[material_id] = old_view
        if old_view is None:
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或已过期，请重新导入。",
                status_code=404,
            )

        payload = request or {}
        req_session_id = str(payload.get("documentSessionId") or payload.get("document_session_id") or "").strip()
        mat_session_id = str(old_view.get("documentSessionId") or "").strip()
        if req_session_id and mat_session_id and req_session_id != mat_session_id:
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或不属于当前会话。",
                status_code=404,
            )
        session_id = req_session_id or mat_session_id
        self._check_composer_busy(session_id)
        doc_identity = str(
            payload.get("documentIdentity")
            or payload.get("document_identity")
            or ""
        ).strip()

        session_cat = self.get_session_catalog(session_id) if session_id else None
        if session_cat and not any(d.get("materialId") == material_id for d in session_cat.get("documents", [])):
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或不属于当前会话。",
                status_code=404,
            )

        file_name = str(payload.get("fileName") or payload.get("file_name") or old_view.get("fileName") or "")
        content = _decode_upload(payload.get("contentBase64") or payload.get("content_base64"))
        if file_name.lower().endswith(".doc") and not converted_doc:
            return self._stage_conversion(dict(payload, documentSessionId=session_id), content, material_id)
        if not converted_doc:
            _reject_wrong_type(file_name, str(payload.get("mimeType") or payload.get("mime_type") or ""))

        try:
            validated = validate_docx_bytes(content)
        except DocxSecurityError as exc:
            raise _security_error(exc) from exc

        current_cells = session_cat.get("totalTableCells", 0) if session_cat else 0
        old_cells = old_view.get("limits", {}).get("extractedTableCells", 0)
        remaining_cells = MATERIAL_IMPORT_MAX_TABLE_CELLS - (current_cells - old_cells)

        start_fragment_index = 1
        if session_cat:
            start_fragment_index = _next_fragment_index(session_cat)

        reading = _read_document(
            validated.document_xml,
            validated.style_names,
            content,
            remaining_table_cells=remaining_cells,
            start_fragment_index=start_fragment_index,
        )
        char_count = reading["limits"]["readableCharacterCount"]
        doc_cells = reading["limits"].get("extractedTableCells", 0)

        old_chars = old_view.get("limits", {}).get("readableCharacterCount", 0)
        if session_cat:
            current_chars = session_cat.get("totalCharacters", 0)
            new_total_chars = current_chars - old_chars + char_count
            if new_total_chars > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
                raise AdapterError(
                    "MATERIAL_TEXT_OVER_LIMIT",
                    "可读取文字超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )
            new_total_cells = current_cells - old_cells + doc_cells
            if new_total_cells > MATERIAL_IMPORT_MAX_TABLE_CELLS:
                raise AdapterError(
                    "MATERIAL_TABLE_OVER_LIMIT",
                    "表格展开规模超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )
        else:
            if char_count > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
                raise AdapterError(
                    "MATERIAL_TEXT_OVER_LIMIT",
                    "可读取文字超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )
            if doc_cells > MATERIAL_IMPORT_MAX_TABLE_CELLS:
                raise AdapterError(
                    "MATERIAL_TABLE_OVER_LIMIT",
                    "表格展开规模超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )

        now_iso = _updated_at(old_view.get("updatedAt") or old_view.get("importedAt") or "")

        for frag in reading["fragments"]:
            frag["fileName"] = file_name
            frag["materialId"] = material_id

        for block in reading["blocks"]:
            block["fileName"] = file_name
            block["materialId"] = material_id

        doc_summary = {
            "materialId": material_id,
            "fileName": file_name,
            "readableCharacterCount": char_count,
            "extractedTableCells": doc_cells,
            "blocksCount": len(reading["blocks"]),
            "fragmentsCount": len(reading["fragments"]),
            "fullReading": reading["fullReading"],
            "importedAt": old_view.get("importedAt") or now_iso,
            "updatedAt": now_iso,
        }

        doc_toc = []
        for block in reading["blocks"]:
            if block.get("kind") == "heading":
                doc_toc.append({
                    "materialId": material_id,
                    "fileName": file_name,
                    "headingLevel": block.get("level", 1),
                    "sectionTitle": block.get("text", ""),
                    "blockId": block.get("blockId", ""),
                })

        if session_cat:
            docs = []
            found = False
            for d in session_cat.get("documents", []):
                if d.get("materialId") == material_id:
                    docs.append(doc_summary)
                    found = True
                else:
                    docs.append(d)
            if not found:
                docs.append(doc_summary)
            session_cat["documents"] = docs
            session_cat["toc"] = [t for t in session_cat.get("toc", []) if t.get("materialId") != material_id] + doc_toc
            session_cat["blocks"] = [b for b in session_cat.get("blocks", []) if b.get("materialId") != material_id] + reading["blocks"]
            session_cat["fragmentsList"] = [f for f in session_cat.get("fragmentsList", []) if f.get("materialId") != material_id]
            session_cat["fragments"] = {k: v for k, v in session_cat.get("fragments", {}).items() if v.get("materialId") != material_id}
            for frag in reading["fragments"]:
                f_item = dict(frag)
                f_item["fileName"] = file_name
                session_cat["fragments"][frag["fragmentId"]] = f_item
                session_cat["fragmentsList"].append(f_item)
            session_cat["totalCharacters"] = sum(d.get("readableCharacterCount", 0) for d in session_cat["documents"])
            session_cat["totalTableCells"] = sum(d.get("extractedTableCells", 0) for d in session_cat["documents"])
            session_cat["totalDocuments"] = len(session_cat["documents"])
            catalog_summary = {
                "totalDocuments": session_cat["totalDocuments"],
                "totalCharacters": session_cat["totalCharacters"],
                "documents": list(session_cat["documents"]),
                "toc": list(session_cat["toc"]),
            }
        else:
            catalog_summary = {
                "totalDocuments": 1,
                "totalCharacters": char_count,
                "documents": [doc_summary],
                "toc": doc_toc,
            }

        view = {
            "materialId": material_id,
            "taskType": TASK_TYPE,
            "fileName": file_name,
            "documentSessionId": session_id,
            "sourceFileUnchanged": True,
            "targetDocumentUnchanged": True,
            "understandsAllContent": False,
            "fullReading": reading["fullReading"],
            "limits": reading["limits"],
            "disclosure": reading["disclosure"],
            "unreadRegions": reading["unreadRegions"],
            "blocks": reading["blocks"],
            "fragments": reading["fragments"],
            "importedAt": old_view.get("importedAt") or now_iso,
            "updatedAt": now_iso,
            "catalogSummary": catalog_summary,
        }
        self._materials[material_id] = view

        cat_for_store = session_cat if session_cat else {
            "documentSessionId": session_id,
            "totalDocuments": 1,
            "totalCharacters": char_count,
            "totalTableCells": doc_cells,
            "documents": [doc_summary],
            "toc": doc_toc,
            "blocks": reading["blocks"],
            "fragments": {frag["fragmentId"]: frag for frag in reading["fragments"]},
            "fragmentsList": reading["fragments"],
        }
        self._store.save_material(
            session_id=session_id,
            doc_identity=doc_identity,
            material_id=material_id,
            file_name=file_name,
            raw_docx_bytes=content,
            reading=reading,
            view=view,
            catalog=cat_for_store,
        )
        return view

    def delete_material(self, material_id: str, document_session_id: str = "") -> dict:
        with self._import_lock:
            return self._delete_material(material_id, document_session_id)

    def _delete_material(self, material_id: str, document_session_id: str = "") -> dict:
        mat = self._materials.get(material_id)
        if mat is None:
            mat = self._store.load_material_view(material_id)
        if mat is None:
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或已过期，请重新导入。",
                status_code=404,
            )

        req_session_id = document_session_id.strip() if document_session_id else ""
        mat_session_id = str(mat.get("documentSessionId") or "").strip()
        if req_session_id and mat_session_id and req_session_id != mat_session_id:
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或不属于当前会话。",
                status_code=404,
            )
        session_id = req_session_id or mat_session_id
        self._check_composer_busy(session_id)
        session_cat = self.get_session_catalog(session_id) if session_id else None

        if session_cat and not any(d.get("materialId") == material_id for d in session_cat.get("documents", [])):
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或不属于当前会话。",
                status_code=404,
            )

        self._materials.pop(material_id, None)

        if session_cat:
            session_cat["documents"] = [d for d in session_cat.get("documents", []) if d.get("materialId") != material_id]
            session_cat["toc"] = [t for t in session_cat.get("toc", []) if t.get("materialId") != material_id]
            session_cat["blocks"] = [b for b in session_cat.get("blocks", []) if b.get("materialId") != material_id]
            session_cat["fragmentsList"] = [f for f in session_cat.get("fragmentsList", []) if f.get("materialId") != material_id]
            session_cat["fragments"] = {k: v for k, v in session_cat.get("fragments", {}).items() if v.get("materialId") != material_id}
            session_cat["totalDocuments"] = len(session_cat["documents"])
            session_cat["totalCharacters"] = sum(d.get("readableCharacterCount", 0) for d in session_cat["documents"])
            session_cat["totalTableCells"] = sum(d.get("extractedTableCells", 0) for d in session_cat["documents"])

        self._store.delete_material(session_id, material_id, session_cat)

        if session_cat:
            return {
                "totalDocuments": session_cat["totalDocuments"],
                "totalCharacters": session_cat["totalCharacters"],
                "documents": list(session_cat["documents"]),
                "toc": list(session_cat["toc"]),
            }
        return {
            "totalDocuments": 0,
            "totalCharacters": 0,
            "documents": [],
            "toc": [],
        }


def _next_fragment_index(catalog: dict) -> int:
    return max(
        (int(fragment["fragmentId"].split("-")[-1])
         for fragment in catalog.get("fragmentsList", [])),
        default=0,
    ) + 1


def _updated_at(previous: str = "") -> str:
    now = datetime.now(timezone.utc)
    if previous:
        previous_time = datetime.fromisoformat(previous.replace("Z", "+00:00"))
        if now <= previous_time:
            now = previous_time + timedelta(microseconds=1)
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode_upload(value) -> bytes:
    encoded = str(value or "").strip()
    if not encoded:
        raise AdapterError("MATERIAL_FILE_TYPE_REJECTED", "未收到 DOCX 文件内容。", status_code=400)
    try:
        return base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise AdapterError(
            "MATERIAL_FILE_REJECTED",
            "文件内容无法读取，请重新选择有效 DOCX。",
            status_code=400,
        ) from exc


def _reject_wrong_type(file_name: str, mime_type: str) -> None:
    lowered_name = file_name.lower()
    lowered_mime = mime_type.lower()
    if lowered_name and not lowered_name.endswith(".docx"):
        raise AdapterError(
            "MATERIAL_FILE_TYPE_REJECTED",
            "只接受 DOCX 资料，当前文件类型不符。",
            status_code=400,
        )
    if not lowered_name and lowered_mime and "wordprocessingml" not in lowered_mime and lowered_mime not in {
        "application/octet-stream",
        "application/zip",
    }:
        raise AdapterError(
            "MATERIAL_FILE_TYPE_REJECTED",
            "只接受 DOCX 资料，当前文件类型不符。",
            status_code=400,
        )


def _security_error(exc: DocxSecurityError) -> AdapterError:
    message = str(exc)
    if "too large" in message or "budget" in message or "ratio" in message:
        return AdapterError(
            "MATERIAL_FILE_TOO_LARGE",
            "文件超过现有 DOCX 安全校验上限，已拒绝导入，未截断内容。",
            status_code=413,
        )
    return AdapterError(
        "MATERIAL_FILE_REJECTED",
        "文件未通过现有 DOCX 安全校验，已拒绝导入。",
        status_code=400,
    )


def _read_document(
    document_xml: bytes,
    style_names: Dict[str, str],
    package: bytes,
    remaining_table_cells: Optional[int] = None,
    start_fragment_index: int = 1,
) -> dict:
    root = ElementTree.fromstring(document_xml)
    body = _find_child(root, "body")
    blocks = []
    fragments = []
    table_index = 0
    readable_count = 0
    table_cells = 0
    max_allowed_cells = (
        MATERIAL_IMPORT_MAX_TABLE_CELLS
        if remaining_table_cells is None
        else remaining_table_cells
    )
    if body is not None:
        for child, body_path in _body_blocks(body):
            block_index = body_path[0]
            name = _local_name(child.tag)
            if name == "p":
                block, fragment, count = _paragraph_block(
                    child, style_names, block_index, start_fragment_index + len(fragments)
                )
                if block is None:
                    continue
                paragraph_fragments = (
                    _split_text_fragment(fragment, start_fragment_index + len(fragments))
                    if fragment is not None else []
                )
                _locate_block(block, paragraph_fragments, body_path)
                blocks.append(block)
                fragments.extend(paragraph_fragments)
                readable_count += count
            elif name == "tbl":
                block, table_fragments, count = _table_block(
                    child, block_index, table_index, start_fragment_index + len(fragments),
                    max_allowed_cells - table_cells,
                )
                table_index += 1
                if block is None:
                    continue
                table_cells += len(block["rows"]) * len(block["rows"][0])
                _locate_block(block, table_fragments, body_path)
                blocks.append(block)
                fragments.extend(table_fragments)
                readable_count += count
    from app.services.word.material_document import extract_document
    complete_reading = extract_document(package, "material.docx")
    readable_count = sum(len(b.get("text", "")) for b in complete_reading["blocks"])
    unread = _unread_regions(document_xml, package)
    return {
        "blocks": blocks,
        "fragments": fragments,
        "unreadRegions": unread,
        "fullReading": {
            "complete": complete_reading["complete"],
            "imageCount": len(complete_reading["images"]),
            "unreadObjects": complete_reading["unreadObjects"],
        },
        "disclosure": (
            "已提取文字、表格及支持的原图；图片由多模态模型识别，不保证辨认全部细节。"
            "完整读取状态和未读取对象见 fullReading，未读取对象不会静默略过。"
        ),
        "limits": {
            "parameterStatus": "implementation_parameter",
            "productConfirmed": False,
            "fileByteLimit": DOCX_MAX_PACKAGE_BYTES,
            "fileByteLimitSource": "existing_docx_security_gate",
            "tableColumnLimit": MATERIAL_IMPORT_MAX_TABLE_COLUMNS,
            "tableCellLimit": MATERIAL_IMPORT_MAX_TABLE_CELLS,
            "readableCharacterLimit": MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
            "characterCountMethod": CHARACTER_COUNT_METHOD,
            "readableCharacterCount": readable_count,
            "extractedTableCells": table_cells,
        },
    }


def _body_blocks(container, path=()):
    for index, child in enumerate(list(container)):
        child_path = path + (index,)
        name = _local_name(child.tag)
        if name in {"p", "tbl"}:
            yield child, child_path
        elif name in {"sdt", "sdtContent"}:
            yield from _body_blocks(child, child_path)


def _locate_block(block, fragments, body_path):
    block["blockId"] = "block-" + "-".join(str(index) for index in body_path)
    block["source"]["bodyPath"] = list(body_path)
    for fragment in fragments:
        fragment["blockId"] = block["blockId"]
        fragment["source"]["bodyPath"] = list(body_path)


def _split_text_fragment(fragment, start_number):
    text = fragment["text"]
    if len(text) <= _MAX_FRAGMENT_CHARACTERS:
        return [fragment]
    parts = []
    for offset in range(0, len(text), _MAX_FRAGMENT_CHARACTERS):
        part = dict(fragment)
        part["fragmentId"] = "frag-{0}".format(start_number + len(parts))
        part["text"] = text[offset:offset + _MAX_FRAGMENT_CHARACTERS]
        part["source"] = dict(fragment["source"], textOffset=offset)
        parts.append(part)
    return parts


def _paragraph_block(paragraph, style_names, block_index, fragment_number):
    text = _element_text(paragraph)
    if not text:
        return None, None, 0
    level = _heading_level(paragraph, style_names)
    source = {"part": _PART, "blockIndex": block_index}
    if level is not None:
        kind = "heading"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "level": level,
            "text": text,
            "source": source,
        }
    elif _has_child(paragraph, "numPr"):
        kind = "list_item"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "text": text,
            "source": source,
        }
    else:
        kind = "paragraph"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "text": text,
            "source": source,
        }
    fragment = {
        "fragmentId": "frag-{0}".format(fragment_number),
        "blockId": block["blockId"],
        "kind": kind,
        "text": text,
        "source": source,
    }
    return block, fragment, len(text)


def _table_block(table, block_index, table_index, fragment_start, cell_budget):
    rows = []
    fragments = []
    readable_count = 0
    fragment_number = fragment_start
    width = 0
    for row_index, row in enumerate(_children(table, "tr")):
        cells = []
        column_index = 0
        for cell in _children(row, "tc"):
            text = _cell_text(cell)
            span = _grid_span(cell)
            next_width = max(width, column_index + span)
            if (next_width > MATERIAL_IMPORT_MAX_TABLE_COLUMNS
                    or next_width * (row_index + 1) > cell_budget):
                raise AdapterError(
                    "MATERIAL_TABLE_OVER_LIMIT",
                    "表格展开规模超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                    status_code=413,
                )
            width = next_width
            cells.append(text)
            source = {
                "part": _PART,
                "blockIndex": block_index,
                "tableIndex": table_index,
                "row": row_index,
                "column": column_index,
            }
            cell_fragments = _split_text_fragment({
                "fragmentId": "frag-{0}".format(fragment_number),
                "blockId": "block-{0}".format(block_index),
                "kind": "table_cell",
                "text": text,
                "source": source,
            }, fragment_number)
            fragments.extend(cell_fragments)
            fragment_number += len(cell_fragments)
            readable_count += len(text)
            column_index += span
            if span > 1:
                cells.extend([""] * (span - 1))
        if width * (row_index + 1) > cell_budget:
            raise AdapterError(
                "MATERIAL_TABLE_OVER_LIMIT",
                "表格展开规模超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                status_code=413,
            )
        rows.append(cells)
    if not rows:
        return None, [], 0
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return (
        {
            "blockId": "block-{0}".format(block_index),
            "kind": "table",
            "rows": rows,
            "source": {
                "part": _PART,
                "blockIndex": block_index,
                "tableIndex": table_index,
            },
        },
        fragments,
        readable_count,
    )


def _heading_level(paragraph, style_names) -> Optional[int]:
    properties = _find_child(paragraph, "pPr")
    if properties is None:
        return None
    style = _find_child(properties, "pStyle")
    style_value = _attr(style, "val") if style is not None else ""
    style_name = (style_names or {}).get(style_value, "")
    match = _HEADING_NAME.match(re.sub(r"\s+", " ", str(style_name or style_value).strip()))
    if match is not None:
        return int(match.group(1))
    outline = _find_child(properties, "outlineLvl")
    if outline is None:
        return None
    try:
        level = int(_attr(outline, "val"))
    except (TypeError, ValueError):
        return None
    if 0 <= level <= 5:
        return level + 1
    return None


def _unread_regions(document_xml: bytes, package: bytes) -> List[dict]:
    root = ElementTree.fromstring(document_xml)
    image_count = 0
    for element in root.iter():
        if _local_name(element.tag) in {"drawing", "pict"}:
            image_count += 1
    embedded_count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
            for name in archive.namelist():
                lowered = name.lower()
                if "/embeddings/" in lowered or "oleobject" in lowered:
                    embedded_count += 1
    except zipfile.BadZipFile:
        embedded_count = 0
    regions = []
    if image_count:
        regions.append(
            {
                "kind": "image",
                "count": image_count,
                "message": "图片中的文字未读取。",
            }
        )
    if embedded_count:
        regions.append(
            {
                "kind": "embedded_attachment",
                "count": embedded_count,
                "message": "嵌入附件未读取。",
            }
        )
    return regions


def _cell_text(cell) -> str:
    parts = []
    for paragraph in cell.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        text = _element_text(paragraph)
        if text:
            parts.append(text)
    return " ".join(parts)


def _element_text(element) -> str:
    parts = []
    for node in element.iter():
        name = _local_name(node.tag)
        if name == "t" and node.text:
            parts.append(node.text)
        elif name in {"br", "cr"}:
            parts.append("\n")
        elif name == "tab":
            parts.append("\t")
    return "".join(parts)


def _grid_span(cell) -> int:
    properties = _find_child(cell, "tcPr")
    for node in list(properties) if properties is not None else []:
        if _local_name(node.tag) == "gridSpan":
            try:
                return max(1, int(_attr(node, "val")))
            except (TypeError, ValueError):
                return 1
    return 1


def _has_child(element, local_name: str) -> bool:
    return _find_descendant(element, local_name) is not None


def _find_child(element, local_name: str):
    if element is None:
        return None
    for child in list(element):
        if _local_name(child.tag) == local_name:
            return child
    return None


def _find_descendant(element, local_name: str):
    for node in element.iter():
        if _local_name(node.tag) == local_name:
            return node
    return None


def _children(element, local_name: str):
    return [child for child in list(element) if _local_name(child.tag) == local_name]


def _attr(element, local_name: str) -> str:
    if element is None:
        return ""
    for key, value in element.attrib.items():
        if _local_name(key) == local_name:
            return str(value or "")
    return ""


def _local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]
