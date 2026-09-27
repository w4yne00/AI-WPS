# Excel：确认后向空白区域写入台账实施计划 (Issue #237)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Excel 插件实现从资料生成的台账结果受控写入工作表空白区域的能力，包含严格空白预检、防公式注入、缺项物理留空、逐格写入与回读验证、异常回滚补偿、用户确认弹窗以及授权范围外数据保护。

**Architecture:** 
- 在 `taskpane-helpers.js` 中新增纯函数辅助模块，负责目标区域计算、逐格只读安全与空白预检、防公式注入转义、逐格写入回读校验以及逆序补偿回滚；
- 在 `material-ledger.js` 状态控制器中集成选区检测、写入参数管理、确认调用与部分写入状态跟踪；
- 在 `taskpane.html` 与 `taskpane.js` 中构建目标位置卡片、表头行包含开关、模态确认流及状态反馈，绑定工作簿/工作表切换生命周期；
- 在 `formal-plugin-kit/tests/excel-material-ledger.test.js` 中建立完备契约测试。

**Tech Stack:** JavaScript (ES5/ES6 兼容，遵循 WPS JSAPI 环境), Node.js (内置 `node:test` 运行器), HTML5/CSS3。

**Spec:** `docs/superpowers/specs/2026-09-27-issue-237-excel-material-write-ledger-design.md`

## Global Constraints

- 纯新增只写空白：目标矩形内任一单元格含有非空数据、公式、合并或隐藏，一律 fail-closed 拦截，严禁覆盖任何已有数据；
- 会话一致性锁定：写入前必须复核当前 `ActiveWorkbook` 的会话标识与生成台账所属的 `documentSessionId` 严格一致，切换工作簿立即拒绝；
- 绝对防公式执行：所有提取文本若以 `=+\-@` 开头，强制添加前缀 `'` 纯文本存储；
- 缺项物理空白：缺项或空值字段写入严格赋值为空字符串 `""`，保持单元格物理空白，不写入任何伪造文本或占位符；
- 失败补偿回滚：写入中途异常时逆序清空已写入单元格；若有单元格无法恢复，明确抛出 `COMPENSATION_FAILED` 并列出需人工核对的地址列表；
- 授权范围保护：授权目标范围之外的单元格数值、公式和格式严格保持不变。

## Review Focus

1. **单单元格选区溢出边界**：选中右下角极限区域（如列号或行号超出工作表最大上限）时的边界保护与友好报错；
2. **公式单元格伪装成空白**：单元格公式计算结果为 `""`（但 `HasFormula === true`），严格拦截不可视为纯空白覆盖；
3. **部分写入残留下的重试**：当发生部分写入且无法全部回滚时，用户再次点击写入，预检必须正确拦截并拒绝覆盖残留数据；
4. **长文本超出单元格上限**：单单元格文本过长时的安全校验与报错处理；
5. **用户取消确认弹窗**：用户点击确认框中的“取消”时，单元格写入次数严格为 0，且不破坏现有预览与选区状态。

---

### Task 1: 目标范围计算与空白预检辅助函数

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`

**Interfaces:**
- Produces:
  - `resolveExcelLedgerTargetRange(app, rowCount, colCount, options)`: 返回 `{ startRow, startCol, endRow, endCol, rowCount, colCount, targetAddress, sheetName }`
  - `validateExcelLedgerTargetBlank(app, targetRangeInfo, options)`: 返回 `{ valid: true, cells: [...] }` 或抛出带有明确原因的 `Error`

- [ ] **Step 1: Write the failing tests for range calculation and blank pre-flight validation**

在 `formal-plugin-kit/tests/excel-material-ledger.test.js` 中新增用例组：
```javascript
test("resolveExcelLedgerTargetRange calculates bounding box for single-cell selection", () => {
  const app = createMockEtApp({ selection: { Row: 2, Column: 1, Rows: { Count: 1 }, Columns: { Count: 1 } }, activeSheet: { Name: "Sheet1" } });
  const rangeInfo = helpers.resolveExcelLedgerTargetRange(app, 5, 4);
  assert.strictEqual(rangeInfo.startRow, 2);
  assert.strictEqual(rangeInfo.startCol, 1);
  assert.strictEqual(rangeInfo.endRow, 6);
  assert.strictEqual(rangeInfo.endCol, 4);
  assert.strictEqual(rangeInfo.targetAddress, "A2:D6");
});

test("validateExcelLedgerTargetBlank rejects non-blank cells, formulas, and merged cells", () => {
  const app = createMockEtApp({
    cells: {
      "2,2": { Value2: "已有数据" }
    }
  });
  const rangeInfo = { startRow: 2, startCol: 1, endRow: 4, endCol: 3, targetAddress: "A2:C4", sheetName: "Sheet1" };
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(app, rangeInfo);
  }, /目标区域包含已有数据/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: FAIL with `helpers.resolveExcelLedgerTargetRange is not a function`

- [ ] **Step 3: Implement minimal code for range calculation and blank pre-flight in `taskpane-helpers.js`**

实现 `resolveExcelLedgerTargetRange` 与 `validateExcelLedgerTargetBlank`：
- 计算 A1 地址工具函数；
- 逐格检查 `Value2`、`Value`、`HasFormula`、`Formula`、`MergeCells`、`Hidden`；
- 会话一致性检查；
- 导出至 `WpsAiAssistantHelpers`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/tests/excel-material-ledger.test.js
git commit -m "feat(excel): add target range resolution and blank pre-flight validation helpers"
```

---

### Task 2: 数据安全转义、受控写入管道与补偿回滚

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`

**Interfaces:**
- Produces:
  - `sanitizeExcelLedgerCellValue(val)`: 返回转义字符串（对 `=+\-@` 开头添加 `'`，空值返回 `""`）
  - `writeExcelMaterialLedger(app, result, options)`: 返回 `{ success: true, writtenCount, targetAddress, sheetName, includeHeaders }` 或抛出带 `code` 的补偿异常

- [ ] **Step 1: Write the failing tests for sanitization, write execution, and rollback compensation**

在 `formal-plugin-kit/tests/excel-material-ledger.test.js` 中新增用例：
```javascript
test("sanitizeExcelLedgerCellValue escapes formulas and keeps missing fields blank", () => {
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue("=SUM(A1)"), "'=SUM(A1)");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue("+123"), "'+123");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue("-cmd"), "'-cmd");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue("@macro"), "'@macro");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(""), "");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(null), "");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(undefined), "");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue("正常文本"), "正常文本");
});

test("writeExcelMaterialLedger rolls back on mid-write failure", () => {
  const app = createMockEtAppWithFailureAtCell("3,2");
  const result = {
    headers: ["工作事项", "责任部门"],
    rows: [
      { values: { "工作事项": "任务1", "责任部门": "部门1" }, missingFields: [] },
      { values: { "工作事项": "任务2", "责任部门": "部门2" }, missingFields: [] }
    ]
  };
  assert.throws(() => {
    helpers.writeExcelMaterialLedger(app, result, { startRow: 2, startCol: 1, includeHeaders: true });
  }, (err) => {
    return err.code === "COMPENSATION_SUCCEEDED" || err.code === "COMPENSATION_FAILED";
  });
  // 验证第一行写入的单元格已被回滚清空
  assert.strictEqual(app.getCellValue(2, 1), "");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: FAIL with `helpers.sanitizeExcelLedgerCellValue is not a function`

- [ ] **Step 3: Implement minimal code for sanitization, write pipeline, and compensation rollback**

在 `taskpane-helpers.js` 中：
- 实现 `sanitizeExcelLedgerCellValue`；
- 实现 `writeExcelMaterialLedger`：
  - 构造 `writePlans` 包含表头（可选）及数据行；
  - 记录 `writtenList`；
  - 赋值 `cell.Value2 = sanitized`；
  - 回读核对；
  - `catch` 异常中逆序清空，若有未清空项报 `COMPENSATION_FAILED` 否则报 `COMPENSATION_SUCCEEDED`；
- 导出方法。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/tests/excel-material-ledger.test.js
git commit -m "feat(excel): add data sanitization, controlled write pipeline and rollback compensation"
```

---

### Task 3: Material Ledger 状态控制器集成

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/material-ledger.js`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`

**Interfaces:**
- Modifies: `createMaterialLedger` 返回对象，新增：
  - `setIncludeHeaders(bool)`
  - `inspectTargetRange(app)`
  - `writeToSheet(app, options)`
- State added:
  - `includeHeaders`: boolean (default `true`)
  - `targetRangeInfo`: null or object
  - `writeStatus`: string
  - `writeError`: string
  - `partialWriteAddresses`: array

- [ ] **Step 1: Write the failing tests for ledger controller target inspection and write action**

在 `formal-plugin-kit/tests/excel-material-ledger.test.js` 中新增用例：
```javascript
test("ledger controller inspects target range and updates state", async () => {
  const ledger = createMaterialLedger();
  ledger.setResult({
    headers: ["工作事项", "责任部门"],
    rows: [{ values: { "工作事项": "任务1", "责任部门": "技术部" }, missingFields: [] }]
  });
  const app = createMockEtApp();
  const info = ledger.inspectTargetRange(app);
  assert.ok(info.targetAddress);
  assert.strictEqual(ledger.getState().includeHeaders, true);
});

test("ledger controller writeToSheet writes to sheet and updates writeResult", async () => {
  const ledger = createMaterialLedger();
  ledger.setResult({
    headers: ["工作事项", "责任部门"],
    rows: [{ values: { "工作事项": "任务1", "责任部门": "技术部" }, missingFields: [] }]
  });
  const app = createMockEtApp();
  const report = await ledger.writeToSheet(app);
  assert.strictEqual(report.success, true);
  assert.strictEqual(ledger.getState().writeStatus, "success");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: FAIL with `ledger.inspectTargetRange is not a function`

- [ ] **Step 3: Implement minimal controller methods in `material-ledger.js`**

在 `createMaterialLedger` 中：
- 初始化 `includeHeaders: true`、`targetRangeInfo: null`、`writeStatus: ""`、`writeError: ""`、`partialWriteAddresses: []`；
- 实现 `setIncludeHeaders`；
- 实现 `inspectTargetRange`：调用 `helpers.resolveExcelLedgerTargetRange` 与 `helpers.validateExcelLedgerTargetBlank`，更新 `state.targetRangeInfo`；
- 实现 `writeToSheet`：检查 `state.status === 'completed'`，调用 `helpers.writeExcelMaterialLedger`，处理异常及状态通知。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/material-ledger.js formal-plugin-kit/tests/excel-material-ledger.test.js
git commit -m "feat(excel): integrate target range inspection and write action into material ledger controller"
```

---

### Task 4: 任务窗格 HTML 结构、CSS 样式与交互确认绑定

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`

**Interfaces:**
- HTML Elements:
  - `#ledger-write-section`
  - `#ledger-target-summary`
  - `#ledger-target-validation`
  - `#btn-refresh-ledger-target`
  - `#ledger-include-headers-toggle`
  - `#btn-write-ledger`
  - `#ledger-write-status`

- [ ] **Step 1: Write the failing tests for taskpane UI elements and confirmation dialog handling**

在 `formal-plugin-kit/tests/excel-material-ledger.test.js` 中新增窗格 DOM 渲染与事件交互用例：
```javascript
test("taskpane renders ledger write section on completed result and handles confirmation", async () => {
  const fixture = setupLedgerTaskpaneFixture();
  fixture.ledger.setResult({
    headers: ["工作事项", "责任部门"],
    rows: [{ values: { "工作事项": "任务1", "责任部门": "技术部" }, missingFields: [] }]
  });
  // 验证写入控制区可见
  const writeSection = fixture.document.getElementById("ledger-write-section");
  assert.strictEqual(writeSection.hidden, false);
  const btnWrite = fixture.document.getElementById("btn-write-ledger");
  assert.ok(btnWrite);

  // 用户点击取消确认弹窗时，写入次数为 0
  fixture.window.confirm = () => false;
  btnWrite.click();
  assert.strictEqual(fixture.app.getWriteCount(), 0);

  // 用户点击确认弹窗时，执行写入
  fixture.window.confirm = () => true;
  await btnWrite.click();
  assert.ok(fixture.app.getWriteCount() > 0);
  assert.ok(fixture.document.getElementById("ledger-write-status").textContent.includes("成功"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: FAIL with missing DOM elements `#ledger-write-section`

- [ ] **Step 3: Update `taskpane.html`, `taskpane.css`, and `taskpane.js`**

- 在 `taskpane.html` 中添加 `#ledger-write-section` 及其子元素；
- 在 `taskpane.css` 中添加相应样式；
- 在 `taskpane.js` 中：
  - 绑定 `#btn-refresh-ledger-target` 点击事件；
  - 绑定 `#ledger-include-headers-toggle` change 事件；
  - 绑定 `#btn-write-ledger` 点击事件并触发带清晰文案的 `window.confirm` 对话框；
  - 在 `renderLedger` 中同步渲染目标摘要、验证状态及按钮状态；
  - 绑定活动工作簿/工作表切换时重置选区检测与写入按钮状态。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js formal-plugin-kit/tests/excel-material-ledger.test.js
git commit -m "feat(excel): add ledger write section UI, styling and confirmation interaction"
```

---

### Task 5: 综合契约验证、交付清单更新与审计门禁

**Files:**
- Modify: `docs/codex-handoff.md`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`
- Test: 全量单元测试

- [ ] **Step 1: Run complete test suites**

Run:
```bash
node --test formal-plugin-kit/tests/excel-material-ledger.test.js
npm test
```
Expected: All tests pass.

- [ ] **Step 2: Perform Python 3.8 compatibility & git diff check**

Run:
```bash
git diff --check
python3 -m compileall adapter_service/
```
Expected: 0 errors, 0 trailing whitespace / format warnings.

- [ ] **Step 3: Update `docs/codex-handoff.md` with Issue #237 implementation record**

记录 Issue #237 的完成内容、设计关键点与测试结果。

- [ ] **Step 4: Commit and finalize**

```bash
git add docs/codex-handoff.md
git commit -m "docs: record issue-237 excel material ledger writeback in codex handoff"
```
