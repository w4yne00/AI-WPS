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

## 3. WPS 插件检查

- [ ] 重启 WPS Word 后出现 `WPS AI 助理` Ribbon。
- [ ] Word 入口可见：智能编写、智能仿写、文档审查、格式审查、设置。
- [ ] 重启 WPS Excel 后出现 `WPS AI 助理` Ribbon。
- [ ] Excel 入口只显示：Excel 智能分析、设置。
- [ ] 点击入口后只出现一个右侧任务窗格。
- [ ] 设置页可刷新配置。
- [ ] 设置页可保存模型提供商名称、API URL、API Key。
- [ ] Word 四个功能和 Excel 智能分析均可保存至少两个具名工作流档案。
- [ ] 功能页下拉选择后，点击“切换”才改变当前工作流，并提示下一次任务生效。
- [ ] 当前工作流不可直接删除，切换后可删除旧的备用档案。
- [ ] Word 不显示 Excel 工作流档案，Excel 不显示 Word 工作流档案。
- [ ] PPT 入口只显示：PPT 单页助手、设置，且只显示 PPT 工作流档案。
- [ ] 清空 API URL 和 API Key 后状态显示未配置或模拟。

## 4. Word 一期能力检查

- [ ] 智能编写可针对选中文本生成改写/续写/总结结果。
- [ ] 智能仿写可针对选中文本或粘贴模板生成仿写结果，且不显示写回按钮。
- [ ] 文档审查可返回问题列表、复制建议和审查记录。
- [ ] 格式审查可返回按模板分组的格式问题，且不写回文档。
- [ ] 应用预览可将结果写回文档。

## 5. Excel 一期能力检查

- [ ] Excel 智能分析优先读取选中区域。
- [ ] 无有效选区时可读取当前工作表已用范围。
- [ ] 结果预览显示数据概览、关键发现、风险异常、建议动作。
- [ ] 汇报段落可复制。
- [ ] 模型响应超过普通请求时长时，任务窗格持续轮询，不提前显示连接超时。
- [ ] 状态查询短暂失败时保留任务编号，并自动恢复查询。
- [ ] 不修改单元格、不新增工作表、不写回公式。

## 6. PPT 一期能力检查

- [ ] 有有效正文时自动使用优化模式。
- [ ] 标题页或空白页要求填写生成要求。
- [ ] 结果支持预览、纯文本和四类复制。
- [ ] 慢任务保留任务编号并可恢复查询。
- [ ] 不修改幻灯片文字、版式、对象或备注。

## 7. 结论

- 验收人员：
- 终端编号：
- 验收日期：
- 是否通过：
- 遗留问题：
