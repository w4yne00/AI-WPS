# PPT Single-Slide Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only WPS Presentation single-slide assistant that optimizes an existing slide or generates one slide from a short instruction, returning a title, 3-5 bullets, and one conclusion without modifying the presentation.

**Architecture:** Add a host-separated `wpp` add-in and a new `ppt.slide_assistant` adapter task. The add-in reads only the current slide plus adjacent slide titles, enforces a 4600-character dynamic input budget, submits an idempotent background job, and renders/copies the result. The adapter revalidates input, determines `generate` versus `optimize`, calls the existing Dify-compatible provider path, and supports FastAPI and standalone modes.

**Tech Stack:** WPS JS/HTML add-ins for Linux WPS Presentation, JavaScript ES5-compatible task pane code, Python 3.8, FastAPI, Pydantic, Dify-compatible `/chat-messages`, Python `unittest`, Node `assert`/`vm` smoke tests, bash delivery scripts.

---

## Scope Notes

- Implement `docs/superpowers/specs/2026-07-10-ppt-single-slide-assistant-design.md`.
- Target release: `0.17.0-alpha`.
- Target rule number: `AI-WPS-P1-WORD-EXCEL-PPT-0.17.0-20260710`.
- Use task status values already established in this repository: `running`, `completed`, and `failed`.
- Stop after Task 1 until the host probe passes on Kylin V10 + WPS 12.1.2. Do not implement model-backed PPT behavior against an unverified presentation object model.
- PPT remains read-only. Do not call `Slides.Add`, `Shapes.Add*`, `TextRange.Text =`, `Delete`, `Paste`, or any equivalent presentation write API.
- Do not change Word or Excel extraction, prompts, routes, result rendering, polling, or writeback behavior.
- The working tree contains historical delivery archive deletions, one modified archive, and untracked old archives. Never use `git add -A`; stage only paths listed by each task.

## File Structure

Create:

- `adapter_service/app/api/ppt.py`: FastAPI background job submission and status routes.
- `adapter_service/app/services/ppt/__init__.py`: PPT service package marker.
- `adapter_service/app/services/ppt/slide_assistant.py`: server-side budget enforcement, mode selection, validation, and provider result shaping.
- `adapter_service/app/services/ppt/slide_assistant_jobs.py`: idempotent in-memory background jobs and public status payloads.
- `adapter_service/tests/test_ppt_slide_assistant.py`: model, service, job, API, and standalone tests.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/`: host-separated WPS Presentation add-in.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`: presentation COM-safe reads, text budgets, Markdown rendering, profile response normalization.
- `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`: mock presentation object-model and pure helper tests.
- `docs/operations/wps-ppt-host-probe.md`: target-machine probe installation and acceptance record.
- `docs/operations/dify-ppt-slide-assistant-workflow.md`: PPT Dify workflow input/output guide.

Modify:

- `adapter_service/app/core/models.py`: PPT request and response models.
- `adapter_service/app/services/provider_client.py`: PPT prompt, parser, timeout, task status, and provider method.
- `adapter_service/app/services/workflow_profiles.py`: allow `ppt.slide_assistant` profiles.
- `adapter_service/app/main.py`: include PPT router and map validation errors to the PPT task.
- `adapter_service/standalone_adapter.py`: standalone PPT parse, job submit, and job status parity.
- `adapter_service/tests/test_enterprise_provider.py`: prompt, parser, task key, and timeout tests.
- `adapter_service/tests/test_review_mode_contract.py`: six-task ordering and release version contract.
- `adapter_service/tests/test_workflow_profiles.py`: PPT profile create/list/activate coverage.
- `adapter_service/tests/test_packaging_scripts.py`: three-add-in installer and package coverage.
- `config/adapter.example.json`: default `ppt.slide_assistant` API key reference.
- `formal-plugin-kit/tests/layout-smoke.test.js`: PPT host isolation, read-only UI, version, and polling checks.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/*`: version tokens only.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/*`: version tokens only.
- `phase1-delivery-kit/wps-jsaddons/publish.xml`: add `type="wpp"` registration.
- `phase1-delivery-kit/installer/install_phase1.sh`: install all three add-ins while preserving runtime configuration.
- `phase1-delivery-kit/scripts/phase1_smoke_test.sh`: verify all three add-ins and publish entries.
- `phase1-delivery-kit/README.md`: document PPT add-in and validation.
- `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`: PPT target acceptance steps.
- `phase1-delivery-kit/docs/phase1-acceptance-record.md`: release evidence fields.
- `packaging/build_phase1_delivery_kit.sh`: include PPT add-in and operations guide.
- `README.md`, `README-ZH.md`, `docs/codex-handoff.md`: release scope, protected boundaries, API list, tests, and delivery package.
- Version-bearing backend and startup files: `adapter_service/app/api/health.py`, `adapter_service/app/main.py`, `adapter_service/app/services/provider_client.py`, `adapter_service/standalone_adapter.py`, `adapter-start-kit/scripts/start_uvicorn_adapter.sh`.

## Task 1: Build And Validate The WPS Presentation Host Probe

**Files:**
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/index.html`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/manifest.json`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/manifest.xml`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.xml`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/assets/ai-assistant-32.png`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/assets/icon-ppt-slide-assistant.png`
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/assets/icon-settings.png`
- Create: `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Create: `docs/operations/wps-ppt-host-probe.md`

- [ ] **Step 1: Add failing static host-isolation assertions**

Extend `formal-plugin-kit/tests/layout-smoke.test.js` with exact PPT file reads and assertions:

```javascript
const pptRoot = "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0";
const pptRibbon = fs.readFileSync(`${pptRoot}/ribbon.xml`, "utf8");
const pptRibbonJs = fs.readFileSync(`${pptRoot}/ribbon.js`, "utf8");
const pptManifest = fs.readFileSync(`${pptRoot}/manifest.json`, "utf8");

assert.ok(pptRibbon.includes('label="PPT 单页助手"'));
assert.ok(pptRibbon.includes('label="设置"'));
assert.ok(!pptRibbon.includes("智能编写"));
assert.ok(!pptRibbon.includes("Excel 智能分析"));
assert.ok(pptRibbonJs.includes('btnAiPptSlideAssistant: "pptSlideAssistant"'));
assert.ok(pptManifest.includes('"name": "wps-ai-assistant-wpp"'));
```

- [ ] **Step 2: Run the static test and verify it fails**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL with `ENOENT` for `wps-ai-assistant-wpp_1.0.0`.

- [ ] **Step 3: Add failing mock object-model extraction tests**

Create `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js` using Node `vm`. The test must construct one-based WPS-like collections and verify current/adjacent slide reads:

```javascript
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js",
  "utf8"
);
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);
const helpers = context.window.WpsAiPptHelpers;

function collection(items) {
  return { Count: items.length, Item(index) { return items[index - 1]; } };
}

function shape(text) {
  return { TextFrame: { HasText: true, TextRange: { Text: text } } };
}

function slide(index, title, body) {
  const titleShape = shape(title);
  const shapes = [titleShape].concat(body.map(shape));
  shapes.Title = titleShape;
  return { SlideIndex: index, Shapes: collection(shapes) };
}

const slides = [
  slide(1, "项目背景", ["背景正文"]),
  slide(2, "项目进展", ["总体方案设计已完成", "正在开展接口联调"]),
  slide(3, "风险与措施", ["风险正文"])
];
const app = {
  ActivePresentation: { Name: "汇报材料.pptx", Slides: collection(slides) },
  ActiveWindow: { View: { Slide: slides[1] } }
};

const result = helpers.extractPresentationSlide(app, {
  maxTitleLength: 200,
  maxBlockLength: 1000,
  maxBodyLength: 3000,
  maxAdjacentTitleLength: 200
});

assert.strictEqual(result.presentationId, "汇报材料.pptx");
assert.strictEqual(result.slide.index, 2);
assert.strictEqual(result.slide.title, "项目进展");
assert.deepStrictEqual(Array.from(result.slide.textBlocks), ["总体方案设计已完成", "正在开展接口联调"]);
assert.strictEqual(result.slide.previousTitle, "项目背景");
assert.strictEqual(result.slide.nextTitle, "风险与措施");
assert.strictEqual(result.slide.truncated, false);
console.log("ppt taskpane helper tests passed");
```

Add cases for `TextFrame2`, no title placeholder, title-only slide, blank slide, one 1200-character shape, and body content over 3000 characters.

- [ ] **Step 4: Run the helper test and verify it fails**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
```

Expected: FAIL because `taskpane-helpers.js` does not exist.

- [ ] **Step 5: Create the minimal `wpp` add-in manifest and Ribbon**

Create the manifest and Ribbon with these exact identities:

```json
{
  "name": "wps-ai-assistant-wpp",
  "version": "0.17.0-alpha",
  "description": "AI-WPS PPT single-slide assistant",
  "icons": { "32": "assets/ai-assistant-32.png" },
  "entry": "index.html"
}
```

```xml
<customUI xmlns="http://schemas.microsoft.com/office/2006/01/customui" onLoad="OnAddinLoad">
  <ribbon startFromScratch="false">
    <tabs>
      <tab id="wpsAiAssistantPptTab" label="WPS AI 助理">
        <group id="wpsAiAssistantPptGroup" label="演示内容">
          <button id="btnAiPptSlideAssistant" label="PPT 单页助手" size="large" getImage="GetImage" onAction="OnAction" />
          <button id="btnAiSettings" label="设置" size="large" getImage="GetImage" onAction="OnAction" />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>
```

In `ribbon.js`, map only `btnAiPptSlideAssistant` and `btnAiSettings`. Use `window.Application.CreateTaskPane` and build token `0.17.0-alpha`. Copy the existing base, smart-write, and settings PNG assets into the PPT asset names; do not synthesize a new icon format in this task.

- [ ] **Step 6: Implement COM-safe read helpers**

In `taskpane-helpers.js`, expose one namespace with no write methods:

```javascript
window.WpsAiPptHelpers = {
  extractPresentationSlide: extractPresentationSlide,
  truncateText: truncateText,
  renderMarkdown: renderMarkdown,
  escapeHtml: escapeHtml,
  normalizeWorkflowProfiles: normalizeWorkflowProfiles
};
```

Implement `safeRead`, `safeCall`, `resolveValue`, one-based collection access, `TextFrame.TextRange.Text` with `TextFrame2.TextRange.Text` fallback, `Shapes.Title` title preference, first-short-text title fallback, adjacent title reads, title de-duplication, per-block truncation, and total-body truncation. Never assign to a WPS object property.

- [ ] **Step 7: Create the host-probe task pane**

The probe pane has one `读取当前页` button and renders a read-only JSON summary. Its click handler must yield before COM reads:

```javascript
setStatus("正在读取当前幻灯片...");
setTimeout(function () {
  try {
    const payload = helpers.extractPresentationSlide(window.Application || window.wps || {}, LIMITS);
    setStatus("当前幻灯片读取完成。");
    byId("result-output").textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    setStatus("读取失败：" + error.message);
  }
}, 0);
```

Use stable dimensions at 420px task-pane width and avoid any Apply/Insert controls.

- [ ] **Step 8: Run automated probe checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js
```

Expected: all commands exit 0.

- [ ] **Step 9: Write and execute the target-machine probe checklist**

`docs/operations/wps-ppt-host-probe.md` must record exact checks for Ribbon registration, current slide index, title placeholder, multiple text boxes, adjacent titles, title-only page, blank page, image-only page, chart-only page, and task-pane responsiveness.

On the target machine, register:

```xml
<jsplugin name="wps-ai-assistant-wpp" url="file://" type="wpp" enable="enable_dev" version="1.0.0"/>
```

Expected: every read scenario returns a visible JSON result or a clear read error without freezing WPS.

**HARD STOP:** Do not start Task 2 until the user confirms this probe on Kylin V10 + WPS 12.1.2.

- [ ] **Step 10: Commit the verified probe**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0 formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/tests/layout-smoke.test.js docs/operations/wps-ppt-host-probe.md
git commit -m "test: verify WPS presentation host access"
```

## Task 2: Add PPT Models, Prompt, Parser, And Provider Task

**Files:**
- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Write failing request and parser tests**

Add tests that construct this payload and verify camelCase aliases:

```python
request = PptSlideAssistantRequest.parse_obj(
    {
        "presentationId": "汇报材料.pptx",
        "scene": "ppt",
        "clientJobId": "client-ppt-slide-12345678",
        "slide": {
            "index": 2,
            "title": "项目进展",
            "textBlocks": ["总体方案设计已完成", "正在开展接口联调"],
            "previousTitle": "项目背景",
            "nextTitle": "风险与措施",
            "truncated": False,
        },
        "userInstruction": "面向管理层，突出进展和风险。",
    }
)
self.assertEqual(request.scene, "ppt")
self.assertEqual(request.slide.text_blocks[0], "总体方案设计已完成")
self.assertEqual(request.user_instruction, "面向管理层，突出进展和风险。")
```

Test JSON, fixed Markdown, `<think>` removal, and raw fallback:

```python
markdown = """## 建议标题
项目总体进展

## 核心要点
- 总体方案设计已完成
- 系统进入联调阶段
- 重点关注接口稳定性

## 本页结论
项目按计划推进，应集中完成联调和风险收敛。
"""
parsed = parse_ppt_slide_answer(markdown)
self.assertEqual(parsed["suggestedTitle"], "项目总体进展")
self.assertEqual(len(parsed["bullets"]), 3)
self.assertEqual(parsed["rawAnswer"], None)

fallback = parse_ppt_slide_answer("模型返回了一段无法分区的最终内容。")
self.assertIn("无法分区", fallback["rawAnswer"])
self.assertEqual(fallback["parseFallbackReason"], "ppt_output_not_structured")
```

- [ ] **Step 2: Run focused provider tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: FAIL importing PPT symbols.

- [ ] **Step 3: Add Pydantic PPT models**

Add these model boundaries in `core/models.py`:

```python
class PptSlideInput(BaseModel):
    index: int = 1
    title: str = ""
    text_blocks: List[str] = Field(default_factory=list, alias="textBlocks")
    previous_title: str = Field(default="", alias="previousTitle")
    next_title: str = Field(default="", alias="nextTitle")
    truncated: bool = False


class PptSlideAssistantRequest(BaseModel):
    presentation_id: str = Field(default="active-presentation", alias="presentationId")
    scene: Literal["ppt"] = "ppt"
    client_job_id: str = Field(default="", alias="clientJobId")
    slide: PptSlideInput = Field(default_factory=PptSlideInput)
    user_instruction: str = Field(default="", alias="userInstruction")


class PptSlideAssistantResponseData(BaseModel):
    mode_used: Literal["generate", "optimize"] = Field(alias="modeUsed")
    suggested_title: str = Field(default="", alias="suggestedTitle")
    bullets: List[str] = Field(default_factory=list)
    conclusion: str = ""
    plain_text: str = Field(default="", alias="plainText")
    raw_answer: Optional[str] = Field(default=None, alias="rawAnswer")
    parse_fallback_reason: Optional[str] = Field(default=None, alias="parseFallbackReason")
    provider: str = "mock"
```

Use existing `_safe_str`, `_safe_int`, and `_safe_bool` validators so non-scalar COM artifacts do not enter provider prompts. Length enforcement remains in `slide_assistant.py`, not in Pydantic coercion.

- [ ] **Step 4: Implement the prompt builder and parser**

Add `PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS = EXCEL_ANALYSIS_TIMEOUT_SECONDS` and `build_ppt_slide_prompt(context, user_instruction, mode)`.

The prompt must include these exact output constraints:

```python
"1. 只输出建议标题、核心要点和本页结论。",
"2. 核心要点必须为 3 至 5 条。",
"3. 不输出配色、版式、图标、图片、动画或页面操作建议。",
"4. 不声称已经修改 PPT，不输出深度思考过程。",
"5. 前后页标题只用于避免重复和保持衔接，不扩写相邻页面。",
```

Implement `parse_ppt_slide_answer` in this order: strip think content, `_extract_json_payload`, fixed Markdown sections, then raw fallback. Normalize bullets by removing Markdown markers and blank lines, but do not invent missing bullets.

Add an explicit unconfigured-provider result; it must remain structurally valid and explain the required setup without claiming model output:

```python
def build_ppt_unconfigured_result(context: Dict, mode: str, prompt: str) -> Dict:
    return {
        "modeUsed": mode,
        "suggestedTitle": context.get("title") or "PPT 单页内容建议",
        "bullets": [
            "已读取当前第 {0} 页内容。".format(context.get("index", 1)),
            "当前尚未配置 PPT 单页助手工作流。",
            "请在设置页保存并启用 ppt.slide_assistant 的工作流配置。",
        ],
        "conclusion": "完成模型后台配置后，可生成正式的本页标题、要点和结论。",
        "plainText": "当前尚未配置 PPT 单页助手工作流，请先在设置页完成配置。",
        "rawAnswer": None,
        "parseFallbackReason": None,
        "provider": "mock",
        "prompt": prompt,
    }
```

- [ ] **Step 5: Add the provider method and independent task key test**

Add:

```python
def ppt_slide_assistant(self, context: Dict, user_instruction: str, mode: str, trace_id: str) -> Dict:
    prompt = build_ppt_slide_prompt(context, user_instruction, mode)
    task_type = "ppt.slide_assistant"
    if not self.is_task_configured(task_type):
        self.record_unconfigured_debug(task_type, trace_id, prompt)
        return build_ppt_unconfigured_result(context, mode, prompt)
    body = self.post_task(
        task_type,
        trace_id,
        {"scene": "ppt", "slideIndex": context["index"], "mode": mode, "truncated": context["truncated"]},
        prompt,
        timeout_seconds=max(self.settings.timeout_seconds, PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS),
    )
    parsed = parse_ppt_slide_answer(extract_answer(body))
    return {
        **parsed,
        "modeUsed": mode,
        "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
        "prompt": prompt,
        "conversationId": body.get("conversation_id", ""),
        "messageId": body.get("message_id", ""),
    }
```

Test that `post_task` receives `ppt.slide_assistant`, timeout `1800`, mode metadata, and no Word/Excel task key.

- [ ] **Step 6: Run provider tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: PASS.

- [ ] **Step 7: Commit the provider contract**

```bash
git add adapter_service/app/core/models.py adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_provider.py
git commit -m "feat: add PPT slide provider contract"
```

## Task 3: Add Server-Side Budgets, Background Jobs, And FastAPI Routes

**Files:**
- Create: `adapter_service/app/services/ppt/__init__.py`
- Create: `adapter_service/app/services/ppt/slide_assistant.py`
- Create: `adapter_service/app/services/ppt/slide_assistant_jobs.py`
- Create: `adapter_service/app/api/ppt.py`
- Create: `adapter_service/tests/test_ppt_slide_assistant.py`
- Modify: `adapter_service/app/main.py`

- [ ] **Step 1: Write failing budget and mode tests**

Add tests for exact limits:

```python
result = normalize_ppt_slide_request(
    self._request(
        title="题" * 250,
        text_blocks=["甲" * 1200, "乙" * 1800, "丙" * 1800],
        previous_title="前" * 250,
        next_title="后" * 250,
        instruction="要求" * 700,
    )
)
self.assertEqual(len(result["title"]), 200)
self.assertEqual(max(map(len, result["textBlocks"])), 1000)
self.assertLessEqual(sum(map(len, result["textBlocks"])), 3000)
self.assertEqual(len(result["previousTitle"]), 200)
self.assertEqual(len(result["nextTitle"]), 200)
self.assertEqual(len(result["userInstruction"]), 1000)
self.assertTrue(result["truncated"])
```

Add mode tests:

```python
self.assertEqual(determine_ppt_slide_mode({"textBlocks": ["有效正文达到二十个非空白字符用于优化模式判定"]}), "optimize")
self.assertEqual(determine_ppt_slide_mode({"textBlocks": ["短内容"]}), "generate")
```

Test that generate mode with blank instruction raises `PPT_SLIDE_INSTRUCTION_REQUIRED` and missing current slide raises `PPT_SLIDE_REQUIRED`.

- [ ] **Step 2: Write failing job idempotency and route tests**

Use a blocking fake assistant. Start the same `clientJobId` twice and assert one model call, original trace ID, `running`, `providerTimeoutSeconds == 1800`, then `completed`. Add FastAPI route tests for submit, status, and `PPT_SLIDE_JOB_NOT_FOUND`.

- [ ] **Step 3: Run focused PPT tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_ppt_slide_assistant -v
```

Expected: FAIL because PPT service and API modules do not exist.

- [ ] **Step 4: Implement server-side normalization and service validation**

Define constants in `slide_assistant.py`:

```python
PPT_MAX_TITLE_LENGTH = 200
PPT_MAX_BLOCK_LENGTH = 1000
PPT_MAX_BODY_LENGTH = 3000
PPT_MAX_ADJACENT_TITLE_LENGTH = 200
PPT_MAX_USER_INSTRUCTION_LENGTH = 1000
PPT_OPTIMIZE_MIN_BODY_CHARS = 20
```

`normalize_ppt_slide_request` must return a new dictionary and never mutate the Pydantic request. Count non-whitespace characters for mode selection. `PptSlideAssistant.assist` validates mode, calls `ProviderClient.ppt_slide_assistant`, and returns only response-model fields plus provider metadata.

- [ ] **Step 5: Implement the idempotent job store**

Follow the existing public job shape exactly:

```python
job = {
    "jobId": job_id,
    "traceId": trace_id,
    "status": "running",
    "createdAt": time.time(),
    "updatedAt": time.time(),
    "runningMessage": "模型后台正在处理 PPT 单页内容，adapter 会继续等待结果。",
    "providerTimeoutSeconds": PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS,
    "result": None,
    "error": None,
}
```

Use the same client job ID regex and 30-job bound as Excel. Worker success sets `completed`; exception sets `failed` with code `PPT_SLIDE_JOB_FAILED`.

- [ ] **Step 6: Implement FastAPI routes and validation mapping**

Add only:

```python
router = APIRouter()
ppt_slide_assistant = PptSlideAssistant()
ppt_slide_jobs = PptSlideAssistantJobStore(ppt_slide_assistant)


@router.post("/ppt/slide-assistant/jobs")
def start_ppt_slide_assistant_job(request: PptSlideAssistantRequest) -> dict:
    trace_id = new_trace_id("ppt-slide-assistant")
    job = ppt_slide_jobs.start(request, trace_id=trace_id)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "ppt.slide_assistant",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/ppt/slide-assistant/jobs/{job_id}")
def get_ppt_slide_assistant_job(job_id: str):
    job = ppt_slide_jobs.get(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "traceId": job_id,
                "taskType": "ppt.slide_assistant",
                "message": "PPT 单页助手后台任务不存在或已过期。",
                "data": {"jobId": job_id, "status": "not_found"},
                "errors": [
                    {
                        "code": "PPT_SLIDE_JOB_NOT_FOUND",
                        "message": "PPT 单页助手后台任务不存在或已过期。",
                    }
                ],
            },
        )
    if job.get("result"):
        job = {
            **job,
            "result": PptSlideAssistantResponseData(**job["result"]).dict(by_alias=True),
        }
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.slide_assistant",
        "message": job["status"],
        "data": job,
        "errors": [],
    }
```

Include `ppt_router` in `main.py`. Map `/ppt/slide-assistant/jobs` to `ppt.slide_assistant` in `_task_type_from_path`. Do not add a synchronous `/ppt/slide-assistant` route.

- [ ] **Step 7: Run PPT and regression tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_ppt_slide_assistant -v
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
```

Expected: PPT tests pass; full suite passes with only dependency-conditioned skips.

- [ ] **Step 8: Commit service and API**

```bash
git add adapter_service/app/services/ppt adapter_service/app/api/ppt.py adapter_service/app/main.py adapter_service/tests/test_ppt_slide_assistant.py
git commit -m "feat: add PPT slide background jobs"
```

## Task 4: Add Workflow Profiles, Diagnostics, Config, And Standalone Parity

**Files:**
- Modify: `adapter_service/app/services/workflow_profiles.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/tests/test_workflow_profiles.py`
- Modify: `adapter_service/tests/test_review_mode_contract.py`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `adapter_service/tests/test_ppt_slide_assistant.py`
- Modify: `config/adapter.example.json`

- [ ] **Step 1: Write failing six-task profile and diagnostics tests**

Update ordered task assertions to:

```python
[
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
    "word.format_review",
    "excel.analysis",
    "ppt.slide_assistant",
]
```

Assert the default ref is `ppt_slide_assistant`. Create, activate, rename, replace the key, list, and delete an inactive PPT profile using `WorkflowProfileStore`.

- [ ] **Step 2: Write failing standalone route tests**

Test `parse_ppt_request`, `ppt_slide_assistant_job_payload`, POST `/ppt/slide-assistant/jobs`, GET `/ppt/slide-assistant/jobs/{jobId}`, and 404 code `PPT_SLIDE_JOB_NOT_FOUND`. Assert `adapter_service/tests/test_packaging_scripts.py` finds those route strings in `standalone_adapter.py`.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_workflow_profiles adapter_service.tests.test_review_mode_contract adapter_service.tests.test_ppt_slide_assistant adapter_service.tests.test_packaging_scripts -v
```

Expected: FAIL because PPT is not in supported task/profile and standalone paths.

- [ ] **Step 4: Add the sixth task to config and diagnostics**

Append `ppt.slide_assistant` to `SUPPORTED_WORKFLOW_TASKS`, `ProviderClient.build_task_api_key_status`, and `config/adapter.example.json`:

```json
"ppt.slide_assistant": "ppt_slide_assistant"
```

Do not change profile storage format, migration behavior, key permissions, or fallback to the unified API key.

- [ ] **Step 5: Add standalone parity**

Create `PPT_SLIDE_ASSISTANT_JOB_STORE = PptSlideAssistantJobStore()`, parse Pydantic v1/v2 request forms, serialize `PptSlideAssistantResponseData`, and implement the two job routes. Use the same envelope fields and status values as FastAPI.

- [ ] **Step 6: Run focused and full tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_workflow_profiles adapter_service.tests.test_review_mode_contract adapter_service.tests.test_ppt_slide_assistant adapter_service.tests.test_packaging_scripts -v
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
```

Expected: all available tests pass.

- [ ] **Step 7: Commit parity and configuration**

```bash
git add adapter_service/app/services/workflow_profiles.py adapter_service/app/services/provider_client.py adapter_service/standalone_adapter.py adapter_service/tests/test_workflow_profiles.py adapter_service/tests/test_review_mode_contract.py adapter_service/tests/test_packaging_scripts.py adapter_service/tests/test_ppt_slide_assistant.py config/adapter.example.json
git commit -m "feat: configure PPT workflow profiles"
```

## Task 5: Replace The Probe With The Read-Only PPT Task Pane

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Add failing final-UI and read-only assertions**

Assert the PPT HTML contains:

```javascript
[
  'id="workflow-profile-select"',
  'id="ppt-slide-summary"',
  'id="ppt-slide-instruction"',
  'id="btn-run-primary"',
  'id="btn-result-preview"',
  'id="btn-result-plain"',
  'id="btn-copy-title"',
  'id="btn-copy-bullets"',
  'id="btn-copy-conclusion"',
  'id="btn-copy-result"'
].forEach(token => assert.ok(pptHtml.includes(token)));
```

Assert JavaScript contains `/ppt/slide-assistant/jobs`, `ppt.slide_assistant`, `clientJobId`, 10-second status request timeout, 240 retry errors, 60-minute recovery budget, and local storage key `ai-wps-ppt-slide-assistant-active-job-v1`.

Assert it does not contain `Slides.Add`, `Shapes.Add`, `TextRange.Text =`, `writeSlide`, `applySlide`, `insertSlide`, or a button ID containing `apply`.

- [ ] **Step 2: Add failing result composition tests**

Export and test:

```javascript
const markdown = helpers.buildPptSlideMarkdown({
  suggestedTitle: "项目总体进展",
  bullets: ["方案设计已完成", "系统进入联调阶段", "重点关注接口稳定性"],
  conclusion: "项目按计划推进。"
});
assert.ok(markdown.includes("## 建议标题"));
assert.ok(markdown.includes("- 方案设计已完成"));
assert.ok(markdown.includes("## 本页结论"));

assert.strictEqual(
  helpers.buildPptSlidePlainText({ suggestedTitle: "标题", bullets: ["要点一", "要点二", "要点三"], conclusion: "结论" }),
  "标题\n\n1. 要点一\n2. 要点二\n3. 要点三\n\n结论"
);
```

- [ ] **Step 3: Run frontend tests and verify failure**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL for missing final controls and result builders.

- [ ] **Step 4: Build the final task-pane markup and layout**

Use one unframed workflow strip, one compact controls panel, and one result panel. The result preview has three semantic sections and the copy actions remain in a fixed-height toolbar. Use `border-radius` no larger than 8px and stable button dimensions. At 420x900, long workflow names wrap or ellipsize without pushing buttons outside the pane.

The primary action is always labeled `生成本页内容`; there is no generate/optimize selector. Show page index, title, body character count, adjacent-title availability, and truncation state in `ppt-slide-summary`.

- [ ] **Step 5: Implement submit and automatic mode flow**

On click:

```javascript
setStatus("正在读取当前幻灯片...");
setPlainResult("正在读取当前幻灯片，请稍候。");
setTimeout(function () {
  const payload = helpers.extractPresentationSlide(getWppApplication(), PPT_EXTRACTION_LIMITS);
  payload.userInstruction = safeText(byId("ppt-slide-instruction").value).slice(0, 1000);
  payload.clientJobId = buildPptSlideClientJobId();
  submitPptSlideJob(payload);
}, 0);
```

Do not send a `mode` field. The adapter owns mode selection. If the slide has fewer than 20 non-whitespace body characters and the instruction is empty, show `请填写本页主题或生成要求。` without calling `fetch`.

- [ ] **Step 6: Implement recoverable job polling**

Use these constants:

```javascript
var PPT_SLIDE_POLL_INTERVAL_MS = 3000;
var PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS = 15000;
var PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS = 30000;
var PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS = 10000;
var PPT_SLIDE_POLL_MAX_ERRORS = 240;
var PPT_SLIDE_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
var PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY = "ai-wps-ppt-slide-assistant-active-job-v1";
```

Treat only `PPT_SLIDE_JOB_NOT_FOUND` and `REQUEST_VALIDATION_FAILED` as fatal status-query errors. Preserve job ID through network failures. On `completed`, render and clear storage; on `failed`, display the job error and clear storage.

- [ ] **Step 7: Implement preview, plain text, and four copy actions**

Structured results use `buildPptSlideMarkdown`. When `rawAnswer` is present, render the sanitized final answer and set all structured copy buttons disabled except `复制完整结果`. Copy operations use `navigator.clipboard.writeText` with the existing hidden-textarea fallback.

- [ ] **Step 8: Add PPT-only workflow profile management and diagnostics**

Use only:

```javascript
var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";
var TASK_API_KEY_DEFS = [
  { taskType: "ppt.slide_assistant", label: "PPT 单页助手" }
];
```

Reuse the existing provider/profile API endpoints and data shapes. Do not render Word or Excel profile sections. Diagnostics remain read-only and must not expose key text or full slide content.

- [ ] **Step 9: Run syntax, helper, layout, and 420x900 visual checks**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js
```

Open `taskpane.html` at 420x900 and inspect home, structured result, raw fallback, long workflow name, and settings states. Expected: no overlap, no horizontal scrolling, no clipped buttons, and no writeback control.

- [ ] **Step 10: Commit the final PPT task pane**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0 formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: add read-only PPT slide assistant UI"
```

## Task 6: Add One-Package Installation And Release Documentation

**Files:**
- Modify: `phase1-delivery-kit/wps-jsaddons/publish.xml`
- Modify: `phase1-delivery-kit/installer/install_phase1.sh`
- Modify: `phase1-delivery-kit/scripts/phase1_smoke_test.sh`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Modify: `packaging/build_phase1_delivery_kit.sh`
- Create: `docs/operations/dify-ppt-slide-assistant-workflow.md`
- Modify: `docs/operations/workflow-profile-management.md`
- Modify: `adapter_service/tests/test_packaging_scripts.py`

- [ ] **Step 1: Write failing three-add-in packaging tests**

Assert all of the following:

```python
self.assertIn('PPT_PLUGIN_NAME="wps-ai-assistant-wpp_1.0.0"', installer)
self.assertIn('name="wps-ai-assistant-wpp"', installer)
self.assertIn('type="wpp"', installer)
self.assertIn('grep -v \'name="wps-ai-assistant-wpp"\'', installer)
self.assertIn("PPT_FORMAL_SRC", build_script)
self.assertIn("wps-ai-assistant-wpp_1.0.0", build_script)
self.assertIn("dify-ppt-slide-assistant-workflow.md", build_script)
self.assertIn('name="wps-ai-assistant-wpp"', publish_xml)
self.assertIn('type="wpp"', publish_xml)
```

Retain existing assertions for `preserve_adapter_runtime_config`, `config/adapter.json`, `provider_api_key`, and `provider_api_keys`.

- [ ] **Step 2: Run packaging tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected: FAIL for missing PPT package/install tokens.

- [ ] **Step 3: Add PPT to publish.xml and installer merge logic**

Add:

```xml
<jsplugin name="wps-ai-assistant-wpp" url="file://" type="wpp" enable="enable_dev" version="1.0.0"/>
```

The installer must verify and copy all three source folders. When merging an existing `publish.xml`, emit the three AI-WPS entries once, filter old copies of all three names, and preserve unrelated third-party `<jsplugin>` entries.

- [ ] **Step 4: Extend smoke and package builders**

`phase1_smoke_test.sh` must fail when the PPT directory or `type="wpp"` entry is missing. `build_phase1_delivery_kit.sh` must copy the PPT add-in and PPT Dify guide into the same delivery tarball as Word and Excel.

- [ ] **Step 5: Write the Dify operations guide**

Document task type `ppt.slide_assistant`, `/chat-messages`, workflow profile selection, input budget, generate/optimize decision, fixed Markdown output, JSON compatibility, think stripping, 1800-second provider budget, and the rule that the model must not claim it modified PPT.

- [ ] **Step 6: Run packaging tests and shell syntax checks**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
bash -n packaging/build_phase1_delivery_kit.sh
bash -n phase1-delivery-kit/installer/install_phase1.sh
bash -n phase1-delivery-kit/scripts/phase1_smoke_test.sh
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit packaging and operations docs**

```bash
git add phase1-delivery-kit packaging/build_phase1_delivery_kit.sh docs/operations/dify-ppt-slide-assistant-workflow.md docs/operations/workflow-profile-management.md adapter_service/tests/test_packaging_scripts.py
git commit -m "build: package WPS presentation assistant"
```

## Task 7: Bump Version, Run Full Regression, Build Delivery, And Record Target Acceptance

**Files:**
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `adapter_service/tests/test_health.py`
- Modify: `adapter_service/tests/test_review_mode_contract.py`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/index.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/manifest.json`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/index.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710-v0170.tar.gz`

- [ ] **Step 1: Update failing version expectations first**

Change tests to require `0.17.0-alpha` and six tasks. Run the focused version tests before implementation.

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_health adapter_service.tests.test_review_mode_contract adapter_service.tests.test_packaging_scripts -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL on old `0.16.0-alpha` tokens.

- [ ] **Step 2: Bump every executable and cache version token**

Replace executable version values with `0.17.0-alpha`, including FastAPI, standalone, diagnostics, startup expected version, three manifests, three Ribbon build query strings, and all task-pane CSS/JS cache query strings. Do not change plugin folder version `1.0.0` or publish entry version `1.0.0`.

- [ ] **Step 3: Update README and handoff**

Record:

- PPT single-slide assistant scope and read-only boundary.
- `ppt.slide_assistant` API key/workflow profile.
- POST/GET background job endpoints.
- 4600-character dynamic budget.
- Kylin WPS presentation probe result.
- Word/Excel/PPT host isolation.
- Combined delivery package path and checksum.
- Exact regression test counts after the final run.

Correct `docs/codex-handoff.md` current branch to `main`.

- [ ] **Step 4: Run the full automated regression suite**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/standalone_adapter.py adapter_service/app/api/ppt.py adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/app/services/ppt/slide_assistant.py adapter_service/app/services/ppt/slide_assistant_jobs.py
git diff --check
```

Expected: all commands exit 0; only dependency-conditioned tests may skip.

- [ ] **Step 5: Build and inspect the combined delivery package**

Run:

```bash
DATE_TAG=20260710-v0170 bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710-v0170.tar.gz | rg 'wps-ai-assistant(_1.0.0|-et_1.0.0|-wpp_1.0.0)|dify-ppt-slide-assistant-workflow.md'
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710-v0170.tar.gz
```

Expected: one tarball contains all three add-ins and the PPT operations guide. Record the checksum in README, handoff, and acceptance record.

- [ ] **Step 6: Execute final target-machine acceptance**

Install the single package over `v0.16.0-alpha`. Verify:

1. Existing API URL, unified key, Word/Excel task keys, and workflow profiles remain.
2. Word, Excel, and PPT show only their own Ribbon controls.
3. Existing-content slide uses optimize mode.
4. Title-only and blank slides require an instruction and use generate mode.
5. Multiple text boxes preserve block boundaries.
6. Adjacent slides contribute titles only.
7. Truncated input displays a visible warning.
8. JSON, Markdown, raw fallback, and think responses remain visible.
9. A model task exceeding 180 seconds continues polling and recovers after reopening the pane.
10. No PPT content, layout, object, or notes are modified.

Record pass/fail evidence in `phase1-delivery-kit/docs/phase1-acceptance-record.md`.

- [ ] **Step 7: Commit the release**

Stage explicit release paths only; do not stage historical archive noise:

```bash
git add README.md README-ZH.md docs/codex-handoff.md adapter-start-kit adapter_service config formal-plugin-kit phase1-delivery-kit packaging docs/operations dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710-v0170.tar.gz
git commit -m "release: publish v0.17.0-alpha"
git push origin main
```

## Final Completion Criteria

- The Kylin V10 WPS Presentation probe passed before model integration began.
- `ppt.slide_assistant` has isolated workflow profiles and API key routing.
- Dynamic input is bounded to 4600 characters and only adjacent titles are read.
- Task status uses `running`, `completed`, and `failed` consistently.
- Slow and interrupted tasks retain `clientJobId` and resume polling.
- PPT results support structured preview, plain text, four copy actions, and raw fallback.
- No PPT write API exists in the add-in.
- Word and Excel tests and target workflows remain unchanged and passing.
- One installer contains Word, Excel, and PPT and preserves runtime configuration.
- README, handoff, operations docs, acceptance evidence, package checksum, and version tokens agree on `0.17.0-alpha`.
