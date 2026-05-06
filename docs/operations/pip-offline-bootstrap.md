# pip 离线引导包安装说明

适用场景：麒麟 V10 ARM 目标机已有 Python 3.8，但没有 `pip` 命令，导致无法安装 `kylin-v10-arm-py38-runtime-deps-20260506` 中的运行依赖。

离线包路径：

```text
dist-offline-deps/kylin-v10-arm-py38-pip-bootstrap-20260506.tar.gz
```

## 1. 安装 pip

```bash
tar -xzf kylin-v10-arm-py38-pip-bootstrap-20260506.tar.gz
cd kylin-v10-arm-py38-pip-bootstrap-20260506
bash scripts/install_pip.sh
python3 -m pip --version
```

如果目标机 Python 命令不是 `python3`：

```bash
PYTHON_BIN=/usr/bin/python3.8 bash scripts/install_pip.sh
/usr/bin/python3.8 -m pip --version
```

## 2. 安装 AI-WPS 运行依赖

```bash
tar -xzf kylin-v10-arm-py38-runtime-deps-20260506.tar.gz
cd kylin-v10-arm-py38
python3 -m pip install --no-index --find-links wheels -r requirements-runtime.txt
```

## 3. 验证

```bash
python3 -m pip --version
python3 -c "import fastapi, uvicorn, requests; print('runtime deps ok')"
```

如果验证失败，先检查 Python 版本是否为 3.8，再检查 `SHA256SUMS` 中的离线 wheel 是否完整。
