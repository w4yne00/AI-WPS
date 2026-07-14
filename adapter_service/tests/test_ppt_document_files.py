import base64
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from app.core.errors import AdapterError
from app.core.models import (
    PptDocumentFileUploadRequest,
    PptSlideAssistantRequest,
    PptSlideAssistantResponseData,
)
from app.services.ppt.document_files import (
    PPT_DOCUMENT_EXPIRES_SECONDS,
    PPT_DOCUMENT_MAX_BYTES,
    PptDocumentFileStore,
)


def parse_model(model_class, payload):
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(payload)
    return model_class.parse_obj(payload)


def build_docx(*names):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in names:
            archive.writestr(name, "<xml />")
    return output.getvalue()


class PptDocumentModelTests(unittest.TestCase):
    def test_document_request_accepts_token_and_allowed_slide_count(self):
        request = parse_model(
            PptSlideAssistantRequest,
            {
                "sourceMode": "document",
                "fileToken": "pptdoc_1234567890abcdef",
                "requestedSlideCount": 10,
                "userInstruction": "面向管理层，突出风险。",
                "clientJobId": "client-ppt-document-1234",
            },
        )

        self.assertEqual(request.source_mode, "document")
        self.assertIsNone(request.slide)
        self.assertEqual(request.file_token, "pptdoc_1234567890abcdef")
        self.assertEqual(request.requested_slide_count, 10)

    def test_document_request_defaults_unknown_slide_count_to_ten(self):
        for value in (0, 6, 20, "invalid", None):
            with self.subTest(value=value):
                request = parse_model(
                    PptSlideAssistantRequest,
                    {"sourceMode": "document", "requestedSlideCount": value},
                )
                self.assertEqual(request.requested_slide_count, 10)

    def test_document_request_accepts_every_supported_slide_count(self):
        for value in (5, 8, 10, 12, 15):
            with self.subTest(value=value):
                request = parse_model(
                    PptSlideAssistantRequest,
                    {"sourceMode": "document", "requestedSlideCount": str(value)},
                )
                self.assertEqual(request.requested_slide_count, value)

    def test_upload_and_document_result_models_accept_frontend_aliases(self):
        upload = parse_model(
            PptDocumentFileUploadRequest,
            {
                "fileName": "source.md",
                "mimeType": "text/markdown",
                "sizeBytes": "4",
                "contentBase64": "dGVzdA==",
            },
        )
        result = parse_model(
            PptSlideAssistantResponseData,
            {
                "resultType": "document",
                "deckTitle": "项目汇报",
                "documentSummary": "项目按计划推进。",
                "recommendedSlideCount": 5,
                "slides": [
                    {
                        "index": 1,
                        "role": "封面",
                        "title": "项目汇报",
                        "layoutSuggestion": "居中布局",
                        "visualSuggestion": "使用项目主视觉",
                    }
                ],
                "globalStyleAdvice": "保持简洁。",
            },
        )

        self.assertEqual(upload.file_name, "source.md")
        self.assertEqual(upload.size_bytes, 4)
        self.assertEqual(result.result_type, "document")
        self.assertIsNone(result.mode_used)
        self.assertEqual(result.slides[0].layout_suggestion, "居中布局")


class PptDocumentFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "ppt-document-files"
        self.clock = [100.0]
        self.store = PptDocumentFileStore(root_dir=self.root, now=lambda: self.clock[0])

    def tearDown(self):
        self.temp_dir.cleanup()

    def _store(self, file_name, content, mime_type=""):
        return self.store.store(
            file_name,
            mime_type,
            len(content),
            base64.b64encode(content).decode("ascii"),
        )

    def assert_store_error(self, code, file_name, content, size_bytes=None, content_base64=None):
        with self.assertRaises(AdapterError) as error:
            self.store.store(
                file_name,
                "application/octet-stream",
                len(content) if size_bytes is None else size_bytes,
                base64.b64encode(content).decode("ascii")
                if content_base64 is None
                else content_base64,
            )
        self.assertEqual(error.exception.code, code)

    def test_store_validates_markdown_and_consumes_token_once(self):
        content = "# 项目报告\n".encode("utf-8")
        staged_payload = self._store("项目报告.md", content, "text/markdown")

        consumed = self.store.consume(staged_payload["fileToken"])

        self.assertEqual(consumed.extension, "md")
        self.assertEqual(consumed.size_bytes, len(content))
        self.assertTrue(consumed.path.is_file())
        with self.assertRaises(AdapterError) as error:
            self.store.consume(staged_payload["fileToken"])
        self.assertEqual(error.exception.code, "PPT_DOCUMENT_FILE_EXPIRED")

    def test_store_accepts_utf8_bom_markdown(self):
        staged_payload = self._store("source.md", b"\xef\xbb\xbf# Report\n")

        staged = self.store.consume(staged_payload["fileToken"])

        self.assertEqual(staged.extension, "md")

    def test_store_rejects_unsupported_extension(self):
        self.assert_store_error("PPT_DOCUMENT_TYPE_UNSUPPORTED", "source.pdf", b"PDF")

    def test_store_rejects_malformed_base64(self):
        self.assert_store_error(
            "PPT_DOCUMENT_INVALID",
            "source.md",
            b"ignored",
            size_bytes=7,
            content_base64="not-valid-base64!",
        )

    def test_store_rejects_decoded_size_mismatch(self):
        self.assert_store_error(
            "PPT_DOCUMENT_INVALID",
            "source.md",
            b"content",
            size_bytes=99,
        )

    def test_store_rejects_zero_bytes(self):
        self.assert_store_error("PPT_DOCUMENT_TOO_LARGE", "source.md", b"")

    def test_store_rejects_more_than_ten_megabytes(self):
        content = b"x" * (PPT_DOCUMENT_MAX_BYTES + 1)
        self.assert_store_error("PPT_DOCUMENT_TOO_LARGE", "source.md", content)

    def test_store_rejects_non_utf8_markdown(self):
        self.assert_store_error("PPT_DOCUMENT_INVALID", "source.md", b"\xff\xfe\x00")

    def test_store_rejects_docx_missing_required_parts(self):
        for names in (
            ("word/document.xml",),
            ("[Content_Types].xml",),
        ):
            with self.subTest(names=names):
                self.assert_store_error(
                    "PPT_DOCUMENT_INVALID",
                    "source.docx",
                    build_docx(*names),
                )

    def test_store_accepts_minimal_structurally_valid_docx(self):
        content = build_docx("[Content_Types].xml", "word/document.xml")

        staged_payload = self._store(
            "source.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        staged = self.store.consume(staged_payload["fileToken"])

        self.assertEqual(staged.extension, "docx")
        self.assertEqual(staged.size_bytes, len(content))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions are required")
    def test_store_uses_private_directory_and_file_permissions(self):
        staged_payload = self._store("source.md", b"private")
        staged = self.store.consume(staged_payload["fileToken"])

        root_mode = stat.S_IMODE(self.root.stat().st_mode)
        file_mode = stat.S_IMODE(staged.path.stat().st_mode)

        self.assertEqual(root_mode, 0o700)
        self.assertEqual(file_mode, 0o600)

    def test_token_expires_and_cleanup_removes_file(self):
        staged_payload = self._store("source.md", b"expires")
        token = staged_payload["fileToken"]
        staged_path = self.root / "{0}.md".format(token)
        self.assertTrue(staged_path.is_file())

        self.clock[0] += PPT_DOCUMENT_EXPIRES_SECONDS
        self.store.cleanup_expired()

        self.assertFalse(staged_path.exists())
        with self.assertRaises(AdapterError) as error:
            self.store.consume(token)
        self.assertEqual(error.exception.code, "PPT_DOCUMENT_FILE_EXPIRED")

    def test_new_store_removes_expired_orphan_left_by_previous_process(self):
        orphan = self.root / "pptdoc_orphan.md"
        orphan.write_bytes(b"expired")
        os.utime(str(orphan), (0, 0))

        PptDocumentFileStore(
            root_dir=self.root,
            now=lambda: PPT_DOCUMENT_EXPIRES_SECONDS + 1,
        )

        self.assertFalse(orphan.exists())

    def test_delete_is_idempotent_and_removes_staged_path(self):
        staged_payload = self._store("source.md", b"delete me")
        staged = self.store.consume(staged_payload["fileToken"])

        self.store.delete(staged)
        self.store.delete(staged)

        self.assertFalse(staged.path.exists())


if __name__ == "__main__":
    unittest.main()
