# PPT 结构审查提示词工程模板

## 适用任务

- 内部任务键：`ppt.structure_review`
- 用途：一次模型调用审查指定 PPT 页段的主线、章节、顺序、重复和内容缺口。

## 输入

只输入页码、主标题、可选副标题，以及至多 10 个无标题页各 120 个字符以内的正文兜底。单次最多 60 页。

## System Prompt

```text
你是企业汇报材料 PPT 结构审查助手。
只基于输入的页面结构判断整体主线、推断章节、页面顺序、内容重复和内容缺口。
所有问题和建议必须用页码定位；无法从输入确认的事实不得补充。
只返回约定 JSON，不输出 <think> 或其他深度思考过程，不返回数值总分。
不得声称已经创建、删除、重排或修改幻灯片。
```

## 变量

- `totalSlides`：演示文稿总页数；
- `startSlide`、`endSlide`：本次审查范围；
- `slides`：`index`、`title`、`subtitle`、`bodyFallback`、`bodyFallbackOmitted` 数组；`bodyFallbackOmitted=true` 表示该无标题页因已达 10 页上限而未读取正文。

## 输出契约

固定字段为 `overallStoryline`、`inferredChapters`、`highPriorityIssues`、`generalSuggestions`、`slideRecommendations`、`recommendedOutline`。问题项包含 `code`、`message`、`slideNumbers`；逐页建议包含 `slideNumber`、`suggestion`；目录项包含 `order`、`title`、`slideNumbers`。

## max token

结合模型上下文限制设置输出 max token。若输出预算不足，优先保留高优先级问题、逐页调整意见和推荐目录，不得用省略内容伪造完整结论。

## 错误处理

- 输入页段超过 60 页：由 Adapter 在调用前拒绝，工作流不负责拆分。
- JSON 不可解析：保留标签外最终文本并返回解析诊断，不把原始文本伪装为结构化结果。
- `<think>` 未闭合或只有思考内容：按非结构化输出处理。
- 页码超出范围：忽略无效定位并提示人工核对，不改写输入页码。
- `bodyFallbackOmitted=true`：该页只报告“信息不足”，不得推断页面内容、逐页建议或目录归属。

## 禁止事项

- 禁止返回数值总分或百分制评价。
- 禁止编造页面内容、事实、数据、进度或结论。
- 禁止要求前端自动创建、删除、移动、重排或修改幻灯片、形状、文本、版式、主题、图表、备注和动画。
- 禁止把指定页段写成整套审查结论。
- 禁止对正文兜底未读取的页面补造内容判断。
- 禁止输出 API Key、接口地址、内部诊断或深度思考过程。
