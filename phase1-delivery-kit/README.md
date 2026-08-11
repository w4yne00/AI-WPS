# AI-WPS 一期交付总包

版本：`v0.23.1-alpha`

适用目标：麒麟 V10 ARM、Python 3.8、WPS `jsaddons` 插件目录。

## 一键安装

```bash
tar -xzf ai-wps-phase1-delivery-20260811-v0231.tar.gz
cd ai-wps-phase1-delivery-20260811-v0231
bash installer/install_phase1.sh
```

安装前必须完全退出 WPS 文字、表格和演示进程。默认安装只允许当前 WPS 登录用户直接执行；`root` 或 `sudo` 上下文不会根据当前 `$HOME` 猜测目标身份。管理员代装必须显式提交目标用户、UID、主目录和 WPS 插件目录：

```bash
sudo bash installer/install_phase1.sh \
  --target-user cloud \
  --target-uid 1000 \
  --target-home /home/cloud \
  --wps-jsaddons-dir /home/cloud/.local/share/Kingsoft/wps/jsaddons
```

安装器会在写入插件或正式 Adapter 前，将四项显式参数与系统账户信息交叉验证，并检查插件目录和安装目录的归属与可写性。任一 WPS、ET 或 WPP 进程仍在运行，或进程枚举失败时，安装都会直接停止，不修改发布组件。

默认安装路径：

- Word 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0`
- Excel 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-et_1.0.0`
- PPT 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-wpp_1.0.0`
- `publish.xml`：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/publish.xml`
- Adapter：`$HOME/ai-wps-phase1/adapter-start-kit`
- Adapter 端口：`18100`
- 发布私有依赖：`$HOME/ai-wps-phase1/adapter-start-kit/python-runtime`

如需覆盖：

```bash
WPS_JSADDONS_DIR="$HOME/.local/share/Kingsoft/wps/jsaddons" \
AI_WPS_INSTALL_ROOT="$HOME/ai-wps-phase1" \
PORT=18100 \
PYTHON_BIN=python3 \
bash installer/install_phase1.sh
```

## 一键联调

```bash
bash scripts/phase1_smoke_test.sh
```

## Python 3.8 候选门禁

构建环境准备好仓库锁定的运行依赖后，必须使用真实 Python 3.8 对最终 tar 包执行：

```bash
python3.8 scripts/python38_delivery_runtime_gate.py \
  ../ai-wps-phase1-delivery-20260811-v0231.tar.gz \
  --expected-version 0.23.1-alpha
```

门禁会重新解包最终产物，扫描其中全部 Python 文件，完整导入 FastAPI 应用，实际启动并停止 Uvicorn，再检查版本、Provider 状态、模型配置列表和写作规范摘要。门禁通过只标记为候选构建，不能替代麒麟 V10/WPS 真机验收。

目标机安装时会先校验离线 Wheel 与锁定清单的 SHA-256，再通过 `pip --target` 安装到候选的发布私有依赖目录。候选使用独立端口完成完整导入、Uvicorn 启动、版本和业务就绪检查；正式启动继续使用同一发布私有依赖目录。安装器会写入发布标记，后续启动若发现该依赖目录缺失会明确失败，不会回退系统或用户依赖。候选和正式进程均设置 `PYTHONNOUSERSITE=1` 与 Python `-s`，不会读取或修改系统、用户 `site-packages`。

## 包内内容

- `packages/wps-ai-assistant_1.0.0/`：WPS Word 正式一期插件。
- `packages/wps-ai-assistant-et_1.0.0/`：WPS Excel“智能分析 / 公式助手”插件。
- `packages/wps-ai-assistant-wpp_1.0.0/`：WPS PPT“智能总结 / 结构审查”插件。
- `packages/adapter-start-kit/`：本地 adapter 启动包。
- `packages/kylin-v10-arm-py38-pip-bootstrap/`：无 pip 目标机离线 pip 引导包。
- `packages/kylin-v10-arm-py38/`：Python 3.8 ARM 离线运行依赖。
- `wps-jsaddons/publish.xml`：WPS `jsaddons` 发布文件。
- `installer/install_phase1.sh`：一键安装脚本。
- `installer/install_private_runtime.sh`：离线依赖哈希校验与发布私有依赖安装脚本。
- `installer/preflight_candidate.sh`：隔离候选完整导入、启动、版本和业务就绪门禁。
- `scripts/phase1_smoke_test.sh`：一键联调脚本。
- `scripts/check_python38_compatibility.py`：Python 3.8 生产代码兼容性扫描。
- `scripts/python38_delivery_runtime_gate.py`：最终 tar 包 Python 3.8 导入、Uvicorn 启动和关键接口门禁。
- `release-manifest.json`：版本、三宿主、四个规范包、来源许可资产及运行态排除策略清单。
- `packages/adapter-start-kit/adapter_service/system_prompts/`：八类任务的版本化 System Prompt Markdown 及哈希清单，供模型直连接入使用。
- 包外同名 `.tar.gz.sha256`：构建脚本自动生成的正式包 SHA-256 校验记录。
- `docs/phase1-acceptance-checklist.md`：验收清单。
- `docs/phase1-acceptance-record.md`：验收记录模板。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify SYSTEM 提示词、Markdown 输出和现场验证手册。
- `docs/operations/dify-smart-imitation-workflow.md`：智能仿写 Dify 工作流配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 工作流配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 工作流配置手册。
- `docs/operations/dify-excel-analysis-workflow.md`：Excel“智能分析”Dify 工作流配置手册。
- `docs/operations/dify-excel-formula-assistant-workflow.md`：Excel“公式助手”Dify 工作流、公式读取降级和只读验收手册。
- `docs/operations/dify-ppt-slide-assistant-workflow.md`：PPT“智能总结”双模式 Dify 工作流配置手册。
- `docs/operations/dify-ppt-structure-review-workflow.md`：PPT“结构审查”Dify 工作流、页段边界和只读验收手册。
- `docs/operations/workflow-profile-management.md`：工作流档案新增、切换、迁移和密钥保护手册。
- `docs/operations/writing-policy-library.md`：Word 写作规范维护、导入、导出、备份和恢复手册。
- `docs/import-templates/writing-policies-import-template.csv`：写作规范 CSV 导入模板。
- `docs/import-templates/writing-policies-import-template.xlsx`：写作规范 XLSX 导入模板。
- `docs/prompt-templates/excel-smart-analysis-prompt-template.md`：Excel“智能分析”提示词工程模板。
- `docs/prompt-templates/excel-formula-assistant-prompt-template.md`：Excel“公式助手”提示词工程模板。
- `docs/prompt-templates/ppt-smart-summary-prompt-template.md`：PPT“智能总结”当前页/文档双模式提示词工程模板。
- `docs/prompt-templates/ppt-structure-review-prompt-template.md`：PPT“结构审查”提示词工程模板。

## 安装后操作

1. 关闭并重新打开 WPS。
2. 打开 WPS Word，确认 `WPS AI 助理` 只显示 Word 专用按钮。
3. 打开 WPS Excel，确认 `WPS AI 助理` 只显示 `智能分析`、`公式助手` 和 `设置`。
4. 打开 WPS 演示，确认 `WPS AI 助理` 只显示 `智能总结`、`结构审查` 和 `设置`。
5. 打开设置页刷新配置。
6. 验证智能编写、智能仿写、文档审查、格式审查、智能分析、公式助手、智能总结和结构审查。
7. 工作流平台接入需确认每个任务命中对应应用；模型直连接入需确认服务兼容 OpenAI `/chat/completions`，并正确填写模型标识。
8. 确认 Word、Excel、PPT 任务窗口分别使用蓝色、绿色、橙色宿主主题；若仍显示旧界面，请完全关闭并重新启动 WPS 后复查。
9. 智能编写、智能仿写、智能分析和智能总结均通过后台任务提交和短轮询等待；超过 180 秒或短暂连接失败后应保留任务编号，重新打开对应任务窗格后自动恢复查询。
10. 旧版 Dify 工作流应继续读取 `inputs.query`；新版“用户输入”节点工作流应在首次 HTTP 400 后自动切换到顶层 `query/files` 并成功返回。
11. 智能总结的文档模式应接受单个 UTF-8 `.md` 或有效 `.docx`（最大 10 MB），并可选择整套 5、8、10、12、15 页建议，默认 10 页。
12. 智能总结只提供预览和复制，绝不自动创建或修改 PPT；同一个 `ppt.slide_assistant` 工作流档案和 API Key 必须用于 `/files/upload` 与 `/chat-messages`，Dify 文件分支必须连接 `userinput.files` 和文档提取节点。
13. 覆盖安装前后应核对 `config/adapter.json`、统一 API Key、`run/provider_api_keys/`、`run/writing_policies.db` 和全部已有规范库备份，确认现场配置和写作规范均被保留。
14. 设置页按任务显示当前宿主的模型配置；每项配置独立保存接入方式、服务地址、API Key，以及模型直连所需模型标识。功能页下拉仅显示完整配置并在选择后立即激活。
15. 在 Word 设置页维护企业术语和文体规则，分别验证新增、修改、删除、CSV/XLSX 预览导入、冲突跳过、CSV 导出和数据库备份；规范库不可用时任务仍应继续并明确显示降级提示。
16. 首次安装后应存在权限为 `0600` 的空组织规范数据库；再次覆盖安装必须保留原数据库字节、组织覆盖/自定义/停用状态、全部已有备份和模型配置。
17. 公式助手必须只读取明确选区，按 `Formula`、`FormulaLocal`、`FormulaR1C1` 顺序降级，并以 `HasFormula=false` 保护普通文本；任何场景都不得写公式、新增工作表或改变计算状态。
18. 按验收清单记录 30×20 上限、空选区、混合值/公式、超长公式、外部引用、版本敏感函数、独立工作流、共享排队、任务窗格重开和复制结果。
19. 结构审查整套请求超过 60 页时必须先拒绝；指定页段不超过 60 页后可提交。核对标题/副标题分离、无标题页 120 字符与 10 页兜底上限、本地与模型问题去重、结论/目录复制及审查前后幻灯片摘要一致。

## 交付边界

- 包内包含四个经审阅的预置规范包、对应审阅清单、schema、来源和许可证说明，以及 CSV/XLSX 空白导入模板。
- 包内不包含现场 `writing_policies.db`、备份、`adapter.json`、API Key、日志、用户导入内容或未确认审阅草稿。
- 预置规范包可以随版本更新；组织规范数据保存在独立数据库中，并在覆盖升级后继续优先于预置基线。
