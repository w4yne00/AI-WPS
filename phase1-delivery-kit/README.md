# AI-WPS 一期交付总包

版本：`v0.19.1-alpha`

适用目标：麒麟 V10 ARM、Python 3.8、WPS `jsaddons` 插件目录。

## 一键安装

```bash
tar -xzf ai-wps-phase1-delivery-20260724-v0191.tar.gz
cd ai-wps-phase1-delivery-20260724-v0191
bash installer/install_phase1.sh
```

默认安装路径：

- Word 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0`
- Excel 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-et_1.0.0`
- PPT 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-wpp_1.0.0`
- `publish.xml`：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/publish.xml`
- Adapter：`$HOME/ai-wps-phase1/adapter-start-kit`
- Adapter 端口：`18100`

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

## 包内内容

- `packages/wps-ai-assistant_1.0.0/`：WPS Word 正式一期插件。
- `packages/wps-ai-assistant-et_1.0.0/`：WPS Excel“智能分析”插件。
- `packages/wps-ai-assistant-wpp_1.0.0/`：WPS PPT“智能总结”插件。
- `packages/adapter-start-kit/`：本地 adapter 启动包。
- `packages/kylin-v10-arm-py38-pip-bootstrap/`：无 pip 目标机离线 pip 引导包。
- `packages/kylin-v10-arm-py38/`：Python 3.8 ARM 离线运行依赖。
- `wps-jsaddons/publish.xml`：WPS `jsaddons` 发布文件。
- `installer/install_phase1.sh`：一键安装脚本。
- `scripts/phase1_smoke_test.sh`：一键联调脚本。
- `docs/phase1-acceptance-checklist.md`：验收清单。
- `docs/phase1-acceptance-record.md`：验收记录模板。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify SYSTEM 提示词、Markdown 输出和现场验证手册。
- `docs/operations/dify-smart-imitation-workflow.md`：智能仿写 Dify 工作流配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 工作流配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 工作流配置手册。
- `docs/operations/dify-excel-analysis-workflow.md`：Excel“智能分析”Dify 工作流配置手册。
- `docs/operations/dify-ppt-slide-assistant-workflow.md`：PPT“智能总结”双模式 Dify 工作流配置手册。
- `docs/operations/workflow-profile-management.md`：工作流档案新增、切换、迁移和密钥保护手册。
- `docs/operations/enterprise-knowledge-management.md`：Word 企业术语与风格规则维护、导入、导出、备份和恢复手册。
- `docs/import-templates/enterprise-knowledge-import-template.csv`：企业知识 CSV 导入模板。
- `docs/import-templates/enterprise-knowledge-import-template.xlsx`：企业知识 XLSX 导入模板。
- `docs/prompt-templates/excel-smart-analysis-prompt-template.md`：Excel“智能分析”提示词工程模板。
- `docs/prompt-templates/ppt-smart-summary-prompt-template.md`：PPT“智能总结”当前页/文档双模式提示词工程模板。

## 安装后操作

1. 关闭并重新打开 WPS。
2. 打开 WPS Word，确认 `WPS AI 助理` 只显示 Word 专用按钮。
3. 打开 WPS Excel，确认 `WPS AI 助理` 只显示 `智能分析` 和 `设置`。
4. 打开 WPS 演示，确认 `WPS AI 助理` 只显示 `智能总结` 和 `设置`。
5. 打开设置页刷新配置。
6. 验证智能编写、智能仿写、文档审查、格式审查、智能分析和智能总结。
7. 如果接入 Dify，确认每个任务命中对应的 Dify 应用或工作流。
8. 确认 Word、Excel、PPT 任务窗口分别使用蓝色、绿色、橙色宿主主题；若仍显示旧界面，请完全关闭并重新启动 WPS 后复查。
9. 智能分析和智能总结的 provider 等待预算为 1800 秒；超过 180 秒或短暂连接失败后应保留任务编号，重新打开任务窗格也能自动恢复查询。
10. 旧版 Dify 工作流应继续读取 `inputs.query`；新版“用户输入”节点工作流应在首次 HTTP 400 后自动切换到顶层 `query/files` 并成功返回。
11. 智能总结的文档模式应接受单个 UTF-8 `.md` 或有效 `.docx`（最大 10 MB），并可选择整套 5、8、10、12、15 页建议，默认 10 页。
12. 智能总结只提供预览和复制，绝不自动创建或修改 PPT；同一个 `ppt.slide_assistant` 工作流档案和 API Key 必须用于 `/files/upload` 与 `/chat-messages`，Dify 文件分支必须连接 `userinput.files` 和文档提取节点。
13. 覆盖安装前后应核对 `config/adapter.json`、统一 API Key、`run/provider_api_keys/`、`run/enterprise_knowledge.db` 和最多三份已有知识库备份，确认现场配置和企业知识均被保留。
14. 设置页只显示统一 API URL 和当前宿主的工作流档案；功能页下拉选择工作流后应立即激活，不再显示统一 Key 或额外“切换”按钮。
15. 在 Word 设置页维护企业术语和风格规则，分别验证新增、修改、删除、CSV/XLSX 预览导入、冲突跳过、CSV 导出和数据库备份；知识库不可用时任务仍应继续并明确显示降级提示。
