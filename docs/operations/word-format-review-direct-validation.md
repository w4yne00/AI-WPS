# Word 格式审查直连验证

格式审查使用共享直连服务，任务标识为 `word.format_review`。设置页先选择服务、模型和任务参数，再执行“验证调用”。验证仅发送合成格式语义候选，不发送用户文档；它会真实调用所选模型并产生相应费用。可以先验证未保存草稿，再“保存并设为当前”。

验证成功只适用于被验证的服务 ID、完整服务端点、API Key、有效模型、温度、最大输出 Token、上下文容量和图片模式。修改这些字段后需要重新验证。只改变服务名称不影响验证。任务验证失败会撤销相同身份的旧成功；验证期间服务配置发生变化返回 `DIRECT_SERVICE_CONFIG_CHANGED`（409）。验证其他草稿不会把当前选择标记为已验证。

未通过格式语义验证时，格式审查仍可执行确定性规则，报告降级原因 `format_semantic_protocol_not_ready`。模型目录不可用或模型已被移除等配置错误仍沿用现有配置检查。

## 图片授权与视觉验证

1. 将图片输入模式设为 `openai_image_url`，保存并设为当前。
2. 点击“授权图片外发”，核对确认框中的服务地址、模型及任务范围。授权只适用于当前格式审查任务配置。
3. 点击“验证视觉能力”。Adapter 生成不含用户内容的随机八色排列 PNG，发送到所选模型并核对识别结果。仅接受正确结果；失败后图片语义保持关闭。
4. 如需停止图片外发，点击“撤销授权”或将图片输入模式设为 `disabled` 后保存。

服务地址、Key、模型或相关任务参数变化后，旧图片授权及视觉验证失效。再次保存不会自动重新授权。无有效图片授权或视觉验证时，任务保留确定性/文字证据降级路径。图片验证通过不代表格式语义协议也已验证，两项验证分别记录。

## 公开接口

FastAPI 与 standalone 提供相同路径：

| 方法与路径 | 请求 | 行为 |
| --- | --- | --- |
| `POST /provider/task-model-selections/word.format_review/validate` | 任务选择草稿；省略时读取已保存选择 | 验证格式语义协议；草稿可在首次保存前验证 |
| `POST /provider/task-model-selections/word.format_review/image-authorization` | `authorized` 布尔值，可附 `expectedSelection` 和 `expectedServiceRevision` | 授权或撤销当前已保存选择；附带选择或服务版本与当前不一致时返回 409；任务窗格会携带两者 |
| `POST /provider/task-model-selections/word.format_review/validate-image` | 空对象 | 发送合成图片并验证识别结果；未授权返回 409，识别失败返回 502 |

图片接口返回 `data.taskModelSelection`，其中 `imageSemanticReadiness.code` 为 `disabled`、`authorization_required`、`validation_required` 或 `ready`。格式语义状态通过任务选择中的 `formatSemanticReadiness.code` 读取。

验证期间切换选择、轮换 Key 或撤销图片授权，不能把原请求的结果写到新配置。视觉验证失败会撤销旧视觉验证成功状态，但不会替用户撤销已明确授予的外发授权。
