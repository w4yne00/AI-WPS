# Kylin V10 项目测试环境

## 已验证环境

- 环境标识：Kylin V10 SP1 ARM64（`aarch64`，UTM 虚拟机）
- SSH 目标：`cloud@192.168.64.2`
- 系统 Python：`/usr/bin/python3.8`（Python `3.8.10`）
- 项目虚拟环境：`/mnt/ai-wps-test-venv`
- 虚拟环境解释器：`/mnt/ai-wps-test-venv/bin/python`
- pip：虚拟环境自带 `pip 20.0.2`
- 已安装运行依赖：`fastapi==0.110.3`、`uvicorn==0.30.6`、`pydantic==2.8.2`、`requests==2.32.3` 及仓库锁定的 ARM64 传递依赖
- 已安装测试依赖：`pytest==7.4.4`、`httpx==0.27.2`（`httpx<0.28` 用于 FastAPI/Starlette `TestClient`）
- Node.js：官方 `v22.23.2` ARM64 用户目录安装，前缀为 `/data/home/cloud/.local/share/ai-wps-node/node-v22.23.2-linux-arm64`
- Node.js 命令链接：`/data/home/cloud/.local/bin/node`、`/data/home/cloud/.local/bin/npm`、`/data/home/cloud/.local/bin/npx`
- 最近验证日期：2026-08-22

验证虚拟环境：

```bash
ssh cloud@192.168.64.2 \
  '/mnt/ai-wps-test-venv/bin/python --version && \
   /mnt/ai-wps-test-venv/bin/python -m pip --version'
```

在 Kylin V10 上运行 Python 项目测试时，统一使用虚拟环境解释器，不使用系统 Python：

```bash
cd /data/home/cloud/AI-WPS-kylin-test
PYTHONPATH=adapter_service /mnt/ai-wps-test-venv/bin/python -m pytest -q adapter_service/tests
```

运行 Node.js 插件测试和构建：

```bash
cd /data/home/cloud/AI-WPS-kylin-test/wps-addon
PATH=/data/home/cloud/.local/bin:$PATH npm test
PATH=/data/home/cloud/.local/bin:$PATH npm run build

cd /data/home/cloud/AI-WPS-kylin-test
PATH=/data/home/cloud/.local/bin:$PATH \
  sh -c 'for file in formal-plugin-kit/tests/*.test.js; do node "$file" || exit 1; done'
```

## 当前边界

- AI-WPS 的脱敏测试副本位于 Kylin V10：`/data/home/cloud/AI-WPS-kylin-test`；初始同步未带入 `.git`、运行态数据、现场配置和缓存，`wps-addon/node_modules` 已在 Kylin 本地安装，生命周期验证所需历史归档已单独放入 `dist-phase1-delivery-kit/`。
- 测试依赖已通过 Kylin 网络源安装到 `/mnt/ai-wps-test-venv`；项目已有的 Kylin V10 ARM 离线依赖包仍位于 `offline-deps/kylin-v10-arm-py38/`，运行依赖按锁定清单安装。
- Node.js 未使用系统仓库中的 `10.19.0~dfsg-3kylin1.6`，因为该版本过旧，不能作为当前 `Vite/Vitest` 测试环境；已改用官方 Node.js `22.23.2` ARM64 用户目录安装。
- `192.168.64.2` 是当前虚拟机地址，若 DHCP 地址变化，应先重新确认 SSH 地址，再更新本文档。

## 2026-08-22 验证结果

- 当前 `v0.25.1-alpha` 候选包在真实 Python 3.8/aarch64 环境通过交付生命周期门禁：使用 `v0.25.0-alpha` 基线完成升级、全新安装、损坏版本、回滚、权限错误、WPS 未退出和安装中断等场景，终态为 `candidate`。
- Python 3.8 专项门禁：7 项通过；1 项旧 `v0.23.1` 构建测试因当前生命周期门禁要求 baseline archive 而失败，错误为 `BASELINE_ARCHIVE_REQUIRED`。
- Python 全量 pytest（`PYTHONPATH=adapter_service`）：`870 passed, 4 skipped`。已修复确定性格式审查拒绝请求时创建 `image-assets` 目录的问题，以及 Kylin locale 下 shell 路径校验漏过 Unicode `U+0085` 控制字符的问题。
- `wps-addon` Node 测试：Vitest `12 passed`；Vite 生产构建成功。
- `formal-plugin-kit/tests/*.test.js`：全部 Node 契约测试通过。
- Kylin Runtime Probe：`wps`、`wpp`、`et` 均存在，临时 Adapter 使用 `/mnt/ai-wps-test-venv` 启动并返回 `adapter_health=reachable`。
- WPS GUI：临时探针插件的首次信任提示已确认，`Runtime Probe` Ribbon 选项卡可见；任务窗格内的 `运行探针` 按钮和文档对象读数尚未完成，因此不能宣称 WPS 插件 API 真机验收通过。临时 `publish.xml` 已恢复，探针目录留在测试副本的 `probe-evidence/` 下。
