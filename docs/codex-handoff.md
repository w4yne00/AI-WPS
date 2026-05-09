# Codex Handoff - AI-WPS

更新时间：2026-05-09

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

当前版本：`v0.9.0-alpha`

版本规则号：`AI-WPS-P1-WORD-0.9.0-20260509`

## 1. 项目目标和当前阶段

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标运行环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 的三层架构。

当前阶段是一期 Word 能力收口和 provider 路线收口：

- 平台底座：WPS 插件框架、本地 adapter、企业 AI provider 接入、离线安装体系、目标机验收体系。
- Word 能力：智能改写、智能续写、格式校对、智能排版预览、技术文档审查。
- Provider 路线：单 provider、单 API Key、单 Dify 工作流，通过 `task_id` 判断节点在 Dify 内部分流。

## 2. 已完成的功能

### WPS 插件侧

- `WPS AI 助理` Ribbon 选项卡。
- 六个入口：智能改写、智能续写、格式校对、智能排版、技术文档审查、设置。
- 单任务窗格模式：点击不同入口时复用任务窗格并切换当前 Word 工作流。
- 当前范围识别：光标单点为全文，框选文字为选中文本。
- 选中文本改写和续写。
- 格式校对随请求提交 `documentStructure`，包含段落、标题和基础样式结构。
- 技术文档审查支持文档类型和可编辑审查提示词。
- 设置页支持单一模型提供商名称、API URL、API Key 配置。
- 设置页识别 `enterprise-dify-workflow` 为 Dify 工作流。
- 结果预览只显示模型输出，支持复制结果。

### adapter 侧

- FastAPI/uvicorn 正式模式，standalone 兜底模式。
- `/health` 健康检查，返回版本、运行模式、provider 状态和 `taskRouteCount`。
- `/config` 运行配置摘要，返回 provider 信息和安全的 `taskRoutes` 摘要。
- `/templates` 模板列表。
- `/provider/status` provider 状态。
- `/provider/base-url` 保存模型提供商名称和 API URL。
- `/provider/api-key` 保存 API Key 到 adapter 本地文件。
- `DELETE /provider/api-key` 清空本地 API Key。
- `/word/rewrite` 智能改写和续写。
- `/word/proofread` 格式校对和文档质量审校。
- `/word/format-preview` 智能排版预览。
- `/word/technical-review` 技术文档审查。
- 新增轻量 `taskRoutes` 配置，按任务解析 `task_id`。
- ProviderClient 支持两类请求体：legacy `/chat-messages` 格式和 Dify `/workflows/run` 的 `inputs/response_mode/user` 格式。
- 未配置 provider 时保留 mock 回退能力。

### 模板和规则

- 通用模板：`general-office`。
- 公司标准 Word 模板：`technical-file-format-requirements`。
- 支持标题层级、字体、字号、行距、缩进、重复空格、中文标点前空格等本地规则。
- 支持 AI 问题分类：`format`、`typo`、`grammar`、`expression`、`logic`、`heading_consistency`。
- 技术审查支持问题分类：`accuracy`、`terminology`、`design`、`requirement`。

## 3. 关键设计决策

### 单 provider + 单 API Key + 单 Dify 工作流

Dify 原生 Service API 未提供标准 `appName` 路由能力。当前一期不做多 provider 和多任务密钥，而是让 adapter 调用一个 Dify 工作流，并传入 `task_id`：

```text
word.rewrite
word.continue
word.proofread
word.format_preview
word.technical_review
```

Dify 工作流通过判断节点分流。

### taskRoutes 保留为演进接口

一期 `taskRoutes` 只包含 `taskId` 和 `enabled`，用于稳定 adapter 内部任务映射。下一版本可以扩展 `path`、`apiKeyRef`、`responseMode`、`workflowId`、`fallbackToDefault`，演进为多工作流/多任务密钥，而不推翻现有接口。

### 请求协议兼容

- `enterprise-dify-workflow` 或 path 为 `/workflows/run` 时，adapter 发送 Dify workflow 格式：`inputs`、`response_mode`、`user`。
- `enterprise-chat-api` 或 path 为 `/chat-messages` 时，adapter 保持旧格式：`input_data`、`query`、`mode`、`user`。

### 密钥只保存在 adapter

前端不保存 API Key。密钥来源：

- 环境变量：`ENTERPRISE_AI_API_KEY`
- 本地文件：`adapter_service/run/provider_api_key`

## 4. 已修改/新增的文件清单

### 核心代码

- `adapter_service/app/core/config.py`
- `adapter_service/app/services/provider_client.py`
- `adapter_service/app/api/config.py`
- `adapter_service/app/api/health.py`
- `adapter_service/standalone_adapter.py`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`

### 测试

- `adapter_service/tests/test_enterprise_provider.py`

### 配置和文档

- `config/adapter.example.json`
- `docs/phase1-provider-task-routes-design.md`
- `docs/phase1-proofread-next-version-backlog.md`
- `docs/operations/dify-single-workflow-task-routing.md`
- `docs/operations/phase1-v0.9.0-deployment.md`
- `docs/operations/runtime-config.md`
- `docs/superpowers/plans/2026-05-09-provider-task-routes.md`
- `docs/codex-handoff.md`
- `README.md`
- `README-ZH.md`
- `phase1-delivery-kit/README.md`

### 打包

- `packaging/build_phase1_delivery_kit.sh`
- `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260509.tar.gz`

## 5. 每个文件的作用

- `adapter_service/app/core/config.py`：加载 provider 和 `taskRoutes`，提供 `TaskRoute`、`task_routes_to_dict`。
- `adapter_service/app/services/provider_client.py`：解析任务 route，构造 Dify workflow 或 legacy chat 请求体，调用企业 provider，解析结果。
- `adapter_service/app/api/config.py`：返回运行配置和 `taskRoutes` 摘要。
- `adapter_service/app/api/health.py`：返回健康状态和 task route 数量。
- `adapter_service/standalone_adapter.py`：standalone 模式下返回相同的 health/config 元数据。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`：设置页识别 `enterprise-dify-workflow` provider 类型。
- `config/adapter.example.json`：默认单 Dify 工作流配置和五类 Word task route。
- `docs/operations/dify-single-workflow-task-routing.md`：Dify 工作流部署手册。
- `docs/operations/phase1-v0.9.0-deployment.md`：新版本目标机部署手册。
- `docs/phase1-provider-task-routes-design.md`：一期 taskRoutes 设计说明。
- `docs/phase1-proofread-next-version-backlog.md`：下一版本遗留能力备忘。
- `packaging/build_phase1_delivery_kit.sh`：把新增运维文档纳入一期交付总包。

## 6. 当前未完成事项

- Dify 工作流需要在内网平台上按手册实际搭建和验证。
- 智能排版当前仍以本地模板规则为主，AI 参与排版建议可在下一版本增强。
- 设置页暂不暴露每个 task route 的高级配置。
- 多任务密钥、多工作流拆分留到下一版本。

## 7. 已知问题和风险

- 本地开发环境当前 `python3` 未安装 `pytest`，只能用 `unittest` 跑不依赖 FastAPI/Pydantic 的测试；FastAPI 相关测试需在具备依赖的环境或目标离线依赖安装后执行。
- 如果企业封装 API 虽然路径为 `/workflows/run`，但请求体仍要求旧 `input_data/query` 格式，需要把 `providerType` 临时设回 `enterprise-chat-api` 或增加显式 payload style 配置。
- Dify 工作流输出必须严格遵守 JSON schema，否则 adapter 解析会降级为空结果或只保留文本 summary。
- 当前 task route 的 `enabled=false` 只作为配置状态展示，尚未作为强制禁用逻辑。

## 8. 数据结构、接口、配置、环境变量说明

### adapter 配置

```json
{
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerChatPath": "/workflows/run",
  "providerMode": "blocking",
  "taskRoutes": {
    "word.rewrite": {"taskId": "word.rewrite", "enabled": true},
    "word.continue": {"taskId": "word.continue", "enabled": true},
    "word.proofread": {"taskId": "word.proofread", "enabled": true},
    "word.format_preview": {"taskId": "word.format_preview", "enabled": true},
    "word.technical_review": {"taskId": "word.technical_review", "enabled": true}
  }
}
```

### Dify workflow 请求

```json
{
  "inputs": {
    "task_id": "word.proofread",
    "taskType": "word.proofread",
    "scene": "word",
    "trace_id": "word-proofread-...",
    "query": "..."
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

### 环境变量

- `ENTERPRISE_AI_API_KEY`：企业 Dify/API 密钥。

## 9. 测试命令和验证结果

已执行：

```bash
python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

结果：`OK (skipped=1)`。

跳过原因：本机缺少 `pydantic`，`test_document_structure_is_accepted_in_word_request` 按测试条件自动跳过。

已尝试：

```bash
python3 -m pytest adapter_service/tests/test_enterprise_provider.py -q
python3 -m unittest discover adapter_service/tests -v
```

结果：失败，原因是本地 Python 环境没有安装 `pytest`、`fastapi`、`pydantic`，且 discover 模式需要设置 `PYTHONPATH=adapter_service`。

## 10. 下一轮任务建议 Prompt

```text
继续基于 v0.9.0-alpha 验证目标机 Dify 单工作流 task_id 路由。请根据 docs/operations/dify-single-workflow-task-routing.md，在 adapter 和插件侧补充必要的联调日志与错误提示，重点验证 word.proofread 和 word.technical_review 的 JSON 输出解析稳定性；如果内网 Dify 实际请求格式与 /workflows/run 标准格式不一致，请设计 providerPayloadStyle 兼容配置。
```
