# Markdown Result Preview Enhancement Design

Date: 2026-05-22

## Goal

Make the WPS task-pane result preview show Dify Markdown output as a readable
rendered document instead of a dense plain-text block.

## Scope

The result pane only shows rendered Markdown output. It does not expose a source
toggle and it does not change copy or WPS writeback behavior; those keep the raw
model text.

## Design

- Keep the dependency-free, safe Markdown renderer in `taskpane-helpers.js`.
- Preserve office-writing structure:
  - empty lines create paragraph spacing
  - single line breaks inside a paragraph remain visual `<br>` breaks
- Extend the rendered subset with:
  - horizontal rules
  - Markdown tables with a header separator row
- Keep existing headings, ordered/unordered lists, bold/italic, inline code,
  fenced code blocks, blockquotes, and allow-listed links.
- Render tables inside a scroll wrapper so a narrow WPS task pane does not crush
  columns or overflow the whole page.
- Keep raw HTML escaped and reject unsafe link protocols.

## Validation

- Helper tests assert paragraph line breaks, table markup, horizontal rules, and
  existing XSS protections.
- Layout smoke tests assert Markdown table styles ship with the formal plugin.
- Full project checks and delivery-kit inspection confirm the packaged target
  files contain the enhancement.
