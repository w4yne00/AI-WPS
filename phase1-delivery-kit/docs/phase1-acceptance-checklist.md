# AI-WPS 一期交付验收清单

## 1. 安装检查

- [ ] 执行 `bash installer/install_phase1.sh` 无错误退出。
- [ ] `python3 -m pip --version` 可返回版本。
- [ ] `python3 -c "import fastapi, uvicorn, pydantic, requests"` 执行成功。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/wps-ai-assistant_1.0.0` 存在。
- [ ] `~/.local/share/Kingsoft/wps/jsaddons/publish.xml` 存在，并包含 `wps-ai-assistant`。

## 2. Adapter 检查

- [ ] `bash scripts/phase1_smoke_test.sh` 执行成功。
- [ ] `/health` 返回 `status=ok`。
- [ ] `/health` 返回 `mode=uvicorn`。
- [ ] `/templates` 返回 `general-office`。
- [ ] `/templates` 返回 `technical-file-format-requirements`。

## 3. WPS 插件检查

- [ ] 重启 WPS 后出现 `WPS AI 助理` Ribbon。
- [ ] 五个入口可见：智能改写、智能续写、格式校对、智能排版、设置。
- [ ] 点击入口后只出现一个右侧任务窗格。
- [ ] 设置页可刷新配置。
- [ ] 设置页可保存模型提供商名称、API URL、API Key。
- [ ] 清空 API URL 和 API Key 后状态显示未配置或模拟。

## 4. Word 一期能力检查

- [ ] 格式校对可返回检查结果。
- [ ] 格式校对可选择公司技术文件模板。
- [ ] 智能排版可返回排版预览。
- [ ] 智能排版可选择公司技术文件模板。
- [ ] 智能改写可针对选中文本生成结果。
- [ ] 智能续写可针对选中文本生成结果。
- [ ] 应用预览可将结果写回文档。

## 5. 结论

- 验收人员：
- 终端编号：
- 验收日期：
- 是否通过：
- 遗留问题：
