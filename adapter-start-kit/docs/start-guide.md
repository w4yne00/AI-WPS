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

```bash
bash scripts/start_adapter.sh 18100
```

说明：

- 如果目标机已安装 `uvicorn`，脚本优先使用 `uvicorn`
- 如果目标机没有 `uvicorn`，脚本会自动降级到 `standalone` 模式
- `standalone` 模式只依赖系统自带 `python3`，适合先打通目标机联调

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

如果返回 `adapter_health=unreachable`，继续执行：

```bash
bash scripts/show_logs.sh 50
```

## 停止

```bash
bash scripts/stop_adapter.sh 18100
```
