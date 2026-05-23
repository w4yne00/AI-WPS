# Template Smart Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a template-driven Word smart-format preview/apply flow based on the user-provided technical document template.

**Architecture:** Keep `/word/format-preview` as the public entry point, but extend its response with deterministic target formatting properties and optional AI paragraph-role classification. Provider configuration gains task-level API keys that override the unified key only for matching tasks.

**Tech Stack:** FastAPI, Pydantic, Python 3.8, WPS JS taskpane, vanilla JavaScript, Dify Chat `/chat-messages`.

---

### Task 1: Template Rule Refresh

**Files:**
- Modify: `templates/company/technical-file-format-requirements.json`
- Modify: `templates/company/technical-file-format-requirements.docx`

- [ ] Replace the bundled template docx with the user-provided standard template.
- [ ] Update JSON rules with page setup, role mappings, style ids, paragraph properties, and table/caption/note/list style rules.
- [ ] Verify the template can still be loaded by `TemplateLoader`.

### Task 2: Backend Smart Format Plan

**Files:**
- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/word/formatter.py`
- Test: `adapter_service/tests/test_word_format_preview.py`

- [ ] Extend `FormatChange` with optional `targetProperties`, `role`, and `confidence`.
- [ ] Extend `FormatPreviewSummary` with optional `provider` and `pageSetupChangeCount`.
- [ ] Add local role inference for headings, captions, notes, lists, appendices, table body, title, and body.
- [ ] Generate page setup and paragraph formatting changes from the selected template.
- [ ] Add tests for technical template roles and target properties.

### Task 3: Task-Level Provider Keys

**Files:**
- Modify: `adapter_service/app/core/config.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/app/api/config.py`
- Modify: `config/adapter.example.json`
- Test: `adapter_service/tests/test_config.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [ ] Add `taskApiKeyRefs` to settings.
- [ ] Prefer task API key for `word.smart_format`, then fallback to unified key.
- [ ] Add task key status/save/delete provider APIs.
- [ ] Include task API key status in `/config`.
- [ ] Add tests proving task key isolation.

### Task 4: WPS Taskpane Apply and Settings UI

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Test: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] Add task key inputs for smart formatting and other AI tasks without removing unified key fallback.
- [ ] Apply `targetProperties` in WPS, including page setup and paragraph formatting.
- [ ] Render smart-format preview with provider, role, and reason.
- [ ] Keep smart writing and technical review UI behavior unchanged.

### Task 5: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

- [ ] Document smart-format template behavior and task API key configuration.
- [ ] Run Python unit tests for config, provider, formatter, and existing word flows.
- [ ] Run JS smoke/helper tests and syntax check.
- [ ] Run `git diff --check`.
