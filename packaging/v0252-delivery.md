# v0.25.2-alpha delivery note

## 候选身份

- Candidate label: `20260825-dacd1e9`
- Candidate build ID: `AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-20260825-dacd1e9d0df9b18ca8103d3270f8bf979931cb87`
- Source commit: `dacd1e9d0df9b18ca8103d3270f8bf979931cb87`
- Archive name: `ai-wps-phase1-delivery-20260825-dacd1e9-v0252.tar.gz`
- Archive checksum file: `ai-wps-phase1-delivery-20260825-dacd1e9-v0252.tar.gz.sha256`
- Archive SHA-256: `c1dfc64fb099c21a8fa05fb64fad4f98d8b7ac5500de052a3f03c3fa8f075871`
- Archive naming template: `ai-wps-phase1-delivery-<YYYYMMDD>-<SOURCE_COMMIT>-v0252.tar.gz`
- Automated status: `candidate`
- Target acceptance status: `manual-pending` (Issue #59)

`v0.25.2-alpha` 沿用 Phase1 安装体系，不进入 Preview 安装断代。自动化门禁只产生 `candidate`。Issue #59 的目标 WPS GUI、真实模型和人工文档验收仍为 `manual-pending`。

已冻结的 `v0.25.1-alpha` 候选 `20260824-d7a1dd8` 保持原字节，SHA-256 为
`ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`，状态仍为
`candidate`，不再登记为 0.25.2 的当前候选。

The package uses the accepted `v0.25.1-alpha` Phase1 baseline (`d7a1dd8`) and explicit
allowlist assembly. The v2 deterministic format-review contract remains
`word.format_review.snapshot.v2` with `format_semantics.v1` rule assets.

## 0.25.2 能力边界

本版本把格式审查模型直连下的**图像语义补充**从休眠默认改为可外发像素：

- 新安装图像语义总开关默认开启；关闭时不导出、不上传、不分配图片像素槽位。
- 从 `v0.25.1-alpha` 覆盖升级后，总开关开启，已有格式审查直连配置进入默认可外发并补写绑定；工作流平台和其它任务的图片输入模式不改写。
- 视觉能力验证未通过、`SaveAsPicture` 失败或总开关关闭时走**视觉关闭降级**：确定性格式审查照常完成，不得声称已看图。
- 不绑定导出验收勾选。保存可用的格式审查直连配置即写入图片外发授权绑定。
- 用户可见文案保持「图像语义补充」，不改成内容审查或 OCR，也不把自动化 candidate 写成 Issue #59 已通过。

退役同步路由 `POST /word/format-review` 固定返回 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED` 且不执行审查；结构/格式哈希、OutlineLevel 和格式事实验收只通过 `word.format_review.snapshot.v2` 的 snapshot/batch/job v2 后台路径执行。独立验证 `word.format_review.snapshot.v2` 的 snapshot/batch/job 取消、失败和重启生命周期。

## 自动化门禁

构建必须使用已冻结的 `v0.25.1-alpha` 候选归档作为基线，并依次完成显式白名单组装、格式规则包编译一致性、Python 3.8 静态兼容、正式插件契约、v0.25.2 专用身份审计和真实 Python 3.8 生命周期门禁。自动化通过只得到 `candidate`。

麒麟 V10 ARM64 / Python 3.8.10 已对 `dacd1e9` 执行生命周期门禁，终态为 `candidate`。该结论不等于 Issue #59 目标机验收。系统 Python 无 pip 时，get-pip 使用 `-sS`，不加载麒麟 apt 的 `dist-packages`，因此不再打印 `distro-info`/`python-apt` 非法版本或 `launchpadlib`/`testresources` 冲突。前任 `20260825-0f50456` 已登记为 `rejected`，保持原字节。

## 明确边界

现场填写模板见 `docs/v0252-target-machine-acceptance.md`。该模板只保存脱敏摘要；目标机原始证据不得写入仓库。自动化 `candidate` 不等于真实 WPS、模型或 Issue #59 目标验收。
