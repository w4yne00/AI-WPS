# Smart Write Markdown Writeback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v0.13.0 direction A by letting smart-write Markdown results write back to Word with basic formatting while preserving preview, copy, and plain-text fallback behavior.

**Architecture:** Add a testable Markdown writeback block parser in `taskpane-helpers.js`, then call it from the existing `applyRewrite()` path in `taskpane.js`. The parser returns a conservative sequence of headings, paragraphs, lists, and inline bold spans; the WPS integration attempts formatted insertion only when the host exposes enough selection/range APIs, otherwise it writes the original model text exactly as before.

**Tech Stack:** WPS JS plugin, browser JavaScript, Node-based helper tests, existing `layout-smoke.test.js`.

---

### Task 1: Add Markdown Writeback Parser Tests

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Test: `formal-plugin-kit/tests/taskpane-helpers.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
function testBuildMarkdownWritebackBlocksPreservesSupportedStructure() {
  const blocks = helpers.buildMarkdownWritebackBlocks([
    "# 总体要求",
    "",
    "第一段包含**重点**内容。",
    "",
    "- 第一项",
    "- 第二项",
    "",
    "1. 步骤一",
    "2. 步骤二"
  ].join("\n"));

  assert.strictEqual(blocks.length, 5);
  assert.deepStrictEqual(blocks[0], {
    type: "heading",
    level: 1,
    text: "总体要求",
    runs: [{ text: "总体要求", bold: false }]
  });
  assert.strictEqual(blocks[1].type, "paragraph");
  assert.deepStrictEqual(blocks[1].runs, [
    { text: "第一段包含", bold: false },
    { text: "重点", bold: true },
    { text: "内容。", bold: false }
  ]);
  assert.strictEqual(blocks[2].type, "unorderedListItem");
  assert.strictEqual(blocks[2].text, "第一项");
  assert.strictEqual(blocks[4].type, "orderedListItem");
  assert.strictEqual(blocks[4].ordinal, 2);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js`

Expected: FAIL because `helpers.buildMarkdownWritebackBlocks` is not defined.

### Task 2: Implement Markdown Writeback Parser

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Test: `formal-plugin-kit/tests/taskpane-helpers.test.js`

- [ ] **Step 1: Add parser helpers**

```javascript
function stripInlineMarkdownForWriteback(value) {
  return String(value || "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/\*{1,3}/g, "");
}

function buildInlineWritebackRuns(value) {
  var runs = [];
  var source = String(value || "");
  var pattern = /\*\*([^*]+)\*\*/g;
  var lastIndex = 0;
  var match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > lastIndex) {
      runs.push({ text: stripInlineMarkdownForWriteback(source.slice(lastIndex, match.index)), bold: false });
    }
    runs.push({ text: stripInlineMarkdownForWriteback(match[1]), bold: true });
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < source.length) {
    runs.push({ text: stripInlineMarkdownForWriteback(source.slice(lastIndex)), bold: false });
  }
  return runs.filter(function (run) { return run.text; });
}
```

- [ ] **Step 2: Add block builder**

```javascript
function buildMarkdownWritebackBlocks(markdown) {
  var lines = String(markdown || "").replace(/\r/g, "").split("\n");
  var blocks = [];
  var paragraph = [];
  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    var text = paragraph.join("\n");
    blocks.push({ type: "paragraph", text: stripInlineMarkdownForWriteback(text), runs: buildInlineWritebackRuns(text) });
    paragraph = [];
  }
  lines.forEach(function (line) {
    var heading = line.match(/^(#{1,6})\s+(.+)$/);
    var unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    var ordered = line.match(/^\s*(\d+)\.\s+(.+)$/);
    if (!line.trim()) {
      flushParagraph();
      return;
    }
    if (heading) {
      flushParagraph();
      blocks.push({ type: "heading", level: heading[1].length, text: stripInlineMarkdownForWriteback(heading[2]), runs: buildInlineWritebackRuns(heading[2]) });
      return;
    }
    if (unordered) {
      flushParagraph();
      blocks.push({ type: "unorderedListItem", text: stripInlineMarkdownForWriteback(unordered[1]), runs: buildInlineWritebackRuns(unordered[1]) });
      return;
    }
    if (ordered) {
      flushParagraph();
      blocks.push({ type: "orderedListItem", ordinal: Number(ordered[1]), text: stripInlineMarkdownForWriteback(ordered[2]), runs: buildInlineWritebackRuns(ordered[2]) });
      return;
    }
    paragraph.push(line.trim());
  });
  flushParagraph();
  return blocks;
}
```

- [ ] **Step 3: Run helper tests**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js`

Expected: PASS.

### Task 3: Add Smart Write Apply Integration

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add smoke assertions**

```javascript
assert.ok(js.includes("buildMarkdownWritebackBlocks"));
assert.ok(js.includes("tryApplyFormattedRewrite"));
assert.ok(js.includes("格式化写回不可用，已按纯文本应用。"));
```

- [ ] **Step 2: Run smoke test to verify it fails**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js`

Expected: FAIL because integration function names are not present.

- [ ] **Step 3: Add formatted writeback attempt**

```javascript
function tryApplyFormattedRewrite(target, text) {
  if (!helpers.buildMarkdownWritebackBlocks) {
    return { ok: false, reason: "parser_unavailable" };
  }
  var blocks = helpers.buildMarkdownWritebackBlocks(text);
  if (!blocks.length) {
    return { ok: false, reason: "empty" };
  }
  if (!target || !target.Range || typeof target.Range.Text === "undefined") {
    return { ok: false, reason: "range_unavailable" };
  }
  target.Range.Text = blocks.map(function (block) { return block.text; }).join("\n");
  return { ok: false, reason: "formatting_api_unverified" };
}
```

The first implementation may intentionally use the pure-text write after parsing because actual WPS style mutation must remain guarded until host APIs are verified. It still establishes the parser and fallback boundary without changing existing write behavior.

- [ ] **Step 4: Run smoke test**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js`

Expected: PASS.

### Task 4: Full Verification

**Files:**
- Read: `docs/codex-handoff.md`
- Test: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Run JS helper tests**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js`

Expected: PASS.

- [ ] **Step 2: Run layout smoke tests**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js`

Expected: PASS.

- [ ] **Step 3: Run syntax checks**

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`

Expected: no output and exit code 0.

Run: `/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`

Expected: no output and exit code 0.

- [ ] **Step 4: Run diff hygiene**

Run: `git diff --check`

Expected: no output and exit code 0.
