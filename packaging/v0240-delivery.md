# v0.24.0-alpha 交付候选门禁

使用 `packaging/build_v0240_delivery_kit.sh` 组装候选包。构建前必须通过
`AI_WPS_V0231_BASELINE_ARCHIVE` 提供已验收的 `v0.23.1-alpha` 归档；门禁会在
隔离目录执行真实升级，并注入切换中断确认整代际回退保持不变。

构建脚本还要求 `PYTHON38_BIN` 指向目标 Python 3.8。通过白名单、哈希、引用闭包、
敏感信息、目标依赖和生命周期检查后，归档只标记为 `candidate`，不代表麒麟 V10、
WPS 或 `cloud` 用户现场验收完成。
