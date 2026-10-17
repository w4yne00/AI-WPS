# 适配层启动说明

## 目录内容

- `adapter_service/`
- `config/`
- `templates/`
- `scripts/start_adapter.sh`
- `scripts/stop_adapter.sh`
- `scripts/status_adapter.sh`
- `scripts/check_health.sh`
- `scripts/check_environment.sh`
- `scripts/show_logs.sh`
- `scripts/enable_exec_permissions.sh`
- `scripts/restart_adapter.sh`
- `scripts/install_autostart.sh`
- `scripts/uninstall_autostart.sh`

## 首次执行权限修复

如果目标机解压后脚本没有执行权限，可运行：

```bash
bash scripts/enable_exec_permissions.sh
```

如果目标机目录权限较严，需要提权：

```bash
bash scripts/enable_exec_permissions.sh sudo
```

## 启动

Preview 交付包请先从包根目录运行 `bash installer/install_ai_wps.sh`，由安装器准备私有依赖并完成安装。安装后进入 `"$HOME/ai-wps/current"`，再执行下面的管理命令。自定义安装根请替换该路径。

独立启动包则进入自身根目录，并事先准备 Python 运行依赖。

```bash
bash scripts/start_adapter.sh 18100
```

说明：

- `start_adapter.sh` 委托 `start_uvicorn_adapter.sh`，只启动 uvicorn/FastAPI 服务。
- Preview 安装使用发布私有依赖目录；依赖缺失或导入失败时明确退出，不会自动降级到 `standalone`。
- 独立启动包未要求私有运行时时，可使用已准备好的 Python 环境；指定解释器时使用 `PYTHON_BIN=/绝对路径/python3`。

## 状态

```bash
bash scripts/status_adapter.sh 18100
```

## 一键重启

```bash
bash scripts/restart_adapter.sh 18100
```

这会按顺序执行：

- `stop_adapter.sh`
- `start_adapter.sh`
- `check_health.sh`

## 健康检查

```bash
bash scripts/check_health.sh 18100
```

脚本先检查 `/health/live`，再读取聚合 `/health`。聚合状态为 `ready` 时核心与增强子系统均正常；`degraded` 表示增强能力降级但核心任务仍可用；`recovery` 表示进程存活但业务未就绪，脚本返回非零并提示先备份和导出脱敏诊断。

如果返回 `adapter_health=unreachable`，继续执行：

```bash
bash scripts/show_logs.sh 50
```

## 停止

```bash
bash scripts/stop_adapter.sh 18100
```

## 开机自启动

麒麟 V10 目标机如果每次重启后 adapter 停止，可以安装 systemd 自启动服务：

```bash
bash scripts/install_autostart.sh 18100
```

安装后确认：

```bash
systemctl status ai-wps-adapter.service --no-pager
bash scripts/status_adapter.sh 18100
```

取消自启动：

```bash
bash scripts/uninstall_autostart.sh
```

详细说明见 `docs/autostart-guide.md`。
