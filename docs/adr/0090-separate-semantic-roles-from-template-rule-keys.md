# 将格式语义角色与模板规则键分离

决定新格式审查不再把 `heading1`、`list2_plain` 等模板规则键同时当作语义角色，而使用稳定的角色类型加独立属性：`document_title`、`heading(level)`、`body`、`list_item(level, ordered)`、`note(numbered)`、`caption(figure|table)`、`toc_title`、`toc_entry(level)`、`appendix_title`、`appendix_heading(level)`、`formula` 和 `unknown`。格式规则包声明各模板允许的属性范围并将组合映射到具体规则键；位于表格单元格内的 `table_body` 由结构事实确定，不进入模型角色分类。模型只能从候选随请求下发的有限组合中选择，不能创造角色；返回未知、低于 `0.85` 或与确定性证据冲突时保持需要确认，可靠角色没有模板映射时标记未配置格式规则而不回退正文。该结构增加一次规则映射，但避免识别算法被当前模板命名锁定，并允许未来规则包扩展层级而不修改稳定语义契约。
