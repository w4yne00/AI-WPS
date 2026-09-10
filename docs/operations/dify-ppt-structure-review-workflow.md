# PPT“结构审查”Dify 工作流配置手册

适用任务：`ppt.structure_review`

## 1. 能力边界

结构审查读取用户指定页段内的页码、主标题和可选副标题。仅当页面没有主标题时，前端可补充最多 120 个正文字符；单次最多尝试补充 10 页，前 10 页即使正文为空也计入预算。超过预算的无标题页不再读取正文，只标记信息不足。一个请求最多包含 60 页，超过上限时必须由用户明确选择起止页，不静默截断，也不拆分为多次模型调用。

结果包含整体主线、推断章节、高优先级问题、一般建议、逐页调整意见和推荐目录。插件只提供预览和复制，不创建、删除、重排或修改幻灯片。

## 2. 独立工作流档案

在 PPT 设置页切换到“结构审查”，新建具名工作流档案并保存独立 API Key。该档案只对应 `ppt.structure_review`，不与 `ppt.slide_assistant` 共用。档案切换只影响下一次新任务；已提交任务使用提交时冻结的认证快照。

## 3. 输入与会话上下文

Adapter 继续调用 Dify `/chat-messages`。顶层 `query` 始终携带完整提示词；兼容模式下分别使用 `inputs.query` 或 `inputs: {}`。输入只包含本次审查范围和已提取的页面结构，不上传 PPT 文件。

任务请求参数与上下文：

- `host`：固定为 `wpp`；
- `documentSessionId`：当前演示文稿的内存/文档会话标识（脱敏处理，不包含本地文件绝对路径）；若省略则由 Adapter 按演示文稿标识或默认值自动派生；
- `documentDisplayName`：当前演示文稿显示名称（如 `方案汇报.pptx`），用于历史记录呈现；
- `clientJobId`：客户端幂等任务号，同一文档重试复用，跨文档或参数不一致复用将触发冲突拒绝；
- `startSlide`、`endSlide`、`totalSlides`：审查范围和演示文稿总页数；
- `slides[].index`：页码；
- `slides[].title`：主标题；
- `slides[].subtitle`：可选副标题；
- `slides[].bodyFallback`：仅无标题页可用的有限正文兜底；
- `slides[].bodyFallbackOmitted`：超过 10 页兜底预算时为 `true`；模型只能报告该页信息不足。

### 并发与槽位保护（HTTP 409）

- **文档槽位互斥**：单个演示文稿会话同一时间只允许一个正在排队或执行中的结构审查任务。若同一 `documentSessionId` 已有活跃任务，提交新任务将返回 HTTP 409，错误码 `PPT_STRUCTURE_REVIEW_DOCUMENT_TASK_BUSY`。
- **任务号冲突检测**：若客户端使用相同的 `clientJobId` 提交，但其关联的 `documentSessionId`、宿主或请求内容指纹不一致，Adapter 判定为冲突并返回 HTTP 409，错误码 `PPT_STRUCTURE_REVIEW_TASK_CONFLICT`。

## 4. 输出与历史归档契约

模型只返回 JSON 对象：

```json
{
  "overallStoryline": "整体主线说明",
  "inferredChapters": [
    {"title": "章节名称", "startSlide": 1, "endSlide": 5}
  ],
  "highPriorityIssues": [
    {"code": "content_gap", "message": "问题说明", "slideNumbers": [2, 3]}
  ],
  "generalSuggestions": [],
  "slideRecommendations": [
    {"slideNumber": 3, "suggestion": "逐页调整意见"}
  ],
  "recommendedOutline": [
    {"order": 1, "title": "推荐目录项", "slideNumbers": [1]}
  ]
}
```

不得返回数值总分。`slideNumbers` 和 `slideNumber` 应位于本次审查范围内。Adapter 将模型结果与空标题、完全重复标题、过长标题和明显编号跳号等本地检查合并，并按页码和问题语义去重；正文兜底未读取的页面会移除模型内容推断、逐页建议和目录定位，只保留本地“信息不足”反馈。结果始终显示“本次审查第 X–Y 页”，指定页段不声称覆盖整套演示文稿。

### 历史归档契约与脱敏

遵循 ADR-0131，结构审查任务完成后写入本地历史记录时必须进行轻量化与安全脱敏：

- **归档保留字段**：仅保留任务摘要元数据、审查范围、审查结论、整体主线、问题计数统计、`reportId` 和报告过期时间 `reportExpiresAt`；
- **剔除详尽数据**：历史条目剔除完整的 `highPriorityIssues`、`slideRecommendations`、`slides` 结构快照及 `pageRoles` 等冗长细节，避免历史存储膨胀；前端查看详情时按需通过 `reportId` 调取完整报告；
- **5 MiB 容灾保护**：若任务结果单条序列化体积超过 5 MiB，跳过历史记录写入，并在任务结果中附带 `historyNotice: "任务结果超过 5 MiB，未写入历史记录。"` 提示用户。

## 5. 超时、错误与诊断

- provider 等待预算为 1800 秒；前端通过共享长任务队列轮询状态。
- 输出包含 `<think>...</think>` 时，Adapter 仅解析标签外的最终结果。
- 非结构化输出保留脱敏后的最终文本和解析诊断，不伪造结构化问题。
- 队列已满、页码不是正整数、范围倒置、页码越界、超过 60 页、幻灯片读取失败或 Adapter 重启中断时，向用户显示对应中文错误，不自动改用其他工作流。
- 高级诊断不得记录 API Key、完整页面结构文本或模型原始异常正文。

## 6. 验收要点

- 分别切换两个 `ppt.structure_review` 档案，确认新任务命中提交时选择的档案。
- 使用 61 页演示文稿发起整套审查，确认请求在模型调用前被拒绝；再选择不超过 60 页的明确页段并成功提交。
- 核对主标题和副标题保持分离；有标题页不读取正文，无标题页正文兜底不超过 120 字符且最多尝试 10 页，第 11 页正文不被读取并只显示信息不足。
- 核对结构化与非结构化降级结果均显示“本次审查第 X–Y 页”，分段审查不显示整套审查结论。
- 核对模型只调用一次，结果不显示数值总分，并可分别复制审查结论和推荐目录。
- 审查前后记录幻灯片数量、顺序、标题和副标题摘要，确认未发生创建、删除、重排或修改。
