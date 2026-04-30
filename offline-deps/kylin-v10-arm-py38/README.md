# Kylin V10 ARM Python 3.8 Runtime Dependencies

This package provides the offline Python runtime dependencies needed to run the adapter in `uvicorn` mode on Kylin V10 ARM/aarch64 with Python 3.8.

## Included Runtime Packages

- `fastapi==0.110.3`
- `uvicorn==0.30.6`
- `pydantic==2.8.2`
- `requests==2.32.3`
- Transitive dependencies downloaded as `manylinux2014_aarch64` or pure Python wheels.

## Install On Target Machine

Run from this directory:

```bash
bash install_runtime_deps.sh
```

If the target machine needs a specific Python binary:

```bash
PYTHON_BIN=/usr/bin/python3 bash install_runtime_deps.sh
```

## Verify

After installation, the adapter start script should prefer `uvicorn` automatically:

```bash
bash scripts/restart_adapter.sh 18100
```

Expected startup mode:

```text
mode=uvicorn
```

If `uvicorn` cannot be imported, the existing adapter start script will still fall back to `standalone` mode.
