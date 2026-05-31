# AI-WPS 稳定增强版设计

日期：2026-05-31

目标版本：`v0.12.11-alpha`

适用范围：Word 侧 `智能编写`、`文档审查`、`格式审查`、`设置/诊断`

## 1. 背景

当前 `v0.12.10-alpha` 已将 Word 侧功能收敛为智能编写、文档审查、格式审查和设置。智能编写与任务级 Dify API Key 选路已经稳定；文档审查和格式审查的功能边界也已明确。格式审查不再承担自动排版写回，只基于标准模板输出检查意见。

现场问题主要集中在可读性和排错效率：

- 文档审查结果可以返回问题列表，但前台展示仍偏线性，不利于按问题类型快速定位。
- 格式审查结果包含规则、角色和当前值，但没有按格式类型聚合，长结果阅读成本高。
- 出现现场异常时，需要人工访问多个接口和日志才能判断是否请求 adapter、是否请求 Dify、使用了哪个任务密钥、为何 fallback。
- Dify 工作流手册需要与当前三任务结构、Markdown 输出限制和 `/provider/debug-last` 诊断口径保持一致。

本版本目标是“稳定可验收”，不新增自动排版、不扩大长文档大模型处理范围、不改变智能编写和任务级 API Key 选路。

## 2. 非目标

- 不恢复“智能排版自动写回”。
- 不新增 Excel、PPT 或跨应用功能。
- 不改变 Dify 官方 `/chat-messages` payload 结构。
- 不改变统一 API URL、统一 API Key、任务级 API Key 的回退链路。
- 不引入前端或后端新依赖。
- 不把全文长文档一次性送入 Dify。

## 3. 用户体验目标

### 3.1 文档审查

文档审查结果按问题类别分组展示：

- 错别字
- 语言表达
- 逻辑表达
- 通畅性
- 专业性

每条问题固定展示：

- 严重程度
- 位置
- 原文片段
- 问题说明
- 修改建议
- 建议改写

如果没有问题，显示简短结论和检查范围，不显示空分组。

### 3.2 格式审查

格式审查结果按规则类型分组展示：

- 页面设置
- 标题层级
- 正文格式
- 段落格式
- 图表题/注释
- 其他格式项

每条问题固定展示：

- 段落号
- 段落角色
- 当前值
- 模板要求
- 建议操作

结果顶部继续显示：

- 模板名称
- 检查范围
- 扫描段落数
- AI 识别段落数
- 本地兜底段落数
- 识别来源
- fallback 原因

### 3.3 设置页诊断

设置页新增“最近一次任务诊断”区域，来源优先使用 `/provider/debug-last`，辅以 `/provider/status`、`/provider/route-diagnostics` 和 `/provider/task-api-keys` 的摘要。

展示字段：

- 任务类型
- traceId
- adapter 状态
- provider 类型
- provider 是否配置
- 认证来源：统一密钥、任务密钥、环境变量或未配置
- 是否已进入 Dify 请求
- 请求路径
- 请求字段摘要
- 响应字段摘要
- fallback 原因
- 最近错误摘要

提供“刷新诊断”和“复制诊断信息”按钮。复制内容为脱敏文本，不包含完整原文和 API Key。

## 4. 数据与接口设计

### 4.1 不新增任务接口

继续使用当前接口：

- `POST /word/smart-write`
- `POST /word/document-review`
- `POST /word/format-review`
- `GET /provider/debug-last`
- `GET /provider/status`
- `GET /provider/route-diagnostics`
- `GET /provider/task-api-keys`

### 4.2 文档审查返回兼容

后端保持当前 `issues` 列表结构，不要求 Dify 返回新字段。前端按已有字段分组：

- `category`
- `severity`
- `location`
- `originalText`
- `problem`
- `suggestion`
- `suggestedRewrite`

未知 `category` 归入“其他问题”，但不作为默认可见分组标题，只有存在问题时显示。

### 4.3 格式审查返回兼容

后端保持当前 `issues` 列表结构，前端按 `ruleId` 做展示分组。

分组映射：

- `page_setup` -> 页面设置
- `style_name` -> 标题层级或正文格式，优先结合 `role`
- `font_name`、`font_size` -> 正文格式
- `line_spacing`、`alignment`、`first_line_indent` -> 段落格式
- `caption`、`note` 相关 role -> 图表题/注释
- 其他 -> 其他格式项

如果后端后续增加 `issueGroup` 字段，前端可优先使用该字段，但本版本不要求增加。

### 4.4 最近一次任务诊断

前端新增诊断聚合函数：

1. 请求 `/provider/debug-last`。
2. 请求 `/provider/status`。
3. 请求 `/provider/route-diagnostics`。
4. 请求 `/provider/task-api-keys`。
5. 将结果合成为一段 Markdown 文本，复用现有 Markdown 渲染能力。

所有展示和复制内容只使用后端已脱敏字段。

## 5. 前端设计

### 5.1 结果渲染

保留当前 `setResult(markdown)` 和安全 Markdown 渲染链路。新增纯前端格式化函数：

- `renderGroupedDocumentReview(data)`
- `renderGroupedFormatReview(data)`
- `renderProviderDiagnostics(debug, status, routes, taskKeys)`

旧函数可重命名或作为内部 helper 保留，但不再输出线性长列表。

### 5.2 设置页布局

在现有设置页诊断区域下方增加一个轻量面板：

- 标题：最近一次任务诊断
- 操作按钮：刷新诊断、复制诊断
- 内容区：Markdown 渲染后的诊断摘要

不新增复杂筛选，不新增图表。

### 5.3 长文档边界

继续保护当前格式审查抽取限制：

- 最多读取 80 段
- 每段最多 800 字
- 正文最多 12000 字
- 框选文本优先，不扫描全文

文档审查本版本不扩大全文抽取能力。如果未来发现全文审查也会卡死，应复用格式审查的限量抽取选项，但不在本设计中主动改变智能编写。

## 6. 后端设计

### 6.1 诊断字段补齐

优先复用 `ProviderClient` 当前 debug 记录能力。仅在必要时补充脱敏摘要字段，例如：

- `taskType`
- `traceId`
- `provider`
- `skipReason`
- `providerBaseUrlConfigured`
- `authSource`
- `url`
- `request.bodyKeys`
- `request.inputKeys`
- `response.bodyKeys`
- `error`

不得记录完整原文、完整 Dify 返回正文和 API Key。

### 6.2 服务逻辑边界

文档审查和格式审查服务不改变核心处理方式：

- 文档审查仍由独立 Dify 工作流生成质量审查结果。
- 格式审查仍由本地规则为主，AI 段落角色识别为可选增强。
- Dify 异常、非 JSON 或超时继续 fallback，不能阻断前台结果。

## 7. 文档设计

更新以下文档：

- `README.md`
- `README-ZH.md`
- `docs/codex-handoff.md`
- `docs/operations/dify-smart-write-workflow.md`
- `docs/operations/dify-document-review-workflow.md`
- `docs/operations/dify-format-review-workflow.md`

文档重点：

- `v0.12.11-alpha` 的功能边界。
- 三任务 Dify API Key 配置方式。
- 文档审查在 Dify 只能输出 Markdown 时，如何用 `json` 代码块返回可解析问题列表。
- 格式审查的 fallback 是正常保护机制，不等同于功能失败。
- `/provider/debug-last` 与设置页诊断面板的对应关系。

## 8. 测试计划

### 8.1 前端测试

- `formal-plugin-kit/tests/layout-smoke.test.js`
  - 校验诊断面板存在。
  - 校验刷新诊断和复制诊断按钮存在。
  - 校验结果渲染函数引用存在。

- `formal-plugin-kit/tests/taskpane-helpers.test.js`
  - 如新增纯 helper，则测试 Markdown 安全渲染和诊断摘要转义。

### 8.2 后端测试

- `adapter_service/tests/test_enterprise_provider.py`
  - 校验 debug-last 脱敏字段完整。
  - 校验不泄露 API Key 和完整原文。

- `adapter_service/tests/test_word_document_review.py`
  - 校验文档审查保留 category、severity、suggestion 等字段。

- `adapter_service/tests/test_word_format_review.py`
  - 校验格式审查 summary 仍包含 AI 识别和 fallback 摘要。

### 8.3 回归命令

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
git diff --check
```

## 9. 验收标准

- 智能编写仍可正常命中 `word.smart_write` 对应 Dify 工作流。
- 文档审查结果按类别分组，用户能直接看到每类问题和建议改写。
- 格式审查结果按格式类型分组，用户能直接看到当前值、模板要求和建议操作。
- 设置页能显示最近一次任务诊断，且可复制脱敏诊断信息。
- 任一任务失败时，前台错误提示能区分 adapter 不可达、provider 未配置、Dify 返回不可解析和本地 fallback。
- 不泄露完整 API Key、完整原文和完整模型返回。
- 现有三任务 API 和任务级 API Key 选路逻辑不变。

## 10. 风险与缓解

- 风险：诊断面板暴露过多信息。
  - 缓解：只展示 debug-last 已脱敏字段，不展示完整正文和密钥。

- 风险：前端结果分组改变用户复制内容的结构。
  - 缓解：复制内容使用同一份分组 Markdown，保持可读，不改变智能编写写回原文逻辑。

- 风险：格式审查分组依赖 `ruleId` 和 `role`，部分问题可能分组不准。
  - 缓解：提供“其他格式项”兜底，后续可在后端增加 `issueGroup` 字段增强。

- 风险：目标机继续加载旧前端资源。
  - 缓解：版本提升到 `0.12.11-alpha` 时同步更新 taskpane 静态资源参数和 Ribbon `build` 参数。
