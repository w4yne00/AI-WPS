# AI-WPS v0.9.1-alpha 新版本部署手册

更新时间：2026-05-09

适用交付包：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260509.tar.gz`

## 1. 版本变化

`v0.9.1-alpha` 在 `v0.9.0-alpha` provider 路线基础上，修复目标机联调中暴露的旧进程、模板下拉和技术审查配置问题：

关键变化：

- `start_uvicorn_adapter.sh` 会检查 `/health` 中的 adapter 版本；如果端口 `18100` 上是旧版本 uvicorn 或未知 PID，会主动替换旧进程。
- 插件模板下拉会合并后端 `/templates` 返回结果和本地兜底模板，避免只显示“通用办公模板”。
- 技术文档审查只保留三类文档：技术方案、合同验收文档、测试大纲和细则。
- 技术文档审查会按文档类型自动切换默认审查提示词。
- `/word/technical-review` 仍通过单 Dify 工作流 `task_id=word.technical_review` 路由。

## 2. 目标机目录

WPS 插件安装目录：

```text
/home/cloud/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0
```

WPS 插件声明文件：

```text
/home/cloud/.local/share/Kingsoft/wps/jsaddons/publish.xml
```

adapter 启动包目录由交付包解压位置决定，建议放在桌面或固定运维目录。

## 3. 一键安装

在目标机解压交付包：

```bash
tar -xzf ai-wps-phase1-delivery-20260509.tar.gz
cd ai-wps-phase1-delivery-20260509
./installer/install_phase1.sh
```

安装脚本会执行：

- 安装或引导 pip。
- 离线安装 Python 运行依赖。
- 复制 WPS 插件到 `jsaddons/wps-ai-assistant_1.0.0`。
- 写入或合并 `publish.xml`。
- 复制 adapter、config、templates。
- 设置脚本执行权限。

## 4. 配置 Dify 工作流

编辑安装后的 `config/adapter.json`，确认：

```json
{
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerChatPath": "/workflows/run"
}
```

API Key 推荐通过插件设置页保存，或通过环境变量提供：

```bash
export ENTERPRISE_AI_API_KEY="your-api-key"
```

Dify 工作流配置请参考：

```text
docs/operations/dify-single-workflow-task-routing.md
```

## 5. 启动 adapter

优先使用 uvicorn 启动脚本：

```bash
cd packages/adapter-start-kit/scripts
./start_uvicorn_adapter.sh 18100
```

检查健康状态：

```bash
./check_health.sh 18100
```

预期看到：

```text
adapter_health=reachable url=http://127.0.0.1:18100/health version=0.9.1-alpha
adapter_mode=uvicorn
adapter_runtime=fastapi
```

如果脚本发现旧进程，会先输出类似：

```text
adapter_stale_running mode=uvicorn current_version=0.9.0-alpha expected_version=0.9.1-alpha port=18100
```

这是正常保护逻辑，脚本会继续替换旧进程并启动当前包内的 adapter。

## 6. WPS 验证

1. 关闭并重新打开 WPS。
2. 确认出现 `WPS AI 助理` Ribbon 选项卡。
3. 点击设置，刷新配置。
4. 确认状态为 `ok` 或可识别的待配置状态。
5. 依次验证：智能改写、智能续写、格式校对、智能排版、技术审查。
6. 在 Dify 工作流日志中确认 `task_id` 分别为对应任务。

## 7. 常见问题

### 插件不显示

检查：

```text
/home/cloud/.local/share/Kingsoft/wps/jsaddons/publish.xml
```

必须包含：

```xml
<jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>
```

### adapter 可达但模型无响应

检查：

- `providerBaseUrl` 是否只到 `/v1`。
- `providerChatPath` 是否为 `/workflows/run`。
- API Key 是否来自当前 Dify 工作流。
- Dify 工作流是否配置了 `task_id` 判断节点。

### 未配置 provider 时

adapter 会回退 mock，方便验证插件按钮、任务窗格、文档读取和本地规则链路。这不是大模型故障。
