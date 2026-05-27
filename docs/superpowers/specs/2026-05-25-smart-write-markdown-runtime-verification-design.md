# 智能编写 Markdown 展示与运行资源校验设计

日期：2026-05-25

目标版本：`v0.12.1-alpha`

## 问题结论

仓库当前前端已经支持将智能编写返回的 Markdown 正文渲染为标题、段落、列表、加粗、引用、表格和代码块，且 `20260523` 交付包包含对应 JS/CSS 文件。现场仍呈现纯文本，更可能是 WPS 使用固定插件目录、固定任务窗格 URL 后继续加载缓存的旧页面资源，或 Dify 实际返回未包含 Markdown 标记。

## 改进范围

本修复不修改 Dify 请求字段、不修改智能编写提示词、不修改结果写回 Word 的纯文本行为，仅增强展示链路可验证性：

1. Ribbon 创建任务窗格时在 URL 中加入前端构建版本参数。
2. `taskpane.html` 引用 CSS/JS 时加入相同版本参数，使页面、脚本和样式同时失效缓存。
3. 设置诊断区域显示前端构建版本，便于现场识别正在运行的插件资源。
4. `/provider/debug-last` 仅记录响应是否包含常见 Markdown 特征，不记录正文内容。

## 数据与安全

诊断返回 `answerFormat` 摘要：

```json
{
  "containsMarkdown": true,
  "containsHeading": true,
  "containsOrderedList": true,
  "containsUnorderedList": false,
  "containsBold": true,
  "containsParagraphBreak": true
}
```

该摘要不泄露模型正文；已有 `answerLength`、请求键摘要与脱敏策略保持不变。

## 验收条件

- 任务窗格 URL 和任务窗格静态资源引用均包含 `0.12.1-alpha` 构建参数。
- 设置页能够看到前端版本 `0.12.1-alpha`。
- 智能编写返回 Markdown 时，`/provider/debug-last` 可确认对应 Markdown 特征。
- 现有 Markdown 安全渲染、复制原文和应用预览行为不回归。
