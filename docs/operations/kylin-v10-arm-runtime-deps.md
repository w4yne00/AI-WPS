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
dist-offline-deps/kylin-v10-arm-py38-runtime-deps-20260430.tar.gz
```

It contains:

- `requirements-runtime.txt`
- `install_runtime_deps.sh`
- `SHA256SUMS`
- `wheels/*.whl`

## Target Install

On the Kylin V10 ARM target machine:

```bash
tar -xzf kylin-v10-arm-py38-runtime-deps-20260430.tar.gz
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

The expected startup output should include:

```text
mode=uvicorn
```

If dependency installation fails or `uvicorn` cannot be imported, the existing start script will continue to fall back to `standalone` mode.
