# AI-WPS 工作流配置档案设计

## 1. 背景与目标

当前系统为每个任务类型保存一个 `apiKeyRef`。当 Dify 工作流发布新版本并生成新 API Key 后，前台保存新密钥会覆盖原引用；切回旧工作流时必须重新输入旧密钥。

本次改造引入“工作流配置档案”。用户可以为智能编写、智能仿写、文档审查、格式审查和 Excel 智能分析分别保存多个具名档案，并通过下拉菜单切换当前使用档案。切换只影响后续新任务，不修改任务请求、超时、结果解析、预览、复制或写回链路。

本版目标：

- 每个任务类型可保存多个“自定义名称 + API Key”档案。
- 功能页面可快速选择当前工作流档案。
- 设置页面可新增、重命名、更换密钥、启用和删除档案。
- 升级时保留已有 URL、统一 API Key、任务级 API Key 和当前选择。
- 兼容旧前端和旧配置格式。

本版不包含：

- 不为单个档案配置独立 API URL、请求路径或模型参数。
- 不实现跨五个任务的一键“方案组”切换。
- 不修改任何 Word 写回或 Excel 只读行为。

## 2. 任务范围与宿主隔离

工作流档案按现有任务类型严格隔离：

| 前台功能 | 任务类型 | 宿主 |
| --- | --- | --- |
| 智能编写 | `word.smart_write` | Word |
| 智能仿写 | `word.smart_imitation` | Word |
| 文档审查 | `word.document_review` | Word |
| 格式审查 | `word.format_review` | Word |
| Excel 智能分析 | `excel.analysis` | Excel |

Word 前端只加载四类 Word 档案，Excel 前端只加载 `excel.analysis` 档案。两个插件共享同一 adapter 档案存储，但不交叉显示入口或档案。

## 3. 数据模型

`config/adapter.json` 增加两个字段：

```json
{
  "workflowProfiles": {
    "profile_01JXYZ": {
      "taskType": "word.smart_write",
      "name": "智能编写稳定版",
      "apiKeyRef": "workflow_profile_01JXYZ",
      "note": "2026-07 正式版",
      "createdAt": "2026-07-10T10:00:00Z",
      "updatedAt": "2026-07-10T10:00:00Z"
    }
  },
  "activeWorkflowProfiles": {
    "word.smart_write": "profile_01JXYZ"
  }
}
```

设计约束：

- `profileId` 和 `apiKeyRef` 由 adapter 生成，与用户名称无关。
- API Key 正文继续存入 `run/provider_api_keys/` 独立文件；配置 JSON 只保存引用。
- 同一任务类型内，档案名称去除首尾空格后不允许重复，比较时忽略大小写。
- 名称长度为 1 至 40 个字符，备注最多 200 个字符，每个任务最多保存 20 个档案。
- 档案不能变更所属任务类型。
- GET 接口和诊断信息永不返回 API Key 正文。

## 4. 兼容与迁移

现有 `taskApiKeyRefs` 保留，作为旧配置和旧前端兼容层。

首次读取某个任务档案时，如果该任务没有档案，但 `taskApiKeyRefs` 中存在引用，则 adapter 自动创建一个名为“当前配置”的档案，复用原 `apiKeyRef`，不移动或覆盖密钥文件，并将其设为当前档案。

激活档案时，adapter 同时：

1. 更新 `activeWorkflowProfiles[taskType]`。
2. 将档案的 `apiKeyRef` 镜像写入 `taskApiKeyRefs[taskType]`。

因此旧版 adapter 或旧版前端仍可使用最后一次激活的密钥。原有 `POST /provider/task-api-key` 保留：如果任务已有当前档案，则替换当前档案的密钥；如果没有，则创建“当前配置”档案。原有清除接口只清除当前档案的密钥，不删除其他历史档案。

密钥解析顺序保持为：

1. 当前工作流档案对应的任务级密钥。
2. 旧 `taskApiKeyRefs` 对应的任务级密钥。
3. 统一 API Key。

## 5. Adapter 接口

新增接口：

```text
GET    /provider/workflow-profiles?taskType=word.smart_write
POST   /provider/workflow-profiles
PATCH  /provider/workflow-profiles/{profileId}
POST   /provider/workflow-profiles/{profileId}/api-key
POST   /provider/workflow-profiles/{profileId}/activate
DELETE /provider/workflow-profiles/{profileId}
```

创建请求：

```json
{
  "taskType": "word.smart_write",
  "name": "智能编写稳定版",
  "apiKey": "app-...",
  "note": "2026-07 正式版",
  "activate": true
}
```

查询响应按任务返回档案列表、当前档案 ID、档案数量和每个档案的 `keyConfigured` 状态。响应不返回 `apiKeyRef` 之外的密钥信息。

接口行为：

- 创建档案时校验任务类型、名称唯一性、数量上限和非空 API Key。
- 更新档案只允许修改名称和备注；更换密钥使用独立接口，避免空密码误覆盖。
- 激活前校验档案属于目标任务且密钥文件存在。
- 当前档案不允许直接删除；用户必须先激活其他档案。
- 删除非当前档案时同时删除其独立密钥文件。
- 所有配置更新先在内存中完成校验，再一次写入配置文件，避免只更新一半。
- 所有校验失败返回中文可读错误和合适的 HTTP 4xx 状态。

## 6. 前台交互

### 6.1 功能页面快捷切换

每个功能页面在任务标题或主操作区上方显示紧凑选择器：

```text
当前工作流  [智能编写稳定版 ▼]  [切换]
```

下拉菜单只显示当前任务类型的已保存档案。选择档案后必须点击“切换”，避免误触立即生效。切换成功后显示：

> 已切换到“智能编写稳定版”，从下一次任务开始生效。

任务执行期间禁用切换按钮；已提交任务继续使用提交时已经解析的密钥，切换只影响下一次任务。

没有档案时显示“尚未配置工作流”，并提供进入设置页的入口。只有一个档案时仍显示其名称和当前状态，但不强迫用户重复配置。

### 6.2 设置页面集中管理

原“任务级 API Key”区域改为“工作流配置管理”。每个任务区域显示：

- 当前档案名称和配置状态。
- 当前任务的档案下拉菜单与“设为当前”按钮。
- “新增工作流”和“管理工作流”操作。

新增表单包含工作流名称、API Key、可选备注和“保存后设为当前”复选框。管理列表显示名称、当前状态、密钥已配置状态和备注，提供“重命名”“更换密钥”“删除”操作。密码输入框保存后立即清空，界面不支持查看或复制已保存密钥。

Word 设置页只管理四类 Word 工作流，Excel 设置页只管理 Excel 智能分析工作流。

## 7. 任务执行与并发语义

Provider 调用在每次新任务开始发送模型请求前解析一次当前 `apiKeyRef` 和密钥。HTTP 请求发出后，用户切换档案不会影响该请求。

文档审查和 Excel 智能分析的后台 job 保持现有 `clientJobId` 幂等及轮询机制。档案切换不得清理 jobId、重新提交后台任务或改变超时预算。

## 8. 安全、诊断与安装升级

- 新密钥文件继续使用现有独立目录，并确保仅当前用户可读写。
- 日志、接口响应和最近一次任务诊断不得包含密钥正文。
- `/provider/debug-last` 增加脱敏字段 `workflowProfileId` 和 `workflowProfileName`，保留现有 `taskApiKeyRef` 与 `taskAuthSource`。
- 安装包继续备份和恢复 `config/adapter.json`、`run/provider_api_key` 和整个 `run/provider_api_keys/` 目录，因此档案元数据、API URL 和所有历史密钥均可保留。
- 档案名称只用于显示和诊断，不参与文件路径拼接。

## 9. 错误处理

- 当前档案密钥缺失：拒绝激活，并提示“该工作流尚未配置 API Key”。
- 档案名称重复：保留用户输入，提示更换名称。
- 删除当前档案：拒绝删除，并提示先切换其他档案。
- 档案列表加载失败：功能执行仍沿用 adapter 当前已激活密钥，前端只禁用档案管理和切换，不影响已有任务按钮。
- 切换请求失败：下拉菜单恢复到 adapter 返回的当前档案，不在前端伪造成功状态。
- 配置文件存在无效档案：忽略无效项并保留其他有效档案，诊断中返回脱敏告警。

## 10. 测试与验收

Adapter 自动测试覆盖：

- 从旧 `taskApiKeyRefs` 自动迁移且复用原密钥文件。
- 新增、重命名、更换密钥、激活和删除档案。
- 同任务名称唯一、数量上限、任务归属、当前档案删除保护。
- 激活时同步更新 `activeWorkflowProfiles` 与 `taskApiKeyRefs`。
- 当前档案密钥、旧任务密钥和统一密钥的回退顺序。
- API 和诊断响应不泄露密钥正文。
- 原任务级 API Key 接口继续兼容。

前端自动测试覆盖：

- Word 只渲染四类 Word 档案，Excel 只渲染 Excel 档案。
- 下拉选择不会自动切换，点击确认后才调用激活接口。
- 新增、编辑、更换密钥、删除和错误状态渲染。
- 没有档案、加载失败、密钥缺失和当前档案状态。
- 文档审查、Excel 长任务轮询以及智能编写写回函数保持原有契约。

目标机验收：

1. 为每个模块保存两个不同名称和不同密钥的档案。
2. 分别切换并执行任务，通过诊断确认命中所选档案。
3. 重启 adapter 和 WPS 后，档案及当前选择保持不变。
4. 安装新版覆盖包后，API URL、统一密钥、所有档案和当前选择不丢失。
5. Word 和 Excel 不交叉显示对方的工作流配置。

## 11. 后续扩展

在独立档案功能稳定后，可另行设计“工作流方案组”，将五个任务的当前档案组合成生产、测试或历史版本并一键切换。该能力不纳入本次实现，避免把不同任务的发布节奏强制绑定。
