# Smart Write Compact SOE Technical Options Plan

日期：2026-05-28

目标版本：`v0.12.3-alpha`

## 执行步骤

1. 先补回归测试：
   - `formal-plugin-kit/tests/layout-smoke.test.js` 检查新菜单、新默认值、紧凑样式、版本缓存参数。
   - `adapter_service/tests/test_enterprise_provider.py` 检查新提示词进入统一 query，并验证旧值别名兼容。

2. 修改任务窗格：
   - `taskpane.html` 更新智能编写三组下拉项，新增“当前要求”摘要。
   - `taskpane.js` 更新提示词字典、默认状态、摘要刷新逻辑，智能编写关闭常驻提示词明细卡。
   - `taskpane.css` 将智能编写设置区压缩为四列/窄窗两列，缩短说明文字占位，智能编写模式扩大结果预览高度。

3. 修改 adapter：
   - `provider_client.py` 更新 `STYLE_TEXT`、`FOCUS_TEXT`、`LENGTH_TEXT`。
   - 保留旧值别名，确保旧前端或历史 payload 不会退回默认错误语义。

4. 同步版本和文档：
   - 更新前端静态资源版本参数、manifest、adapter 版本和启动脚本期望版本。
   - 更新 README、README-ZH、handoff 和智能编写 Dify 操作手册。

5. 验证：
   - 运行 Python 单测、前端 layout smoke、helper 测试、`taskpane.js` 语法检查、Python compileall 和 `git diff --check`。
