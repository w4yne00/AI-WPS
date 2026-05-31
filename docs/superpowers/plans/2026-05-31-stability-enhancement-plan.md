# AI-WPS Stability Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `v0.12.11-alpha` as a stability and usability release that improves 文档审查 and 格式审查 result readability, adds a settings-page diagnostics panel, and keeps the existing Dify routing/API key behavior unchanged.

**Architecture:** Preserve the current WPS taskpane + local FastAPI adapter + Dify `/chat-messages` design. Frontend changes are pure rendering and settings-page diagnostics additions. Backend changes only enrich already-sanitized provider debug metadata; Word task routes and task-level API key selection remain intact.

**Tech Stack:** Vanilla JS/HTML/CSS WPS taskpane, Python FastAPI/Pydantic adapter, existing Node smoke tests, existing Python unittest suite, existing packaging scripts.

---

## Preconditions

- [ ] Re-read `docs/codex-handoff.md` before code edits and confirm the current version is `v0.12.10-alpha`.
- [ ] Work in the current dirty tree without reverting unrelated tarball deletions or untracked historical delivery artifacts.
- [ ] Do not change these public task routes:
  - `POST /word/smart-write`
  - `POST /word/document-review`
  - `POST /word/format-review`
- [ ] Do not change Dify request shape. It must remain:

```json
{
  "inputs": {"query": "完整中文任务提示词"},
  "query": "完整中文任务提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

- [ ] Do not change task API key selection for:
  - `word.smart_write`
  - `word.document_review`
  - `word.format_review`
- [ ] Do not add runtime dependencies.

## File Map

- Modify `formal-plugin-kit/tests/layout-smoke.test.js`: lock the new frontend contract first.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`: add grouped renderers and diagnostics aggregation.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`: add the diagnostics card under settings.
- Modify `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`: style the diagnostics card and Markdown output.
- Modify `adapter_service/tests/test_enterprise_provider.py`: lock sanitized provider debug metadata.
- Modify `adapter_service/app/services/provider_client.py`: enrich provider debug events without secrets.
- Modify version-bearing files: `adapter_service/app/main.py`, `adapter_service/app/services/provider_client.py`, `adapter_service/standalone_adapter.py`, `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`, `taskpane.html`, `ribbon.js`, packaging metadata that already carries the frontend/cache version.
- Modify docs: `README.md`, `README-ZH.md`, `docs/codex-handoff.md`, `docs/operations/dify-smart-write-workflow.md`, `docs/operations/dify-document-review-workflow.md`, `docs/operations/dify-format-review-workflow.md`.

## Task 1: Lock Frontend Contract In Smoke Tests

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add failing smoke assertions for grouped renderers and diagnostics controls**

Add these assertions after the existing `diagnostics-section` assertions:

```js
assert.ok(html.includes('id="last-task-diagnostics-card"'));
assert.ok(html.includes('id="btn-refresh-diagnostics"'));
assert.ok(html.includes('id="btn-copy-diagnostics"'));
assert.ok(html.includes('id="last-task-diagnostics-output"'));
assert.ok(html.includes('最近一次任务诊断'));
```

Add these assertions after the existing JS checks for `/word/format-review`:

```js
assert.ok(js.includes("renderGroupedDocumentReview"));
assert.ok(js.includes("renderGroupedFormatReview"));
assert.ok(js.includes("renderProviderDiagnostics"));
assert.ok(js.includes("refreshDiagnostics"));
assert.ok(js.includes("copyDiagnostics"));
assert.ok(js.includes("/provider/debug-last"));
assert.ok(js.includes("/provider/route-diagnostics"));
assert.ok(js.includes("/provider/task-api-keys"));
assert.ok(js.includes('diagnosticsCopyText: ""'));
assert.ok(js.includes("错别字"));
assert.ok(js.includes("页面设置"));
assert.ok(js.includes("其他格式项"));
```

- [ ] **Step 2: Run the smoke test and confirm the expected failure**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: fails because `last-task-diagnostics-card`, `renderGroupedDocumentReview`, and `renderProviderDiagnostics` are not implemented yet.

- [ ] **Step 3: Commit the failing frontend contract test**

Run:

```bash
git add formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "test: lock stability enhancement frontend contract"
```

## Task 2: Add Grouped Document Review And Format Review Rendering

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add grouping constants and helpers in `taskpane.js` near `formatAiFallbackReason`**

Add this code before `formatAiFallbackReason`:

```js
  var DOCUMENT_REVIEW_CATEGORY_ORDER = ["typo", "expression", "logic", "fluency", "professional", "other"];
  var DOCUMENT_REVIEW_CATEGORY_TEXT = {
    typo: "错别字",
    expression: "语言表达",
    logic: "逻辑表达",
    fluency: "通畅性",
    professional: "专业性",
    other: "其他问题"
  };
  var REVIEW_SEVERITY_TEXT = {
    high: "高",
    medium: "中",
    low: "低"
  };
  var FORMAT_REVIEW_GROUP_ORDER = [
    "page_setup",
    "heading",
    "body_text",
    "paragraph",
    "caption_note",
    "other"
  ];
  var FORMAT_REVIEW_GROUP_TEXT = {
    page_setup: "页面设置",
    heading: "标题层级",
    body_text: "正文格式",
    paragraph: "段落格式",
    caption_note: "图表题/注释",
    other: "其他格式项"
  };

  function groupItems(items, getKey) {
    var grouped = {};
    (items || []).forEach(function (item) {
      var key = getKey(item) || "other";
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    });
    return grouped;
  }

  function getDocumentReviewCategory(issue) {
    var category = issue && issue.category ? String(issue.category) : "";
    return DOCUMENT_REVIEW_CATEGORY_TEXT[category] ? category : "other";
  }

  function getFormatReviewGroup(issue) {
    var ruleId = String((issue && issue.ruleId) || "");
    var role = String((issue && issue.role) || "");
    if (ruleId === "page_setup") {
      return "page_setup";
    }
    if (role.indexOf("heading") >= 0 || role.indexOf("title") >= 0) {
      return "heading";
    }
    if (ruleId === "style_name") {
      return "body_text";
    }
    if (ruleId === "font_name" || ruleId === "font_size") {
      return "body_text";
    }
    if (ruleId === "line_spacing" || ruleId === "alignment" || ruleId === "first_line_indent") {
      return "paragraph";
    }
    if (role.indexOf("caption") >= 0 || role.indexOf("note") >= 0 || ruleId.indexOf("caption") >= 0 || ruleId.indexOf("note") >= 0) {
      return "caption_note";
    }
    return "other";
  }
```

- [ ] **Step 2: Replace `renderDocumentReview(data)` with grouped output**

Replace the existing `renderDocumentReview(data)` function with this implementation:

```js
  function renderGroupedDocumentReview(data) {
    var documentTypeText = {
      technical_solution: "技术方案",
      contract_acceptance: "合同验收文档",
      test_outline: "测试大纲和细则"
    };
    var issues = data.issues || [];
    var lines = [
      "文档审查结果",
      "",
      "文档类型：" + (documentTypeText[data.documentType] || data.documentType || "技术方案"),
      "检查范围：" + (data.scope === "selection" ? "选中内容" : "全文"),
      "总体结论：" + (data.summary || "审查完成。"),
      "问题数量：" + issues.length,
      ""
    ];

    if (!issues.length) {
      lines.push("未发现明显文档质量问题。");
      return lines.join("\n");
    }

    var grouped = groupItems(issues, getDocumentReviewCategory);
    DOCUMENT_REVIEW_CATEGORY_ORDER.forEach(function (category) {
      var categoryIssues = grouped[category] || [];
      if (!categoryIssues.length) {
        return;
      }
      lines.push("## " + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + "（" + categoryIssues.length + "）");
      lines.push("");
      categoryIssues.forEach(function (issue, index) {
        lines.push("### " + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + " #" + (index + 1));
        lines.push("- 严重程度：" + (REVIEW_SEVERITY_TEXT[issue.severity] || issue.severity || "中"));
        lines.push("- 位置：" + (issue.location || "未定位"));
        if (issue.originalText) {
          lines.push("- 原文片段：" + issue.originalText);
        }
        lines.push("- 问题说明：" + (issue.problem || "未说明"));
        lines.push("- 修改建议：" + (issue.suggestion || "无"));
        if (issue.suggestedRewrite) {
          lines.push("- 建议改写：" + issue.suggestedRewrite);
        }
        lines.push("");
      });
    });

    return lines.join("\n").trim();
  }
```

- [ ] **Step 3: Replace `renderFormatReview(data)` with grouped output**

Replace the existing `renderFormatReview(data)` function with this implementation:

```js
  function renderGroupedFormatReview(data) {
    var summary = data.summary || {};
    var issues = data.issues || [];
    var lines = [
      "格式审查结果",
      "",
      "模板：" + (summary.templateId || "technical-file-format-requirements"),
      "检查范围：" + (summary.scope === "selection" ? "选中内容" : "全文"),
      "发现问题：" + (summary.issueCount || issues.length || 0)
    ];
    var hasCoverageStats = typeof summary.paragraphCount !== "undefined";

    if (hasCoverageStats) {
      lines.push("扫描段落：" + summary.paragraphCount);
      lines.push(
        "AI 识别段落：" + (summary.aiClassifiedParagraphCount || 0) +
        " | 本地兜底段落：" + (summary.localFallbackParagraphCount || 0)
      );
    }
    lines.push("识别来源：" + (summary.provider || "local"));
    var aiFallbackText = formatAiFallbackReason(summary.aiFallbackReason);
    if (aiFallbackText) {
      lines.push("fallback 原因：" + aiFallbackText);
    }
    if (summary.aiInvalidRoleCount || summary.aiOutOfBatchCount) {
      lines.push(
        "AI 无效角色：" + (summary.aiInvalidRoleCount || 0) +
        " | 越界段落：" + (summary.aiOutOfBatchCount || 0)
      );
    }
    lines.push("");
    lines.push("以下仅显示需要调整的格式项，正文内容不会在检查中改写。");
    lines.push("");

    if (!issues.length) {
      lines.push("当前范围未发现明显格式问题。");
      return lines.join("\n");
    }

    var grouped = groupItems(issues, getFormatReviewGroup);
    FORMAT_REVIEW_GROUP_ORDER.forEach(function (group) {
      var groupIssues = grouped[group] || [];
      if (!groupIssues.length) {
        return;
      }
      lines.push("## " + FORMAT_REVIEW_GROUP_TEXT[group] + "（" + groupIssues.length + "）");
      lines.push("");
      groupIssues.forEach(function (issue, index) {
        lines.push("### " + FORMAT_REVIEW_GROUP_TEXT[group] + " #" + (index + 1));
        lines.push("- 段落号：" + (issue.paragraphIndex || 0));
        lines.push("- 段落角色：" + (issue.role || "未识别"));
        lines.push("- 问题说明：" + (issue.message || "格式问题"));
        lines.push("- 当前值：" + (issue.currentValue || "未读取"));
        lines.push("- 模板要求：" + (issue.expectedValue || "未给出"));
        lines.push("- 建议操作：" + (issue.suggestion || "按模板调整。"));
        lines.push("");
      });
    });

    return lines.join("\n").trim();
  }
```

- [ ] **Step 4: Update task runners to use grouped renderers**

Change the document review success handler:

```js
setResult(renderGroupedDocumentReview(body.data || {}));
```

Change the format review success handler:

```js
setResult(renderGroupedFormatReview(body.data || {}));
```

- [ ] **Step 5: Run frontend checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: `node --check` passes. Smoke test still fails until the diagnostics card is implemented in Task 3.

- [ ] **Step 6: Commit grouped renderers**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
git commit -m "feat: group review result output"
```

## Task 3: Add Settings Page Recent Task Diagnostics

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add diagnostics HTML under the existing `联调状态` card**

Insert this card inside `section id="diagnostics-section"` after the current `settings-card`:

```html
            <section id="last-task-diagnostics-card" class="settings-card diagnostics-card">
              <div class="settings-card-head">
                <h4>最近一次任务诊断</h4>
                <span class="inline-status">脱敏摘要</span>
              </div>
              <div class="button-row diagnostics-actions">
                <button id="btn-refresh-diagnostics" class="ghost-action" type="button">刷新诊断</button>
                <button id="btn-copy-diagnostics" class="ghost-action" type="button">复制诊断信息</button>
              </div>
              <div id="last-task-diagnostics-output" class="markdown-output diagnostics-output">尚未刷新诊断。</div>
            </section>
```

- [ ] **Step 2: Add diagnostics CSS**

Add this block near the existing result/Markdown styles:

```css
.diagnostics-card {
  gap: 12px;
}

.diagnostics-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.diagnostics-output {
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
  font-size: 12px;
  line-height: 1.55;
}
```

- [ ] **Step 3: Add diagnostics state**

In the `state` object, add:

```js
    diagnosticsCopyText: "",
```

- [ ] **Step 4: Add diagnostics render helpers after `readAdapterJson(path)`**

Add this code:

```js
  function yesNo(value) {
    return value ? "是" : "否";
  }

  function describeAuthSource(value) {
    return {
      env: "环境变量",
      file: "统一密钥文件",
      "task-file": "任务级密钥文件",
      "route-file": "任务级密钥文件",
      none: "未配置"
    }[value] || value || "未检测";
  }

  function firstErrorMessage(result) {
    if (!result || result.success !== false) {
      return "";
    }
    return result.errors && result.errors[0] && result.errors[0].message
      ? result.errors[0].message
      : "请求失败";
  }

  function renderProviderDiagnostics(debugResult, statusResult, routesResult, taskKeysResult) {
    var debug = (debugResult && debugResult.data) || {};
    var status = (statusResult && statusResult.data) || {};
    var routes = (routesResult && routesResult.data) || {};
    var taskKeys = (taskKeysResult && taskKeysResult.data) || {};
    var lines = ["最近一次任务诊断", ""];

    if (firstErrorMessage(debugResult)) {
      lines.push("- debug-last：" + firstErrorMessage(debugResult));
    }
    if (firstErrorMessage(statusResult)) {
      lines.push("- provider/status：" + firstErrorMessage(statusResult));
    }
    if (firstErrorMessage(routesResult)) {
      lines.push("- route-diagnostics：" + firstErrorMessage(routesResult));
    }
    if (firstErrorMessage(taskKeysResult)) {
      lines.push("- task-api-keys：" + firstErrorMessage(taskKeysResult));
    }

    lines.push("- 任务类型：" + (debug.taskType || "未记录"));
    lines.push("- traceId：" + (debug.traceId || "未记录"));
    lines.push("- adapter 状态：" + (status.configured ? "provider 已配置" : "provider 未配置"));
    lines.push("- provider 类型：" + (status.providerType || routes.providerType || "未检测"));
    lines.push("- provider 名称：" + (status.providerName || "未检测"));
    lines.push("- 统一 API URL 已配置：" + yesNo(routes.providerBaseUrlConfigured || debug.providerBaseUrlConfigured));
    lines.push("- 认证来源：" + describeAuthSource(debug.taskAuthSource || debug.authSource || status.authSource || routes.authSource));
    lines.push("- 请求路径：" + (debug.url || routes.url || "未进入 Dify 请求"));
    lines.push("- fallback 原因：" + (debug.skipReason || "无"));

    if (debug.request) {
      lines.push("");
      lines.push("## 请求摘要");
      lines.push("- body 字段：" + (debug.request.bodyKeys || []).join(", "));
      lines.push("- inputs 字段：" + (debug.request.inputsKeys || []).join(", "));
      lines.push("- query 长度：" + (debug.request.queryLength || 0));
      lines.push("- query 预览：" + (debug.request.queryPreview || "空"));
      lines.push("- response_mode：" + (debug.request.responseMode || "未记录"));
    }

    if (debug.response) {
      lines.push("");
      lines.push("## 响应摘要");
      lines.push("- HTTP 状态：" + (debug.response.status || "未记录"));
      lines.push("- body 字段：" + (debug.response.bodyKeys || []).join(", "));
      lines.push("- answer 长度：" + (debug.response.answerLength || 0));
      if (debug.response.answerFormat) {
        lines.push("- Markdown 特征：" + yesNo(debug.response.answerFormat.containsMarkdown));
      }
    }

    if (debug.error) {
      lines.push("");
      lines.push("## 错误摘要");
      lines.push("- 类型：" + (debug.error.type || "未记录"));
      lines.push("- 状态：" + (debug.error.status || "未记录"));
      lines.push("- 信息：" + (debug.error.message || "未记录"));
    }

    lines.push("");
    lines.push("## 任务密钥状态");
    Object.keys(taskKeys).forEach(function (taskType) {
      var item = taskKeys[taskType] || {};
      lines.push("- " + taskType + "：" + describeAuthSource(item.authSource) + "，已配置：" + yesNo(item.configured));
    });

    return lines.join("\n");
  }
```

- [ ] **Step 5: Add diagnostics refresh and copy functions after `copyResult()`**

Add this code:

```js
  function setDiagnosticsResult(text) {
    var output = byId("last-task-diagnostics-output");
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(text);
    } else {
      output.textContent = text;
    }
    state.diagnosticsCopyText = text || "";
  }

  function refreshDiagnostics() {
    setDiagnosticsResult("正在刷新最近一次任务诊断...");
    return Promise.all([
      readAdapterJson("/provider/debug-last"),
      readAdapterJson("/provider/status"),
      readAdapterJson("/provider/route-diagnostics"),
      readAdapterJson("/provider/task-api-keys")
    ]).then(function (results) {
      var markdown = renderProviderDiagnostics(results[0], results[1], results[2], results[3]);
      setDiagnosticsResult(markdown);
      setStatus("诊断信息已刷新。");
    });
  }

  function copyDiagnostics() {
    var text = state.diagnosticsCopyText || byId("last-task-diagnostics-output").textContent || "";
    if (!text.trim()) {
      setStatus("暂无可复制的诊断信息。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("诊断信息已复制。");
      }).catch(function () {
        fallbackCopy(text);
      });
      return;
    }
    fallbackCopy(text);
  }
```

- [ ] **Step 6: Bind diagnostics buttons**

Add these lines in `bindEvents()` after the existing refresh button binding:

```js
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
```

- [ ] **Step 7: Refresh diagnostics after configuration refresh**

At the end of successful `refreshConfig()` handling, after `setStatus("就绪");`, add:

```js
      refreshDiagnostics();
```

- [ ] **Step 8: Run frontend checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: both pass.

- [ ] **Step 9: Commit diagnostics UI**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: add settings task diagnostics panel"
```

## Task 4: Enrich Sanitized Provider Debug Metadata

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] **Step 1: Add failing tests for debug metadata**

In `test_provider_debug_records_sanitized_request_and_response`, add these fields to the `record_provider_debug()` event:

```python
                "provider": "enterprise-dify-chat",
                "providerName": "企业大模型接口",
                "providerType": "enterprise-dify-chat",
                "providerBaseUrlConfigured": True,
                "authSource": "task-file",
                "taskAuthSource": "task-file",
                "taskApiKeyRef": "word_smart_write",
```

Then add assertions after `self.assertEqual(debug["taskType"], "word.smart_write")`:

```python
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["providerName"], "企业大模型接口")
        self.assertEqual(debug["providerType"], "enterprise-dify-chat")
        self.assertTrue(debug["providerBaseUrlConfigured"])
        self.assertEqual(debug["authSource"], "task-file")
        self.assertEqual(debug["taskAuthSource"], "task-file")
        self.assertEqual(debug["taskApiKeyRef"], "word_smart_write")
```

In `test_record_skipped_debug_records_format_review_skip_reason`, add:

```python
        self.assertEqual(debug["taskApiKeyRef"], "word_format_review")
        self.assertEqual(debug["taskAuthSource"], "none")
```

- [ ] **Step 2: Run provider tests and confirm the expected failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: fails on missing `providerName`, `providerType`, or `taskApiKeyRef`.

- [ ] **Step 3: Preserve new debug fields in `record_provider_debug(event)`**

Change the field copy loop to:

```python
    for field in (
        "provider",
        "providerName",
        "providerType",
        "skipReason",
        "providerBaseUrlConfigured",
        "authSource",
        "taskAuthSource",
        "taskApiKeyRef",
    ):
        if field in event:
            debug[field] = event[field]
```

- [ ] **Step 4: Add a debug metadata helper on `ProviderClient`**

Add this method above `post_task()`:

```python
    def build_debug_metadata(self, task_type: str, provider: str = "enterprise-dify-chat") -> Dict:
        return {
            "provider": provider,
            "providerName": self.settings.provider_name,
            "providerType": self.settings.provider_type,
            "providerBaseUrlConfigured": bool(self.settings.provider_base_url.strip()),
            "authSource": self.get_auth_source_for_task(task_type),
            "taskAuthSource": self.get_auth_source_for_task(task_type),
            "taskApiKeyRef": self.get_task_api_key_ref(task_type),
        }
```

- [ ] **Step 5: Use the helper in all `post_task()` debug events**

For each `record_provider_debug({...})` call inside `post_task()`, expand the event dictionary with:

```python
                **self.build_debug_metadata(task_type),
```

For the initial pre-request debug event, use:

```python
                **self.build_debug_metadata(task_type),
```

- [ ] **Step 6: Use the helper in skipped debug events**

In `record_skipped_debug()`, replace the provider/auth fields with:

```python
                **self.build_debug_metadata(task_type, provider=provider),
                "skipReason": skip_reason,
```

- [ ] **Step 7: Run provider tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: provider tests pass and no assertion output contains API keys or full prompt text.

- [ ] **Step 8: Commit backend debug enrichment**

Run:

```bash
git add adapter_service/tests/test_enterprise_provider.py adapter_service/app/services/provider_client.py
git commit -m "feat: enrich sanitized provider diagnostics"
```

## Task 5: Version Bump And Documentation Updates

**Files:**
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `docs/operations/dify-smart-write-workflow.md`
- Modify: `docs/operations/dify-document-review-workflow.md`
- Modify: `docs/operations/dify-format-review-workflow.md`

- [ ] **Step 1: Replace version strings**

Replace:

```text
0.12.10-alpha
```

with:

```text
0.12.11-alpha
```

Replace:

```text
AI-WPS-P1-WORD-0.12.10-20260531
```

with:

```text
AI-WPS-P1-WORD-0.12.11-20260531
```

- [ ] **Step 2: Update README release notes**

Add a `v0.12.11-alpha` note containing these exact bullets:

```markdown
- 文档审查结果按错别字、语言表达、逻辑表达、通畅性、专业性分组展示。
- 格式审查结果按页面设置、标题层级、正文格式、段落格式、图表题/注释、其他格式项分组展示。
- 设置页新增“最近一次任务诊断”，可查看并复制脱敏的 adapter/provider/Dify 请求摘要。
- 不改变智能编写、文档审查、格式审查的接口路径和任务级 API Key 选路逻辑。
```

- [ ] **Step 3: Update Dify workflow manuals**

In each Dify manual, add a diagnostics section with this text:

```markdown
## 现场诊断

设置页“最近一次任务诊断”对应 adapter 的 `/provider/debug-last`、`/provider/status`、`/provider/route-diagnostics`、`/provider/task-api-keys`。诊断信息只显示脱敏摘要，不显示完整原文和 API Key。

如果前台结果异常，优先确认：

1. `taskType` 是否为当前功能对应任务。
2. `authSource` 或 `taskAuthSource` 是否为任务级密钥文件。
3. `url` 是否为统一 API URL 拼接 `/chat-messages`。
4. `request.bodyKeys` 是否包含 `inputs`、`query`、`response_mode`、`user`。
5. `response.answerLength` 是否大于 0。
```

In `docs/operations/dify-document-review-workflow.md`, keep the Markdown `json` code block requirement and add:

```markdown
文档审查可以输出 Markdown，但必须包含一个合法 `json` 代码块，adapter 从该代码块中提取 `summary` 和 `issues`。
```

In `docs/operations/dify-format-review-workflow.md`, add:

```markdown
格式审查的 AI 段落角色识别是可选增强。Dify 超时、无 JSON 或未配置时，adapter 会回退本地模板规则并在诊断里显示 fallback 原因。
```

- [ ] **Step 4: Update handoff**

In `docs/codex-handoff.md`, update:

```markdown
当前版本：`v0.12.11-alpha`
版本规则号：`AI-WPS-P1-WORD-0.12.11-20260531`
```

Add a current-version change note:

```markdown
- 文档审查和格式审查结果改为分组 Markdown 展示，便于按问题类型定位。
- 设置页新增最近一次任务诊断，可直接查看 adapter/provider/Dify 脱敏请求和响应摘要。
- 智能编写、文档审查、格式审查的任务级 API Key 选路未变。
```

- [ ] **Step 5: Run documentation and syntax checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
git diff --check
```

Expected: all commands pass.

- [ ] **Step 6: Commit version and documentation**

Run:

```bash
git add adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/standalone_adapter.py formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js README.md README-ZH.md docs/codex-handoff.md docs/operations/dify-smart-write-workflow.md docs/operations/dify-document-review-workflow.md docs/operations/dify-format-review-workflow.md
git commit -m "docs: prepare v0.12.11 stability release"
```

## Task 6: Full Regression And Delivery Package

**Files:**
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260531.tar.gz`

- [ ] **Step 1: Run full backend tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
```

Expected: existing Python suite passes; FastAPI TestClient tests may skip in the bundled environment if FastAPI is unavailable, matching the current handoff pattern.

- [ ] **Step 2: Run full frontend checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
```

Expected: all frontend checks pass.

- [ ] **Step 3: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Build delivery package**

Run:

```bash
DATE_TAG=20260531 bash packaging/build_phase1_delivery_kit.sh
```

Expected: package path `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260531.tar.gz` is printed.

- [ ] **Step 5: Record package hash**

Run:

```bash
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260531.tar.gz
```

Expected: one SHA256 line for the new delivery package.

- [ ] **Step 6: Commit package**

Run:

```bash
git add dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260531.tar.gz docs/codex-handoff.md
git commit -m "chore: package v0.12.11 delivery kit"
```

## Task 7: Final Verification And GitHub Push

**Files:**
- No code files changed in this task.

- [ ] **Step 1: Review intended changes only**

Run:

```bash
git status --short
```

Expected: only unrelated historical tarball changes and untracked historical artifacts remain unstaged. The new commits must not include unrelated deletions of old delivery packages.

- [ ] **Step 2: Show recent commits**

Run:

```bash
git log --oneline -5
```

Expected: the latest commits include frontend contract, grouped rendering, diagnostics, docs/version, and package commits.

- [ ] **Step 3: Push the current branch**

Run:

```bash
git push origin codex/smart-format-full-document-preview
```

Expected: push succeeds and GitHub contains `v0.12.11-alpha` commits.

## Self-Review Notes

- Spec coverage: 文档审查分组 is covered by Task 1 and Task 2. 格式审查分组 is covered by Task 1 and Task 2. 设置页诊断 is covered by Task 1 and Task 3. 脱敏 provider debug metadata is covered by Task 4. README/handoff/Dify manuals are covered by Task 5. Packaging and GitHub delivery are covered by Task 6 and Task 7.
- Protected logic: no task changes `/word/*` route names, Dify `/chat-messages` payload shape, or task-level API key fallback.
- Test coverage: frontend contract smoke test fails first, then passes after implementation; provider debug test fails first, then passes after backend enrichment; full regression runs before packaging.
