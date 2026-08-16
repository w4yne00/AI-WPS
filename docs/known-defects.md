# 已知缺陷

本文件记录已经确认复现、但有意不在当前变更中修复的缺陷。每条缺陷保留复现方式和判定依据，供后续接手的人独立修复和验收。

---

## D-0001｜本地文档抽取的标题识别对 styleId 型文档完全失效

- **优先级**：最高
- **状态**：待修复（有意保留，留给后续接手人）
- **位置**：`adapter_service/app/services/ppt/document_text_extractor.py`，`_paragraph_text()`
- **影响范围**：一切依赖本地文档抽取的任务。当前为 PPT 文档总结；素材编排落地后同样受影响。

### 现象

抽取结果中标题层级全部丢失，正文与标题被压平为同级文本。

### 根因

`_paragraph_text()` 取 `w:pStyle/@w:val` 后直接用于标题正则：

```python
style_value = str(style.attrib.get("{0}val".format(_W), ""))
heading_match = re.search(r"(?:Heading|标题)\s*([1-6])", style_value, re.IGNORECASE)
```

`w:pStyle/@w:val` 是 **styleId**，不是样式名。样式名存放于 `word/styles.xml` 的 `w:style/w:name/@w:val`，而抽取器从不读取该部件。在 Word 生成的大量文档中 styleId 为纯数字，正则必然不匹配。

### 复现

以仓库内 `templates/company/technical-file-format-requirements.docx` 为输入调用 `extract_staged_document_text()`：

- 抽取字符数 5158，表格行正常输出；
- 以 `#` 开头的标题行数为 **0**。

该文档的实际映射为 styleId `2` → 样式名 `heading 1`、`3` → `heading 2`、`4` → `heading 3`，另有 styleId `22` → `文档标题` 且携带 `w:outlineLvl=0`。

### 修复方向（已验证有效，供参考）

1. 解析 `word/styles.xml`，建立 `styleId → 样式名` 映射，用**样式名**参与标题匹配；
2. 样式名无法判定层级时，回退读取 `w:pPr/w:outlineLvl`，层级取其值加一。

按此方向验证，同一文档的标题识别数由 **0 提升至 29**，且首层结构与文档实际章节一致。

### 备注

修复不改变对外接口与结果契约，可独立提交与独立验收，不必与素材编排功能绑定。相关背景见 ADR-0116。
