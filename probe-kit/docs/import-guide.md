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

3. 如果目标机使用本地 `jsaddons` 手工导入方式，请将插件目录命名为 `wps-probe-addon_1.0.0/` 再导入。
4. 导入目录中必须包含以下桥接文件，否则 Ribbon 可以显示但任务面板通常无法正常拉起：

```text
index.html
main.js
ribbon.js
ribbon.xml
taskpane.html
taskpane.js
```

5. 打开 WPS，进入探针插件任务面板。
6. 点击 `运行探针`，记录结果。
7. 根据 `docs/target-machine-validation-checklist.md` 完成逐项验证。
8. 使用 `scripts/collect_acceptance_record.sh` 生成验收记录模板并填写。

## 为什么不能只放 `manifest.xml + ribbon.xml + taskpane.html/js`

你现场这套麒麟版 WPS 手工导入机制更接近本地 `jsaddons` 宿主加载模式，而不是直接按开放平台文档里的最小目录去加载。

在这种模式下：

- Ribbon 事件需要通过 `ribbon.js` 提供 `OnAddinLoad` 和 `OnAction`
- 宿主通常从 `index.html -> main.js -> ribbon.js/taskpane.js` 这条链拉起插件
- 插件目录名通常要满足 `<插件名>_<版本号>`

因此如果只给 `manifest.xml + ribbon.xml + taskpane.html/js`，目录可能能被识别，但任务面板无法正常创建。

## 产出物

- `runtime-probe.txt`
- 插件任务面板截图
- 验收记录 Markdown 文件
