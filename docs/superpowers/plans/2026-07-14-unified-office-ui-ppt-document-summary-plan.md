# Unified Office UI and PPT Document Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `v0.18.0-alpha` with a unified Word/Excel/PPT task-pane design, renamed Excel/PPT user-facing entries, secure PPT Markdown/DOCX document summarization, prompt templates, and one combined upgrade package.

**Architecture:** Keep the three WPS add-ins isolated and keep Word/Excel behavior unchanged. Extend the existing `ppt.slide_assistant` request and job pipeline with a discriminated `sourceMode`, stage one validated file behind a one-time token, upload it to Dify with the active PPT workflow key, then reuse the existing `/chat-messages` compatibility fallback and long-polling job endpoint. All PPT results remain preview/copy only.

**Tech Stack:** Python 3.8 standard library, FastAPI, Pydantic v1/v2-compatible models, `urllib`, WPS JavaScript API, ES5-compatible browser JavaScript, HTML/CSS, Node.js assertion tests, Bash packaging.

---

## File Map

**Create**

- `adapter_service/app/services/ppt/document_files.py`: validate, stage, consume, expire, and securely delete one-time PPT source files.
- `adapter_service/tests/test_ppt_document_files.py`: unit tests for Base64, size, UTF-8 Markdown, DOCX ZIP structure, permissions, token consumption, and expiry.
- `docs/prompt-templates/excel-smart-analysis-prompt-template.md`: deployable Excel analysis prompt engineering template.
- `docs/prompt-templates/ppt-smart-summary-prompt-template.md`: deployable dual-mode PPT summary prompt engineering template.

**Modify**

- `adapter_service/app/core/models.py`: discriminated PPT request, file upload models, and slide/document result models.
- `adapter_service/app/api/ppt.py`: file-upload route and dual-result job serialization.
- `adapter_service/app/services/provider_client.py`: Dify multipart upload, auth snapshot reuse, files-aware compatibility payload, document prompt/parser/provider method.
- `adapter_service/app/services/ppt/slide_assistant.py`: dispatch slide and document modes while preserving current slide normalization.
- `adapter_service/app/services/ppt/slide_assistant_jobs.py`: stage-aware running messages without changing idempotency or the 1800-second budget.
- `adapter_service/standalone_adapter.py`: standalone equivalents for the new upload route and dual-result serialization.
- `adapter_service/tests/test_enterprise_provider.py`: payload, multipart, parser, think-filter, and auth reuse coverage.
- `adapter_service/tests/test_ppt_slide_assistant.py`: dual-mode service, jobs, FastAPI, standalone, cleanup, and idempotency coverage.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`: file validation and document result formatting helpers.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`: “智能总结” segmented UI, connection badge, file controls, and shared results.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`: upload, submit, recoverable polling, document rendering, and copy actions.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`: unified visual system and PPT document result layout.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.xml`: rename the PPT entry to “智能总结”.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js`: keep the PPT icon mapping and update build cache key.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`: visual-only adoption of the unified design tokens.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`: visual-only adoption of the unified design tokens.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`: rename user-visible Excel title and labels to “智能分析”.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`: rename user-visible status/profile text only.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`: rename the Excel entry to “智能分析”.
- `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`: PPT document helper tests.
- `formal-plugin-kit/tests/layout-smoke.test.js`: host isolation, labels, unified visual contract, read-only protection, route, and version assertions.
- `adapter_service/tests/test_packaging_scripts.py`: prompt-template and three-host package assertions.
- `packaging/build_phase1_delivery_kit.sh`: copy both prompt templates into the package.
- `docs/operations/dify-ppt-slide-assistant-workflow.md`: document upload/extraction and dual-mode workflow setup.
- `docs/operations/dify-excel-analysis-workflow.md`: current user-facing “智能分析” terminology.
- `docs/operations/workflow-profile-management.md`: current Excel/PPT names and shared PPT workflow behavior.
- `README.md`, `README-ZH.md`, `docs/codex-handoff.md`: release state, interfaces, protection boundaries, validation, and package checksum.
- `phase1-delivery-kit/README.md`, `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`, `phase1-delivery-kit/docs/phase1-acceptance-record.md`: delivery contents and target-machine acceptance.
- `adapter-start-kit/scripts/start_uvicorn_adapter.sh`, adapter diagnostics, three manifests/index/taskpane/ribbon cache keys: `0.18.0-alpha` version alignment.

## Protected Contracts

- Do not change Word request bodies, task routes, long polling, structured preview, comparison highlighting, or writeback functions.
- Do not change Excel extraction, `clientJobId` recovery, `/excel/analysis/jobs`, or read-only behavior; only labels and CSS may change.
- Do not change current-slide PPT extraction, title/subtitle separation, generate/optimize mode rules, 1800-second provider timeout, or idempotent job semantics.
- Do not add any PPT object, shape, text, layout, notes, or slide write API.
- Preserve Dify legacy/user-input HTTP 400 fallback and think-tag removal for every task.
- Preserve workflow-profile key precedence and ensure one PPT document job uses the same resolved key for `/files/upload` and `/chat-messages`.
- Preserve upgrade protection for `config/adapter.json`, `run/provider_api_key`, and `run/provider_api_keys/`.
- Never stage or rewrite unrelated historical archives currently visible in `git status`.

### Task 1: Add Secure One-Time PPT Document Staging

**Files:**
- Create: `adapter_service/app/services/ppt/document_files.py`
- Create: `adapter_service/tests/test_ppt_document_files.py`
- Modify: `adapter_service/app/core/models.py:288-344`

- [ ] **Step 1: Write failing model and file-store tests**

Add tests that construct these exact payloads and assert aliases work in both Pydantic v1 and v2:

```python
def test_document_request_accepts_token_and_allowed_slide_count(self):
    request = parse_ppt_request({
        "sourceMode": "document",
        "fileToken": "pptdoc_1234567890abcdef",
        "requestedSlideCount": 10,
        "userInstruction": "面向管理层，突出风险。",
        "clientJobId": "client-ppt-document-1234",
    })
    self.assertEqual(request.source_mode, "document")
    self.assertIsNone(request.slide)
    self.assertEqual(request.requested_slide_count, 10)

def test_store_validates_markdown_and_consumes_token_once(self):
    store = PptDocumentFileStore(root_dir=self.root, now=lambda: 100.0)
    content = "# 项目报告\n".encode("utf-8")
    payload = base64.b64encode(content).decode("ascii")
    staged = store.store("项目报告.md", "text/markdown", len(content), payload)
    consumed = store.consume(staged["fileToken"])
    self.assertEqual(consumed.extension, "md")
    with self.assertRaises(AdapterError) as error:
        store.consume(staged["fileToken"])
    self.assertEqual(error.exception.code, "PPT_DOCUMENT_FILE_EXPIRED")
```

Cover these additional exact cases in `test_ppt_document_files.py`:

- unsupported `.pdf` -> `PPT_DOCUMENT_TYPE_UNSUPPORTED`;
- malformed Base64 -> `PPT_DOCUMENT_INVALID`;
- decoded size mismatch, zero bytes, and `10 * 1024 * 1024 + 1` bytes -> `PPT_DOCUMENT_TOO_LARGE` or `PPT_DOCUMENT_INVALID`;
- invalid UTF-8 Markdown -> `PPT_DOCUMENT_INVALID`;
- DOCX ZIP without `[Content_Types].xml` or `word/document.xml` -> `PPT_DOCUMENT_INVALID`;
- valid minimal DOCX -> accepted;
- root mode `0700`, staged file mode `0600` on POSIX;
- token expires after 1800 seconds and cleanup removes the file;
- `delete(staged)` is idempotent and removes the path.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_ppt_document_files adapter_service.tests.test_ppt_slide_assistant -v
```

Expected: FAIL because `PptDocumentFileStore`, `sourceMode`, `fileToken`, and `requestedSlideCount` do not exist.

- [ ] **Step 3: Add discriminated request and upload/result models**

Add the following model shapes to `adapter_service/app/core/models.py`, retaining `PptSlideInput` unchanged:

```python
class PptDocumentFileUploadRequest(BaseModel):
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(default="", alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    content_base64: str = Field(alias="contentBase64")


class PptDocumentSlide(BaseModel):
    index: int
    role: str = ""
    title: str = ""
    subtitle: str = ""
    bullets: List[str] = Field(default_factory=list)
    conclusion: str = ""
    layout_suggestion: str = Field(default="", alias="layoutSuggestion")
    visual_suggestion: str = Field(default="", alias="visualSuggestion")


class PptSlideAssistantRequest(BaseModel):
    presentation_id: str = Field(default="active-presentation", alias="presentationId")
    scene: Literal["ppt"] = "ppt"
    source_mode: Literal["slide", "document"] = Field(default="slide", alias="sourceMode")
    client_job_id: str = Field(default="", alias="clientJobId")
    slide: Optional[PptSlideInput] = None
    file_token: str = Field(default="", alias="fileToken")
    requested_slide_count: int = Field(default=10, alias="requestedSlideCount")
    user_instruction: str = Field(default="", alias="userInstruction")


class PptSlideAssistantResponseData(BaseModel):
    result_type: Literal["slide", "document"] = Field(default="slide", alias="resultType")
    mode_used: Optional[Literal["generate", "optimize"]] = Field(default=None, alias="modeUsed")
    suggested_title: str = Field(default="", alias="suggestedTitle")
    bullets: List[str] = Field(default_factory=list)
    conclusion: str = ""
    deck_title: str = Field(default="", alias="deckTitle")
    document_summary: str = Field(default="", alias="documentSummary")
    recommended_slide_count: Optional[int] = Field(default=None, alias="recommendedSlideCount")
    slides: List[PptDocumentSlide] = Field(default_factory=list)
    global_style_advice: str = Field(default="", alias="globalStyleAdvice")
    plain_text: str = Field(default="", alias="plainText")
    raw_answer: Optional[str] = Field(default=None, alias="rawAnswer")
    parse_fallback_reason: Optional[str] = Field(default=None, alias="parseFallbackReason")
    provider: str = "mock"
```

Validators must coerce strings, keep only slide counts in `{5, 8, 10, 12, 15}`, default to 10, and preserve `slide=None` for document mode.

- [ ] **Step 4: Implement the secure store using only the standard library**

Implement the store in `document_files.py` with this structure:

```python
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
        self.root_dir = Path(root_dir or Path(tempfile.gettempdir()) / "ai-wps-adapter" / "ppt-document-files")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.root_dir), 0o700)
        self._now = now
        self._items: Dict[str, StagedPptDocument] = {}
        self._lock = threading.Lock()

    def store(self, file_name: str, mime_type: str, size_bytes: int, content_base64: str) -> Dict:
        extension = Path(str(file_name or "")).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise AdapterError("PPT_DOCUMENT_TYPE_UNSUPPORTED", "仅支持 Markdown（.md）和 Word（.docx）文档。", status_code=400)
        try:
            content = base64.b64decode(str(content_base64 or ""), validate=True)
        except (binascii.Error, ValueError):
            raise AdapterError("PPT_DOCUMENT_INVALID", "文件内容编码无效，请重新选择文件。", status_code=400)
        if not content or len(content) > PPT_DOCUMENT_MAX_BYTES:
            raise AdapterError("PPT_DOCUMENT_TOO_LARGE", "文件大小必须在 1 字节至 10 MB 之间。", status_code=400)
        if int(size_bytes or 0) != len(content):
            raise AdapterError("PPT_DOCUMENT_INVALID", "文件大小校验失败，请重新选择文件。", status_code=400)
        if extension == "md":
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise AdapterError("PPT_DOCUMENT_INVALID", "Markdown 文件必须使用 UTF-8 编码。", status_code=400)
        else:
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    names = set(archive.namelist())
            except (zipfile.BadZipFile, OSError):
                raise AdapterError("PPT_DOCUMENT_INVALID", "Word 文档格式无效或文件已损坏。", status_code=400)
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise AdapterError("PPT_DOCUMENT_INVALID", "Word 文档缺少必要结构。", status_code=400)
        self.cleanup_expired()
        token = "pptdoc_{0}".format(secrets.token_urlsafe(24))
        path = self.root_dir / "{0}.{1}".format(token, extension)
        path.write_bytes(content)
        os.chmod(str(path), 0o600)
        staged = StagedPptDocument(token, path, extension, str(mime_type or ""), len(content), self._now() + PPT_DOCUMENT_EXPIRES_SECONDS)
        with self._lock:
            self._items[token] = staged
        return {"fileToken": token, "extension": extension, "sizeBytes": len(content), "expiresInSeconds": PPT_DOCUMENT_EXPIRES_SECONDS}

    def consume(self, token: str) -> StagedPptDocument:
        self.cleanup_expired()
        with self._lock:
            staged = self._items.pop(str(token or ""), None)
        if staged is None or staged.expires_at <= self._now() or not staged.path.is_file():
            if staged is not None:
                self.delete(staged)
            raise AdapterError("PPT_DOCUMENT_FILE_EXPIRED", "文档上传凭证已过期，请重新选择文件。", status_code=400)
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
```

Use `base64.b64decode(content_base64, validate=True)`, `zipfile.ZipFile(BytesIO(content))`, `secrets.token_urlsafe(24)`, `tempfile.gettempdir()`, `Path.write_bytes`, `os.chmod(root, 0o700)`, and `os.chmod(path, 0o600)`. Store only token metadata in memory. Never log `file_name`, `content_base64`, or content. Return:

```python
{
    "fileToken": token,
    "extension": extension,
    "sizeBytes": len(content),
    "expiresInSeconds": PPT_DOCUMENT_EXPIRES_SECONDS,
}
```

- [ ] **Step 5: Run focused tests and commit**

Run the command from Step 2. Expected: all file-store tests PASS and existing slide tests PASS.

```bash
git add adapter_service/app/core/models.py adapter_service/app/services/ppt/document_files.py adapter_service/tests/test_ppt_document_files.py adapter_service/tests/test_ppt_slide_assistant.py
git commit -m "feat: add secure PPT document staging"
```

### Task 2: Upload PPT Documents to Dify with the Same Workflow Key

**Files:**
- Modify: `adapter_service/app/services/provider_client.py:260-301,356-382,1162-1280,1458-1487`
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Write failing provider payload, multipart, parser, and auth tests**

Add assertions for both Dify input modes:

```python
files = [{
    "type": "document",
    "transfer_method": "local_file",
    "upload_file_id": "file-dify-123",
}]
legacy = build_provider_request_payload(settings, {}, "总结文档", "legacy", files=files)
modern = build_provider_request_payload(settings, {}, "总结文档", "user-input", files=files)
self.assertEqual(legacy["inputs"], {"query": "总结文档"})
self.assertEqual(modern["inputs"], {})
self.assertEqual(legacy["files"], files)
self.assertEqual(modern["files"], files)
```

Mock `urllib_request.urlopen` and assert `/files/upload` receives:

- `Authorization: Bearer <the active ppt.slide_assistant profile key>`;
- multipart fields `user=wps-ai-assistant` and file name `source.md`;
- no original filename in URL, headers, debug metadata, or logger message;
- returned `id` becomes `upload_file_id` in both compatibility attempts;
- upload and chat use exactly one `resolve_task_auth("ppt.slide_assistant")` snapshot even if profile selection changes during the test.

Add parser coverage with this payload:

```python
answer = '<think>internal reasoning</think>\n' + json.dumps({
    "deckTitle": "项目进展汇报",
    "documentSummary": "项目总体按计划推进。",
    "recommendedSlideCount": 5,
    "slides": [{
        "index": 1,
        "role": "封面",
        "title": "项目进展汇报",
        "subtitle": "阶段成果与下一步安排",
        "bullets": [],
        "conclusion": "",
        "layoutSuggestion": "居中标题",
        "visualSuggestion": "使用项目主视觉",
    }],
    "globalStyleAdvice": "使用宋体和雾蓝色强调。",
    "plainText": "项目进展汇报",
}, ensure_ascii=False)
result = parse_ppt_document_answer(answer, requested_slide_count=5)
self.assertEqual(result["resultType"], "document")
self.assertNotIn("internal reasoning", result["plainText"])
self.assertEqual(result["slides"][0]["subtitle"], "阶段成果与下一步安排")
```

Also assert non-JSON Markdown is preserved in `rawAnswer` with `parseFallbackReason`.

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: FAIL because payload builders reject `files` and no document upload/parser method exists.

- [ ] **Step 3: Make chat payload builders files-aware without changing default behavior**

Change both builders to copy a caller-supplied list and default to the existing empty list:

```python
def build_provider_request_payload(settings, input_data, query, input_mode=DIFY_INPUT_MODE_LEGACY, files=None):
    inputs = {"query": query} if input_mode == DIFY_INPUT_MODE_LEGACY else {}
    return {
        "inputs": inputs,
        "query": query,
        "conversation_id": "",
        "response_mode": settings.provider_mode,
        "user": "wps-ai-assistant",
        "files": list(files or []),
    }
```

Add optional `files=None` and `task_auth=None` parameters to `post_task`. Resolve a task auth snapshot once when absent:

```python
def resolve_task_auth(self, task_type: str) -> Dict:
    self.refresh_settings()
    profile = self.get_active_workflow_profile(task_type)
    key_ref = str(profile.get("apiKeyRef", "")) if profile else self.get_task_api_key_ref(task_type)
    return {
        "workflowProfile": profile,
        "apiKeyRef": key_ref,
        "apiKey": load_route_api_key(key_ref) or self.get_api_key("default"),
    }
```

Pass `files` unchanged to every legacy/user-input retry. Keep the existing compatibility cache key, response parsing, timeout handling, and debug redaction.

- [ ] **Step 4: Implement standard-library multipart upload**

Add a pure encoder and provider method:

```python
def encode_dify_file_upload(content: bytes, extension: str, mime_type: str) -> Tuple[bytes, str]:
    boundary = "----ai-wps-{0}".format(uuid.uuid4().hex)
    chunks = [
        "--{0}\r\nContent-Disposition: form-data; name=\"user\"\r\n\r\nwps-ai-assistant\r\n".format(boundary).encode("utf-8"),
        ("--{0}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"source.{1}\"\r\n"
         "Content-Type: {2}\r\n\r\n").format(boundary, extension, mime_type).encode("utf-8"),
        content,
        "\r\n--{0}--\r\n".format(boundary).encode("ascii"),
    ]
    return b"".join(chunks), "multipart/form-data; boundary={0}".format(boundary)
```

`upload_task_file` must call `providerBaseUrl + "/files/upload"`, use the supplied auth snapshot, parse JSON field `id`, and map 400/auth/timeout/unreachable errors through existing provider error classes. Debug metadata may include only `taskType`, `extension`, `sizeBytes`, stage, status, and redacted error.

- [ ] **Step 5: Add the document prompt, parser, and provider method**

The prompt must state:

```text
你是企业汇报材料智能总结助手。模型后台已收到一份文档附件。
请根据附件内容生成整套 PPT 方案，不得声称已经创建或修改幻灯片。
建议页数：{requested_slide_count}
用户补充要求：{instruction_or_none}
只返回 JSON 对象，字段固定为 deckTitle、documentSummary、recommendedSlideCount、slides、globalStyleAdvice、plainText。
slides 每项固定包含 index、role、title、subtitle、bullets、conclusion、layoutSuggestion、visualSuggestion。
subtitle 和 conclusion 可为空；bullets 每页 2 至 5 条；不得编造附件中不存在的事实和数据；不得输出深度思考过程。
```

Implement `parse_ppt_document_answer(answer, requested_slide_count)` with `strip_think_tag_content` and `_extract_json_payload`. Normalize slide indexes, strings, bullet lists, and allowed slide count. For fallback return:

```python
{
    "resultType": "document",
    "deckTitle": "",
    "documentSummary": "模型后台已返回结果，但未按结构化 JSON 输出。",
    "recommendedSlideCount": requested_slide_count,
    "slides": [],
    "globalStyleAdvice": "",
    "plainText": cleaned,
    "rawAnswer": cleaned,
    "parseFallbackReason": "模型后台未返回可解析的 PPT 文档总结 JSON。",
}
```

`ppt_document_summary` must resolve auth once, upload the staged file, construct one Dify document reference, and call `post_task` with the same snapshot:

```python
body = self.post_task(
    task_type,
    trace_id,
    {"scene": "ppt", "sourceMode": "document", "requestedSlideCount": requested_slide_count},
    prompt,
    timeout_seconds=max(self.settings.timeout_seconds, PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS),
    files=files,
    task_auth=task_auth,
)
return parse_ppt_document_answer(extract_answer(body), requested_slide_count)
```

- [ ] **Step 6: Run tests and commit**

Run the command from Step 2. Expected: all provider tests PASS, including old empty-files behavior.

```bash
git add adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_provider.py
git commit -m "feat: upload PPT summary documents to model backend"
```

### Task 3: Extend PPT Jobs and Both Adapter Entrypoints

**Files:**
- Modify: `adapter_service/app/services/ppt/slide_assistant.py`
- Modify: `adapter_service/app/services/ppt/slide_assistant_jobs.py`
- Modify: `adapter_service/app/api/ppt.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/tests/test_ppt_slide_assistant.py`
- Modify: `adapter_service/tests/test_packaging_scripts.py`

- [ ] **Step 1: Write failing dual-mode service and route tests**

Add a recording document provider and assert:

```python
request = parse_ppt_request({
    "sourceMode": "document",
    "fileToken": staged["fileToken"],
    "requestedSlideCount": 10,
    "userInstruction": "突出风险与计划",
    "clientJobId": "client-ppt-document-route",
})
result = assistant.assist(request, "trace-document", progress_callback=messages.append)
self.assertEqual(result["resultType"], "document")
self.assertEqual(provider.calls[0]["requestedSlideCount"], 10)
self.assertFalse(Path(provider.calls[0]["path"]).exists())
self.assertIn("正在上传模型后台", messages)
```

Add exact failure assertions:

- slide mode without slide -> `PPT_SLIDE_REQUIRED`;
- document mode without token -> `PPT_DOCUMENT_FILE_REQUIRED`;
- invalid slide count -> normalized to 10;
- expired token -> `PPT_DOCUMENT_FILE_EXPIRED`;
- provider failure -> staged path removed and job status `failed`;
- duplicate `clientJobId` -> provider called once and file consumed once;
- document completed result serializes `resultType=document` and `slides` in FastAPI and standalone;
- `POST /ppt/document-files` returns a token in both entrypoints;
- standalone rejects an upload JSON body above 15 MB before reading it;
- logs/error payloads do not contain the original filename or Base64.

- [ ] **Step 2: Run focused PPT tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_ppt_document_files adapter_service.tests.test_ppt_slide_assistant adapter_service.tests.test_packaging_scripts -v
```

Expected: FAIL because the service dispatch and upload routes do not exist.

- [ ] **Step 3: Dispatch document mode and guarantee cleanup**

Inject one shared `PptDocumentFileStore` into `PptSlideAssistant`. Keep the existing slide branch byte-for-byte where practical. Add:

```python
def assist(self, request, trace_id, progress_callback=None):
    if request.source_mode == "document":
        if not request.file_token:
            raise AdapterError("PPT_DOCUMENT_FILE_REQUIRED", "请先选择并上传 Markdown 或 Word 文档。", 400)
        staged = self.document_file_store.consume(request.file_token)
        try:
            if progress_callback:
                progress_callback("正在上传文档到模型后台。")
            return self.provider_client.ppt_document_summary(
                staged,
                request.requested_slide_count,
                request.user_instruction[:PPT_MAX_USER_INSTRUCTION_LENGTH],
                trace_id,
                progress_callback=progress_callback,
            )
        finally:
            self.document_file_store.delete(staged)
    return self._assist_slide(request, trace_id)
```

The provider method reports “模型后台正在解析文档并生成 PPT 建议。” after successful file upload. Do not expose the local path.

- [ ] **Step 4: Add stage-aware job updates without weakening idempotency**

Change `_run` to pass a callback that only updates `runningMessage` and `updatedAt`:

```python
result = self.assistant.assist(
    request,
    trace_id=trace_id,
    progress_callback=lambda message: self._update(job_id, runningMessage=message),
)
```

Set the initial message by mode:

```python
"已接收文档，adapter 正在准备模型后台任务。" if request.source_mode == "document" else RUNNING_MESSAGE
```

Keep the existing lock-before-thread start, job ID normalization, max jobs, 1800 timeout field, and duplicate return path.

- [ ] **Step 5: Add FastAPI and standalone upload routes**

Instantiate one store and inject it into the assistant in each entrypoint. FastAPI response:

```python
@router.post("/ppt/document-files")
def upload_ppt_document_file(request: PptDocumentFileUploadRequest) -> dict:
    trace_id = new_trace_id("ppt-document-file")
    data = ppt_document_files.store(
        request.file_name, request.mime_type, request.size_bytes, request.content_base64
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "ppt.slide_assistant",
        "message": "文档已安全接收。",
        "data": data,
        "errors": [],
    }
```

Standalone must parse the same model and envelope. Set `PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES = 15 * 1024 * 1024`; for this route, inspect `Content-Length` before `rfile.read` and return HTTP 413 with `PPT_DOCUMENT_TOO_LARGE` when exceeded. Preserve all other route behavior.

- [ ] **Step 6: Run tests and commit**

Run the command from Step 2. Expected: all focused tests PASS.

```bash
git add adapter_service/app/services/ppt/slide_assistant.py adapter_service/app/services/ppt/slide_assistant_jobs.py adapter_service/app/api/ppt.py adapter_service/standalone_adapter.py adapter_service/tests/test_ppt_slide_assistant.py adapter_service/tests/test_packaging_scripts.py
git commit -m "feat: add PPT document summary jobs"
```

### Task 4: Build the PPT “智能总结” Task Pane

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.xml`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Write failing helper and layout tests**

Add helper tests for:

```javascript
assert.deepStrictEqual(helpers.validatePptDocumentFile({ name: "报告.md", size: 1024 }), {
  valid: true, extension: "md", mimeType: "text/markdown"
});
assert.strictEqual(helpers.validatePptDocumentFile({ name: "报告.pdf", size: 1024 }).code, "PPT_DOCUMENT_TYPE_UNSUPPORTED");
assert.strictEqual(helpers.validatePptDocumentFile({ name: "报告.docx", size: 10 * 1024 * 1024 + 1 }).code, "PPT_DOCUMENT_TOO_LARGE");
assert.strictEqual(helpers.normalizePptDocumentResult({ slides: [{ index: 1, title: "封面" }] }).resultType, "document");
assert.ok(helpers.buildPptDocumentOutline(result).includes("1. 封面"));
assert.ok(helpers.buildPptDocumentSlidePlainText(result.slides[0]).includes("版式建议"));
```

Add layout assertions for these exact contracts:

- PPT Ribbon and `<title>` contain “智能总结”, not “PPT 单页助手”;
- top-right contains `id="health-indicator"` and no `build-badge`;
- segmented buttons `ppt-source-slide` and `ppt-source-document` exist;
- file input has `accept=".md,.docx"`;
- page count contains `5, 8, 10, 12, 15` and defaults to 10;
- JavaScript contains `/ppt/document-files`, `/ppt/slide-assistant/jobs`, `FileReader`, and persistent job recovery;
- no PPT write members such as `.Text =`, `.TextRange.Text`, `.Shapes.Add`, `.Slides.Add`, `.Delete()`, or `.Apply` occur.

- [ ] **Step 2: Run JS tests and verify failure**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on the new names, controls, routes, and helper exports.

- [ ] **Step 3: Add pure document helpers**

Export the following functions while retaining every current slide helper:

```javascript
function validatePptDocumentFile(file) {
  var name = safeText(file && file.name);
  var size = Number(file && file.size) || 0;
  var match = name.toLowerCase().match(/\.([^.]+)$/);
  var extension = match ? match[1] : "";
  if (extension !== "md" && extension !== "docx") return { valid: false, code: "PPT_DOCUMENT_TYPE_UNSUPPORTED", message: "仅支持 Markdown（.md）和 Word（.docx）文档。" };
  if (size < 1 || size > 10 * 1024 * 1024) return { valid: false, code: "PPT_DOCUMENT_TOO_LARGE", message: "文件大小必须在 1 字节至 10 MB 之间。" };
  return { valid: true, extension: extension, mimeType: extension === "md" ? "text/markdown" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document" };
}
```

`normalizePptDocumentResult` must sanitize every field and sort slides by numeric index. `buildPptDocumentPlainText`, `buildPptDocumentOutline`, and `buildPptDocumentSlidePlainText` must produce Chinese section labels and must never include `rawAnswer` when structured output exists.

- [ ] **Step 4: Replace the PPT shell with the approved segmented layout**

Use this hierarchy and preserve existing workflow/settings DOM IDs:

```html
<header class="app-header">
  <div><p class="eyebrow">WPS AI 助理</p><h1 id="task-title">智能总结</h1></div>
  <span id="health-indicator" class="health-badge is-checking">检测中</span>
</header>
<main id="home-view">
  <div class="segmented-control" role="tablist" aria-label="总结来源">
    <button id="ppt-source-slide" class="segment is-active" type="button">当前页总结</button>
    <button id="ppt-source-document" class="segment" type="button">文档总结</button>
  </div>
  <section id="slide-summary-controls"></section>
  <section id="document-summary-controls" hidden>
    <label class="file-picker" for="ppt-document-file">选择 Markdown 或 Word 文档</label>
    <input id="ppt-document-file" type="file" accept=".md,.docx" hidden />
    <div id="ppt-document-file-summary" class="file-summary">尚未选择文件</div>
    <label for="ppt-slide-count">建议页数</label>
    <select id="ppt-slide-count"><option>5</option><option>8</option><option selected>10</option><option>12</option><option>15</option></select>
  </section>
  <button id="btn-run-summary" class="primary-action" type="button"><img src="./assets/icon-ppt-slide-assistant.png" alt="" />开始总结</button>
  <section id="result-section"></section>
</main>
```

The real HTML must retain current-page instruction, current slide preview, workflow selector, result tabs, copy controls, and full settings/diagnostics controls. Do not nest result cards inside panels.

- [ ] **Step 5: Implement upload, submit, polling, and rendering**

Add state fields `sourceMode`, `selectedDocument`, `documentResult`, and reuse the current persisted `clientJobId`. File reading must use:

```javascript
function readFileAsBase64(file) {
  return new Promise(function (resolve, reject) {
    var reader = new FileReader();
    reader.onload = function () {
      var value = safeText(reader.result);
      resolve(value.indexOf(",") >= 0 ? value.split(",").pop() : value);
    };
    reader.onerror = function () { reject(new Error("读取文件失败，请重新选择文件。")); };
    reader.readAsDataURL(file);
  });
}
```

Document submission order is fixed:

1. validate file and instruction length at most 1000;
2. upload JSON to `/ppt/document-files`;
3. create and persist `clientJobId` before job POST;
4. submit `sourceMode=document`, token, count, instruction, and ID;
5. poll the existing job endpoint with the existing short request timeout and recovery counters;
6. retain job ID on transient query failures and clear it only on completed/failed/not-found;
7. render structured document results or raw fallback.

Render document output as a summary header followed by separator rows. Each slide row provides `复制标题`, `复制正文`, and `复制本页`; the global toolbar provides `复制大纲` and `复制完整方案`. Keep current-slide copies unchanged. Switching segments must not clear completed results or submit a second running task.

Load `/health` during initialization and set badge states to `检测中`, `已连接`, or `未连接`. Remove the visible fixed build badge, but keep `FRONTEND_BUILD_VERSION` for diagnostics.

- [ ] **Step 6: Run JS tests, syntax checks, and commit**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: all commands exit 0.

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0 formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: add PPT smart summary task pane"
```

### Task 5: Unify Word, Excel, and PPT Visual Design and Rename Excel

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add failing visual-contract and Excel naming assertions**

For all three CSS files assert the same tokens and constraints:

```javascript
for (const css of [wordCss, excelCss, pptCss]) {
  assert.ok(css.includes("--color-bg: #f3f6f8"));
  assert.ok(css.includes("--color-surface: #ffffff"));
  assert.ok(css.includes("--color-primary: #397894"));
  assert.ok(css.includes("--radius-panel: 8px"));
  assert.ok(!/radial-gradient|linear-gradient/.test(css));
}
```

Assert Excel runtime UI uses “智能分析” and does not contain current user-facing “Excel 智能分析”, while `excel.analysis`, existing DOM IDs, endpoints, and recovery strings remain present. Assert all three headers expose the same health badge classes and primary action icon dimensions.

- [ ] **Step 2: Run layout smoke and verify failure**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on old gradients/radii and the old Excel label.

- [ ] **Step 3: Apply one visual token set to all three CSS files**

Use this exact root token set in each file:

```css
:root {
  --color-bg: #f3f6f8;
  --color-surface: #ffffff;
  --color-surface-muted: #eef3f5;
  --color-border: #d5e0e5;
  --color-text: #17262e;
  --color-text-muted: #63757f;
  --color-primary: #397894;
  --color-primary-hover: #2f687f;
  --color-success: #2f7d5c;
  --color-warning: #a56a13;
  --color-danger: #a44242;
  --radius-control: 6px;
  --radius-panel: 8px;
  --shadow-panel: 0 1px 3px rgba(23, 38, 46, 0.08);
  --control-height: 36px;
}
```

Remove decorative gradients and color blobs. Use stable `min-width: 0`, `overflow-wrap: anywhere`, 36px controls, 8px panels, 6px buttons/inputs, visible focus outlines, and no panel-inside-panel shadows. Keep every Word/Excel DOM structure and JavaScript selector unchanged. Use existing local PNG assets inside primary actions; do not add a third-party icon library.

- [ ] **Step 4: Rename Excel user-facing text only**

Change Ribbon, page title, heading, workflow label, status messages, and profile manager display label from “Excel 智能分析” to “智能分析”. Keep:

```javascript
{ taskType: "excel.analysis", label: "智能分析" }
```

Do not change `/excel/analysis`, `/excel/analysis/jobs`, storage keys, `clientJobId`, extraction options, report rendering, or clipboard behavior.

- [ ] **Step 5: Perform 420x900 visual regression for all hosts**

Serve the repository with the existing local static server, open each task pane at `420x900`, and capture:

- Word smart write and settings;
- Excel analysis and settings;
- PPT current-page summary, document summary, and settings.

Verify no horizontal overflow, clipped labels, overlapping controls, nested cards, decorative gradients, or invisible focus/state badges. Verify all action icons remain sharp and aligned. Do not approve the task if any button text wraps outside its control.

- [ ] **Step 6: Run regression and commit**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: all commands exit 0 and visual checks pass.

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0 formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "style: unify WPS host task panes"
```

### Task 6: Add Prompt Templates and Workflow Documentation

**Files:**
- Create: `docs/prompt-templates/excel-smart-analysis-prompt-template.md`
- Create: `docs/prompt-templates/ppt-smart-summary-prompt-template.md`
- Modify: `docs/operations/dify-ppt-slide-assistant-workflow.md`
- Modify: `docs/operations/dify-excel-analysis-workflow.md`
- Modify: `docs/operations/workflow-profile-management.md`
- Modify: `packaging/build_phase1_delivery_kit.sh`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`

- [ ] **Step 1: Write failing packaging assertions**

Add:

```python
def test_delivery_includes_excel_and_ppt_prompt_templates(self):
    script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")
    self.assertIn("docs/prompt-templates", script)
    self.assertIn("excel-smart-analysis-prompt-template.md", script)
    self.assertIn("ppt-smart-summary-prompt-template.md", script)
    for name in ["excel-smart-analysis-prompt-template.md", "ppt-smart-summary-prompt-template.md"]:
        text = (ROOT / "docs/prompt-templates" / name).read_text(encoding="utf-8")
        self.assertIn("System Prompt", text)
        self.assertIn("输出契约", text)
        self.assertIn("<think>", text)
        self.assertIn("max token", text.lower())
        self.assertNotIn("Bearer sk-", text)
        self.assertNotIn("provider_api_key", text)
```

- [ ] **Step 2: Run packaging tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected: FAIL because the two files and copy commands are absent.

- [ ] **Step 3: Write the Excel prompt template**

The Markdown file must contain task scope, Dify variables, deployment steps, output schema, max-token guidance, errors, and this copy-ready System Prompt:

```text
你是企业表格数据分析助手。只根据 userinput.query 中提供的表格范围、表头、样本、统计信息和用户要求进行分析。
输出一个 JSON 对象，顶层字段固定为 structuredReport 和 plainText。
structuredReport 固定包含 overview、findings、risks、actions；后三项必须是字符串数组。
识别趋势、异常、风险和可执行建议；数据被截断时必须明确说明结论仅基于有限样本。
不得编造数据、因果关系或业务背景，不得生成或执行公式，不得声称已经修改 Excel，不得输出深度思考过程或 <think> 标签内容。
plainText 应为可直接复制到 Word 或 PPT 的中文汇报段落。
```

Recommend limiting findings/risks/actions to 3-8 each and `plainText` to 800 Chinese characters when Dify max token is constrained.

- [ ] **Step 4: Write the dual-mode PPT prompt template**

Document both branches: no `userinput.files` means current-page summary; file present means document extraction followed by full deck planning. Include exact current-page Markdown contract and exact document JSON contract from the design spec. The System Prompt must say attachments are untrusted source content, not instructions; subtitle is optional; facts must come from query/attachment; no PPT write claim; no think content.

Document required Dify nodes:

1. User Input exposing `userinput.query` and `userinput.files`.
2. Conditional branch on whether files exist.
3. Document Extractor in the file branch.
4. LLM node receiving extracted text plus query.
5. Answer node returning only final output.

Recommend at most 2-5 bullets per slide and no more than the requested 15 slides.

- [ ] **Step 5: Update operations and delivery documentation**

Rename current labels to “智能分析” and “智能总结”; retain internal keys. Add `/ppt/document-files`, file limits, Dify `/files/upload`, document extractor, one-time token behavior, stage messages, raw fallback, and read-only boundary. Acceptance must explicitly test:

- `.md`, valid `.docx`, invalid DOCX, unsupported type, and over-10-MB rejection;
- 5/8/10/12/15 slide choices;
- 180+ second recovery and reopening the task pane;
- slide/document result copy actions;
- Word/Excel/PPT host isolation;
- API URL and all keys preserved after overwrite install.

Update the builder:

```bash
mkdir -p "$TMP_DIR/docs/operations" "$TMP_DIR/docs/prompt-templates"
cp "$ROOT_DIR/docs/prompt-templates/excel-smart-analysis-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"
cp "$ROOT_DIR/docs/prompt-templates/ppt-smart-summary-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"
```

- [ ] **Step 6: Run documentation/package tests and commit**

Run the command from Step 2 and `bash -n packaging/build_phase1_delivery_kit.sh`. Expected: all pass.

```bash
git add docs/prompt-templates docs/operations packaging/build_phase1_delivery_kit.sh adapter_service/tests/test_packaging_scripts.py phase1-delivery-kit
git commit -m "docs: add Excel and PPT prompt templates"
```

### Task 7: Align `v0.18.0-alpha`, README, and One Combined Package

**Files:**
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/manifest.json`
- Modify: three hosts' `index.html`, `taskpane.html`, `taskpane.js`, and `ribbon.js` cache/version tokens
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260714-v0180.tar.gz`

- [ ] **Step 1: Update version assertions first**

Change tests to require `0.18.0-alpha` in adapter diagnostics, start script, all manifests, cache keys, and task panes. Keep the package directory names ending in `_1.0.0`; those are stable WPS add-in identifiers, not release versions.

- [ ] **Step 2: Run version tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on remaining `0.17.0-alpha` runtime tokens.

- [ ] **Step 3: Replace active runtime version tokens and update release docs**

Set every active runtime token to `0.18.0-alpha` and user-facing docs to `v0.18.0-alpha`. Add a release-history row describing:

- PPT “智能总结” current-page/document dual mode;
- secure Markdown/DOCX upload and full-deck advice;
- unified three-host visual design;
- Excel “智能分析” rename;
- two prompt templates;
- one combined package preserving configuration.

Update handoff interfaces, key files, protection logic, test results, target package, and target-machine checklist. Historical release rows may retain names used by those historical versions.

- [ ] **Step 4: Run the complete automated regression suite**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/standalone_adapter.py adapter_service/app/api/ppt.py adapter_service/app/main.py adapter_service/app/core/models.py adapter_service/app/services/provider_client.py adapter_service/app/services/ppt/document_files.py adapter_service/app/services/ppt/slide_assistant.py adapter_service/app/services/ppt/slide_assistant_jobs.py
bash -n packaging/build_phase1_delivery_kit.sh
bash -n phase1-delivery-kit/installer/install_phase1.sh
git diff --check
```

Expected: all commands exit 0; only dependency-conditioned tests may skip. Record exact pass/skip counts in `docs/codex-handoff.md`.

- [ ] **Step 5: Build and inspect the one combined formal delivery package**

Run:

```bash
DATE_TAG=20260714-v0180 bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260714-v0180.tar.gz | rg 'wps-ai-assistant(_1.0.0|-et_1.0.0|-wpp_1.0.0)|prompt-templates/(excel-smart-analysis|ppt-smart-summary)-prompt-template.md|dify-ppt-slide-assistant-workflow.md'
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260714-v0180.tar.gz
```

Expected: exactly one new archive contains all three add-ins, adapter, installer, both prompt templates, and operations docs. Record the checksum in README, handoff, and acceptance record. Do not delete or stage unrelated archive changes.

- [ ] **Step 6: Inspect the final diff and commit the release**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Stage only the paths changed by this plan and the one new `20260714-v0180` archive:

```bash
git add README.md README-ZH.md docs/codex-handoff.md docs/operations docs/prompt-templates adapter-start-kit adapter_service config formal-plugin-kit phase1-delivery-kit packaging dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260714-v0180.tar.gz
git commit -m "release: publish v0.18.0-alpha"
```

Confirm `git status --short` still shows the pre-existing historical archive changes untouched.

### Task 8: Target-Machine Acceptance and GitHub Delivery

**Files:**
- Modify after testing: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Modify after testing: `docs/codex-handoff.md`

- [ ] **Step 1: Perform overwrite-install preservation checks on Kylin V10**

Install the single `20260714-v0180` package over `v0.17.0-alpha`. Before and after installation compare:

- `config/adapter.json` API URL and provider path;
- `run/provider_api_key`;
- every file under `run/provider_api_keys/`;
- active workflow profile names and key references.

Expected: values and files remain unchanged.

- [ ] **Step 2: Verify host isolation and visual consistency**

Open each WPS host and verify:

1. Word shows only 智能编写、智能仿写、文档审查、格式审查、设置.
2. Excel shows only 智能分析、设置.
3. PPT shows only 智能总结、设置.
4. All task panes show the same header, connection badge, panel/button/input style, and no fixed build badge.

- [ ] **Step 3: Verify PPT current-page regression**

Test a slide with title + subtitle + body, one without subtitle, and one with insufficient body. Expected: title/subtitle remain separate, generate/optimize selection is unchanged, copy actions work, 180+ second tasks recover, and the presentation remains byte-for-byte unmodified by the add-in.

- [ ] **Step 4: Verify PPT document summary**

Test UTF-8/BOM Markdown, valid DOCX, invalid DOCX, PDF, and a file over 10 MB. For a valid document test 5 and 15 slide requests, raw Markdown fallback, think-mode output, adapter restart/token expiry, temporary status-query failure, and reopening the pane during a running task. Expected: valid tasks complete with structured/copyable output; invalid inputs show Chinese errors; think content is absent; no duplicate model task occurs.

- [ ] **Step 5: Record evidence, commit, and push `main`**

Write actual results and package checksum into the acceptance record and handoff, then run the relevant automated tests once more if either file changes executable expectations.

```bash
git add phase1-delivery-kit/docs/phase1-acceptance-record.md docs/codex-handoff.md
git commit -m "docs: record v0.18.0-alpha acceptance"
git push origin main
```

Expected: `main` and `origin/main` point to the same final commit; the design-spec commit `37f05a2` and every implementation/release commit are present on `main`.

## Final Completion Criteria

- One formal package installs isolated Word, Excel, and PPT add-ins and preserves all existing adapter configuration and keys.
- Excel user-facing text is “智能分析”; internal task key remains `excel.analysis`.
- PPT user-facing text is “智能总结”; internal task key remains `ppt.slide_assistant`.
- PPT current-page mode retains title/subtitle separation, generate/optimize behavior, 1800-second provider budget, recoverable polling, and read-only output.
- PPT document mode accepts one valid `.md` or `.docx` up to 10 MB, securely stages it, uploads it with the active PPT workflow key, and deletes local content after upload/failure/expiry.
- Dify legacy and user-input payload retries carry the same file reference and remove think-tag content.
- Structured full-deck results, raw fallback, global copy, and per-slide copy work without PPT write APIs.
- Word and Excel business behavior, Word writeback, job recovery, workflow profiles, and diagnostics remain unchanged.
- Three task panes pass 420x900 visual review with unified tokens, readable controls, and no overlap.
- Both prompt templates and updated workflow documentation are inside the package.
- Python, JS helper, layout smoke, syntax, shell, packaging, and target-machine acceptance checks pass and are recorded.
