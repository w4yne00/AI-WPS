# 依赖说明

## 运行要求

- `python3`
- `uvicorn`
- `fastapi`
- `pydantic`
- `requests`
- `curl`（建议）

## 说明

这份启动包主要解决“现场如何启动和检查适配层”的问题，不替代离线 Python 依赖分发。

如果目标机还没有完成 Python 依赖离线安装，需要先安装依赖，再使用这份启动包。

补充：

- `scripts/start_adapter.sh` 现在支持自动回退到 `standalone` 模式
- `standalone` 模式不依赖 `uvicorn`、`fastapi`、`pydantic`、`requests`
- 这适合先验证 WPS 插件、localhost 通信、基础 Word 流程
