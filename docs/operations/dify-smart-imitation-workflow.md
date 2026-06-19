# 智能仿写 Dify 工作流配置

适用任务：`word.smart_imitation`

适用版本：`v0.14.0-alpha` 及以上

推荐任务级 API Key 引用：`word_smart_imitation`

## 输入约定

adapter 会把完整提示词放入 Dify `/chat-messages` 的顶层 `query` 和 `inputs.query`。Dify 工作流应直接把 `query` 传给 LLM 节点。

提示词内已包含：

- 仿写模板：来自用户在 Word 中框选的文本，或任务窗格手动粘贴的模板。
- 仿写需求：用户填写的专业方向、用途、对象和语气要求。
- 参考素材：用户选填的事实背景、参数、问题清单或项目材料。

## 输出约定

只输出仿写后的正文，不输出解释、分析过程、处理说明、JSON 包裹或前端状态。

如果模型开启 think 模式，adapter 会在结果预览前剥离 `<think>...</think>` 内容；Dify 最终回复仍应把可展示正文放在最终输出中。

## 建议模型参数

建议温度在 `0.3` 到 `0.5` 之间。

- 需要严格贴近模板句式、段落数量和参考素材时，建议使用 `0.3`。
- 需要稍强表达变化、但仍保持文风稳定时，建议使用 `0.5`。

## 前台行为

智能仿写与智能编写并列展示，但首版只复用智能编写的预览、纯文本和复制能力。

- 不提供对照视图。
- 不提供应用预览。
- 不写回 Word 正文。
- 不改变智能编写、文档审查、格式审查的既有链路。

## 排查

在 WPS 设置页查看“最近一次任务诊断”，重点确认：

- `taskType=word.smart_imitation`
- `taskAuthSource=task-file` 或按现场配置回退到统一密钥
- 任务级 API Key 命中 `word_smart_imitation`
- provider URL 带 `/v1`，聊天路径为 `/chat-messages`

如果 WPS 提示未配置模型接口，先在设置页保存统一 API URL，再保存“智能仿写”的任务级 API Key。
