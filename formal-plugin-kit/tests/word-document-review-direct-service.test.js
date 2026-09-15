const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

function loadFn(name, ctx) {
  return vm.runInNewContext(`(${functionSource(name)})`, ctx);
}

test("Compact menu items: word.document_review includes shared direct services", () => {
  const profiles = [
    { id: "wf_1", name: "文档审查平台配置", taskType: "word.document_review", complete: true }
  ];
  const directServices = [
    {
      id: "direct_svc_1",
      name: "企业直连服务",
      keyConfigured: true,
      serviceBaseUrl: "https://api.openai.com/v1",
      defaultModel: "gpt-4o"
    }
  ];

  const items = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_1",
    taskType: "word.document_review",
    directServices: directServices,
    taskModelSelection: {
      serviceId: "direct_svc_1",
      modelName: "gpt-4o",
      maxOutputTokens: 2048,
      contextWindowTokens: 40000
    }
  });

  assert.ok(items.length >= 3, "should include profile, direct service, and manage items");
  const directItem = items.find(i => i.id === "direct_svc_1");
  assert.ok(directItem, "direct service item must exist for word.document_review");
  assert.strictEqual(directItem.selected, true);
  assert.strictEqual(directItem.label, "企业直连服务 · 模型直连");
  assert.strictEqual(directItem.disabled, false);
});

test("Settings section: renders direct service card for word.document_review with generic access title", () => {
  const mockNodes = {};
  const nodeIds = [
    "word-task-direct-service-section",
    "word-task-direct-service-title",
    "word-task-direct-service-hint",
    "word-task-direct-service-select",
    "word-task-direct-params",
    "word-task-model-select",
    "word-task-custom-model-check",
    "word-task-custom-model-row",
    "word-task-custom-model-input",
    "word-task-temperature",
    "word-task-max-output",
    "word-task-context",
    "word-task-image-mode-row",
    "word-task-image-input-mode",
    "word-task-model-cost-warning",
    "word-task-model-validation-status"
  ];
  nodeIds.forEach(id => {
    mockNodes[id] = {
      id,
      textContent: "",
      innerHTML: "",
      value: "",
      checked: false,
      disabled: false,
      hidden: false,
      style: {}
    };
  });

  const state = {
    settingsWorkflowTaskType: "word.document_review",
    workflowProfiles: { "word.document_review": { activeProfileId: "direct_svc_doc", profiles: [] } },
    directServices: [
      {
        id: "direct_svc_doc",
        name: "文档模型服务",
        defaultModel: "gpt-4o",
        modelList: ["gpt-4o", "gpt-4o-mini"],
        keyConfigured: true,
        serviceBaseUrl: "https://api.openai.com/v1"
      }
    ],
    taskModelSelections: {
      "word.document_review": {
        serviceId: "direct_svc_doc",
        modelName: "gpt-4o",
        temperature: 0.2,
        maxOutputTokens: 4096,
        contextWindowTokens: 64000
      }
    }
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    getWorkflowProfileData(task) {
      return {
        activeProfileId: state.workflowProfiles[task] ? state.workflowProfiles[task].activeProfileId : ""
      };
    },
    escapeWorkflowText(s) { return s || ""; }
  };
  ctx.findDirectService = loadFn("findDirectService", ctx);
  ctx.renderTaskModelSelectionSection = loadFn("renderTaskModelSelectionSection", ctx);

  ctx.renderTaskModelSelectionSection();

  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false, "section must be visible for word.document_review");
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "接入选择", "title must follow the selected tab context");
  assert.strictEqual(mockNodes["word-task-image-mode-row"].hidden, true, "image mode row must be hidden for document review");
  assert.strictEqual(mockNodes["word-task-max-output"].value, 4096);
  assert.strictEqual(mockNodes["word-task-context"].value, 64000);
});

test("getFullDocumentReviewReadiness handles shared direct service readiness", () => {
  // Scenario A: Direct service is ready
  const stateReady = {
    directServices: [{ id: "direct_svc_1", name: "直连服务" }],
    taskModelSelections: {
      "word.document_review": {
        serviceId: "direct_svc_1",
        fullDocumentReviewReady: true,
        fullDocumentReviewReadiness: {
          code: "ready",
          label: "限量审查与全篇审查均可用。"
        }
      }
    }
  };

  const ctxReady = {
    state: stateReady,
    getWorkflowProfileData() {
      return {
        activeProfileId: "direct_svc_1",
        profiles: [],
        taskModelSelection: stateReady.taskModelSelections["word.document_review"]
      };
    }
  };

  const fnReady = loadFn("getFullDocumentReviewReadiness", ctxReady);
  const resReady = fnReady();
  assert.strictEqual(resReady.fullDocumentReviewReady, true);
  assert.strictEqual(resReady.label, "限量审查与全篇审查均可用。");

  // Scenario B: Direct service lacks explicit tokens
  const stateUnready = {
    directServices: [{ id: "direct_svc_1", name: "直连服务" }],
    taskModelSelections: {
      "word.document_review": {
        serviceId: "direct_svc_1",
        fullDocumentReviewReady: false,
        fullDocumentReviewReadiness: {
          code: "explicit_output_tokens_required",
          label: "仅限量审查可用：请显式设置最大输出 Token。"
        }
      }
    }
  };

  const ctxUnready = {
    state: stateUnready,
    getWorkflowProfileData() {
      return {
        activeProfileId: "direct_svc_1",
        profiles: [],
        taskModelSelection: stateUnready.taskModelSelections["word.document_review"]
      };
    }
  };

  const fnUnready = loadFn("getFullDocumentReviewReadiness", ctxUnready);
  const resUnready = fnUnready();
  assert.strictEqual(resUnready.fullDocumentReviewReady, false);
  assert.strictEqual(resUnready.label, "仅限量审查可用：请显式设置最大输出 Token。");
});

test("Preflight readiness check: validateActiveDirectTaskSelection gates word.document_review", () => {
  const state = {
    directServices: [
      {
        id: "direct_svc_ready",
        name: "就绪服务",
        keyConfigured: true,
        serviceBaseUrl: "https://api.openai.com/v1",
        defaultModel: "gpt-4o",
        modelList: ["gpt-4o"]
      },
      {
        id: "direct_svc_nokey",
        name: "无Key服务",
        keyConfigured: false,
        serviceBaseUrl: "https://api.openai.com/v1",
        defaultModel: "gpt-4o",
        modelList: ["gpt-4o"]
      }
    ],
    taskApiKeys: {
      "word.document_review": {
        accessMethod: "direct_model",
        activeProfileId: "direct_svc_nokey"
      }
    },
    taskModelSelections: {
      "word.document_review": {
        serviceId: "direct_svc_nokey",
        modelName: "gpt-4o"
      }
    }
  };

  const ctx = {
    state,
    helpers,
    byId() { return null; }
  };
  ctx.findDirectService = loadFn("findDirectService", ctx);
  ctx.validateActiveDirectTaskSelection = loadFn("validateActiveDirectTaskSelection", ctx);

  // 1. 无 Key 服务 -> 校验不通过
  const checkNoKey = ctx.validateActiveDirectTaskSelection("word.document_review");
  assert.strictEqual(checkNoKey.valid, false, "service without key must be invalid");

  // 2. 切换为就绪服务 -> 校验通过
  state.taskApiKeys["word.document_review"].activeProfileId = "direct_svc_ready";
  state.taskModelSelections["word.document_review"].serviceId = "direct_svc_ready";
  const checkReady = ctx.validateActiveDirectTaskSelection("word.document_review");
  assert.strictEqual(checkReady.valid, true, "ready service must be valid");

  // 3. 工作流配置 -> applicable 为 false，valid 为 true
  state.taskApiKeys["word.document_review"].accessMethod = "workflow_platform";
  state.taskApiKeys["word.document_review"].activeProfileId = "wf_profile_1";
  const checkWf = ctx.validateActiveDirectTaskSelection("word.document_review");
  assert.strictEqual(checkWf.applicable, false);
  assert.strictEqual(checkWf.valid, true);
});

test("Preflight gate: runDocumentReview invokes validateActiveDirectTaskSelection('word.document_review')", () => {
  assert.ok(
    js.includes('validateActiveDirectTaskSelection("word.document_review")'),
    "runDocumentReview must call validateActiveDirectTaskSelection('word.document_review')"
  );
});
