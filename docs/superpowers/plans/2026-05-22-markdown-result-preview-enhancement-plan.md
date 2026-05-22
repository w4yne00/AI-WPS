# Markdown Result Preview Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the rendered Markdown result pane for Dify office-writing output.

**Architecture:** Extend the existing safe, dependency-free task-pane Markdown helper and style the new output structures in the formal plugin CSS. Keep result display rendered-only while copy and WPS apply paths continue to use raw model text.

**Tech Stack:** WPS native HTML/CSS/JavaScript, Node smoke tests.

---

### Task 1: Lock Missing Markdown Structures

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`

- [x] Add expectations for paragraph single-line breaks.
- [x] Add expectations for horizontal rules.
- [x] Add expectations for table wrapper, headers, and body cells.
- [x] Run the helper test and verify it fails on the current renderer.

### Task 2: Extend Renderer and Styling

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [x] Preserve paragraph line breaks as `<br>`.
- [x] Render Markdown table headers and body rows inside a scroll wrapper.
- [x] Render Markdown horizontal rules.
- [x] Switch rendered output whitespace to normal HTML flow and add table/rule
  styles for a narrow task pane.
- [x] Keep safe HTML escaping and allow-listed links covered by tests.

### Task 3: Release Validation

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

- [x] Bump the release to `v0.11.8-alpha`.
- [x] Run JS, Python, Bash syntax, compile, and diff checks.
- [x] Build and inspect the Phase 1 delivery package.
