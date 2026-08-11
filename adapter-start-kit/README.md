# Adapter Start Kit

This kit is the manual startup bundle for the local Phase 1 adapter service.

Use it when the target intranet machine needs a simple, operator-friendly startup package for:

- `adapter_service/`
- `config/`
- `templates/`
- start / stop / status / health-check scripts

The target default listen address is `127.0.0.1:18100`.

## Shared Runtime Layout

For an immutable release directory, configure the live state root before using
any start, stop, status, log, or autostart command:

```bash
export AI_WPS_STATE_DIR="$HOME/ai-wps-phase1/state"
export AI_WPS_BACKUP_DIR="$HOME/ai-wps-phase1/backups"
export AI_WPS_VAR_DIR="$HOME/ai-wps-phase1/var"
```

`state/` stores configuration, API Keys, and the writing-policy database.
`backups/` is reserved for whole-state snapshots. `var/` stores logs, the PID,
and transaction records, so none of those files enter a state snapshot. If only
`AI_WPS_STATE_DIR` is set, the start kit derives sibling `backups/` and `var/`
directories. If no path variables are set, existing `config/`, `run/`, and
`logs/` locations remain in use for legacy installations.

Configured runtime directories must use absolute paths and must not contain
control characters. Paths containing spaces are supported. Use `$HOME` rather
than `~`, because runtime path values are not shell-expanded.

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

Autostart on Kylin V10 / systemd targets:

```bash
bash scripts/install_autostart.sh 18100
systemctl status ai-wps-adapter.service --no-pager
```

See `docs/autostart-guide.md` for uninstall and troubleshooting commands.

`check_health.sh` checks `/health/live`, `/health/ready`, and aggregate `/health`
before printing `/provider/status`, `/provider/route-diagnostics`, and
`/provider/debug-last`. Recovery mode fails the business-readiness check while
keeping liveness visible. A log line with
`provider=mock` means the adapter did not forward that task to enterprise Dify;
confirm the unified API URL and Dify API Key are both configured.
