# Dify 格式语义工作流必须实现版本化契约

决定首版定义 `format_semantics.v1` 作为 Dify 自定义工作流参与格式模型语义补充的强制协议。工作流输入固定包含 `contract_version`、`operation` 和 `candidate_json`，图像操作另接收 `image_files`；AI-WPS 只从固定输出变量 `result_json` 读取结果，并按对应操作的完整 JSON Schema 校验。AI-WPS 不覆盖、拼接或自动修改用户工作流的 System Prompt，工作流 URL 和 Key 可连接不代表契约兼容。模型配置保存、升级或服务地址、工作流、模式、模型标识等契约相关字段变化后，使用无敏感合成数据分别验证 `classify_role`、`associate_caption`、`suggest_table_caption` 和 `suggest_figure_caption`，最后一项同时完成视觉能力验证；验证调用不计入具体文档的十六次调用预算。升级前保存的工作流配置和密钥必须原样保留，但在协议验证通过前，格式审查只执行确定性规则。失败界面提供稳定错误码、不兼容字段和工作流改造说明，不自动迁移工作流或提示词。模型直连模式由 Adapter 构造受控提示词和 Schema，不要求实现 Dify 输出变量。
