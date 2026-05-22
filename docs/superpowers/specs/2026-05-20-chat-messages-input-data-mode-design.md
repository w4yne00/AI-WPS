# v0.11.3-alpha Chat Messages input_data/mode Design

## Background

`v0.11.2-alpha` removed task-route selection and sent every AI task to one Dify Chat/Chatflow endpoint, `/chat-messages`, with the complete task prompt in top-level `query`. Target-machine testing still returned the original text unchanged.

The latest interface screenshots show the enterprise Dify-compatible `/chat-messages` request body uses these field names:

```json
{
  "input_data": {},
  "query": "用户输入/提问内容",
  "conversation_id": "",
  "mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

`v0.11.2-alpha` used `inputs` and `response_mode`. This version changes only the request envelope to match the target interface screenshots while preserving the single-query prompt strategy.

## Goal

Make the adapter call the simple Dify workflow as:

```text
Start node -> LLM node -> Reply node
```

The Start node keeps only Dify system default parameters. WPS task-pane selections, style options, focus options, length options, selected text, and custom user requirements are merged by the adapter into one complete Chinese prompt and sent as top-level `query`.

## Runtime Contract

Endpoint:

```text
POST {providerBaseUrl}/chat-messages
```

Headers:

```text
Authorization: Bearer <unified-api-key>
Content-Type: application/json
X-Trace-Id: <trace-id>
```

Body:

```json
{
  "input_data": {},
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

Rejected fields for this version:

- No `inputs`.
- No `response_mode`.
- No custom Start variables such as `source_text`, `write_action`, `style`, `focus`, `length`, `user_prompt`, or `selection_mode`.
- No per-task route path or per-task API key selection.

## Adapter Behavior

- `build_provider_request_payload()` returns the target `input_data` / `mode` envelope.
- `build_route_request_payload()` remains as a compatibility helper but returns the same unified envelope.
- `ProviderClient.post_task()` always posts to `providerBaseUrl + providerChatPath`, which defaults to `/chat-messages`.
- `ProviderClient.post_task()` ignores task-specific input data and logs only ignored key names plus query length.
- `extract_answer()` continues to read Dify Chat responses from `answer`, and nested workflow-style `data.outputs.result` remains tolerated for compatibility.

## Configuration

Default config remains:

```json
{
  "providerType": "enterprise-dify-chat",
  "providerChatPath": "/chat-messages",
  "providerMode": "blocking",
  "taskRoutes": {}
}
```

`providerMode` maps to request body field `mode`.

## UI Behavior

No task-pane workflow change is required:

- Settings page keeps one API URL and one unified API Key.
- Smart Write still uses one visible task pane and `/word/smart-write`.
- The adapter, not the frontend, builds the final prompt.

## Acceptance Criteria

1. Payload helper returns `input_data: {}`, top-level `query`, `conversation_id: ""`, `mode: "blocking"`, `user`, and `files`.
2. Payload helper does not return `inputs` or `response_mode`.
3. Smart Write sends no custom Start fields to `post_task`; all user selections are embedded in `query`.
4. `/provider/route-diagnostics` reports `payloadStyle=chat`, `path=/chat-messages`, and `routes={}`.
5. Delivery package contains `EXPECTED_VERSION=0.11.3-alpha` and the default config still targets `/chat-messages`.
