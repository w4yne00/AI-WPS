# Word、Excel、PPT 宿主感知任务窗格主题设计

日期：2026-07-14  
目标版本：v0.18.x-alpha 后续增量版本  
范围：Word、Excel、PPT 三个 WPS JS 插件的任务窗格前端

## 1. 背景

当前三个宿主的任务窗格已经统一布局，但仍共用同一套蓝灰色主色，无法直观体现 WPS 文字、表格、演示的宿主差异。Word 和 Excel 的右上角连接状态直接显示 `/health` 返回的 `ok`，且没有 PPT 已具备的设置快捷入口和返回交互。

WPS 开放平台将任务窗格定义为加载网页的侧边界面，网页可以自行组织视觉和交互；WPS 加载项同时支持 Windows 和 Linux。因此，本次修改可以完全限定在现有 HTML、CSS 和 JavaScript 前端，不需要新增 WPS API 或修改 adapter：

- [任务窗格概述](https://open.wps.cn/documents/app-integration-dev/wps365/client/wpsoffice/jsapi/addin-api/TaskPane/task-pane-overview)
- [加载项概述](https://open.wps.cn/documents/app-integration-dev/wps365/client/wpsoffice/wps-integration-mode/wps-addin-development/addin-overview)

WPS 文档未规定任务窗格必须采用的十六进制色值。本设计依据用户确认的 WPS 宿主图标语义，采用文字蓝、表格绿、演示橙，并选择“平衡宿主主题”方案：颜色承担宿主识别，不大面积覆盖内容背景。

## 2. 目标

1. Word、Excel、PPT 分别使用蓝、绿、橙作为宿主主色。
2. 三个任务窗格右上角健康检查成功时统一显示“已连接”，不显示原始 `ok`。
3. Word 和 Excel 增加与 PPT 相同结构的设置快捷按钮，并支持从设置页返回功能页。
4. 保持三个宿主的布局、控件尺寸、状态语义和设置页结构一致。
5. 不修改业务任务、adapter 接口、模型调用、轮询、复制、预览或回写逻辑。

## 3. 非目标

- 不修改 Ribbon 的宿主隔离或按钮功能。
- 不修改 Word 智能编写回写及对照高亮。
- 不修改 Word 文档审查、Excel 智能分析、PPT 智能总结的后台任务链路。
- 不调整工作流档案、API URL、API Key 或安装配置保护逻辑。
- 不新增依赖，不引入前端框架或图标库。
- 不根据 WPS 运行时主题动态切换深色模式。

## 4. 视觉方案

### 4.1 宿主色

| 宿主 | 主色 | 悬停/按下色 | 浅色背景 | 语义 |
| --- | --- | --- | --- | --- |
| Word | `#2F6DB3` | `#265C98` | `#EAF2FB` | WPS 文字蓝 |
| Excel | `#237A4B` | `#1B643D` | `#EAF6EF` | WPS 表格绿 |
| PPT | `#D36B2C` | `#B95720` | `#FFF1E7` | WPS 演示橙 |

每个插件继续通过自身 `taskpane.css` 定义 CSS 变量，不在运行时判断宿主。宿主色应用于：

- 任务窗格顶部的细识别线；
- 主操作按钮及其悬停、按下状态；
- 选中态、分段控件激活态和可见焦点框；
- 结果区标题、链接等现有强调元素；
- 识别范围、当前状态等少量浅色信息区域。

宿主色不应用于成功、警告和错误状态。连接成功继续使用绿色状态语义，即使当前宿主是 Word 或 PPT，也不把成功徽标改成蓝色或橙色。

### 4.2 视觉强度

采用用户确认的“B. 平衡宿主主题”：

- 保留白色内容面板和中性正文颜色；
- 不使用大面积饱和色标题栏；
- 不改变现有圆角、间距、字号和信息密度；
- 通过顶部细线、主按钮和浅色信息区形成宿主识别。

## 5. 顶部状态与设置交互

### 5.1 顶部结构

三个宿主统一采用以下顺序：

1. 左侧显示“WPS AI 助理”和当前功能标题；
2. 右侧先显示设置/返回图标按钮；
3. 最右显示连接状态徽标。

设置按钮使用插件内已有 `assets/icon-settings.png`。进入设置页后隐藏设置图片并显示返回箭头；按钮的 `title` 和 `aria-label` 同步变为返回目标功能的中文名称。

### 5.2 连接状态文案

| 场景 | 样式 | 文案 |
| --- | --- | --- |
| 正在请求 `/health` | `badge-warn` | 检测中 |
| `/health` 成功 | `badge-ok` | 已连接 |
| adapter 未启动或请求失败 | `badge-warn` 或 `badge-error` | 待启动或未连接 |

Word 和 Excel 不再把 `health.data.status` 原样写入徽标。`ok` 仍保留在 adapter 接口响应中，前端只做用户可见文案转换。PPT 现有“已连接/未连接”逻辑保持不变。

### 5.3 Word 返回行为

Word 同一任务窗格包含智能编写、智能仿写、文档审查、格式审查和设置。新增 `lastTaskMode` 状态，规则如下：

- 每次进入非设置功能时记录该功能；
- 点击设置按钮进入设置页时保留 `lastTaskMode`；
- 设置页点击返回时回到 `lastTaskMode`；
- 若通过 `?mode=settings` 直接打开设置且没有历史功能，默认返回智能编写；
- 返回时继续调用现有 `switchMode`，确保对应工作流档案、范围和未完成任务恢复逻辑仍生效。

### 5.4 Excel 返回行为

Excel 当前只有智能分析和设置：

- 功能页点击设置按钮进入设置页；
- 设置页按钮切换为返回箭头；
- 点击返回进入智能分析，并继续调用现有范围刷新、工作流档案加载和未完成任务恢复逻辑。

### 5.5 PPT 行为

PPT 保留现有设置/返回状态机，仅替换宿主主题变量为橙色并补充相应视觉测试。当前页总结、文档总结和任务恢复逻辑不变。

## 6. 文件范围

预计修改：

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- `formal-plugin-kit/tests/layout-smoke.test.js`

不修改 adapter、Python 服务、Ribbon XML、manifest、安装脚本或交付包。

## 7. 测试策略

实施采用测试先行：

1. 在 `formal-plugin-kit/tests/layout-smoke.test.js` 中增加静态契约断言并确认失败：
   - Word、Excel HTML 包含 `btn-open-settings`；
   - 三个 CSS 文件分别包含确认后的宿主主色；
   - Word、Excel 成功健康状态使用“已连接”，不透传 `ok`；
   - Word JavaScript 包含独立 `lastTaskMode`，且设置按钮返回时使用该状态；
   - Excel 设置返回智能分析；
   - Word、Excel 设置按钮在设置页使用 `is-back` 状态。
2. 进行最小实现，使新增测试通过。
3. 运行现有任务窗格辅助函数测试、PPT 辅助函数测试和布局冒烟测试。
4. 对修改后的 JavaScript 运行 `node --check`。
5. 在 420×900 视口检查 Word、Excel、PPT 的功能页和设置页：
   - 无横向溢出；
   - 标题、设置按钮和状态徽标不重叠；
   - 设置/返回图标状态正确；
   - 三个宿主色可区分，且正文可读性不下降。

## 8. 风险与保护措施

- **Word 模式丢失风险**：设置页不直接覆盖返回目标，使用独立 `lastTaskMode` 保存最后一个非设置功能。
- **任务恢复回归风险**：返回功能页继续走原有 `switchMode` 分支，不自行复制恢复逻辑。
- **状态语义混淆风险**：宿主色与成功/警告/错误色分离，连接徽标保持统一状态色。
- **窄任务窗格拥挤风险**：设置按钮使用固定 36px 图标尺寸，徽标使用短文案“已连接”，并在 420px 视口验证。
- **缓存风险**：本次开发不变更发布版本号或交付包；本地和目标机验收时关闭并重新打开对应 WPS 宿主，确保任务窗格重新加载插件资源。

## 9. 验收标准

1. Word 主色为蓝色、Excel 主色为绿色、PPT 主色为橙色，三者内容布局保持一致。
2. 三个宿主连接成功时右上角只显示“已连接”，不显示 `ok`。
3. Word 和 Excel 右上角均可进入设置，设置页同一按钮可返回功能页。
4. Word 从任一功能进入设置后可返回原功能；直接打开设置时返回智能编写。
5. Excel 设置页返回智能分析；PPT 设置返回行为无回归。
6. 所有既有前端测试和新增测试通过，JavaScript 语法检查通过。
7. 420px 宽任务窗格无横向滚动、控件重叠或文本截断。
8. 不发生 adapter、模型调用、任务轮询、复制、预览和回写行为变化。
