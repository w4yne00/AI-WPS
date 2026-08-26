# v0.25.3-alpha delivery note

## 候选身份

- Candidate label: `20260826-d1a346b`
- Candidate build ID: `AI-WPS-P1-WORD-EXCEL-PPT-0.25.3-20260826-d1a346b0d7e1301f74b37e692664fd31085ee050`
- Source commit: `d1a346b0d7e1301f74b37e692664fd31085ee050`
- Archive name: `ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz`
- Archive checksum file: `ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz.sha256`
- Archive SHA-256: `120a2cfd8decd956224c3702721d85846bdaecf91d71b87b31c0f7be1b258cb7`
- Archive naming template: `ai-wps-phase1-delivery-<YYYYMMDD>-<SOURCE_COMMIT>-v0253.tar.gz`
- Automated status: `candidate`
- Target acceptance status: `manual-pending` (Issue #59)

`v0.25.3-alpha` 沿用 Phase1 安装体系，不进入 Preview 安装断代。自动化门禁只产生 `candidate`。Issue #59 的目标 WPS GUI、真实模型和人工文档验收仍为 `manual-pending`。

已冻结的 `v0.25.2-alpha` 候选 `20260825-850871c` 保持原字节，SHA-256 为
`c5d663d1249147104bee66790fea60f5e15675418a51c0c1a7a0fc028a285a92`，状态仍为
`candidate`，不再登记为 0.25.3 的当前候选。冻结的 `v0.25.1-alpha` 候选
`20260824-d7a1dd8` 保持原字节，SHA-256 为
`ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`。

The package uses the accepted `v0.25.2-alpha` Phase1 baseline (`850871c`) and
explicit allowlist assembly. The v2 deterministic format-review contract remains
`word.format_review.snapshot.v2` with `format_semantics.v1` rule assets.

## 0.25.3 能力边界

本版本落实 Issue #101 的三路能力，不改写已冻结的 0.25.2 候选身份：

- **结果预览**：Word / Excel / PPT 任务窗按受限 Markdown 预览语法渲染标题、列表、表格和加粗。对照保持已渲染高亮。纯文本才是源码。Excel 继续使用分析报告和汇报段落，不改名。
- **格式问题**：操作面改为问题卡片和独立操作条。预览顶部只留覆盖和计数摘要。题注关联结论显示已关联、孤立、缺失或歧义，不得用无法识别冒充关联结论。
- **幻灯片页角色**：结构审查先判定封面页、目录页、过渡页、正文页、结束页或未确认页角色，再执行规则豁免。结果展示页角色清单；目录页和结束页豁免缺标题，封面缺标题仍报。

0.25.2 已发布的**图像语义补充**默认开启、覆盖升级迁移和视觉关闭降级保持不变。

退役同步路由 `POST /word/format-review` 固定返回 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED`。
结构/格式哈希验收只通过 `word.format_review.snapshot.v2` 后台路径执行。

## 自动化门禁

构建必须使用已冻结的 `v0.25.2-alpha` 候选归档作为基线，并依次完成显式白名单组装、格式规则包编译一致性、Python 3.8 静态兼容、正式插件契约、v0.25.3 专用身份审计和真实 Python 3.8 生命周期门禁。自动化通过只得到 `candidate`。

麒麟 V10 ARM64 / Python 3.8.10 已对 `d1a346b` 执行生命周期门禁，终态为 `candidate`。系统 Python 无 pip 时 get-pip 使用 `-sS`，不加载麒麟 apt 的 `dist-packages`。该结论不等于 Issue #59 目标机验收。冻结的 `20260825-850871c` 保持原字节，不是 0.25.3 当前候选。

## 明确边界

现场填写模板见 `docs/v0253-target-machine-acceptance.md`。该模板只保存脱敏摘要；目标机原始证据不得写入仓库。自动化 `candidate` 不等于真实 WPS、模型或 Issue #59 目标验收。
