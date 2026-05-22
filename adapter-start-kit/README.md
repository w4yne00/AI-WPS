# Adapter Start Kit

This kit is the manual startup bundle for the local Phase 1 adapter service.

Use it when the target intranet machine needs a simple, operator-friendly startup package for:

- `adapter_service/`
- `config/`
- `templates/`
- start / stop / status / health-check scripts

The target default listen address is `127.0.0.1:18100`.

## Uvicorn Operations

The start kit now treats the uvicorn/FastAPI adapter as the managed runtime.
Install the offline Python runtime dependencies before starting it.

```bash
bash scripts/check_environment.sh
bash scripts/start_adapter.sh
bash scripts/check_health.sh
```

Operational commands:

```bash
bash scripts/status_adapter.sh
bash scripts/show_logs.sh 120
bash scripts/restart_adapter.sh
bash scripts/stop_adapter.sh
```

`check_health.sh` prints `/health`, `/provider/status`,
`/provider/route-diagnostics`, and `/provider/debug-last`. A log line with
`provider=mock` means the adapter did not forward that task to enterprise Dify;
confirm the unified API URL and Dify API Key are both configured.
