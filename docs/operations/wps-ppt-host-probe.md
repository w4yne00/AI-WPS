# WPS PPT 宿主探针验证手册

适用版本：`v0.17.0-alpha` 开发探针

目标环境：麒麟 V10 ARM、WPS 12.1.2、WPS 演示

## 1. 验证目的

本探针只验证 Linux WPS 演示 JS 插件能否稳定读取：

- 当前演示文稿名称。
- 当前幻灯片序号。
- 当前页标题。
- 当前页普通文本框内容。
- `TextFrame` 和 `TextFrame2` 文本。
- 前一页和后一页标题。
- 空白页、无标题页、图片页和图表页。

探针不连接 adapter，不调用模型后台，也不修改幻灯片。

只有本手册中的必测场景全部通过后，才能继续开发 `ppt.slide_assistant` 模型任务。

## 2. 探针文件

插件目录：

```text
formal-plugin-kit/wps-ai-assistant-wpp_1.0.0
```

关键文件：

- `ribbon.xml`：只显示“PPT 单页助手”和“设置”。
- `taskpane.html`：只读探针界面。
- `taskpane.js`：异步触发当前页读取。
- `taskpane-helpers.js`：WPS 对象容错、当前页文本提取和输入截断。

## 3. 安装前备份

完全退出 WPS 文字、WPS 表格和 WPS 演示后执行：

```bash
export WPS_JSADDONS_DIR="$HOME/.local/share/Kingsoft/wps/jsaddons"
mkdir -p "$WPS_JSADDONS_DIR"
if [ -f "$WPS_JSADDONS_DIR/publish.xml" ]; then
  cp "$WPS_JSADDONS_DIR/publish.xml" "$WPS_JSADDONS_DIR/publish.xml.ppt-probe-backup"
fi
```

该备份只用于恢复 `publish.xml`。不要删除现有 Word、Excel 插件和 adapter 配置。

## 4. 安装探针插件

将仓库中的插件目录复制到目标机后执行：

```bash
export WPS_JSADDONS_DIR="$HOME/.local/share/Kingsoft/wps/jsaddons"
rm -rf "$WPS_JSADDONS_DIR/wps-ai-assistant-wpp_1.0.0"
cp -R wps-ai-assistant-wpp_1.0.0 "$WPS_JSADDONS_DIR/wps-ai-assistant-wpp_1.0.0"
```

编辑 `$WPS_JSADDONS_DIR/publish.xml`，在 `<jsplugins>` 内增加且只增加一次：

```xml
<jsplugin name="wps-ai-assistant-wpp" url="file://" type="wpp" enable="enable_dev" version="1.0.0"/>
```

保留已有 Word、Excel 和第三方插件条目。最终文件结构示例：

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<jsplugins>
  <jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>
  <jsplugin name="wps-ai-assistant-et" url="file://" type="et" enable="enable_dev" version="1.0.0"/>
  <jsplugin name="wps-ai-assistant-wpp" url="file://" type="wpp" enable="enable_dev" version="1.0.0"/>
</jsplugins>
```

检查注册结果：

```bash
grep 'name="wps-ai-assistant-wpp"' "$WPS_JSADDONS_DIR/publish.xml"
grep 'type="wpp"' "$WPS_JSADDONS_DIR/publish.xml"
test -f "$WPS_JSADDONS_DIR/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js"
```

三条命令都应成功。

## 5. 准备测试演示文稿

新建至少 7 页演示文稿：

1. 标准标题和正文页，标题为“项目背景”。
2. 标准标题和两个正文文本框，标题为“项目进展”。
3. 标准标题和正文页，标题为“风险与措施”。
4. 没有标题占位符，手工放置两个文本框。
5. 只有标题，没有正文。
6. 完全空白页。
7. 仅图片或仅图表页。

第 2 页两个正文文本框分别填写：

```text
总体方案设计已完成
正在开展接口联调
```

## 6. 执行验证

打开 WPS 演示，确认 Ribbon 中出现“WPS AI 助理”页签，且只显示：

- PPT 单页助手。
- 设置。

点击“PPT 单页助手”，再点击“读取当前页”。结果区应显示 JSON。

第 2 页的核心期望值：

```json
{
  "scene": "ppt",
  "slide": {
    "index": 2,
    "title": "项目进展",
    "textBlocks": [
      "总体方案设计已完成",
      "正在开展接口联调"
    ],
    "previousTitle": "项目背景",
    "nextTitle": "风险与措施",
    "truncated": false
  }
}
```

`presentationId` 应为当前文件名。`bodyCharacterCount` 应为两个正文文本框清洗后的字符总数。

## 7. 验收记录

| 场景 | 期望结果 | 结果 |
| --- | --- | --- |
| `wpp` 插件注册 | WPS 演示出现“WPS AI 助理”页签 | 未验证 |
| 宿主隔离 | 不显示 Word 和 Excel 专用按钮 | 未验证 |
| 当前页序号 | 切换页面后 `slide.index` 同步变化 | 未验证 |
| 标题占位符 | 标准标题正确进入 `slide.title` | 未验证 |
| 多文本框 | 每个正文文本框保持独立数组项 | 未验证 |
| `TextFrame2` | 使用新版文本框时仍可读取文字 | 未验证 |
| 相邻页标题 | 只读取前后各一页标题 | 未验证 |
| 无标题占位符 | 第一个非空短文本作为候选标题 | 未验证 |
| 仅标题页 | `textBlocks` 为空，不报错 | 未验证 |
| 空白页 | 标题和正文为空，不报错 | 未验证 |
| 仅图片/图表页 | 不读取图片或图表数据，不报错 | 未验证 |
| 超长文本框 | 单文本框最多 1000 字并标记截断 | 未验证 |
| 超长当前页 | 正文合计最多 3000 字并标记截断 | 未验证 |
| 响应性 | 点击读取时任务窗格不冻结 | 未验证 |
| 只读保护 | 读取前后幻灯片内容和版式不变化 | 未验证 |

## 8. 失败信息采集

出现异常时保留以下信息：

1. WPS 完整版本号和系统架构。
2. `publish.xml` 中 `wps-ai-assistant-wpp` 完整条目。
3. 当前测试页类型和页码。
4. 结果区完整文字或截图。
5. Ribbon 是否出现、任务窗格是否能打开。
6. WPS 是否冻结，以及恢复所需时间。

常见结果判断：

- 没有 Ribbon：优先核对 `type="wpp"`、插件目录名和 `publish.xml` 路径。
- Ribbon 存在但任务窗格打不开：核对 `index.html`、`ribbon.js` 和 `CreateTaskPane`。
- 提示“未能读取当前幻灯片”：目标 WPS 的当前页对象路径与探针假设不同，需要根据现场对象调整兼容读取。
- 页码正常但文字为空：重点核对 `Shapes`、`TextFrame`、`TextFrame2` 和 `TextRange.Text`。

## 9. 恢复原配置

需要移除探针时，完全退出 WPS 后执行：

```bash
export WPS_JSADDONS_DIR="$HOME/.local/share/Kingsoft/wps/jsaddons"
rm -rf "$WPS_JSADDONS_DIR/wps-ai-assistant-wpp_1.0.0"
if [ -f "$WPS_JSADDONS_DIR/publish.xml.ppt-probe-backup" ]; then
  cp "$WPS_JSADDONS_DIR/publish.xml.ppt-probe-backup" "$WPS_JSADDONS_DIR/publish.xml"
fi
```

该操作不影响 Word、Excel 插件和 adapter 运行时配置。
