# Runtime Config

Runtime config lives in `config/adapter.example.json` and can be copied to a deployment-specific `adapter.json`.

## Supported Fields

- `servicePort`: local adapter listen port
- `difyBaseUrl`: intranet Dify base URL
- `difyApiKeyEnv`: environment variable name that stores the Dify API key
- `difyWorkflowId`: workflow or app identifier used by rewrite calls
- `logPath`: adapter log file path
- `templateRoot`: template directory root
- `timeoutSeconds`: HTTP timeout for Dify requests

## Notes

- If `difyApiKeyEnv` is not set in the environment, rewrite requests currently fall back to a local mock response.
- Production deployment should replace the mock path with real intranet credentials and workflow identifiers.
