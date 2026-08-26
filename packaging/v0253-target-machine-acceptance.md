# v0.25.3 目标机整合验收记录

## 基本信息

- 对应工单：[Issue #59](https://github.com/w4yne00/AI-WPS/issues/59)
- 验收版本：`v0.25.3-alpha`
- 验收范围：麒麟 V10 ARM、目标 WPS、`cloud` 用户环境
- 当前记录状态：`manual-pending`
<!-- V0253-CANDIDATE-CONTEXT:BEGIN -->
- 当前源树没有活动的 0.25.3 候选；冻结的 `v0.25.2-alpha` 候选 `850871c` 保持原字节，SHA-256 为 `c5d663d1249147104bee66790fea60f5e15675418a51c0c1a7a0fc028a285a92`，状态仍为 `candidate`，不是 0.25.3 当前候选。
<!-- V0253-CANDIDATE-CONTEXT:END -->
- 验收人员：
- 验收日期：
- 交付包文件名：
- 交付包 SHA-256：
- v0.25.2 基线包 SHA-256：

本记录是目标机现场填写模板。候选上下文由 `prepare_v0253_delivery.py` 在组装交付树时整体生成；自动化门禁只能证明候选构建，不能替代麒麟 V10、目标 WPS 和 `cloud` 用户环境中的真实操作。所有现场原始命令输出、截图、目标机编号、账号信息、配置内容、API Key、文档正文和模型原始回复只保留在受控验收记录中，不写入仓库。

## 验收结论规则

- `manual-pending`：尚未在全部目标环境完成，或仍有任一项待验证/阻塞。
- `passed`：下表全部项目均有现场证据，且没有 `blocked`、`failed` 或 `unverified` 项。
- `failed`：任一必测项目失败，或发现升级、只读、隐私或数据生命周期问题。

只有全部必测项为 `passed` 时，才可以把记录状态改为 `passed` 并决定是否关闭 Issue #59。自动化测试、静态审计或候选包构建成功都不能单独改变该状态。

## 必测项目

| 编号 | 验收项目 | 结果（`manual-pending`/`passed`/`failed`） | 现场证据引用（脱敏） | 备注 |
| --- | --- | --- | --- | --- |
| 1 | 从已验收的最新适用 `0.24.x` 版本真实升级；配置、Key 引用、写作规范库、文档审查和回退能力保持 | `manual-pending` |  |  |
| 2 | 全文与选区验证 `60,000`/`120,000` 审查字符、混合字符格式、复杂表格、题注关系、不支持对象和容量拒绝边界 | `manual-pending` |  |  |
| 3 | 验证抽取响应性、两遍指纹、编辑中止、取消、关闭 WPS、Adapter 重启、公平调度、分页、导出和保守定位 | `manual-pending` |  |  |
| 4 | 审查前后 Word 正文、格式、表格及对象摘要一致，证明全链路只读 | `manual-pending` |  |  |
| 5 | 验证 Word 设置页、三宿主任务配置标签及 Excel/PPT Ribbon 图标在常规、窄窗和高 DPI 下可用 | `manual-pending` |  |  |
| 6 | 新安装图像语义总开关默认开启；覆盖升级后旧格式审查直连进入默认可外发。总开关关闭或探针未过时走视觉关闭降级，确定性审查完成。不绑定导出验收勾选。真实 `SaveAsPicture` 保真度留待 Issue #59，不作为本记录的通过依据 | `manual-pending` |  |  |
| 7 | 日志、诊断和报告不包含正文、图片像素、模型原始回复、API Key 或敏感本地路径 | `manual-pending` |  |  |
| 8 | 真实 WPS 批次同时核对 `characterCount`、`contentSha256`、`structureSha256`、`formatSha256`；普通块含 `images: []`，表格/嵌套表格、cell format、图片元数据和非 BMP 字符均参与对拍 | `manual-pending` |  | 任一 structure/format 漂移或 `DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` 均不得进入后台任务 |
| 9 | 只篡改 structure 或 format 声明时均返回 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH`，且不启动 reviewer/provider；图片项确认 `pixelExportCount=0`、`pixelUploadCount=0` | `manual-pending` |  |  |
| 10 | Word/Excel/PPT **结果预览**按受限语法渲染；对照保持高亮；纯文本为源码；Excel 汇报段落不改名 | `manual-pending` |  |  |
| 11 | **格式问题**以卡片操作条呈现；**题注关联结论**显示已关联、孤立、缺失或歧义，不得用无法识别冒充 | `manual-pending` |  |  |
| 12 | 结构审查展示**幻灯片页角色**清单；目录/结束豁免缺标题；封面缺标题仍报；局部页段不升格封面/结束 | `manual-pending` |  |  |

### v2 后台格式审查判定矩阵

以下每一行必须独立执行并记录现场证据；所有合法场景只走
`word.format_review.snapshot.v2` 后台批次，不调用退役同步路由。四项指标对拍必须同时记录
`characterCount`、`contentSha256`、`structureSha256`、`formatSha256` 的 JS/Python 值及是否一致；
`409` 栏记录 HTTP 状态与 Adapter code；后台任务栏记录是否创建/启动 `jobId`，不得以“未报错”代替。

| 用例 | 输入与独立预期 | 四项指标 JS/Python 对拍记录 | 409 记录 | 后台任务记录 |
| --- | --- | --- | --- | --- |
| `OutlineLevel=0` | 段落保留为正文块，规范化 `outlineLevel=0`，不得生成 heading | 四项值：；一致： | 合法输入应无 409；篡改对应 structure/format 声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`；篡改输入不得启动 reviewer/provider |
| `OutlineLevel=10` | 按规则归一为 `0`，保留正文语义，不得生成 heading | 四项值：；一致： | 合法输入应无 409；篡改对应 structure/format 声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`；篡改输入不得启动 reviewer/provider |
| `OutlineLevel=1..9` | 分别执行 1 至 9 级；每级规范化值与输入相等并生成对应 heading level | 四项值：；一致： | 合法输入应无 409；逐级篡改对应 structure/format 声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 每级合法输入均应启动并记录 `jobId`；篡改输入不得启动 reviewer/provider |
| `表格/嵌套表格` | 递归核对表格行列、合并跨度、嵌套表格和 cell format，正文按规范化表格文本计算 | `characterCount` JS/Python：；`contentSha256` JS/Python：；`structureSha256` JS/Python：；`formatSha256` JS/Python：；四项指标 JS/Python 对拍一致： | 合法输入应无 409；篡改表格结构或 cell format 时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`/后台任务；篡改输入不得启动 reviewer/provider |
| `图片元数据` | 同一图片块只核对 `fingerprint`、`altText`、关联和题注等稳定元数据；不导出像素 | `characterCount` JS/Python：；`contentSha256` JS/Python：；`structureSha256` JS/Python：；`formatSha256` JS/Python：；四项指标 JS/Python 对拍一致；`pixelExportCount=0`；`pixelUploadCount=0` | 合法输入应无 409；篡改图片元数据或声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`/后台任务；篡改输入不得启动 reviewer/provider |
| `非 BMP emoji` | 使用 `😀`、`🚀`、`𠮷` 等非 BMP 字符核对 UTF-16 `characterCount` 与正文/表格哈希 | `characterCount` JS/Python：；`contentSha256` JS/Python：；`structureSha256` JS/Python：；`formatSha256` JS/Python：；四项指标 JS/Python 对拍一致： | 合法输入应无 409；篡改任一 structure/format 声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`/后台任务；篡改输入不得启动 reviewer/provider |
| `dataStatus=insufficient` 且 reason 非空 | 非空 `insufficientReason` 保留（按协议上限截断），并在格式事实/诊断中可见 | 四项值：；一致： | 合法输入应无 409；篡改 reason/format 后保留原声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`；篡改输入不得启动 reviewer/provider |
| 其它 `dataStatus` | 对 `verified`、`mixed`、`unknown`、`read_failed`、`unsupported`、`context_only` 分别执行；`insufficientReason` 必须为空/缺失 | 四项值：；一致： | 合法输入应无 409；篡改 reason/format 后保留原声明时记录 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH` | 合法输入应启动并记录 `jobId`；篡改输入不得启动 reviewer/provider |

现场证据引用（脱敏）：

- JS/Python 四项指标对拍：
- 409 响应与 Adapter code：
- 后台 `jobId`、终态和 reviewer/provider 调用计数：

## 现场执行摘要

### 升级、回退和数据保持

- 基线版本及其验收记录：
- 升级前配置/Key/规范库摘要（仅填写数量、版本或不可逆指纹）：
- 升级后配置/Key/规范库摘要：
- 文档审查与回退验证结果：
- Adapter 重启和 WPS 重启后结果：

### Word 全文与选区

- `60,000` 字符全文两遍抽取目标 ≤ 30 秒；现场耗时和任务窗格响应：
- `120,000` 字符全文两遍抽取目标 ≤ 60 秒；现场耗时和任务窗格响应：
- 两遍指纹（内容哈希、结构哈希和格式/对象摘要）一致：
- 选区扩展、范围外隔离和容量拒绝结果：
- 混合字符格式、复杂/嵌套/合并表格、题注关系和不支持对象结果：

### 任务生命周期与报告

- 编辑中止、取消、关闭 WPS、Adapter 重启和网络异常结果：
- 公平调度和交互任务优先结果：
- 分页、筛选、处理状态、Markdown/JSON 导出和保守定位结果：
- 任务终态、报告保留和临时数据清理结果：

### 三宿主 UI 与只读边界

- Word 设置页和任务配置标签结果：
- Excel/PPT Ribbon 图标、任务配置标签结果：
- 常规、窄窗、高 DPI 和键盘操作结果：
- Word 正文、格式、表格、对象摘要前后值：
- Excel/PPT 文档或工作簿摘要前后值（如本轮联测覆盖）：

### 隐私与视觉关闭降级

- `formatReview.imageSemantics.enabled` 新安装/升级后现场值：`true`（运维止损关闭时为 `false`）
- 视觉关闭降级时像素导出槽位、`SaveAsPicture`、像素上传调用计数：
- 日志/诊断/报告脱敏检查结果：
- 受控原始证据保存位置（不得填写 API Key 或用户正文）：


### 结果预览、格式问题与幻灯片页角色

- 结果预览：Word 有结构/无结构、对照高亮、纯文本源码、复制非 HTML：
- Excel 分析报告渲染、汇报段落未渲染、名称未改成预览/纯文本：
- PPT 智能总结预览与非结构化降级仍渲染：
- 格式问题卡片：操作条与位置句分离，窄窗只在条内折行：
- 题注关联结论：已关联/孤立/缺失/歧义；无法识别仅用于未映射字体：
- 幻灯片页角色清单与逐页标签；目录/结束空标题不再报缺标题：

## 发布决定

- 记录状态：`manual-pending`
- 是否允许关闭 Issue #59：否，须待全部目标机必测项目为 `passed`
- 自动化 `candidate` 不能改写 Issue #59 结论
- 图像语义补充默认开启不等于内容审查或 OCR
- 现场遗留问题及跟踪工单：
