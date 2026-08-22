# AI-WPS Session Handoff

## Purpose

供下一次 Codex 会话继续 AI-WPS 开发、目标机验收或后续版本规划。本次会话已完成 `v0.23.0-alpha`，没有遗留的实现步骤。

## Repository State

- 仓库：`/Users/wayne/Documents/New project/AI-WPS`
- 远端：`https://github.com/w4yne00/AI-WPS.git`
- 分支：`main`
- 当前提交：`4070422c8c72012f4bf5dc96b2dce49f8e2be5b1`
- `origin/main` 已与当前提交一致。
- 当前版本：`v0.23.0-alpha`
- 提交说明：`feat: add per-task dual model access`

## Completed Work

- 八类 Word/Excel/PPT 任务已支持“工作流平台”和 OpenAI 兼容“模型直连”两种按任务隔离的模型配置。
- 旧工作流档案可原位迁移；旧 API 保留一版兼容包装，新前端使用 `/provider/model-configurations`。
- Adapter 随包提供八份版本化 Markdown System Prompt 和 SHA-256 清单。
- 智能编写、智能仿写已切换为可恢复后台任务，模型调用预算为 600 秒，并使用共享队列交互优先级与公平调度。
- 三宿主设置页已统一为紧凑下钻式模型配置编辑器；既有 Word 回写边界及 Excel/PPT 只读边界未改变。
- 生产模拟结果默认禁用，仅可通过显式环境变量开启。

详细设计和实现依据不要在新会话中重新推导，优先阅读：

- `docs/codex-handoff.md`
- `docs/superpowers/specs/2026-08-10-dual-model-access-design.md`
- `docs/adr/0018-*.md` 至 `docs/adr/0031-*.md`
- `docs/operations/workflow-profile-management.md`
- Git 提交 `4070422`

## Delivery Artifact

- 文件：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260811-v0230.tar.gz`
- 大小：8,765,340 字节
- 归档条目：283
- SHA256：`acee06ff18b17591079531fcae7bb9fe046648db8b221a67a2794211025ddb2f`
- 同名 `.sha256` 校验文件已提交。

## Verification Evidence

- Python：`526 passed, 55 skipped`
- 正式插件 Node 契约：14 个测试文件全部通过
- 打包测试：`30 passed`
- 三宿主 10 个 JavaScript 文件语法通过
- Shell 语法、`git diff --check`、归档敏感路径审计和包外 SHA 校验通过
- Word/Excel/PPT 设置页完成 420px 真实浏览器视觉核对；320px 完成 DOM 几何与横向溢出检查
- `wps-addon` 未安装 Vite/Vitest 开发依赖，未执行其独立测试；该目录不是本次正式交付包构建源
- 麒麟 V10、WPS 12.1.2、Python 3.8 真机验收仍待执行

## Workspace Warning

下列变更明确未纳入提交。新会话不得自动删除、恢复或暂存：

- 多个历史 `dist-phase1-delivery-kit/*.tar.gz` 的已跟踪删除
- 未跟踪旧交付包 `20260627`、`20260702`、`20260703`
- `.scratch/writing-policy-review/`
- `config/adapter.json`，这是本机运行态配置，可能包含敏感部署信息

开始任何开发前先执行 `git status --short`，继续保护上述内容。

## Recommended Next Session

优先进行麒麟 V10/WPS 真机验收，覆盖：

1. 覆盖安装后旧模型配置、API URL、API Key、写作规范库和备份是否保留。
2. 八类任务分别验证工作流平台与模型直连，重点测试 GLM/DeepSeek 兼容接口、Think 内容剥离和输入预算拦截。
3. 使用 180 秒以上慢模型验证智能编写、智能仿写、文档审查、Excel、PPT 的后台任务恢复。
4. 验证三宿主 Ribbon 隔离、任务下拉仅显示完整配置，以及 Word 回写、Excel/PPT 只读边界。
5. 将证据填写到 `phase1-delivery-kit/docs/phase1-acceptance-record.md`；如修改归档内文档，必须重新打包并更新 SHA256。

## Suggested Skills

- `$implement`：依据现有规格或真机缺陷实施小范围修复。
- `$verification-before-completion`：提交或重新打包前执行发布门禁。
- `$receiving-code-review`：处理真机测试或评审反馈，先验证再修改。
- `$apple-design`：后续调整三宿主任务窗与设置页时保持既定交互风格。
- `$playwright`：进行桌面和窄任务窗视觉回归。
- `$handoff`：下一阶段结束时再次更新临时交接。

## Guardrails

- 修改前阅读仓库根目录 `AGENTS.md` 和 `docs/codex-handoff.md`。
- 不大规模重构，不改变用户未要求的链路逻辑。
- 不缩短长任务预算，不恢复统一 URL/统一 Key 的运行时回退。
- 不改变智能编写既有写回能力；智能仿写仅预览/纯文本/复制；Excel/PPT 保持只读。
- 不提交任何真实 API Key、运行态数据库、日志、备份或 `config/adapter.json`。
- 后续提交继续直接使用 `main`，并确认 `origin/main` 同步。
