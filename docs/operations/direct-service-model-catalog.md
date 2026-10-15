# 直连服务模型目录契约

共享直连服务保存后，Adapter 在存在 API Key 时自动请求 `<serviceBaseUrl>/models`；用户也可以通过 `POST /provider/direct-services/{serviceId}/refresh-models` 手动刷新。服务地址或 API Key 变更会触发同一刷新流程。刷新只读取模型目录，不执行任务调用。

## 缓存状态

每次成功读取保存 `modelListFetchedAt`，并返回 `modelListExpiresAt` 作为上次成功获取时间。服务详情中的 `modelCatalog` 只描述列表辅助选择的状态，不参与已保存模型的任务就绪判定：

- `available` / `valid`：有模型目录，可从目录辅助选择模型。
- `available` / `valid` + `fetchStatus=error`：本次刷新失败，但仍保留最近一次目录；错误通过 `lastError` 返回。
- `expired` / `expired`：目录超过 24 小时未成功刷新。列表仅供参考，已保存模型仍可发起任务。
- `unavailable`、`empty` 或 `invalidated`：当前没有可用于辅助选择的目录。已保存的服务、凭据、模型 ID 和参数保持不变，任务按这些值发起真实调用。

地址或 Key 变化时，旧目录保留用于诊断和恢复，但标记为 `invalidated`，在新目录成功刷新前不得用于新任务。任何刷新失败都不会覆盖最近一次成功的 `modelList`。

`POST /provider/direct-services/{serviceId}/models` 仅保留为兼容性写入接口。客户端提交的列表标记为 `untrusted`，不会成为可选模型目录；权威目录只能来自服务端 `<serviceBaseUrl>/models` 的成功响应。目录响应最多读取 1 MiB、包含不超过 1000 个模型，单个模型标识不超过 160 个字符。

刷新请求会固定开始时的服务配置版本。请求期间发生地址或 Key 变更时，旧响应被丢弃，不得回写到新配置。

## 验证边界

`POST /provider/direct-services/{serviceId}/validate` 只验证 URL、认证和目录读取。目录接口返回 404/405 时，只能判定服务可达，不能证明 API Key 已通过认证；响应会返回 `authenticated=null`、`authenticationVerified=false`，并标记目录不可用。该响应不会执行任务调用，也不产生模型费用；系统不会为了补验认证而隐式发起可能计费的任务调用。

`POST /provider/task-model-selections/{taskType}/validate` 使用目标任务的真实提示词、输入和结果契约执行一次调用。响应明确返回 `taskCallPerformed`、`taskContractValidated`、`mayIncurModelCost` 和费用提示。任务验证失败不会改变当前选择。

新配置可以从目录辅助选择模型，也可以保留已保存的模型 ID。不得把不在目录中的模型静默替换为其他模型。升级前已有的自定义模型记录仅保留读取兼容，不再通过三宿主设置页新建或修改。已选模型从新目录消失、目录过期、目录刷新失败或目录因 URL/Key 变化而失效时，不清空配置，也不阻断新任务和激活请求；真实调用返回成功或服务端错误。

## 任务选择与激活

`POST /provider/direct-services/{serviceId}/activate` 可在 `taskType` 之外携带 `taskModelSelection`。Adapter 会先校验服务地址、凭据和任务参数，再用一次配置文件写入同时更新任务模型选择与 `activeModelConfigurations`；任一校验失败时两者都保持原值。目录状态不参与这次校验。未携带 `taskModelSelection` 的旧客户端仍沿用已保存的任务选择。

任务页切换共享服务时必须显式提交选择快照。仅从紧凑菜单切换服务时，前端提交空 `modelName` 和空任务参数，使新服务继承自己的默认模型，不能把上一服务的同名覆盖静默带入新服务。
