# 随交付包提供文本和视觉 Dify 参考工作流

决定后续白名单交付包包含两份可人工导入的 `format_semantics.v1` 参考 DSL：`format-semantics-text-v1.yml` 支持段落角色分类、题注关联和表题建议，并对图题操作明确返回不可视觉判断；`format-semantics-vision-v1.yml` 在此基础上支持一个图对象组最多四张图片的图题建议。两份模板包含版本化 System Prompt、固定输入变量、操作 JSON Schema 和 `result_json` 输出映射，参考最大输出设置为 2048 Token；管理员导入后自行选择 DeepSeek、Qwen 或其它实际模型。模板不得包含服务 URL、API Key、业务数据或目标环境标识，安装器不得自动导入、更新或覆盖任何现有工作流。每份 DSL 的版本和 SHA-256 进入交付清单，修改时生成差异记录。模板只提供部署起点，Adapter 内置的 `format_semantics.v1` Schema 和契约验证结果才是运行时兼容性权威。
