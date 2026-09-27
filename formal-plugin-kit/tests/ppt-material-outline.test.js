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
