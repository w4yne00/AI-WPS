# v0.25.1-alpha candidate delivery note

## 候选身份

- Candidate label: `20260824-f953c58`
- Candidate build ID: `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-f953c58312c8d3d42d3dccea402fccf55a3c7d53`
- Source commit: `f953c58312c8d3d42d3dccea402fccf55a3c7d53`
- Archive name: `ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz`
- Archive checksum file: `ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz.sha256`
- Archive SHA-256: `833e71fcf5a6e2172c93e44cc3502d46e1ea89c5dc4abb77f658ac8c5ee77ee7`
- Automated status: `candidate`
- Target acceptance status: `manual-pending` (Issue #59)

The package uses the accepted `v0.25.0-alpha` Phase1 baseline and explicit
allowlist assembly. The v2 deterministic format-review contract is
`word.format_review.snapshot.v2`; JavaScript and Python independently verify
`characterCount`, `contentSha256`, `structureSha256`, and `formatSha256`.
The contract uses `format_semantics.v1` rule assets, UTF-16 character counts,
stable compact JSON, and fail-closed trust-boundary checks. A successful
automated gate records only `candidate`; it is not manual acceptance.

`20260824-afe109c` is the superseded rejected candidate. Its archive
`ai-wps-phase1-delivery-20260824-afe109c-v0251.tar.gz` has SHA-256
`e3d4da0d1d8e1edc619d2101f45afb104ef8e3a6e5197e4b8e59b46513f78c6b` and remains
byte-frozen. The previous `20260824-799adf9`, `20260824-5318d4b`,
`20260824-2e7a3e6`, and `20260824-ccad09f` records remain `rejected` with their
original identities and archive digests.

## 自动化门禁

构建必须使用已生成的 `v0.25.0-alpha` 候选归档作为基线，并依次完成：

1. 显式白名单组装和发布文件 SHA-256 清单；
2. 格式规则包编译后逐字节一致性检查；
3. Python 3.8 静态兼容性、正式插件契约（含 `AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN"` 跨运行时对拍）和 Adapter 导入/公开接口检查；
4. v0.25.1 专用版本、插件缓存身份、格式规则资产和安全范围审计；
5. 真实 Python 3.8 生命周期门禁，包括全新安装、v0.25.0 基线升级、故障注入和事务回退。

候选的源提交记录在 `release-manifest.json` 的 `candidateEvidence.sourceCommit`，独立构建标识记录在 `candidateEvidence.candidateBuildId`；归档 SHA-256 记录在同名 `.sha256` 文件中。源码 `packaging/v0251-candidate-status.json` 将 `f953c58` 作为唯一 `candidate`，并将 `afe109c`、`799adf9`、`5318d4b`、`2e7a3e6`、`ccad09f` 及更早历史记录保持为 `rejected`；Issue #59 仍为 `manual-pending`。

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

候选不包含素材编排、共享本地文档抽取重构、DOCX `styleId` 缺陷修复或图片语义启用。图片语义保持关闭，不导出、上传或分配图片像素槽位。
