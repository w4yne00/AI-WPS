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

## 启动

```bash
bash scripts/start_adapter.sh 18100
```

## 状态

```bash
bash scripts/status_adapter.sh
```

## 健康检查

```bash
bash scripts/check_health.sh 18100
```

## 停止

```bash
bash scripts/stop_adapter.sh
```
