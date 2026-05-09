# Runtime Config

Runtime config lives in `config/adapter.example.json` and can be copied to a deployment-specific `adapter.json`.

## Supported Fields

- `servicePort`: local adapter listen port
- `providerType`: upstream AI provider type, currently `enterprise-dify-workflow` or legacy `enterprise-chat-api`
- `providerBaseUrl`: enterprise AI API base URL
- `providerApiKeyEnv`: environment variable name that stores the provider API key
- `providerChatPath`: upstream endpoint path, default `/workflows/run` for the single Dify workflow route
- `providerMode`: upstream call mode, currently `blocking`
- `taskRoutes`: lightweight phase-1 task route map. Each key is an adapter task type and each value contains `taskId` and `enabled`.
- `logPath`: adapter log file path
- `templateRoot`: template directory root
- `timeoutSeconds`: HTTP timeout for Dify requests

## Notes

- If `providerApiKeyEnv` and the local provider key file are both empty, AI requests fall back to local mock responses where supported.
- Production deployment should set the enterprise API key in the environment or through the adapter provider key file, not in `adapter.json`.
- In `enterprise-dify-workflow` mode, adapter sends `task_id` to Dify so one workflow can branch into rewrite, continue, proofread, format preview, and technical review paths.
