# v0.25.1-alpha delivery note

## 候选身份

- Candidate label: `20260824-d7a1dd8`
- Candidate build ID: `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`
- Source commit: `d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`
- Archive name: `ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz`
- Archive checksum file: `ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz.sha256`
- Archive SHA-256: `ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`
- Automated status: `candidate`
- Target acceptance status: `manual-pending` (Issue #59)

The candidate uses the accepted `v0.25.0-alpha` Phase1 baseline and explicit
allowlist assembly. The v2 deterministic format-review contract is
`word.format_review.snapshot.v2`; JavaScript and Python independently verify
`characterCount`, `contentSha256`, `structureSha256`, and `formatSha256`.
The contract uses `format_semantics.v1` rule assets, UTF-16 character counts,
stable compact JSON, and fail-closed trust-boundary checks. The direct
predecessor `20260824-10b251d` is frozen and rejected because its packaged
target-acceptance record contained contradictory current-candidate/
no-current-candidate narratives and duplicate previous-rejected lines; its
SHA-256 is
`6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120`.

The assembled archive contains a generated target-acceptance context bound to
d7a1dd8. The source
`packaging/v0251-target-machine-acceptance.md` remains the pre-build generator
template and intentionally has no bound current candidate; it is not a claim
about the assembled archive. Automated status `candidate` is not manual
acceptance. Issue #59 remains `manual-pending` until real Kylin V10, target WPS,
and model evidence is recorded.

The earlier `20260824-f953c58`, `20260824-afe109c`, `20260824-799adf9`,
`20260824-5318d4b`, `20260824-2e7a3e6`, and `20260824-ccad09f` records remain
`rejected` with their original identities and archive digests. The
direct predecessor `20260824-10b251d` remains byte-frozen. The
direct predecessor `20260824-afe109c` remains rejected. 其直接前任 `20260824-10b251d`
保持原字节并登记为 `rejected`。`20260824-f953c58` 的直接前任 `20260824-afe109c`
仍为 `rejected`。

## 自动化门禁

构建必须使用已生成的 `v0.25.0-alpha` 候选归档作为基线，并依次完成：

1. 显式白名单组装和发布文件 SHA-256 清单；
2. 格式规则包编译后逐字节一致性检查；
3. Python 3.8 静态兼容性、正式插件契约（含 `AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN"` 跨运行时对拍）和 Adapter 导入/公开接口检查；
4. v0.25.1 专用版本、插件缓存身份、格式规则资产和安全范围审计；
5. 真实 Python 3.8 生命周期门禁，包括全新安装、v0.25.0 基线升级、故障注入和事务回退。

候选的源提交记录在 `release-manifest.json` 的 `candidateEvidence.sourceCommit`，独立构建标识记录在 `candidateEvidence.candidateBuildId`；归档 SHA-256 记录在同名 `.sha256` 文件中。源码 `packaging/v0251-candidate-status.json` 只保留一个 `candidate` 记录，即 d7a1dd8；直接前任 `10b251d` 保持 `rejected`，Issue #59 仍为 `manual-pending`。

本次可复核的自动化证据为：Sol/high 核心结论 `CLEAN FOR BUILD`；核心 focused
`199 passed, 1 skipped`；Adapter `874 passed, 95 skipped`；正式插件
`28/28`；交付 focused `87 passed`，协议/交付 aggregate `137 passed, 5 skipped`。

| 门禁 | 结果 |
| --- | --- |
| v0.25.1 交付/prepare/audit focused | `87 passed`（`test_v0251_delivery.py`） |
| 协议/交付 focused 合计 | `137 passed, 5 skipped` |
| 正式插件合同测试 | `28/28` |
| v0.25.1 delivery/prepare/audit focused | `87 passed` (`test_v0251_delivery.py`) |
| Focused protocol/delivery aggregate | `137 passed, 5 skipped` |
| Formal plugin contract tests | `28/28` |

以上数字与当时候选构建一致：
Kylin Node `v22.23.2`、Python `3.8.10`；source provenance `246`、Python 3.8
扫描 `82`；公开 format-review API、`characterCount`/`contentSha256`/
`structureSha256`/`formatSha256` 四个哈希键，以及 runtime/lifecycle/install/
upgrade/rollback/deleted-workflow-profile gates 均通过；本地 checksum 与最终
candidate audit 均通过。以上结果只证明自动化 candidate，不证明 Issue #59 的真实
WPS、模型或目标机验收。

## Issue #59 现场验收步骤

以下步骤交给 Issue #59 执行，作为 manual acceptance gate，不能由本地自动化结论替代：

- 在麒麟 V10 ARM、Python 3.8、目标 WPS 12.1.2 上安装该 Phase1 候选，核对 `/health`、Adapter、Word/Excel/PPT 插件和缓存版本均为 `0.25.1-alpha`。
- 验证退役同步路由 `POST /word/format-review` 固定返回 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED` 且不执行审查；结构/格式哈希、OutlineLevel 和格式事实验收只通过 `word.format_review.snapshot.v2` 的 snapshot/batch/job v2 后台路径执行，使用包含 `OutlineLevel=10` 正文、`OutlineLevel=0` 正文和 1–9 级标题的只读 Word 样本文档，正文不生成标题跳级，一级后三级只生成一条可定位问题。
- 核对标题问题显示真实 `P<n>` 或“位置待确认”，不出现 `P0 未识别角色`；审查前后正文、格式和结构摘要一致，未写回 Word。
- 在 `word.format_review` 中配置模型直连，使用合成 `format_semantics.v1` `classify_role` 验证调用；核对验证显示配置名称、ID、修订和当前任务关系，验证不会自动激活，正式审查不上传用户文档或 API Key。
- 分别验证无候选、调用失败、协议/解析失败、越界、低置信度、零接受和正常接受场景；报告将“识别来源”和“模型执行诊断”分开显示，并披露调用数、候选数、尝试数和接受数。
- 在 WPS 运行期间关闭文档、重开任务窗格、重启 Adapter，确认退役同步路由仍固定返回 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED` 且不执行审查；独立验证 `word.format_review.snapshot.v2` 的 snapshot/batch/job 取消、失败和重启生命周期不留下临时文件；检查日志、诊断和导出不包含 API Key、认证头、完整正文、模型思维内容或敏感绝对路径。
- 在安装中断或健康检查失败时，依据事务日志执行整代际回退，确认上一版本的 Adapter、三宿主插件、发布清单和运行数据快照保持一致；本工单不自动关闭或替代 Issue #59。

## 明确边界

现场填写模板见 `docs/v0251-target-machine-acceptance.md`。该模板只保存
脱敏摘要；目标机原始证据不得写入仓库，且记录必须保持 `manual-pending`
直到全部 Issue #59 必测项目完成。

候选不包含素材编排、共享本地文档抽取重构或 DOCX `styleId` 缺陷修复。新安装图像语义总开关默认开启；关闭时不导出、上传或分配图片像素槽位。Issue #59 仍为 `manual-pending`。
