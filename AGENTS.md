# 项目上下文
- 改代码前先读 `docs/codex-handoff.md`（不存在则跳过，并在回复中说明未找到）。

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

# 项目约束
<!-- 按本仓库实际情况填写；未填写的项沿用全局 ~/.codex/AGENTS.md 的代码基线 -->
- 技术栈：Python 3.8/FastAPI/Pydantic Adapter，WPS JS/HTML 插件，Node.js/Vite/Vitest。
- 后端测试：在 Kylin V10 上先读取 `docs/operations/kylin-v10-test-environment.md`，使用其中当前“虚拟环境解释器”运行 `PYTHONPATH=adapter_service <解释器> -m pytest -q adapter_service/tests`；插件使用 `npm test`、`npm run build` 和 `node --test formal-plugin-kit/tests/*.test.js`。
- 构建与检查命令：`bash packaging/build_v0251_delivery_kit.sh`；提交前执行 `git diff --check`、Python 3.8 兼容扫描和交付审计。
- 不可触碰的目录或文件：`config/adapter.json`、`run/`、`.scratch/writing-policy-review/` 等运行态或本地审查文件不得提交。

## 测试环境
- Kylin V10 ARM64 测试环境及 SSH 验证命令见 `docs/operations/kylin-v10-test-environment.md`。
- 运行 Kylin V10 测试时使用上述文档记录的当前虚拟环境解释器，不默认使用系统 Python。
- 浏览器测试请在沙箱外运行 agent-browser；需要授权时发起授权，不要从受限环境直接启动 Chrome for Testing

# Code Review Rules
<!-- 供 Codex code review 使用；只写要拦截的行为和安全替代路径，格式与 lint 交给 CI -->
