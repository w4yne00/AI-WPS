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
- `AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW=1`: enables the new read-only deterministic Word format snapshot/job protocol; unset or any other value keeps the entry and protocol disabled.
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
