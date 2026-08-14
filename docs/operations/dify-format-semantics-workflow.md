# Word 格式语义 Dify 工作流

`word.format_review` 的工作流平台接入使用 `format_semantics.v1` 协议。工作流必须把以下固定字段作为输入：

- `contract_version`：固定为 `format_semantics.v1`。
- `operation`：只能是 `classify_role`、`associate_caption`、`suggest_table_caption` 或 `suggest_figure_caption`。
- `candidate_json`：adapter 提交的候选范围、证据和快照绑定；这是唯一事实来源。
- `image_files`：仅 `suggest_figure_caption` 使用，最多四个图像文件。

adapter 只读取 `data.outputs.result_json`，并按当前操作的完整 Schema 校验。自由文本、聊天历史、其他输出变量和不在候选范围内的对象都不能作为结果来源。

模型配置保存、升级或服务地址、调用方式、模型参数、API Key 等相关字段变化后，格式工作流必须用无敏感合成数据依次验证四类操作。验证未通过或验证记录已过期时，已保存的地址和 Key 不会被清除，格式审查只执行确定性规则，并在摘要中披露语义协议未就绪。

`packaging/reference-workflows/format-semantics-text-v1.yml` 与 `packaging/reference-workflows/format-semantics-vision-v1.yml` 是白名单内的参考 DSL。它们仅供人工导入参考，安装器不会自动导入、更新或覆盖现有工作流；发布清单记录文件哈希。
