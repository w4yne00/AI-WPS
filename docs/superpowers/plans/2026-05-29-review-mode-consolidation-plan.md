# Review Mode Consolidation Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the Word taskpane into 智能编写、文档审查、格式审查、设置; keep 智能编写 and task-level API key routing stable; replace old 格式校对/智能排版/技术文档审查 paths with the new document review and format review workflows.

**Architecture:** Preserve the FastAPI adapter + WPS taskpane split. Backend exposes `/word/smart-write`, `/word/document-review`, and `/word/format-review`. Frontend modes become `smartWrite`, `documentReview`, `formatReview`, and `settings`. Task-specific API keys route through existing `ProviderClient.post_task()` and the unified Dify `/chat-messages` payload.

**Tech Stack:** Python FastAPI/Pydantic/Pytest, vanilla JS/HTML/CSS taskpane, Node-based frontend smoke tests, existing adapter config and packaging scripts.

---

## Preconditions

- [ ] Before any code edit, re-read `docs/codex-handoff.md` and confirm no newer handoff constraints supersede this plan.
- [ ] Work in the existing dirty tree without reverting unrelated user changes.
- [ ] Keep 智能编写 backend behavior unchanged: `/word/smart-write`, `word.smart_write`, `RewriteResponseData`, Markdown result rendering, and apply-to-selection/full-document behavior.
- [ ] Keep the adapter task API key mechanism unchanged, only replace the visible task definitions and task types.
- [ ] Do not add new runtime dependencies.

## Task 1: Lock The New Public Contract In Tests

**Files**
- `adapter_service/tests/test_health.py`
- `adapter_service/tests/test_enterprise_provider.py`
- `formal-plugin-kit/tests/layout-smoke.test.js`
- `formal-plugin-kit/tests/taskpane-helpers.test.js`

**Steps**
- [ ] Add failing backend assertions that `/health` and `/provider/route-diagnostics` report version `0.12.9-alpha` and task API key statuses only for:
  - `word.smart_write`
  - `word.document_review`
  - `word.format_review`
- [ ] Add failing provider tests that `ProviderClient.build_task_api_key_status()` maps:
  - `word.smart_write` to `word_smart_write`
  - `word.document_review` to `word_document_review`
  - `word.format_review` to `word_format_review`
- [ ] Add failing frontend smoke assertions that Ribbon/taskpane labels include 智能编写、文档审查、格式审查、设置, and do not include 格式校对、智能排版、技术文档审查.
- [ ] Add failing frontend assertions that old endpoints `/word/proofread`, `/word/technical-review`, `/word/format-preview`, and `/word/rewrite` are not referenced by taskpane/ribbon code.
- [ ] Run targeted tests and confirm failures are contract failures, not unrelated environment failures:

```bash
python -m pytest adapter_service/tests/test_health.py adapter_service/tests/test_enterprise_provider.py
node --test formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/tests/taskpane-helpers.test.js
```

## Task 2: Replace Provider Task Definitions And Review Parsing

**Files**
- `adapter_service/app/services/provider_client.py`
- `adapter_service/app/core/config.py`
- `config/adapter.example.json`
- `adapter_service/tests/test_enterprise_provider.py`

**Steps**
- [ ] Update provider version diagnostics from `0.12.8-alpha` to `0.12.9-alpha`.
- [ ] Change `ProviderClient.build_task_api_key_status()` task list to 智能编写、文档审查、格式审查 only.
- [ ] Keep `ProviderClient.post_task()` using the current Dify chat body:

```json
{
  "inputs": {"query": "<prompt>"},
  "query": "<prompt>",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

- [ ] Rename technical review prompt helpers to document review helpers:
  - `get_default_technical_review_prompt()` -> `get_default_document_review_prompt()`
  - `build_technical_review_prompt()` -> `build_document_review_prompt()`
  - `parse_technical_review_answer()` -> `parse_document_review_answer()`
- [ ] Update document review prompt categories to `typo`, `expression`, `logic`, `fluency`, `professional`.
- [ ] Keep Markdown-only Dify compatibility by parsing a fenced `json` block, plain JSON object, or JSON object embedded in answer text.
- [ ] Add `ProviderClient.document_review(text, trace_id, document_type, review_prompt)` that calls `post_task("word.document_review", ...)`.
- [ ] Add `ProviderClient.format_review_roles(trace_id, input_data, prompt)` for paragraph role classification through `post_task("word.format_review", ...)`.
- [ ] Delete unused public provider methods after callers are migrated:
  - `proofread_document_batch()`
  - `proofread_document()`
  - `technical_review()`
  - public entry points that still submit `word.smart_format`
- [ ] Run provider tests.

```bash
python -m pytest adapter_service/tests/test_enterprise_provider.py
```

## Task 3: Add Document Review Backend And Remove Old Text Review Services

**Files**
- `adapter_service/app/core/models.py`
- `adapter_service/app/services/word/document_reviewer.py`
- `adapter_service/app/services/word/technical_reviewer.py`
- `adapter_service/app/services/word/proofreader.py`
- `adapter_service/tests/test_word_document_review.py`
- `adapter_service/tests/test_word_technical_review.py`
- `adapter_service/tests/test_word_proofread.py`

**Steps**
- [ ] Add models:
  - `DocumentReviewIssue`
  - `DocumentReviewResponseData`
- [ ] Keep request fields compatible with the current frontend by reusing `RequestOptions.technical_document_type` and `RequestOptions.technical_review_prompt`; only the user-facing feature name changes.
- [ ] Implement `WordDocumentReviewer.review(request, trace_id)`:
  - Use `request.content.plain_text.strip()`.
  - Fallback to joined non-empty `request.content.paragraphs`.
  - Respect `request.selection_mode` and return `scope` as `selection` or `document`.
  - Use default prompt based on `technicalDocumentType` when the textarea is empty.
  - Call `ProviderClient.document_review()`.
  - Return `documentType`, `reviewPrompt`, `scope`, `summary`, `issues`, and `provider`.
- [ ] Ensure empty content returns a clear `AdapterError` or empty-result response consistent with existing backend behavior.
- [ ] Replace old tests with `test_word_document_review.py` covering:
  - selection scope
  - full-document scope
  - prompt fallback by document type
  - Markdown `json` code block parsing
  - category normalization for typo/expression/logic/fluency/professional
- [ ] Delete `WordProofreader` and `WordTechnicalReviewer` once no imports remain.
- [ ] Delete old proofread and technical review tests or replace them with new document review tests.
- [ ] Run:

```bash
python -m pytest adapter_service/tests/test_word_document_review.py adapter_service/tests/test_enterprise_provider.py
```

## Task 4: Add Format Review Backend And Remove Auto-Apply Preview Semantics

**Files**
- `adapter_service/app/core/models.py`
- `adapter_service/app/services/word/format_reviewer.py`
- `adapter_service/app/services/word/formatter.py`
- `adapter_service/tests/test_word_format_review.py`
- `adapter_service/tests/test_word_format_preview.py`

**Steps**
- [ ] Add models:
  - `FormatReviewIssue`
  - `FormatReviewSummary`
  - `FormatReviewResponseData`
- [ ] Extract retained logic from `WordFormatter` into `WordFormatReviewer`:
  - template resolution
  - `body_paragraphs(request)` handling
  - page setup comparison
  - local paragraph role inference
  - AI paragraph role classification
  - role JSON extraction
  - template role rule lookup
  - font, font size, line spacing, alignment, and indent comparison
- [ ] Change task type for AI role classification from `word.smart_format` to `word.format_review`.
- [ ] Ensure AI role classification is optional:
  - If `word.format_review` key is not configured, record debug with `skipReason=provider_not_configured` and continue local checks.
  - If Dify returns invalid role JSON, continue local checks and expose `aiFallbackReason`.
- [ ] Return `summary.issueCount` and `issues`, not `changes`.
- [ ] Do not return `targetProperties`, `currentStyle -> targetStyle`, or any writeback plan.
- [ ] Keep `paragraphIndex=0` page setup issues as review findings, not apply instructions.
- [ ] Replace old format preview tests with `test_word_format_review.py` covering:
  - selected paragraphs only
  - full document when no selection
  - local fallback when no task key
  - AI role classification when task key exists
  - no `targetProperties` in response
  - debug-last populated for skipped AI classification
- [ ] Delete `WordFormatter.preview()` and `FormatChange` usage after route/frontend migration.
- [ ] Run:

```bash
python -m pytest adapter_service/tests/test_word_format_review.py adapter_service/tests/test_templates.py adapter_service/tests/test_enterprise_provider.py
```

## Task 5: Replace Word API Routes And Validation Mapping

**Files**
- `adapter_service/app/api/word.py`
- `adapter_service/app/main.py`
- `adapter_service/standalone_adapter.py`
- `adapter_service/tests/test_word_document_review.py`
- `adapter_service/tests/test_word_format_review.py`
- `adapter_service/tests/test_health.py`

**Steps**
- [ ] In `app/api/word.py`, keep only:
  - `POST /word/smart-write`
  - `POST /word/document-review`
  - `POST /word/format-review`
- [ ] Route `/word/document-review` to `WordDocumentReviewer.review()` and return task type `word.document_review`.
- [ ] Route `/word/format-review` to `WordFormatReviewer.review()` and return task type `word.format_review`.
- [ ] Remove imports and singleton instances for deleted services.
- [ ] Update `_task_type_from_path()` in `app/main.py`:

```python
{
    "/word/smart-write": "word.smart_write",
    "/word/document-review": "word.document_review",
    "/word/format-review": "word.format_review",
}
```

- [ ] Update `FastAPI(... version=...)` and `/health` version to `0.12.9-alpha`.
- [ ] Mirror the same route surface in `adapter_service/standalone_adapter.py`, or delete obsolete standalone handlers if standalone adapter no longer exposes them.
- [ ] Add tests that old route strings do not appear in `adapter_service/app/api/word.py`, `adapter_service/app/main.py`, and frontend code.
- [ ] Run:

```bash
python -m pytest adapter_service/tests/test_word_document_review.py adapter_service/tests/test_word_format_review.py adapter_service/tests/test_health.py
```

## Task 6: Update Frontend Modes, Ribbon, And Smart Write Requirement Panel

**Files**
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- `formal-plugin-kit/tests/layout-smoke.test.js`
- `formal-plugin-kit/tests/taskpane-helpers.test.js`

**Steps**
- [ ] Update build/version query strings to `0.12.9-alpha`.
- [ ] Replace Ribbon IDs and mapping:
  - Keep `btnAiSmartWrite`.
  - Replace `btnAiProofread` with `btnAiDocumentReview`.
  - Replace `btnAiFormat` with `btnAiFormatReview`.
  - Remove `btnAiTechnicalReview`.
  - Keep `btnAiSettings`.
- [ ] Update `resolveMode()` to return only `smartWrite`, `documentReview`, `formatReview`, `settings`.
- [ ] Keep icon assets if useful, but update labels and mode names; do not introduce new image dependencies.
- [ ] Replace `TASK_API_KEY_DEFS` with:

```javascript
[
  { taskType: "word.smart_write", label: "智能编写" },
  { taskType: "word.document_review", label: "文档审查" },
  { taskType: "word.format_review", label: "格式审查" }
]
```

- [ ] Remove smart write `field-help` text under `rewrite-style`, `focus-point`, and `length-mode`.
- [ ] Expand `#rewrite-summary-card` into the only visible explanation panel for smart write:
  - selected option summary
  - style prompt full text
  - focus prompt full text
  - length prompt full text
  - output prompt text
- [ ] Update `updateRewritePromptPreview()` so it fills the current requirement panel and no longer targets removed `field-help` nodes.
- [ ] Make `#rewrite-summary-card` auto-height in CSS. Do not clamp text or use internal scroll.
- [ ] Rename technical review UI identifiers only where it reduces confusion:
  - display label becomes 文档审查
  - keep request option fields `technicalDocumentType` and `technicalReviewPrompt` unless a broader model migration is already complete
- [ ] Remove template dropdown from document review and format review screens.
- [ ] Format review screen shows fixed template text `技术文件格式及书写要求`.
- [ ] Change primary button labels:
  - 智能编写: `生成内容`
  - 文档审查: `开始文档审查`
  - 格式审查: `开始格式审查`
- [ ] Hide or disable `btn-apply` for document review and format review. It remains enabled only for smart write rewrite application.
- [ ] Delete frontend functions and state:
  - `runProofread()`
  - `runTechnicalReview()`
  - `runFormatPreview()`
  - `renderProofreadResult()`
  - `renderTechnicalReview()` after replacement
  - `renderFormatChanges()` after replacement
  - `applyFormatChanges()`
  - `applyPageSetup()`
  - `applyParagraphStyle()`
  - `state.formatChanges`
  - `pendingApplyAction === "format"` branch
- [ ] Add:
  - `runDocumentReview()`
  - `runFormatReview()`
  - `renderDocumentReview(data)`
  - `renderFormatReview(data)`
- [ ] Both new run functions use `resolveSelectionScope(false)` and pass the returned `selectionMode` into `extractDocument(scope.selectionMode)`.
- [ ] Run:

```bash
node --test formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/tests/taskpane-helpers.test.js
```

## Task 7: Update Docs, Operations Manuals, And Packaging

**Files**
- `README.md`
- `README-ZH.md`
- `docs/codex-handoff.md`
- `docs/operations/dify-proofread-workflow.md`
- `docs/operations/dify-smart-format-workflow.md`
- `docs/operations/dify-document-review-workflow.md`
- `docs/operations/dify-format-review-workflow.md`
- `packaging/build_phase1_delivery_kit.sh`
- `phase1-delivery-kit/README.md`
- `adapter-start-kit/scripts/start_uvicorn_adapter.sh`

**Steps**
- [ ] Update user-facing feature names to 智能编写、文档审查、格式审查、设置.
- [ ] Document that 智能排版 is intentionally paused as a long-document auto-formatting feature due Dify output and model context limits.
- [ ] Add Dify operation manual for 文档审查:
  - endpoint type: Chat App `/chat-messages`
  - task key: `word.document_review`
  - expected output: Markdown containing a single `json` code block
  - categories: `typo`, `expression`, `logic`, `fluency`, `professional`
- [ ] Add Dify operation manual for 格式审查 role recognition:
  - endpoint type: Chat App `/chat-messages`
  - task key: `word.format_review`
  - AI role recognition only
  - expected output: paragraph role JSON in a Markdown `json` code block
  - adapter performs the actual format compliance check locally
- [ ] Remove or archive old proofread/smart-format workflow manuals if they are no longer referenced by README and delivery package.
- [ ] Update packaging script so delivery package includes new manuals and excludes deleted manuals.
- [ ] Update handoff with:
  - `v0.12.9-alpha` feature state
  - exact task API key refs
  - old endpoint deletion note
  - preserved 智能编写 behavior
  - 智能排版 long-document auto-formatting deferred item
- [ ] Run packaging tests:

```bash
python -m pytest adapter_service/tests/test_packaging_scripts.py
```

## Task 8: Full Regression And Cleanup

**Steps**
- [ ] Search for deleted strings and remove remaining dead references:

```bash
rg -n "word\\.proofread|word\\.technical_review|word\\.smart_format|/word/proofread|/word/technical-review|/word/format-preview|/word/rewrite|runProofread|runTechnicalReview|runFormatPreview|applyFormatChanges|智能排版|格式校对|技术文档审查" adapter_service formal-plugin-kit config docs README.md README-ZH.md packaging phase1-delivery-kit
```

- [ ] Keep only intentional historical mentions in handoff or migration notes; all executable code and user-facing current docs should use new names.
- [ ] Run backend tests:

```bash
python -m pytest adapter_service/tests
```

- [ ] Run frontend tests:

```bash
node --test formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/tests/taskpane-helpers.test.js
```

- [ ] Run syntax/static sanity checks:

```bash
python -m compileall adapter_service
git diff --check
```

- [ ] Manually inspect `git diff` to confirm:
  - no 智能编写 backend changes beyond version/config/task key display
  - no old route fallback remains
  - no format auto-apply code remains
  - new document review and format review use independent task API keys
- [ ] Commit implementation with a message such as:

```bash
git add adapter_service formal-plugin-kit config docs README.md README-ZH.md packaging phase1-delivery-kit
git commit -m "feat: consolidate review modes"
```

## Expected Acceptance Criteria

- [ ] Ribbon shows only 智能编写、文档审查、格式审查、设置.
- [ ] 智能编写 still calls `/word/smart-write` and `word.smart_write`.
- [ ] 智能编写 current requirement panel shows all explanation text without clipping.
- [ ] 文档审查 calls `/word/document-review` and `word.document_review`.
- [ ] 文档审查 supports selected text/paragraph review and full-document review.
- [ ] 文档审查 does not show or send template selection.
- [ ] 格式审查 calls `/word/format-review` and `word.format_review`.
- [ ] 格式审查 supports selected range and full-document checks.
- [ ] 格式审查 keeps AI paragraph role recognition but performs compliance checks locally.
- [ ] 格式审查 never outputs or applies Word writeback instructions.
- [ ] Settings page task API keys are 智能编写、文档审查、格式审查 only.
- [ ] `/provider/debug-last` still records Dify request/response or local skip diagnostics.
- [ ] Old route strings are absent from executable code.
