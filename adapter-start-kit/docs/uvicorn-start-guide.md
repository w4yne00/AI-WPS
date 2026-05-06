# Adapter uvicorn 一键启动说明

适用目标：麒麟 V10 ARM，Python 3.8，已安装 `kylin-v10-arm-py38-runtime-deps` 离线依赖。

## 1. 安装依赖

如果目标机没有 pip，先安装 pip 引导包：

```bash
tar -xzf kylin-v10-arm-py38-pip-bootstrap-20260506.tar.gz
cd kylin-v10-arm-py38-pip-bootstrap-20260506
bash scripts/install_pip.sh
```

安装运行依赖：

```bash
tar -xzf kylin-v10-arm-py38-runtime-deps-20260506.tar.gz
cd kylin-v10-arm-py38
python3 -m pip install --no-index --find-links wheels -r requirements-runtime.txt
```

## 2. 一键启动 uvicorn

```bash
tar -xzf adapter-start-kit-20260506.tar.gz
cd adapter-start-kit-20260506
bash scripts/start_uvicorn_adapter.sh 18100
bash scripts/check_health.sh 18100
```

成功标志：

```text
adapter_health=reachable url=http://127.0.0.1:18100/health
adapter_mode=uvicorn
```

如果健康检查显示 `adapter_mode=standalone`，说明端口可达但仍是旧的兼容服务。
重新执行 `bash scripts/start_uvicorn_adapter.sh 18100` 即可，脚本会识别并替换占用 `18100` 的旧 standalone 进程。

## 3. 常用命令

```bash
bash scripts/status_adapter.sh 18100
bash scripts/show_logs.sh 80
bash scripts/stop_adapter.sh 18100
bash scripts/restart_adapter.sh 18100
```

## 4. 说明

- `start_uvicorn_adapter.sh` 只走 uvicorn；缺依赖会直接提示安装离线依赖，并会在端口被旧 standalone 占用时自动替换旧进程。
- `start_adapter.sh` 会优先 uvicorn，缺 uvicorn 时自动降级 standalone，也会避免被旧模式进程占用端口。
- WPS 插件访问地址固定为 `http://127.0.0.1:18100`，因此启动端口建议保持 `18100`。
