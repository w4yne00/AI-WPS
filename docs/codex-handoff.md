# Codex Handoff - AI-WPS

更新时间：2026-05-22

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

当前版本：`v0.11.8-alpha`

版本规则号：`AI-WPS-P1-WORD-0.11.8-20260522`

## 1. 项目状态

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 三层架构。

本轮根据 Dify 官方 `/chat-messages` 文档重新校正 adapter 请求体。官方字段为 `query`、`inputs`、`user`、`response_mode`、`conversation_id`、`files`。由于目标机 Dify 开始节点同时存在自定义 `query` 和系统 `sys.query`，adapter 现在把同一份完整 WPS 任务提示词同时写入顶层 `query` 和 `inputs.query`。

本轮还修复任务窗口结果预览的展示方式：Dify 返回的 Markdown 不再作为纯文本放进 `<pre>`，而是在任务窗口中按安全 Markdown 子集渲染；复制和写回 WPS 仍使用模型返回的原始文本。

2026-05-22 继续增强结果预览：任务窗口只显示 Markdown 渲染成品，保留正文段落和单换行，并补充分隔线与窄窗可横向滚动的表格样式，避免模型输出在任务窗口里挤成单段纯文本。

本轮根据目标机日志继续收敛 adapter 运维诊断：`provider=mock` 表示任务在 provider 配置不足时命中本地回退，未向 Dify 发起真实 HTTP 请求。启动包运维脚本现在以 uvicorn 为唯一管理入口，并把 provider 配置状态、路由诊断和最后一次转发诊断一起暴露出来。

2026-05-22 目标机日志又暴露了 uvicorn 生命周期问题：`/health` 每次请求会重新读取 settings，因此可显示 `providerConfigured=true`；但 `/word` 路由模块此前在 uvicorn 启动时创建全局 `WordRewriter -> ProviderClient`，会缓存启动时 URL 为空的旧 settings，导致设置页后来保存 URL 后智能编写仍走 mock。本版本在默认 `ProviderClient()` 做配置判定和转发前刷新 settings，修复该不一致。

## 2. 本版本关键变化

- 运行路径继续停用 `taskRoutes` 路由选择，不再按任务选择不同 `path`、`payloadStyle`、`apiKeyRef`。
- 默认 provider 保持 `enterprise-dify-chat`，默认 `providerChatPath=/chat-messages`。
- Dify 请求体统一为：

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

- 不再发送 `input_data` 或 `mode`。
- 智能编写、旧改写兼容、格式校对 AI 审校、技术文档审查都只构造一份完整提示词；任务细节嵌入提示词文本，不再作为自定义 Start 字段分散发送。
- 新增脱敏诊断接口：`GET /provider/debug-last`，用于查看最后一次 provider 调用的请求键、`inputs` 键、query 长度、响应键、answer 长度和错误摘要。
- 设置页保持统一 Dify Chat API Key 保存/清除控件，无“任务接口”和每任务密钥配置区。
- 结果预览区改为 Markdown 渲染，支持段落、单换行、标题、列表、表格、分隔线、引用、行内代码、代码块和安全链接；HTML 会转义，`javascript:` 链接不会渲染为可点击链接。
- 未配置 URL 或统一 API Key 时，mock 回退也会写入 `/provider/debug-last`，返回 `provider=mock`、`skipReason=provider_not_configured`、`providerBaseUrlConfigured` 和 `authSource`。
- `start_adapter.sh`、`restart_adapter.sh` 收敛到 `start_uvicorn_adapter.sh`；`check_health.sh`、`status_adapter.sh`、`show_logs.sh`、`stop_adapter.sh` 补足 uvicorn/provider 运维诊断。
- 默认构造的 `ProviderClient()` 在 `is_configured()` 和 `post_task()` 前重新加载配置文件，避免 uvicorn 长生命周期 Word 服务持有设置页保存前的 provider URL。

## 3. 需要重点保护的既有逻辑

- WPS Ribbon 五个入口：智能编写、格式校对、智能排版、技术文档审查、设置。
- 智能编写 UI 中的动作、风格、侧重点、篇幅、用户补充要求，以及“不允许原样返回”的提示词约束。
- 未配置 URL 或统一 API Key 时的 mock 回退能力。
- 格式校对本地规则、模板加载、`documentStructure` 抽取和本地模板兜底。
- 技术文档审查三类文档及其默认提示词。
- `uvicorn` 优先、`standalone` 兜底的 adapter 启动方式，以及旧进程版本替换逻辑。

## 4. 当前关键文件

- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、统一 API Key、脱敏 provider 调试记录、模型结果解析和各任务提示词调用。
- `adapter_service/app/core/config.py`：读取 adapter 配置；不再从示例配置自动注入默认任务路由。
- `adapter_service/app/api/config.py`、`adapter_service/app/api/health.py`、`adapter_service/app/api/provider.py`：配置、健康检查、统一密钥和 provider 诊断接口。
- `adapter_service/standalone_adapter.py`：standalone 模式需与 FastAPI 输出保持一致。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`、`taskpane.js`、`taskpane.css`、`taskpane-helpers.js`：设置页统一 API URL + 统一 API Key；任务区调用 `/word/smart-write`；结果区安全渲染 Markdown。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages`、空 `taskRoutes`。
- `adapter-start-kit/scripts/start_uvicorn_adapter.sh`：`EXPECTED_VERSION=0.11.8-alpha`。
- `adapter-start-kit/scripts/*.sh`：目标机 uvicorn adapter 启停、状态、日志、健康检查和环境检查入口。

## 5. 配置和接口

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
  "taskRoutes": {}
}
```

关键接口：

```text
GET    /health
GET    /config
GET    /provider/status
GET    /provider/route-diagnostics
GET    /provider/debug-last
POST   /provider/base-url
POST   /provider/api-key
DELETE /provider/api-key
POST   /word/smart-write
POST   /word/proofread
POST   /word/format-preview
POST   /word/technical-review
```

每任务密钥接口已从 FastAPI 和 standalone 后台移除，避免目标机继续维护与路由选择相关的旧配置。

## 6. 设计和计划文档

```text
docs/superpowers/specs/2026-05-19-single-chatflow-sys-query-design.md
docs/superpowers/plans/2026-05-19-single-chatflow-sys-query-plan.md
docs/superpowers/specs/2026-05-20-chat-messages-input-data-mode-design.md
docs/superpowers/plans/2026-05-20-chat-messages-input-data-mode-plan.md
docs/superpowers/specs/2026-05-21-dify-official-chat-payload-and-debug-design.md
docs/superpowers/plans/2026-05-21-dify-official-chat-payload-and-debug-plan.md
docs/superpowers/specs/2026-05-21-markdown-result-preview-design.md
docs/superpowers/plans/2026-05-21-markdown-result-preview-plan.md
docs/superpowers/specs/2026-05-21-uvicorn-adapter-operations-design.md
docs/superpowers/plans/2026-05-21-uvicorn-adapter-operations-plan.md
docs/superpowers/specs/2026-05-22-provider-settings-refresh-design.md
docs/superpowers/plans/2026-05-22-provider-settings-refresh-plan.md
docs/superpowers/specs/2026-05-22-markdown-result-preview-enhancement-design.md
docs/superpowers/plans/2026-05-22-markdown-result-preview-enhancement-plan.md
```

历史方案仍保留作背景：

```text
docs/superpowers/specs/2026-05-17-smart-write-redesign.md
docs/superpowers/specs/2026-05-19-task-route-key-diagnostics-design.md
```

## 7. 测试命令

本版本应执行：

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite -v
node formal-plugin-kit/tests/layout-smoke.test.js
node formal-plugin-kit/tests/taskpane-helpers.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
bash packaging/build_phase1_delivery_kit.sh
```

本次已执行结果：

- Python 单测：`53 tests OK (skipped=9)`；新增回归覆盖默认 `ProviderClient()` 在 uvicorn 长生命周期下重新读取设置页保存后的 provider URL。
- JS 布局冒烟：通过。
- JS helper 测试：Markdown 段落/单换行、表格、分隔线、基础格式和危险 HTML/链接转义通过。
- `taskpane.js` 语法检查：通过。
- Adapter start-kit Bash 脚本 `bash -n`：通过。
- 本机 uvicorn 运行时检查：当前环境缺少 `uvicorn`；`start_adapter.sh` 已验证会明确提示安装离线运行依赖，未在本机启动真实 uvicorn 进程。
- `compileall`：通过。
- `git diff --check`：通过。
- 一期交付包已生成：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260522.tar.gz`。
- 包内校验通过：`start_uvicorn_adapter.sh` 为 `0.11.8-alpha`；`manifest.json` 为 `0.11.8-alpha`；`provider_client.py` 包含 `reload_settings` / `refresh_settings` 并在 `is_configured()`、`post_task()` 前刷新配置；`taskpane-helpers.js` 含段落 `<br>`、表格和分隔线渲染；`taskpane.css` 含 Markdown 表格和正常 HTML 流样式；既有 Dify Chat payload 和 mock 诊断保留。

## 8. 下一轮目标机验证建议

继续基于 `v0.11.8-alpha` 在目标机验证单 Chatflow 闭环：

1. 设置页只配置统一 API URL 和统一 Dify Chat API Key。
2. Dify 应用使用 Chat/Chatflow `/chat-messages`，LLM 节点可以引用系统 `sys.query`，也可以引用开始节点自定义 `query`。
3. 先执行 `bash scripts/check_health.sh`，确认 `adapter_mode=uvicorn` 且 `provider_configured=true`。
4. `/provider/debug-last` 在真实转发后应显示 `bodyKeys` 包含 `inputs`、`query`、`response_mode`，`inputsKeys=["query"]`；若仍显示 `provider=mock` 和 `skipReason=provider_not_configured`，说明配置尚未进入真实转发。
5. 若结果仍原样返回，先查看 `/provider/debug-last` 的 `response.answerLength`、`error` 和 query 长度，再对照 Dify 应用日志确认 LLM 节点实际收到的变量。
