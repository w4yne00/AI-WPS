# Word 格式语义模型接入

`word.format_review` 的工作流平台接入使用 `format_semantics.v1` 协议。工作流必须把以下固定字段作为输入：

- `contract_version`：固定为 `format_semantics.v1`。
- `operation`：只能是 `classify_role`、`associate_caption`、`suggest_table_caption` 或 `suggest_figure_caption`。
- `candidate_json`：adapter 提交的候选范围、证据和快照绑定；这是唯一事实来源。
- `image_files`：仅 `suggest_figure_caption` 使用，最多四个图像文件。

adapter 只读取 `data.outputs.result_json`，并按当前操作的完整 Schema 校验。自由文本、聊天历史、其他输出变量和不在候选范围内的对象都不能作为结果来源。

模型直连配置使用同一生产格式语义契约，但验证请求只执行 `classify_role`：Adapter 将固定的合成候选、`snapshotBinding` 和操作名放入直连模型的用户消息，并校验模型返回的完整契约对象。旧式角色 JSON 数组、错误 `operation`、错误绑定、未知候选 ID 或缺少候选结果均验证失败。验证只使用合成事实，不读取或发送用户文档、文档正文或图片像素。

工作流平台的四类操作（`classify_role`、`associate_caption`、`suggest_table_caption`、`suggest_figure_caption`）保持不变。`POST /provider/model-configurations/{configurationId}/validate` 只验证指定配置，不自动激活，也不改变任务路由；返回结果包含配置名称、ID、修订号及其是否为当前配置。服务地址、接入方式、模型、上下文、输出上限或 API Key 变化会使原验证记录过期。

## 格式审查报告中的模型调用诊断

同步 `/word/format-review` 与确定性格式审查后台报告都在 `summary` 中披露同一组安全字段：`modelConfigurationName`、`modelConfigurationId`、`modelConfigurationVersion`、`accessMethod`、`semanticStatus`、`aiCandidateCount`、`aiAttempted`、`aiCallCount`、`aiAcceptedCount` 和 `aiFallbackReason`。`provider` 只表示“识别来源”，不替代模型调用事实；前端和 Markdown 导出使用中文标签，不直接展示 Provider 标识。

`aiAttempted=false` 且 `aiFallbackReason=no_candidates` 表示没有需要模型确认的模糊候选，属于正常未调用；这与模型未配置、协议未就绪或模型调用失败不同。模型已调用但没有被接受的结果仍返回确定性审查结果，并使用稳定原因码 `format_semantic_response_invalid`、`format_semantic_candidate_out_of_range`、`format_semantic_low_confidence` 或 `format_semantic_zero_accepted`；请求失败使用 `provider_request_failed`。

诊断投影不包含 API Key、认证头、文档正文、原始模型响应、思考内容或本地敏感路径。模型配置快照在后台任务提交时冻结，报告和导出只保留上述身份及计数。

## 受控图片组生命周期

`suggest_figure_caption` 的图片像素输入必须经过以下顺序：

1. 确定性抽取确认正文图片缺少图题，且图片类型、题注关联和对象组均无歧义。
2. Adapter 为最多四张图片分配随机、短期、仅 Adapter 可控的 PNG 槽位；WPS 只能调用 `SaveAsPicture(slotPath, 2)` 写入槽位。
3. Adapter 校验槽位位于受控目录、非符号链接普通文件、属主正确、PNG CRC 有效，并执行 5 MiB、8192 单边和 2,000 万像素限制。
4. 通过 `image_files` 发送当前批次：工作流模式先上传并只传 Dify 文件 ID，直连模式在内存中转为 PNG data URI。候选 JSON 不包含本地路径、密钥或原始图片内容。
5. 每个批次或重试完成后删除图片组；文档关闭、身份变化或编辑序列变化会拒绝提交并清理剩余槽位。

运行时图片总开关默认关闭。关闭时仍可基于 Alt Text 和邻近文字生成 `text_evidence_only` 图题建议，但不得创建槽位、导出 PNG 或上传像素；证据不足返回 `not_assessable`。

模型配置保存、升级或服务地址、调用方式、模型参数、API Key 等相关字段变化后，格式工作流必须用无敏感合成数据依次验证四类操作。验证未通过或验证记录已过期时，已保存的地址和 Key 不会被清除，格式审查只执行确定性规则，并在摘要中披露语义协议未就绪。

`packaging/reference-workflows/format-semantics-text-v1.yml` 与 `packaging/reference-workflows/format-semantics-vision-v1.yml` 是白名单内的参考 DSL。它们仅供人工导入参考，安装器不会自动导入、更新或覆盖现有工作流；发布清单记录文件哈希。
