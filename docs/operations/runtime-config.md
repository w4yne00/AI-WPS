# Runtime Config

Runtime config lives in `config/adapter.example.json` and can be copied to a deployment-specific `adapter.json`.

## Supported Fields

- `servicePort`: local adapter listen port
- `providerType`: upstream AI provider type, currently `enterprise-chat-api`
- `providerBaseUrl`: enterprise AI API base URL
- `providerApiKeyEnv`: environment variable name that stores the provider API key
- `providerChatPath`: upstream chat endpoint path, default `/chat-messages`
- `providerMode`: upstream chat call mode, currently `blocking`
- `logPath`: adapter log file path
- `templateRoot`: template directory root
- `timeoutSeconds`: HTTP timeout for Dify requests

## Notes

- If `providerApiKeyEnv` is not set in the environment, rewrite requests fall back to a local mock response.
- Production deployment should set the enterprise API key in the environment rather than storing it in `adapter.json`.
