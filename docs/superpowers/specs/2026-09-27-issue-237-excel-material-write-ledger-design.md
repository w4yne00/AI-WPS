# Excel：确认后向空白区域写入台账设计规格 (Issue #237)

- 日期：2026-09-27
- 状态：已确认，待编制计划
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#237、#229（Parent）、#236（Prerequisite）
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Parent Issue #229 与 Issue #236 中，AI-WPS 已经为 Excel 建立了多资料导入、资料复用克隆、自定义表头映射以及台账长任务生成和只读预览能力。用户可以在任务窗格中查看结构化的工作事项列表、缺项标记、疑似重复警示及原文出处抽屉。

然而，在 Issue #236 的边界定义中，全流程严格处于只读预览模式，未调用任何单元格写入接口。本规格依据 Issue #237 的验收标准，为 Excel 插件建立“确认后向空白区域写入台账”的完整端到端技术规范：
1. **仅向用户确认的目标新增**：严格绑定当前工作簿、工作表及选定的空白目标区域，不匹配更新、不覆盖已有台账；
2. **严格空白预检**：写入前逐格复核目标区域仍为空白，若存在数据、公式、范围变化或工作簿切换则坚决拒绝覆盖；
3. **安全防注入与缺项留空**：缺项保持物理空白，对前缀为 `=+\-@` 的文本增加防执行前缀，严禁将提取文本作为新增公式执行；未确认、取消、失败结果不能写回；
4. **受控写入与失败恢复**：复用受控写入和逐格回滚补偿能力，明确记录部分写入状态，重试时防重复新增；
5. **授权边界保护**：确保授权范围外的值、公式与工作表绝对保持不变。

---

## 2. 核心架构原则与不变量

1. **纯新增只写空白原则（No Overwrite Invariant）**：
   - 本功能仅在目标区域完全为空白时执行新增记录操作；
   - 系统绝不自动猜测、匹配或覆盖已有记录或已有表格行；
   - 目标区域内若有任何一个单元格含有值或公式，一律 fail-closed 拦截，拒绝执行写入。
2. **多重身份与会话锁定原则（Session Consistency Invariant）**：
   - 写入操作必须核验当前的 `ActiveWorkbook` 会话标识与生成台账所属的 `documentSessionId` 100% 保持一致；
   - 在用户点击“确认写入”到实际执行写入的整个周期内，若检测到用户切换了活动工作簿或工作表，立即中止写入。
3. **公式注入绝对防御原则（Formula Defense Invariant）**：
   - 从资料提取出的文本内容若以 `=`、`+`、`-`、`@` 开头，写入单元格时必须自动添加前置单引号 `'`（例如 `'=SUM(...)`），强制 Excel 将其视作纯文本，彻底消除公式注入与恶意代码执行风险。
4. **缺项物理空白原则（Physical Blank for Missing Fields Invariant）**：
   - 提取结果中属于 `missingFields` 或值为空字符串 `""`/`null`/`undefined` 的项，写入时一律赋值为空字符串 `""`，保持单元格物理空白；
   - 严禁在单元格中写入 `〔缺项〕`、`N/A`、`待补充` 等占位文本。
5. **补偿回滚与重试幂等原则（Compensation & Idempotent Retry Invariant）**：
   - 写入过程维护已写入单元格快照；一旦中途发生错误，立即执行逆序回滚，将已写入单元格还原为空白；
   - 若全部回滚成功，用户清理环境后可重新写入；
   - 若部分回滚失败，系统明确提示未恢复的单元格地址并标记中断，后续重试因预检发现非空白而自动阻断，避免重复新增。

---

## 3. 目标区域选定与空白预检规范

### 3.1 目标区域计算逻辑

设定本次台账结果包含 $R$ 条记录（$R = \text{result.rows.length}$），表头包含 $C$ 列（$C = \text{result.headers.length}$）。用户可通过界面配置 `includeHeaders`（布尔值，默认 `true`）。

总计需要写入的行数 $N$ 计算如下：
$$N = R + (\text{includeHeaders} ? 1 : 0)$$

用户选定目标区域支持两种模式：
1. **单单元格起始点模式**：
   - 若当前选区仅为单个单元格 $(r_0, c_0)$（即选区行数与列数均为 1）：
   - 系统以该单元格作为左上角，自动计算目标矩形区域：
     $$\text{TargetRange} = [r_0, c_0] \sim [r_0 + N - 1, c_0 + C - 1]$$
2. **多单元格区域模式**：
   - 若当前选区包含多个单元格，起始点同样取选区左上角 $(r_0, c_0)$；
   - 校验当前选区的总行数必须 $\ge N$，总列数必须 $\ge C$；若选区尺寸不足，预检报错提示：“当前选区尺寸不足以容纳 $N$ 行 $C$ 列台账，请扩大选区或仅选中起始单元格。”

### 3.2 预检安全门禁 (Pre-flight Validation)

在用户点击写入以及实际写入执行前，系统必须同步执行严格的只读预检遍历：
1. **会话一致性检验**：
   - 获取当前活动工作簿标识 `helpers.getDocumentSessionId(app)`；
   - 断言该标识与当前台账结果所属的 `state.documentSessionId` 严格一致；
   - 获取当前活动工作表名称 `sheetName = app.ActiveSheet.Name`。
2. **逐单元格安全与空白检查**：
   - 遍历目标矩形内所有的 $N \times C$ 个单元格 $(r, c)$：
     - **可读性检查**：单元格对象必须存在且可正常读取属性；
     - **保护状态检查**：若工作表开启了保护（`Protect`），且单元格被锁定（`Locked`），立即拒绝；
     - **合并单元格拦截**：单元格不可为合并单元格（`cell.MergeCells !== true` 且 `!cell.mergeCells`）；
     - **隐藏行列拦截**：单元格所在的行或列不可被隐藏（`cell.EntireRow.Hidden !== true` 且 `cell.EntireColumn.Hidden !== true`）；
     - **无公式拦截**：单元格不能包含公式（`!cell.HasFormula` 且 `!cell.formula` 且 `!cell.Formula`）；
     - **严格空白检查**：单元格值必须为空，即满足：
       ```javascript
       var raw = cell.Value2 !== undefined ? cell.Value2 : cell.Value;
       if (raw !== null && raw !== "" && typeof raw !== "undefined") {
         throw new Error("目标区域包含已有数据（单元格 " + address + " 值为 " + raw + "），已拒绝覆盖。请选择完全空白的区域。");
       }
       ```
3. **预检报告对象**：
   预检成功后产出明确的目标绑定上下文 `targetContext`：
   ```javascript
   {
     workbookSessionId: "sess_excel_xxxx",
     workbookName: "项目任务跟踪.xlsx",
     sheetName: "Sheet1",
     startRow: 2,
     startCol: 1,
     endRow: 6,
     endCol: 4,
     targetAddress: "A2:D6",
     rowCount: 5,
     colCount: 4,
     includeHeaders: true,
     verifiedBlank: true
   }
   ```

---

## 4. 数据映射与防注入规范

### 4.1 写入网格构建

根据 `result.headers`、`result.rows` 以及 `includeHeaders` 参数构建写入单元格计划队列 `writePlans`：
1. **表头行（若 `includeHeaders === true`）**：
   - 行号 $r = r_0$；
   - 对于第 $j$ 列（$j \in [0, C-1]$），目标列号 $c = c_0 + j$；
   - 写入值为 `headers[j]`。
2. **数据行**：
   - 对应数据行索引 $i \in [0, R-1]$；
   - 目标行号 $r = r_0 + (\text{includeHeaders} ? 1 : 0) + i$；
   - 对于第 $j$ 列，列名为 $H = \text{headers}[j]$；
   - 读取行提取值 $V = \text{row.values}[H]$；
   - 若 $H \in \text{row.missingFields}$ 或 $V$ 为 `null`/`undefined`，则最终字符串值为 `""`；
   - 否则转为字符串并去除换行制表符影响（保持单行语义）。

### 4.2 公式前缀转义规则

所有计划写入的文本字符串 $S$ 执行如下处理：
```javascript
function sanitizeCellValue(val) {
  if (val === null || typeof val === "undefined") {
    return "";
  }
  var str = String(val);
  if (/^[=+\-@]/.test(str)) {
    return "'" + str;
  }
  return str;
}
```
通过转义，任何以 `=`, `+`, `-`, `@` 开头的文本在写入 Excel 单元格时，均作为纯文本存储，绝不会被解析为 Excel 内部公式或超链接宏。

---

## 5. 受控写入管道与回滚补偿机制

### 5.1 受控写入流程

写入函数 `writeExcelMaterialLedger(app, result, options)` 遵循如下时序：
1. **前置门禁断言**：
   - 断言 `result` 有效、`result.rows` 为非空数组、`result.headers` 为非空数组；
   - 断言当前任务状态为 `completed`；若处于 `running`、`queued`、`cancelled` 或 `failed`，拒绝写入。
2. **执行前置空白预检**：
   - 调用预检函数读取选区并验证所有目标单元格完全空白；
   - 获取 `writePlans` 列表（包含每个单元格的引用、行列号、A1地址及计划值）。
3. **逐步写入与回读核对**：
   - 维护已成功写入列表 `writtenList = []`；
   - 循环遍历 `writePlans`：
     ```javascript
     var plan = writePlans[idx];
     var entry = {
       cell: plan.cell,
       address: plan.address,
       previousValue: ""
     };
     writtenList.push(entry);
     plan.cell.Value2 = plan.sanitizedValue;
     // 回读核对
     var after = plan.cell.Value2;
     if (!verifyCellWriteMatches(after, plan.sanitizedValue)) {
       throw new Error("写回后未能核对目标地址 " + plan.address + "。");
     }
     ```
4. **终态返回**：
   - 全部写入并核验成功后，返回写入报告：
     ```javascript
     {
       success: true,
       writtenCount: writePlans.length,
       targetAddress: targetContext.targetAddress,
       sheetName: targetContext.sheetName,
       includeHeaders: targetContext.includeHeaders
     }
     ```

### 5.2 异常补偿回滚机制 (Compensation Rollback)

在写入循环发生任何捕获异常（如 COM 错误、网络中断或校验不匹配）时，立即进入回滚分支：
```javascript
catch (error) {
  var rollbackFailures = [];
  // 逆序还原已写入的单元格
  writtenList.slice().reverse().forEach(function (entry) {
    try {
      entry.cell.Value2 = "";
      var afterRollback = entry.cell.Value2;
      if (afterRollback !== null && afterRollback !== "" && typeof afterRollback !== "undefined") {
        rollbackFailures.push(entry.address);
      }
    } catch (e) {
      rollbackFailures.push(entry.address);
    }
  });

  if (rollbackFailures.length > 0) {
    var compErr = new Error("台账写入失败，且部分单元格无法自动恢复空白，需要人工核对：" + rollbackFailures.join("、"));
    compErr.code = "COMPENSATION_FAILED";
    compErr.rollbackFailures = rollbackFailures;
    compErr.cause = error;
    throw compErr;
  } else {
    var compSucc = new Error("台账写入失败，已成功将已写入单元格恢复为空白。" + (error && error.message ? " " + error.message : ""));
    compSucc.code = "COMPENSATION_SUCCEEDED";
    compSucc.cause = error;
    throw compSucc;
  }
}
```

### 5.3 部分写入防御与重试保护

若发生 `COMPENSATION_FAILED`：
1. 任务窗格在状态栏和结果面板显式展示红色警示，列出未能恢复的单元格地址列表；
2. 内部状态标记 `partialWriteAddresses`；
3. 用户在清理工作表之前若再次点击写入，预检系统在第一步就会检测到目标区域存在残留值，立即强行阻止写入，彻底杜绝数据覆盖或错位重复新增。

---

## 6. 前端组件与用户确认流程规范

### 6.1 界面元素布局 (`taskpane.html`)

在 `#excel-ledger-result` 结果面板中，位于表格与 TSV 复制按钮下方，新增专属写入控制区 `#ledger-write-section`：
```html
<div id="ledger-write-section" class="ledger-write-section" style="margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--color-border-subtle, #e0e0e0);">
  <div class="ledger-target-panel" style="background: var(--color-surface-muted, #f8f9fa); padding: 8px 10px; border-radius: 4px; margin-bottom: 8px;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span style="font-size: 12px; font-weight: 500;">目标写入位置</span>
      <button id="btn-refresh-ledger-target" class="ghost-action" type="button" style="font-size: 11px;">刷新选区检测</button>
    </div>
    <p id="ledger-target-summary" class="field-hint" style="margin: 4px 0 2px 0;">请在工作表中选中空白区域或起始单元格后检测。</p>
    <p id="ledger-target-validation" class="field-hint" style="margin: 0; font-size: 11px;"></p>
  </div>

  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
    <label class="checkbox-field" style="display: flex; align-items: center; font-size: 12px; cursor: pointer;">
      <input id="ledger-include-headers-toggle" type="checkbox" checked style="margin-right: 6px;" />
      <span>包含表头行（首行写入列名）</span>
    </label>
  </div>

  <div class="button-cluster">
    <button id="btn-write-ledger" class="primary-action" type="button" disabled style="width: 100%;">确认写入工作表</button>
  </div>
  <p id="ledger-write-status" class="inline-status" role="status" aria-live="polite" style="margin-top: 6px;"></p>
</div>
```

### 6.2 交互生命周期

1. **结果生成完成 (`status === 'completed'`)**：
   - 自动激活写入控制区，调用一次自动选区检测；
   - 若当前选区已满足空白条件，高亮呈现绿色状态“✓ 目标区域完全空白（Sheet1!A2:D6，共5行4列），可安全写入”，同时启用“确认写入工作表”按钮；
   - 若当前选区包含数据或未选中，提示具体原因，按钮保持禁用。
2. **勾选切换 (`includeHeaders` 切换)**：
   - 用户切换复选框时，即时重新计算行数并重新校验目标选区；
   - 目标地址范围与行列数动态刷新。
3. **点击「确认写入工作表」**：
   - 触发原生模态确认框（Confirm Dialog/Modal）：
     > “确认将 N 条台账记录写入到当前工作簿【<工作簿名>】的【<工作表名>!<地址>】吗？\n系统已核验该区域完全空白，写入将新增记录，不覆盖已有内容。”
   - 若用户点击“取消”：安全中止，不改变文档，保持草稿与选区状态；
   - 若用户点击“确认”：
     - 按钮进入 disabled 并提示“正在写入工作表...”；
     - 重新执行一次原子空白预检，随后执行写入管道；
     - 成功后：展示成功反馈“✓ 已成功新增 N 条记录至 <工作表名>!<地址>”，更新按钮为“已完成写入”，不重复执行。

---

## 7. 验证与门禁标准

### 7.1 插件契约测试规范 (`formal-plugin-kit/tests/excel-material-ledger.test.js`)

增补一组专属受控写入契约测试：
1. **选区尺寸与地址计算测试**：
   - 单单元格选区自动扩展为 $N \times C$ 范围；
   - 多单元格选区尺寸充足时正常匹配，尺寸不足时正确报错拦截。
2. **非空白区域拒绝覆盖拦截测试**：
   - 目标区域内含文本、数值时拦截；
   - 目标区域内含公式（`HasFormula` / `Formula`）时拦截；
   - 目标区域为合并单元格或隐藏行列时拦截；
   - 目标工作表受保护时拦截。
3. **工作簿与会话一致性测试**：
   - 切换工作簿（会话 ID 不符）时拦截；
   - 跨工作表切换时拒绝将旧工作表选区写入新工作表。
4. **防公式注入测试**：
   - 验证提取结果中包含 `=SUM(1,2)`、`+123`、`-test`、`@cmd` 时，单元格写入的值带前置单引号 `'`，不产生执行。
5. **缺项留空测试**：
   - 验证 `missingFields` 字段写入后单元格为严格的 `""`，不产生占位文字。
6. **写入异常与回滚补偿测试**：
   - 模拟中途抛出异常，断言已写入单元格被完全恢复为空字符串；
   - 模拟部分恢复失败，断言返回 `COMPENSATION_FAILED` 并在结果状态中列出具体需要人工核对的地址列表；
   - 验证在部分残留状态下重试写入被预检安全拦截。
7. **用户确认与取消流测试**：
   - 用户取消确认弹窗时，写入调用次数严格为 0；
   - 用户确认后成功写入，并触发成功状态。
8. **授权范围外值保持不变测试**：
   - 验证目标矩形范围外的单元格数据和公式未发生任何改变。

### 7.2 构建与质量门禁

- `npm test` 与 `node --test formal-plugin-kit/tests/*.test.js` 100% 通过；
- `git diff --check` 无格式警告；
- 不破坏现有 Word、Excel 智能分析与 PPT 功能。
