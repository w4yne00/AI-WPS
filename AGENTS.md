# 项目上下文
- 改代码前先读 `docs/codex-handoff.md`（不存在则跳过，并在回复中说明未找到）。

# 项目约束
<!-- 按本仓库实际情况填写；未填写的项沿用全局 ~/.codex/AGENTS.md 的代码基线 -->
- 技术栈：Python 3.8/FastAPI/Pydantic Adapter，WPS JS/HTML 插件，Node.js/Vite/Vitest。
- 测试命令：`PYTHONPATH=adapter_service /mnt/ai-wps-test-venv/bin/python -m pytest -q adapter_service/tests`；插件使用 `npm test`、`npm run build` 和 `node --test formal-plugin-kit/tests/*.test.js`。
- 构建与检查命令：`bash packaging/build_v0251_delivery_kit.sh`；提交前执行 `git diff --check`、Python 3.8 兼容扫描和交付审计。
- 不可触碰的目录或文件：`config/adapter.json`、`run/`、`.scratch/writing-policy-review/` 等运行态或本地审查文件不得提交。

## 测试环境
- Kylin V10 ARM64 测试环境及 SSH 验证命令见 `docs/operations/kylin-v10-test-environment.md`。
- 项目虚拟环境路径：`/mnt/ai-wps-test-venv`。
- 运行 Kylin V10 测试时使用 `/mnt/ai-wps-test-venv/bin/python`，不要默认使用系统 Python。

# Code Review Rules
<!-- 供 Codex code review 使用；只写要拦截的行为和安全替代路径，格式与 lint 交给 CI -->
