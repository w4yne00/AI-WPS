# v0.25.1 格式审查跨运行时哈希契约修复计划

> **状态：** 可执行；`20260824-ccad09f` 存在阻断缺陷，必须停止分发并登记为 `rejected`。
>
> **执行约束：** 代码修复交由 `luna`、思考级别“极高”的子智能体实施；实施前完整重读 `AGENTS.md`、`docs/codex-handoff.md` 和本计划。不得改写或删除用户的 `config/adapter.json`、`run/`、`.scratch/writing-policy-review/` 及未跟踪历史归档。

## 目标与版本裁决

修复 Word 格式审查 v2 批次在 WPS JavaScript 与 Python Adapter 之间的哈希前镜像不一致，使同一批规范化语义块在两个运行时得到完全相同的：

- `characterCount`
- `contentSha256`
- `structureSha256`
- `formatSha256`

**版本裁决：继续构建 `v0.25.1-alpha` 的新候选，不升为 `v0.25.2-alpha`。** 理由：

1. `20260824-ccad09f` 仍为 `candidate`，Issue #59 未接受，尚未形成对外稳定版本边界。
2. 本修复恢复 `word.format_review.snapshot.v2` 原本要求的跨运行时完整性校验，不新增用户能力、不改变已接受的公开业务语义，也不允许兼容旧错误哈希。
3. ADR-0119 已明确：未通过人工审查的 `v0.25.1-alpha` 构建应标记为 `rejected`，修复后仍以同一产品版本、不同日期和源码提交号形成新候选。
4. 新候选必须有新的完整源码提交、`candidateBuildId`、归档名和 SHA-256；旧归档及校验文件保持不可变。若实施期间发现 `ccad09f` 已被登记为 `target-accepted` 或作为稳定版本外部分发，则暂停构建并重新裁决为 `v0.25.2-alpha`。

## 已确认根因与潜在同类缺陷

当前前端在 `taskpane-helpers.js` 中直接对构造出的 JS 块投影并哈希，Adapter 则先调用 `_normalize_format_blocks()`，再由 `_format_metrics()` 对规范化结果投影并哈希。两端实际使用的是两套哈希前镜像：

| 维度 | JavaScript 当前行为 | Python 当前行为 | 裁决 |
| --- | --- | --- | --- |
| 普通块图片字段 | structure 固定包含 `images: []` | structure 不包含 `images` | structure 固定包含规范化 `images`，空数组也保留 |
| 空不足原因 | format 包含 `insufficientReason: ""` | 删除空 reason | 仅 `dataStatus="insufficient"` 且 reason 非空时保留 |
| 大纲级别 | 块顶层有 `outlineLevel`，format 中缺失 | 规范化后补 `format.outlineLevel`，未知值为 `null` | 顶层与 format 使用同一规范值；存在大纲事实时两处都保留，包括 `null` |
| 图片块文本 | JS 内容投影跳过空文本 | Python 把空字符串加入换行拼接 | 图片空文本不进入内容前镜像，图片元数据进入结构前镜像 |
| 表格默认值 | JS 可能按 `0` 或空 ID 投影 | Python 为行列和单元格补 1-based 默认值/ID | 上传前按同一 1-based 规则递归规范化 |
| 长度格式值 | JS 可能哈希 point 标量，同时携带已规范化 fact | Python 会按 fact 把标量改为 twip/规范单位 | 哈希规范化标量，原始值只保留在 fact 的 `rawValue/rawUnit` |
| 嵌套表格 | JS 递归投影原值 | Python 当前只完整规范化顶层 rows | 顶层与嵌套表格调用同一个递归规范化函数 |
| emoji 字符数 | JS `String.length` 计算 UTF-16 code unit | Python 已用 UTF-16LE 字节数除以 2 | 明确锁定 UTF-16 code unit，并加入非 BMP 回归 |

当前报告只暴露 `images`、`insufficientReason` 和 `outlineLevel` 三处差异，不能据此做字段级补丁。表格、图片和非零缩进一旦进入同一批次，仍可能出现新的哈希差异。实施必须把“规范化块 → 固定投影 → 规范 JSON → SHA-256”作为一个完整契约修复。

## 锁定的 `snapshot.v2` 哈希契约

本计划不新增第三套兼容分支。两端必须实现并测试同一个逻辑契约：

1. **规范化块先于哈希。** JS 构建出的 `blocks` 必须先成为上传用规范块；批次、整份快照和第二遍验证只对这些规范块计算。Adapter 在信任边界再次执行同一语义的防御性规范化，且满足幂等性：`normalize(normalize(blocks)) == normalize(blocks)`。
2. **内容前镜像。** 按块顺序取 `scope == "in_scope"` 的非空规范文本，使用 `\n` 连接；表格文本由递归行/单元格文本按稳定顺序生成，图片空文本不增加额外换行。SHA-256 输入为 UTF-8。
3. **字符数。** 对上述每个文本值计算 UTF-16 code unit 数并求和；不能改为 Unicode code point 数或 UTF-8 字节数。
4. **结构前镜像。** 每个块固定投影 `blockId/blockType/scope/paragraphIndex/range/tableId/tableIndex/headingLevel/listLabel/captionFor/rows/nestedTables/images`。`images` 始终存在；图片顺序保持采集顺序，并只投影稳定元数据 `imageId/groupId/fingerprint/captionStatus/associationStatus/supported/altText/nearbyText`。
5. **格式前镜像。** 每个块固定投影 `blockId/scope/format/segments/table`；表格格式递归投影行、单元格 ID 和规范化 cell format。`segments` 保持现有重复投影，避免无关协议变化。
6. **可选字段。** `undefined`/函数不进入 JSON；协议中的明确 `null` 保留。空 `insufficientReason` 删除，非空不足原因截断规则与 Adapter 一致。
7. **大纲事实。** WPS `0` 和 `10` 规范为正文 `0`，`1..9` 保持标题级别，其他值为 `null`。原始 `outlineLevel` 优先于派生 `headingLevel`；规范值同步写入块顶层与 `format.outlineLevel`。
8. **规范 JSON。** 对象键按 Unicode/JavaScript 默认字符串顺序升序，数组顺序不变，紧凑 JSON，不 ASCII 转义中文或 emoji；最终以 UTF-8 计算 SHA-256。禁止通过删除图片、格式或结构维度来换取哈希一致。
9. **服务端校验保持强制。** Adapter 对每个批次重算四项指标，并逐项精确比较；任一不一致返回 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH`，不保存该批次、不启动任务、不调用模型。commit 与第二遍验证继续同时校验内容、结构、格式和覆盖统计。

新增 ADR `docs/adr/0120-use-one-cross-runtime-format-review-hash-contract.md`，记录上述契约、同版本新候选裁决、替代方案及风险。ADR 是规范说明；运行时代码只保留各自一个规范化入口，跨运行时测试负责证明两个实现没有漂移。

## 预计文件范围

### 生产代码与构建门禁

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- `adapter_service/app/services/word/deterministic_format_review.py`
- `packaging/build_v0251_delivery_kit.sh`

### 测试

- 新增 `formal-plugin-kit/tests/format-review-hash-contract.test.js`
- 修改 `formal-plugin-kit/tests/deterministic-format-review.test.js`
- 修改 `adapter_service/tests/test_deterministic_format_snapshot_protocol.py`
- 视实际复用边界修改 `adapter_service/tests/test_outline_levels.py`
- 修改 `adapter_service/tests/test_v0251_delivery.py`

### 决策、交付与跨会话状态

- 新增 `docs/adr/0120-use-one-cross-runtime-format-review-hash-contract.md`
- 修改 `packaging/v0251-candidate-status.json`
- 修改 `packaging/v0251-delivery.md`
- 修改 `packaging/v0251-target-machine-acceptance.md`
- 修改 `README.md`
- 修改 `README-ZH.md`
- 修改 `docs/codex-handoff.md`

不要改同步 `/word/format-review` 退役路由、格式语义模型协议、规则包、写回逻辑、图片像素开关或其他七类模型任务。

## 实施步骤

### 任务 0：先传播阻断状态，避免其他会话继续使用旧候选

- [ ] 在 `docs/codex-handoff.md` 顶部将 `20260824-ccad09f` 明确标为“已确认阻断、待登记 rejected、不得继续分发”，链接本计划，并说明修复中的源码尚未形成候选。
- [ ] 在 `packaging/v0251-candidate-status.json` 新增 `ccad09f` 的完整记录：完整源码提交 `ccad09fb1d8019da3a40f14610ab3bd75de1ec23`、现有归档名、现有 SHA-256 `2c3f8b5004c40fb7271a6afe7e4c8a292acb227b9d3ec08afc7f6b561d413a02`、`status: "rejected"`，原因写明跨运行时 structure/format 哈希契约不一致。
- [ ] 保留现有归档和 `.sha256` 文件原字节，不重命名、不覆盖、不删除。

**完成标准：** 任何新会话按仓库 `AGENTS.md` 强制读取 handoff 后，都能看到旧候选已阻断、活动计划路径和禁止分发边界；状态 JSON 能被 v0.25.1 审计读取。

### 任务 1：先建立跨运行时红灯测试

- [ ] 新增 `format-review-hash-contract.test.js`。测试必须调用真实 `buildDeterministicFormatReviewBody()` 和 `buildDeterministicFormatReviewBatches()` 生成 JS 批次，再用子进程把 `blocks` 送入真实 Python `DeterministicFormatReviewService._normalize_format_blocks()` 与 `_format_metrics()`；禁止在测试中复制一份简化 Python/JS 哈希算法。
- [ ] Python 可执行文件由 `AI_WPS_HASH_CONTRACT_PYTHON` 指定，默认 `python3`；子进程显式设置 `PYTHONPATH=<repo>/adapter_service`，失败时完整报告 stderr 和退出码，不静默跳过。
- [ ] 表驱动用例至少独立覆盖：
  - 普通正文（WPS `OutlineLevel=10` 与 `0` 至少各一个）；
  - 标题（`OutlineLevel=1..9`，含一级后三级的结构差异）；
  - 表格（1-based 行列、缺省单元格 ID、row/column span、cell format；至少一个嵌套表格）；
  - 图片元数据块（非空 images；保持图片语义关闭，不读取或上传像素）；
  - `dataStatus="insufficient"` 的非空 reason，以及 verified/unknown 下的空 reason；
  - 含 `😀`、`🚀`、`𠮷` 等非 BMP 字符的正文和表格单元格。
- [ ] 对每个用例及其每个批次断言 JS 与 Python 的四项指标全部相同；额外断言规范块幂等、普通块结构含 `images: []`、图片元数据确实改变 `structureSha256`、格式值或 reason 改变 `formatSha256`、emoji 的字符数按 UTF-16 code unit 计算。
- [ ] 先运行测试并保存预期红灯证据：当前版本应至少同时显示 structure 和 format 不一致；图片/表格用例若暴露额外差异，也纳入本次修复，不缩减夹具规避。

**完成标准：** 红灯能够用当前 `ccad09f` 逻辑稳定复现，且失败信息指出具体用例和不一致维度。

### 任务 2：统一 JavaScript 上传前规范化

- [ ] 在 `taskpane-helpers.js` 增加一个唯一的格式审查块规范化入口，以及它调用的 range、format、segment、table、image 小函数。现有 `buildDeterministicFormatReviewBody()` 先生成规范块，body/batch/第二遍都只复用该结果。
- [ ] format 规范化复用现有 WPS fact 转换函数，把 `fontSize/lineSpacing/firstLineIndent/spaceBefore/spaceAfter/leftIndent/rightIndent` 的标量与 `facts.*.normalizedValue` 对齐；保留 fact 的原始值和单位，不做数值大小猜测。
- [ ] 仅在大纲事实确实存在时同步写入顶层和 `format.outlineLevel`；空 `insufficientReason` 从段落、segment、表格 cell format 中统一删除。
- [ ] 表格递归补齐稳定的 1-based 行列、跨度、cell ID，并由规范化 cell 文本生成表格块文本；图片使用稳定字段和默认值，普通块保留 `images: []` 投影。
- [ ] `formatReviewStructureProjection()`、`formatReviewFormatProjection()`、body 和 batch 不再分别做不同默认值补齐；投影函数只读取规范块。
- [ ] 保持 ES5 兼容，不引入依赖，不改 WPS 同步扫描/写回行为。

**完成标准：** JS 单测绿；同一 JS 规范块重复规范化结果逐字节一致；第一遍批次与第二遍使用同一投影入口。

### 任务 3：收敛 Python 信任边界规范化与投影

- [ ] 在 `deterministic_format_review.py` 中让 `_normalize_format_blocks()` 成为唯一入口；将表格 rows/nestedTables、cell format 和 images 递归规范化，删除当前顶层与嵌套表格处理不一致。
- [ ] 修复 `blockType == "image"` 对 JS `images: [{...}]` 形态的处理：从已规范化 images 取得唯一图片事实并生成兼容的顶层稳定字段，不能再把整个 block 当成一条缺少 `imageId` 的图片事实解析；确保 inventory 只计一次。
- [ ] `_format_metrics()` 只接受规范块；内容前镜像跳过图片空文本，表格文本与 JS 顺序一致；structure 投影固定加入 `images`；format 投影复用同一规范化 format/cell format。
- [ ] 保留现有四项逐项精确比较。新增 Python 负向测试：只篡改 structure、只篡改 format、同时让 character/content 正确但 structure/format 之一错误，均必须返回 `DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH`，且 reviewer/provider 未调用。
- [ ] 增加规范化幂等、图片不重复计数、嵌套表格和 emoji 字符数测试；不得用“服务器接受客户端哈希”或“只校验 content”替代重算。

**完成标准：** Python focused tests 绿；四个指标由规范块唯一导出；不存在允许 structure 或 format 单独失配的分支。

### 任务 4：把跨运行时测试接入候选构建门禁

- [ ] 修改 `build_v0251_delivery_kit.sh`，运行正式插件测试时显式设置 `AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN"`，使新增 Node 测试调用构建所用的真实 Python 环境。
- [ ] 修改 `test_v0251_delivery.py`，锁定构建脚本必须包含跨运行时哈希门禁和 Python 可执行文件传递；构建不能因缺少 Python/Node 而跳过该门禁。
- [ ] 确认 `check_delivery_source_provenance.py` 的 `formal-plugin-kit/tests/*.test.js` 输入发现会覆盖新增测试；若现状不覆盖，再做最小修改并补交付源追踪测试，不能留下未跟踪门禁输入。

**完成标准：** 直接执行新测试、执行全部 Node 契约测试、执行 v0.25.1 构建脚本时，跨运行时对拍都会实际运行；日志明确输出通过，而非 skip。

### 任务 5：更新 ADR、交付说明和人工验收模板

- [ ] 新 ADR 记录固定投影、UTF-16 字符计数、规范 JSON、双运行时实现和 Adapter 独立重算的信任边界；明确拒绝“禁用哈希”“只校验 content”“删除图片/格式字段”“把 Python 返回哈希回填为客户端声明”等方案。
- [ ] `packaging/v0251-delivery.md` 增加本次缺陷、跨运行时自动门禁、旧候选拒绝和新候选边界；修正其中已过时的 `docs/v0251-candidate-status.json` 描述，说明源码位于 `packaging/`、构建后复制到归档 `docs/`。
- [ ] `packaging/v0251-target-machine-acceptance.md` 新增普通段落、标题、表格、图片元数据、insufficient、emoji 的真实 WPS 批次验收；每项同时记录 structure/format 是否匹配、是否出现 `BATCH_HASH_MISMATCH`、是否进入后台任务。图片项固定验证 `pixelExportCount=0`、`pixelUploadCount=0`。
- [ ] 暂不把任何状态写成 `passed` 或 `target-accepted`。

**完成标准：** 自动化和人工边界都有可判定结果；文档不暗示图片语义已启用或真实 WPS 已验收。

### 任务 6：完整回归、审查与源码候选冻结

按下列顺序运行，并保存真实输出。命令中的 Python 路径在麒麟环境必须使用项目虚拟环境，不能默认系统 Python。

本地 focused：

```bash
AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test \
  formal-plugin-kit/tests/format-review-hash-contract.test.js \
  formal-plugin-kit/tests/deterministic-format-review.test.js

PYTHONPATH=adapter_service python3 -m pytest -q \
  adapter_service/tests/test_deterministic_format_snapshot_protocol.py \
  adapter_service/tests/test_outline_levels.py \
  adapter_service/tests/test_v0251_delivery.py
```

麒麟 V10/Python 3.8 focused 与全量：

```bash
AI_WPS_HASH_CONTRACT_PYTHON=/mnt/ai-wps-test-venv/bin/python \
  node --test formal-plugin-kit/tests/*.test.js

PYTHONPATH=adapter_service /mnt/ai-wps-test-venv/bin/python -m pytest -q \
  adapter_service/tests/test_deterministic_format_snapshot_protocol.py \
  adapter_service/tests/test_outline_levels.py \
  adapter_service/tests/test_v0251_delivery.py

PYTHONPATH=adapter_service /mnt/ai-wps-test-venv/bin/python -m pytest -q \
  adapter_service/tests
```

静态与兼容检查：

```bash
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
python3 packaging/check_python38_compatibility.py \
  adapter_service/app packaging
bash -n packaging/build_v0251_delivery_kit.sh
git diff --check
```

- [ ] 由独立审查者检查：固定投影字段是否两端一一对应、图片/表格是否真实参与、空 reason 是否唯一处理、服务端重算是否仍在、错误码与清理/幂等语义是否未弱化。
- [ ] 在生成候选前提交全部生产代码、测试、ADR、拒绝记录和交付模板，确认 `HEAD` 是完整 40 位提交，构建输入均已跟踪且无未提交差异；用户的运行态未跟踪目录不进入提交。

**完成标准：** focused、全量、Node、Python 3.8 兼容、Shell 和 diff 检查全部通过，复审无 P0–P2；任何一项失败都不得构建候选。

### 任务 7：构建新的 `v0.25.1-alpha` 候选并验收产物

构建必须把 `ccad09f` 归档作为“上一候选”，不能继续指向 `e43dc8c`：

```bash
AI_WPS_V0250_BASELINE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260814-v0250.tar.gz \
AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-ccad09f-v0251.tar.gz \
DATE_TAG=<实际构建日期> \
PYTHON_BIN=/mnt/ai-wps-test-venv/bin/python \
PYTHON38_BIN=/mnt/ai-wps-test-venv/bin/python \
bash packaging/build_v0251_delivery_kit.sh
```

- [ ] 新归档名必须为 `ai-wps-phase1-delivery-<date>-<new-head-short-sha>-v0251.tar.gz`，不得覆盖旧归档。
- [ ] 构建日志必须包含跨运行时哈希测试、全部正式插件测试、Python 3.8 扫描、交付审计和生命周期门禁通过；生命周期终态只能是 `candidate`。
- [ ] 独立核对归档 `.sha256`、归档内 `release-manifest.json.candidateEvidence.sourceCommit/candidateBuildId/automatedResult`、归档内 `docs/v0251-candidate-status.json` 的 `ccad09f rejected` 记录，以及正式包内修复后的 JS/Python 文件。
- [ ] 在目标 WPS 使用验收模板执行六类用例。**只有 structure 和 format 两个哈希同时与 Adapter 重算值一致才算通过**；content/character 单独一致不能接受。
- [ ] 真实 WPS、模型直连和 Issue #59 未全部完成前，新构建仍仅是 `candidate`，不得标为 `target-accepted`，也不得关闭 Issue #59。

**完成标准：** 新候选拥有独立身份和可复核证据；旧 `ccad09f` 始终为 rejected；自动化与人工验收边界未混淆。

### 任务 8：用真实证据更新 README 与 handoff

候选构建和审计完成后再更新，不允许预填通过数字：

- [ ] 同步修改 `README.md` 与 `README-ZH.md`：当前候选 ID、完整/短提交、归档、SHA-256、实际测试计数、`ccad09f rejected` 原因、Issue #59 状态。英文 README 当前仍停留在 `385a251`，本次必须消除中英文状态漂移。
- [ ] 更新 `docs/codex-handoff.md`：把任务 0 的“修复中”状态替换为新候选真实证据，记录跨运行时六类覆盖、实际命令/计数、构建环境、旧候选拒绝链和剩余人工验收项。
- [ ] 更新 `packaging/v0251-delivery.md` 的候选修复摘要，但保持通用归档模板，不写不存在的结果。
- [ ] 再运行文档中的归档路径/SHA/提交交叉核对、`git diff --check` 和相关文档测试。

**完成标准：** README 中英文、handoff、状态 JSON、归档 manifest 与磁盘产物相互一致；其他会话只读 handoff 即能得到当前唯一候选和禁止使用的旧候选列表。

## 构建验收硬边界

以下任一条件成立，候选构建或发布必须停止：

- 任一用例只有 `structureSha256` 或只有 `formatSha256` 对齐；
- 跨运行时测试被 skip、调用了模拟规范化器、未使用真实 JS builder 或真实 Python service；
- 为通过测试而关闭/放宽 Adapter 哈希校验，或只比较 content/character；
- 图片元数据未进入结构指纹，或图片用例触发任何像素导出/上传；
- 表格/嵌套表格、insufficient 或 emoji 用例未覆盖；
- Python 3.8、正式 Node 契约、全量 Adapter 回归、源码 provenance、交付审计或生命周期门禁失败；
- 构建输入有未跟踪/未提交差异，归档 sourceCommit 不是完整 `HEAD`；
- 新归档覆盖旧文件，或 `ccad09f` 未在交付状态中标为 rejected；
- README/handoff 使用推测的测试计数、SHA 或人工验收结论。

## 关键风险与应对

1. **潜在差异多于当前三项。** 使用真实 builder→Adapter 对拍覆盖单位、range、表格默认值、嵌套结构和图片空文本，禁止只修表面字段。
2. **测试自身形成第三套契约。** 测试只组织夹具并调用生产函数；固定规则写入 ADR，预期哈希只作为防漂移黄金值，不在测试内实现替代规范化器。
3. **Node 子进程选错 Python。** 构建门禁显式传入 `$PYTHON_BIN`；麒麟 focused 测试显式使用 `/mnt/ai-wps-test-venv/bin/python`。
4. **图片块兼容修复误启用图片语义。** 只处理文本元数据和结构哈希，保持 runtime master switch 关闭及像素计数为零。
5. **同版本候选混淆。** 依赖 date + 完整 sourceCommit + archive SHA 区分；所有旧候选只追加 rejected 记录，不修改历史证据。
6. **文档状态漂移。** `AGENTS.md` 已强制新会话先读 handoff；实施先写阻断状态，完成后用真实构建证据替换，并同步中英文 README。

## 最终完成定义

- 六类跨运行时回归在本地和麒麟 Python 3.8 环境全部通过；
- JS 与 Python 对每个用例/批次的四项指标逐项相等；
- 结构或格式单独篡改均被 Adapter 拒绝，且没有模型调用；
- 全量测试、静态检查、provenance、审计、生命周期门禁全部通过；
- 新 `v0.25.1-alpha` 候选有独立提交、构建 ID、归档和 SHA-256；
- `ccad09f` 及更早候选全部保持 rejected；
- README、README-ZH、handoff、交付说明、验收模板和归档 manifest 一致；
- Issue #59 未完成人工验收前只宣称 `candidate`。
