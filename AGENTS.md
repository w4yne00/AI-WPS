# 项目上下文
- 改代码前先读 `docs/codex-handoff.md`（不存在则跳过，并在回复中说明未找到）。

# 项目约束
<!-- 按本仓库实际情况填写；未填写的项沿用全局 ~/.codex/AGENTS.md 的代码基线 -->
- 技术栈：<语言 / 框架 / 版本>
- 测试命令：<例如 pnpm test / make test / pytest -q>
- 构建与检查命令：<例如 pnpm lint && pnpm build>
- 不可触碰的目录或文件：<例如 migrations/、生成代码目录>

## 测试环境
- Kylin V10 ARM64 测试环境及 SSH 验证命令见 `docs/operations/kylin-v10-test-environment.md`。
- 项目虚拟环境路径：`/mnt/ai-wps-test-venv`。
- 运行 Kylin V10 测试时使用 `/mnt/ai-wps-test-venv/bin/python`，不要默认使用系统 Python。

# Code Review Rules
<!-- 供 Codex code review 使用；只写要拦截的行为和安全替代路径，格式与 lint 交给 CI -->
