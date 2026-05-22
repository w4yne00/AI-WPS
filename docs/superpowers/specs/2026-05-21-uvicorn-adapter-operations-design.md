# Uvicorn Adapter Operations Design

Date: 2026-05-21

## Problem

Target-machine evidence showed `provider=mock` in adapter logs and an empty
`/provider/debug-last` payload. The service was reachable, but that does not
prove enterprise Dify forwarding occurred. The adapter intentionally falls back
to mock output whenever the unified provider URL or API key is missing.

Existing start-kit scripts mixed uvicorn and standalone behavior and did not
surface provider readiness or last-forwarding diagnostics in one operator flow.

## Design

- Treat uvicorn/FastAPI as the managed runtime for the adapter start kit.
- Keep `start_uvicorn_adapter.sh` as the concrete starter and have
  `start_adapter.sh` and `restart_adapter.sh` route into it.
- Make health/status scripts expose service mode, version, provider status,
  route diagnostics, and last provider debug data.
- Make log output explain `provider=mock` as a non-forwarded fallback.
- Make stop logic clean a listener on the configured port even if the PID file
  is stale or missing.
- Keep standalone adapter source in the package as compatibility code, but do
  not use it from the managed operations scripts.
- Record mock fallback in `/provider/debug-last` without exposing prompt bodies
  or secrets.

## Validation

- Provider unit tests assert mock fallback records a sanitized skip reason.
- Packaging tests assert operations scripts target uvicorn and include provider
  diagnostic endpoints.
- Existing provider forwarding tests continue to validate Dify Chat payload
  generation for smart write and related tasks.
