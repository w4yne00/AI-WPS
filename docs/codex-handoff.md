# Codex Handoff - AI-WPS

更新时间：2026-05-08

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`main`

最新提交：以 `git log -1 --oneline` 为准。本文件已随 `v0.7.1-alpha` 路径修正一并更新。

当前版本：`v0.7.1-alpha`

版本规则号：`AI-WPS-P1-DELIVERY-0.7.1-20260508`

## 1. 项目目标和当前阶段

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标运行环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python 适配服务、企业封装 HTTP AI 接口的三层架构。

当前阶段是一期收口阶段：

- 平台底座：WPS 插件框架、本地 adapter、企业 AI provider 接入、离线安装体系、目标机验收体系。
- Word 能力：格式校对、智能排版预览、智能改写、智能续写、选中文本处理、模板化规则。
- 交付状态：已生成正式一期交付总包，可在目标机通过一键安装脚本完成插件部署、pip 引导、离线依赖安装、adapter 安装启动和联调检查。

一期交付包路径：

- `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260508.tar.gz`
- `dist-formal-plugin-kit/wps-ai-assistant-kit-20260508.tar.gz`
- `dist-adapter-start-kit/adapter-start-kit-20260508.tar.gz`

## 2. 已完成的功能

### WPS 插件侧

- `WPS AI 助理` Ribbon 选项卡。
- 五个入口：智能改写、智能续写、格式校对、智能排版、设置。
- 单任务窗格模式：点击不同入口时复用同一任务窗格并切换当前工作流。
- 当前范围识别：光标落在单点时显示全文，框选文字时显示选中文本。
- 选中文本改写和续写。
- 结果预览区域只显示模型输出结果，支持复制结果。
- 设置页支持单一模型提供商名称、API URL、API Key 配置。
- 设置页包含联调状态、运行探针、配置刷新。
- UI 已多轮压缩和简化，趋向苹果式简洁风格。
- Ribbon 图标资源已加入 `assets/`，并在 `ribbon.xml` 中引用。
- 正式插件目录已按目标机可识别方式组织为 `wps-ai-assistant_1.0.0`。

### 本地 adapter 侧

- FastAPI 正式模式，推荐通过 uvicorn 启动。
- standalone 兜底模式，在无 uvicorn 或依赖不完整时仍可提供基础能力。
- `/health` 健康检查。
- `/config` 运行配置查询。
- `/templates` 模板列表查询。
- `/word/proofread` Word 格式校对。
- `/word/format-preview` Word 排版预览。
- `/word/rewrite` Word 改写和续写。
- `/provider/status` provider 配置状态。
- `/provider/base-url` 保存模型提供商名称和 API URL。
- `/provider/api-key` 保存 API Key 到本地文件。
- `DELETE /provider/api-key` 清空本地 API Key。
- 企业封装 HTTP API provider 支持 Dify 风格 `/chat-messages` 请求。
- 未配置 provider 时自动使用 mock 结果，避免阻断前端验证。
- AI 错别字检查已接入格式校对流程，只有 provider 配置完整时调用。

### 模板和规则

- 已接入通用模板 `general-office`。
- 已接入公司标准 Word 模板：`技术文件格式及书写要求`。
- 已将上传的 `技术文件格式及书写要求.docx` 抽取为 JSON 规则。
- 格式校对支持标题层级、字体、字号、行距、缩进、重复空格、中文标点前空格等检查。
- 智能排版预览基于模板规则生成待调整段落列表。

### 离线部署与交付

- 已提供麒麟 V10 ARM Python 3.8 离线依赖包。
- 已提供无 pip 目标机的 pip 离线 bootstrap 包。
- 已提供 adapter 启动包。
- 已提供正式 WPS 插件导入包。
- 已提供一期交付总包。
- 已提供一键安装脚本 `installer/install_phase1.sh`。
- 已提供一键联调脚本 `scripts/phase1_smoke_test.sh`。
- 已提供批量执行权限脚本 `scripts/enable_exec_permissions.sh`。
- 交付包内脚本已在打包时设置可执行权限。
- 安装脚本会自动写入或合并 `publish.xml`。
- 安装脚本会把插件复制到 `/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0`。

## 3. 关键设计决策

### 插件轻量，复杂逻辑放到 adapter

WPS 插件负责 UI、文档读取、选区识别、预览、复制和写回。格式规则、模板加载、AI provider、日志、健康检查、配置读写都放在本地 adapter。这样可以降低 WPS JS 运行时差异带来的风险。

### adapter 优先 uvicorn，保留 standalone 兜底

uvicorn/FastAPI 更适合正式能力扩展，支持 CORS、中间件、结构化路由、错误处理和测试。standalone 用于目标机依赖缺失时快速验证基础链路。

### 企业 AI provider 只在 adapter 保存密钥

API Key 不放在 WPS 插件端，避免泄露到前端文件。当前实现支持环境变量和本地文件两种来源：

- 环境变量：`ENTERPRISE_AI_API_KEY`
- 本地文件：`adapter_service/run/provider_api_key`

### 未配置 provider 时使用 mock

目标机内网接口可能尚未配置，插件仍需要验证文档读取、任务窗格、adapter 连通和按钮流程。因此 provider 未配置时默认 mock，而不是直接报错。

### Word 写回必须先预览

格式校对、排版预览、改写、续写都以预览为中心，避免 AI 或规则结果直接覆盖用户文档。

### 模板文件必须随 adapter 启动包同步

曾出现 uvicorn 健康检查成功但 `/word/proofread` 报 `Template not found: general-office` 的问题。原因是启动包模板路径或模板文件未同步。当前打包逻辑会把 `templates/` 带入 adapter 启动包，并修复模板路径解析。

### WPS 目标机采用 `jsaddons` 目录安装

根据目标机验证，插件目录必须放在：

```text
/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0
```

同时需要在：

```text
/home/cloud/.local/share/Kingsoft/wps/jsaddons/publish.xml
```

加入插件声明。安装脚本会保留已有其他 `<jsplugin>` 行，并替换或新增本项目插件行。

## 4. 已修改/新增的文件清单

### 本轮一期交付收口新增或修改

- `.gitignore`
- `README.md`
- `README-ZH.md`
- `adapter_service/app/api/health.py`
- `adapter_service/app/main.py`
- `adapter_service/standalone_adapter.py`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- `packaging/build_phase1_delivery_kit.sh`
- `phase1-delivery-kit/README.md`
- `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- `phase1-delivery-kit/installer/install_phase1.sh`
- `phase1-delivery-kit/scripts/enable_exec_permissions.sh`
- `phase1-delivery-kit/scripts/phase1_smoke_test.sh`
- `phase1-delivery-kit/wps-jsaddons/publish.xml`
- `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260508.tar.gz`
- `docs/codex-handoff.md`

### 已存在且与当前功能强相关的核心文件

- `adapter_service/app/api/config.py`
- `adapter_service/app/api/provider.py`
- `adapter_service/app/api/templates.py`
- `adapter_service/app/api/word.py`
- `adapter_service/app/core/config.py`
- `adapter_service/app/core/models.py`
- `adapter_service/app/services/provider_client.py`
- `adapter_service/app/services/template_loader.py`
- `adapter_service/app/services/word/proofreader.py`
- `adapter_service/app/services/word/formatter.py`
- `adapter_service/app/services/word/rewriter.py`
- `adapter_service/standalone_adapter.py`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/main.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/`
- `templates/company/technical-file-format-requirements.docx`
- `templates/company/technical-file-format-requirements.json`
- `templates/general/general-office.json`
- `templates/general/proofread-rules.json`
- `config/adapter.example.json`
- `docs/operations/adapter-start-kit.md`
- `docs/operations/formal-plugin-import.md`
- `docs/operations/kylin-v10-arm-runtime-deps.md`
- `docs/operations/offline-install.md`
- `docs/operations/pip-offline-bootstrap.md`
- `docs/operations/runtime-config.md`

## 5. 每个文件的作用

### 根目录和说明文档

- `.gitignore`：忽略展开后的交付包目录，仅保留需要入库的交付压缩包。
- `README.md`：英文项目说明、版本规则、能力列表、快速启动、更新记录。
- `README-ZH.md`：中文项目说明、当前版本、能力范围、交付说明和更新记录。
- `docs/codex-handoff.md`：当前交接文档，供下一轮 Codex 或人工继续开发时读取。

### adapter 服务

- `adapter_service/app/main.py`：FastAPI 应用入口，注册健康、配置、模板、provider、Word API 路由，版本为 `v0.7.1-alpha`。
- `adapter_service/app/api/health.py`：健康检查接口，返回服务名、状态、版本、运行模式、provider 配置状态。
- `adapter_service/app/api/config.py`：返回 adapter 运行配置、provider 状态、日志路径、模板根目录等信息。
- `adapter_service/app/api/provider.py`：模型提供商配置接口，包括保存 URL、保存密钥、清空密钥和查询状态。
- `adapter_service/app/api/templates.py`：模板列表接口，返回可用 Word 模板。
- `adapter_service/app/api/word.py`：Word 核心能力 API，包括格式校对、排版预览、改写/续写。
- `adapter_service/app/core/config.py`：配置加载和保存逻辑，默认配置文件为 `config/adapter.json`，示例文件为 `config/adapter.example.json`。
- `adapter_service/app/core/models.py`：请求和响应数据模型，定义 `WordDocumentRequest`、段落、标题、审校问题、排版变更、改写结果等结构。
- `adapter_service/app/core/errors.py`：provider 错误类型定义。
- `adapter_service/app/core/logging.py`：adapter 日志工具。
- `adapter_service/app/core/tracing.py`：生成 trace id。
- `adapter_service/app/services/provider_client.py`：企业 AI HTTP provider 封装，负责构造 prompt、调用 `/chat-messages`、解析结果、mock 回退、API Key 文件读写和 AI 错别字检查。
- `adapter_service/app/services/template_loader.py`：加载 `templates/company/*.json` 和 `templates/general/*.json`，提供模板列表和模板查找。
- `adapter_service/app/services/document_normalizer.py`：文档内容归一化工具。
- `adapter_service/app/services/word/proofreader.py`：格式校对规则执行和 AI 错别字检查编排。
- `adapter_service/app/services/word/formatter.py`：排版预览生成。
- `adapter_service/app/services/word/rewriter.py`：改写/续写服务编排。
- `adapter_service/standalone_adapter.py`：无 FastAPI/uvicorn 环境的轻量 HTTP 服务兜底，版本同步为 `v0.7.1-alpha`。
- `adapter_service/requirements.txt`：adapter Python 依赖声明。
- `adapter_service/tests/`：adapter 单元测试。

### WPS 正式插件

- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`：插件元信息和版本号。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.xml`：兼容 WPS 插件结构的 manifest。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`：WPS Ribbon 按钮定义，包含五个功能入口和图标引用。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`：Ribbon 回调逻辑，负责打开或切换任务窗格。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/main.js`：插件主入口和 WPS 生命周期桥接。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/index.html`：插件入口页面。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`：任务窗格 DOM 结构。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`：任务窗格视觉样式。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`：任务窗格业务逻辑，包含配置读取、范围识别、调用 adapter、结果预览、复制结果、应用预览等。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`：可测试的前端辅助函数。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/`：Ribbon 图标和 AI 助理图标资源。

### 模板和配置

- `templates/company/technical-file-format-requirements.docx`：公司标准 Word 格式模板源文件。
- `templates/company/technical-file-format-requirements.json`：从标准模板抽取并整理出的格式规则。
- `templates/general/general-office.json`：通用办公文档模板规则。
- `templates/general/proofread-rules.json`：基础格式校对规则。
- `config/adapter.example.json`：adapter 示例配置。
- `config/adapter.json`：目标机或本地运行时实际配置，通常不应硬编码提交敏感信息。

### 打包和运维脚本

- `packaging/build_formal_plugin_kit.sh`：构建正式 WPS 插件包。
- `packaging/build_adapter_start_kit.sh`：构建 adapter 启动包。
- `packaging/build_offline_bundle.sh`：构建离线依赖包。
- `packaging/build_phase1_delivery_kit.sh`：构建一期交付总包。
- `packaging/build_probe_kit.sh`：构建运行时探针包。
- `packaging/diagnose.sh`：诊断脚本。
- `packaging/install.sh`：早期安装脚本。
- `packaging/probe_runtime.sh`：运行时探测脚本。
- `packaging/start_adapter.sh`：早期 adapter 启动脚本。
- `packaging/uninstall.sh`：卸载脚本。

### 一期交付总包源目录

- `phase1-delivery-kit/README.md`：一期总包使用说明。
- `phase1-delivery-kit/installer/install_phase1.sh`：目标机一键安装脚本。负责 pip 引导、离线依赖安装、插件复制、`publish.xml` 写入、adapter 安装启动和健康检查。
- `phase1-delivery-kit/scripts/enable_exec_permissions.sh`：对总包内脚本批量设置执行权限。
- `phase1-delivery-kit/scripts/phase1_smoke_test.sh`：一键联调脚本，检查插件目录、`publish.xml`、Python 依赖、adapter 健康和模板接口。
- `phase1-delivery-kit/wps-jsaddons/publish.xml`：目标机 `jsaddons` 发布文件模板。
- `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`：目标机验收清单。
- `phase1-delivery-kit/docs/phase1-acceptance-record.md`：验收记录模板。

### 交付产物

- `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260508.tar.gz`：正式一期交付总包，包含插件、adapter、pip 引导、离线依赖、安装脚本、联调脚本、验收文档。
- `dist-formal-plugin-kit/wps-ai-assistant-kit-20260508.tar.gz`：正式 WPS 插件包。
- `dist-adapter-start-kit/adapter-start-kit-20260508.tar.gz`：adapter 启动包。

## 6. 当前未完成事项

- 一期交付包尚需在真实目标机上执行完整验收并回填验收记录。
- 智能排版目前以“预览待调整计划”为主，自动写回格式能力还应继续增强和细化。
- 格式校对已支持规则和 AI 错别字检查，但标准模板规则仍可继续补充，例如页边距、页眉页脚、编号、图表标题、表格格式、目录等。
- 企业 AI provider 目前按 Dify 风格 `/chat-messages` 封装，其他企业 API 变体需要通过 provider adapter 扩展。
- 多模型供应商选择功能曾尝试加入，但因目标机交互不稳定已回退为单一模型供应商配置。后续若恢复，需要重新设计并补测试。
- Excel 和 PPT 能力仍属于二期：Excel 报表生成、多表对比；PPT 根据文档或主题生成大纲。
- 目标机上的 WPS JS API 差异仍需持续记录，尤其是图标显示、Ribbon 回调、任务窗格生命周期、选区读取。

## 7. 已知问题和风险

- 目标机无 pip 时，离线 pip 引导依赖 Python 权限和用户 site-packages 可写性。安装脚本会先尝试默认安装，失败后自动 `--user`，但仍可能受系统策略限制。
- 如果目标机已有旧 adapter 进程占用 `18100`，新的 uvicorn 可能未真正启动。需要先执行 stop 脚本或一键重启脚本。
- 如果 adapter 启动成功但 `/templates` 或 Word API 报模板找不到，优先检查启动目录和 `templates/` 是否随启动包复制完整。
- 如果 WPS 前端显示 `Failed to fetch`，通常是 adapter 未启动、端口不一致、CORS/localhost 访问受限、或旧包未覆盖成功。优先执行 `phase1_smoke_test.sh` 和 `check_health.sh 18100`。
- 如果清空 API URL/API Key 后状态仍显示已配置，检查目标机是否存在环境变量 `ENTERPRISE_AI_API_KEY` 或旧配置文件未覆盖。
- WPS Ribbon 图标在不同版本中可能出现问号，当前已提供 PNG 和 SVG 资源，但仍需要在目标机继续验证 `ribbon.xml` 图标路径兼容性。
- `publish.xml` 中旧插件声明可能与新插件共存。安装脚本会保留其他插件行，仅替换本项目 `wps-ai-assistant` 行，若现场要求只保留本项目，需要手动调整策略。
- 交付包中包含离线依赖轮子，包较大，GitHub 推送和下载会慢于普通代码。
- 仓库中存在本地 Python `__pycache__` 文件显示在文件列表中，后续应检查 `.gitignore` 是否完全覆盖并避免误提交。

## 8. 数据结构、接口、配置、环境变量说明

### Word 请求结构

核心模型：`WordDocumentRequest`

字段：

- `documentId`：文档标识。
- `scene`：固定为 `word`。
- `selectionMode`：`document` 或 `selection`。
- `content.plainText`：全文或选中文本。
- `content.paragraphs`：段落数组。
- `content.headings`：标题数组。
- `options.templateId`：模板 ID，例如 `general-office` 或 `technical-file-format-requirements`。
- `options.trackChanges`：是否跟踪变更。
- `options.userInstruction`：用户补充要求。
- `options.rewriteStyle`：改写风格。
- `options.focusPoint`：侧重点。
- `options.lengthMode`：篇幅模式。
- `options.rewriteAction`：`rewrite` 或 `continue`。

### 主要 HTTP 接口

健康检查：

```http
GET /health
```

配置查询：

```http
GET /config
```

模板查询：

```http
GET /templates
```

格式校对：

```http
POST /word/proofread
```

排版预览：

```http
POST /word/format-preview
```

改写/续写：

```http
POST /word/rewrite
```

provider 状态：

```http
GET /provider/status
```

保存模型提供商名称和 API URL：

```http
POST /provider/base-url
Content-Type: application/json

{
  "providerName": "星辰大模型接口API",
  "baseUrl": "https://aibot.chinasatnet.com.cn/v1"
}
```

保存 API Key：

```http
POST /provider/api-key
Content-Type: application/json

{
  "apiKey": "..."
}
```

清空 API Key：

```http
DELETE /provider/api-key
```

### 企业 AI 接口请求约定

adapter 调用企业 HTTP API 时默认请求：

```http
POST {providerBaseUrl}{providerChatPath}
Authorization: Bearer {apiKey}
Content-Type: application/json
```

默认路径：

```text
/chat-messages
```

请求体核心字段：

```json
{
  "input_data": {
    "scene": "word",
    "rewrite_mode": "rewrite",
    "trace_id": "..."
  },
  "query": "...",
  "conversation_id": "",
  "mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

响应解析优先读取：

- 顶层 `answer`
- `data.answer`
- `data.text`
- `data.rewrittenText`

### 配置文件

示例配置：`config/adapter.example.json`

关键字段：

- `servicePort`：adapter 端口，默认 `18100`。
- `providerName`：设置页显示的模型提供商名称。
- `providerType`：当前默认 `enterprise-chat-api`。
- `providerBaseUrl`：企业大模型 API 基础 URL。
- `providerApiKeyEnv`：API Key 环境变量名，默认 `ENTERPRISE_AI_API_KEY`。
- `providerChatPath`：聊天接口路径，默认 `/chat-messages`。
- `providerMode`：默认 `blocking`。
- `logPath`：日志路径。
- `templateRoot`：模板根目录，默认 `./templates`。
- `timeoutSeconds`：provider 调用超时时间。

### 环境变量

- `ENTERPRISE_AI_API_KEY`：企业 AI API Key。优先级高于本地文件。
- `DIFY_API_KEY`：早期 Dify 配置保留字段，当前主流程优先使用 `ENTERPRISE_AI_API_KEY`。
- `WPS_JSADDONS_DIR`：一期安装脚本的 WPS 插件安装目录覆盖项。
- `AI_WPS_INSTALL_ROOT`：一期安装脚本的 adapter 安装根目录覆盖项。
- `PORT`：一期安装脚本和 smoke test 的 adapter 端口，默认 `18100`。
- `PYTHON_BIN`：一期安装脚本使用的 Python 命令，默认 `python3`。

### 本地密钥文件

adapter 会把界面保存的 API Key 写入：

```text
adapter_service/run/provider_api_key
```

交付包安装到目标机后，对应路径位于安装后的 adapter 目录中。

## 9. 测试命令和验证结果

最近一次一期交付收口已执行并通过以下命令：

```bash
bash -n packaging/build_phase1_delivery_kit.sh phase1-delivery-kit/installer/install_phase1.sh phase1-delivery-kit/scripts/phase1_smoke_test.sh phase1-delivery-kit/scripts/enable_exec_permissions.sh
```

结果：通过。

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

结果：通过。

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
```

结果：通过。

```bash
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
```

结果：通过。

```bash
python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

结果：通过。

```bash
python3 -m compileall -q adapter_service
```

结果：通过。

一期交付包内容和权限已人工验证：

- `installer/install_phase1.sh` 具备执行权限。
- `scripts/phase1_smoke_test.sh` 具备执行权限。
- `scripts/enable_exec_permissions.sh` 具备执行权限。
- adapter 包内 `start_uvicorn_adapter.sh`、`check_health.sh`、`enable_exec_permissions.sh` 具备执行权限。
- 总包包含 pip bootstrap：`packages/kylin-v10-arm-py38-pip-bootstrap/get-pip.py`。
- 总包包含 uvicorn 离线 wheel。
- 总包包含 WPS 插件目录 `packages/wps-ai-assistant_1.0.0/`。
- 总包包含 `wps-jsaddons/publish.xml`。
- 总包包含验收清单和验收记录模板。

目标机建议验收命令：

```bash
tar -xzf ai-wps-phase1-delivery-20260508.tar.gz
cd ai-wps-phase1-delivery-20260508
bash installer/install_phase1.sh
bash scripts/phase1_smoke_test.sh
```

如果需要单独验证 adapter：

```bash
cd "$HOME/ai-wps-phase1/adapter-start-kit/scripts"
./check_health.sh 18100
./show_logs.sh 100
```

## 10. 下一轮任务建议的 prompt

建议下一轮从目标机验收和一期稳定性修复开始，不要直接进入 Excel/PPT。可以使用以下 prompt：

```text
请继续接手 AI-WPS 项目。先阅读 docs/codex-handoff.md 和 AGENTS.md。

当前版本是 v0.7.1-alpha，一期交付总包已经生成：
dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260508.tar.gz

下一步任务：
1. 根据目标机执行 installer/install_phase1.sh 和 scripts/phase1_smoke_test.sh 的回显，定位并修复安装或联调问题；
2. 核对 WPS 中 publish.xml、wps-ai-assistant_1.0.0、Ribbon 图标、五个入口、任务窗格打开和设置页保存是否稳定；
3. 验证 /health、/config、/templates、/word/proofread、/word/format-preview、/word/rewrite；
4. 若发现问题，优先修复一期稳定性，不要大规模重构；
5. 修改后同步更新版本号、README、交付包、验收清单，并运行对应测试；
6. 最后重新构建一期交付包并给出目标机验证步骤。
```

如果一期验收通过，可以进入下一阶段 prompt：

```text
请在 AI-WPS 当前一期稳定版本基础上，规划二期 Excel 和 PPT 能力。

要求：
1. 不破坏现有 Word 能力和一期交付脚本；
2. 先做需求拆分和架构设计，再进入开发；
3. Excel 优先支持报表生成和多表对比；
4. PPT 优先支持根据文档或主题生成大纲；
5. 继续保持插件轻量、adapter 承载复杂逻辑、离线部署可验收。
```
