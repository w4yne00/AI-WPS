# Blue-Gray Task Pane And Ribbon Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved `A 雾蓝银白` foreground theme to the WPS task pane and Ribbon icon artwork without changing any application or adapter behavior.

**Architecture:** The task pane already centralizes its presentation tokens and component colors in one CSS file, so the implementation replaces palette values in place. Ribbon buttons already resolve stable PNG paths, so their artwork can be recolored in place while keeping mappings and runtime code unchanged.

**Tech Stack:** HTML/CSS task pane, WPS Ribbon PNG assets, Node.js smoke assertions.

---

### Task 1: Pin Theme Expectations In The Frontend Smoke Test

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Write the failing palette assertions**

Add checks after the CSS smoke assertions:

```javascript
assert.ok(css.includes("--accent: #386ea8;"));
assert.ok(css.includes("--accent-press: #2c5a8b;"));
assert.ok(css.includes("rgba(56, 110, 168"));
assert.ok(!css.includes("#174f43"));
assert.ok(!css.includes("#1e6a59"));
assert.ok(!css.includes("rgba(23, 79, 67"));
```

- [ ] **Step 2: Run the smoke test and verify RED**

Run: `node formal-plugin-kit/tests/layout-smoke.test.js`
Expected: FAIL because `taskpane.css` still contains the green accent palette.

### Task 2: Apply The Approved Task Pane Color Tokens

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Replace only theme colors**

Update the root palette to use:

```css
--bg: #f4f7fc;
--surface-soft: rgba(238, 244, 251, 0.78);
--text: #182334;
--muted: #647286;
--accent: #386ea8;
--accent-press: #2c5a8b;
--secondary: #eef3f8;
```

Replace all former `rgba(23, 79, 67, ...)` accent uses with `rgba(56, 110, 168, ...)`, and change the button gradient start to `#477eb8`.

- [ ] **Step 2: Run the smoke test and verify GREEN**

Run: `node formal-plugin-kit/tests/layout-smoke.test.js`
Expected: PASS.

### Task 3: Replace Ribbon Artwork In Place

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/ai-assistant-32.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-write.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-proofread.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-format.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-review.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-settings.png`
- Verify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`

- [ ] **Step 1: Generate blue-gray versions with identical semantics**

Preserve the current symbol roles and transparent 32 x 32 format while replacing dark green artwork with a `#386ea8`/`#8ca9c7` blue-gray treatment.

- [ ] **Step 2: Verify dimensions and unchanged mapping**

Run:

```bash
file formal-plugin-kit/wps-ai-assistant_1.0.0/assets/*.png
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: the six Ribbon images remain `32 x 32` RGBA PNG files and existing icon mapping assertions pass.

### Task 4: Visual Verification

**Files:**
- Verify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Verify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`

- [ ] **Step 1: Render the themed task pane at sidebar width**

Load the task pane UI in a local browser preview at a narrow sidebar width, with Markdown result content visible.

- [ ] **Step 2: Check visual acceptance conditions**

Confirm that the surface reads as bright blue-gray/white, primary actions and focus states remain legible, Markdown elements remain differentiated, and no controls overlap.

- [ ] **Step 3: Preserve delivery separation**

Do not commit or push this theme independently while the existing uncommitted feature delivery is still being assembled; include it in the next user-requested delivery commit after full verification.
