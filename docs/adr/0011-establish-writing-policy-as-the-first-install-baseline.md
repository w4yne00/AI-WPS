# 写作规范库建立首次正式安装基线

---
status: accepted
---

本版本视为写作规范库的首次正式安装版本，统一使用 `writing_policy` 领域名称、`/writing-policies/*` 接口和 `run/writing_policies.db` 数据库，不保留 `/enterprise-knowledge/*` 或旧数据库迁移逻辑。从该版本起，覆盖安装必须保留数据库及备份，schema 变更必须先备份并采用非破坏性迁移；预置规范包更新不得覆盖组织覆盖、组织自定义规范或预置停用状态。该选择避免长期保留首次正式使用前的旧命名，代价是开发阶段旧接口和数据不再兼容。
