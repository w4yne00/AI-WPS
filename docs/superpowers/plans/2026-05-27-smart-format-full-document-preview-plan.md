# Smart Format Full Document Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure smart-format preview processes every non-empty paragraph in a full Word document and makes document coverage visible in the task pane.

**Architecture:** Retain `/word/format-preview` and deterministic template writeback. Split Dify paragraph-role classification into bounded batches, merge valid classifications, and use existing local inference for unclassified paragraphs. Extend only the preview summary and its rendering so existing consumers remain compatible.

**Tech Stack:** Python 3.8, Pydantic models, FastAPI adapter, WPS JavaScript task pane, Node smoke tests, Python `unittest`.

---

### Task 1: Reproduce Long Document Role Truncation

**Files:**
- Modify: `adapter_service/tests/test_word_format_preview.py`

- [ ] **Step 1: Write the failing formatter test**

Add a fake configured provider that records prompts and returns `caption` for paragraph `121`, then assert a 121-paragraph request produces two provider calls and a caption change for paragraph `121`.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_word_format_preview.WordFormatterUnitTests.test_formatter_classifies_all_paragraphs_in_long_document -v
```

Expected: failure because the current implementation submits only the first 120 paragraphs.

### Task 2: Process Every Paragraph in Bounded AI Batches

**Files:**
- Modify: `adapter_service/app/services/word/formatter.py`
- Modify: `adapter_service/app/core/models.py`
- Test: `adapter_service/tests/test_word_format_preview.py`

- [ ] **Step 1: Implement batched role classification**

Keep a 120-paragraph per-request maximum, loop over all non-empty paragraphs, submit one prompt per batch, merge valid roles, and allow individual failed batches to fall back locally.

- [ ] **Step 2: Extend preview summary**

Return `paragraphCount`, `aiClassifiedParagraphCount`, `localFallbackParagraphCount`, and `aiBatchCount`, preserving existing `changes`, `changeCount`, `provider`, and `pageSetupChangeCount`.

- [ ] **Step 3: Run the formatter tests**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_word_format_preview -v
```

Expected: new long-document coverage test and existing formatter tests pass.

### Task 3: Clarify Preview Coverage in the WPS Task Pane

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`

- [ ] **Step 1: Write failing UI smoke assertions**

Require the task-pane implementation to render labels for `全文扫描段落`, `AI 识别段落`, `本地兜底段落`, and the explanation that only pending format changes are listed.

- [ ] **Step 2: Run the smoke test to verify it fails**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: failure until the new summary labels are implemented.

- [ ] **Step 3: Implement compatible summary rendering**

When new summary fields exist, show coverage statistics and the explanatory note. When they do not exist, preserve the existing preview header.

- [ ] **Step 4: Run the smoke test**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: pass.

### Task 4: Document and Verify the Fix

**Files:**
- Modify: `docs/codex-handoff.md`
- Modify: `docs/operations/dify-smart-format-workflow.md`

- [ ] **Step 1: Document long-document batching and summary interpretation**

Explain that `changeCount` is not a document length indicator, document the new coverage fields, and note that long documents may issue multiple smart-format requests.

- [ ] **Step 2: Run the regression suite**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite adapter_service.tests.test_word_format_preview adapter_service.tests.test_word_proofread adapter_service.tests.test_word_technical_review -v
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
```

Expected: all available tests pass; API tests may retain their existing dependency-based skip in the bundled environment.
