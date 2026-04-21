# 导入说明

## 目标

将探针包手工导入内网目标机，用于验证麒麟 V10 ARM + WPS 插件运行时环境。

## 包内依赖

本探针包默认不依赖 `npm`、`vite`、`pytest` 或外网下载。

- WPS 插件部分：纯静态 `HTML + JavaScript + XML`
- 终端探针部分：`bash` 脚本
- 可选依赖：`curl` 用于检查 `127.0.0.1:18100/health`

## 导入步骤

1. 将压缩包复制到内网目标机并解压。
2. 进入解压目录，先运行：

```bash
bash scripts/probe_runtime.sh ./runtime-probe.txt
```

3. 根据 WPS 插件导入方式，手工导入 `wps-probe-addon/`。
4. 打开 WPS，进入探针插件任务面板。
5. 点击 `运行探针`，记录结果。
6. 根据 `docs/target-machine-validation-checklist.md` 完成逐项验证。
7. 使用 `scripts/collect_acceptance_record.sh` 生成验收记录模板并填写。

## 产出物

- `runtime-probe.txt`
- 插件任务面板截图
- 验收记录 Markdown 文件
