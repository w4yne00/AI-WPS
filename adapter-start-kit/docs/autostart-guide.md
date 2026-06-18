# Adapter 开机自启动说明

目标机：麒麟 V10 / systemd 环境。

自启动脚本会安装一个系统级 systemd 服务：`ai-wps-adapter.service`。开机后服务会自动执行当前启动包内的 `scripts/start_adapter.sh 18100`，继续复用现有的 uvicorn 启动、版本替换、端口占用处理、日志和 PID 文件逻辑。

## 安装自启动

在目标机上进入已安装的 adapter 启动包目录，例如：

```bash
cd "$HOME/ai-wps-phase1/adapter-start-kit"
bash scripts/install_autostart.sh 18100
```

如果目标机需要固定 Python 路径：

```bash
PYTHON_BIN=/usr/bin/python3.8 bash scripts/install_autostart.sh 18100
```

脚本会自动请求 `sudo`，并默认使用执行 sudo 的登录用户运行 adapter。若需要指定运行用户：

```bash
bash scripts/install_autostart.sh 18100 cloud
```

## 验证

```bash
systemctl status ai-wps-adapter.service --no-pager
bash scripts/status_adapter.sh 18100
bash scripts/check_health.sh 18100
```

重启目标机后再次执行：

```bash
bash scripts/status_adapter.sh 18100
```

如果显示 `adapter_health=reachable`，说明 adapter 已随系统启动。

## 查看日志

adapter 自身日志仍在启动包目录：

```bash
bash scripts/show_logs.sh 120
```

systemd 服务日志可用：

```bash
journalctl -u ai-wps-adapter.service -n 120 --no-pager
```

## 取消自启动

```bash
bash scripts/uninstall_autostart.sh
```

该命令会停止并禁用 `ai-wps-adapter.service`，删除 `/etc/systemd/system/ai-wps-adapter.service`，然后执行 `systemctl daemon-reload`。

## 注意事项

- 自启动依赖 systemd；如果目标机没有 `systemctl`，需要继续手工执行 `bash scripts/start_adapter.sh 18100`。
- 服务绑定 `127.0.0.1:18100`，仅供本机 WPS 插件访问。
- 如果移动了 adapter 启动包目录，需要重新执行 `bash scripts/install_autostart.sh 18100`，让 systemd 服务指向新目录。
