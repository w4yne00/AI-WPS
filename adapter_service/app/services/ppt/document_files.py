import base64
import binascii
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.services.ppt.docx_security import (
    DOCX_COMPRESSION_RATIO_MIN_BYTES,
    DOCX_MAX_COMPRESSION_RATIO,
    DOCX_MAX_ENTRIES,
    DOCX_MAX_PACKAGE_BYTES,
    DOCX_MAX_RELATIONSHIPS,
    DOCX_MAX_REQUIRED_PART_BYTES,
    DOCX_MAX_UNCOMPRESSED_BYTES,
    DOCX_MAX_XML_ELEMENTS,
    DOCX_MAX_XML_PART_BYTES,
    DOCX_MAX_XML_DEPTH,
    DocxSecurityError,
    validate_docx_bytes,
)


PPT_DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
PPT_DOCUMENT_EXPIRES_SECONDS = 1800
PPT_DOCUMENT_MAX_BASE64_BYTES = ((PPT_DOCUMENT_MAX_BYTES + 2) // 3) * 4
PPT_DOCX_MAX_PACKAGE_BYTES = DOCX_MAX_PACKAGE_BYTES
PPT_DOCX_MAX_ENTRIES = DOCX_MAX_ENTRIES
PPT_DOCX_MAX_UNCOMPRESSED_BYTES = DOCX_MAX_UNCOMPRESSED_BYTES
PPT_DOCX_MAX_REQUIRED_PART_BYTES = DOCX_MAX_REQUIRED_PART_BYTES
PPT_DOCX_MAX_XML_PART_BYTES = DOCX_MAX_XML_PART_BYTES
PPT_DOCX_MAX_COMPRESSION_RATIO = DOCX_MAX_COMPRESSION_RATIO
PPT_DOCX_COMPRESSION_RATIO_MIN_BYTES = DOCX_COMPRESSION_RATIO_MIN_BYTES
PPT_DOCX_MAX_XML_ELEMENTS = DOCX_MAX_XML_ELEMENTS
PPT_DOCX_MAX_XML_DEPTH = DOCX_MAX_XML_DEPTH
PPT_DOCX_MAX_RELATIONSHIPS = DOCX_MAX_RELATIONSHIPS
ALLOWED_EXTENSIONS = {"md", "docx"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StagedPptDocument:
    token: str
    path: Path
    extension: str
    mime_type: str
    size_bytes: int
    expires_at: float


class PptDocumentFileStore:
    def __init__(
        self,
        root_dir: Optional[Path] = None,
        now=time.time,
        cleanup_interval_seconds: float = 0,
    ) -> None:
        self.root_dir = Path(
            root_dir
            or Path(tempfile.gettempdir()) / "ai-wps-adapter" / "ppt-document-files"
        )
        self.root_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.root_dir), 0o700)
        self._now = now
        self._items: Dict[str, StagedPptDocument] = {}
        self._owned: Dict[str, StagedPptDocument] = {}
        self._lock = threading.Lock()
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = None
        self._delete_restart_orphans()
        if cleanup_interval_seconds > 0:
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                args=(cleanup_interval_seconds,),
                daemon=True,
                name="ppt-document-cleanup",
            )
            self._cleanup_thread.start()

    def close(self) -> None:
        self._cleanup_stop.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1)
        with self._lock:
            staged_files = list(self._items.values()) + list(self._owned.values())
            self._items.clear()
            self._owned.clear()
        for staged in staged_files:
            self.delete(staged)

    def _cleanup_loop(self, interval_seconds: float) -> None:
        while not self._cleanup_stop.wait(interval_seconds):
            try:
                self.cleanup_expired()
            except OSError as exc:
                logger.warning("PPT document cleanup will retry after filesystem error: %s", exc)

    def store(
        self,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        content_base64: str,
    ) -> Dict:
        extension = Path(str(file_name or "")).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise AdapterError(
                "PPT_DOCUMENT_TYPE_UNSUPPORTED",
                "仅支持 Markdown（.md）和 Word（.docx）文档。",
                status_code=400,
            )

        declared_size = self._coerce_size(size_bytes)
        encoded_content = str(content_base64 or "")
        if declared_size < 1 or declared_size > PPT_DOCUMENT_MAX_BYTES:
            raise AdapterError(
                "PPT_DOCUMENT_TOO_LARGE",
                "文件大小必须在 1 字节至 10 MB 之间。",
                status_code=400,
            )
        if len(encoded_content) > PPT_DOCUMENT_MAX_BASE64_BYTES:
            raise AdapterError(
                "PPT_DOCUMENT_TOO_LARGE",
                "文件大小必须在 1 字节至 10 MB 之间。",
                status_code=400,
            )

        try:
            content = base64.b64decode(encoded_content, validate=True)
        except (binascii.Error, ValueError):
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "文件内容编码无效，请重新选择文件。",
                status_code=400,
            )

        if not content or len(content) > PPT_DOCUMENT_MAX_BYTES:
            raise AdapterError(
                "PPT_DOCUMENT_TOO_LARGE",
                "文件大小必须在 1 字节至 10 MB 之间。",
                status_code=400,
            )
        if declared_size != len(content):
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "文件大小校验失败，请重新选择文件。",
                status_code=400,
            )

        validation = self._validate_content(extension, content)
        self.cleanup_expired()

        token = "pptdoc_{0}".format(secrets.token_urlsafe(24))
        path = self.root_dir / "{0}.{1}".format(token, extension)
        path.write_bytes(content)
        os.chmod(str(path), 0o600)
        staged = StagedPptDocument(
            token=token,
            path=path,
            extension=extension,
            mime_type=str(mime_type or ""),
            size_bytes=len(content),
            expires_at=self._now() + PPT_DOCUMENT_EXPIRES_SECONDS,
        )
        with self._lock:
            self._items[token] = staged
        response = {
            "fileToken": token,
            "extension": extension,
            "sizeBytes": len(content),
            "expiresInSeconds": PPT_DOCUMENT_EXPIRES_SECONDS,
        }
        if validation is not None:
            response["styleCapability"] = validation.style_capability
        return response

    def consume(self, token: str) -> StagedPptDocument:
        self.cleanup_expired()
        with self._lock:
            staged = self._items.pop(str(token or ""), None)
        if staged is None or staged.expires_at <= self._now() or not staged.path.is_file():
            if staged is not None:
                self.delete(staged)
            raise AdapterError(
                "PPT_DOCUMENT_FILE_EXPIRED",
                "文档上传凭证已过期，请重新选择文件。",
                status_code=400,
            )
        return staged

    def claim(self, token: str, owner_id: str) -> StagedPptDocument:
        owner = str(owner_id or "").strip()
        if not owner:
            raise ValueError("owner_id is required")
        self.cleanup_expired()
        staged = None
        with self._lock:
            existing = self._owned.get(owner)
            if existing is not None:
                return existing
            staged = self._items.pop(str(token or ""), None)
            if (
                staged is not None
                and staged.expires_at > self._now()
                and staged.path.is_file()
            ):
                self._owned[owner] = staged
                return staged
        if staged is not None:
            self.delete(staged)
        raise AdapterError(
            "PPT_DOCUMENT_FILE_EXPIRED",
            "文档上传凭证已过期，请重新选择文件。",
            status_code=400,
        )

    def release(self, owner_id: str) -> None:
        with self._lock:
            staged = self._owned.pop(str(owner_id or "").strip(), None)
        if staged is not None:
            self.delete(staged)

    def delete(self, staged: StagedPptDocument) -> None:
        try:
            staged.path.unlink()
        except FileNotFoundError:
            pass

    def cleanup_expired(self) -> None:
        now = self._now()
        with self._lock:
            expired = [item for item in self._items.values() if item.expires_at <= now]
            for item in expired:
                self._items.pop(item.token, None)
            owned_paths = {item.path for item in self._owned.values()}
        for item in expired:
            self.delete(item)
        for path in self.root_dir.glob("pptdoc_*.*"):
            if path.suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
                continue
            if path in owned_paths:
                continue
            try:
                is_orphan_expired = now - path.stat().st_mtime >= PPT_DOCUMENT_EXPIRES_SECONDS
            except FileNotFoundError:
                continue
            if is_orphan_expired:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def _delete_restart_orphans(self) -> None:
        for path in self.root_dir.glob("pptdoc_*.*"):
            if path.suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _coerce_size(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _validate_content(extension: str, content: bytes):
        if extension == "md":
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise AdapterError(
                    "PPT_DOCUMENT_INVALID",
                    "Markdown 文件必须使用 UTF-8 编码。",
                    status_code=400,
                )
            return None

        try:
            return validate_docx_bytes(
                content,
                max_package_bytes=PPT_DOCX_MAX_PACKAGE_BYTES,
                max_entries=PPT_DOCX_MAX_ENTRIES,
                max_uncompressed_bytes=PPT_DOCX_MAX_UNCOMPRESSED_BYTES,
                max_required_part_bytes=PPT_DOCX_MAX_REQUIRED_PART_BYTES,
                max_xml_part_bytes=PPT_DOCX_MAX_XML_PART_BYTES,
                max_compression_ratio=PPT_DOCX_MAX_COMPRESSION_RATIO,
                compression_ratio_min_bytes=PPT_DOCX_COMPRESSION_RATIO_MIN_BYTES,
                max_xml_elements=PPT_DOCX_MAX_XML_ELEMENTS,
                max_xml_depth=PPT_DOCX_MAX_XML_DEPTH,
                max_relationships=PPT_DOCX_MAX_RELATIONSHIPS,
            )
        except DocxSecurityError:
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "Word 文档结构不安全、无效或文件已损坏。",
                status_code=400,
            )
