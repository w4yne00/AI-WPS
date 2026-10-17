# 依赖说明

## 运行要求

- 麒麟 V10 ARM/aarch64，Python 3.8
- `uvicorn`、`fastapi`、`pydantic`、`requests` 及交付包锁定的传递依赖
- `curl`（启动及健康检查使用）

## Preview 交付包

在交付包根目录执行：

```bash
bash installer/install_ai_wps.sh
```

安装器使用包内离线依赖创建并校验发布私有 Python 运行目录。不要把依赖安装到系统或用户 `site-packages` 来替代该目录。

## 独立启动包

独立启动包不包含完整离线依赖分发。请先在指定 Python 环境中准备所需依赖，再从启动包根目录执行 `bash scripts/start_adapter.sh 18100`；需要指定解释器时设置 `PYTHON_BIN=/绝对路径/python3`。

启动脚本只运行 uvicorn/FastAPI。依赖缺失或导入失败时直接退出，不会回退到 `standalone`。
