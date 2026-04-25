# 目标机验证清单

## A. 终端基础环境

- [ ] 目标机系统为麒麟 V10
- [ ] 目标机 CPU 架构符合预期 ARM / `aarch64`
- [ ] `python3 --version` 输出符合预期
- [ ] `wps` 二进制存在
- [ ] `wpp` 二进制存在
- [ ] `et` 二进制存在

## B. 探针包完整性

- [ ] 探针包已成功解压
- [ ] `wps-probe-addon/manifest.xml` 存在
- [ ] `wps-probe-addon/index.html` 存在
- [ ] `wps-probe-addon/main.js` 存在
- [ ] `wps-probe-addon/ribbon.js` 存在
- [ ] `wps-probe-addon/ribbon.xml` 存在
- [ ] `wps-probe-addon/taskpane.html` 存在
- [ ] `wps-probe-addon/taskpane.js` 存在
- [ ] 手工导入时目录名符合 `<插件名>_<版本号>`
- [ ] `scripts/probe_runtime.sh` 可执行

## C. Shell 探针结果

- [ ] 成功生成 `runtime-probe.txt`
- [ ] `machine` 字段符合预期
- [ ] `python3_path` 非 `missing`
- [ ] `python3_version` 非 `missing`
- [ ] `wps_path` 非 `missing`
- [ ] `adapter_health` 结果已记录

## D. WPS 插件导入与运行

- [ ] 成功手工导入探针插件
- [ ] WPS 中能看到探针入口
- [ ] 能正常打开任务面板
- [ ] 点击 `运行探针` 后能输出结果
- [ ] `WPS global` 为 `true`
- [ ] `Active document` 为 `true`
- [ ] 在有选区时 `Selection available` 为 `true`
- [ ] `Paragraph count` 大于 `0`

## E. localhost 通信

- [ ] 若适配层已启动，`Adapter reachable` 为 `true`
- [ ] 若适配层未启动，任务面板能显示明确错误而非崩溃

## F. 结论

- [ ] 本机满足后续一期插件联调前置条件
- [ ] 已形成验收记录
- [ ] 已保留运行截图与输出文件
