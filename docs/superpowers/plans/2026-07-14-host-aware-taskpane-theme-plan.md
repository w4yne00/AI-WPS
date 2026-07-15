# Host-Aware Taskpane Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Word, Excel, and PPT task panes distinct WPS-aligned host colors, normalize successful connection feedback to “已连接”, add PPT-style settings/back navigation to Word and Excel, and make all primary generation buttons text-only.

**Architecture:** Keep the three existing host-specific plugin directories and their isolated HTML/CSS/JavaScript entry points. Implement host identity through static CSS variables, reuse the existing PPT header interaction pattern for Word and Excel, and normalize health text only at the presentation layer. Do not change adapter APIs, task payloads, polling, result rendering, copying, or Word writeback.

**Tech Stack:** WPS JS add-in HTML/CSS/ES5 JavaScript, Node.js `assert` smoke tests, local static HTTP server, Playwright/browser visual inspection.

---

## File Map

- `formal-plugin-kit/tests/layout-smoke.test.js`: static contracts for host colors, header controls, health text, navigation state, and text-only primary actions.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`: Word header settings/back button markup.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`: Word blue palette, header icon button, top host marker, and text-only primary action.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`: Word “已连接” text and last non-settings mode navigation.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`: Excel header settings/back button markup.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`: Excel green palette, header icon button, top host marker, and text-only primary action.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`: Excel “已连接” text and settings/back navigation.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`: PPT orange palette, top host marker, and text-only primary action.
- `docs/codex-handoff.md`: current UI behavior, protected logic, and verification record.

No new runtime files or dependencies are required.

### Task 1: Word blue theme, connection text, and settings return

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`

- [ ] **Step 1: Add failing Word layout and behavior contracts**

In `formal-plugin-kit/tests/layout-smoke.test.js`, add these Word header assertions beside the existing `top-toolbox` assertion:

```js
assert.ok(html.includes('id="btn-open-settings"'));
assert.ok(html.includes('class="icon-button"'));
assert.ok(html.includes('class="settings-icon"'));
assert.ok(html.includes('class="back-icon"'));
assert.ok(html.includes('title="打开设置"'));
assert.ok(html.includes('aria-label="打开设置"'));
```

Add these Word JavaScript assertions beside the existing `switchMode` assertions:

```js
assert.ok(js.includes('lastTaskMode: "smartWrite"'));
assert.ok(js.includes('byId("btn-open-settings").addEventListener("click"'));
assert.ok(js.includes('state.currentMode === "settings" ? state.lastTaskMode : "settings"'));
assert.ok(js.includes('setHealthBadge("badge-ok", "已连接")'));
assert.ok(js.includes('classList.toggle("is-back", settingsMode)'));
assert.ok(js.includes('settingsMode ? "返回" + returnTitle : "打开设置"'));
assert.ok(!js.includes('setHealthBadge("badge-ok", health.data.status)'));
```

In the shared CSS contract loop, remove the old cross-host requirements:

```js
assert.ok(hostCss.includes("--color-bg: #f3f6f8"));
assert.ok(hostCss.includes("--color-primary: #397894"));
assert.ok(hostCss.includes("#btn-run-primary::before"));
assert.ok(hostCss.includes("width: 18px"));
assert.ok(hostCss.includes("height: 18px"));
```

Then add Word-specific CSS contracts after the shared loop:

```js
assert.ok(css.includes("--color-primary: #2f6db3"));
assert.ok(css.includes("--color-primary-hover: #265c98"));
assert.ok(css.includes("--color-bg: #f4f7fb"));
assert.ok(css.includes("--color-surface-muted: #eaf2fb"));
assert.ok(css.includes("rgba(47, 109, 179"));
assert.ok(!css.includes("rgba(57, 120, 148"));
assert.ok(css.includes("border-top: 3px solid var(--color-primary)"));
assert.ok(css.includes(".icon-button"));
assert.ok(css.includes(".icon-button.is-back .settings-icon"));
assert.ok(css.includes(".icon-button.is-back .back-icon"));
assert.ok(!css.includes("#btn-run-primary::before"));
```

Replace the existing Word-only assertion `assert.ok(css.includes("rgba(57, 120, 148"));` with `assert.ok(css.includes("rgba(47, 109, 179"));` so the test no longer requires the retired generic blue.

- [ ] **Step 2: Run the smoke test and verify the new contracts fail**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on the missing Word `btn-open-settings` assertion. The failure must come from the new requirement, not a syntax or file-read error.

- [ ] **Step 3: Add the Word settings/back header control**

Replace the contents of Word `#top-toolbox` in `taskpane.html` with the PPT-aligned structure:

```html
<div id="top-toolbox" class="header-actions">
  <button id="btn-open-settings" class="icon-button" type="button" title="打开设置" aria-label="打开设置">
    <img class="settings-icon" src="./assets/icon-settings.png" alt="" />
    <span class="back-icon" aria-hidden="true">←</span>
  </button>
  <div id="health-indicator" class="badge badge-warn" aria-live="polite">检测中</div>
</div>
```

- [ ] **Step 4: Apply the Word blue palette and text-only primary action**

Update the Word `:root` host variables in `taskpane.css`:

```css
--color-bg: #f4f7fb;
--color-surface-muted: #eaf2fb;
--color-border: #c9d9e8;
--color-text: #182636;
--color-text-muted: #607386;
--color-primary: #2f6db3;
--color-primary-hover: #265c98;
--hairline-strong: #adc4da;
```

Replace every Word task-pane accent occurrence of `rgba(57, 120, 148, A)` with `rgba(47, 109, 179, A)`, preserving each existing alpha `A`. This updates field focus, blockquote accents, and selected result-view backgrounds without changing their layout.

Add the top host marker to `body`:

```css
border-top: 3px solid var(--color-primary);
```

Copy the established PPT icon-button behavior into Word CSS, keeping the existing 36px control size:

```css
.icon-button {
  display: inline-flex;
  width: var(--control-height);
  min-width: var(--control-height);
  height: var(--control-height);
  align-items: center;
  justify-content: center;
  padding: 7px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}

.icon-button:hover {
  background: var(--surface-soft);
}

.icon-button img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.back-icon {
  display: none;
  font-size: 22px;
  line-height: 1;
}

.icon-button.is-back .settings-icon {
  display: none;
}

.icon-button.is-back .back-icon {
  display: inline;
}
```

Delete the complete Word `#btn-run-primary::before` rule. Keep `#btn-run-primary` centered but remove its unused icon gap:

```css
#btn-run-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
```

- [ ] **Step 5: Implement Word connection normalization and return-state navigation**

Add a stable return target to the Word `state` object:

```js
lastTaskMode: "smartWrite",
```

Replace the complete Word `switchMode(mode)` function with:

```js
function switchMode(mode) {
  var requestedMode = modeConfig[mode] ? mode : "smartWrite";
  var config = modeConfig[requestedMode] || modeConfig.smartWrite;
  var settingsMode = requestedMode === "settings";
  var returnTitle;

  state.currentMode = requestedMode;
  if (!settingsMode) {
    state.lastTaskMode = requestedMode;
  }
  returnTitle = (modeConfig[state.lastTaskMode] || modeConfig.smartWrite).title;
  document.body.setAttribute("data-task-mode", state.currentMode);
  byId("task-title").textContent = config.title;
  byId("btn-open-settings").classList.toggle("is-back", settingsMode);
  byId("btn-open-settings").setAttribute("title", settingsMode ? "返回" + returnTitle : "打开设置");
  byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回" + returnTitle : "打开设置");
  resetSmartWritePreviewState();
  resetDocumentReviewState();

  if (settingsMode) {
    switchView("settings");
    renderWorkflowProfileManager();
    return;
  }

  switchView("home");
  renderWorkflowProfileStrip();
  loadWorkflowProfiles(getCurrentWorkflowTaskType());
  byId("rewrite-options").hidden = !config.showRewriteOptions;
  byId("instruction-block").hidden = !config.showInstruction;
  byId("template-options").hidden = !config.showTemplate;
  byId("document-review-options").hidden = !config.showDocumentReviewOptions;
  byId("fixed-template-options").hidden = !config.showFixedTemplate;
  byId("smart-imitation-options").hidden = !config.showSmartImitationOptions;
  byId("style-field-label").textContent = config.styleLabel || "表达风格";
  byId("btn-run-primary").textContent = config.primaryText;
  byId("btn-apply").hidden = state.currentMode !== "smartWrite";
  hideCompareForSmartImitation();
  updateRewritePromptPreview();
  state.pendingApplyAction = "";
  setApplyEnabled(false);
  setStatus("等待操作。");
  if (state.currentMode === "smartImitation") {
    fillSmartImitationTemplateFromSelection();
  }
  if (state.currentMode === "documentReview") {
    resumeDocumentReviewActiveJob();
  }
}
```

Bind the new button in `bindEvents()`:

```js
byId("btn-open-settings").addEventListener("click", function () {
  switchMode(state.currentMode === "settings" ? state.lastTaskMode : "settings");
});
```

Normalize successful health text in `refreshConfig()`:

```js
setHealthBadge("badge-ok", "已连接");
```

Do not change `setAdapterUnavailableState`, task requests, result rendering, polling, or writeback functions.

- [ ] **Step 6: Run the smoke and Word helper tests**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

Expected: all three commands PASS.

- [ ] **Step 7: Commit the Word task-pane change**

```bash
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
git commit -m "style: align Word task pane with host theme"
```

### Task 2: Excel green theme, connection text, and settings return

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`

- [ ] **Step 1: Add failing Excel contracts**

Add Excel header assertions near the existing Excel HTML assertions:

```js
assert.ok(excelHtml.includes('id="btn-open-settings"'));
assert.ok(excelHtml.includes('class="icon-button"'));
assert.ok(excelHtml.includes('class="settings-icon"'));
assert.ok(excelHtml.includes('class="back-icon"'));
assert.ok(excelHtml.includes('title="打开设置"'));
```

Add Excel JavaScript assertions near the existing `switchMode` assertions:

```js
assert.ok(excelJs.includes('byId("btn-open-settings").addEventListener("click"'));
assert.ok(excelJs.includes('state.currentMode === "settings" ? "excelAnalysis" : "settings"'));
assert.ok(excelJs.includes('setHealthBadge("badge-ok", "已连接")'));
assert.ok(excelJs.includes('classList.toggle("is-back", settingsMode)'));
assert.ok(!excelJs.includes('setHealthBadge("badge-ok", healthData.status || "就绪")'));
```

Add Excel CSS contracts after the Word-specific contracts:

```js
assert.ok(excelCss.includes("--color-primary: #237a4b"));
assert.ok(excelCss.includes("--color-primary-hover: #1b643d"));
assert.ok(excelCss.includes("--color-bg: #f4f8f5"));
assert.ok(excelCss.includes("--color-surface-muted: #eaf6ef"));
assert.ok(excelCss.includes("rgba(35, 122, 75"));
assert.ok(!excelCss.includes("rgba(57, 120, 148"));
assert.ok(excelCss.includes("border-top: 3px solid var(--color-primary)"));
assert.ok(excelCss.includes(".icon-button.is-back .settings-icon"));
assert.ok(excelCss.includes(".icon-button.is-back .back-icon"));
assert.ok(!excelCss.includes("#btn-run-primary::before"));
```

- [ ] **Step 2: Run the smoke test and verify the Excel contract fails**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on the missing Excel `btn-open-settings` assertion.

- [ ] **Step 3: Add the Excel settings/back header control**

Use the same header markup as Word, with Excel's existing settings asset:

```html
<div id="top-toolbox" class="header-actions">
  <button id="btn-open-settings" class="icon-button" type="button" title="打开设置" aria-label="打开设置">
    <img class="settings-icon" src="./assets/icon-settings.png" alt="" />
    <span class="back-icon" aria-hidden="true">←</span>
  </button>
  <div id="health-indicator" class="badge badge-warn" aria-live="polite">检测中</div>
</div>
```

- [ ] **Step 4: Apply the Excel green palette and text-only primary action**

Update the Excel host variables:

```css
--color-bg: #f4f8f5;
--color-surface-muted: #eaf6ef;
--color-border: #c8ddcf;
--color-text: #192a21;
--color-text-muted: #60766a;
--color-primary: #237a4b;
--color-primary-hover: #1b643d;
--hairline-strong: #aecdb9;
```

Replace every Excel task-pane accent occurrence of `rgba(57, 120, 148, A)` with `rgba(35, 122, 75, A)`, preserving each existing alpha `A`.

Add `border-top: 3px solid var(--color-primary);` to `body`. Add these complete header-control rules:

```css
.icon-button {
  display: inline-flex;
  width: var(--control-height);
  min-width: var(--control-height);
  height: var(--control-height);
  align-items: center;
  justify-content: center;
  padding: 7px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}

.icon-button:hover {
  background: var(--surface-soft);
}

.icon-button img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.back-icon {
  display: none;
  font-size: 22px;
  line-height: 1;
}

.icon-button.is-back .settings-icon {
  display: none;
}

.icon-button.is-back .back-icon {
  display: inline;
}
```

Delete the complete Excel `#btn-run-primary::before` rule and replace the primary button rule with:

```css
#btn-run-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
```

- [ ] **Step 5: Implement Excel connection normalization and settings return**

Update `switchMode(mode)`:

```js
var settingsMode = mode === "settings";
state.currentMode = settingsMode ? "settings" : "excelAnalysis";
document.body.setAttribute("data-task-mode", state.currentMode);
byId("task-title").textContent = settingsMode ? "设置" : "智能分析";
byId("btn-open-settings").classList.toggle("is-back", settingsMode);
byId("btn-open-settings").setAttribute("title", settingsMode ? "返回智能分析" : "打开设置");
byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回智能分析" : "打开设置");
switchView(settingsMode ? "settings" : "home");
```

Bind the button in `bindEvents()`:

```js
byId("btn-open-settings").addEventListener("click", function () {
  switchMode(state.currentMode === "settings" ? "excelAnalysis" : "settings");
});
```

Normalize successful health text in `refreshConfig()`:

```js
setHealthBadge("badge-ok", "已连接");
```

Keep `updateScopeIndicator`, `resumeExcelAnalysisActiveJob`, and `loadWorkflowProfiles` in the non-settings branch exactly as they are.

- [ ] **Step 6: Run the Excel and shared front-end tests**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
```

Expected: all commands PASS.

- [ ] **Step 7: Commit the Excel task-pane change**

```bash
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
git commit -m "style: align Excel task pane with host theme"
```

### Task 3: PPT orange theme and text-only primary action

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`

- [ ] **Step 1: Add failing PPT theme contracts**

Add these assertions after the Excel theme assertions:

```js
assert.ok(pptCss.includes("--color-primary: #d36b2c"));
assert.ok(pptCss.includes("--color-primary-hover: #b95720"));
assert.ok(pptCss.includes("--color-action: #b95720"));
assert.ok(pptCss.includes("--color-action-hover: #99461a"));
assert.ok(pptCss.includes("--color-bg: #fbf6f3"));
assert.ok(pptCss.includes("--color-surface-muted: #fff1e7"));
assert.ok(pptCss.includes("rgba(211, 107, 44, 0.42)"));
assert.ok(!pptCss.includes("rgba(57, 120, 148"));
assert.ok(pptCss.includes("border-top: 3px solid var(--color-primary)"));
assert.ok(!pptCss.includes("#btn-run-primary::before"));
```

Add this color-contrast helper near the test file imports and assert the three white-on-action-color combinations:

```js
function relativeLuminance(hex) {
  const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((value) => (
    value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
  ));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(first, second) {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

assert.ok(contrastRatio("#2f6db3", "#ffffff") >= 4.5);
assert.ok(contrastRatio("#237a4b", "#ffffff") >= 4.5);
assert.ok(contrastRatio("#b95720", "#ffffff") >= 4.5);
```

Replace the existing positive icon assertion:

```js
assert.ok(pptCss.includes("icon-ppt-slide-assistant.png"));
```

with the negative primary-action contract:

```js
assert.ok(!pptCss.includes('background: url("./assets/icon-ppt-slide-assistant.png")'));
```

- [ ] **Step 2: Run the smoke test and verify the PPT palette contract fails**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL because PPT still contains the generic blue primary color.

- [ ] **Step 3: Apply the PPT orange palette and text-only primary action**

Update the PPT host variables:

```css
--color-bg: #fbf6f3;
--color-surface-muted: #fff1e7;
--color-border: #ead6c9;
--color-text: #30231d;
--color-text-muted: #7b695f;
--color-primary: #d36b2c;
--color-primary-hover: #b95720;
--color-action: #b95720;
--color-action-hover: #99461a;
```

Replace PPT's focus outline `rgba(57, 120, 148, 0.42)` with `rgba(211, 107, 44, 0.42)`.

Add `border-top: 3px solid var(--color-primary);` to `body`. Delete the complete PPT `#btn-run-primary::before` rule and replace the primary action rules with:

```css
#btn-run-primary {
  display: inline-flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  background: var(--color-action);
  color: #fff;
}

#btn-run-primary:hover {
  background: var(--color-action-hover);
}
```

Do not change PPT HTML or JavaScript because its settings/back and “已连接/未连接” behavior already match the approved design.

- [ ] **Step 4: Run PPT, shared, and syntax tests**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: all commands PASS.

- [ ] **Step 5: Commit the PPT task-pane change**

```bash
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css
git commit -m "style: align PPT task pane with host theme"
```

### Task 4: Documentation, full regression, and visual acceptance

**Files:**
- Modify: `docs/codex-handoff.md`
- Verify: all files changed in Tasks 1-3

- [ ] **Step 1: Update the handoff document**

Add these current-version facts to `docs/codex-handoff.md`:

```markdown
- Word、Excel、PPT 任务窗格分别使用文字蓝、表格绿、演示橙的平衡宿主主题；布局和状态语义保持统一。
- 三个宿主健康检查成功时统一显示“已连接”，不直接展示 adapter `/health` 的原始 `ok`。
- Word 和 Excel 右上角新增与 PPT 一致的设置/返回快捷按钮；Word 返回进入设置前的功能，Excel 返回智能分析。
- 三个宿主的主生成按钮均为高对比度纯文字按钮，不显示图片、SVG 或伪元素图标。
```

Add this exact bullet to the protected-logic section:

```markdown
- Word/Excel/PPT 宿主配色、连接文案、设置快捷入口和纯文字主按钮均为前端展示层变化；不得借此改动 Word 回写、文档审查/智能分析/智能总结长任务恢复、模型请求或三个 Ribbon 的宿主隔离。
```

- [ ] **Step 2: Run all front-end regression tests and syntax checks**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: every command PASS with no syntax error.

- [ ] **Step 3: Start a local static server for visual inspection**

Run from the repository root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

Open the following pages at a 420×900 viewport:

```text
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html?mode=smartWrite
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html?mode=settings
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html?mode=excelAnalysis
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html?mode=settings
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html?mode=pptSlideAssistant
http://127.0.0.1:8765/formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html?mode=settings
```

Expected for all six views:

- no horizontal overflow or overlapping header controls;
- Word visibly blue, Excel visibly green, PPT visibly orange without large saturated color blocks;
- the settings icon is visible on task views and the back arrow is visible on settings views;
- the health badge uses a Chinese state label;
- primary generation buttons contain centered text only, with no icon blank space;
- button labels remain readable against each host color.

- [ ] **Step 4: Inspect the final diff and repository status**

Run:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only this feature's source, test, and handoff files are part of the new changes. Existing unrelated delivery-archive deletions/modifications/untracked files remain untouched and unstaged.

- [ ] **Step 5: Commit documentation and verification record**

```bash
git add docs/codex-handoff.md
git commit -m "docs: record host-aware taskpane themes"
```

Do not build a new delivery archive, bump the version, or push to GitHub unless the user requests those release actions separately.

## Review Corrections Applied During Execution

- Word 的设置快捷入口不得直接调用完整 `switchMode("settings")`。从任一已初始化功能页进入设置和返回时，仅切换 `home-view/settings-view`、标题和设置/返回图标；`state.currentMode`、结果 DOM、文档审查处理状态、未完成任务及回写可用性保持不变。只有通过 `?mode=settings` 直接打开设置时，返回才调用 `switchMode("smartWrite")` 初始化默认功能页。
- PPT 使用 `#D36B2C` 作为顶部宿主识别色，使用 `#B95720` 作为通用白字操作底色，悬停/按下使用 `#99461A`；避免任何白字按钮继续使用对比度不足的亮橙。
- Excel 范围摘要、当前工作流徽标和次级按钮悬停不得保留旧蓝色硬编码；PPT 文档选择入口不得保留旧蓝色浅背景。
- `layout-smoke.test.js` 除主题变量外，还必须排除上述旧蓝色值，并检查 Word 设置快捷切换函数不包含预览、审查或回写状态重置调用。
