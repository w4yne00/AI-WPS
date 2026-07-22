# Word/Excel/PPT Apple Interface Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变三宿主业务链路和宿主配色的前提下，统一 Word、Excel、PPT 的任务页与设置页体验，并让模型接口状态按当前宿主当前工作流实时更新。

**Architecture:** 保留三个插件独立 HTML/CSS/JavaScript 运行时，在各宿主 `taskpane-helpers.js` 中提供同名纯状态函数和可测试刷新控制器，在各宿主 `taskpane.js` 中接入现有状态机。通过新增跨宿主静态契约测试约束统一 DOM、CSS 和可访问性结构，不引入共享构建系统、前端框架或运行时依赖。

**Tech Stack:** WPS JS 插件、原生 HTML/CSS/ES5 JavaScript、Node.js `assert` 源码契约测试、Playwright 浏览器视觉验证。

---

## 文件结构

本次不新增运行时代码目录，只新增一个跨宿主测试文件和一份实施记录：

- `formal-plugin-kit/tests/taskpane-experience-contract.test.js`：校验三宿主统一结构、宿主隔离、Apple 交互边界和可访问性标记。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`：Word 模型接口就绪度纯函数与设置刷新控制器。
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`：Excel 同名纯函数与刷新控制器。
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`：PPT 同名纯函数与刷新控制器。
- 三个宿主各自的 `taskpane.html`：紧凑模型接口、工作流说明、任务选项卡和高级诊断语义结构。
- 三个宿主各自的 `taskpane.css`：保留蓝/绿/橙变量，增加统一层级、焦点、按压、折叠和减少动态效果规则。
- 三个宿主各自的 `taskpane.js`：接入当前宿主就绪度、30 秒可见刷新、提示层、键盘选项卡和高级诊断披露行为。
- `docs/codex-handoff.md`：记录本次界面增量、保护边界和验证结果。

不修改 adapter、Ribbon、manifest、模型请求、任务轮询、结果解析、企业知识数据库、安装脚本或交付包。

### Task 1: 建立就绪度与刷新生命周期纯函数

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js:1-40, 900-950`
- Modify: `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js:1-45`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`（工作流辅助函数及导出区）
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`（工作流辅助函数及导出区）
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`（工作流辅助函数及 `WpsAiPptHelpers` 导出区）

- [ ] **Step 1: 先写模型接口状态和刷新控制器失败测试**

在 `taskpane-helpers.test.js` 中增加并同时对 Word、Excel helpers 执行：

```javascript
function assertSettingsExperienceContract(targetHelpers) {
  const profilesByTask = {
    "word.smart_write": {
      activeProfileId: "write-current",
      profiles: [{ id: "write-current", keyConfigured: true }]
    },
    "word.document_review": {
      activeProfileId: "review-current",
      profiles: [
        { id: "review-current", keyConfigured: false },
        { id: "review-backup", keyConfigured: true }
      ]
    }
  };

  assert.deepStrictEqual(
    targetHelpers.deriveModelInterfaceState({
      detectable: true,
      providerBaseUrl: "https://aibot.example.com/v1",
      taskTypes: ["word.smart_write", "word.document_review"],
      profilesByTask
    }),
    { code: "partial", label: "部分就绪 · 1/2", readyCount: 1, totalCount: 2 }
  );
  assert.strictEqual(targetHelpers.deriveModelInterfaceState({
    detectable: true,
    providerBaseUrl: "",
    taskTypes: ["word.smart_write"],
    profilesByTask
  }).code, "unconfigured");
  assert.strictEqual(targetHelpers.deriveModelInterfaceState({
    detectable: false,
    providerBaseUrl: "https://aibot.example.com/v1",
    taskTypes: ["word.smart_write"],
    profilesByTask
  }).code, "unavailable");

  let callback = null;
  let cleared = 0;
  let refreshes = 0;
  const controller = targetHelpers.createSettingsRefreshController({
    intervalMs: 30000,
    refresh() { refreshes += 1; },
    setIntervalFn(fn, delay) {
      assert.strictEqual(delay, 30000);
      callback = fn;
      return 17;
    },
    clearIntervalFn(id) {
      assert.strictEqual(id, 17);
      cleared += 1;
    }
  });
  controller.start();
  controller.start();
  assert.strictEqual(refreshes, 1);
  callback();
  assert.strictEqual(refreshes, 2);
  controller.stop();
  controller.stop();
  assert.strictEqual(cleared, 1);
}

assertSettingsExperienceContract(helpers);
assertSettingsExperienceContract(excelHelpers);
```

在 `ppt-taskpane-helpers.test.js` 中用现有 `plain()` 转换跨 VM 对象，并增加：

```javascript
const pptState = plain(helpers.deriveModelInterfaceState({
  detectable: true,
  providerBaseUrl: "https://aibot.example.com/v1",
  taskTypes: ["ppt.slide_assistant"],
  profilesByTask: {
    "ppt.slide_assistant": {
      activeProfileId: "ppt-current",
      profiles: [{ id: "ppt-current", keyConfigured: true }]
    }
  }
}));
assert.deepStrictEqual(pptState, {
  code: "ready",
  label: "已就绪",
  readyCount: 1,
  totalCount: 1
});

let pptTimerCallback = null;
let pptRefreshes = 0;
let pptClears = 0;
const pptController = helpers.createSettingsRefreshController({
  intervalMs: 30000,
  refresh() { pptRefreshes += 1; },
  setIntervalFn(fn) { pptTimerCallback = fn; return 23; },
  clearIntervalFn(id) { assert.strictEqual(id, 23); pptClears += 1; }
});
pptController.start();
pptController.start();
pptTimerCallback();
pptController.stop();
pptController.stop();
assert.strictEqual(pptRefreshes, 2);
assert.strictEqual(pptClears, 1);
```

- [ ] **Step 2: 运行测试并确认失败原因正确**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
```

Expected: 两个命令均因 `deriveModelInterfaceState is not a function` 失败，而不是既有测试失败。

- [ ] **Step 3: 在三个 helper 中实现相同合同**

在三个 helper 的工作流辅助函数附近加入以下 ES5 实现；PPT 版本使用相同函数体并加入 `WpsAiPptHelpers` 导出：

```javascript
function deriveModelInterfaceState(input) {
  var source = input || {};
  var taskTypes = Array.isArray(source.taskTypes) ? source.taskTypes : [];
  var profilesByTask = source.profilesByTask || {};
  var readyCount = 0;
  var totalCount = taskTypes.length;

  if (source.detectable === false) {
    return { code: "unavailable", label: "无法检测", readyCount: 0, totalCount: totalCount };
  }

  taskTypes.forEach(function (taskType) {
    var data = profilesByTask[taskType] || {};
    var profiles = Array.isArray(data.profiles) ? data.profiles : [];
    var active = profiles.filter(function (profile) {
      return profile && profile.id === data.activeProfileId;
    })[0];
    if (active && active.keyConfigured) {
      readyCount += 1;
    }
  });

  if (!String(source.providerBaseUrl || "").trim() || !totalCount || !readyCount) {
    return { code: "unconfigured", label: "未配置", readyCount: readyCount, totalCount: totalCount };
  }
  if (readyCount === totalCount) {
    return { code: "ready", label: "已就绪", readyCount: readyCount, totalCount: totalCount };
  }
  return {
    code: "partial",
    label: "部分就绪 · " + readyCount + "/" + totalCount,
    readyCount: readyCount,
    totalCount: totalCount
  };
}

function createSettingsRefreshController(options) {
  var settings = options || {};
  var refresh = typeof settings.refresh === "function" ? settings.refresh : function () {};
  var setIntervalFn = settings.setIntervalFn || setInterval;
  var clearIntervalFn = settings.clearIntervalFn || clearInterval;
  var intervalMs = Number(settings.intervalMs) || 30000;
  var timerId = null;

  return {
    start: function () {
      if (timerId !== null) {
        return;
      }
      refresh();
      timerId = setIntervalFn(refresh, intervalMs);
    },
    stop: function () {
      if (timerId === null) {
        return;
      }
      clearIntervalFn(timerId);
      timerId = null;
    },
    isRunning: function () {
      return timerId !== null;
    }
  };
}
```

将两个函数加入各自导出对象，名称必须完全一致：

```javascript
deriveModelInterfaceState: deriveModelInterfaceState,
createSettingsRefreshController: createSettingsRefreshController,
```

- [ ] **Step 4: 运行 helper 测试并确认通过**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
```

Expected: 两个命令均退出码 `0`，分别输出既有通过信息。

- [ ] **Step 5: 提交纯函数与测试**

```bash
git add formal-plugin-kit/tests/taskpane-helpers.test.js formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
git commit -m "test: define taskpane settings state contract"
```

### Task 2: 统一三宿主设置页语义结构

**Files:**
- Create: `formal-plugin-kit/tests/taskpane-experience-contract.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html:197-295`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`（设置首页与诊断区域）
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`（设置首页与诊断区域）

- [ ] **Step 1: 写三宿主 HTML 结构契约失败测试**

创建 `taskpane-experience-contract.test.js`：

```javascript
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const hosts = [
  { dir: "wps-ai-assistant_1.0.0", taskType: "word.smart_write", label: "智能编写" },
  { dir: "wps-ai-assistant-et_1.0.0", taskType: "excel.analysis", label: "智能分析" },
  { dir: "wps-ai-assistant-wpp_1.0.0", taskType: "ppt.slide_assistant", label: "智能总结" }
];

hosts.forEach((host) => {
  const html = fs.readFileSync(path.join(ROOT, host.dir, "taskpane.html"), "utf8");
  [
    'id="task-title"',
    'id="btn-open-settings"',
    'id="health-indicator"',
    'id="btn-run-primary"',
    'id="result-output"',
    'id="settings-status-line"',
    'id="provider-readiness-badge"',
    'id="btn-edit-provider-url"',
    'id="workflow-help-button"',
    'aria-controls="workflow-help-popover"',
    'id="workflow-help-popover"',
    'id="workflow-task-tabs"',
    'role="tablist"',
    'id="diagnostics-disclosure"',
    'id="diagnostics-section"',
    'id="btn-refresh-diagnostics"',
    'id="btn-copy-diagnostics"'
  ].forEach((marker) => assert.ok(html.includes(marker), `${host.dir} missing ${marker}`));
  assert.ok(html.includes(`data-workflow-task-tab="${host.taskType}"`));
  assert.ok(html.includes(`>${host.label}</button>`));
  assert.ok(!html.includes('id="btn-refresh"'), `${host.dir} must remove the redundant refresh button`);
  assert.ok(!html.includes("每项任务可保存多个工作流</span>"));
});

const wordHtml = fs.readFileSync(path.join(ROOT, hosts[0].dir, "taskpane.html"), "utf8");
const excelHtml = fs.readFileSync(path.join(ROOT, hosts[1].dir, "taskpane.html"), "utf8");
const pptHtml = fs.readFileSync(path.join(ROOT, hosts[2].dir, "taskpane.html"), "utf8");
assert.ok(wordHtml.includes('id="enterprise-knowledge-summary-card"'));
assert.ok(!excelHtml.includes('id="enterprise-knowledge-summary-card"'));
assert.ok(!pptHtml.includes('id="enterprise-knowledge-summary-card"'));

console.log("taskpane experience markup contract passed");
```

- [ ] **Step 2: 运行结构测试并确认失败**

Run:

```bash
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
```

Expected: FAIL，首个缺失标记为 `provider-readiness-badge` 或 Excel/PPT 的 `workflow-task-tabs`。

- [ ] **Step 3: 将三个模型接口区改为两行紧凑结构**

三个宿主保留各自现有 URL 编辑容器和输入框 ID，摘要区统一为：

```html
<section id="provider-summary-card" class="settings-card model-interface-card">
  <div class="model-interface-heading">
    <h4>模型接口</h4>
    <span id="provider-readiness-badge" class="readiness-badge is-unavailable" aria-live="polite">无法检测</span>
  </div>
  <div class="model-interface-row">
    <p id="provider-summary-url" class="provider-url-summary" title="">未配置接口地址</p>
    <button id="btn-edit-provider-url" class="text-action" type="button">修改</button>
  </div>
</section>
```

在上述摘要行后按宿主放置明确的编辑容器：

- Word：`details#provider-url-details` 内保留 `input#provider-base-url`、`button#btn-save-provider-url`、`button#btn-cancel-provider-url`；移除可见 `summary` 触发文字，改由 `btn-edit-provider-url` 设置 `open`。
- Excel：把 `div#provider-edit-view` 放入 `provider-summary-card`，保留 `input#provider-base-url`、`button#btn-save-provider-url`、`button#btn-back-provider-summary`，将后者显示文字改为“取消”；把原 `btn-edit-provider` 重命名为 `btn-edit-provider-url`。
- PPT：把现有 `div#provider-url-editor` 放入 `provider-summary-card`，保留 `input#provider-base-url`、`button#btn-save-provider-url`、`button#btn-cancel-provider-url`。

删除三个宿主的常驻 `btn-refresh`，并在后续 JavaScript 任务中删除对应事件绑定。

- [ ] **Step 4: 统一工作流标题、提示层和任务选项卡**

三个宿主的工作流标题区统一加入：

```html
<div class="workflow-settings-heading">
  <h4>工作流设置</h4>
  <button id="workflow-help-button" class="info-button" type="button"
    aria-label="查看多工作流说明" aria-expanded="false"
    aria-controls="workflow-help-popover">i</button>
  <div id="workflow-help-popover" class="workflow-help-popover" role="tooltip" hidden>
    每项任务可保存多个工作流，可在任务页选择当前使用的工作流。
  </div>
</div>
```

Word 保留四个现有 tab 按钮；Excel 增加：

```html
<div id="workflow-task-tabs" class="workflow-task-tabs" role="tablist" aria-label="Excel 任务">
  <button type="button" role="tab" aria-selected="true"
    data-workflow-task-tab="excel.analysis">智能分析</button>
</div>
```

PPT 增加：

```html
<div id="workflow-task-tabs" class="workflow-task-tabs" role="tablist" aria-label="PPT 任务">
  <button type="button" role="tab" aria-selected="true"
    data-workflow-task-tab="ppt.slide_assistant">智能总结</button>
</div>
```

- [ ] **Step 5: 将诊断合并为默认折叠的披露区**

三个宿主统一保留已有诊断内容 ID，将外层改为：

```html
<details id="diagnostics-disclosure" class="advanced-diagnostics">
  <summary aria-controls="diagnostics-section">
    <span>高级诊断</span>
    <span id="diagnostics-summary" class="inline-status">按需查看</span>
  </summary>
  <div id="diagnostics-section" class="advanced-diagnostics-content">
  </div>
</details>
```

Word 和 Excel 在 `diagnostics-section` 内移动现有四项 `diag-grid`，完整保留 `trace-line`、`settings-scope-line`、`provider-line`、`frontend-version-line`；随后移动 `last-task-diagnostics-card`，完整保留 `btn-refresh-diagnostics`、`btn-copy-diagnostics` 和 `last-task-diagnostics-output`。PPT 在 `diagnostics-section` 内放置 `btn-refresh-diagnostics`、`btn-copy-diagnostics` 和 `pre#diagnostics-output`。不要修改任何诊断字段的脱敏数据来源。

- [ ] **Step 6: 运行结构与既有工作流测试**

Run:

```bash
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node formal-plugin-kit/tests/workflow-settings-integration.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: 新结构测试通过；既有测试若只因旧结构断言失败，应在本任务内把断言更新为新的统一结构，不删除工作流隔离、编辑器和诊断能力断言。

- [ ] **Step 7: 提交统一 HTML 结构**

```bash
git add formal-plugin-kit/tests/taskpane-experience-contract.test.js formal-plugin-kit/tests/workflow-settings-integration.test.js formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html
git commit -m "feat: unify three-host settings structure"
```

### Task 3: 应用克制型 Apple 视觉与交互样式

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-experience-contract.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`

- [ ] **Step 1: 增加 CSS 合同失败断言**

在新契约测试的 host 循环中读取 CSS 并增加：

```javascript
[
  ".model-interface-card",
  ".readiness-badge",
  ".workflow-settings-heading",
  ".workflow-help-popover",
  ".workflow-task-tabs",
  ".advanced-diagnostics",
  ":focus-visible",
  ":active",
  "@media (prefers-reduced-motion: reduce)"
].forEach((marker) => assert.ok(css.includes(marker), `${host.dir} missing CSS ${marker}`));
assert.ok(!css.includes("backdrop-filter"), `${host.dir} must not use expensive glass blur`);
```

- [ ] **Step 2: 运行契约测试并确认 CSS 标记失败**

Run:

```bash
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
```

Expected: FAIL，提示缺少 `.model-interface-card` 或 `.advanced-diagnostics`。

- [ ] **Step 3: 在三份 CSS 中加入相同结构规则**

将以下规则加入三个宿主 CSS；继续使用各文件已有 `--host-accent`、`--host-accent-soft` 或对应宿主色变量，不硬编码另一个宿主的颜色：

```css
:root {
  --host-accent: var(--color-primary);
  --host-accent-soft: var(--color-surface-muted);
  --border-color: var(--color-border);
}

.model-interface-card,
.workflow-settings-card,
.advanced-diagnostics {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fff;
}

.model-interface-heading,
.model-interface-row,
.workflow-settings-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.provider-url-summary {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.readiness-badge {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 12px;
  line-height: 18px;
}

.readiness-badge.is-ready { color: #176b3a; background: #e9f6ee; }
.readiness-badge.is-partial { color: #8a5a00; background: #fff4d6; }
.readiness-badge.is-unconfigured,
.readiness-badge.is-unavailable { color: #6b7280; background: #f1f3f5; }

.workflow-settings-heading { position: relative; }
.info-button {
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 50%;
}
.workflow-help-popover {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  right: 0;
  width: min(260px, calc(100vw - 40px));
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
}

.workflow-task-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: thin;
  scroll-behavior: smooth;
}
.workflow-task-tabs button { flex: 0 0 auto; white-space: nowrap; }
.workflow-task-tabs button[aria-selected="true"],
.workflow-task-tabs button.active {
  color: var(--host-accent);
  border-color: var(--host-accent);
  background: var(--host-accent-soft);
}

.advanced-diagnostics > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 12px;
  cursor: pointer;
  list-style: none;
}
.advanced-diagnostics-content {
  padding: 0 12px 12px;
  animation: disclosure-in 160ms ease-out;
}

button,
[role="tab"],
summary {
  transition: background-color 140ms ease, border-color 140ms ease,
    color 140ms ease, opacity 140ms ease, transform 100ms ease;
}
button:active:not(:disabled) { transform: scale(0.98); }
button:focus-visible,
[role="tab"]:focus-visible,
summary:focus-visible {
  outline: 2px solid var(--host-accent);
  outline-offset: 2px;
}

@keyframes disclosure-in {
  from { opacity: 0; transform: translateY(-2px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
```

三个文件现有变量均支持上述映射：Word `--color-primary: #2f6db3`，Excel `--color-primary: #237a4b`，PPT `--color-primary: #b95720`；浅色背景均来自各自 `--color-surface-muted`。移除或覆盖大于 8px 的设置卡片圆角、嵌套卡片阴影和会改变布局尺寸的 hover 规则；不得改变任务结果正文的排版语义。

- [ ] **Step 4: 增加窄视口稳定规则**

在三个 CSS 的 `max-width: 420px` 区域加入：

```css
.model-interface-row,
.workflow-settings-toolbar,
.workflow-profile-list-row {
  align-items: flex-start;
}
.workflow-profile-actions { flex-wrap: wrap; }
.workflow-help-popover { right: -4px; }
.diagnostics-actions { display: flex; flex-wrap: wrap; }
```

不要缩放字体，不使用负字距，不让状态徽标覆盖标题。

- [ ] **Step 5: 运行视觉契约和布局测试**

Run:

```bash
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: PASS；三个宿主仍分别通过既有蓝、绿、橙主题断言，主生成按钮仍无图标伪元素。

- [ ] **Step 6: 提交统一样式**

```bash
git add formal-plugin-kit/tests/taskpane-experience-contract.test.js formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css
git commit -m "feat: apply restrained taskpane interaction styling"
```

### Task 4: 接入 Word 实时状态与渐进披露行为

**Files:**
- Modify: `formal-plugin-kit/tests/workflow-settings-word.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js:180-220, 323-365, 673-780, 1251-1320, 1530-1660, 3456-3495, 4080-4295`

- [ ] **Step 1: 写 Word 行为失败测试**

在 `workflow-settings-word.test.js` 中增加源码合同：

```javascript
const refreshConfig = functionSource("refreshConfig");
const renderManager = functionSource("renderWorkflowProfileManager");
assert.ok(js.includes("settingsRefreshController"));
assert.ok(js.includes("configRefreshRequestId"));
assert.ok(js.includes("deriveModelInterfaceState"));
assert.ok(js.includes("document.visibilityState"));
assert.ok(js.includes('byId("diagnostics-disclosure").addEventListener("toggle"'));
assert.ok(js.includes('byId("workflow-help-button").addEventListener("click"'));
assert.ok(js.includes('byId("workflow-task-tabs").addEventListener("keydown"'));
assert.ok(!refreshConfig.includes("health.data.providerConfigured"));
assert.ok(!refreshConfig.includes("refreshDiagnostics()"));
assert.ok(!renderManager.includes('profile.note || "暂无备注"'));
assert.ok(renderManager.includes("profile.note ?"));
```

在 `layout-smoke.test.js` 中把旧 `btn-refresh` 断言改为不存在，并要求 Word 存在 readiness、help、disclosure 三个 ID。

- [ ] **Step 2: 运行 Word 测试并确认失败**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-word.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL，原因是 Word 尚未声明 `settingsRefreshController` 或仍调用 `providerConfigured`。

- [ ] **Step 3: 增加 Word 设置状态和刷新控制器**

在 `state` 中加入：

```javascript
configRefreshRequestId: 0,
modelInterfaceDetectable: false,
settingsRefreshController: null,
```

加入以下函数，并使用 Word 四个 `TASK_API_KEY_DEFS` 任务类型：

```javascript
function renderModelInterfaceState(detectable) {
  var profilesByTask = {};
  var taskTypes = TASK_API_KEY_DEFS.map(function (item) { return item.taskType; });
  taskTypes.forEach(function (taskType) {
    profilesByTask[taskType] = getWorkflowProfileData(taskType);
  });
  var result = helpers.deriveModelInterfaceState({
    detectable: detectable,
    providerBaseUrl: state.providerBaseUrl,
    taskTypes: taskTypes,
    profilesByTask: profilesByTask
  });
  var badge = byId("provider-readiness-badge");
  badge.className = "readiness-badge is-" + result.code;
  badge.textContent = result.label;
  byId("provider-summary-url").title = state.providerBaseUrl || "未配置接口地址";
  byId("diagnostics-summary").textContent = result.label;
}

function syncSettingsRefreshLifecycle() {
  var settingsVisible = byId("settings-view").classList.contains("active") &&
    document.visibilityState !== "hidden" && state.knowledgeView === "home" &&
    !state.workflowProfileEditor;
  if (settingsVisible) {
    state.settingsRefreshController.start();
  } else {
    state.settingsRefreshController.stop();
  }
}
```

初始化时创建控制器：

```javascript
state.settingsRefreshController = helpers.createSettingsRefreshController({
  intervalMs: 30000,
  refresh: refreshConfig
});
```

在 `switchView()`、工作流编辑器打开/关闭和 `setKnowledgeView()` 完成后调用 `syncSettingsRefreshLifecycle()`；绑定 `visibilitychange` 后再次同步。

- [ ] **Step 4: 改写 Word `refreshConfig()` 的顺序保护和就绪度计算**

每次刷新先递增 `configRefreshRequestId`，仅最新请求更新状态：

```javascript
function refreshConfig() {
  var requestId = state.configRefreshRequestId + 1;
  state.configRefreshRequestId = requestId;
  return request("/health").then(function (health) {
    return Promise.all([
      Promise.resolve(health),
      readAdapterJson("/templates"),
      readAdapterJson("/config")
    ]);
  }).then(function (results) {
    if (requestId !== state.configRefreshRequestId) {
      return null;
    }
    var health = results[0];
    var templates = results[1];
    var config = results[2];
    setHealthBadge("badge-ok", "已连接");
    setTrace(health.traceId || "");
    setProviderLine(health.data.providerType || "未检测");
    if (config.success === false) {
      applyProviderConfig({
        providerName: health.data.providerName || "企业大模型接口",
        providerBaseUrl: state.providerBaseUrl
      });
      setResult("当前适配服务版本较旧或缺少 /config 接口，请使用新版 adapter-start-kit 后再保存模型配置。\n后台返回：" + config.errors[0].message);
    } else {
      applyProviderConfig(config.data || {});
    }
    resolveSelectionScope(false);
    if (templates.success === false) {
      renderFallbackTemplateOptions();
    } else {
      state.templates = mergeTemplates(templates.data.templates || []);
      renderTemplateOptions();
    }
    return refreshAllWorkflowProfiles().then(function () {
      if (requestId !== state.configRefreshRequestId) {
        return null;
      }
      state.modelInterfaceDetectable = true;
      renderModelInterfaceState(true);
      setStatus("就绪");
      return null;
    });
  }).catch(function (error) {
    if (requestId !== state.configRefreshRequestId) {
      return null;
    }
    state.modelInterfaceDetectable = false;
    renderModelInterfaceState(false);
    setAdapterUnavailableState(error);
    return null;
  });
}
```

删除 `refreshConfig()` 末尾的 `refreshDiagnostics()`。URL 保存、工作流创建、Key 更新、激活或删除完成并重新加载档案后调用 `renderModelInterfaceState(true)`；不发起真实模型请求。

- [ ] **Step 5: 实现 Word 备注省略、提示层、选项卡键盘和诊断披露**

把工作流备注渲染改为条件拼接：

```javascript
rows.push('<div class="workflow-profile-summary"><strong>' + escapeWorkflowText(profile.name) + '</strong>');
if (profile.note) {
  rows.push('<span class="workflow-profile-note">' + escapeWorkflowText(profile.note) + '</span>');
}
rows.push('</div>');
```

新增 `setWorkflowHelpOpen(open)`，同步 `hidden` 与 `aria-expanded`；绑定按钮 click、图标 hover/focus、文档外部 click 和 `Escape`。新增 `handleWorkflowTaskTabKeydown(event)`，按 `ArrowLeft/ArrowRight/Home/End` 计算目标 tab，触发点击并调用：

```javascript
target.focus();
target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
```

诊断披露绑定：

```javascript
byId("diagnostics-disclosure").addEventListener("toggle", function (event) {
  if (event.currentTarget.open) {
    refreshDiagnostics();
  }
});
```

重新进入设置首页前设置 `byId("diagnostics-disclosure").open = false`。删除 `btn-refresh` 事件绑定，保留展开区内的诊断刷新和复制。

- [ ] **Step 6: 运行 Word 测试与语法检查**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-word.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/enterprise-knowledge-word.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

Expected: 全部 PASS；企业知识测试确认 Word 设置下钻和 fail-open 相关前端合同没有回归。

- [ ] **Step 7: 提交 Word 行为**

```bash
git add formal-plugin-kit/tests/workflow-settings-word.test.js formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
git commit -m "feat: refresh Word model settings state"
```

### Task 5: 接入 Excel 同构设置体验

**Files:**
- Modify: `formal-plugin-kit/tests/workflow-settings-excel.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js:940-975, 1402-1438, 1547-1640`

- [ ] **Step 1: 写 Excel 行为失败测试**

增加与 Word 同义、Excel 专用的源码断言：

```javascript
const refreshConfig = functionSource("refreshConfig");
const renderManager = functionSource("renderWorkflowProfileManager");
assert.ok(js.includes("settingsRefreshController"));
assert.ok(js.includes("configRefreshRequestId"));
assert.ok(js.includes('taskTypes: [EXCEL_WORKFLOW_TASK_TYPE]'));
assert.ok(js.includes('byId("workflow-task-tabs").addEventListener("keydown"'));
assert.ok(js.includes('byId("diagnostics-disclosure").addEventListener("toggle"'));
assert.ok(!refreshConfig.includes("healthData.providerConfigured"));
assert.ok(!refreshConfig.includes("refreshDiagnostics()"));
assert.ok(!renderManager.includes('profile.note || "无备注"'));
```

- [ ] **Step 2: 运行 Excel 测试并确认失败**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-excel.test.js
```

Expected: FAIL，提示缺少刷新控制器或仍使用旧 `providerConfigured`。

- [ ] **Step 3: 接入 Excel 单任务就绪度和可见刷新**

加入与 Word 同名的 `renderModelInterfaceState()`，输入固定为：

```javascript
var profilesByTask = {};
profilesByTask[EXCEL_WORKFLOW_TASK_TYPE] = getWorkflowProfileData();
var result = helpers.deriveModelInterfaceState({
  detectable: detectable,
  providerBaseUrl: state.providerBaseUrl,
  taskTypes: [EXCEL_WORKFLOW_TASK_TYPE],
  profilesByTask: profilesByTask
});
```

加入 `configRefreshRequestId` 和 `settingsRefreshController`，进入设置首页且页面可见时启动，返回智能分析或进入工作流编辑器时停止。`refreshConfig()` 使用请求序号，移除 `healthData.providerConfigured` 和自动 `refreshDiagnostics()`；URL 或档案变更后重新计算状态。

- [ ] **Step 4: 接入 Excel 提示、单 tab 键盘和高级诊断**

为 `workflow-help-button` 使用与 Word 相同的打开/关闭合同。Excel 当前只有一个 tab，方向键、`Home`、`End` 均保持焦点在该项，不触发额外请求。高级诊断只在 `diagnostics-disclosure.open` 从 false 变为 true 时刷新；重新进入设置默认折叠。

Excel 工作流备注改为：

```javascript
var noteHtml = profile.note
  ? '<p class="workflow-profile-note">' + escapeWorkflowText(profile.note) + '</p>'
  : "";
```

将 `noteHtml` 拼入现有列表行，不保留“无备注”或空段落。

- [ ] **Step 5: 运行 Excel 测试与语法检查**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-excel.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
```

Expected: 全部 PASS；即时工作流切换、删除确认、任务提交忙碌保护断言继续通过。

- [ ] **Step 6: 提交 Excel 行为**

```bash
git add formal-plugin-kit/tests/workflow-settings-excel.test.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
git commit -m "feat: align Excel settings interactions"
```

### Task 6: 接入 PPT 同构设置体验

**Files:**
- Modify: `formal-plugin-kit/tests/workflow-settings-ppt.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js:881-1010, 1202-1255, 1298-1450`

- [ ] **Step 1: 写 PPT 行为失败测试**

增加 PPT 源码合同：

```javascript
const refreshSettings = functionSource("refreshSettings");
const renderManager = functionSource("renderProfileManager");
assert.ok(js.includes("settingsRefreshController"));
assert.ok(js.includes("configRefreshRequestId"));
assert.ok(js.includes("deriveModelInterfaceState"));
assert.ok(js.includes('taskTypes: [PPT_WORKFLOW_TASK_TYPE]'));
assert.ok(js.includes('byId("workflow-task-tabs").addEventListener("keydown"'));
assert.ok(js.includes('byId("diagnostics-disclosure").addEventListener("toggle"'));
assert.ok(!refreshSettings.includes("refreshDiagnostics()"));
assert.ok(!renderManager.includes('profile.note || "无备注"'));
```

- [ ] **Step 2: 运行 PPT 测试并确认失败**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-ppt.test.js
```

Expected: FAIL，提示缺少设置刷新控制器或 `refreshSettings()` 仍自动刷新诊断。

- [ ] **Step 3: 将 PPT `refreshSettings()` 改为统一状态刷新**

保持 PPT 的 `checkHealth()` 只负责右上角“已连接/未连接”。设置刷新并行读取 `/config` 和 `loadProfiles()`，用 `configRefreshRequestId` 防止旧响应覆盖，并按单任务输入计算就绪度：

```javascript
function renderModelInterfaceState(detectable) {
  var profilesByTask = {};
  profilesByTask[PPT_WORKFLOW_TASK_TYPE] = state.profiles;
  var result = helpers.deriveModelInterfaceState({
    detectable: detectable,
    providerBaseUrl: state.providerBaseUrl,
    taskTypes: [PPT_WORKFLOW_TASK_TYPE],
    profilesByTask: profilesByTask
  });
  var badge = byId("provider-readiness-badge");
  badge.className = "readiness-badge is-" + result.code;
  badge.textContent = result.label;
  byId("diagnostics-summary").textContent = result.label;
}
```

`refreshSettings()` 不再调用 `refreshDiagnostics()`。进入设置且 `document.visibilityState !== "hidden"` 时启动 30 秒刷新；返回智能总结或打开工作流编辑器时停止。URL 保存和 profile 增删改切换后立即刷新就绪度。

- [ ] **Step 4: 接入 PPT 备注省略、提示、单 tab 和诊断披露**

PPT `renderProfileManager()` 使用与 Excel 相同的条件 `noteHtml`，不渲染“无备注”。为信息提示、单任务 tab 键盘和诊断 `<details>` 绑定与 Word 相同的开关合同。复制诊断仍调用现有 `copyText(state.diagnosticsText, ...)`，不改变诊断 JSON 内容。

- [ ] **Step 5: 运行 PPT 测试与语法检查**

Run:

```bash
node formal-plugin-kit/tests/workflow-settings-ppt.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: 全部 PASS；PPT 当前页总结、文档总结、文件校验和未完成任务恢复的既有 helper 测试继续通过。

- [ ] **Step 6: 提交 PPT 行为**

```bash
git add formal-plugin-kit/tests/workflow-settings-ppt.test.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
git commit -m "feat: align PPT settings interactions"
```

### Task 7: 全量回归、视觉验收与交接更新

**Files:**
- Modify: `docs/codex-handoff.md`
- Verify only: 三宿主 HTML/CSS/JS 与全部前端测试

- [ ] **Step 1: 运行全部前端测试**

Run each command independently:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node formal-plugin-kit/tests/workflow-settings-word.test.js
node formal-plugin-kit/tests/workflow-settings-excel.test.js
node formal-plugin-kit/tests/workflow-settings-ppt.test.js
node formal-plugin-kit/tests/workflow-settings-integration.test.js
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/enterprise-knowledge-word.test.js
```

Expected: 九个命令均退出码 `0`，没有跳过既有业务断言。

- [ ] **Step 2: 运行三个 JavaScript 语法检查**

```bash
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
```

Expected: 六个命令均无输出并退出码 `0`。

- [ ] **Step 3: 启动静态服务器并执行桌面/窄窗视觉检查**

Run:

```bash
python3 -m http.server 4173 --directory formal-plugin-kit
```

使用 Playwright 分别打开：

```text
http://127.0.0.1:4173/wps-ai-assistant_1.0.0/taskpane.html?mode=settings
http://127.0.0.1:4173/wps-ai-assistant-et_1.0.0/taskpane.html?mode=settings
http://127.0.0.1:4173/wps-ai-assistant-wpp_1.0.0/taskpane.html?mode=settings
```

在 `420x900` 和 `320x700` 两种视口截图并验证：

- Word 蓝、Excel 绿、PPT 橙未改变。
- 顶部标题、设置/返回和“已连接”区域不重叠。
- 模型接口始终为两行，长 URL 省略且“修改”可见。
- Word 四 tab 可横向滚动；Excel/PPT 只显示当前真实功能 tab。
- 信息提示在视口内，鼠标、键盘和 `Esc` 均可关闭。
- 高级诊断默认折叠，展开后刷新/复制可见，再次进入设置恢复折叠。
- 无备注档案不产生空白备注行。
- 开启 `prefers-reduced-motion: reduce` 后没有可感知持续动画。
- 任务页主按钮、输入区、结果区和原业务操作无布局遮挡。

静态环境无法验证真实 adapter 状态时，只验收“无法检测”布局；真实“已就绪/部分就绪/未配置”在本地 adapter 或目标机回归中验证。

- [ ] **Step 4: 在有 adapter 的本地环境验证状态和业务保护**

按宿主分别建立以下配置并观察状态：

1. URL 缺失：未配置。
2. URL 存在、当前工作流无 Key：未配置。
3. Word 只有部分任务当前工作流有 Key：部分就绪并显示 `n/4`。
4. 当前宿主所有任务当前工作流有 Key：已就绪。
5. adapter 停止：顶部未连接，模型接口无法检测。
6. 备用工作流有 Key、当前工作流无 Key：仍为未配置。

随后各提交一次现有任务：Word 智能编写或文档审查、Excel 智能分析、PPT 智能总结。确认请求路径、长任务恢复、结果预览、复制和 Word 回写行为与修改前一致。

- [ ] **Step 5: 更新交接文档**

在 `docs/codex-handoff.md` 的当前版本关键变化加入：

```markdown
- 三宿主任务页和设置页采用克制型 Apple 交互原则：保持 Word 蓝、Excel 绿、PPT 橙，统一系统字体、8px 以内圆角、即时按压反馈、短促披露动效和键盘焦点；未引入毛玻璃、弹簧动画或新依赖。
- 设置页模型接口状态改为按当前宿主各任务当前激活工作流计算“已就绪 / 部分就绪 / 未配置 / 无法检测”，进入设置、配置变更和页面可见期间每 30 秒自动刷新，备用工作流及统一 Key 回退不计入用户可见就绪度。
- 三宿主统一使用可扩展任务选项卡、悬浮信息说明和默认折叠高级诊断；无备注工作流不再显示占位文案，Excel/PPT 当前只显示已交付的智能分析/智能总结选项卡。
- 本次只调整前端结构、状态反馈和可访问性，不改变模型请求、长任务轮询、结果解析、企业知识、复制、预览或 Word 回写逻辑。
```

同时在“需要重点保护的既有逻辑”中增加本地连接状态与模型接口就绪度不得混用的说明。

- [ ] **Step 6: 检查最终差异和历史脏文件隔离**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: 没有空白错误；本次变更只包含计划列出的正式插件、测试和交接文档。`dist-phase1-delivery-kit` 的历史删除、修改和未跟踪压缩包保持未暂存，不得纳入提交。

- [ ] **Step 7: 提交交接文档和最终验证修正**

```bash
git add docs/codex-handoff.md formal-plugin-kit/tests/taskpane-helpers.test.js formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/tests/workflow-settings-word.test.js formal-plugin-kit/tests/workflow-settings-excel.test.js formal-plugin-kit/tests/workflow-settings-ppt.test.js formal-plugin-kit/tests/workflow-settings-integration.test.js formal-plugin-kit/tests/taskpane-experience-contract.test.js formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/tests/enterprise-knowledge-word.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
git diff --cached --name-status
git commit -m "docs: record three-host taskpane experience update"
```

暂存检查必须确认没有 `dist-phase1-delivery-kit` 文件。如果视觉验收产生截图，截图保存在临时目录，不提交仓库。

## 实施完成定义

- 三宿主模型接口状态不再依赖 `/health.providerConfigured`。
- 只有当前激活工作流参与就绪度计算。
- 设置可见期间刷新控制器只存在一个定时器，离开后停止。
- 工作流提示、选项卡和高级诊断具有完整鼠标与键盘行为。
- Word、Excel、PPT 设置结构一致，只展示各自真实功能和数据。
- 任务界面使用相同视觉反馈，原业务状态、长任务、结果和回写路径保持不变。
- 自动测试、语法检查、两种视口和真实 adapter 状态验证全部通过。
- 历史交付包改动未被暂存、提交或删除。
