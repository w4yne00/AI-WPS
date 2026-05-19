# Codex Handoff - AI-WPS

更新时间：2026-05-19

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

当前版本：`v0.11.2-alpha`

版本规则号：`AI-WPS-P1-WORD-0.11.2-20260519`

## 1. 项目状态

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 三层架构。

当前版本为收敛修复版：`v0.11.0-alpha` 和 `v0.11.1-alpha` 的多工作流路由、每任务 Key、Workflow Start 自定义变量路径在目标机仍出现“模型结果原样返回原文”。`v0.11.2-alpha` 先回归早期稳定路径：所有 AI 功能统一调用一条 Dify Chat/Chatflow `/chat-messages`，adapter 将完整中文任务提示词放入顶层 `query`，由 Dify 应用通过系统变量 `sys.query` 读取。

## 2. 本版本关键变化

- 运行路径停用 `taskRoutes` 路由选择，不再按任务选择不同 `path`、`payloadStyle`、`apiKeyRef`。
- 默认 provider 改为 `enterprise-dify-chat`，默认 `providerChatPath=/chat-messages`。
- Dify 请求体统一为：

```json
{
  "inputs": {},
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

- 智能编写、旧改写兼容、格式校对 AI 审校、技术文档审查都只向 Dify 发送完整 `query`，不再发送 `source_text`、`write_action` 等自定义 Start 字段。
- 设置页恢复统一 Dify Chat API Key 保存/清除控件，移除“任务接口”和每任务密钥配置区。
- `/config` 和 `/health` 返回 `providerAuthSource`，`taskRoutes` 固定为空摘要，`taskRouteConfiguredCount=0`。
- `/provider/route-diagnostics` 返回统一 Chat endpoint 的脱敏诊断，不再返回每任务路由。

## 3. 需要重点保护的既有逻辑

- WPS Ribbon 五个入口：智能编写、格式校对、智能排版、技术文档审查、设置。
- 智能编写 UI 中的动作、风格、侧重点、篇幅、用户补充要求，以及“不允许原样返回”的提示词约束。
- 未配置 URL 或统一 API Key 时的 mock 回退能力，避免离线开发和目标机未配 key 时功能硬失败。
- 格式校对本地规则、模板加载、`documentStructure` 抽取和本地模板兜底。
- 技术文档审查三类文档及其默认提示词。
- `uvicorn` 优先、`standalone` 兜底的 adapter 启动方式，以及旧进程版本替换逻辑。

## 4. 当前关键文件

- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、统一 API Key、模型结果解析和各任务提示词调用。
- `adapter_service/app/core/config.py`：读取 adapter 配置；不再从示例配置自动注入默认任务路由。
- `adapter_service/app/api/config.py`、`adapter_service/app/api/health.py`、`adapter_service/app/api/provider.py`：配置、健康检查和统一密钥接口。
- `adapter_service/standalone_adapter.py`：standalone 模式需与 FastAPI 输出保持一致。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`、`taskpane.js`：设置页统一 API URL + 统一 API Key；任务区调用 `/word/smart-write`。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages`、空 `taskRoutes`。
- `adapter-start-kit/scripts/start_uvicorn_adapter.sh`：`EXPECTED_VERSION=0.11.2-alpha`。

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
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
bash packaging/build_phase1_delivery_kit.sh
```

本次已执行结果：

- Python 单测：`48 tests OK (skipped=9)`；跳过项为本机缺少 `pydantic` / `fastapi` 时的条件测试。
- JS 布局冒烟：通过。
- `taskpane.js` 语法检查：通过。
- `compileall`：通过。
- `git diff --check`：通过。
- 一期交付包已生成：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260519.tar.gz`。
- 包内校验通过：`start_uvicorn_adapter.sh` 为 `0.11.2-alpha`；`adapter.example.json` 为 `enterprise-dify-chat` + `/chat-messages` + 空 `taskRoutes`；任务窗格包含统一密钥控件且不包含 `task-routes-list`。

## 8. 下一轮目标机验证建议

继续基于 `v0.11.2-alpha` 在目标机验证单 Chatflow 闭环：

1. 设置页只配置统一 API URL 和统一 Dify Chat API Key。
2. Dify 应用使用 Chat/Chatflow `/chat-messages`，LLM 节点从系统变量 `sys.query` 读取完整提示词。
3. `/provider/route-diagnostics` 应显示 `url=https://.../v1/chat-messages`、`payloadStyle=chat`、`routes={}`。
4. 智能编写请求不应再依赖 `source_text`、`write_action` 等 Start 自定义字段。
5. 若仍原样返回，优先检查 Dify 应用提示词是否直接引用 `sys.query`，以及应用类型/API Key 是否属于 Chat/Chatflow 而不是 Workflow `/workflows/run`。
