# Kylin V10 ARM Python 3.8 pip 离线安装包

适用目标：麒麟 V10 ARM64，系统已有 Python 3.8，但没有 `pip`。

## 安装 pip

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

## 安装 AI-WPS 运行依赖

解压运行依赖包后执行：

```bash
tar -xzf kylin-v10-arm-py38-runtime-deps-20260430.tar.gz
cd kylin-v10-arm-py38
python3 -m pip install --no-index --find-links wheels -r requirements-runtime.txt
```

如果目标机无 `pip` 命令，统一使用 `python3 -m pip`。

## 包内文件

- `get-pip.py`：Python 3.8 对应的 pip bootstrap 脚本
- `wheels/pip-24.0-py3-none-any.whl`
- `wheels/setuptools-69.5.1-py3-none-any.whl`
- `wheels/wheel-0.43.0-py3-none-any.whl`
- `scripts/install_pip.sh`：离线安装脚本
