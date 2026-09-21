# Runtime Config

Runtime config lives in `config/adapter.example.json` and can be copied to a deployment-specific `adapter.json`.

## Runtime Path Contract

New release layouts should pass an explicit shared-state directory before starting
the Adapter:

```bash
export AI_WPS_STATE_DIR="$HOME/ai-wps-phase1/state"
export AI_WPS_BACKUP_DIR="$HOME/ai-wps-phase1/backups"
export AI_WPS_VAR_DIR="$HOME/ai-wps-phase1/var"
```

The directories have separate responsibilities:

- `AI_WPS_STATE_DIR`: `adapter.json`, the unified and task API Key files, and `writing_policies.db`.
- `AI_WPS_BACKUP_DIR`: reserved for validated whole-state snapshots. It is not a live configuration source.
- `AI_WPS_VAR_DIR`: `logs/`, `run/adapter.pid`, and `transactions/`. These files are excluded from state snapshots.
- `AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW=0`: disables the read-only deterministic Word format snapshot/job protocol for operational containment. The protocol is enabled when the variable is unset or set to `1`.
- `AI_WPS_FORMAT_REVIEW_DIR`: optional absolute staging directory for the deterministic format review protocol. When unset, snapshots use `AI_WPS_VAR_DIR/format-review` (or the legacy runtime `var/format-review` location).

Each configured value must be an absolute path and must not contain control
characters. Paths containing spaces are supported, including in the generated
systemd unit. `~` is not expanded; use `$HOME` when exporting a value.

When only `AI_WPS_STATE_DIR` is set, `backups/` and `var/` default to siblings of
that directory. `AI_WPS_BACKUP_DIR` and `AI_WPS_VAR_DIR` override those derived
locations. When none of the three variables is set, the Adapter keeps the legacy
layout (`config/adapter.json`, `run/`, and `logs/`) so existing installations can
continue to start before migration.

With the shared-state layout enabled, `AI_WPS_VAR_DIR/logs/adapter.log` overrides
the legacy `logPath` field. `AI_WPS_WRITING_POLICY_DB` remains a supported
file-level override for diagnostics and compatibility gates, and takes precedence
over `AI_WPS_STATE_DIR` for the writing-policy database only.

## Supported Fields

- `servicePort`: local adapter listen port
- `providerType`: upstream AI provider type, currently `enterprise-dify-workflow` or legacy `enterprise-chat-api`
- `providerBaseUrl`: enterprise AI API base URL
- `providerApiKeyEnv`: environment variable name that stores the provider API key
- `providerChatPath`: fallback upstream endpoint path when a task route does not define `path`
- `providerMode`: upstream call mode, currently `blocking`
- `taskRoutes`: phase-1 task route map. Each key is an adapter task type and each value can contain `taskId`, `path`, `apiKeyRef`, `payloadStyle`, `responseMode`, `outputKey`, and `enabled`.
- `logPath`: legacy-layout adapter log file path; the shared-state layout writes to `AI_WPS_VAR_DIR/logs/adapter.log`
- `templateRoot`: template directory root
- `timeoutSeconds`: HTTP timeout for Dify requests

## Notes

- If `providerApiKeyEnv` and the local provider key file are both empty, AI requests fall back to local mock responses where supported.
- Production deployment should set each task API key through the plugin settings page. The shared-state files are stored under `AI_WPS_STATE_DIR/provider_api_keys/<apiKeyRef>` with mode `0600`; the legacy fallback remains `run/provider_api_keys/<apiKeyRef>`.
- `v0.10.0-alpha` recommends separate Dify Chat App / Workflow routes per task. The legacy single-workflow `task_id` branch mode is still documented in `docs/operations/dify-single-workflow-task-routing.md` for compatibility.

## 交互文本流式、毫秒性能诊断与回滚合同

### 1. 特性开关 (Feature Flag)

- `AI_WPS_ENABLE_DIRECT_STREAMING`: 直连模型流式增量生成与运行中取消特性开关。
  - **默认状态**：未设置或设为 `0` / `false` 时完全禁用，所有直连任务保持阻塞式执行与 3 秒短轮询。
  - **启用状态**：显式设置为 `1` 时启用 Word 智能编写与智能仿写直连模型的流式增量生成。
  - **FastAPI / Standalone 对等性**：双运行时在 `GET /config` 的 `features.directStreamingEnabled` 中对等暴露该布尔值。

### 2. 模型流式能力验证与快照冻结 (Streaming Capability)

- **五元组强绑定**：能力记录强绑定 `serviceId`、`serviceRevision`、规范化 `serviceBaseUrl`、`apiKeyFingerprint`（SHA-256 前缀）及精确 `modelName`。
- **状态枚举**：
  - `validated`：真实探针通过，模型支持 SSE 流式且输出符合任务合同。
  - `unsupported`：真实探针检测到模型不支持流式（返回 400/415/422 或非 SSE 响应），自动回退至阻塞调用。
  - `stale`：服务地址、Key、版本号或所选模型发生任何变更，旧能力结论自动失效。
  - `not_checked`：尚未执行流式探针验证，新任务不启用流式。
- **提交快照冻结**：任务提交时冻结当前的 `streamingCapability` 快照，运行中轮换 Key 或修改服务配置不影响当前执行中任务。

### 3. 阻塞回退机制 (Blocking Fallback)

- 仅在产生首个可见文本增量之前，若模型服务返回 400/404/415/422/501 或非 SSE 响应，允许平滑回退至阻塞调用最多一次。
- 一旦产生首个可见文本增量，绝不再发起阻塞重试；后续任何网络中断或上游错误直接作为终态 `failed` 处理，杜绝重复计费与双份调用。

### 4. 运行中取消边界 (Cancellation Boundaries)

- 仅流式任务启用运行中取消（`allow_running_cancel=True`）；阻塞任务严格保持排队阶段后不可取消，绝不显示虚假取消入口。
- 用户点击“停止生成”后，任务窗格在 <100ms 内展示“正在停止”并禁用按钮。
- 协调器立即标记 `stopping` 阶段，流式读取器检测到取消信号后抛出异常并主动关闭上游 HTTP socket 连接。
- 权威状态竞态仲裁：取消请求先接受则终态为 `cancelled`；完整响应先到达则终态为 `completed`；终态幂等。
- 取消或失败的残缺正文保留在前端内存中供只读查看与复制，严格不写入任务历史（`history_store` 零条目），智能编写的“应用”写回按钮保持禁用。

### 5. 资源与耗时边界守护 (Resource Boundaries)

- **事件环形缓冲区**：协调器最多保留 256 项增量事件（`DEFAULT_MAX_EVENTS`）。
- **文本快照上限**：增量纯文本快照严格限制为 512 KiB（`previewSnapshot`）。
- **模型总响应体**：累计读取上限 5 MiB，超限立即关闭并抛出 `MODEL_RESPONSE_SIZE_LIMIT`。
- **长轮询超时**：事件接口 `waitMs` 参数上限 25000ms（25 秒），超时返回空事件信封与当前最新序号。
- **DOM 节流**：前端最多每 50ms 或累计 4 KiB 合并一次增量文本渲染，距离底部 30px 阈值智能跟随滚动。

### 6. 脱敏性能诊断指标 (Sanitized Diagnostics)

- 长任务轮询与终态诊断对等公开毫秒指标：`elapsedMs`（总耗时）、`phaseElapsedMs`（当前阶段耗时）、`phaseDurationsMs`（阶段耗时字典）、`queueWaitMs`（排队时长）、`metrics`（ Provider 各阶段耗时）。
- 阻塞调用首包可见时间 `providerFirstVisibleMs` 严格为 `null`，杜绝伪造首包时间。
- 真实记录 `providerOutcome`（`success`、`not_attempted`、`degraded`、`provider_timeout`、`provider_error`）。
- 严格遵循脱敏规范：指标绝不包含用户文档正文、提示词内容、增量文本、API Key、认证头或本地绝对路径。

### 7. 关闭与平滑降级路径 (Rollback & Graceful Degradation)

- **特性即时关闭**：将环境变量设为 `AI_WPS_ENABLE_DIRECT_STREAMING=0` 并重启 Adapter，后续提交的新任务立即回到现有阻塞调用与 3 秒状态短轮询；运行中任务继续按提交时快照安全收敛。
- **增量事件接口不可用自动降级**：若 `/events` 端点返回 404（旧版本 Adapter）或连续 3 次长轮询失败，正式任务窗格自动平滑降级回退至现有 3 秒状态短轮询，不清除已保存的模型配置，不破坏文档会话，不清理任务历史。
- **向前向后兼容**：新增的 `streamingCapability` 字段为纯附加字段，旧版本 Adapter 可安全忽略；加载未包含该字段的历史配置时自动赋予安全默认值 `not_checked`，无需破坏性配置迁移。

### 8. 发布裁决与默认启用规则 (Release Adjudication)

- **当前发布裁决（Issue #213 / ADR-0132）**：
  - 自动化合同测试仅验证流式协议、取消、回退和确定性边界；真实模型、真实 WPS、每个模型组合至少 30 次采样及 p50/p95/p99 门禁仍为 `manual-pending`。
  - 但因目标机现场未配置公网商业大模型服务，真实供应商直连流式的真实网络延迟与长效稳定性尚未建立完整现场证据，且真实 WPS 12.1.2 客户端的端到端人机交互受限于环境仍维持 `manual-pending`（绑定 Issue #154）。
  - 根据门禁规则第 11 条：“只有全部门槛通过并记录证据后，才能提出后续版本默认开启；否则保持显式 feature flag”。
  - **当前候选裁决**：`v0.26.0-preview.1` 保持 `AI_WPS_ENABLE_DIRECT_STREAMING=0`（默认关闭）。流式能力仅在显式配置环境变量 `=1` 时启用；后续版本须根据新的目标机验收证据重新裁决。
