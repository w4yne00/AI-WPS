# Codex Handoff - AI-WPS

更新时间：2026-05-17

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

当前版本：`v0.11.0-alpha`

版本规则号：`AI-WPS-P1-WORD-0.11.0-20260517`

## 1. 项目目标和当前阶段

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标运行环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 的三层架构。

当前阶段是一期开闭环收口：平台底座 + Word 能力 + 离线交付体系。当前版本重点把原“智能改写/智能续写”合并为“智能编写”，并把智能编写改为 Dify Workflow 严格输入变量，解决 Chat App 参数易被工作流忽略导致原文原样返回的问题。

## 2. 已完成的功能

### WPS 插件侧

- `WPS AI 助理` Ribbon 选项卡。
- 五个入口：智能编写、格式校对、智能排版、技术文档审查、设置。
- 单任务窗格模式：点击不同入口时复用任务窗格并切换当前 Word 工作流。
- 当前范围识别：光标单点为全文，框选文字为选中文本。
- 智能编写：支持改写润色、续写扩展、提炼总结、自定义编写，保留用户自定义编写要求。
- 智能编写任务窗格显性展示风格、侧重点、篇幅和输出约束对应的提示词片段。
- 格式校对随请求提交 `documentStructure`，包含段落、标题和基础样式结构。
- 技术文档审查支持三类文档：技术方案、合同验收文档、测试大纲和细则，并按文档类型自动切换默认审查提示词。
- 模板下拉会合并后端 `/templates` 返回结果和本地兜底模板。
- 设置页支持单一模型提供商名称和全局 API URL 配置。
- 设置页“任务接口”区域可查看每个任务的 `path`、`payloadStyle`、`apiKeyRef` 和密钥配置状态，并保存/清除每任务 API Key。
- 设置页已移除全局 API Key 和运行探针入口，避免用户误以为所有任务共用同一密钥。
- 结果预览只显示模型输出，支持复制结果。

### adapter 侧

- FastAPI/uvicorn 正式模式，standalone 兜底模式。
- `/health` 健康检查，返回版本、运行模式、provider 状态和 `taskRouteCount`。
- `/config` 返回 provider 信息、安全的 `taskRoutes` 摘要、每任务密钥配置状态。
- `/templates` 模板列表。
- `/provider/base-url` 保存模型提供商名称和 API URL。
- `/provider/task-api-key` 保存每任务 API Key 到 `adapter_service/run/provider_api_keys/<apiKeyRef>`。
- `DELETE /provider/task-api-key/{apiKeyRef}` 清空指定任务 API Key。
- `/word/smart-write` 智能编写新端点。
- `/word/rewrite` 保留作旧版本回滚兼容，插件界面不再调用。
- `/word/proofread` 格式校对和文档质量审校。
- `/word/format-preview` 智能排版预览。
- `/word/technical-review` 技术文档审查。
- ProviderClient 支持按任务选择接口路径、请求体结构和密钥。
- ProviderClient 支持 Dify Workflow `/workflows/run`、Dify Chat `/chat-messages` 和 legacy-chat 三类字段形态。
- 智能编写严格发送 Dify Workflow Start 变量：`source_text`、`write_action`、`style`、`focus`、`length`、`user_prompt`、`selection_mode`、`trace_id`。
- 未配置对应任务密钥时保留 mock 回退能力。

## 3. 关键设计决策

### 正式设计文档作为开发准绳

从 `v0.11.0-alpha` 开始，除明确 bug 修复外，所有新功能或功能改进必须先更新正式设计文档，再进入代码实施。

当前设计文档：

```text
docs/superpowers/specs/2026-05-17-smart-write-redesign.md
```

实施计划：

```text
docs/superpowers/plans/2026-05-17-smart-write-redesign-plan.md
```

### 单 providerBaseUrl + 每任务路由

adapter 负责按任务选择 Dify 应用或工作流：

```text
providerBaseUrl: https://aibot.chinasatnet.com.cn/v1
word.smart_write      -> /workflows/run -> apiKeyRef=smart_write
word.proofread        -> /workflows/run -> apiKeyRef=proofread
word.format_preview   -> /workflows/run -> apiKeyRef=format_preview
word.technical_review -> /workflows/run -> apiKeyRef=technical_review
```

### 智能编写统一走 Workflow

智能编写不再依赖 Chat App 的顶层 `query` 作为主要输入。adapter 发送：

```json
{
  "inputs": {
    "source_text": "待处理原文",
    "write_action": "rewrite",
    "style": "formal",
    "focus": "risk",
    "length": "same",
    "user_prompt": "用户补充要求",
    "selection_mode": "selection",
    "trace_id": "word-smart-write-..."
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

Dify 工作流 Start 节点必须显式创建这些输入变量，LLM 节点必须读取 `source_text`，Output 节点建议输出字段 `result`。

### 密钥只保存在 adapter

前端不持久化 API Key。每任务读取顺序：

1. `adapter_service/run/provider_api_keys/<apiKeyRef>`。
2. 当 `apiKeyRef=default` 时可回退到环境变量 `ENTERPRISE_AI_API_KEY` 或默认文件；命名任务密钥不再隐式回退默认密钥。

## 4. 已修改/新增的文件清单

### 设计和计划

- `docs/superpowers/specs/2026-05-17-smart-write-redesign.md`
- `docs/superpowers/plans/2026-05-17-smart-write-redesign-plan.md`

### 核心代码

- `adapter_service/app/services/provider_client.py`
- `adapter_service/app/services/word/rewriter.py`
- `adapter_service/app/api/word.py`
- `adapter_service/app/api/config.py`
- `adapter_service/app/api/provider.py`
- `adapter_service/app/api/health.py`
- `adapter_service/app/main.py`
- `adapter_service/standalone_adapter.py`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- `config/adapter.example.json`

### 图标资产

- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-write.png`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-proofread.png`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-format.png`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-review.png`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-settings.png`

移除旧资产：

- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-rewrite.png`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-continue.png`

### 测试

- `adapter_service/tests/test_enterprise_provider.py`
- `adapter_service/tests/test_packaging_scripts.py`
- `adapter_service/tests/test_rewriter_modes.py`
- `adapter_service/tests/test_word_rewrite.py`
- `formal-plugin-kit/tests/layout-smoke.test.js`

### 文档

- `README.md`
- `README-ZH.md`
- `docs/operations/dify-task-routes-path-apikeyref.md`
- `docs/codex-handoff.md`
- `phase1-delivery-kit/README.md`
- `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- `phase1-delivery-kit/docs/phase1-acceptance-record.md`

## 5. 每个文件的作用

- `provider_client.py`：构造 Dify 请求、按任务选择 API Key、解析返回结果；新增 `smart_write()` 和严格 Workflow 输入。
- `rewriter.py`：封装 Word 智能编写和旧改写逻辑。
- `word.py`：新增 `/word/smart-write`，保留 `/word/rewrite`。
- `config.py`：返回任务路由安全摘要和每任务配置状态。
- `provider.py`：保存/清除模型 URL 和每任务 API Key。
- `standalone_adapter.py`：standalone 模式对齐智能编写接口。
- `taskpane.html/js`：合并智能编写 UI，移除全局 Key 和探针 UI，调用 `/word/smart-write`。
- `ribbon.xml/js`：五个 Ribbon 入口和对应图标。
- `adapter.example.json`：默认展示 `word.smart_write` 等四个任务路由。
- `dify-task-routes-path-apikeyref.md`：Dify 多任务工作流部署手册。

## 6. 当前未完成事项

- 需要在目标机内网 Dify 中新建“智能编写”Workflow，并按设计文档配置 Start 输入变量和 Output `result`。
- 格式校对、智能排版、技术文档审查仍按既有接口保留，后续可逐步统一到更严格的 Workflow Start 变量契约。
- 设置页当前不编辑每任务 `path` 和 `payloadStyle`，这些仍通过 `config/adapter.json` 管理。
- 智能排版当前仍以本地模板规则为主，AI 参与排版建议可在下一版本增强。
- 多 provider、多 baseUrl、多租户隔离仍留到下一版本。

## 7. 已知问题和风险

- 目标机 Dify 工作流若未创建 `source_text` 等 Start 变量，智能编写仍可能无法读取原文。
- Dify Output 节点如果不输出 `result`，需同步修改 taskRoute 的 `outputKey`。
- 企业封装接口如不是标准 Dify workflow/chat 字段形态，需要继续扩展 `payloadStyle`。
- 旧 `/word/rewrite` 仍保留，但不建议继续作为新功能入口。
- `enabled=false` 当前只作为配置展示，尚未强制禁用任务调用。

## 8. 数据结构、接口、配置、环境变量说明

### adapter 配置

```json
{
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerMode": "blocking",
  "taskRoutes": {
    "word.smart_write": {
      "taskId": "word.smart_write",
      "path": "/workflows/run",
      "apiKeyRef": "smart_write",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
      "enabled": true
    }
  }
}
```

### 关键接口

```text
POST   /provider/base-url
POST   /provider/task-api-key
DELETE /provider/task-api-key/{apiKeyRef}
POST   /word/smart-write
POST   /word/proofread
POST   /word/format-preview
POST   /word/technical-review
```

`POST /provider/task-api-key` 请求体：

```json
{
  "apiKeyRef": "smart_write",
  "apiKey": "dify-workflow-key"
}
```

`POST /word/smart-write` 的核心字段来自 `WordDocumentRequest.options`：

- `rewriteAction`：`rewrite`、`continue`、`summarize`、`custom`。
- `rewriteStyle`：表达风格。
- `focusPoint`：侧重点。
- `lengthMode`：篇幅。
- `userInstruction`：用户补充编写要求。

### 环境变量

- `ENTERPRISE_AI_API_KEY`：仅作为 default 任务密钥兼容兜底；推荐通过设置页保存每任务 API Key。

## 9. 测试命令和验证结果

已执行：

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite -v
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260517.tar.gz | rg 'wps-ai-assistant_1.0.0/(ribbon.xml|taskpane.js|assets/icon-smart-write.png|assets/icon-review.png)|config/adapter.example.json|dify-task-routes-path-apikeyref|install_phase1.sh|publish.xml'
tar -tvzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260517.tar.gz | rg 'installer/install_phase1.sh|scripts/phase1_smoke_test.sh|packages/adapter-start-kit/scripts/(enable_exec_permissions|check_health|start_uvicorn_adapter)\.sh'
```

结果：

- Python 单测：`42 tests OK (skipped=7)`。
- 跳过原因：本机缺少 `pydantic` / `fastapi`，涉及 `WordDocumentRequest` 和 FastAPI `TestClient` 的测试按条件跳过；目标机安装离线依赖后可执行。
- JS 布局冒烟：通过。
- `taskpane.js` 语法检查：通过。
- `compileall`：通过。
- `git diff --check`：通过。
- 一期交付包已生成：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260517.tar.gz`。
- 交付包校验：包含 `icon-smart-write.png`、`icon-review.png`、`taskpane.js`、`ribbon.xml`、`adapter.example.json`、`publish.xml`、Dify 路由手册；安装脚本和 adapter 脚本权限为 `rwxr-xr-x`。

## 10. 下一轮任务建议 Prompt

```text
继续基于 v0.11.0-alpha 在麒麟 V10 ARM 目标机验证智能编写 Workflow 闭环。请重点验证：1）设置页是否只显示全局 API URL 和每任务 API Key；2）保存 smart_write 任务 Key 后 /config 是否返回 word.smart_write configured=true；3）智能编写是否调用 /word/smart-write；4）Dify Workflow Start 是否接收到 source_text、write_action、style、focus、length、user_prompt、selection_mode、trace_id；5）Output result 是否能在任务窗格结果预览显示，并可应用到选中文本。
```
