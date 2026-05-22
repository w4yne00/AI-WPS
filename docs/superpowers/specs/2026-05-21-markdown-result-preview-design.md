# Markdown Result Preview Design

Date: 2026-05-21

## Goal

Render Dify model responses in the WPS task pane with Markdown formatting while preserving the raw response text for copy and apply actions.

## Current Problem

The task pane result area used `<pre id="result-output">` and `textContent`. This preserved line breaks but displayed Markdown literally, so headings, lists, quotes, code blocks, and links looked unformatted even when Dify returned valid Markdown.

## Design

- Keep the adapter response contract unchanged.
- Add a small Markdown renderer to `taskpane-helpers.js` so the plugin has no new offline dependency.
- Render only a safe subset needed for office output review:
  - headings
  - paragraphs
  - unordered and ordered lists
  - blockquotes
  - inline code and fenced code blocks
  - bold, italic, and safe links
- Escape raw HTML before rendering.
- Allow links only for `http`, `https`, and `mailto`.
- Continue storing the original model text in `state.copyText`.
- Continue applying the original model text back into WPS documents.

## Files

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- `formal-plugin-kit/tests/taskpane-helpers.test.js`
- `formal-plugin-kit/tests/layout-smoke.test.js`

## Validation

- Helper tests cover Markdown block rendering and unsafe HTML/link escaping.
- Layout smoke tests prevent the result area from reverting to a plain `<pre>`.
- Existing JS syntax and packaging checks remain required.
