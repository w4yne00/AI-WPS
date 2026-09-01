# v0.26.0-preview.1 目标机验收记录

## 基本信息

- 对应工单：[Issue #120](https://github.com/w4yne00/AI-WPS/issues/120)
- 验收版本：`v0.26.0-preview.1`
- 验收范围：麒麟 V10 ARM、目标 WPS、既有 Phase1 安装共存边界
- Issue #119 状态：作为本票阻塞工单的实现已完成并关闭；本记录只负责 Issue #120 对应的 `v0.26.0-preview.1` 目标机验收
- 当前记录状态：`manual-pending`
- 候选标识：待构建时由 `prepare_v0260_preview1_delivery.py` 写入
- 归档文件：待构建时由构建脚本写入
- 归档 SHA-256：待构建时由构建脚本写入

本记录只保存脱敏摘要。目标机原始命令输出、截图、配置内容、API Key、用户正文和运行数据不得写入仓库。

## 首次 Preview 安装边界

| 项目 | 预期结果 | 现场证据（脱敏） |
| --- | --- | --- |
| 默认安装根 | `$TARGET_HOME/ai-wps` |  |
| 管理路径边界 | 安装根、状态、备份、运行变量及 WPS 插件目录均位于 `$TARGET_HOME` 下，且不通过符号链接绕过边界 |  |
| 安装入口 | `installer/install_ai_wps.sh` |  |
| 旧 Phase1 检测 | 只读检测 `$TARGET_HOME/ai-wps-phase1` 并提示人工重新安装、重新配置 |  |
| 旧配置/API Key/运行数据 | 不读取、不导入、不搬迁、不覆盖、不删除 |  |
| 新 Preview 状态 | 使用独立新根初始化，不把旧状态当作已迁移 |  |
| 既有 Phase1 交付路径 | 源码仓库路径继续可用 |  |

## 交付闭包

- 显式白名单组装：`release-allowlist.json`
- 完整文件哈希：`release-file-hashes.json`
- 版本、候选状态和基线：`release-manifest.json`
- 通用交付审计：`scripts/audit_delivery.py`
- Preview 身份审计：`scripts/audit_v0260_preview1_delivery.py`
- Python 3.8 运行门禁：`scripts/python38_delivery_runtime_gate.py`
- 发布生命周期门禁：`scripts/python38_delivery_lifecycle_gate.py`
- 现有三宿主与九类任务行为：Word、Excel、PPT 基线加 Excel“智能填写”，并由独立任务配置隔离

## Excel“智能填写”目标机验收

| 项目 | 预期结果 | 现场证据（脱敏） |
| --- | --- | --- |
| Ribbon 入口 | Excel 只显示“智能分析”“公式助手”“智能填写”和“设置” |  |
| 目标范围 | 同一工作表的单个单元格或单列连续区域，最多 500 项；非连续、跨列、跨表、隐藏、合并、受保护或公式目标拒绝 |  |
| 预览协议 | 结果严格按 `excel.smart_fill.v2` 展示，可逐项编辑、排除和重试 |  |
| 写入门禁 | 写回前重新校验工作簿/工作表/来源快照及目标原值；普通文本/数值需要二次确认；`= + - @` 前缀按文本保护；公式、合并、保护单元格始终拒绝 |  |
| 写回边界 | 仅写入用户选中的完成项，不提供撤销，不创建历史文件，失败时执行写入失败补偿并报告准确地址 |  |
| 任务恢复 | 慢模型持续轮询；运行中取消显示部分预览，任务总时限 60 分钟，结果仅进程内保留 |  |
| 数据边界 | 模型请求不含地址、工作簿标识、公式、隐藏值和未授权工作表内容 |  |

## 验收结论规则

- `manual-pending`：尚未完成全部目标机和安装边界验证。
- `passed`：所有必测项目均有现场证据，且没有失败、阻塞或未验证项。
- `failed`：发现旧目录被修改、运行数据被自动导入/删除、Preview 身份泄漏，或交付闭包不完整。

自动化构建与静态审计通过只能记录 `candidate`，不能将本记录写成 `passed` 或 `target-accepted`。
