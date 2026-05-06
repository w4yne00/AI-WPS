# Kylin V10 ARM Runtime Dependencies

This project can run the local adapter in two modes:

- `uvicorn`: preferred when Python runtime dependencies are installed.
- `standalone`: fallback mode using only the Python standard library.

## Why Prefer Uvicorn Mode

`uvicorn` mode runs the FastAPI adapter application directly. It gives us the full API implementation, middleware chain, structured exception handling, CORS behavior, and a more standard ASGI runtime for future Word/Excel/PPT routes.

`standalone` mode is intentionally small. It is useful for offline verification and emergency fallback, but it duplicates only the core behavior we need for field testing.

## Offline Package

The offline runtime dependency package is:

```text
dist-offline-deps/kylin-v10-arm-py38-runtime-deps-20260506.tar.gz
```

It contains:

- `requirements-runtime.txt`
- `install_runtime_deps.sh`
- `SHA256SUMS`
- `wheels/*.whl`

20260506 package note:

- Adds `exceptiongroup==1.2.2`, required by `anyio` on Python 3.8.
- Fixes offline install failures like `No matching distribution found for exceptiongroup>=1.0.2; python_version < "3.11"`.

## Target Install

On the Kylin V10 ARM target machine:

```bash
tar -xzf kylin-v10-arm-py38-runtime-deps-20260506.tar.gz
cd kylin-v10-arm-py38
bash install_runtime_deps.sh
```

If needed, specify the Python binary:

```bash
PYTHON_BIN=/usr/bin/python3 bash install_runtime_deps.sh
```

Then restart the adapter:

```bash
bash scripts/restart_adapter.sh 18100
```

To force FastAPI/uvicorn mode instead of fallback standalone mode:

```bash
bash scripts/start_uvicorn_adapter.sh 18100
bash scripts/check_health.sh 18100
```

The expected startup output should include:

```text
mode=uvicorn
adapter_mode=uvicorn
```

If dependency installation fails or `uvicorn` cannot be imported, the existing start script will continue to fall back to `standalone` mode.
If health is reachable but reports `adapter_mode=standalone`, rerun `bash scripts/start_uvicorn_adapter.sh 18100`; the script now replaces the old standalone process before starting FastAPI.
