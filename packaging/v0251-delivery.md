# v0.25.1-alpha candidate delivery note

当前没有活动的自动化候选。归档记录 `20260824-799adf9` 的 candidateBuildId 为
`AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-799adf93cc1e594a82b6d2bc88abcf08b3f3c252`，
源码提交 `799adf93cc1e594a82b6d2bc88abcf08b3f3c252`，归档
`ai-wps-phase1-delivery-20260824-799adf9-v0251.tar.gz`，校验文件
`ai-wps-phase1-delivery-20260824-799adf9-v0251.tar.gz.sha256`，SHA-256
`5f15e385358dcaea987e62f43cd2db1b943696372a7867449a986cdfc403f67c`；该归档已登记为
`rejected`：包内目标机验收文档仍声称“暂无候选”，与 manifest/status 的候选身份不一致。
修复源在重新构建归档前不属于候选。上一候选 `20260824-5318d4b` 及更早归档仍保持原
`rejected` 记录，Issue #59 目标 WPS GUI、真实模型和人工验收仍为 `manual-pending`。

历史候选 `20260824-ccad09f` 已登记为 `rejected`：其
`word.format_review.snapshot.v2` 在 WPS JavaScript 与 Python Adapter 的 structure/format
哈希前镜像不一致。`20260824-2e7a3e6` 也已登记为 `rejected`，candidateBuildId
`AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f`，
源码提交 `2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f`，归档
`ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz`，SHA-256
`576ad6580fc261e486adb3bac784d2e2a7f47c4f62209686bb1e2e58b5599c1e`。其拒绝原因是包内交付
说明过期且缺失大纲事实被写为 `null`。Issue #59 目标 WPS GUI、真实模型和人工验收仍为
`manual-pending`。

## 自动化门禁

构建必须使用已生成的 `v0.25.0-alpha` 候选归档作为基线，并依次完成：

1. 显式白名单组装和发布文件 SHA-256 清单；
2. 格式规则包编译后逐字节一致性检查；
3. Python 3.8 静态兼容性、正式插件契约（含 `AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN"` 跨运行时对拍）和 Adapter 导入/公开接口检查；
4. v0.25.1 专用版本、插件缓存身份、格式规则资产和安全范围审计；
5. 真实 Python 3.8 生命周期门禁，包括全新安装、v0.25.0 基线升级、故障注入和事务回退。

候选的源提交记录在 `release-manifest.json` 的 `candidateEvidence.sourceCommit`，独立构建标识记录在 `candidateEvidence.candidateBuildId`；归档 SHA-256 记录在同名 `.sha256` 文件中。源码 `packaging/v0251-candidate-status.json` 保留 `20260824-799adf9` 及所有历史 `rejected` 记录；修复源尚未形成新的候选，Issue #59 仍为 `manual-pending`。

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
