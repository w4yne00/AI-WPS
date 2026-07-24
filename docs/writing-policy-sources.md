# 写作规范预置包来源与审阅

AI-WPS 的预置规范包是只读、版本化的发布资源。组织数据库不能直接修改预置 JSON；默认启用条目必须先通过人工审阅门禁。

## G企技术写作基础

- 上游：`yangqi-tech-writing`
- 标签：`v1.1.0`
- 提交：`d3640165569071251248a5fafb2def6ef2fe2cf4`
- 许可证：MIT
- 固定读取方式：`git show v1.1.0:SKILL.md`

候选生成器不得读取上游仓库的工作树文件。运行前会确认标签解析到上述完整提交；提交不一致时立即停止。

```bash
PYTHONPATH=adapter_service python3 \
  adapter_service/tools/build_writing_policy_candidates.py \
  --repository /path/to/guoqi-write-style \
  --output /safe/review/path/yangqi-tech-writing-base-v1.0.0
```

命令生成同列的 CSV 与 XLSX 规范审阅清单。所有“审阅决定”单元格保持为空，生成器不具备自动批准能力。

## 人工门禁

审阅人逐条填写“通过”或“拒绝”，并检查：

1. 稳定 ID 是否唯一且能长期复用。
2. 内容是否属于短文本写作核心，没有引入事实核验、法律适用性或作者身份判断。
3. 来源、标签、完整提交、定位和许可证是否齐全。
4. 是否存在重复、近似重复或互斥要求。
5. 规则是否保持事实、数字、责任主体、条款和规范性强度。

只有“通过”的条目可以写入 `adapter_service/writing_policy_packs/*.json` 且设置 `defaultEnabled: true`。发布包还必须携带独立的 `*.review.json`；每条决定记录最终条目规范化 JSON 的 SHA-256。加载器会逐项核对 ID、包版本、审阅人、审阅日期、人工决定和内容摘要，审批后改动正文或适用范围都会导致规范包拒绝加载。

草稿 CSV/XLSX 仅用于审阅，不进入正式交付包。

## 标准与第三方文本处理

G企基础包保留人工审阅清单中通过的 17 条短规则内容，上游 `yangqi-tech-writing` 采用 MIT 许可证并在交付包中完整归属。政府、行业或网络安全标准仍采用面向产品的原创归纳，不批量复制标准原文，并记录来源名称、版本或标准号；许可证说明和第三方归属随正式规范包发布。
