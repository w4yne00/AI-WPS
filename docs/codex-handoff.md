# Codex Handoff - AI-WPS

更新时间：2026-05-29

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`codex/smart-format-full-document-preview`

当前版本：`v0.12.9-alpha`

版本规则号：`AI-WPS-P1-WORD-0.12.9-20260529`

## 1. 当前项目状态

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 三层架构。

当前版本将 Word 侧任务收敛为四个 Ribbon 入口：

- 智能编写：`POST /word/smart-write`，任务类型 `word.smart_write`。
- 文档审查：`POST /word/document-review`，任务类型 `word.document_review`。
- 格式审查：`POST /word/format-review`，任务类型 `word.format_review`。
- 设置：统一 API URL、统一 Dify API Key、任务级 API Key、诊断信息。

本轮按用户确认的“方式 1”执行：删除无用旧接口和旧前台入口，避免后续继续维护多套审查/排版代码。智能编写及其 Dify 路由、任务级 API Key 逻辑保持不变；原“智能排版”不再执行自动排版写回，改为“格式审查”，只按标准模板输出格式问题；原“格式校对”和“技术文档审查”合并为“文档审查”，专注错别字、语言逻辑、通畅性和对应文档类型专业性评估。

## 2. 当前接口与 Dify 入参

adapter 继续使用 Dify 官方 `/chat-messages` 字段：

```json
{
  "inputs": {
    "query": "完整中文任务提示词..."
  },
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

所有任务都通过同一 `providerBaseUrl + providerChatPath` 发送。任务级 API Key 只决定认证密钥，不决定 path、payloadStyle 或 outputKey。未配置任务级 key 时回退统一 key。

推荐配置：

```json
{
  "servicePort": 18100,
  "providerName": "企业大模型接口",
  "providerType": "enterprise-dify-chat",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerApiKeyEnv": "ENTERPRISE_AI_API_KEY",
  "providerChatPath": "/chat-messages",
  "providerMode": "blocking",
  "taskApiKeyRefs": {
    "word.smart_write": "word_smart_write",
    "word.document_review": "word_document_review",
    "word.format_review": "word_format_review"
  },
  "taskRoutes": {}
}
```

当前关键接口：

```text
GET    /health
GET    /config
GET    /templates
GET    /provider/status
GET    /provider/route-diagnostics
GET    /provider/debug-last
GET    /provider/task-api-keys
POST   /provider/base-url
POST   /provider/api-key
DELETE /provider/api-key
POST   /provider/task-api-key
DELETE /provider/task-api-key/{taskType}
POST   /word/smart-write
POST   /word/document-review
POST   /word/format-review
```

## 3. 本版本关键变化

- 前台 Ribbon 入口调整为“智能编写 / 文档审查 / 格式审查 / 设置”。
- 删除旧 Word 路由和服务文件，只保留当前三条任务 API。
- 智能编写只改前台展示：表达风格、侧重点、篇幅下方说明文字已统一挪入“当前要求”窗格，窗格按内容自动撑开；后台提示词和接口逻辑不改。
- 文档审查复用原技术审查的界面形态：文档类型为技术方案、合同验收文档、测试大纲及细则；不再选择文档模板，不再检查格式合规。
- 文档审查支持选中文本和全文审查，用户可通过框选段落分段规避 Dify 输出长度和模型上下文限制。
- 格式审查固定使用 `technical-file-format-requirements` 模板，不再提供模板下拉，不提供“应用预览”写回。
- 格式审查保留 AI 段落角色识别能力；Dify 不可用或返回不可解析时回退本地规则。
- 任务窗口结果区继续只显示渲染后的 Markdown 成品；复制和写回仍使用原始模型文本。
- adapter 版本、前端缓存参数、manifest、启动脚本版本统一更新到 `0.12.9-alpha`。

## 4. 需要重点保护的既有逻辑

- 智能编写 Dify 调用、任务级 API Key 选路和“不允许原样返回”的提示词约束。
- 智能编写新菜单值和旧值兼容映射：前端只展示新选项，adapter 仍识别旧 payload 值。
- `/chat-messages` 官方 payload：顶层 `query` 和 `inputs.query` 都必须携带同一份完整提示词。
- 统一 API URL + 统一 API Key + 任务级 API Key 的回退链路。
- `/provider/debug-last` 脱敏诊断，不泄露完整原文和密钥。
- Markdown 安全渲染：HTML 转义，危险链接不可点击，复制仍保留原始文本。
- WPS COM 对象容错：段落集合、选区文本、全文 Range 和宿主对象清洗逻辑不能被审查功能改动破坏。
- uvicorn 优先、standalone 兜底的 adapter 启动方式，以及旧进程版本替换逻辑。

## 5. 当前关键文件

- `adapter_service/app/api/word.py`：当前 Word 三任务路由。
- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、任务级 API Key、脱敏 provider 调试记录、智能编写/文档审查/格式审查 provider 调用。
- `adapter_service/app/services/word/document_reviewer.py`：文档审查服务，负责选区/全文、默认提示词、模型结果解析和问题列表输出。
- `adapter_service/app/services/word/format_reviewer.py`：格式审查服务，负责模板规则检查、可选 AI 段落角色识别和本地兜底。
- `adapter_service/app/core/models.py`：当前请求/响应模型。
- `adapter_service/standalone_adapter.py`：standalone 模式，与 FastAPI 当前输出保持一致。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`、`taskpane.js`、`taskpane.css`、`taskpane-helpers.js`：当前任务窗格、设置页、Markdown 渲染和 WPS 读取逻辑。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`、`ribbon.js`：当前 Ribbon 入口和图标映射。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages` 和三任务 `taskApiKeyRefs`。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify 配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 配置手册。
- `docs/superpowers/plans/2026-05-29-review-mode-consolidation-plan.md`：本轮执行计划。

## 6. 本轮测试命令

已执行：

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
```

当前结果：

- Python 单测：`64 tests OK (skipped=3)`。
- JS layout smoke：通过。
- JS helpers：通过。
- `taskpane.js`、`ribbon.js` 语法检查：通过。

说明：当前 bundled Python 环境有 Pydantic，但没有 FastAPI，因此 FastAPI TestClient 相关 3 项按测试文件 skip；不依赖 FastAPI 的 provider、服务、前端、打包脚本和契约测试均已通过。

## 7. 目标机验证建议

1. 关闭并重新打开 WPS，确认设置页“前端版本”为 `0.12.9-alpha`。
2. 设置页配置统一 API URL，例如 `https://aibot.chinasatnet.com.cn/v1`。
3. 分别保存“智能编写”“文档审查”“格式审查”的任务级 API Key。
4. 执行“智能编写”，确认 `/provider/debug-last.taskType=word.smart_write`，Dify 后台命中智能编写应用。
5. 执行“文档审查”，优先框选 3 到 10 个段落联调；确认 `/provider/debug-last.taskType=word.document_review`，结果区显示审查摘要和问题列表。
6. 执行“格式审查”，可框选局部段落；确认 `/provider/debug-last.taskType=word.format_review` 或结果区显示本地规则兜底来源。
7. 如果 Dify 后台有调用但 WPS 结果为空，检查 Dify 回复节点是否绑定 LLM 输出正文，而不是开始节点原始 query。
8. 如果 `provider=mock` 或 `skipReason=provider_not_configured`，检查任务级 API Key 文件是否已保存，以及统一 API URL 是否带 `/v1`。

## 8. 遗留项

- 智能排版暂缓：目标机已确认任务级 API Key 选路可命中独立 Dify 工作流，但长文档角色识别受 Dify 输出最大值和模型上下文窗口限制影响。当前版本不再尝试自动写回排版，改为“格式审查”。
- 文档审查要求 Dify 输出 Markdown 中的 JSON 代码块。若现场 Dify 只能输出普通 Markdown，也应至少保留一个合法 `json` 代码块；adapter 会从代码块中提取问题列表。
- 历史操作文档中仍可能保留旧版本部署背景；当前交付和配置以本 handoff、README、`dify-document-review-workflow.md`、`dify-format-review-workflow.md` 为准。
