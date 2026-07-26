# AI-WPS 一期交付验收清单

## 1. 安装检查

- [ ] 执行 `bash installer/install_phase1.sh` 无错误退出。
- [ ] `python3 -m pip --version` 可返回版本。
- [ ] `python3 -c "import fastapi, uvicorn, pydantic, requests"` 执行成功。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0` 存在。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-et_1.0.0` 存在。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-wpp_1.0.0` 存在。
- [ ] `publish.xml` 同时包含 Word 的 `type="wps"`、Excel 的 `type="et"` 和 PPT 的 `type="wpp"`。
- [ ] 首次安装自动创建非空的 `adapter-start-kit/run/writing_policies.db`，文件权限为 `0600`。
- [ ] `release-manifest.json` 的版本、三宿主、四个规范包和版本规则号与本包一致。

## 2. Adapter 检查

- [ ] `bash scripts/phase1_smoke_test.sh` 执行成功。
- [ ] `/health` 返回 `status=ok`。
- [ ] `/health` 返回 `mode=uvicorn`。
- [ ] `/health` 返回 `version=0.20.0-alpha`。
- [ ] `/templates` 返回 `general-office`。
- [ ] `/templates` 返回 `technical-file-format-requirements`。
- [ ] 旧版 Dify 工作流可继续读取 `inputs.query`。
- [ ] 新版“用户输入”节点工作流在旧格式返回 HTTP 400 后可自动切换并成功返回。
- [ ] `/provider/debug-last` 显示最终 `inputMode`，且错误摘要不包含完整提示词或 API Key。
- [ ] PPT 文档总结工作流的用户输入节点暴露 `userinput.query` 和 `userinput.files`。
- [ ] PPT 文件分支连接文档提取节点，回答节点只返回最终答案且不显示 `<think>` 内容。

## 3. WPS 插件检查

- [ ] 重启 WPS Word 后出现 `WPS AI 助理` Ribbon。
- [ ] Word 入口可见：智能编写、智能仿写、文档审查、格式审查、设置。
- [ ] 重启 WPS Excel 后出现 `WPS AI 助理` Ribbon。
- [ ] Excel 入口只显示：智能分析、设置。
- [ ] 点击入口后只出现一个右侧任务窗格。
- [ ] 设置页可刷新配置。
- [ ] 设置页只显示统一 API URL，不显示统一 API Key 或模型提供商名称输入框。
- [ ] Word 四个功能、智能分析和智能总结均可保存至少两个具名工作流档案，并可填写备注。
- [ ] 功能页下拉选择后立即激活对应工作流，不显示额外“切换”按钮。
- [ ] 编辑工作流时 Key 留空保持原密钥，填写新 Key 时只替换当前档案密钥。
- [ ] 当前工作流不可直接删除，切换后可删除旧的备用档案。
- [ ] Word 不显示 Excel 工作流档案，Excel 不显示 Word 工作流档案。
- [ ] PPT 入口只显示：智能总结、设置，且只显示 PPT 工作流档案。
- [ ] Word、Excel、PPT 三个宿主的 Ribbon 和工作流档案互不交叉显示。
- [ ] 清空 API URL 后状态显示未配置或模拟；旧统一 Key 回退仅由 adapter 兼容，不在任务窗格展示。

## 4. Word 一期能力检查

- [ ] 智能编写可针对选中文本生成改写/续写/总结结果。
- [ ] 智能仿写可针对选中文本或粘贴模板生成仿写结果，且不显示写回按钮。
- [ ] 文档审查可返回问题列表、复制建议和审查记录。
- [ ] 格式审查可返回按模板分组的格式问题，且不写回文档。
- [ ] 应用预览可将结果写回文档。
- [ ] 三个写作规范任务在单个预置包缺失、校验失败或版本不兼容时继续调用原模型工作流。
- [ ] 组织数据库不可读或迁移失败时主文件未被清空、重建或覆盖，并保留 `writing_policies.db.backup-*` 恢复备份。
- [ ] 规范解析或结果检查异常时结果区显示“写作规范暂未应用，已继续处理”，不显示模型后台连接失败。
- [ ] `/writing-policies/diagnostics` 只包含阶段、受控错误码、规则 ID、预置版本、计数和耗时，不包含 API Key、用户全文或完整规则正文。
- [ ] 四个预置规范包及对应 `*.review.json` 均可加载，来源、版本、许可证和审阅摘要可追溯。
- [ ] 预置包版本更新后，已有组织覆盖、组织自定义规范和预置停用状态仍优先生效。
- [ ] 执行 `AI_WPS_WRITING_POLICY_PERFORMANCE_TARGET_MS=200 PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_writing_policy_performance -v` 通过。
- [ ] 320 px 窄任务窗无横向页面溢出、遮挡或不可达操作；规范列表单页最多渲染 50 条，键盘可通过上一页、下一页访问第 51 条及后续条目。
- [ ] 键盘可操作规范选择、结果披露和设置控件；reduced-motion 开启后无非必要位移动画。
- [ ] 故障注入前后模型超时、文档审查长任务轮询、复制、智能编写写回和智能仿写只读行为保持不变。

## 5. Excel“智能分析”能力检查

- [ ] 智能分析优先读取选中区域。
- [ ] 无有效选区时可读取当前工作表已用范围。
- [ ] 结果预览显示数据概览、关键发现、风险异常、建议动作。
- [ ] 汇报段落可复制。
- [ ] 模型响应超过普通请求时长时，任务窗格持续轮询，不提前显示连接超时。
- [ ] 状态查询短暂失败时保留任务编号，并自动恢复查询。
- [ ] 不修改单元格、不新增工作表、不写回公式。

## 6. PPT“智能总结”能力检查

- [ ] 当前页有有效正文时自动使用优化模式。
- [ ] 当前页为标题页或空白页时要求填写生成要求。
- [ ] 主标题和可选副标题分开识别，副标题不混入普通正文。
- [ ] 当前页结果支持预览、纯文本、复制标题、复制要点、复制结论和复制完整结果。
- [ ] 文档模式可选择一个 `.md` 文件并生成整套 PPT 建议。
- [ ] 文档模式可选择一个结构有效的 `.docx` 文件并生成整套 PPT 建议。
- [ ] 损坏、伪装或结构无效的 DOCX 被 adapter 拒绝并显示明确提示。
- [ ] `.md`、`.docx` 之外的文件类型在前端和 adapter 均被拒绝。
- [ ] 超过 10 MB 的文件在前端和 adapter 均被拒绝。
- [ ] 建议页数可分别选择 5、8、10、12、15 页，默认值为 10 页。
- [ ] 文档结果支持复制大纲和复制完整方案。
- [ ] 每页结果支持复制标题、复制正文和复制本页。
- [ ] 模型处理超过 180 秒时任务窗格仍保留任务编号并继续恢复查询。
- [ ] 任务运行中关闭并重新打开任务窗格后，使用原任务编号恢复结果，不重复提交文件或模型任务。
- [ ] 状态查询短暂失败后继续恢复，不把慢模型误报为连接失败。
- [ ] 模型返回非标准 JSON 或普通 Markdown 时可显示并复制原始回复。
- [ ] 不自动创建页面，不修改幻灯片文字、版式、对象、主题、动画或备注。

## 7. 覆盖安装与配置保护

- [ ] 覆盖安装前记录当前 API URL、统一 API Key 和各任务工作流档案。
- [ ] 执行新版本 `installer/install_phase1.sh` 覆盖安装后，`config/adapter.json` 保持原 API URL。
- [ ] 覆盖安装后，`run/provider_api_key` 和 `run/provider_api_keys/` 中的统一及任务级密钥均被保留。
- [ ] 覆盖安装后，`run/writing_policies.db` 的 SHA-256 与安装前一致。
- [ ] 覆盖安装后，全部已有 `writing_policies.db.backup-*` 均被保留。
- [ ] 覆盖安装后，组织覆盖、组织自定义规范和预置停用状态仍可读取并优先于预置基线。
- [ ] 覆盖安装后，智能编写、智能仿写、文档审查、格式审查、智能分析、智能总结仍命中原工作流档案。

## 8. 交付包完整性与排除检查

- [ ] 包内包含四个规范包、四份已批准审阅清单、`schema-v1.json`、来源文档和 `THIRD_PARTY_NOTICES.md`。
- [ ] 包内包含 CSV/XLSX 空白导入模板、写作规范使用说明、验收清单和验收记录。
- [ ] 包内不包含 `writing_policies.db`、任何数据库备份、`adapter.json`、API Key、日志目录或 `.log` 文件。
- [ ] 包内除 `docs/import-templates/` 空白模板外，不包含其他 CSV/XLSX 用户导入内容。
- [ ] 包内不包含名称含 `.draft.` 的未确认审阅草稿。
- [ ] Python 全量测试、全部 Node 测试、三宿主脚本语法、Shell 语法、浏览器布局和交付包构建审计均通过。

## 9. 麒麟 V10 发布验收

- [ ] 在无历史安装目录的终端完成首次安装，并验证规范库初始化。
- [ ] 新增一条组织自定义规范、建立一条预置覆盖并停用一条预置项，重启 WPS 和 adapter 后状态保持。
- [ ] 使用启用 `<think>` 的慢模型分别验证文档审查、智能分析和智能总结，180 秒以上仍保留任务编号并持续轮询。
- [ ] 分别注入单个预置包损坏、组织数据库不可读、规范解析异常和结果检查异常，三个 Word 任务均降级继续且不泄露敏感信息。
- [ ] 记录安装前数据库、全部已有备份、API URL、统一 Key 和工作流档案密钥摘要，再次覆盖安装后逐项一致。
- [ ] 格式审查、Excel 智能分析、PPT 智能总结、工作流档案、智能编写写回、文档审查/智能分析/智能总结超时与轮询回归无变化。

## 10. 结论

- 验收人员：
- 终端编号：
- 验收日期：
- 是否通过：
- 遗留问题：
