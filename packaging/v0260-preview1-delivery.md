# AI-WPS v0.26.0-preview.1

这是 AI-WPS 的首个 Preview 交付骨架。它使用中性产品身份和一次性安装基线，不把历史 Phase1 目录或发布标识当作当前产品身份。

## 交付身份

- 产品版本：`v0.26.0-preview.1`
- 产品通道：`preview`
- 归档命名：`ai-wps-delivery-<YYYYMMDD>-<SOURCE_COMMIT>-v0260-preview1.tar.gz`
- 默认安装根：`$TARGET_HOME/ai-wps`
- 管理路径边界：安装根、共享状态、备份、运行变量及 WPS 插件目录必须位于 `$TARGET_HOME` 下，且不接受符号链接路径组件
- 安装入口：`installer/install_ai_wps.sh`
- 冒烟入口：`scripts/ai_wps_smoke_test.sh`
- 交付状态：自动化门禁只能记录 `candidate`
- 目标机状态：首次 Preview 验收前保持 `manual-pending`
- Issue #119：作为本票阻塞工单的实现范围已完成并关闭；本版本目标机验收记录绑定 Issue #120，仍未完成

`release-manifest.json`、`release-allowlist.json` 和 `release-file-hashes.json` 是同一候选的身份、白名单和完整性边界。发布脚本只从显式白名单组装文件，不把仓库测试、缓存、历史归档或运行数据带入交付包。

## 从历史安装进入 Preview

首次安装会只读检测 `$TARGET_HOME/ai-wps-phase1`。检测到旧目录时，安装器会输出人工重新安装和重新配置提示；它不会读取、导入、搬迁、覆盖或删除旧目录中的配置、API Key、规范库、备份和运行数据。旧目录由管理员按现场迁移方案另行保留或处置。

Preview 的默认安装根、脚本名、release ID 和成功标记均使用 `ai-wps` / `AI-WPS` 中性身份。现有 Phase1 交付路径继续保留在源码仓库中，供已部署环境维护和历史追溯；本包不执行破坏性全库重命名。

## 安装与验证

```bash
bash installer/install_ai_wps.sh
bash scripts/ai_wps_smoke_test.sh
```

安装器复用经过验证的私有 Python 运行时、候选预检、事务式发布和生命周期组件。Preview 首次安装以空状态初始化；从 `v0.26.0-preview.1` 起的后续兼容升级必须保留配置和运行数据，并由单独的兼容升级合同约束。

自动化构建会执行白名单组装、版本和引用闭包审计、敏感值扫描、文件 SHA-256 清单、Python 3.8 兼容性检查、正式插件契约测试及最终归档生命周期门禁。自动化通过不等于麒麟 V10/WPS 目标机已经验收。

## Scope

This package keeps the existing Word, Excel, and PPT behavior unchanged while establishing the neutral Preview delivery boundary and adding Excel Smart Fill as the ninth independently configured task. Smart Fill is limited to one contiguous single-column target, uses synthetic-data validation, and requires preview confirmation before guarded write-back. The `v0.26.0-preview.1` baseline is a one-time manual reinstall and reconfiguration boundary. It does not automatically migrate or delete the legacy `ai-wps-phase1` installation.
