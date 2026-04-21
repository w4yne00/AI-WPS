#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_FILE="${1:-$KIT_ROOT/acceptance-record-$(date '+%Y%m%d-%H%M%S').md}"

cat > "$OUT_FILE" <<'EOF'
# 目标机验收记录

## 基本信息

- 验证日期：
- 验证人员：
- 终端编号：
- 操作系统版本：
- CPU 架构：
- WPS 版本：

## Shell 探针结果

- 运行命令：
- 输出文件路径：
- `machine`：
- `python3_version`：
- `wps_path`：
- `wpp_path`：
- `et_path`：
- `adapter_health`：

## WPS 插件探针结果

- 是否成功导入插件：
- 是否能打开任务面板：
- `WPS global`：
- `Active document`：
- `Selection available`：
- `Paragraph count`：
- `Heading count`：
- `Adapter reachable`：
- `Adapter detail`：

## 结论

- 是否通过：
- 阻塞项：
- 需要跟进的问题：

EOF

echo "Acceptance record template written to $OUT_FILE"
