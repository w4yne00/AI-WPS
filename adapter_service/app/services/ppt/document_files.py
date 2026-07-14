import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Dict, Optional
import zipfile

from app.core.errors import AdapterError


PPT_DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
PPT_DOCUMENT_EXPIRES_SECONDS = 1800
ALLOWED_EXTENSIONS = {"md", "docx"}


@dataclass(frozen=True)
class StagedPptDocument:
    token: str
    path: Path
    extension: str
    mime_type: str
    size_bytes: int
    expires_at: float


class PptDocumentFileStore:
    def __init__(self, root_dir: Optional[Path] = None, now=time.time) -> None:
        self.root_dir = Path(
            root_dir
            or Path(tempfile.gettempdir()) / "ai-wps-adapter" / "ppt-document-files"
        )
        self.root_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.root_dir), 0o700)
        self._now = now
        self._items: Dict[str, StagedPptDocument] = {}
        self._lock = threading.Lock()
        self.cleanup_expired()

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

        try:
            content = base64.b64decode(str(content_base64 or ""), validate=True)
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
        if self._coerce_size(size_bytes) != len(content):
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "文件大小校验失败，请重新选择文件。",
                status_code=400,
            )

        self._validate_content(extension, content)
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
        return {
            "fileToken": token,
            "extension": extension,
            "sizeBytes": len(content),
            "expiresInSeconds": PPT_DOCUMENT_EXPIRES_SECONDS,
        }

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
        for item in expired:
            self.delete(item)
        for path in self.root_dir.glob("pptdoc_*.*"):
            if path.suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
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

    @staticmethod
    def _coerce_size(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _validate_content(extension: str, content: bytes) -> None:
        if extension == "md":
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise AdapterError(
                    "PPT_DOCUMENT_INVALID",
                    "Markdown 文件必须使用 UTF-8 编码。",
                    status_code=400,
                )
            return

        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except (zipfile.BadZipFile, OSError):
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "Word 文档格式无效或文件已损坏。",
                status_code=400,
            )
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise AdapterError(
                "PPT_DOCUMENT_INVALID",
                "Word 文档缺少必要结构。",
                status_code=400,
            )
