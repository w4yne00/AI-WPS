# Kylin V10 ARM Python 3.8 Runtime Dependencies

This package provides the offline Python runtime dependencies needed to run the adapter in `uvicorn` mode on Kylin V10 ARM/aarch64 with Python 3.8.

## Included Runtime Packages

- `fastapi==0.110.3`
- `uvicorn==0.30.6`
- `pydantic==2.8.2`
- `requests==2.32.3`
- Transitive dependencies downloaded as `manylinux2014_aarch64` or pure Python wheels.

## Install On Target Machine

正式交付必须由总包安装器将本目录依赖安装到当前发布代际的发布私有依赖目录 `python-runtime/`，不得直接安装到系统或用户 `site-packages`：

```bash
bash installer/install_phase1.sh
```

安装器会验证 `SHA256SUMS` 与 `requirements-lock.txt`，并使用 `pip --require-hashes --target`。候选预检与正式启动都设置 `PYTHONNOUSERSITE=1`，使用同一发布私有依赖目录。

仓库中的 `install_runtime_deps.sh` 仅保留为历史独立依赖包兼容入口，不用于 `v0.23.1-alpha` 正式安装。

If the target machine needs a specific Python binary:

```bash
PYTHON_BIN=/usr/bin/python3 bash installer/install_phase1.sh
```

## Verify

通过总包安装器安装后，Adapter 启动脚本必须从发布私有依赖目录启动 `uvicorn`：

```bash
bash scripts/restart_adapter.sh 18100
```

Expected startup mode:

```text
mode=uvicorn
```

如果发布私有依赖目录缺失或无法导入 `uvicorn`，启动脚本会明确失败，不会回退到系统、用户 `site-packages` 或 `standalone` 模式。
