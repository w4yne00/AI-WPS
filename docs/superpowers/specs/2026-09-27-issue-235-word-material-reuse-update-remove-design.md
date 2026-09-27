# Word：资料跨次复用、更新与移除设计规格 (Issue #235)

- 日期：2026-09-27
- 状态：已确认，待实施
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#235、#229（Parent）、#233（Prerequisite）、#234（Prerequisite）
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Issue #233 中，系统实现了单文档会话内多份（最多 5 份）、累计最多 100,000 字 DOCX 资料的目录汇总与章节生成；在 Issue #234 中，实现了补充事实与写作要求的严格解耦、资料事实冲突显式呈现与人工选项裁决、以及逐段出处核对和无依据内容标记。

然而，在当前的实现中：
1. **资料目录未持久化**：资料与大纲仅维护在 Adapter 内存中，关闭 WPS 窗格或重启 Adapter 后，用户导入的资料会丢失，必须重新上传；
2. **缺乏主动更新与替换机制**：当参考资料修订时，用户无法主动替换旧资料并重新计算限额，更无法感知已有草稿与新资料之间的时序依据关系；
3. **缺乏资料移除与清理**：用户无法从会话中移除无用资料以释放 5 份或 10 万字限额；
4. **多文档串用与未保存/另存为风险**：未保存的新建文档（如“文档1”）或另存为新文件的文档，若缺乏严密的身份追踪与隔离，极易出现不同文档串用资料集的安全隐患；
5. **运行中并发竞态**：若在生成草稿期间并发执行更新或移除，可能导致正在运行的任务崩溃、抽取内容错乱或伪报结果有效。

本规格依据 Issue #235 验收标准，为 Word 任务窗格及 Adapter 建立完整的“资料跨次复用、更新、移除、依据状态追踪及并发互斥”架构与实施规范。

---

## 2. 存储架构与文档身份生命周期

### 2.1 独立持久化存储目录架构

在 Adapter 的状态存储根目录（由 `AI_WPS_STATE_DIR` 或 `resolve_runtime_paths().state_dir` 决定）下，设立专用的 `word_materials` 子目录：

```text
$AI_WPS_STATE_DIR/word_materials/
└── <document_identity_hash>/
    ├── manifest.json                  # 资料清单与统计元数据
    ├── catalog_cache.json             # 抽取后的层级大纲、段落块与引用片段字典
    └── files/                         # 经过安全检验的原始 DOCX 文件副本
        ├── mat_01a2b3c4.docx
        └── mat_5d6e7f8a.docx
```

- **脱敏与隔离保证**：资料仓储完全物理独立于通用任务历史（`TaskHistoryStore`），不向历史写入任何资料明文，严格遵循脱敏规范；
- **安全副本**：`files/` 目录下仅保存通过 `validate_docx_bytes` 校验的合法 DOCX 二进制副本，文件名采用 `materialId.docx` 格式，杜绝路径遍历攻击；
- **清单元数据（`manifest.json`）**：
  ```json
  {
    "documentIdentity": "full:/Users/wayne/docs/方案.docx",
    "documentSessionId": "doc_session_v2_12345678",
    "totalDocuments": 2,
    "totalCharacters": 45000,
    "totalTableCells": 320,
    "updatedAt": "2026-09-27T10:20:00Z",
    "documents": [
      {
        "materialId": "mat_01a2b3c4",
        "fileName": "立项需求.docx",
        "readableCharacterCount": 25000,
        "blocksCount": 42,
        "fragmentsCount": 88,
        "tableCellsCount": 160,
        "importedAt": "2026-09-27T10:15:00Z",
        "updatedAt": "2026-09-27T10:15:00Z",
        "fileSha256": "..."
      }
    ]
  }
  ```

### 2.2 文档身份判定与多文档隔离

为彻底杜绝不同文档间串用参考资料，系统定义双重身份标识：
1. **已保存文档（Saved Document）**：
   - 读取 `document.FullName`（或规范化后的绝对路径）；
   - 前缀加 `full:`，计算 SHA-256 派生哈希（8-16 字符）作为目录名；
   - 只要文档在同一路径打开，重开窗格或重启 Adapter 均能准确识别并加载对应资料。
2. **未保存文档（Unsaved Document，如“文档1”）**：
   - `document.FullName` 为空，仅有临时名称（如 `文档1`）；
   - 前缀加 `name:`，结合窗格首次分配的 `documentSessionId`（如 `session_doc_session_uuid`）作为目录名；
   - 保证不同新建文档之间物理隔离，互不串用。

### 2.3 另存为与首次保存无感迁移（`bind-document`）

当未保存文档首次保存到磁盘，或已保存文档执行“另存为”获得新路径时：
1. 插件在轮询或事件响应中检测到活动文档的 `FullName` 发生变更，但所属编辑窗口与会话连续；
2. 插件向 Adapter 发起原子绑定请求：
   - `POST /word/materials/bind-document`
   - 载荷：
     ```json
     {
       "oldDocumentSessionId": "doc_session_old",
       "newDocumentSessionId": "doc_session_new",
       "newDocumentIdentity": "full:/Users/wayne/docs/新方案.docx"
     }
     ```
3. Adapter 在锁保护下：
   - 校验 `oldDocumentSessionId` 对应的资料目录是否存在；
   - 计算新身份的目录路径；若新路径尚无资料，将旧临时目录安全迁移（重命名或复制副本）至新目录，更新 `manifest.json` 中的 `documentIdentity` 与 `documentSessionId`；
   - 原临时会话目录安全销毁，返回迁移后的目录摘要；
   - 若新路径已存在资料集，则返回 409 拒绝静默覆盖，要求用户显式确认。

---

## 3. 主动更新、移除管理与容量门禁

### 3.1 主动更新/替换资料（`PUT /word/materials/{material_id}`）

用户在任务窗格的资料目录列表中，点击某份资料的“更新”按钮，选择新版 DOCX 文件发起替换。

1. **接口规范**：
   - `PUT /word/materials/{material_id}`
   - 载荷：`{ "fileName": "...", "contentBase64": "...", "documentSessionId": "..." }`
   - 请求体总大小门禁：常规接口沿用 64 KiB 上限；上传文件接口通过安全流式/Base64 解码，最大支持 20 MiB DOCX 包（`DOCX_MAX_PACKAGE_BYTES`）。
2. **非自动跟随原则**：
   - 系统严禁后台轮询监听本地磁盘文件；只有用户显式点击更新并提交时才执行替换。
3. **Fail-Closed 容量重算门禁**：
   - 预计算新文件的可读字符数 `new_chars` 与单元格数 `new_cells`；
   - 计算更新后总字数：`totalCharacters - old_doc.readableCharacterCount + new_chars`；
   - 若更新后字数超过 100,000 字上限，抛出 HTTP 413 `MATERIAL_TEXT_OVER_LIMIT`，**原资料副本与目录保持完全不变**；
   - 若单元格数超限，抛出 HTTP 413 `MATERIAL_TABLE_OVER_LIMIT`，原资料保持不变。
4. **原子落盘与目录重建**：
   - 覆写 `files/{material_id}.docx`；
   - 保持 `materialId` 不变，重新解析 blocks、fragments 与 heading 目录项；
   - 刷新 `manifest.json`，设置 `updatedAt = 当前 ISO 时间戳`；
   - 原子刷新 `catalog_cache.json`，返回更新后的资料视图与 `catalogSummary`。

### 3.2 资料移除与物理清理（`DELETE /word/materials/{material_id}`）

用户在资料目录列表中，点击某份资料的“移除”按钮，经确认后发起删除。

1. **接口规范**：
   - `DELETE /word/materials/{material_id}?documentSessionId=...`
2. **物理清理与配额释放**：
   - 从磁盘彻底删除 `files/{material_id}.docx`；
   - 从 `manifest.json` 中移除该资料条目，相应扣减 `totalCharacters`、`totalTableCells` 与 `totalDocuments`；
   - 从 `catalog_cache.json` 中清理属于该 `materialId` 的所有 blocks、fragments 以及 TOC 目录项；
   - 释放已占用的文件份数与字符配额，允许用户后续导入新资料；
   - 若资料不存在或不属于当前会话，返回 HTTP 404 `MATERIAL_NOT_FOUND`。

---

## 4. 运行中并发互斥与取消安全

### 4.1 运行中互斥门禁（`MATERIAL_COMPOSER_BUSY`）

为防止在模型推理或原文提取期间资料集发生变更导致数据不一致或崩溃，建立严格的前置互斥保护：

1. **前端窗格状态互斥**：
   - 当任务处于 `queued` 或 `running` 阶段时（`state.busy = true`），窗格内所有的“添加资料”文件选择框、“更新”按钮、“移除”按钮统一设置为 `disabled = true`；
   - 悬浮提示“生成任务进行中，不可修改参考资料”。
2. **后端接口互斥防御**：
   - 当 `LongTaskCoordinator` 中属于该 `documentSessionId` 的 `word.material_composer` 任务处于活跃态（`queued` / `running`）时：
   - 任何针对该会话的 `POST /word/materials`、`PUT /word/materials/{material_id}`、`DELETE /word/materials/{material_id}` 请求，立即拦截并返回 **HTTP 409 `MATERIAL_COMPOSER_BUSY`**；
   - 错误信息：“章节草稿正在生成中，请等待完成或取消任务后再更新/移除资料。”

### 4.2 取消与异常收敛

1. 用户点击“取消任务”时，后端将长任务标记为 `cancelled` 并切断上游连接，释放任务槽位；
2. 窗格接收到取消确认后，`busy` 状态解除，“更新”与“移除”按钮立即恢复可用；
3. 取消后的残缺草稿绝不作为有效依据，后续操作可安全修改资料。

### 4.3 双运行时接口对等性

FastAPI 路由（`app/api/word.py`）与 Standalone Adapter（`standalone_adapter.py`）均完整对等实现：
- `PUT /word/materials/{material_id}`
- `DELETE /word/materials/{material_id}`
- `POST /word/materials/bind-document`

两套运行时共享相同的底层服务 `WordMaterialImportService` 与 `WordMaterialStore`，错误码、状态码及 JSON 结构保持绝对一致。

---

## 5. 依据状态追踪与写入安全熔断

### 5.1 草稿依据快照（`basisMaterials`）

生成任务成功完成时，草稿结果对象（`result`）中固化当时所采纳的资料版本快照：

```json
{
  "taskType": "word.material_composer",
  "documentSessionId": "doc_session_1",
  "generatedAt": "2026-09-27T10:24:00Z",
  "basisMaterials": [
    {
      "materialId": "mat_01",
      "fileName": "招标文件.docx",
      "updatedAt": "2026-09-27T10:15:00Z"
    }
  ],
  "plainText": "...",
  "paragraphs": [...]
}
```

### 5.2 动态依据状态判定矩阵

前端窗格在每次渲染、更新资料、移除资料或重开恢复时，动态核对草稿的 `basisMaterials` 与当前会话目录 `catalogSummary.documents`：

| 条件 | 状态码 (`basisStatus`) | 界面警示标签 | 写入选区/光标权限 | 复制正文权限 |
| :--- | :--- | :--- | :--- | :--- |
| `basisMaterials` 中至少一份资料不在当前目录中 | `removed` | `⚠️ 所引参考资料已被移除，当前草稿依据已失效` | **禁用（Pause）** | 允许（Enabled） |
| 资料均在，但至少一份资料的当前 `updatedAt > generatedAt` | `updated` | `⚠️ 参考资料已更新，当前草稿依据已变更，请重新生成` | **禁用（Pause）** | 允许（Enabled） |
| 所有资料均在且未被更新 | `current` | 无警示 | 允许（正常激活） | 允许（Enabled） |

### 5.3 写入安全熔断实现

1. **按钮状态联动**：
   - 当 `basisStatus === "removed"` 或 `basisStatus === "updated"` 时：
   - “确认写入选区 / 在光标处插入”按钮（`btn-material-apply`）处于 `disabled = true`；
   - 按钮标题或状态行明确提示：“资料依据已变更，请重新生成草稿后再写入。”
2. **逻辑兜底防御**：
   - 若通过任何非法途径调用 `applyMaterialComposerResult()`，首行检查 `basisStatus`；
   - 若不为 `current`，抛出 `Error("草稿所依据的资料已变更或移除，已暂停写入。请重新生成。")`；
3. **只读资产安全保留**：
   - 正文与逐段出处、待补充项、待核对事实卡片保持正常渲染，不静默清空；
   - “复制正文”按钮（`btn-material-copy`）始终保持可用，支持用户手动选复制用。

---

## 6. 前端任务窗格交互规范

### 6.1 资料目录卡片交互

在折叠的 `<details class="material-composer-toc">` 中，每份资料渲染为独立区块：
- 文件名、字数、导入/更新时间；
- 操作按钮栏：
  - `[更新]`：点击触发隐藏的文件 `<input type="file" accept=".docx" />`；选中文件后调用 `PUT` 接口，展示“正在更新资料...”；
  - `[移除]`：点击弹出浏览器确认框“确定移除该参考资料吗？已生成的草稿依据将失效。”；确认后调用 `DELETE` 接口并刷新目录。
- 目录中的章节标题按钮：依然支持点击自动填入“目标章节”文本框。

### 6.2 窗格重开与恢复流程（`restore()`）

1. 用户切回模式或重新打开 WPS 侧边栏；
2. 窗格调用 `GET /word/materials/catalog?documentSessionId=...`；
3. 取得持久化的资料目录后，更新总份数、总字数提示与目录折叠树；
4. 若本地存在历史未写回的草稿，比对目录评估其 `basisStatus`；
5. 若资料已更新或移除，草稿顶部呈现对应警示条，写入按钮自动熔断禁用。

---

## 7. 测试验证与质量门禁

遵循 `/test-driven-development`（红-绿-重构）与项目质量门禁，设计以下分层测试矩阵：

### 7.1 后端测试（Python 3.8 / Pytest）
1. `test_word_material_store.py`（或在 `test_word_material_import.py` 中扩展）：
   - **持久化与重启恢复**：创建新服务实例指向同一 `state_dir`，验证目录与抽取内容完整恢复；
   - **磁盘副本真实性**：验证 `files/` 存在实际 `.docx` 文件，且与上传内容哈希一致；
   - **多文档隔离**：`docA` 与 `docB` 资料互不泄露；
   - **另存为迁移**：`bind-document` 将未保存目录安全迁移至新路径目录；
   - **主动更新**：`PUT` 替换文件、字符数动态扣减与增加、10 万字超限拦截、`updatedAt` 刷新；
   - **主动移除**：`DELETE` 清理磁盘副本与片段缓存、释放配额、404 处理；
   - **并发互斥**：任务运行期间发起更新与移除，断言返回 409 `MATERIAL_COMPOSER_BUSY`；
   - **脱敏独立性**：断言 `TaskHistoryStore` 中零资料历史记录。
2. 双运行时路由对等测试（FastAPI & Standalone）：
   - `PUT /word/materials/{id}`
   - `DELETE /word/materials/{id}`
   - `POST /word/materials/bind-document`

### 7.2 前端正式插件契约测试（Node.js / Vitest）
1. `formal-plugin-kit/tests/word-material-composer.test.js` & `word-material-pane.test.js`：
   - 验证草稿在资料被更新后标记为 `updated`，展示警示条，禁用写入按钮；
   - 验证草稿在资料被移除后标记为 `removed`，展示警示条，禁用写入按钮；
   - 验证依据异常时“复制正文”依然可用；
   - 验证运行中“更新”和“移除”按钮置灰；
   - 验证重开窗格后通过 `catalog` 接口无损恢复已导入的资料目录；
   - 验证多文档切换时资料目录与草稿隔离。

### 7.3 交付规范与代码门禁
1. `python -m compileall adapter_service/` Python 3.8 兼容性扫描；
2. `git diff --check` 检查无格式告警与行尾空格；
3. 全量测试回归（后端 1590+ 测试通过，正式插件 350+ 测试通过）。
