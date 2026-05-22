# Provider Settings Refresh Design

Date: 2026-05-22

## Problem

Target-machine diagnostics showed an inconsistent state after the settings pane
saved the unified provider URL and API key:

- `/health` reported `providerConfigured=true`.
- `/provider/route-diagnostics` showed the configured Dify Chat URL.
- `/provider/debug-last` for a later smart-write task still showed
  `provider=mock`, `providerBaseUrlConfigured=false`, and an empty forwarding
  URL.

FastAPI health/config endpoints create a new `ProviderClient` for each request,
but `app.api.word` constructs global Word service objects when uvicorn imports
the module. Their default `ProviderClient()` cached the startup settings. If the
adapter started before the settings pane saved `providerBaseUrl`, those Word
services kept the empty URL until uvicorn restarted.

## Design

- Keep injected `ProviderClient(settings)` instances stable for tests and
  explicit callers.
- Mark default `ProviderClient()` instances as config-backed clients.
- Reload settings for config-backed clients before provider readiness checks and
  immediately before HTTP forwarding.
- Keep API key lookup dynamic through the existing environment/file lookup.
- Leave standalone mode unchanged because it already constructs a fresh provider
  per task.

## Validation

- Unit test a default `ProviderClient()` whose first settings load has an empty
  URL and whose next load has the saved URL.
- Assert `is_task_configured("word.smart_write")` observes the saved URL without
  restarting the client.
- Run existing provider payload, Word route, script, and packaging checks.
