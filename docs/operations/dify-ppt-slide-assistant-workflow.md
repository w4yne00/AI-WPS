# PPT“智能总结”Dify 工作流配置

## 接口与任务

- 用户可见名称：智能总结
- 内部任务键：`ppt.slide_assistant`
- 模型接口：Dify `/chat-messages`
- 本地文件入口：`POST /ppt/document-files`
- 后台任务：`POST /ppt/slide-assistant/jobs`
- 状态查询：`GET /ppt/slide-assistant/jobs/{jobId}`
- provider 等待预算：1800 秒
- 提示词模板：`docs/prompt-templates/ppt-smart-summary-prompt-template.md`

在 PPT 任务窗格设置页创建具名工作流档案并保存对应 API Key。当前页总结和文档总结共用同一个 `ppt.slide_assistant` 档案；切换档案只影响下一次新任务，不改变已经提交的后台任务。

## 双模式输入

### 当前页总结

无文件时，adapter 将当前页主标题、可选副标题、普通文本形状、前一页标题、后一页标题和用户补充要求写入 `userinput.query`。动态输入总预算为 4600 字符：主标题 200、副标题与正文合计 3000、相邻页标题各 200、补充要求 1000；单个正文文本形状最多 1000 字符。

正文达到 20 个非空白字符时使用 `optimize`，不足时使用 `generate`。主标题和副标题不参与阈值计算；生成模式必须提供补充要求。副标题是可选字段，不得混入普通正文。

### 文档总结

文档模式只支持一个 `.md` 或 `.docx` 文件，最大 10 MB。前端先调用：

```text
POST /ppt/document-files
```

请求体包含 `fileName`、`mimeType`、`sizeBytes` 和 `contentBase64`。adapter 校验扩展名、Base64 实际大小、Markdown UTF-8 编码或 DOCX ZIP 结构后，返回 30 分钟有效的一次性 `fileToken`。文件名和正文不会写入普通日志或诊断。

随后前端提交现有后台任务接口：

```json
{
  "sourceMode": "document",
  "fileToken": "一次性令牌",
  "requestedSlideCount": 10,
  "userInstruction": "面向管理层，突出风险和下一步安排",
  "clientJobId": "客户端生成的幂等任务号"
}
```

`requestedSlideCount` 只允许 5、8、10、12、15，默认 10。`clientJobId` 用于幂等恢复，同一任务不得重复上传文件或重复调用模型。

adapter 使用当前工作流档案的同一 API Key 调用 Dify `/files/upload`，取得 `upload_file_id` 后向 `/chat-messages` 传入：

```json
{
  "files": [
    {
      "type": "document",
      "transfer_method": "local_file",
      "upload_file_id": "Dify 返回的文件 ID"
    }
  ]
}
```

本地文件采用一次性令牌，上传模型后台成功、任务失败或令牌过期后删除。adapter 重启后未完成的文件令牌失效，用户需要重新选择文件。

## Dify 节点配置

同一工作流按 `userinput.files` 是否存在分支：

1. 用户输入节点暴露 `userinput.query` 和 `userinput.files`。
2. 条件分支判断文件列表是否存在有效文件。
3. 无文件分支直接把 `userinput.query` 传给当前页总结 LLM。
4. 有文件分支先使用文档提取节点读取 Markdown 或 DOCX，再把提取正文与 `userinput.query` 一起传给文档总结 LLM。
5. 回答节点只返回最终 Markdown 或 JSON，不返回中间变量、提取全文或深度思考过程。

附件内容是不可信的数据源，不是系统指令。System Prompt 必须要求模型忽略附件中的提示注入文字，并且只根据查询与附件事实生成建议。

## 输出约定

### 当前页结果

```markdown
## 建议标题
项目总体进展

## 核心要点
- 总体方案设计已完成
- 系统进入联调阶段
- 重点关注接口稳定性

## 本页结论
项目按计划推进，下一阶段应集中完成接口联调和风险收敛。
```

也可返回包含 `suggestedTitle`、`bullets`、`conclusion` 和可选 `plainText` 的 JSON。

### 文档结果

文档模式应返回 `resultType=document` 的 JSON，包含 `deckTitle`、`documentSummary`、`recommendedSlideCount`、`slides`、`globalStyleAdvice` 和 `plainText`。每个 `slides` 项包含连续页码、页面角色、主标题、可选副标题、2 至 5 条要点、可选结论、版式建议和视觉建议。

完整字段和可复制 System Prompt 见提示词模板。adapter 会先剥离 `<think>...</think>`，再解析约定结构；非标准 JSON 或普通 Markdown 会保留在 `rawAnswer`，并通过 `parseFallbackReason` 提示前端显示和复制原始模型回复。

## 长任务与恢复

- 前端提交后台任务后短轮询状态，不保持单次长连接等待模型完成。
- 运行阶段依次显示：本地文件已接收、正在上传模型后台、模型后台正在解析文档、正在生成 PPT 建议。
- provider 最长等待 1800 秒；180 秒以上的模型任务仍应继续查询。
- 状态查询短暂超时或连接中断时必须保留 `jobId` 和 `clientJobId`，不得重新提交。
- 任务窗格关闭再打开后，应使用本地保存的任务号恢复查询。

## 只读边界

智能总结只读取当前页内容或用户主动选择的文档，只提供结果预览、纯文本和复制操作。不得自动创建页面，不得修改幻灯片文字、形状、版式、主题、图表、动画或备注，也不得声称已经完成这些操作。

## 故障排查

- 文件类型或大小错误：确认扩展名为 `.md`/`.docx` 且不超过 10 MB。
- DOCX 格式错误：确认文件是真实、未损坏的 DOCX，而不是仅修改扩展名。
- 文件令牌过期：重新选择文件并提交，不要复用旧令牌。
- Dify 文件上传失败：检查当前 `ppt.slide_assistant` 档案的密钥权限和文件上传能力。
- 模型收到文件但无正文：检查 `userinput.files`、条件分支和文档提取节点连线。
- 返回无法结构化：查看前端原始回复和 `parseFallbackReason`，确认回答节点只返回最终输出。
- 长任务前端失联：重新打开任务窗格恢复任务号，不要重复点击提交。
