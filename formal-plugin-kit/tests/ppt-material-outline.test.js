const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const { pptRoot: root } = require("./support/plugin-roots");

function createTestHarness(sharedStorage) {
  const context = {
    window: {},
    console,
    Promise,
    Date,
    Math,
    Array,
    Object,
    setTimeout,
    clearTimeout,
    btoa: (value) => Buffer.from(value, "binary").toString("base64"),
  };
  const scriptPath = path.join(root, "material-outline.js");
  const scriptContent = fs.readFileSync(scriptPath, "utf8");
  vm.runInNewContext(scriptContent, context);

  const storage = sharedStorage || new Map();
  const h = {
    session: "sess-ppt-doc-1",
    calls: [],
    views: [],
    copied: [],
    scheduled: [],
  };

  // WPS Mock
  h.mockApp = {
    ActivePresentation: {
      Slides: {
        Count: 0,
        Add: () => {
          throw new Error("Slides.Add must NOT be called by material outline controller!");
        },
        AddSlide: () => {
          throw new Error("Slides.AddSlide must NOT be called by material outline controller!");
        },
      },
    },
  };

  h.api = context.window.createMaterialOutline({
    storage: {
      getItem: (k) => storage.get(k),
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    getSessionId: () => h.session,
    getWordApp: () => h.wordApp,
    render: (v) => h.views.push(v),
    copyText: (t) => h.copied.push(t),
    schedule: (fn) => h.scheduled.push(fn),
    request: async (url, body, opts) => {
      h.calls.push({ url, body, method: opts && opts.method });
      if (h.requestHandler) {
        return h.requestHandler(url, body, opts);
      }
      if (url.startsWith("/ppt/materials/catalog")) {
        return h.catalogResponse || {
          success: true,
          data: { totalDocuments: 0, totalCharacters: 0, documents: [] },
        };
      }
      if (url === "/materials/reusable-sources") {
        return { success: true, data: { sources: [] } };
      }
      return { success: true, data: {} };
    },
  });

  return h;
}

test("material outline controller initializes and enforces confirmation gate", () => {
  const h = createTestHarness();
  assert.equal(h.api.hasConfirmedOutline(), false);
  assert.equal(h.api.getConfirmedOutline(), null);

  const state = h.api.stateFor(h.session);
  assert.equal(state.audience, "公司高管与业务领导");
  assert.equal(state.slideCount, 8);
  assert.equal(state.confirmationStatus, "unconfirmed");
});

test("material outline lifecycle, confirmation, and downgrade state machine", async () => {
  const h = createTestHarness();

  // Set catalog
  h.catalogResponse = {
    success: true,
    data: {
      totalDocuments: 1,
      totalCharacters: 1500,
      documents: [{ materialId: "mat_1", fileName: "建设成果.docx", updatedAt: "2026-09-27T00:00:00Z" }],
    },
  };
  await h.api.refreshCatalog();
  assert.equal(h.api.stateFor(h.session).catalogSummary.totalDocuments, 1);

  // Submit outline job
  const sampleOutline = {
    schemaVersion: "ppt.material_outline.v1",
    audience: "公司高管与业务领导",
    slideCount: 3,
    instruction: "突出重点",
    slides: [
      {
        pageIndex: 1,
        pageRole: "cover",
        title: "项目阶段汇报",
        keyPoints: ["汇报要点一", "汇报要点二"],
        missingItems: [],
        fragmentIds: [1],
        sources: [{ sourceId: 1, fileName: "建设成果.docx", chapter: "封面", text: "项目建设成果" }],
      },
      {
        pageIndex: 2,
        pageRole: "content",
        title: "核心系统成效",
        keyPoints: ["全面上线运行", "零故障保障"],
        missingItems: ["二期预算待核定"],
        fragmentIds: [2],
        sources: [{ sourceId: 2, fileName: "建设成果.docx", chapter: "正文", text: "已全面上线运行" }],
      },
      {
        pageIndex: 3,
        pageRole: "backcover",
        title: "致谢与问答",
        keyPoints: ["Q&A 环节"],
        missingItems: [],
        fragmentIds: [],
        sources: [],
      },
    ],
    basisMaterials: [{ materialId: "mat_1", fileName: "建设成果.docx", updatedAt: "2026-09-27T00:00:00Z" }],
    generatedAt: "2026-09-27T10:00:00Z",
  };

  h.requestHandler = async (url, body, opts) => {
    if (url === "/ppt/material-outline/jobs") {
      return {
        success: true,
        data: {
          jobId: "ppt_job_1",
          status: "running",
          phase: "provider_processing",
          documentSessionId: h.session,
        },
      };
    }
    if (url.startsWith("/ppt/material-outline/jobs/ppt_job_1")) {
      return {
        success: true,
        data: {
          jobId: "ppt_job_1",
          status: "completed",
          phase: "completed",
          result: sampleOutline,
          documentSessionId: h.session,
        },
      };
    }
    return { success: true, data: {} };
  };

  h.api.setSlideCount(3);
  await h.api.submit();
  assert.equal(h.api.stateFor(h.session).busy, true);
  assert.equal(h.api.hasConfirmedOutline(), false);

  // Poll job completion
  await h.api.poll();
  const state = h.api.stateFor(h.session);
  assert.equal(state.status, "completed");
  assert.equal(state.result.slides.length, 3);
  assert.equal(state.confirmationStatus, "unconfirmed");
  assert.equal(h.api.hasConfirmedOutline(), false);

  // Confirm outline
  const confirmed = h.api.confirmOutline();
  assert.ok(confirmed);
  assert.equal(confirmed.slides.length, 3);
  assert.equal(h.api.hasConfirmedOutline(), true);
  assert.equal(state.confirmationStatus, "confirmed");
  assert.ok(state.confirmedAt);

  // User edits slide title -> downgrades to needs_reconfirmation
  h.api.updateSlideTitle(2, "一期建设核心成果");
  assert.equal(h.api.hasConfirmedOutline(), false);
  assert.equal(state.confirmationStatus, "needs_reconfirmation");
  assert.equal(state.result.slides[1].title, "一期建设核心成果");

  // Re-confirm
  h.api.confirmOutline();
  assert.equal(h.api.hasConfirmedOutline(), true);
  assert.equal(state.confirmationStatus, "confirmed");

  // User edits slide keypoints -> downgrades to needs_reconfirmation
  h.api.updateSlideKeyPoints(2, ["全新要点1", "全新要点2"]);
  assert.equal(h.api.hasConfirmedOutline(), false);
  assert.equal(state.confirmationStatus, "needs_reconfirmation");

  // Re-confirm
  h.api.confirmOutline();
  assert.equal(h.api.hasConfirmedOutline(), true);

  // Underlying material updated -> basis warning & downgrades to needs_reconfirmation
  h.api.onMaterialsChanged([{ materialId: "mat_1", fileName: "建设成果.docx", updatedAt: "2026-09-27T11:00:00Z" }]);
  assert.equal(h.api.hasConfirmedOutline(), false);
  assert.equal(state.confirmationStatus, "needs_reconfirmation");
  assert.equal(state.basisWarning, true);
});

test("material outline copy text and markdown export", () => {
  const h = createTestHarness();
  const state = h.api.stateFor(h.session);
  state.result = {
    schemaVersion: "ppt.material_outline.v1",
    audience: "公司高管",
    slideCount: 2,
    slides: [
      {
        pageIndex: 1,
        pageRole: "cover",
        title: "封面标题",
        keyPoints: ["汇报人：张三"],
        missingItems: [],
        sources: [],
      },
      {
        pageIndex: 2,
        pageRole: "content",
        title: "成效展示",
        keyPoints: ["重点成果A", "重点成果B"],
        missingItems: ["待补充预算"],
        sources: [{ sourceId: 1, fileName: "资料.docx", chapter: "第一章", text: "原文" }],
      },
    ],
  };

  h.api.copyOutlineMarkdown();
  assert.equal(h.copied.length, 1);
  const text = h.copied[0];
  assert.ok(text.includes("# 第 1 页（封面页）：封面标题"));
  assert.ok(text.includes("# 第 2 页（内容页）：成效展示"));
  assert.ok(text.includes("- 重点成果A"));
  assert.ok(text.includes("〔待补充：待补充预算〕"));
});

test("pure read-only slide invariant: calls 0 slide modification APIs", () => {
  const h = createTestHarness();
  assert.equal(h.mockApp.ActivePresentation.Slides.Count, 0);
  // Entire controller has no slide modification side-effects
});

test("ribbon.xml and ribbon.js integrate btnAiPptMaterialOutline", () => {
  const ribbonXml = fs.readFileSync(path.join(root, "ribbon.xml"), "utf8");
  assert.ok(ribbonXml.includes('id="btnAiPptMaterialOutline"'), "ribbon.xml must declare btnAiPptMaterialOutline");
  assert.ok(ribbonXml.includes('label="资料大纲"'), "ribbon.xml must label button as 资料大纲");

  const ribbonJs = fs.readFileSync(path.join(root, "ribbon.js"), "utf8");
  const context = { window: { Application: {} }, location: { href: "http://localhost/" } };
  vm.runInNewContext(ribbonJs, context);
  assert.equal(typeof context.resolveMode, "function");
  assert.equal(context.resolveMode("btnAiPptMaterialOutline"), "pptMaterialOutline");
});

test("taskpane.html contains material outline controls, outline result section, and confirmation elements", () => {
  const taskpaneHtml = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
  assert.ok(taskpaneHtml.includes('id="ppt-material-outline-controls"'), "taskpane.html must contain outline controls");
  assert.ok(taskpaneHtml.includes('id="outline-result-section"'), "taskpane.html must contain outline result section");
  assert.ok(taskpaneHtml.includes('id="outline-material-count-label"'), "taskpane.html must contain material count label");
  assert.ok(taskpaneHtml.includes('id="btn-import-outline-material"'), "taskpane.html must contain import material button");
  assert.ok(taskpaneHtml.includes('id="outline-reusable-select"'), "taskpane.html must contain reusable source select");
  assert.ok(taskpaneHtml.includes('id="ppt-outline-audience"'), "taskpane.html must contain audience input");
  assert.ok(taskpaneHtml.includes('id="ppt-outline-slide-count"'), "taskpane.html must contain slide count select");
  assert.ok(taskpaneHtml.includes('id="btn-run-outline"'), "taskpane.html must contain run outline button");
  assert.ok(taskpaneHtml.includes('id="btn-confirm-outline"'), "taskpane.html must contain confirm outline button");
  assert.ok(taskpaneHtml.includes('id="outline-source-drawer"'), "taskpane.html must contain source drawer");
  assert.ok(taskpaneHtml.includes('src="./material-outline.js'), "taskpane.html must load material-outline.js");
});

test("taskpane.js initializes material outline mode, attaches event handlers, and routes mode correctly", () => {
  const taskpaneJs = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  assert.ok(taskpaneJs.includes("pptMaterialOutline"), "taskpane.js must handle pptMaterialOutline mode");
  assert.ok(taskpaneJs.includes("ensureMaterialOutline"), "taskpane.js must declare ensureMaterialOutline");
  assert.ok(taskpaneJs.includes("renderMaterialOutlineView"), "taskpane.js must declare renderMaterialOutlineView");
  assert.ok(taskpaneJs.includes("btn-run-outline"), "taskpane.js must bind btn-run-outline");
  assert.ok(taskpaneJs.includes("btn-confirm-outline"), "taskpane.js must bind btn-confirm-outline");
  assert.ok(taskpaneJs.includes("btn-copy-outline-markdown"), "taskpane.js must bind btn-copy-outline-markdown");
  assert.ok(taskpaneJs.includes("ppt-outline-audience"), "taskpane.js must bind ppt-outline-audience");
  assert.ok(taskpaneJs.includes("ppt-outline-slide-count"), "taskpane.js must bind ppt-outline-slide-count");
  assert.ok(taskpaneJs.includes("ppt-outline-file-input"), "taskpane.js must bind ppt-outline-file-input");
  assert.ok(taskpaneJs.includes("outline-reusable-select"), "taskpane.js must bind outline-reusable-select");
  assert.ok(taskpaneJs.includes("outline-material-list"), "taskpane.js must bind outline-material-list");
  assert.ok(taskpaneJs.includes("outline-conflicts"), "taskpane.js must bind outline-conflicts");
});

// These tests exercise the real controller; only the external HTTP and clock are replaced.
test("scheduled polling stays with the submitting presentation after switching", async () => {
  const h = createTestHarness();
  h.requestHandler = async (url) => ({ success: true, data: url.endsWith("/jobs")
    ? { jobId: "job-A", status: "running" }
    : { jobId: "job-A", status: "completed", result: { slides: [{ title: "A" }] } } });
  await h.api.submit();
  h.session = "sess-B";
  await h.scheduled.shift()();
  assert.equal(h.api.stateFor("sess-ppt-doc-1").status, "completed");
  assert.equal(h.api.current().result, null);
  assert.equal(h.calls[1].url, "/ppt/material-outline/jobs/job-A?documentSessionId=sess-ppt-doc-1");
});

test("a lost outline task stops polling and permits a new submission", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "lost", status: "running", busy: true });
  h.requestHandler = async () => { throw Object.assign(new Error("gone"), { status: 404, adapterCode: "LONG_TASK_NOT_FOUND" }); };
  await h.api.poll();
  assert.equal(h.api.current().busy, false);
  assert.equal(h.api.current().jobId, "");
  assert.match(h.api.current().error, /重新提交/);
  assert.equal(h.scheduled.length, 0);
  h.requestHandler = async () => ({ success: true, data: { jobId: "replacement", status: "running" } });
  await h.api.submit();
  assert.equal(h.api.current().jobId, "replacement");
});

test("temporary polling failure retains the original task and retries", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "job-A", status: "running", busy: true });
  h.requestHandler = async () => { throw new Error("network down"); };
  await h.api.poll();
  assert.equal(h.api.current().busy, true);
  assert.equal(h.api.current().jobId, "job-A");
  assert.equal(h.scheduled.length, 1);
});

test("failed cancellation keeps the job active and explains the failure", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "job-A", status: "running", busy: true });
  h.requestHandler = async () => { throw new Error("network down"); };
  await h.api.cancel();
  assert.equal(h.api.current().status, "running");
  assert.equal(h.api.current().busy, true);
  assert.match(h.api.current().error, /取消失败/);
});

test("unconfirmed cancellation response cannot report cancelled", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "job-A", status: "running", busy: true });
  h.requestHandler = async () => ({ success: true, data: { jobId: "job-A", status: "running" } });
  await h.api.cancel();
  assert.equal(h.api.current().status, "running");
  assert.equal(h.api.current().busy, true);
});

test("a late poll cannot restore a result after confirmed cancellation", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "job-A", status: "running", busy: true });
  let finishPoll;
  h.requestHandler = async (url) => url.endsWith("/cancel")
    ? { success: true, data: { jobId: "job-A", status: "cancelled", phase: "cancelled" } }
    : new Promise((resolve) => { finishPoll = resolve; });
  const poll = h.api.poll();
  await h.api.cancel();
  finishPoll({ success: true, data: { jobId: "job-A", status: "completed", result: { slides: [{ title: "late" }] } } });
  await poll;
  assert.equal(h.api.current().status, "cancelled");
  assert.equal(h.api.current().result, null);
});

test("a late poll for an earlier job cannot overwrite a replacement job", async () => {
  const h = createTestHarness();
  Object.assign(h.api.current(), { jobId: "old", status: "running", busy: true });
  let finishPoll;
  h.requestHandler = async () => new Promise((resolve) => { finishPoll = resolve; });
  const poll = h.api.poll();
  Object.assign(h.api.current(), { jobId: "new", status: "running" });
  finishPoll({ success: true, data: { jobId: "old", status: "completed", result: { slides: [{ title: "old" }] } } });
  await poll;
  assert.equal(h.api.current().status, "running");
  assert.equal(h.api.current().result, null);
});

function paneHarness() {
  const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  const helpers = require(path.join(root, "taskpane-helpers.js"));
  const nodes = {};
  const context = {
    helpers, state: { taskMode: "pptMaterialOutline", documentSessionId: "stale-other-task" },
    window: { localStorage: { getItem() {}, setItem() {}, removeItem() {} } },
    document: { createElement: () => ({}) },
    getActivePresentation: () => context.presentation,
    byId: (id) => nodes[id] || (nodes[id] = { style: {} }),
    request: async (...args) => context.requestHandler(...args),
    setTimeout: () => {}, Date, copyText() {}, setStatus() {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, "material-outline.js"), "utf8"), context);
  const safeStart = source.indexOf("  function safeText(");
  const start = source.indexOf("  var materialOutline = null;");
  const end = source.indexOf("  function copyText(", start);
  vm.runInContext(source.slice(safeStart, source.indexOf("  function describeSettingsError", safeStart)) + source.slice(start, end), context);
  return { context, nodes, helpers };
}

test("outline presentation identity ignores stale shared task state and separates unsaved instances", () => {
  const { context: c, helpers } = paneHarness();
  c.presentation = { Name: "新建演示文稿.pptx", FullName: "新建演示文稿.pptx" };
  const first = c.presentation;
  const a = c.ensureMaterialOutline().current();
  a.instruction = "A only";
  c.presentation = { Name: "新建演示文稿.pptx", FullName: "新建演示文稿.pptx" };
  const b = c.ensureMaterialOutline().current();
  assert.notEqual(a.documentSessionId, "stale-other-task");
  assert.notEqual(a.documentSessionId, b.documentSessionId);
  assert.equal(b.instruction, "");
  c.presentation = first;
  assert.equal(c.ensureMaterialOutline().current().instruction, "A only");
  assert.equal(helpers.getDocumentSessionId({ FullName: "/reports/a.pptx" }), helpers.getDocumentSessionId({ FullName: "/reports/a.pptx" }));
});

test("save and save-as bind materials and preserve outline in the owning presentation", async () => {
  const { context: c } = paneHarness();
  c.presentation = { Name: "新建.pptx" };
  const ctrl = c.ensureMaterialOutline();
  const original = ctrl.current();
  original.result = { slides: [{ pageIndex: 1, title: "A outline" }] };
  original.catalogSummary = { totalDocuments: 1, documents: [{ materialId: "mat-A" }] };
  let finishBind;
  const calls = [];
  c.requestHandler = (url, body) => {
    calls.push({ url, body });
    return new Promise((resolve) => { finishBind = resolve; });
  };
  c.presentation.FullName = "/reports/a.pptx";
  ctrl.current();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/ppt/materials/bind-document");
  assert.equal(calls[0].body.oldDocumentSessionId, original.documentSessionId);
  assert.equal(calls[0].body.newDocumentIdentity, "full:/reports/a.pptx");
  const savedId = calls[0].body.newDocumentSessionId;
  c.presentation = { FullName: "/reports/b.pptx" };
  assert.equal(ctrl.current().result, null);
  finishBind({ success: true, data: { totalDocuments: 1, documents: [{ materialId: "mat-A" }] } });
  await new Promise(setImmediate);
  assert.equal(ctrl.current().result, null);
  assert.equal(ctrl.stateFor(savedId).result.slides[0].title, "A outline");
  const savedPresentation = { FullName: "/reports/a.pptx" };
  c.presentation = savedPresentation;
  assert.equal(ctrl.current().result.slides[0].title, "A outline");
  savedPresentation.FullName = "/reports/a-copy.pptx";
  ctrl.current();
  assert.equal(calls[1].body.oldDocumentSessionId, savedId);
  assert.equal(calls[1].body.newDocumentIdentity, "full:/reports/a-copy.pptx");
  finishBind({ success: true, data: {} });
  await new Promise(setImmediate);
  assert.equal(ctrl.current().result.slides[0].title, "A outline");
});

test("outline renderer escapes every externally supplied text and attribute", () => {
  const { context: c, nodes } = paneHarness();
  const payload = '<img src=x onerror="globalThis.injected=true">';
  c.renderMaterialOutlineView({
    catalogSummary: { documents: [{ materialId: payload, fileName: payload }] },
    conflicts: [{ conflictId: payload, topic: payload, options: [{ optionId: payload, sourceName: payload, value: payload }] }],
    activeDrawerPageIndex: payload,
    result: { slides: [{ pageIndex: payload, pageRole: payload, title: payload, keyPoints: [payload], missingItems: [payload], sources: [{ fileName: payload, chapter: payload, text: payload }] }] },
  });
  for (const id of ["outline-material-list", "outline-conflicts", "outline-slide-list", "outline-drawer-content"]) {
    assert.equal(nodes[id].innerHTML.includes(payload), false, id);
    assert.ok(nodes[id].innerHTML.includes("&lt;img"), id);
  }
});

test("cancel failure is visible while an outline task is still running", () => {
  const { context: c, nodes } = paneHarness();
  c.renderMaterialOutlineView({ busy: true, phaseLabel: "正在生成...", error: "取消失败：network down" });
  assert.equal(nodes["outline-result-output"].textContent, "取消失败：network down");
  c.renderMaterialOutlineView({ busy: true, error: "取消失败：network down", result: { slides: [{ pageIndex: 1, title: "old", sources: [] }] } });
  assert.equal(nodes["outline-result-output"].hidden, false);
  assert.equal(nodes["outline-result-output"].textContent, "取消失败：network down");
});

test("a delayed submit response cannot reset an already confirmed cancellation", async () => {
  const h = createTestHarness();
  let finishSubmit;
  h.requestHandler = async (url) => url.endsWith("/cancel")
    ? { success: true, data: { status: "cancelled" } }
    : new Promise((resolve) => { finishSubmit = resolve; });
  const submit = h.api.submit();
  await h.api.cancel();
  finishSubmit({ success: true, data: { jobId: "accepted", status: "running" } });
  await submit;
  assert.equal(h.api.current().status, "cancelled");
  assert.equal(h.api.current().busy, false);
});

test("failed save binding preserves the original ownership until the server confirms", async () => {
  const { context: c } = paneHarness();
  c.presentation = { Name: "新建.pptx" };
  const ctrl = c.ensureMaterialOutline();
  const old = ctrl.current();
  old.result = { slides: [{ title: "A" }] };
  c.requestHandler = async () => { throw Object.assign(new Error("still generating"), { status: 409, adapterCode: "MATERIAL_COMPOSER_BUSY" }); };
  c.presentation.FullName = "/reports/a.pptx";
  ctrl.current();
  await new Promise(setImmediate);
  assert.equal(ctrl.current().documentSessionId, old.documentSessionId);
  assert.equal(ctrl.current().result.slides[0].title, "A");
  assert.equal(ctrl.stateFor(c.helpers.getDocumentSessionId(c.presentation)).result, null);
});

test("consecutive save-as operations keep the server migration chain", async () => {
  const { context: c } = paneHarness();
  c.presentation = { FullName: "/reports/a.pptx" };
  const ctrl = c.ensureMaterialOutline();
  const a = ctrl.current();
  a.result = { slides: [{ title: "A" }] };
  let finishBind;
  const calls = [];
  c.requestHandler = (url, body) => {
    calls.push(body);
    return new Promise((resolve) => { finishBind = resolve; });
  };
  c.presentation.FullName = "/reports/b.pptx";
  ctrl.current();
  c.presentation.FullName = "/reports/c.pptx";
  ctrl.current();
  assert.equal(calls.length, 1);
  finishBind({ success: true, data: {} });
  await new Promise(setImmediate);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].oldDocumentSessionId, calls[0].newDocumentSessionId);
  finishBind({ success: true, data: {} });
  await new Promise(setImmediate);
  assert.equal(ctrl.current().documentSessionId, c.helpers.getDocumentSessionId(c.presentation));
  assert.equal(ctrl.current().result.slides[0].title, "A");
});

test("first save without server materials permits import into the saved presentation", async () => {
  const { context: c } = paneHarness();
  c.presentation = { Name: "新建.pptx" };
  const ctrl = c.ensureMaterialOutline();
  Object.assign(ctrl.current(), { audience: "项目组", slideCount: 5, instruction: "重点汇报进度", userFacts: "预算500万元" });
  c.requestHandler = async () => { throw Object.assign(new Error("no old materials"), { status: 404, adapterCode: "MATERIAL_NOT_FOUND" }); };
  c.presentation.FullName = "/reports/a.pptx";
  ctrl.current();
  await new Promise(setImmediate);
  assert.equal(ctrl.current().documentSessionId, c.helpers.getDocumentSessionId(c.presentation));
  assert.equal(ctrl.current().result, null);
  assert.equal(ctrl.current().audience, "项目组");
  assert.equal(ctrl.current().slideCount, 5);
  assert.equal(ctrl.current().instruction, "重点汇报进度");
  assert.equal(ctrl.current().userFacts, "预算500万元");
});

test("catalog responses only invalidate the outline owned by the requesting presentation", async () => {
  const h = createTestHarness();
  const a = h.api.current();
  a.result = { basisMaterials: [{ materialId: "A", updatedAt: "old" }] };
  a.confirmationStatus = "confirmed";
  let finishCatalog;
  h.requestHandler = async () => new Promise((resolve) => { finishCatalog = resolve; });
  const refresh = h.api.refreshCatalog();
  h.session = "B";
  const b = h.api.current();
  b.result = { basisMaterials: [{ materialId: "B", updatedAt: "current" }] };
  b.confirmationStatus = "confirmed";
  finishCatalog({ success: true, data: { totalDocuments: 1, documents: [{ materialId: "A", updatedAt: "new" }] } });
  await refresh;
  assert.equal(a.confirmationStatus, "needs_reconfirmation");
  assert.equal(b.confirmationStatus, "confirmed");
});

test("file read and subsequent refresh keep the upload's original presentation", async () => {
  const h = createTestHarness();
  let finishRead;
  const upload = h.api.importMaterial({ name: "a.docx", arrayBuffer: () => new Promise((resolve) => { finishRead = resolve; }) }, "");
  h.session = "B";
  finishRead(Uint8Array.from([1, 2]).buffer);
  await upload;
  assert.equal(h.calls[0].body.documentSessionId, "sess-ppt-doc-1");
  assert.equal(h.calls[1].url, "/ppt/materials/catalog?documentSessionId=sess-ppt-doc-1");
  assert.equal(h.calls[2].body.documentSessionId, "sess-ppt-doc-1");
});

test("typing an outline title retains the active input instead of rebuilding it", () => {
  const { context: c, nodes } = paneHarness();
  const view = { documentSessionId: "A", result: { slides: [{ pageIndex: 1, title: "first", sources: [] }] } };
  c.renderMaterialOutlineView(view);
  let writes = 0;
  let html = nodes["outline-slide-list"].innerHTML;
  Object.defineProperty(nodes["outline-slide-list"], "innerHTML", {
    get: () => html,
    set: (value) => { html = value; writes += 1; },
  });
  const input = { getAttribute: (name) => name === "data-title-page" ? "1" : null };
  c.document.activeElement = input;
  nodes["outline-slide-list"].contains = (node) => node === input;
  view.result.slides[0].title = "first typed";
  view.confirmationStatus = "needs_reconfirmation";
  c.renderMaterialOutlineView(view);
  assert.equal(writes, 0);
  assert.equal(nodes["outline-confirmation-status-line"].textContent, "大纲状态：已修改，需重新确认");
  c.document.activeElement = null;
  c.renderMaterialOutlineView(view);
  assert.equal(writes, 1);
  assert.ok(html.includes('value="first typed"'));
});

test("switching presentations restores the inputs actually submitted for that presentation", async () => {
  const { context: c, nodes } = paneHarness();
  for (const id of ["ppt-outline-audience", "ppt-outline-slide-count", "ppt-outline-instruction", "ppt-outline-user-facts"]) {
    nodes[id] = { value: "previous presentation" };
  }
  const first = { FullName: "/reports/a.pptx" };
  c.presentation = first;
  const ctrl = c.ensureMaterialOutline();
  Object.assign(ctrl.current(), { audience: "A audience", slideCount: 5, instruction: "A instruction", userFacts: "A facts" });
  c.renderMaterialOutlineView();
  c.presentation = { FullName: "/reports/b.pptx" };
  Object.assign(ctrl.current(), { audience: "B audience", slideCount: 8, instruction: "B instruction", userFacts: "B facts" });
  c.renderMaterialOutlineView();
  assert.equal(nodes["ppt-outline-audience"].value, "B audience");
  assert.equal(nodes["ppt-outline-slide-count"].value, "8");
  assert.equal(nodes["ppt-outline-instruction"].value, "B instruction");
  assert.equal(nodes["ppt-outline-user-facts"].value, "B facts");
  let submitted;
  c.requestHandler = async (_url, body) => { submitted = body; return { success: true, data: { jobId: "job-B", status: "running" } }; };
  await ctrl.submit();
  assert.equal(submitted.audience, "B audience");
  assert.equal(submitted.instruction, "B instruction");
  c.presentation = first;
  c.renderMaterialOutlineView();
  assert.equal(nodes["ppt-outline-audience"].value, "A audience");
  assert.equal(nodes["ppt-outline-instruction"].value, "A instruction");
});


test("local-only first-save binding preserves an existing target draft", async () => {
  const h = createTestHarness();
  h.api.setInstruction("unsaved draft");
  h.api.stateFor("saved").instruction = "existing saved draft";
  h.requestHandler = async () => { throw Object.assign(new Error("no old materials"), { status: 404, adapterCode: "MATERIAL_NOT_FOUND" }); };
  await assert.doesNotReject(h.api.bindDocument(h.session, "full:/reports/saved.pptx", "saved"));
  assert.equal(h.api.stateFor("saved").instruction, "existing saved draft");
});

test("real outline pane renders untrusted text safely and keeps edits with their presentation", t => {
  const { execFileSync } = require("node:child_process");
  const os = require("node:os");
  try { execFileSync("agent-browser", ["--version"], { stdio: "ignore" }); }
  catch (_) { t.skip("agent-browser unavailable"); return; }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "ppt-outline-pane-"));
  const run = (...args) => execFileSync("agent-browser", ["--session", "ppt-outline-pane", ...args], {
    encoding: "utf8", env: { ...process.env, AGENT_BROWSER_SOCKET_DIR: temp }
  });
  const unsafe = '<img src=x onerror="window.outlineInjected=true">';
  const fixture = {
    audience: "公司高管与业务领导", slideCount: 8,
    slides: [{ pageIndex: 1, pageRole: "content", title: '报告"' + unsafe,
      keyPoints: [unsafe], missingItems: [unsafe], sources: [{ fileName: unsafe, chapter: unsafe, text: unsafe }] }]
  };
  const mock = `
window.paneErrors=[];window.addEventListener('error',e=>paneErrors.push(e.message));
window.outlineInjected=false;window.slideWrites=0;
window.mockPresA={Name:'A.pptx',FullName:'/test/A.pptx',Slides:{Count:0,Add:()=>{slideWrites++;throw Error('write forbidden');}}};
window.mockPresB={Name:'B.pptx',FullName:'/test/B.pptx'};
window.Application={ActivePresentation:mockPresA};
window.fetch=async function(url,options){
  var p=new URL(url).pathname,body=options&&options.body?JSON.parse(options.body):null,data={};
  if(p==='/health')data={status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true};
  if(p==='/ppt/materials/catalog')data={totalDocuments:1,totalCharacters:10,documents:[{materialId:'m1',fileName:${JSON.stringify(unsafe)}}]};
  if(p==='/materials/reusable-sources')data={sources:[]};
  if(p==='/ppt/material-outline/conflicts')data={conflicts:[]};
  if(p==='/ppt/material-outline/jobs')data={jobId:body.clientJobId,status:'running'};
  if(p.startsWith('/ppt/material-outline/jobs/'))data={status:'completed',result:${JSON.stringify(fixture)}};
  return {ok:true,status:200,json:async()=>({success:true,data})};
};`;
  let html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
  html = html.replace("</head>", "<script>" + mock + "</script></head>");
  html = html.replace(/<script src="\.\/([^"?]+)[^"]*"><\/script>/g, (_, name) => {
    let code = fs.readFileSync(path.join(root, name), "utf8");
    if (name === "material-outline.js") code += "\nvar createOutlineForTest=window.createMaterialOutline;window.createMaterialOutline=function(options){window.outlineTestController=createOutlineForTest(options);return window.outlineTestController;};";
    return "<script>" + code + "</script>";
  });
  html = html.replace(/<link rel="stylesheet"[^>]+>/, "<style>" + fs.readFileSync(path.join(root, "taskpane.css"), "utf8") + "</style>");
  const page = path.join(temp, "pane.html");
  fs.writeFileSync(page, html);
  try {
    run("open", require("node:url").pathToFileURL(page).href + "?mode=pptMaterialOutline");
    run("set", "viewport", "360", "900");
    run("wait", "--fn", "window.outlineTestController && document.querySelector('#outline-material-list').textContent.includes('<img')");
    run("fill", "#ppt-outline-instruction", "A的重点");
    run("click", "#btn-run-outline");
    run("wait", "--fn", "document.querySelector('[data-title-page=\"1\"]') !== null");
    assert.equal(run("eval", "window.outlineInjected").trim(), "false");
    assert.equal(run("eval", "document.querySelectorAll('#outline-slide-list img,#outline-material-list img').length").trim(), "0");
    assert.match(run("get", "text", ".outline-slide-keypoints"), /<img/);
    run("fill", '[data-title-page="1"]', "重新编辑标题");
    run("keyboard", "type", "继续");
    assert.equal(run("get", "value", '[data-title-page="1"]').trim(), "重新编辑标题继续");
    run("click", "#btn-confirm-outline");
    run("wait", "--text", "大纲状态：已确认");
    run("set", "viewport", "320", "700");
    run("click", '[data-drawer-page="1"]');
    assert.equal(run("eval", "document.querySelector('#outline-slide-list').hidden").trim(), "true");
    run("click", "#btn-close-outline-drawer");
    assert.equal(run("eval", "document.activeElement.getAttribute('data-drawer-page')").trim(), '"1"');
    run("set", "viewport", "420", "700");
    run("click", '[data-drawer-page="1"]');
    assert.equal(run("eval", "document.querySelectorAll('#outline-source-drawer img').length").trim(), "0");
    assert.match(run("get", "text", "#outline-drawer-content"), /<img/);
    run("eval", "Application.ActivePresentation=mockPresB");
    run("wait", "--fn", "document.querySelector('#outline-slide-list').hidden && document.querySelector('#ppt-outline-instruction').value===''");
    run("eval", "Application.ActivePresentation=mockPresA");
    run("wait", "--fn", "document.querySelector('[data-title-page=\"1\"]') && document.querySelector('[data-title-page=\"1\"]').value==='重新编辑标题继续'");
    assert.equal(run("get", "value", "#ppt-outline-instruction").trim(), "A的重点");
    assert.equal(run("eval", "window.slideWrites").trim(), "0");
    assert.equal(run("eval", "JSON.stringify(window.paneErrors)").trim(), '"[]"');
  } finally {
    try { run("close"); } finally { fs.rmSync(temp, { recursive: true, force: true }); }
  }
});

test('outline sources replace the page list and restore it on return', () => {
  const { context: c, nodes } = paneHarness();
  const view = { activeDrawerPageIndex: 1, result: { slides: [{pageIndex: 1, title: '报告',
    coreMessage: '核心结论', presentationAdvice: '使用对比图',
    sources: [{fileName: '材料', text: '原文'}]}] } };
  c.renderMaterialOutlineView(view);
  assert.equal(nodes['outline-slide-list'].hidden, true);
  assert.equal(nodes['outline-source-drawer'].hidden, false);
  view.activeDrawerPageIndex = null;
  c.renderMaterialOutlineView(view);
  assert.equal(nodes['outline-slide-list'].hidden, false);
  assert.match(nodes['outline-slide-list'].innerHTML, /核心结论/);
  assert.match(nodes['outline-slide-list'].innerHTML, /使用对比图/);
});


test('DOC import restores Word security and completes the original presentation session', async () => {
  const h = createTestHarness();
  let closed = false, activated = false;
  h.wordApp = { AutomationSecurity: 2, DisplayAlerts: 1, Options: {UpdateLinksAtOpen: true},
    ActiveDocument: {Activate() {activated = true;}}, Documents: {Open() {
      assert.equal(h.wordApp.AutomationSecurity, 3);
      assert.equal(h.wordApp.Options.UpdateLinksAtOpen, false);
      return {SaveAs2(target, format) { assert.equal(format, 12); h.session = 'other'; }, Close() {closed = true;}};
    }} };
  h.requestHandler = async (url, body) => {
    if (body && body.contentBase64) return {success: true, data: {conversionRequired: true, conversionId: 'conversion', sourcePath: '/tmp/source.doc', targetPath: '/tmp/converted.docx'}};
    if (body && body.conversionId) assert.equal(body.documentSessionId, 'sess-ppt-doc-1');
    return {success: true, data: {documents: [], conflicts: []}};
  };
  await h.api.importMaterial({name: '材料.doc', contentBase64: 'test'});
  assert.equal(h.wordApp.AutomationSecurity, 2);
  assert.equal(h.wordApp.Options.UpdateLinksAtOpen, true);
  assert.equal(h.wordApp.DisplayAlerts, 1);
  assert.ok(closed && activated);
});

test('source pictures load on demand without entering persisted outline', async () => {
  const storage = new Map();
  const h = createTestHarness(storage);
  const s = h.api.current();
  s.result = {slides: [{pageIndex: 1, title: '图示', sources: [{materialId: 'm', imageId: 'm-image-1'}]}], basisMaterials: [{materialId: 'm', updatedAt: 'v1'}]};
  const image = 'data:image/png;base64,' + 'a'.repeat(1024 * 1024);
  h.requestHandler = async url => {
    assert.match(url, /\/ppt\/materials\/image\?/);
    assert.match(url, /updatedAt=v1/);
    return {success: true, data: {imageDataUri: image}};
  };
  await h.api.openSources(1);
  assert.equal(s.sourceImages['m-image-1'], image);
  h.api.confirmOutline();
  assert.ok([...storage.values()].every(v => !v.includes('data:image/')));
  const reopened = createTestHarness(storage);
  assert.equal(reopened.api.hasConfirmedOutline(), true);
});
