# 按服务地址和密钥指纹合并旧直连配置

升级时对旧任务直连配置计算“规范化服务地址 + API Key 指纹”分组，每组形成一份共享直连服务；地址相同但 Key 不同或 Key 相同但地址不同都不得合并。规范化服务地址须折叠主机名大小写与 IDNA、http/https 默认端口，并正确处理 IPv6 与非默认端口。每个功能原有模型、温度、Token 和图片设置转为任务模型选择；同一任务若存在多份旧档案，只消费活动项（否则最后一项），未消费记录写入 `legacyDirectPending` 并进入 `pending_manual`（`DIRECT_SERVICE_MIGRATION_PENDING_PROFILES`），禁止删除对应配置和 Key。不完整配置只迁移为未启用草稿，并逐字段保留已有 URL 或 Key。复用已有共享服务时，迁入模型与原 `defaultModel` 不一致则置空默认模型。已迁移且原本可用的模型在目录尚未成功拉取前处于 `legacy_compatible` 可用状态，不得因空目录阻断活动任务；兼容证明绑定服务 URL、Key 指纹、revision 与期限，复用已有共享服务时同样播种该证明。401/403 等确定性认证失败立即撤销兼容。迁移提交以自包含快照（JSON + 被引用 Key + 事务日志）为回滚/恢复单元，硬终止后启动协调未完成事务；正式配置不可读时在所有配置读取之前恢复，恢复记录写失败须可见。未消费档案提供脱敏列表及迁移/重建/放弃入口。成功切换后才删除已被消费且不再被引用的重复 Key 文件；若形成超过五组不同服务，则升级进入受限处理状态，不擅自删除或覆盖任何配置。该规则减少重复密钥并保持原任务行为，代价是同一后台的多个账号仍会显示为不同服务，且超限或未消费多档案现场需要管理员决策。

`GET /provider/direct-services` 的 `legacyDirectMigration` 字段披露本次读取触发的迁移结果：无待迁移配置为 `not_needed`，成功为 `completed`，超过五份上限为 `restricted` 并附带 `DIRECT_SERVICE_MIGRATION_LIMIT` 和所需服务数，同任务未消费旧档案为 `pending_manual` 并附带 `DIRECT_SERVICE_MIGRATION_PENDING_PROFILES`。同一响应的 `legacyDirectPending` 给出脱敏列表；`GET/POST /provider/legacy-direct-pending` 提供列表与迁移/重建/放弃。服务地址规范化拒绝任何 `userinfo@host`（含空 userinfo）。迁移入口全量覆盖九类任务（Word 4 类：智能编写、智能仿写、文档审查、格式审查；Excel 3 类：智能分析、公式助手、智能填写；PPT 2 类：幻灯片助手、结构审查）的旧 `direct_model` 配置；读取服务列表或解析活动任务认证时触发迁移。

旧直连写入合同全面收缩与退役：
1. `POST/PATCH /provider/model-configurations` 及其 API Key 替换、复制接口严格拒绝 `access_method == "direct_model"`，统一返回 HTTP 400 错误码 `MODEL_CONFIG_DIRECT_WRITE_RETIRED`；
2. Word、Excel、PPT 三大宿主的前端模型配置编辑器（Workflow Profile Editor）全面下线 `direct_model` 选项及模型标识、温度、Token 高级配置字段，直连服务录入与管理完全收敛至共享直连服务接口；
3. `WorkflowProfileCompatibilityStore` 严格限定仅访问 `workflow_platform` 配置。
