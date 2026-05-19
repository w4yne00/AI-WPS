# v0.11.1-alpha Task Route Key Diagnostics Design

更新时间：2026-05-19

## 背景

`v0.11.0-alpha` 将智能编写切换为 Dify Workflow，并引入单一 `providerBaseUrl` 加每任务 `apiKeyRef` 的配置模型。目标机测试显示，Dify Workflow 本地预览正常，Start 变量、LLM 节点变量引用和 Output `result` 绑定均正确，但 WPS 任务窗格调用后仍出现原文和结果一致的问题。

当前更可能的问题在 adapter 路由层：

- 目标机可能已有旧版 `config/adapter.json`，导致新版 `adapter.example.json` 中的 `word.smart_write` 路由没有被加载。
- UI 已移除全局 API Key 输入，但设置页摘要仍显示全局“密钥：未配置”状态。
- adapter 后端仍保留 default/global key fallback 概念，容易混淆“当前 provider 已配置”和“某个任务 Workflow key 已配置”。
- 运行脚本版本识别仍存在旧版本常量，目标机旧进程和新包混用时不易诊断。

## 目标

`v0.11.1-alpha` 的目标是让 adapter 的任务路由选择可验证、可诊断，并消除全局 API Key 对任务工作流路由的影响。

## 非目标

- 不改 Dify Workflow 节点设计。
- 不新增多 provider、多 baseUrl 或租户隔离。
- 不重构 WPS 插件整体 UI。
- 不删除旧 `/provider/api-key` 兼容接口，但它不再作为命名任务的正常配置路径。

## 用户可见行为

### 设置页

设置页顶部 provider 卡片只显示：

- provider 名称。
- provider 类型或 URL 配置状态。
- `providerBaseUrl`。
- 编辑入口。

设置页顶部不再显示全局密钥状态，例如 `密钥：未配置`、`密钥：环境变量`、`密钥：本地文件`。

任务接口区域继续显示每个任务的：

- 功能名称。
- `path`。
- `payloadStyle`。
- `apiKeyRef`。
- 该任务密钥是否已配置。
- 保存/清除该任务 API Key 的控件。

### Adapter 行为

对命名任务路由，尤其是：

- `word.smart_write`
- `word.proofread`
- `word.format_preview`
- `word.technical_review`

adapter 必须只读取 `provider_api_keys/<apiKeyRef>`。当 `apiKeyRef` 不是 `default` 时，不回退 `ENTERPRISE_AI_API_KEY`，也不回退旧的 `run/provider_api_key`。

全局 API Key 仅作为旧接口兼容能力保留，不影响上述命名任务的路由选择。

## 配置升级规则

`load_settings()` 读取配置时：

1. 优先读取 `config/adapter.json` 中用户保存的配置。
2. 同时读取 `config/adapter.example.json` 中的默认 `taskRoutes`。
3. 如果 `adapter.json` 缺少某个默认任务路由，则自动补齐该默认路由。
4. 如果 `adapter.json` 已定义某个任务路由，则保留用户定义。
5. 不覆盖用户保存的 `providerBaseUrl`、`providerName`、`providerType`、`providerMode`。

这保证目标机从旧版本升级后，即使已有旧 `adapter.json`，也能获得 `word.smart_write` 等新版任务路由。

## 诊断接口

新增只读诊断能力，用于确认 adapter 实际将任务发往哪个工作流。

建议接口：

```text
GET /provider/route-diagnostics
```

返回脱敏信息：

```json
{
  "success": true,
  "data": {
    "version": "0.11.1-alpha",
    "configPath": ".../config/adapter.json",
    "exampleConfigPath": ".../config/adapter.example.json",
    "providerBaseUrlConfigured": true,
    "taskRouteConfiguredCount": 4,
    "routes": {
      "word.smart_write": {
        "taskId": "word.smart_write",
        "enabled": true,
        "url": "https://aibot.chinasatnet.com.cn/v1/workflows/run",
        "path": "/workflows/run",
        "payloadStyle": "workflow",
        "responseMode": "blocking",
        "outputKey": "result",
        "apiKeyRef": "smart_write",
        "configured": true,
        "authSource": "route-file"
      }
    }
  }
}
```

该接口不得返回 API Key 明文。

## `/health` 和 `/config`

`/health` 保留健康检查作用，但不再返回全局 `providerAuthSource`。它应返回：

- `version`
- `mode`
- `providerBaseUrlConfigured`
- `taskRouteCount`
- `taskRouteConfiguredCount`

`/config` 保留 provider 和任务路由摘要，但不再返回全局 `providerAuthSource`。如果保留 `providerConfigured`，其含义必须调整为“URL 已配置且至少一个任务 key 已配置”。更推荐返回更明确的：

- `providerBaseUrlConfigured`
- `taskRouteConfiguredCount`

## 请求日志

`ProviderClient.post_task()` 在实际发请求前记录脱敏路由信息：

- `traceId`
- `taskType`
- `routeTaskId`
- `url`
- `apiKeyRef`
- `authSource`
- `payloadStyle`
- `outputKey`
- `inputKeys`

日志不得包含 API Key 和完整正文。

## 版本

所有版本展示更新为：

```text
0.11.1-alpha
AI-WPS-P1-WORD-0.11.1-20260519
```

启动脚本 `EXPECTED_VERSION` 必须同步为 `0.11.1-alpha`。

## 验收标准

1. 目标机旧 `adapter.json` 缺少 `word.smart_write` 时，`/config` 仍能显示补齐后的 `word.smart_write` route。
2. `word.smart_write` 的 `configured` 只取决于 `provider_api_keys/smart_write` 是否存在。
3. 即使存在环境变量 `ENTERPRISE_AI_API_KEY` 或旧 `run/provider_api_key`，`word.smart_write` 也不应显示已配置，除非 `smart_write` 任务 key 存在。
4. 设置页顶部不再显示全局密钥状态。
5. `/provider/route-diagnostics` 能显示 `word.smart_write` 的实际 URL、`apiKeyRef`、`authSource` 和脱敏配置状态。
6. 启动脚本能以 `0.11.1-alpha` 判断当前 adapter 版本。
7. 现有智能编写请求 payload 仍保持 Dify Workflow Start 变量契约。
