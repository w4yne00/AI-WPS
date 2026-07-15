# AI-WPS 一期交付验收清单

## 1. 安装检查

- [ ] 执行 `bash installer/install_phase1.sh` 无错误退出。
- [ ] `python3 -m pip --version` 可返回版本。
- [ ] `python3 -c "import fastapi, uvicorn, pydantic, requests"` 执行成功。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0` 存在。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-et_1.0.0` 存在。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant-wpp_1.0.0` 存在。
- [ ] `publish.xml` 同时包含 Word 的 `type="wps"`、Excel 的 `type="et"` 和 PPT 的 `type="wpp"`。

## 2. Adapter 检查

- [ ] `bash scripts/phase1_smoke_test.sh` 执行成功。
- [ ] `/health` 返回 `status=ok`。
- [ ] `/health` 返回 `mode=uvicorn`。
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
- [ ] 覆盖安装后，智能编写、智能仿写、文档审查、格式审查、智能分析、智能总结仍命中原工作流档案。

## 8. 结论

- 验收人员：
- 终端编号：
- 验收日期：
- 是否通过：
- 遗留问题：
