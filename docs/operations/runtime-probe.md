# Runtime Probe

Use the runtime probe before finalizing deployment on a Kylin V10 ARM endpoint. The goal is to confirm:

- WPS binaries are present on the terminal
- Python runtime is available and matches expectations
- The local adapter health endpoint is reachable
- The installed file layout matches the offline package
- The WPS add-in runtime exposes document and selection APIs

## Shell Probe

Run:

```bash
bash packaging/probe_runtime.sh "$HOME/.wps-ai-assistant" "$HOME/.wps-ai-assistant/runtime-probe.txt"
```

This writes a plain-text report containing:

- kernel and machine architecture
- python path and version
- `wps`, `wpp`, and `et` binary locations
- installed file layout checks
- localhost adapter health response

## Add-in Probe

Inside the WPS task pane, click `Runtime Probe`.

Expected output should confirm:

- `WPS global: true`
- `Active document: true`
- `Selection available: true` when a selection exists
- non-zero paragraph count on a populated document
- `Adapter reachable: true` if the local adapter is running

## Probe Outcome Checklist

- If `machine` is not `aarch64` or your expected ARM string, stop and confirm the target image
- If `python3` is missing or not on the approved version line, stop and fix the runtime bundle
- If `wps_path`, `wpp_path`, or `et_path` are missing, confirm the installed WPS package and PATH policy
- If `adapter_health=unreachable`, check `packaging/start_adapter.sh`, port `18100`, and local firewall policy
- If the add-in probe reports `WPS global: false`, the plugin runtime model is not matching assumptions and the add-in integration must be revalidated on that build
