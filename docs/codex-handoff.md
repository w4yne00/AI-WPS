# Codex Handoff - AI-WPS

更新时间：2026-05-11

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

当前版本：`v0.10.1-alpha`

版本规则号：`AI-WPS-P1-WORD-0.10.1-20260513`

## 1. 项目目标和当前阶段

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标运行环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 的三层架构。

当前阶段是一期 Word 能力收口和 provider 路由升级：

- 平台底座：WPS 插件框架、本地 adapter、企业 AI provider 接入、离线安装体系、目标机验收体系。
- Word 能力：智能改写、智能续写、格式校对、智能排版预览、技术文档审查。
- Provider 路线：单 `providerBaseUrl` + `taskRoutes`，每个任务可配置独立 `path`、`apiKeyRef`、`payloadStyle`。

## 2. 已完成的功能

### WPS 插件侧

- `WPS AI 助理` Ribbon 选项卡。
- 六个入口：智能改写、智能续写、格式校对、智能排版、技术文档审查、设置。
- 单任务窗格模式：点击不同入口时复用任务窗格并切换当前 Word 工作流。
- 当前范围识别：光标单点为全文，框选文字为选中文本。
- 选中文本改写和续写。
- 智能改写/续写任务窗格会显性展示风格、侧重点、篇幅和输出约束对应的提示词片段，并将用户输入区按当前任务标记为“改写提示词”或“续写提示词”。
- 格式校对随请求提交 `documentStructure`，包含段落、标题和基础样式结构。
- 技术文档审查支持三类文档：技术方案、合同验收文档、测试大纲和细则，并按文档类型自动切换默认审查提示词。
- 模板下拉会合并后端 `/templates` 返回结果和本地兜底模板。
- 设置页支持单一模型提供商名称和 API URL 配置。
- 设置页新增“任务接口”区域，可查看每个任务的 `path`、`payloadStyle`、`apiKeyRef` 和密钥配置状态，并保存/清除每任务 API Key。
- 结果预览只显示模型输出，支持复制结果。

### adapter 侧

- FastAPI/uvicorn 正式模式，standalone 兜底模式。
- `/health` 健康检查，返回版本、运行模式、provider 状态和 `taskRouteCount`。
- `/config` 返回 provider 信息、安全的 `taskRoutes` 摘要、每任务密钥配置状态。
- `/templates` 模板列表。
- `/provider/status` provider 状态。
- `/provider/base-url` 保存模型提供商名称和 API URL。
- `/provider/api-key` 保存默认 API Key 到 `adapter_service/run/provider_api_key`。
- `/provider/task-api-key` 保存每任务 API Key 到 `adapter_service/run/provider_api_keys/<apiKeyRef>`。
- `DELETE /provider/api-key` 清空默认 API Key。
- `DELETE /provider/task-api-key/{apiKeyRef}` 清空指定任务 API Key。
- `/word/rewrite` 智能改写和续写。
- `/word/proofread` 格式校对和文档质量审校。
- `/word/format-preview` 智能排版预览。
- `/word/technical-review` 技术文档审查。
- ProviderClient 支持按任务选择接口路径、请求体结构和密钥。
- ProviderClient 支持 Dify chat `/chat-messages` 和 workflow `/workflows/run` 两类字段形态。
- 智能改写和智能续写会把原文同时放入 Chat `query` 和 `inputs.source_text` / `inputs.text`，适配 Dify Chat 直接对话和变量编排两种方式。
- 未配置 provider 时保留 mock 回退能力。
- uvicorn 启动脚本会检查 `/health` 版本，发现旧版本或未知 PID 占用 `18100` 时主动替换旧进程。

## 3. 关键设计决策

### 单 providerBaseUrl + 每任务路由

`v0.10.1-alpha` 放弃“单 Dify 工作流 + 判断节点分流”作为主路线。adapter 负责按任务选择 Dify 应用或工作流：

```text
providerBaseUrl: https://aibot.chinasatnet.com.cn/v1
word.rewrite           -> /chat-messages   -> apiKeyRef=rewrite
word.continue          -> /chat-messages   -> apiKeyRef=continue
word.proofread         -> /workflows/run   -> apiKeyRef=proofread
word.format_preview    -> /workflows/run   -> apiKeyRef=format_preview
word.technical_review  -> /workflows/run   -> apiKeyRef=technical_review
```

### Dify 字段兼容

- `payloadStyle=workflow`：adapter 发送 `inputs`、`response_mode`、`user`、`files`。
- `payloadStyle=chat`：adapter 发送标准 Dify Chat App 字段：`query`、`inputs`、`response_mode`、`user`、`files`。
- 对 `word.rewrite` 和 `word.continue`，`inputs` 内额外包含 `source_text`、`text`、`rewrite_mode`、`user_instruction`、`rewrite_style`、`focus_point`、`length_mode`。
- `payloadStyle=legacy-chat`：adapter 额外发送 `input_data` 和 `mode`，用于兼容企业旧封装。
- workflow 输出优先读取 route 的 `outputKey`，并兼容 `result`、`answer`、`text`、`output`、`rewrittenText`。

### 密钥只保存在 adapter

前端不持久化 API Key。读取顺序：

1. `adapter_service/run/provider_api_keys/<apiKeyRef>`。
2. 环境变量 `ENTERPRISE_AI_API_KEY`。
3. 默认文件 `adapter_service/run/provider_api_key`。

## 4. 已修改/新增的文件清单

### 核心代码

- `adapter_service/app/core/config.py`
- `adapter_service/app/services/provider_client.py`
- `adapter_service/app/api/config.py`
- `adapter_service/app/api/provider.py`
- `adapter_service/app/api/health.py`
- `adapter_service/standalone_adapter.py`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- `adapter-start-kit/scripts/start_uvicorn_adapter.sh`

### 测试

- `adapter_service/tests/test_enterprise_provider.py`
- `adapter_service/tests/test_packaging_scripts.py`

### 配置和文档

- `config/adapter.example.json`
- `docs/operations/dify-task-routes-path-apikeyref.md`
- `docs/superpowers/plans/2026-05-11-task-routes-path-apikeyref.md`
- `docs/codex-handoff.md`
- `README.md`
- `README-ZH.md`
- `phase1-delivery-kit/README.md`

## 5. 每个文件的作用

- `adapter_service/app/core/config.py`：加载 provider 和扩展后的 `TaskRoute`，提供安全摘要。
- `adapter_service/app/services/provider_client.py`：按任务解析 route，选择 path、payloadStyle、apiKeyRef，构造 Dify chat/workflow 请求并解析输出。
- `adapter_service/app/api/config.py`：返回运行配置、路由摘要和每任务密钥状态。
- `adapter_service/app/api/provider.py`：提供默认密钥和每任务密钥保存/清除接口。
- `adapter_service/standalone_adapter.py`：standalone 模式下提供同等的配置摘要和每任务密钥接口。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`：设置页新增任务接口区域。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`：渲染任务路由，保存/清除每任务密钥。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`：任务路由卡片样式。
- `config/adapter.example.json`：每任务 path/apiKeyRef/payloadStyle 示例配置。
- `docs/operations/dify-task-routes-path-apikeyref.md`：多任务 Dify 应用/工作流部署手册。

## 6. 当前未完成事项

- 目标机需要按新文档为不同 Dify 应用/工作流配置不同 API Key。
- 设置页当前只维护每任务 API Key，不在 UI 中编辑 `path` 和 `payloadStyle`；这些仍通过 `config/adapter.json` 管理。
- 智能排版当前仍以本地模板规则为主，AI 参与排版建议可在下一版本增强。
- 多 provider、多 baseUrl、多租户隔离仍留到下一版本。

## 7. 已知问题和风险

- 本地开发环境当前没有完整 FastAPI/Pydantic 依赖，只能用 `unittest` 跑不依赖服务启动的测试；FastAPI 集成测试需在目标离线依赖安装后执行。
- 如果企业封装接口不是标准 Dify chat/workflow 字段形态，需要继续扩展 `payloadStyle`，例如 `enterprise_legacy`。
- Dify workflow 输出必须返回 adapter 可解析的 JSON 文本；建议 Output 节点字段名为 `result`。
- `enabled=false` 当前只作为配置展示，尚未强制禁用任务调用。
- 用户已确认删除 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260509.tar.gz`，本轮未恢复该文件。

## 8. 数据结构、接口、配置、环境变量说明

### adapter 配置

```json
{
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerMode": "blocking",
  "taskRoutes": {
    "word.proofread": {
      "taskId": "word.proofread",
      "path": "/workflows/run",
      "apiKeyRef": "proofread",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
      "enabled": true
    }
  }
}
```

### 新增接口

```text
POST   /provider/task-api-key
DELETE /provider/task-api-key/{apiKeyRef}
```

`POST /provider/task-api-key` 请求体：

```json
{
  "apiKeyRef": "proofread",
  "apiKey": "dify-app-key"
}
```

### 环境变量

- `ENTERPRISE_AI_API_KEY`：默认企业 Dify/API 密钥，可作为所有任务的兜底密钥。

## 9. 测试命令和验证结果

已执行：

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
python3 -m unittest adapter_service.tests.test_packaging_scripts -v
PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
```

结果：

- `adapter_service.tests.test_enterprise_provider`：`OK (skipped=1)`，共 26 个测试。
- `adapter_service.tests.test_packaging_scripts`：`OK`，共 5 个测试。
- `compileall`：通过。

跳过原因：本机缺少 `pydantic`，`test_document_structure_is_accepted_in_word_request` 按测试条件自动跳过。

## 10. 下一轮任务建议 Prompt

```text
继续基于 v0.10.1-alpha 在麒麟 V10 ARM 目标机验证多任务 Dify 路由。请重点验证：1）/config 是否返回每个 taskRoute 的 path、payloadStyle、apiKeyRef 和 configured 状态；2）设置页能否分别保存 rewrite、continue、proofread、format_preview、technical_review 的 API Key；3）智能改写/续写是否命中 chat 应用；4）格式校对/技术审查是否命中对应 workflow 并能解析 outputs.result；5）如果企业封装接口字段与 Dify 标准不同，请记录请求/响应样例，用于新增 payloadStyle 兼容层。
```
