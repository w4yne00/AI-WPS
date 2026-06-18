# Proofread Quality Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Word format proofreading as local deterministic format checks plus small-batch AI quality checks for typo, grammar, expression, logic, and fluency issues.

**Architecture:** Keep `/word/proofread` and `word.proofread` task API key routing unchanged. `WordProofreader` owns paragraph batching, local issue aggregation, AI issue validation, deduplication, and summary stats. `ProviderClient` owns prompt construction and one Dify call per proofread batch through the existing `/chat-messages` payload shape.

**Tech Stack:** Python 3.8, FastAPI adapter, Pydantic request models, existing unittest suite, WPS taskpane JavaScript issue rendering.

---

### Task 1: Provider Prompt And Parser

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [x] **Step 1: Write failing tests**

Add tests that assert `build_document_proofread_prompt` embeds small-batch JSON and that `parse_document_proofread_issues` accepts `fluency` while rejecting malformed AI items.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_document_proofread_prompt_embeds_batch_payload adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_parse_document_proofread_issues_accepts_fluency_and_rejects_invalid_items -v
```

Expected: tests fail because the prompt builder does not accept batch payload and the parser does not support `fluency` validation.

- [x] **Step 3: Implement minimal provider changes**

Change `build_document_proofread_prompt` to accept a `batch_payload` dict and include it as compact JSON after the instruction block. Keep `build_provider_request_payload` unchanged. Update `parse_document_proofread_issues` so allowed categories include `fluency`, allowed severities remain `info|warning|error`, invalid categories are discarded, empty `original/message/suggestion` items are discarded, and optional `allowed_paragraph_indexes` filters out out-of-batch results.

- [x] **Step 4: Run tests and verify pass**

Run the two tests from Step 2. Expected: PASS.

### Task 2: Proofreader Batching And Summary

**Files:**
- Modify: `adapter_service/app/services/word/proofreader.py`
- Test: `adapter_service/tests/test_word_proofread.py`

- [x] **Step 1: Write failing unit tests**

Add unit tests with a fake provider that records calls. Verify long documents are split into multiple `word.proofread` calls, each query stays below the configured character budget, local format issues still return, AI invalid issues are dropped, and accepted AI issues include `fluency`.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_word_proofread -v
```

Expected: new tests fail because `WordProofreader` still sends one full-document AI request and does not expose summary.

- [x] **Step 3: Implement batching**

Add a `ProofreadResult` shape or internal dict so proofreading can return `issues` plus `summary`. Keep API response compatible by still returning `data.issues`. Add constants for max batch paragraphs and max batch characters. Build AI batches from non-empty paragraphs, call `provider_client.proofread_document_batch`, merge local and AI issues, and keep per-batch failures as counters instead of aborting.

- [x] **Step 4: Run proofreader tests**

Run the command from Step 2. Expected: PASS.

### Task 3: API And Taskpane Display

**Files:**
- Modify: `adapter_service/app/api/word.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [x] **Step 1: Write failing display/API assertions**

Add assertions that `/word/proofread` response data may include `summary`, and taskpane category labels include `fluency` as `通畅性`.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: frontend smoke test fails until the new category label exists.

- [x] **Step 3: Implement compatibility output**

Update `/word/proofread` to put `summary` beside `issues` when the proofreader returns one. Update `renderIssues` category labels and optionally prepend summary lines without changing smart write or smart format UI.

- [x] **Step 4: Run frontend smoke test**

Expected: PASS.

### Task 4: Docs, Version, Regression

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `docs/operations/dify-smart-format-workflow.md` only if needed for cross-reference; do not change smart format behavior.

- [x] **Step 1: Update docs**

Document `v0.12.8-alpha` format proofreading redesign, Dify output JSON, batching constraints, and the protection boundary for smart write and smart format.

- [x] **Step 2: Run full regression**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite adapter_service.tests.test_word_format_preview adapter_service.tests.test_word_proofread adapter_service.tests.test_word_technical_review -v
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall -q adapter_service/app adapter_service/standalone_adapter.py
git diff --check
```

Expected: all runnable tests pass; existing FastAPI TestClient tests may skip in environments without FastAPI.

### Task 5: Commit

**Files:**
- Stage only files touched by this implementation and its docs.

- [ ] **Step 1: Review staged diff**

Run:

```bash
git diff --cached --stat
git diff --cached -- adapter_service/app/services/provider_client.py adapter_service/app/services/word/proofreader.py adapter_service/app/api/word.py formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

- [ ] **Step 2: Commit**

Run:

```bash
git commit -m "feat: batch proofread quality checks"
```
