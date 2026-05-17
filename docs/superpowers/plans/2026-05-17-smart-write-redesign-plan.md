# Smart Write Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate Rewrite and Continue entries with one workflow-backed Smart Write task that reliably passes WPS source text to Dify Workflow inputs and renders `outputs.result` in the task pane.

**Architecture:** Keep the current WPS native add-in and Python adapter structure. Add a new `word.smart_write` route using `/workflows/run`, expose `/word/smart-write`, update the task pane to one Smart Write mode, and simplify settings to global API URL plus four route-specific API keys.

**Tech Stack:** WPS JS add-in, vanilla HTML/CSS/JS task pane, Python 3.8 FastAPI adapter, standalone adapter fallback, Dify Workflow API.

---

## File Map

- Modify `config/adapter.example.json`: replace `word.rewrite` and `word.continue` with `word.smart_write`.
- Modify `adapter_service/app/services/provider_client.py`: add `build_smart_write_prompt()` and `ProviderClient.smart_write()` using workflow payload.
- Modify `adapter_service/app/services/word/rewriter.py`: add `smart_write()` method while keeping old `rewrite()` compatibility.
- Modify `adapter_service/app/api/word.py`: add `POST /word/smart-write`.
- Modify `adapter_service/standalone_adapter.py`: add standalone route handling for `/word/smart-write`, update `/config` and settings behavior.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`: replace rewrite/continue buttons with Smart Write.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`: map new button mode and icons.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`: change default title, add Smart Write action selector, remove global API key/probe controls.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`: add `smartWrite` mode, call `/word/smart-write`, render four route keys, remove probe and default key UI.
- Create/update icon files under `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/`.
- Modify tests in `adapter_service/tests/test_enterprise_provider.py`, `adapter_service/tests/test_packaging_scripts.py`, and `adapter_service/tests/test_word_rewrite.py`.
- Update docs and versions: README, README-ZH, handoff, Dify route guide, delivery README.

## Tasks

### Task 1: Backend Smart Write Payload

- [ ] Add tests asserting `word.smart_write` builds workflow payload with `source_text`, `write_action`, `style`, `focus`, `length`, `user_prompt`, `selection_mode`, `trace_id`.
- [ ] Implement `ProviderClient.smart_write()` and prompt helper.
- [ ] Preserve old `ProviderClient.rewrite()` for compatibility.
- [ ] Run `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v`.

### Task 2: Adapter Endpoint

- [ ] Add `/word/smart-write` endpoint returning `taskType=word.smart_write` and `data.rewrittenText`.
- [ ] Add tests for smart write endpoint with explicit `writeAction` values.
- [ ] Keep `/word/rewrite` unchanged for rollback compatibility.
- [ ] Run `python3 -m unittest adapter_service.tests.test_word_rewrite -v` where dependencies allow.

### Task 3: Config And Key Model

- [ ] Update `config/adapter.example.json` to four task routes: `word.smart_write`, `word.proofread`, `word.format_preview`, `word.technical_review`.
- [ ] Update settings summary tests so UI renders four route keys.
- [ ] Keep default key endpoints server-side for compatibility but remove them from product UI.

### Task 4: Ribbon And Icons

- [ ] Replace Ribbon buttons with Smart Write, Proofread, Format, Technical Review, Settings.
- [ ] Generate/commit simple PNG icons: smart write, proofread, format, review, settings.
- [ ] Update `ribbon.js` icon map and default mode to `smartWrite`.
- [ ] Add packaging tests asserting old rewrite/continue labels are absent and Smart Write is present.

### Task 5: Task Pane UI

- [ ] Change default task title to 智能编写.
- [ ] Replace modeConfig rewrite/continue with smartWrite.
- [ ] Add `write-action` select with rewrite/continue/summarize/custom.
- [ ] Keep style/focus/length/userInstruction.
- [ ] Call `/word/smart-write` and map response to existing apply-result logic.
- [ ] Remove probe button and global API key UI.
- [ ] Render task route order as smart write, proofread, format, technical review.

### Task 6: Standalone Adapter

- [ ] Add `/word/smart-write` route to standalone mode.
- [ ] Return mock Smart Write result when route key or URL is missing.
- [ ] Keep old `/word/rewrite` route unchanged.

### Task 7: Docs, Version, Package

- [ ] Bump version to `v0.11.0-alpha` and rule to `AI-WPS-P1-WORD-0.11.0-20260517`.
- [ ] Update README, README-ZH, handoff, Dify task route guide, delivery README.
- [ ] Rebuild `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260517.tar.gz`.
- [ ] Verify script executable bits in tarball.

### Task 8: Verification

- [ ] Run packaging tests.
- [ ] Run enterprise provider tests.
- [ ] Run compileall.
- [ ] Run `node --check taskpane.js`.
- [ ] Run `git diff --check`.
- [ ] Commit and push.
