# Markdown Result Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WPS task pane result preview display Dify Markdown responses with formatting while preserving raw text for copy/apply.

**Architecture:** Add a dependency-free safe Markdown renderer in `taskpane-helpers.js`, call it from `setResult`, and style the result container as Markdown content. Tests lock both rendering behavior and XSS-safe escaping.

**Tech Stack:** WPS native HTML/CSS/JavaScript, Node-based smoke tests.

---

### Task 1: Add Markdown Helper Tests

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`

- [x] **Step 1: Add a test for common Markdown blocks**

Validate headings, lists, bold text, inline code, blockquotes, and fenced code blocks.

- [x] **Step 2: Add a test for unsafe input**

Validate raw HTML is escaped and `javascript:` links are not rendered as clickable links.

- [x] **Step 3: Run the test and verify it fails**

Run: `node formal-plugin-kit/tests/taskpane-helpers.test.js`

Expected: failure because `helpers.renderMarkdown` does not exist yet.

### Task 2: Implement Safe Markdown Rendering

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`

- [x] **Step 1: Add HTML escaping and URL allow-list helpers**

Escape `&`, `<`, `>`, `"`, and `'`; allow only `http`, `https`, and `mailto` link targets.

- [x] **Step 2: Add inline Markdown rendering**

Render inline code, links, bold, and italic after protecting generated HTML tokens.

- [x] **Step 3: Add block Markdown rendering**

Render headings, paragraphs, ordered/unordered lists, blockquotes, and fenced code blocks.

- [x] **Step 4: Export `renderMarkdown`**

Expose the helper through `WpsAiAssistantHelpers` and CommonJS tests.

### Task 3: Use Markdown in the Result Preview

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`

- [x] **Step 1: Change result insertion**

Use `output.innerHTML = helpers.renderMarkdown(text)` when available, with `textContent` fallback.

- [x] **Step 2: Preserve copy/apply behavior**

Keep `state.copyText = text || ""` and do not change WPS writeback logic.

- [x] **Step 3: Replace `<pre>` with a Markdown container**

Use `<div id="result-output" class="markdown-output">等待运行。</div>`.

- [x] **Step 4: Add Markdown content styles**

Style headings, paragraphs, lists, blockquotes, inline code, code blocks, links, and strong text.

### Task 4: Validate and Package

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

- [x] **Step 1: Add layout smoke coverage**

Assert the result container uses `markdown-output`, no longer uses `<pre id="result-output">`, and `taskpane.js` references `renderMarkdown`.

- [x] **Step 2: Run focused JS checks**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

- [x] **Step 3: Run full project checks**

Run the Python tests, JS tests, compile check, `git diff --check`, and package builder listed in `docs/codex-handoff.md`.

- [x] **Step 4: Update docs**

Record `v0.11.5-alpha`, Markdown result preview behavior, tests, and package output.
