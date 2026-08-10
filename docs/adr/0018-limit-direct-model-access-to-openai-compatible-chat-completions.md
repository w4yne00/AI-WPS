# 直接模型接入首版仅支持 OpenAI-compatible Chat Completions

AI-WPS 在保留现有模型平台接入的同时增加直接模型接入。首版只兼容 OpenAI-compatible Chat Completions 的核心非流式文本协议，不接入 Anthropic 等厂商原生协议，也不提供用户自定义 JSON 请求模板；这样可以复用现有任务提示词和结果解析，仅把协议差异限制在 Adapter 的接入适配层，并避免把复杂且高风险的协议映射暴露到三宿主设置界面。

接入类型必须由配置明确指定，不能根据 URL 自动推断。后续如需增加厂商原生协议，应作为新的接入适配器单独设计和验收。
