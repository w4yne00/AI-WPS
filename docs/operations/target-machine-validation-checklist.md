# 目标机验证清单

来源文件建议使用手工导入包中的：

- `docs/target-machine-validation-checklist.md`
- `docs/acceptance-record-template.md`

如果你在当前仓库直接查看，这份清单与手工导入包保持一致。

## 核心检查项

- [ ] 目标机为麒麟 V10
- [ ] 架构为预期 ARM / `aarch64`
- [ ] WPS 二进制存在
- [ ] Python 版本符合预期
- [ ] 探针插件可导入
- [ ] 任务面板可打开
- [ ] `Runtime Probe` 可返回结果
- [ ] localhost 适配层连通性结果已记录
- [ ] 已生成验收记录
