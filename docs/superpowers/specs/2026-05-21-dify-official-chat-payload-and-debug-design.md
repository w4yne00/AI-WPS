# v0.11.4-alpha Dify Official Chat Payload and Debug Design

## Background

Target-machine testing still indicates that WPS task-pane prompts are not reaching the Dify LLM node correctly. The latest screenshot shows the Dify Start node has both:

- a custom input variable named `query`;
- the system variable `sys.query`.

Dify official Chat Messages API documentation defines the request body for `POST /chat-messages` as `query`, `inputs`, `user`, `response_mode`, `conversation_id`, and `files`. The `inputs` object carries app-defined variables, while top-level `query` carries the user question.

Therefore, to support both Start-node variable shapes safely, the adapter must send the complete prompt in two places:

```json
{
  "inputs": {
    "query": "完整中文任务提示词..."
  },
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

## Goal

Make WPS task-pane options and selected text reach the Dify LLM node whether the workflow references custom `query` or system `sys.query`.

## Runtime Contract

Endpoint:

```text
POST {providerBaseUrl}/chat-messages
```

Body:

```json
{
  "inputs": {
    "query": "完整中文任务提示词..."
  },
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

No `input_data` and no `mode` in request body.

## Debug Contract

Add a local adapter diagnostic endpoint:

```text
GET /provider/debug-last
```

It returns the last provider call with sensitive values removed:

- URL path and task type.
- Request body keys.
- `inputs` keys.
- Query length and short query preview.
- Response keys and answer length when available.
- HTTP status or error type/message.
- Trace ID.

The endpoint must never return API keys or full prompt text.

## Acceptance Criteria

1. Payload helper returns top-level `query` and `inputs.query` with the same complete prompt.
2. Payload helper returns `response_mode`, not `mode`.
3. Payload helper returns no `input_data`.
4. Smart Write still passes an empty internal `input_data` argument to `post_task`; task details are embedded in prompt text.
5. `/provider/debug-last` reports sanitized request/response metadata after a provider call or provider error.
6. Version is `0.11.4-alpha`.
