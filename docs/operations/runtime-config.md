# Runtime Config

Runtime config lives in `config/adapter.example.json` and can be copied to a deployment-specific `adapter.json`.

## Supported Fields

- `servicePort`: local adapter listen port
- `providerType`: upstream AI provider type, currently `enterprise-dify-workflow` or legacy `enterprise-chat-api`
- `providerBaseUrl`: enterprise AI API base URL
- `providerApiKeyEnv`: environment variable name that stores the provider API key
- `providerChatPath`: fallback upstream endpoint path when a task route does not define `path`
- `providerMode`: upstream call mode, currently `blocking`
- `taskRoutes`: phase-1 task route map. Each key is an adapter task type and each value can contain `taskId`, `path`, `apiKeyRef`, `payloadStyle`, `responseMode`, `outputKey`, and `enabled`.
- `logPath`: adapter log file path
- `templateRoot`: template directory root
- `timeoutSeconds`: HTTP timeout for Dify requests

## Notes

- If `providerApiKeyEnv` and the local provider key file are both empty, AI requests fall back to local mock responses where supported.
- Production deployment should set each task API key through the plugin settings page or through route key files under `adapter_service/run/provider_api_keys/<apiKeyRef>`, not in `adapter.json`.
- `v0.10.0-alpha` recommends separate Dify Chat App / Workflow routes per task. The legacy single-workflow `task_id` branch mode is still documented in `docs/operations/dify-single-workflow-task-routing.md` for compatibility.
