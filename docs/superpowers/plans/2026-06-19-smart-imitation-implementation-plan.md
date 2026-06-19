# Smart Imitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Word "智能仿写" workflow that accepts a template, a required imitation requirement, optional reference material, and returns preview/copy-only generated text without writeback.

**Architecture:** Implement Smart Imitation as an additive workflow with a new Ribbon mode, new task-pane input section, new `/word/smart-imitation` route, new `word.smart_imitation` provider task type, and new Dify operations documentation. Reuse the existing Word task envelope, provider `/chat-messages` payload shape, safe result rendering, copy flow, diagnostics, and task-level API key mechanism, while explicitly disabling comparison and writeback for this mode.

**Tech Stack:** WPS native JS/HTML/CSS plugin, Python FastAPI adapter with standalone fallback, Pydantic request models, enterprise Dify-compatible `/chat-messages` provider integration, Node static smoke tests, Python `unittest`, existing bash packaging scripts.

---

## Scope Notes

- This plan implements `docs/superpowers/specs/2026-06-19-smart-imitation-design.md`.
- Current working tree contains unrelated v0.13.8 delivery changes and historical package noise. Do not revert them. Stage only files touched by each task.
- Keep Smart Write, Document Review, Format Review, and all existing writeback paths behaviorally unchanged.
- First Smart Imitation version is preview/copy only. Do not add "对照", "应用预览", selection replacement, insertion, or Word writeback.
- Target release version: `0.14.0-alpha`; rule number: `AI-WPS-P1-WORD-0.14.0-20260619`.

## File Structure

Create:

- `adapter_service/app/services/word/smart_imitator.py`: Smart Imitation service, validation, provider call, rewrite-shaped response.
- `adapter_service/tests/test_word_smart_imitation.py`: service-level tests for template extraction, provider call, and readable validation errors.
- `docs/operations/dify-smart-imitation-workflow.md`: operations guide for the new model workflow.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png`: Ribbon icon matching the current icon family.

Modify:

- `adapter_service/app/core/models.py`: add `imitationRequirement` and `imitationReferenceMaterial` request options.
- `adapter_service/app/services/provider_client.py`: add prompt builder, provider method, task key status entry, mock behavior, and route diagnostics entry.
- `adapter_service/app/api/word.py`: add `/word/smart-imitation` FastAPI route.
- `adapter_service/app/main.py`: map `/word/smart-imitation` validation errors to `word.smart_imitation`.
- `adapter_service/standalone_adapter.py`: add standalone route and helper for Smart Imitation.
- `config/adapter.example.json`: add `word.smart_imitation` default task API key ref.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`: add Ribbon button.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`: map button and icon.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`: add Smart Imitation input section and make result switch compatible with no-compare mode.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`: add `smartImitation` mode, state, selection-to-template read, validation, request, result rendering, and compare/writeback hiding.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`: style Smart Imitation fields consistently with the existing task pane.
- `formal-plugin-kit/tests/layout-smoke.test.js`: static assertions for UI, route, diagnostics, hidden comparison/writeback, and icon.
- `adapter_service/tests/test_enterprise_provider.py`: provider prompt, routing, and options tests.
- `adapter_service/tests/test_review_mode_contract.py`: task API key ordering and deleted route checks.
- `adapter_service/tests/test_packaging_scripts.py`: packaging assertions for new docs/icon/config.
- Version-bearing files: `README.md`, `docs/codex-handoff.md`, `adapter_service/app/api/health.py`, `adapter_service/app/main.py`, `adapter_service/app/services/provider_client.py`, `adapter_service/standalone_adapter.py`, `adapter-start-kit/scripts/start_uvicorn_adapter.sh`, `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`, `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`, `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`, and version-related tests.

## Task 1: Provider Contract And Prompt

**Files:**
- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`
- Test: `adapter_service/tests/test_review_mode_contract.py`

- [ ] **Step 1: Write failing provider and model tests**

Add `build_smart_imitation_prompt` to the provider-client imports in `adapter_service/tests/test_enterprise_provider.py`, then add these tests to `EnterpriseProviderTests`:

```python
def test_word_request_accepts_smart_imitation_options(self):
    request = WordDocumentRequest.parse_obj(
        {
            "documentId": "imitate.docx",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "模板段落。",
                "paragraphs": [],
                "headings": [],
            },
            "options": {
                "imitationRequirement": "仿写成安全整改通知。",
                "imitationReferenceMaterial": "整改对象：核心系统。",
            },
        }
    )

    self.assertEqual(request.options.imitation_requirement, "仿写成安全整改通知。")
    self.assertEqual(request.options.imitation_reference_material, "整改对象：核心系统。")


def test_build_smart_imitation_prompt_includes_template_requirement_reference_and_constraints(self):
    prompt = build_smart_imitation_prompt(
        template_text="本项目坚持问题导向，持续完善闭环机制。",
        requirement="仿写成网络安全整改说明。",
        reference_material="整改范围：终端账号、日志审计、漏洞修复。",
    )

    self.assertIn("企业办公文档智能仿写助手", prompt)
    self.assertIn("本项目坚持问题导向", prompt)
    self.assertIn("仿写成网络安全整改说明", prompt)
    self.assertIn("终端账号、日志审计、漏洞修复", prompt)
    self.assertIn("不编造事实", prompt)
    self.assertIn("只输出仿写后的正文", prompt)


def test_smart_imitation_uses_independent_task_type_and_task_key(self):
    class CapturingProviderClient(ProviderClient):
        def __init__(self):
            super().__init__(AppSettings())
            self.calls = []

        def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
            return True

        def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
            self.calls.append(
                {
                    "taskType": task_type,
                    "traceId": trace_id,
                    "inputData": input_data,
                    "query": query,
                    "timeoutSeconds": timeout_seconds,
                }
            )
            return {"answer": "仿写后的正文。"}

    provider = CapturingProviderClient()

    result = provider.smart_imitation(
        template_text="模板正文。",
        requirement="仿写成技术风险提示。",
        reference_material="风险：接口超时。",
        trace_id="trace-smart-imitation",
    )

    self.assertEqual(result["rewrittenText"], "仿写后的正文。")
    self.assertEqual(provider.calls[0]["taskType"], "word.smart_imitation")
    self.assertIn("仿写成技术风险提示", provider.calls[0]["query"])
```

Add `"word.smart_imitation"` into the expected task list in `adapter_service/tests/test_review_mode_contract.py`:

```python
self.assertEqual(
    list(status.keys()),
    ["word.smart_write", "word.smart_imitation", "word.document_review", "word.format_review"],
)
self.assertEqual(status["word.smart_imitation"]["apiKeyRef"], "word_smart_imitation")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_review_mode_contract -v
```

Expected:

```text
FAIL or ERROR because imitation_requirement, build_smart_imitation_prompt, smart_imitation, and word.smart_imitation task status do not exist yet.
```

- [ ] **Step 3: Implement request options**

In `adapter_service/app/core/models.py`, extend `RequestOptions`:

```python
imitation_requirement: str = Field(default="", alias="imitationRequirement")
imitation_reference_material: str = Field(default="", alias="imitationReferenceMaterial")
```

Add these fields to the existing string coercion if the model has a shared validator for string-like options. If no shared validator exists for `RequestOptions`, leave the default Pydantic coercion pattern consistent with nearby fields.

- [ ] **Step 4: Implement prompt builder and provider method**

In `adapter_service/app/services/provider_client.py`, add:

```python
def build_smart_imitation_prompt(template_text: str, requirement: str, reference_material: str = "") -> str:
    reference_text = reference_material.strip() or "未提供参考素材。"
    return "\n".join(
        [
            "你是企业办公文档智能仿写助手。",
            "",
            "仿写模板：",
            template_text.strip(),
            "",
            "仿写需求：",
            requirement.strip(),
            "",
            "参考素材：",
            reference_text,
            "",
            "要求：",
            "1. 学习仿写模板的句式、层次、表达节奏和段落结构。",
            "2. 生成内容必须服务于仿写需求。",
            "3. 如提供参考素材，应优先基于参考素材，不编造事实、数据、结论或机构名称。",
            "4. 不要照抄模板中的具体事实、对象、项目名称或数字，除非用户明确要求保留。",
            "5. 尽量保持模板的段落数量、标题层级、列表结构和语气风格。",
            "6. 只输出仿写后的正文，不解释仿写过程。",
        ]
    )
```

Add provider task status entry near the current Smart Write/Document Review/Format Review task list:

```python
("word.smart_imitation", "智能仿写")
```

Add method:

```python
def smart_imitation(
    self,
    template_text: str,
    requirement: str,
    reference_material: str,
    trace_id: str,
) -> Dict:
    prompt = build_smart_imitation_prompt(template_text, requirement, reference_material)
    task_type = "word.smart_imitation"
    if not self.is_task_configured(task_type):
        logger.info("traceId=%s provider=mock task=word.smart_imitation", trace_id)
        self.record_unconfigured_debug(task_type, trace_id, prompt)
        return {
            "rewrittenText": self._mock_rewrite(template_text, "imitate", requirement),
            "provider": "mock",
            "prompt": prompt,
        }

    body = self.post_task(task_type, trace_id, {}, prompt)
    rewritten_text = extract_answer(body)
    logger.info("traceId=%s provider=enterprise-dify-chat task=word.smart_imitation", trace_id)
    return {
        "rewrittenText": rewritten_text,
        "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
        "prompt": prompt,
        "conversationId": body.get("conversation_id", ""),
        "messageId": body.get("message_id", ""),
    }
```

- [ ] **Step 5: Run provider tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_review_mode_contract -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add adapter_service/app/core/models.py adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_provider.py adapter_service/tests/test_review_mode_contract.py
git commit -m "feat: add smart imitation provider contract"
```

## Task 2: Backend Service And Routes

**Files:**
- Create: `adapter_service/app/services/word/smart_imitator.py`
- Create: `adapter_service/tests/test_word_smart_imitation.py`
- Modify: `adapter_service/app/api/word.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`

- [ ] **Step 1: Write failing service tests**

Create `adapter_service/tests/test_word_smart_imitation.py`:

```python
import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import WordDocumentRequest
    from app.services.word.smart_imitator import WordSmartImitator


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingSmartImitationProvider:
    def __init__(self):
        self.calls = []

    def smart_imitation(self, template_text, requirement, reference_material, trace_id):
        self.calls.append(
            {
                "templateText": template_text,
                "requirement": requirement,
                "referenceMaterial": reference_material,
                "traceId": trace_id,
            }
        )
        return {
            "rewrittenText": "仿写后的技术风险提示。",
            "provider": "enterprise-dify-chat/task-file",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for smart imitation tests")
class WordSmartImitationTests(unittest.TestCase):
    def _request(self, template_text="模板段落。", requirement="仿写成技术风险提示。", reference="风险：接口超时。"):
        return parse_word_request(
            {
                "documentId": "imitate.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": template_text,
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "imitationRequirement": requirement,
                    "imitationReferenceMaterial": reference,
                },
            }
        )

    def test_smart_imitation_sends_template_requirement_and_reference(self):
        provider = RecordingSmartImitationProvider()
        result = WordSmartImitator(provider_client=provider).imitate(
            self._request(),
            trace_id="trace-smart-imitation",
        )

        self.assertEqual(provider.calls[0]["templateText"], "模板段落。")
        self.assertEqual(provider.calls[0]["requirement"], "仿写成技术风险提示。")
        self.assertEqual(provider.calls[0]["referenceMaterial"], "风险：接口超时。")
        self.assertEqual(result["originalText"], "模板段落。")
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")
        self.assertEqual(result["rewriteMode"], "imitate")
        self.assertEqual(result["diffHints"], [])
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")

    def test_smart_imitation_falls_back_to_paragraph_text_for_template(self):
        request = parse_word_request(
            {
                "documentId": "imitate-paragraphs.docx",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "",
                    "paragraphs": [
                        {"index": 1, "text": "第一段模板。"},
                        {"index": 2, "text": "第二段模板。"},
                    ],
                    "headings": [],
                },
                "options": {
                    "imitationRequirement": "仿写成验收结论。",
                    "imitationReferenceMaterial": "",
                },
            }
        )
        provider = RecordingSmartImitationProvider()

        WordSmartImitator(provider_client=provider).imitate(request, trace_id="trace-paragraphs")

        self.assertEqual(provider.calls[0]["templateText"], "第一段模板。\n第二段模板。")

    def test_smart_imitation_requires_template_and_requirement(self):
        imitator = WordSmartImitator(provider_client=RecordingSmartImitationProvider())

        with self.assertRaises(AdapterError) as missing_template:
            imitator.imitate(self._request(template_text=""), trace_id="trace-missing-template")
        self.assertEqual(missing_template.exception.code, "SMART_IMITATION_TEMPLATE_REQUIRED")
        self.assertIn("仿写模板", missing_template.exception.message)

        with self.assertRaises(AdapterError) as missing_requirement:
            imitator.imitate(self._request(requirement=""), trace_id="trace-missing-requirement")
        self.assertEqual(missing_requirement.exception.code, "SMART_IMITATION_REQUIREMENT_REQUIRED")
        self.assertIn("仿写需求", missing_requirement.exception.message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing service tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_word_smart_imitation -v
```

Expected:

```text
ERROR because app.services.word.smart_imitator does not exist yet.
```

- [ ] **Step 3: Implement Smart Imitator service**

Create `adapter_service/app/services/word/smart_imitator.py`:

```python
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.provider_client import ProviderClient


class WordSmartImitator:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def imitate(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        template_text = self._extract_template_text(request)
        requirement = request.options.imitation_requirement.strip()
        reference_material = request.options.imitation_reference_material.strip()

        if not template_text:
            raise AdapterError("SMART_IMITATION_TEMPLATE_REQUIRED", "请先提供仿写模板。", status_code=400)
        if not requirement:
            raise AdapterError("SMART_IMITATION_REQUIREMENT_REQUIRED", "请填写仿写需求。", status_code=400)

        provider_result = self.provider_client.smart_imitation(
            template_text,
            requirement,
            reference_material,
            trace_id,
        )
        return {
            "originalText": template_text,
            "rewrittenText": provider_result["rewrittenText"],
            "rewriteMode": "imitate",
            "diffHints": [],
            "provider": provider_result.get("provider", "mock"),
        }

    def _extract_template_text(self, request: WordDocumentRequest) -> str:
        template_text = request.content.plain_text.strip()
        if not template_text:
            template_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()
        return template_text
```

- [ ] **Step 4: Add FastAPI route and validation mapping**

Modify `adapter_service/app/api/word.py`:

```python
from app.services.word.smart_imitator import WordSmartImitator

smart_imitator = WordSmartImitator()


@router.post("/word/smart-imitation")
def smart_imitation_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-imitation")
    imitation = smart_imitator.imitate(request, trace_id=trace_id)
    payload = RewriteResponseData(**imitation)
    logger.info(
        "traceId=%s task=word.smart_imitation templateLength=%s resultLength=%s",
        trace_id,
        len(payload.original_text),
        len(payload.rewritten_text),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.smart_imitation",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
```

Modify `_task_type_from_path` in `adapter_service/app/main.py`:

```python
"/word/smart-imitation": "word.smart_imitation",
```

- [ ] **Step 5: Add standalone route**

Modify `adapter_service/standalone_adapter.py`:

```python
from app.services.word.smart_imitator import WordSmartImitator


def smart_imitation(payload):
    request = parse_word_request(payload)
    data = WordSmartImitator().imitate(request, trace_id="standalone-word-smart-imitation")
    if hasattr(RewriteResponseData, "model_validate"):
        return RewriteResponseData.model_validate(data).model_dump(by_alias=True)
    return RewriteResponseData(**data).dict(by_alias=True)
```

In `do_POST`:

```python
if path == "/word/smart-imitation":
    self._write(200, envelope("standalone-word-smart-imitation", "word.smart_imitation", smart_imitation(payload)))
    return
```

- [ ] **Step 6: Run backend service tests and compile checks**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_word_smart_imitation -v
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/app/services/word/smart_imitator.py adapter_service/app/api/word.py adapter_service/app/main.py adapter_service/standalone_adapter.py
```

Expected:

```text
OK
```

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add adapter_service/app/services/word/smart_imitator.py adapter_service/tests/test_word_smart_imitation.py adapter_service/app/api/word.py adapter_service/app/main.py adapter_service/standalone_adapter.py
git commit -m "feat: add smart imitation adapter route"
```

## Task 3: Frontend Mode, Inputs, Preview, And Copy

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Write failing frontend smoke assertions**

Add assertions to `formal-plugin-kit/tests/layout-smoke.test.js`:

```js
assert.ok(html.includes('id="smart-imitation-options"'));
assert.ok(html.includes('id="imitation-template-text"'));
assert.ok(html.includes('id="imitation-requirement"'));
assert.ok(html.includes('id="imitation-reference-material"'));
assert.ok(html.includes("仿写模板"));
assert.ok(html.includes("仿写需求"));
assert.ok(html.includes("参考素材"));

assert.ok(js.includes("smartImitation"));
assert.ok(js.includes("/word/smart-imitation"));
assert.ok(js.includes("runSmartImitationAction"));
assert.ok(js.includes("imitationTemplateText"));
assert.ok(js.includes("imitationRequirement"));
assert.ok(js.includes("imitationReferenceMaterial"));
assert.ok(js.includes("请先提供仿写模板。"));
assert.ok(js.includes("请填写仿写需求。"));
assert.ok(js.includes("setSmartWriteResult(body.data)"));
assert.ok(js.includes("state.currentMode !== \"smartImitation\""));
assert.ok(js.includes("hideCompareForSmartImitation"));
```

Add negative assertions:

```js
assert.ok(!js.includes('state.pendingApplyAction = "imitation"'));
assert.ok(!js.includes('applySmartImitation'));
```

- [ ] **Step 2: Run failing frontend smoke test**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected:

```text
AssertionError because Smart Imitation HTML and JS do not exist yet.
```

- [ ] **Step 3: Add Smart Imitation HTML inputs**

In `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`, add a section near existing task option sections:

```html
<section class="glass-card form-section" id="smart-imitation-options" hidden>
  <div class="section-heading">
    <p>智能仿写</p>
    <span>根据模板句式生成新内容</span>
  </div>
  <label for="imitation-template-text">仿写模板</label>
  <textarea id="imitation-template-text" rows="6" placeholder="可先在 Word 中选中文本，也可在此粘贴模板段落。"></textarea>
  <label for="imitation-requirement">仿写需求</label>
  <textarea id="imitation-requirement" rows="4" placeholder="说明要仿写成什么专业方向、用途、对象和语气。"></textarea>
  <label for="imitation-reference-material">参考素材</label>
  <textarea id="imitation-reference-material" rows="5" placeholder="选填。粘贴事实背景、参数、问题清单或项目材料。"></textarea>
</section>
```

- [ ] **Step 4: Add Smart Imitation JS mode and state**

In `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`, add mode config:

```js
smartImitation: {
  title: "智能仿写",
  primaryText: "生成仿写内容",
  runningText: "正在执行智能仿写...",
  doneText: "智能仿写结果已生成。",
  showRewriteOptions: false,
  showInstruction: false,
  showTemplate: false,
  showDocumentReviewOptions: false,
  showFixedTemplate: false,
  showSmartImitationOptions: true
}
```

Add state:

```js
imitationTemplateText: "",
imitationRequirement: "",
imitationReferenceMaterial: "",
```

Add visibility handling in `switchMode`:

```js
byId("smart-imitation-options").hidden = !config.showSmartImitationOptions;
byId("result-view-switch").hidden = state.currentMode === "smartImitation" && !state.smartWritePreviewModel;
```

Add a small helper:

```js
function hideCompareForSmartImitation() {
  var compareButton = byId("btn-result-compare");
  if (compareButton) {
    compareButton.hidden = state.currentMode === "smartImitation";
  }
  if (state.currentMode === "smartImitation" && state.resultViewMode === "compare") {
    setResultViewMode("preview");
  }
}
```

Call `hideCompareForSmartImitation()` from `switchMode` and after setting Smart Imitation results.

- [ ] **Step 5: Add template auto-fill and run function**

Add:

```js
function fillSmartImitationTemplateFromSelection() {
  var document = getActiveDocument();
  var selectedText = document ? getSelectionText(document) : "";
  if (selectedText && !state.imitationTemplateText) {
    state.imitationTemplateText = selectedText;
    byId("imitation-template-text").value = selectedText;
  }
}
```

Call it when entering `smartImitation` mode.

Add:

```js
function runSmartImitationAction() {
  var templateText = String(byId("imitation-template-text").value || "").trim();
  var requirement = String(byId("imitation-requirement").value || "").trim();
  var referenceMaterial = String(byId("imitation-reference-material").value || "").trim();
  var config = modeConfig[state.currentMode] || modeConfig.smartImitation;

  resetSmartWritePreviewState();
  state.pendingApplyAction = "";
  setApplyEnabled(false);

  if (!templateText) {
    setStatus("请先提供仿写模板。");
    setResult("请先提供仿写模板。");
    return;
  }
  if (!requirement) {
    setStatus("请填写仿写需求。");
    setResult("请填写仿写需求。");
    return;
  }

  state.latestDocumentPayload = {
    documentId: "smart-imitation",
    scene: "word",
    selectionMode: "selection",
    content: {
      plainText: templateText,
      paragraphs: helpers.collectParagraphsFromText
        ? helpers.collectParagraphsFromText(templateText, SMART_WRITE_EXTRACTION_OPTIONS)
        : [],
      headings: []
    },
    options: {
      imitationRequirement: requirement,
      imitationReferenceMaterial: referenceMaterial
    }
  };

  setStatus(config.runningText);
  setPlainResult("正在生成仿写内容，请稍候。");
  request("/word/smart-imitation", state.latestDocumentPayload)
    .then(function (body) {
      state.pendingApplyAction = "";
      state.rewriteResult = setSmartWriteResult(body.data);
      setApplyEnabled(false);
      setTrace(body.traceId);
      hideCompareForSmartImitation();
      setStatus(config.doneText);
    })
    .catch(function (error) {
      var message = describeFetchError(error);
      setStatus("生成失败：" + message);
      setResult(message);
    });
}
```

Update `runPrimaryAction`:

```js
if (state.currentMode === "smartImitation") {
  runSmartImitationAction();
  return;
}
```

Update apply button visibility:

```js
byId("btn-apply").hidden = state.currentMode !== "smartWrite";
```

- [ ] **Step 6: Bind input events**

In `bindEvents()`:

```js
byId("imitation-template-text").addEventListener("input", function (event) {
  state.imitationTemplateText = event.target.value;
});
byId("imitation-requirement").addEventListener("input", function (event) {
  state.imitationRequirement = event.target.value;
});
byId("imitation-reference-material").addEventListener("input", function (event) {
  state.imitationReferenceMaterial = event.target.value;
});
```

- [ ] **Step 7: Add CSS**

In `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`, add textarea styling only if existing textarea rules do not already cover the new IDs:

```css
#smart-imitation-options textarea {
  min-height: 88px;
  resize: vertical;
}

#imitation-template-text {
  min-height: 132px;
}
```

- [ ] **Step 8: Run frontend tests and syntax check**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

Expected:

```text
layout smoke tests passed
```

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: add smart imitation taskpane mode"
```

## Task 4: Ribbon Entry, Icon, Settings, And Packaging Assertions

**Files:**
- Create: `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `config/adapter.example.json`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`
- Test: `adapter_service/tests/test_packaging_scripts.py`

- [ ] **Step 1: Write failing Ribbon, icon, and settings assertions**

In `formal-plugin-kit/tests/layout-smoke.test.js`, add:

```js
assert.ok(ribbon.includes('id="btnAiSmartImitation"'));
assert.ok(ribbon.includes('label="智能仿写"'));
assert.ok(ribbonJs.includes('btnAiSmartImitation: "smartImitation"'));
assert.ok(ribbonJs.includes('btnAiSmartImitation: "assets/icon-smart-imitation.png"'));
assert.ok(fs.existsSync("formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png"));
assert.ok(js.includes('{ taskType: "word.smart_imitation", label: "智能仿写" }'));
```

In `adapter_service/tests/test_packaging_scripts.py`, add:

```python
def test_smart_imitation_assets_and_docs_are_packaged(self) -> None:
    self.assertTrue(Path("formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png").exists())
    self.assertTrue(Path("docs/operations/dify-smart-imitation-workflow.md").exists())
    config = Path("config/adapter.example.json").read_text(encoding="utf-8")
    self.assertIn('"word.smart_imitation": "word_smart_imitation"', config)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected:

```text
Assertions fail because Ribbon, icon, config, and Smart Imitation docs are not present yet.
```

- [ ] **Step 3: Add Ribbon button and icon mapping**

In `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`, insert the new button after Smart Write:

```xml
<button id="btnAiSmartImitation" label="智能仿写" size="large" getImage="GetImage" onAction="OnAction" />
```

In `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`:

```js
btnAiSmartImitation: "smartImitation",
```

and:

```js
btnAiSmartImitation: "assets/icon-smart-imitation.png",
```

- [ ] **Step 4: Create the icon asset**

Create `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png` as a PNG matching the current icon family:

- 32px visual style compatible with the current Ribbon icons.
- Transparent background.
- Blue/gray treatment consistent with `icon-smart-write.png`.
- Distinct metaphor: a document/template mark with a generated text line.

After creating it, verify:

```bash
file formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png
```

Expected:

```text
PNG image data
```

- [ ] **Step 5: Add task API key ref**

In `config/adapter.example.json`:

```json
"word.smart_imitation": "word_smart_imitation"
```

In `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`, add to `TASK_API_KEY_ITEMS`:

```js
{ taskType: "word.smart_imitation", label: "智能仿写" },
```

- [ ] **Step 6: Run tests**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected:

```text
layout smoke tests passed
OK
```

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js config/adapter.example.json formal-plugin-kit/tests/layout-smoke.test.js adapter_service/tests/test_packaging_scripts.py
git commit -m "feat: add smart imitation ribbon entry"
```

## Task 5: Operations Docs, Version Bump, Handoff, And Package

**Files:**
- Create: `docs/operations/dify-smart-imitation-workflow.md`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: version-bearing files listed in the File Structure section
- Modify: version-related tests
- Modify: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260619.tar.gz` or date-tagged package for the release date

- [ ] **Step 1: Write Dify workflow documentation**

Create `docs/operations/dify-smart-imitation-workflow.md`:

```markdown
# 智能仿写 Dify 工作流配置

适用任务：`word.smart_imitation`

推荐任务级 API Key 引用：`word_smart_imitation`

## 输入约定

adapter 会把完整提示词放入 `/chat-messages` 的顶层 `query` 和 `inputs.query`。Dify 工作流应直接把 `query` 传给 LLM 节点。

## 输出约定

只输出仿写后的正文，不输出解释、分析过程、处理说明或前端状态。

## 建议模型参数

建议温度在 `0.3` 到 `0.5` 之间。需要严格贴近模板和素材时使用 `0.3`，需要稍强表达变化时使用 `0.5`。

## 排查

在 WPS 设置页查看“最近一次任务诊断”，确认 `taskType=word.smart_imitation`，并确认任务级 API Key 命中 `word_smart_imitation`。
```

- [ ] **Step 2: Bump versions to 0.14.0-alpha**

Update these files from `0.13.8-alpha` to `0.14.0-alpha`, and update rule number to `AI-WPS-P1-WORD-0.14.0-20260619`:

```text
README.md
docs/codex-handoff.md
adapter_service/app/api/health.py
adapter_service/app/main.py
adapter_service/app/services/provider_client.py
adapter_service/standalone_adapter.py
adapter-start-kit/scripts/start_uvicorn_adapter.sh
adapter_service/tests/test_health.py
adapter_service/tests/test_packaging_scripts.py
adapter_service/tests/test_review_mode_contract.py
formal-plugin-kit/tests/layout-smoke.test.js
formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json
formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html
formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
```

- [ ] **Step 3: Update README and handoff**

In `README.md`, add changelog row:

```markdown
| `v0.14.0-alpha` | Adds the independent Smart Imitation workflow with a dedicated Ribbon entry, task-pane template/requirement/reference inputs, separate `word.smart_imitation` model-backend route, task-level API key, Dify workflow guide, and preview/plain-text/copy-only results without comparison or writeback |
```

In `docs/codex-handoff.md`, update:

- Current version and rule number.
- Current routes list with `POST /word/smart-imitation`.
- Current key changes with Smart Imitation summary.
- Protected logic with "Smart Imitation must remain preview/copy only in first version."
- Tests and package SHA after final packaging.

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/standalone_adapter.py adapter_service/app/api/word.py adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/app/services/word/smart_imitator.py adapter_service/app/core/models.py
git diff --check
```

Expected:

```text
Python unittest OK with the existing FastAPI-related skips.
Node smoke and helper tests pass.
Syntax and diff checks pass.
```

- [ ] **Step 5: Build delivery package**

Run:

```bash
DATE_TAG=20260619 bash packaging/build_phase1_delivery_kit.sh
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260619.tar.gz
```

Verify package contents:

```bash
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260619.tar.gz | rg 'icon-smart-imitation.png|dify-smart-imitation-workflow.md|taskpane.js|provider_client.py|smart_imitator.py'
```

Expected:

```text
The package contains the new icon, operations doc, frontend code, provider code, and smart_imitator service.
```

- [ ] **Step 6: Update handoff package SHA**

Copy the SHA from Step 5 into `docs/codex-handoff.md` under the current package result section.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add README.md docs/codex-handoff.md docs/operations/dify-smart-imitation-workflow.md adapter_service/app/api/health.py adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/standalone_adapter.py adapter-start-kit/scripts/start_uvicorn_adapter.sh adapter_service/tests/test_health.py adapter_service/tests/test_packaging_scripts.py adapter_service/tests/test_review_mode_contract.py formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260619.tar.gz
git commit -m "chore: release smart imitation alpha"
```

## Final Verification Checklist

- [ ] `POST /word/smart-imitation` works through FastAPI and standalone adapter.
- [ ] `word.smart_imitation` appears in task API key settings and diagnostics.
- [ ] Smart Imitation task pane can use selected text as template and manual template text.
- [ ] Missing template and missing requirement show Chinese user-facing messages.
- [ ] Result preview and plain-text views work.
- [ ] Copy copies generated text.
- [ ] Compare view is hidden in Smart Imitation mode.
- [ ] Apply/writeback is hidden and unreachable in Smart Imitation mode.
- [ ] Smart Write behavior remains unchanged.
- [ ] Document Review long-task recovery remains unchanged.
- [ ] Format Review behavior remains unchanged.
- [ ] Delivery package contains new icon and Dify guide.
- [ ] `docs/codex-handoff.md` contains the final package SHA.
