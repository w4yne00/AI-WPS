# 三宿主：支持手填默认模型及功能模型设计规范

## 1. 意图与背景 (Intent and The Why)

在当前的 AI-WPS 体系中，Word、PPT 和 Excel 三个宿主已实现了通过共享直连服务调用模型。此前实现存在两个局限：
1. **目录强耦合与不可用拦截**：此前当服务模型目录可用时，后端和插件强制禁止使用手填高级模型（`DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED`），或者在目录不可访问时要求必须先完成一次真实测试调用才能设为当前模型；
2. **手填模型单一且无历史沉淀**：用户手填模型 ID 后，无法持久沉淀为可选列表，若切换至其他模型或需在多个常用私有/微调模型间切换，需频繁重复手动输入，且无法直观管理已录入的模型。

本功能旨在彻底解除模型目录与测试调用的硬性门禁，在三宿主中支持自由录入、记录多个手填模型形成历史列表，并提供遵循 Apple Design 风格的手填模型管理面板，实现即时添加、单项删除与无障碍任务执行。

---

## 2. 目标与非目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **三宿主对等**：Word、Excel、PPT 三宿主设置页中的共享直连服务“默认模型”以及各具体功能的“任务模型”均全面支持列表选择和手填模型。
2. **手填模型历史沉淀与管理**：用户手填的模型 ID 将持久化保存在该直连服务的 `customModels` 列表中。提供独立的手填模型管理面板，支持查看已有手填模型、即时添加新模型以及即时单项删除模型。
3. **解除目录与测试调用阻断**：
   - 无论目录是否已获取、不可用、权限错误或完全可用，用户均可自由选择手填或从历史手填中选取；
   - 保存手填模型不强制触发测试调用，未经测试的模型标识为未验证，但不阻断实际任务调用；
   - 目录刷新不覆盖或清空用户手填的模型，目录重新可用后也不禁用手填模型。
4. **Apple Design 视觉与交互风格**：
   - 管理面板遵循 Apple Design（WWDC Fluid Interfaces / Inset Grouped / Capsule 规范）：
     - 半透明毛玻璃层次（`backdrop-filter` 柔和模糊与次级表面）、精致圆角（10–12px）与微阴影；
     - 操作响应灵敏（`:active` 带来 `scale(0.96)` 微物理反馈）；
     - 列表项与删除按钮简洁克制，悬浮高亮与无障碍交互；
     - 展开/收起过渡顺滑自然。
5. **协议与运行时对等**：FastAPI 与 Standalone 双运行时行为严格一致，同步更新 ADR-0128 规范。

### 非目标 (Non-Goals)
1. 不自动探测手填模型的上下文窗口与最大 Token 上限，继续沿用既有通用默认值或用户显式配置参数。
2. 不在保存配置时自动静默发送扣费的模型请求。
3. 不变更既有 API Key 凭据指纹与安全存储逻辑。

### 反目标 (Anti-Goals)
1. **严禁静默切换**：当测试或任务调用手填模型失败时，严禁静默回退到目录模型或默认模型，必须向用户准确返回真实报错原因。
2. **严禁悬空配置**：当用户删除正在生效的手填模型时，必须安全平滑回退（如回退至继承服务默认模型或空值），不得导致插件报错或崩溃。
3. **严禁阻断正常任务**：目录失效或验证状态过期不得作为任务执行的门禁。

---

## 3. 约束条件 (Constraints)

1. **环境与依赖**：
   - 后端必须严格兼容 Python 3.8（ARM64 Kylin V10 SP1 与通用 Linux/macOS）；
   - 前端必须兼容 WPS 内嵌 Chromium/CEF 内核，不引入额外重量级前端框架或动画库，使用原生 CSS 与轻量 DOM 操作实现 Apple Design 动效与质感；
   - 不修改运行态数据 `config/adapter.json` 或 `run/` 目录。
2. **测试与回归**：
   - 遵循 Test-Driven Development（TDD）规范，所有新增逻辑先编写失败测试再编写实现；
   - 保证 Kylin V10 上 Python 全量 pytest 与插件 Node 契约测试全量通过；
   - 构建 `packaging/build_v0251_delivery_kit.sh` 及 Python 3.8 兼容性检查必须通过。

---

## 4. 用户交互与界面设计 (UI & Interaction Decided by User)

### 4.1 下拉框与管理面板展开机制
- 在直连服务的“默认模型”下拉框以及任务设置的“任务模型”下拉框中：
  - 第一部分：固有选项（如“继承服务默认模型”或“不设置默认模型”）；
  - 第二部分：服务目录模型列表（若目录可用）；
  - 第三部分：历史手填模型列表（若存在已有手填模型）；
  - 第四部分：固定选项「输入 / 管理手填模型」（值约定为 `__manual__`）。
- 当用户在下拉框中选择「输入 / 管理手填模型」时：
  - 下拉框下方顺畅展开独立的“手填模型管理面板”；
  - 面板保持展开，允许用户添加新模型或管理已有列表。
- 当用户在下拉框中切回其他已有模型（目录模型、已存手填模型或继承默认）时，管理面板自动平滑收起。

### 4.2 手填模型管理面板布局 (Apple Design 规范)
管理面板嵌入在模型选择器正下方，设计语言：
1. **容器卡片 (Container)**：
   - 采用 Inset Grouped 风格：浅色模式下 `background: rgba(0, 0, 0, 0.03)`，细边框 `1px solid rgba(0, 0, 0, 0.08)`，圆角 `10px`，内边距 `10px 12px`；
   - 支持平滑展开/折叠过渡。
2. **添加输入区 (Add Input Row)**：
   - 包含一个文本输入框（placeholder: "输入模型 ID，例如 deepseek-chat"）和一个轻量「添加」按钮；
   - 用户输入模型 ID 点击「添加」后：
     - 若模型 ID 校验合法且不重复，**立即调用后端专用接口**追加记录至该服务的 `customModels` 列表中；
     - **保留在面板中**，供用户继续添加其他模型或进行选择；
     - 输入框清空并重新获得焦点，新添加的模型即刻出现在下方列表中，外层下拉框中的手填分组也即时同步刷新。
3. **已存模型列表与单项删除 (Saved List & Actions)**：
   - 列表展示当前服务下所有已保存的手填模型；
   - 每一项为一个胶囊条目（Pill Item），左侧展示模型名称，点击条目可直接设为当前选用模型；
   - 条目右侧提供一个精致的删除按钮（圆形小叉或垃圾桶图标）：
     - 悬浮时呈现微红警示色彩；
     - 点击按压时提供 `:active { transform: scale(0.96); }` 瞬时反馈；
     - 点击后**立即调用后端专用接口**将该模型从 `customModels` 清单中移除；
     - **平滑重置**：若被删除的模型正好是当前服务的默认模型或某个任务的当前选中模型，系统在后端与前端自动安全重置为“继承服务默认模型”（任务）或“不设置默认模型”（服务），不阻断删除，并即时更新界面展示与下拉框选中态。
4. **测试调用与保存按钮**：
   - 直连服务卡片沿用现有的“验证服务”连通性测试；
   - 任务设置参数区保留独立「验证调用」按钮，明确标注“验证调用会真实请求模型，可能产生费用”；
   - 点击「保存并设为当前」时，直接保存当前选定模型（无论是否经过测试），未经测试的不打上已验证标记，但即刻可用于后续任务。

---

## 5. 数据与后端协议设计 (Data & Backend Contracts)

### 5.1 共享服务配置数据结构扩展
在每个直连服务对象（`DirectServiceConfig`）中增加字段：
```json
{
  "id": "direct_svc_1",
  "name": "DeepSeek 官方",
  "serviceBaseUrl": "https://api.deepseek.com/v1",
  "defaultModel": "deepseek-chat",
  "customModels": ["deepseek-chat", "deepseek-coder", "custom-v1"],
  "modelCatalog": { ... }
}
```
- `customModels: List[str]`：按录入顺序保存该服务下的手填模型列表（去重、去除首尾空格）。缺失该字段时默认为空列表 `[]`。

### 5.2 后端 API 与服务层调整
1. **即时增删手填模型轻量端点 (FastAPI & Standalone)**：
   - `POST /provider/direct-services/{service_id}/custom-models`：
     - 请求体：`{"modelName": "custom-model-id"}`；
     - 行为：校验模型名非空有效后，将模型增量追加至该服务的 `customModels`，返回更新后的服务概要及模型列表。
   - `DELETE /provider/direct-services/{service_id}/custom-models/{model_name}`：
     - 模型 ID 可含斜杠，前端编码后传入；支持可选查询参数 `expectedRevision`，三宿主删除时传入已加载的服务版本，过期版本返回 409 且不修改配置；未传参数的旧调用保持兼容。
     - 行为：从 `customModels` 移除指定模型；
     - **平滑重置级联**：若该服务的 `defaultModel == model_name`，自动将其清空为 `""`；同时扫描所有引用了 `(service_id, model_name)` 且 `customModel == True` 的 `taskModelSelections`，平滑重置其 `modelName = ""`、`customModel = False`、`customModelValidated = False`；返回更新后的状态。
     - 清空默认模型时递增服务版本，成功响应返回最新版本；当前操作的编辑器同步该版本，其他宿主的旧编辑器继续受现有版本冲突保护。
2. **解除目录与手填互斥限制**：
   - 移除 `DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED` 阻断逻辑：无论 `catalog.get("usableForSelection")` 为 True 还是 False，均允许保存和选用手填模型；
   - 移除 `DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED` 在保存配置或发起常规任务时的阻断限制：未测试模型可以正常设为当前配置并执行任务。
3. **保存任务选择时自动增量沉淀**：
   - 在 `PUT /provider/task-model-selections/{task_type}` 中，若 `customModel: true` 且提供了有效 `modelName`，后端在保存任务模型选择的同时，自动将该 `modelName` 去重追加至所属服务的 `customModels` 中，确保多宿主并发录入时平滑沉淀。
4. **验证与调用行为**：
   - 「验证调用」接口保持独立运作，仅在显式点击时触发，调用成功后在配置中标记 `customModelValidated = True`；
   - 任务执行器（`ProviderClient`）读取配置中的真实 `modelName` 发起真实请求，服务失败时如实抛出错误并透传状态码与错误信息。

---

## 6. ADR-0128 更新

在 `docs/adr/0128-share-direct-model-services-across-hosts.md` 中同步修订以下内容：
- 修改原有“手填值只有在验证调用成功后才能视为已验证可用并设为当前”的表述；
- 明确：**手填入口始终可用，不依赖目录可用性，不强制要求先完成测试调用即可保存并用于任务；服务维护手填模型历史列表并支持即时增删与平滑重置，测试调用独立发起且未经测试不标记为已验证，但不阻断任务执行。**

---

## 7. 留给实现工程师的细节 (Left to the Builder)

1. **三宿主 Taskpane HTML 结构与命名规范**：在 Word、Excel、PPT 三宿主现有 `taskpane.html` 中保持 class 命名风格一致（如 `.custom-models-panel`、`.custom-model-chip`、`.btn-delete-custom-model` 等）。
2. **CSS 动效细节**：根据 `apple-design` 规范配置微过渡曲线与 `:active` 缩放，保证在低性能内嵌浏览器中也有轻盈无卡顿的视觉质感。
3. **向后兼容**：旧版本未包含 `customModels` 字段的 `adapter.json` 或历史草稿数据自动平滑迁移为空数组，旧 `customModel: true` 配置自动纳入 `customModels` 列表中。
