# AI-WPS 一期交付总包

版本：`v0.16.0-alpha`

适用目标：麒麟 V10 ARM、Python 3.8、WPS `jsaddons` 插件目录。

## 一键安装

```bash
tar -xzf ai-wps-phase1-delivery-YYYYMMDD.tar.gz
cd ai-wps-phase1-delivery-YYYYMMDD
bash installer/install_phase1.sh
```

默认安装路径：

- Word 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0`
- Excel 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-et_1.0.0`
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
- `packages/wps-ai-assistant-et_1.0.0/`：WPS Excel 智能分析插件。
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
- `docs/operations/dify-excel-analysis-workflow.md`：Excel 智能分析 Dify 工作流配置手册。
- `docs/operations/workflow-profile-management.md`：工作流档案新增、切换、迁移和密钥保护手册。

## 安装后操作

1. 关闭并重新打开 WPS。
2. 打开 WPS Word，确认 `WPS AI 助理` 只显示 Word 专用按钮。
3. 打开 WPS Excel，确认 `WPS AI 助理` 只显示 `Excel 智能分析` 和 `设置`。
4. 打开设置页刷新配置。
5. 验证智能编写、智能仿写、文档审查、格式审查和 Excel 智能分析。
6. 如果接入 Dify，确认每个任务命中对应的 Dify 应用或工作流。
7. 确认任务窗口和 Ribbon 图标显示为雾蓝银白配色；若显示旧绿色，请完全关闭并重新启动 WPS 后复查。
8. Excel 智能分析长任务应持续显示模型后台处理状态；短暂连接失败后应保留任务编号并自动恢复查询。
9. 旧版 Dify 工作流应继续读取 `inputs.query`；新版“用户输入”节点工作流应在首次 HTTP 400 后自动切换到顶层 `query/files` 并成功返回。
