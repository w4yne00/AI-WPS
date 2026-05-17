# AI-WPS 一期交付总包

版本：`v0.11.0-alpha`

适用目标：麒麟 V10 ARM、Python 3.8、WPS `jsaddons` 插件目录。

## 一键安装

```bash
tar -xzf ai-wps-phase1-delivery-YYYYMMDD.tar.gz
cd ai-wps-phase1-delivery-YYYYMMDD
bash installer/install_phase1.sh
```

默认安装路径：

- WPS 插件：`/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0`
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

- `packages/wps-ai-assistant_1.0.0/`：WPS 正式一期插件。
- `packages/adapter-start-kit/`：本地 adapter 启动包。
- `packages/kylin-v10-arm-py38-pip-bootstrap/`：无 pip 目标机离线 pip 引导包。
- `packages/kylin-v10-arm-py38/`：Python 3.8 ARM 离线运行依赖。
- `wps-jsaddons/publish.xml`：WPS `jsaddons` 发布文件。
- `installer/install_phase1.sh`：一键安装脚本。
- `scripts/phase1_smoke_test.sh`：一键联调脚本。
- `docs/phase1-acceptance-checklist.md`：验收清单。
- `docs/phase1-acceptance-record.md`：验收记录模板。
- `docs/operations/dify-task-routes-path-apikeyref.md`：Dify 多任务路由部署手册。
- `docs/operations/AI-WPS-Dify多任务工作流节点配置手册-v0.10.0.docx`：Word 版 Dify 节点级配置手册。
- `docs/operations/phase1-v0.9.1-deployment.md`：新版本部署手册。

## 安装后操作

1. 关闭并重新打开 WPS。
2. 确认 Ribbon 出现 `WPS AI 助理`。
3. 打开设置页刷新配置。
4. 验证智能编写、格式校对、智能排版和技术审查。
5. 如果接入 Dify，确认每个任务命中对应的 Dify 应用或工作流。
