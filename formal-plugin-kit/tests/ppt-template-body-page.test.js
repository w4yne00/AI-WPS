const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const { pptRoot: root } = require("./support/plugin-roots");

function createTestHarness(options = {}) {
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
  const scriptPath = path.join(root, "template-body-page.js");
  if (fs.existsSync(scriptPath)) {
    const scriptContent = fs.readFileSync(scriptPath, "utf8");
    vm.runInNewContext(scriptContent, context);
  }

  const storage = options.storage || new Map();
  const h = {
    session: "sess-ppt-template-1",
    calls: [],
    views: [],
    scheduled: [],
    confirmedOutline: options.confirmedOutline || null,
  };

  h.createController = (extraOpts = {}) => {
    if (!context.window.createTemplateBodyPage) {
      throw new Error("createTemplateBodyPage is not defined");
    }
    return context.window.createTemplateBodyPage({
      storage: {
        getItem: (k) => storage.get(k),
        setItem: (k, v) => storage.set(k, v),
        removeItem: (k) => storage.delete(k),
      },
      getSessionId: () => h.session,
      getConfirmedOutline: () => h.confirmedOutline,
      hasConfirmedOutline: () => !!(h.confirmedOutline && h.confirmedOutline.confirmed),
      render: (v) => h.views.push(v),
      schedule: options.schedule || ((fn, ms) => setTimeout(fn, ms || 0)),
      request: async (url, body, opts) => {
        h.calls.push({ url, body, method: opts && opts.method });
        if (h.requestHandler) {
          return h.requestHandler(url, body, opts);
        }
        return { success: true, data: {} };
      },
      ...extraOpts,
    });
  };

  return { context, h };
}

test("evaluateSlideTextCapacity calculates capacity and enforces boundaries", async (t) => {
  const { context } = createTestHarness();
  const evaluate = context.window.evaluateSlideTextCapacity;
  assert.ok(evaluate, "evaluateSlideTextCapacity should be exported");

  // 1. Empty points
  const emptyRes = evaluate([]);
  assert.equal(emptyRes.totalPoints, 0);
  assert.equal(emptyRes.totalCharacters, 0);
  assert.equal(emptyRes.estimatedLines, 0);
  assert.equal(emptyRes.isOverflow, false);
  assert.equal(emptyRes.reasons.length, 0);

  // 2. Normal points (within limits: <=4 points, <=260 chars, <=8 lines)
  const normalPoints = [
    "分层解耦：采用标准微服务架构进行业务解耦与能力隔离",
    "安全可控：全栈适配自主可控技术体系，满足等保要求",
  ];
  const normalRes = evaluate(normalPoints);
  assert.equal(normalRes.totalPoints, 2);
  assert.equal(normalRes.totalCharacters, normalPoints[0].length + normalPoints[1].length);
  assert.equal(normalRes.estimatedLines, 2);
  assert.equal(normalRes.isOverflow, false);

  // 3. Points count overflow (>4 points)
  const fivePoints = ["要点1", "要点2", "要点3", "要点4", "要点5"];
  const fiveRes = evaluate(fivePoints);
  assert.equal(fiveRes.isOverflow, true);
  assert.ok(fiveRes.reasons.some((r) => r.includes("4")));

  // 4. Total characters overflow (>260 characters)
  const longPoint1 = "字".repeat(140);
  const longPoint2 = "字".repeat(130);
  const charOverflowRes = evaluate([longPoint1, longPoint2]);
  assert.equal(charOverflowRes.isOverflow, true);
  assert.ok(charOverflowRes.reasons.some((r) => r.includes("260")));

  // 5. Estimated lines overflow (>8 lines)
  // Each point wraps every 32 chars. 3 points of 70 chars each = ceil(70/32)=3 lines each -> 9 lines total.
  // Characters: 210 (<= 260), Points: 3 (<= 4), but lines: 9 (> 8)
  const wrapPoints = ["一".repeat(70), "二".repeat(70), "三".repeat(70)];
  const lineOverflowRes = evaluate(wrapPoints);
  assert.equal(lineOverflowRes.isOverflow, true);
  assert.ok(lineOverflowRes.reasons.some((r) => r.includes("8")));
});

test("outline gate blocks execution if outline is not confirmed", async (t) => {
  const { h } = createTestHarness({ confirmedOutline: null });
  const controller = h.createController();

  await assert.rejects(
    async () => {
      await controller.startGenerate({ pageIndex: 2 });
    },
    (err) => {
      return err.message.includes("请先确认逐页大纲");
    }
  );
});

test("candidate page selection validates pageRole and pageIndex", async (t) => {
  const sampleOutline = {
    confirmed: true,
    slides: [
      { pageIndex: 1, pageRole: "cover", title: "封面页", keyPoints: [] },
      { pageIndex: 2, pageRole: "content", title: "核心架构", keyPoints: ["要点一", "要点二"] },
      { pageIndex: 3, pageRole: "content", title: "实施路线", keyPoints: ["阶段一"] },
      { pageIndex: 4, pageRole: "backcover", title: "封底页", keyPoints: [] },
    ],
  };

  const { h } = createTestHarness({ confirmedOutline: sampleOutline });
  const controller = h.createController();

  // 1. Rejects non-content page (cover)
  await assert.rejects(
    async () => {
      await controller.startGenerate({ pageIndex: 1 });
    },
    (err) => err.message.includes("正文页")
  );

  // 2. Rejects non-existent page
  await assert.rejects(
    async () => {
      await controller.startGenerate({ pageIndex: 99 });
    },
    (err) => err.message.includes("不存在")
  );

  // 3. Default selection picks first content page (pageIndex 2)
  const candidate = controller.getCandidatePage();
  assert.equal(candidate.pageIndex, 2);
  assert.equal(candidate.title, "核心架构");
});

test("task lifecycle: start, poll, and handle model overflow rejection", async (t) => {
  const sampleOutline = {
    confirmed: true,
    slides: [
      { pageIndex: 2, pageRole: "content", title: "核心架构", keyPoints: ["要点一"] },
    ],
  };

  const { h } = createTestHarness({ confirmedOutline: sampleOutline });
  let polled = 0;

  // Mock server responses
  h.requestHandler = async (url, body, opts) => {
    if (url === "/ppt/template-page/jobs" && opts.method === "POST") {
      return {
        success: true,
        data: {
          jobId: "cjob_test_overflow_1",
          status: "running",
          phase: "provider_processing",
        },
      };
    }
    if (url.startsWith("/ppt/template-page/jobs/cjob_test_overflow_1")) {
      polled++;
      if (polled < 2) {
        return {
          success: true,
          data: {
            jobId: "cjob_test_overflow_1",
            status: "running",
            phase: "provider_processing",
          },
        };
      }
      // Return overflowing content from model (5 points > 4 limit)
      return {
        success: true,
        data: {
          jobId: "cjob_test_overflow_1",
          status: "completed",
          phase: "completed",
          result: {
            schemaVersion: "ppt.template_page.v1",
            pageIndex: 2,
            pageRole: "content",
            title: "核心架构设计",
            keyPoints: ["点1", "点2", "点3", "点4", "点5"],
            speakerNotes: "讲稿",
            sources: [],
          },
        },
      };
    }
    return { success: true };
  };

  const controller = h.createController({ pollIntervalMs: 10 });
  const result = await controller.startGenerate({ pageIndex: 2 });

  // When overflow defense kicks in, controller marks result as OVERFLOW_REJECTED
  assert.equal(result.status, "OVERFLOW_REJECTED");
  assert.equal(result.isOverflow, true);
  assert.ok(result.overflowReasons.length > 0);
  assert.equal(result.writtenToSlide, false);
});

test("cancelJob cancels running generation task", async (t) => {
  const sampleOutline = {
    confirmed: true,
    slides: [
      { pageIndex: 2, pageRole: "content", title: "核心架构", keyPoints: ["要点一"] },
    ],
  };

  const { h } = createTestHarness({ confirmedOutline: sampleOutline });
  let cancelledOnServer = false;

  h.requestHandler = async (url, body, opts) => {
    if (url === "/ppt/template-page/jobs" && opts.method === "POST") {
      return {
        success: true,
        data: { jobId: "cjob_to_cancel_1", status: "running", phase: "provider_processing" },
      };
    }
    if (url.includes("/cancel") && opts.method === "POST") {
      cancelledOnServer = true;
      return { success: true, data: { status: "cancelled" } };
    }
    if (url.startsWith("/ppt/template-page/jobs/cjob_to_cancel_1")) {
      return {
        success: true,
        data: { jobId: "cjob_to_cancel_1", status: "running", phase: "provider_processing" },
      };
    }
    return { success: true };
  };

  const controller = h.createController({ pollIntervalMs: 50 });
  const generatePromise = controller.startGenerate({ pageIndex: 2 });

  // Cancel immediately after starting
  await controller.cancelJob();
  const res = await generatePromise;

  assert.equal(res.status, "CANCELLED");
  assert.equal(controller.getState().status, "cancelled");
  assert.equal(cancelledOnServer, true);
});

test("handles server failure gracefully", async (t) => {
  const sampleOutline = {
    confirmed: true,
    slides: [
      { pageIndex: 2, pageRole: "content", title: "核心架构", keyPoints: ["要点一"] },
    ],
  };

  const { h } = createTestHarness({ confirmedOutline: sampleOutline });

  h.requestHandler = async (url, body, opts) => {
    if (url === "/ppt/template-page/jobs" && opts.method === "POST") {
      return {
        success: true,
        data: { jobId: "cjob_fail_1", status: "running" },
      };
    }
    if (url.startsWith("/ppt/template-page/jobs/cjob_fail_1")) {
      return {
        success: true,
        data: {
          jobId: "cjob_fail_1",
          status: "failed",
          error: { code: "MODEL_TIMEOUT", message: "模型调用超时" },
        },
      };
    }
    return { success: true };
  };

  const controller = h.createController({ pollIntervalMs: 10 });
  const res = await controller.startGenerate({ pageIndex: 2 });

  assert.equal(res.status, "FAILED");
  assert.equal(controller.getState().status, "failed");
  assert.equal(controller.getState().error.message, "模型调用超时");
});

test("appendTemplateBodySlide appends slide at Count + 1 and fills placeholders", async (t) => {
  const { context } = createTestHarness();
  const appendSlide = context.window.appendTemplateBodySlide;
  assert.ok(appendSlide, "appendTemplateBodySlide should be exported");

  // Mock Presentation with 3 existing slides
  const createdSlides = [];
  const mockLayout = { Name: "标题和内容", Index: 3 };

  const mockPres = {
    Designs: {
      Item: (idx) => ({
        SlideMaster: {
          CustomLayouts: {
            Count: 1,
            Item: (i) => mockLayout,
          },
        },
      }),
    },
    SlideMaster: {
      CustomLayouts: {
        Count: 1,
        Item: (i) => mockLayout,
      },
    },
    Slides: {
      Count: 3,
      Item: (i) => ({ Index: i }),
      AddSlide: (index, layout) => {
        const titleShape = {
          Name: "标题 1",
          PlaceholderFormat: { Type: 1 },
          TextFrame: { TextRange: { Text: "" } },
        };
        const bodyShape = {
          Name: "内容占位符 2",
          PlaceholderFormat: { Type: 2 },
          TextFrame: { TextRange: { Text: "" } },
        };
        const notesShape = {
          Name: "备注占位符",
          PlaceholderFormat: { Type: 2 },
          TextFrame: { TextRange: { Text: "" } },
        };
        const newSlide = {
          Index: index,
          Layout: layout,
          Shapes: {
            Count: 2,
            Item: (idx) => (idx === 1 ? titleShape : bodyShape),
            Placeholders: {
              Count: 2,
              Item: (idx) => (idx === 1 ? titleShape : bodyShape),
            },
          },
          NotesPage: {
            Shapes: {
              Placeholders: {
                Count: 1,
                Item: (idx) => notesShape,
              },
            },
          },
          deleted: false,
          Delete: function () {
            this.deleted = true;
            mockPres.Slides.Count--;
          },
        };
        mockPres.Slides.Count++;
        createdSlides.push(newSlide);
        return newSlide;
      },
    },
  };

  const mockApp = { ActivePresentation: mockPres };

  const result = {
    schemaVersion: "ppt.template_page.v1",
    pageIndex: 2,
    pageRole: "content",
    title: "核心系统架构",
    keyPoints: [
      "分层解耦：采用业务域服务化解耦架构",
      "安全可控：全栈适配自主可控基础设施",
    ],
    speakerNotes: "各位评委，这是总体架构设计要点。",
  };

  const appendRes = appendSlide(mockApp, result, {
    expectedSessionId: "sess-1",
    sessionId: "sess-1",
  });

  assert.equal(appendRes.success, true);
  assert.equal(appendRes.slideIndex, 4); // Count 3 -> appended at 4
  assert.equal(mockPres.Slides.Count, 4);
  assert.equal(createdSlides.length, 1);

  const slide = createdSlides[0];
  assert.equal(slide.Layout.Name, "标题和内容");
  assert.equal(slide.Shapes.Item(1).TextFrame.TextRange.Text, "核心系统架构");
  assert.ok(slide.Shapes.Item(2).TextFrame.TextRange.Text.includes("分层解耦"));
  assert.ok(slide.Shapes.Item(2).TextFrame.TextRange.Text.includes("安全可控"));
  assert.equal(slide.NotesPage.Shapes.Placeholders.Item(1).TextFrame.TextRange.Text, "各位评委，这是总体架构设计要点。");
});

test("appendTemplateBodySlide rejects on session mismatch", async (t) => {
  const { context } = createTestHarness();
  const appendSlide = context.window.appendTemplateBodySlide;

  const mockApp = { ActivePresentation: { Slides: { Count: 2 } } };
  const result = { title: "测试", keyPoints: ["点1"] };

  assert.throws(
    () => {
      appendSlide(mockApp, result, {
        expectedSessionId: "sess-original",
        sessionId: "sess-switched",
      });
    },
    (err) => err.message.includes("会话已变更")
  );
});

test("appendTemplateBodySlide performs reverse rollback compensation on write error", async (t) => {
  const { context } = createTestHarness();
  const appendSlide = context.window.appendTemplateBodySlide;

  let deletedCalled = false;
  const mockPres = {
    SlideMaster: { CustomLayouts: { Count: 1, Item: () => ({ Name: "标题和内容" }) } },
    Slides: {
      Count: 5,
      AddSlide: (index, layoutType) => {
        mockPres.Slides.Count++;
        return {
          Index: index,
          Shapes: {
            Count: 1,
            Item: () => {
              throw new Error("COM_DISP_E_BADPARAM: Shape text frame write error");
            },
          },
          Delete: () => {
            deletedCalled = true;
            mockPres.Slides.Count--;
          },
        };
      },
    },
  };

  const mockApp = { ActivePresentation: mockPres };
  const result = { title: "故障测试", keyPoints: ["要点"] };

  const rollbackRes = appendSlide(mockApp, result);

  assert.equal(rollbackRes.success, false);
  assert.equal(rollbackRes.status, "ROLLBACK_COMPENSATED");
  assert.equal(deletedCalled, true);
  assert.equal(mockPres.Slides.Count, 5); // Count restored back to initial 5
  assert.equal(rollbackRes.initialCount, 5);
  assert.equal(rollbackRes.currentCount, 5);
});

test("controller.appendSlide integrates with generator and prevents duplicate writes", async (t) => {
  const sampleOutline = {
    confirmed: true,
    slides: [
      { pageIndex: 2, pageRole: "content", title: "核心架构", keyPoints: ["要点一", "要点二"] },
    ],
  };

  const { h } = createTestHarness({ confirmedOutline: sampleOutline });

  h.requestHandler = async (url, body, opts) => {
    if (url === "/ppt/template-page/jobs" && opts.method === "POST") {
      return { success: true, data: { jobId: "cjob_success_write", status: "running" } };
    }
    if (url.startsWith("/ppt/template-page/jobs/cjob_success_write")) {
      return {
        success: true,
        data: {
          jobId: "cjob_success_write",
          status: "completed",
          result: {
            schemaVersion: "ppt.template_page.v1",
            pageIndex: 2,
            pageRole: "content",
            title: "核心系统架构",
            keyPoints: ["微服务解耦", "信创适配"],
            speakerNotes: "演讲备注",
          },
        },
      };
    }
    return { success: true };
  };

  const mockPres = regressionPresentation().pres;
  mockPres.Slides.Count = 2;

  const mockApp = { ActivePresentation: mockPres };

  const controller = h.createController({ pollIntervalMs: 10, wpsApp: mockApp });
  await controller.startGenerate({ pageIndex: 2 });

  const state = controller.getState();
  assert.equal(state.status, "completed");
  assert.equal(state.writtenToSlide, false);

  // 1. First append succeeds
  const writeRes = controller.appendSlide(mockApp);
  assert.equal(writeRes.success, true);
  assert.equal(writeRes.slideIndex, 3);
  assert.equal(mockPres.Slides.Count, 3);
  assert.equal(controller.getState().writtenToSlide, true);
  assert.equal(controller.getState().newSlideIndex, 3);

  // 2. Second append throws error (duplicate write prevention)
  assert.throws(
    () => {
      controller.appendSlide(mockApp);
    },
    (err) => err.message.includes("请勿重复写入")
  );
});

test("taskpane.html contains template body page markup and script tags", async (t) => {
  const htmlPath = path.join(root, "taskpane.html");
  const htmlContent = fs.readFileSync(htmlPath, "utf8");

  assert.ok(htmlContent.includes('src="./template-body-page.js'), "taskpane.html must load template-body-page.js");
  assert.ok(htmlContent.includes('id="ppt-template-page-card"'));
  assert.ok(htmlContent.includes('id="ppt-template-page-select"'));
  assert.ok(htmlContent.includes('id="btn-ppt-generate-template-page"'));
  assert.ok(htmlContent.includes('id="btn-ppt-cancel-template-page"'));
  assert.ok(htmlContent.includes('id="ppt-template-page-overflow-warning"'));
  assert.ok(htmlContent.includes('id="ppt-template-page-preview"'));
  assert.ok(htmlContent.includes('id="btn-ppt-append-slide-confirm"'));
});

function regressionPresentation(options = {}) {
  const layout = { Name: '标题和内容' };
  const shape = (type) => ({ PlaceholderFormat: { Type: type }, TextFrame: { TextRange: { Text: '', ParagraphFormat: { Bullet: { Type: 0 } } } } });
  const title = shape(1), body = shape(2), notes = shape(2);
  if (options.notesError) Object.defineProperty(notes.TextFrame.TextRange, 'Text', { get: () => '', set: () => { throw Error('notes write failed'); } });
  if (options.silentBody) Object.defineProperty(body.TextFrame.TextRange, 'Text', { get: () => '', set: () => {} });
  const shapes = options.noBody ? [title] : [title, body];
  const pres = {
    SlideMaster: { CustomLayouts: { Count: options.noLayout ? 0 : 1, Item: () => layout } },
    Slides: { Count: 3 }
  };
  const created = [];
  function add(index, selectedLayout) {
    pres.Slides.Count++;
    const slide = {
      SlideIndex: index, CustomLayout: selectedLayout,
      Shapes: { Count: shapes.length, Item: i => shapes[i - 1] },
      NotesPage: { Shapes: { Count: 1, Item: () => notes } },
      Delete() { if (options.deleteError) throw Error('delete failed'); pres.Slides.Count--; }
    };
    created.push(slide);
    return slide;
  }
  pres.Slides.AddSlide = add;
  pres.Slides.Add = add;
  return { app: { ActivePresentation: pres }, pres, created, title, body, notes };
}
const regressionOutline = () => ({ confirmed: true, slides: [{ pageIndex: 2, pageRole: 'content', title: '架构', keyPoints: ['分层'] }] });
const regressionResult = () => ({ title: '架构', keyPoints: ['分层', '隔离'], speakerNotes: '讲稿', sources: [{ fileName: '依据.docx', chapter: '第一章', text: '必须分层' }], missingItems: ['待补数据'] });
function generationHarness(options = {}) {
  const harness = createTestHarness({ confirmedOutline: regressionOutline() });
  harness.h.requestHandler = async (url, body) => ({ success: true, data: url === '/ppt/template-page/jobs' ? { jobId: body.clientJobId } : { status: 'completed', result: regressionResult() } });
  return { ...harness, controller: harness.h.createController({ pollIntervalMs: 1, ...options }) };
}

test('confirmed outline exposes template page card and renders only content candidates', () => {
  const { context, controller } = generationHarness();
  const nodes = {};
  context.byId = id => nodes[id] || (nodes[id] = { style: {}, value: '' });
  context.ensureTemplateBodyPage = () => controller;
  context.helpers = require(path.join(root, 'taskpane-helpers.js'));
  const source = fs.readFileSync(path.join(root, 'taskpane.js'), 'utf8');
  const start = source.indexOf('  function renderTemplateBodyPageView(view) {');
  vm.runInNewContext(source.slice(start, source.indexOf('  function copyText(', start)), context);
  context.renderTemplateBodyPageView();
  assert.equal(nodes['ppt-template-page-card'].hidden, false);
  assert.match(nodes['ppt-template-page-select'].innerHTML, /第 2 页/);
});

test('template page preview exposes escaped sources and missing facts', async () => {
  const { context, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  const nodes = {};
  context.byId = id => nodes[id] || (nodes[id] = { style: {}, value: '' });
  context.ensureTemplateBodyPage = () => controller;
  context.helpers = require(path.join(root, 'taskpane-helpers.js'));
  const source = fs.readFileSync(path.join(root, 'taskpane.js'), 'utf8');
  const start = source.indexOf('  function renderTemplateBodyPageView(view) {');
  vm.runInNewContext(source.slice(start, source.indexOf('  function copyText(', start)), context);
  const view = controller.getState();
  view.result.sources[0].text = '<img src=x onerror=alert(1)>必须分层';
  context.renderTemplateBodyPageView(view);
  const html = nodes['ppt-template-page-preview-content'].innerHTML;
  assert.match(html, /依据.docx/); assert.match(html, /第一章/); assert.match(html, /待补数据/);
  assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img/);
});

test('generated page cannot be appended to a different presentation session', async () => {
  const { h, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  h.session = 'other-session';
  const target = regressionPresentation();
  assert.throws(() => controller.appendSlide(target.app), /会话|演示文稿/);
  assert.equal(target.pres.Slides.Count, 3);
});

test('changed confirmed outline invalidates a generated page before writing', async () => {
  const { h, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  h.confirmedOutline.slides[0].title = '新的主题';
  const target = regressionPresentation();
  assert.throws(() => controller.appendSlide(target.app), /大纲|依据/);
  assert.equal(target.pres.Slides.Count, 3);
});

test('failed submission leaves a retryable failed state', async () => {
  const { h, controller } = generationHarness();
  h.requestHandler = async () => { throw Error('POST timeout'); };
  await assert.rejects(controller.startGenerate({ pageIndex: 2 }), /POST timeout/);
  assert.equal(controller.getState().status, 'failed');
});

for (const [label, options] of [['missing body', { noBody: true }], ['notes error', { notesError: true }], ['silent write', { silentBody: true }]]) {
  test('incomplete template page rolls back: ' + label, () => {
    const { context } = createTestHarness();
    const target = regressionPresentation(options);
    const result = context.window.appendTemplateBodySlide(target.app, regressionResult());
    assert.equal(result.success, false);
    assert.equal(result.status, 'ROLLBACK_COMPENSATED');
    assert.equal(target.pres.Slides.Count, 3);
  });
}

test('missing fixed layout refuses all slide writes', () => {
  const { context } = createTestHarness();
  const target = regressionPresentation({ noLayout: true });
  const result = context.window.appendTemplateBodySlide(target.app, regressionResult());
  assert.equal(result.success, false);
  assert.equal(target.pres.Slides.Count, 3);
});

test('failed rollback reports residual slide and blocks both append and regeneration', async () => {
  const { controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  const target = regressionPresentation({ notesError: true, deleteError: true });
  const result = controller.appendSlide(target.app);
  assert.equal(result.success, false);
  assert.equal(result.status, 'ROLLBACK_FAILED');
  assert.equal(result.currentCount, 4);
  assert.equal(result.slideIndex, 4);
  assert.throws(() => controller.appendSlide(target.app), /核查|恢复/);
  await assert.rejects(controller.startGenerate({ pageIndex: 2 }), /核查|恢复/);
  assert.equal(target.pres.Slides.Count, 4);
});

test('explicit newlines count against eight physical text lines', () => {
  const { context } = createTestHarness();
  const points = ['一\n'.repeat(12).trim(), '二\r\n'.repeat(12).trim()];
  const res = context.window.evaluateSlideTextCapacity(points);
  assert.equal(res.estimatedLines, 24);
  assert.equal(res.isOverflow, true);
});

test('write boundary independently refuses unflagged multiline overflow', () => {
  const { context } = createTestHarness();
  const target = regressionPresentation();
  assert.throws(() => context.window.appendTemplateBodySlide(target.app, { ...regressionResult(), keyPoints: ['一\n'.repeat(12).trim()], isOverflow: false }), /容量|超限/);
  assert.equal(target.pres.Slides.Count, 3);
});

test('generation finishes in preview without opening a write confirmation', async () => {
  const { context, controller } = generationHarness();
  let generation, handler, confirmations = 0;
  const startGenerate = controller.startGenerate;
  controller.startGenerate = (...args) => (generation = startGenerate(...args));
  context.byId = id => id === 'btn-ppt-generate-template-page' ? { addEventListener: (_, fn) => { handler = fn; } } : { value: '2' };
  context.ensureTemplateBodyPage = () => controller;
  context.window.confirm = () => { confirmations++; return false; };
  context.setStatus = () => {};
  const source = fs.readFileSync(path.join(root, 'taskpane.js'), 'utf8');
  const start = source.indexOf('    if (byId("btn-ppt-generate-template-page")) {');
  vm.runInNewContext(source.slice(start, source.indexOf('    if (byId("btn-ppt-cancel-template-page")) {', start)), context);
  handler(); await generation; await new Promise(setImmediate);
  assert.equal(confirmations, 0);
  assert.equal(controller.getState().status, 'completed');
});

test('late completed poll cannot revive a server-confirmed cancellation', async () => {
  const { h, controller } = generationHarness();
  let finishPoll, polled;
  const startedPoll = new Promise(resolve => { polled = resolve; });
  h.requestHandler = async (url, body) => {
    if (url === '/ppt/template-page/jobs') return { success: true, data: { jobId: body.clientJobId } };
    if (url.endsWith('/cancel')) return { success: true, data: { status: 'cancelled' } };
    return new Promise(resolve => { finishPoll = resolve; polled(); });
  };
  const pending = controller.startGenerate({ pageIndex: 2 });
  await startedPoll; await controller.cancelJob();
  finishPoll({ success: true, data: { status: 'completed', result: regressionResult() } });
  assert.equal((await pending).status, 'CANCELLED');
  assert.equal(controller.getState().status, 'cancelled');
  assert.equal(controller.getState().result, null);
});

test('failed cancellation is reported and is not mistaken for server cancellation', async () => {
  const { h, controller } = generationHarness();
  let finishPoll, polled;
  const startedPoll = new Promise(resolve => { polled = resolve; });
  h.requestHandler = async (url, body) => {
    if (url === '/ppt/template-page/jobs') return { success: true, data: { jobId: body.clientJobId } };
    if (url.endsWith('/cancel')) throw Error('cancel network failed');
    return new Promise(resolve => { finishPoll = resolve; polled(); });
  };
  const pending = controller.startGenerate({ pageIndex: 2 });
  await startedPoll;
  await assert.rejects(controller.cancelJob(), /cancel network failed/);
  assert.notEqual(controller.getState().status, 'cancelled');
  finishPoll({ success: true, data: { status: 'completed', result: regressionResult() } });
  await pending;
});

test('switching presentation hides previous generated preview', async () => {
  const { h, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  h.session = 'B';
  assert.equal(controller.getState().result, null);
});

test('rollback recovery remains blocked after reopening and clears only after manual cleanup', async () => {
  const { h, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  const target = regressionPresentation({ notesError: true, deleteError: true });
  controller.appendSlide(target.app);
  const reopened = h.createController();
  await assert.rejects(reopened.startGenerate({ pageIndex: 2 }), /核查|恢复/);
  assert.throws(() => reopened.verifyRecovery(target.app), /页数|清理|恢复/);
  assert.equal(target.pres.Slides.Count, 4);
  target.pres.Slides.Count = 3; // User removed the residual slide in WPS.
  reopened.verifyRecovery(target.app);
  assert.equal(reopened.getState().recoveryRequired, false);
});

test('unable to save a pending write refuses slide mutations', async () => {
  const { h } = generationHarness();
  const controller = h.createController({ storage: { getItem() {}, setItem() { throw Error('storage full'); }, removeItem() {} } });
  await controller.startGenerate({ pageIndex: 2 });
  const target = regressionPresentation();
  assert.throws(() => controller.appendSlide(target.app), /storage full/);
  assert.equal(target.pres.Slides.Count, 3);
});

test('real DOM template page pane previews evidence before confirmation and appends only once', t => {
  const { execFileSync } = require('node:child_process');
  try { execFileSync('agent-browser', ['--version'], { stdio: 'ignore' }); }
  catch (_) { t.skip('agent-browser unavailable'); return; }
  const temp = fs.mkdtempSync('/private/tmp/pr250-pane-');
  const run = (...args) => execFileSync('agent-browser', ['--session', 'pr250', ...args], {
    encoding: 'utf8', timeout: 30000, env: { ...process.env, AGENT_BROWSER_SOCKET_DIR: temp }
  });
  function waitFor(expression) {
    // The controller polls asynchronously; a fixed number of fast evaluations
    // can finish before the first scheduled poll has even run.
    run('wait', '--fn', expression);
  }
  const outline = { slides: [{ pageIndex: 1, pageRole: 'cover', title: '封面' }, { pageIndex: 2, pageRole: 'content', title: '架构', keyPoints: ['分层'] }], basisMaterials: [] };
  const pageResult = regressionResult();
  pageResult.sources[0].text = '<img src=x onerror="window.injected=true">必须分层';
  const mock = `
window.paneErrors=[];window.addEventListener('error',e=>paneErrors.push(e.message));
window.injected=false;window.confirmCalls=0;window.allowAppend=false;
window.confirm=()=>{confirmCalls++;return allowAppend;};
window.mockPres={Name:'A.pptx',FullName:'/test/A.pptx',SlideMaster:{CustomLayouts:{Count:2,Item:i=>({Name:i===1?'标题幻灯片':'标题和内容'})}},Slides:{Count:3}};
window.writtenSlides=[];
mockPres.Slides.AddSlide=function(index,layout){
 if(window.failDeckContent&&layout.Name==='标题和内容')throw Error('正文版式暂不可写');
 const shape=t=>({PlaceholderFormat:{Type:t},TextFrame:{TextRange:{Text:''}}});
 const title=shape(layout.Name==='标题幻灯片'?3:1),body=shape(layout.Name==='标题幻灯片'?4:2),notes=shape(2);
 const slide={Shapes:{Count:2,Item:i=>[title,body][i-1]},NotesPage:{Shapes:{Count:1,Item:()=>notes}},Delete(){mockPres.Slides.Count--;}};
 mockPres.Slides.Count++;writtenSlides.push(slide);return slide;
};
window.Application={ActivePresentation:mockPres};window.wps={WppApplication:()=>Application};
window.fetch=async function(url,options){
 const p=new URL(url).pathname,body=options&&options.body?JSON.parse(options.body):null;let data={};
 if(p==='/health')data={status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true};
 if(p==='/ppt/materials/catalog')data={totalDocuments:1,documents:[{materialId:'m1',fileName:'依据.docx'}]};
 if(p==='/materials/reusable-sources')data={sources:[]};
 if(p==='/ppt/material-outline/conflicts')data={conflicts:[]};
 if(p==='/ppt/material-outline/jobs'||p==='/ppt/template-page/jobs'){
   if(p==='/ppt/template-page/jobs')window.lastTemplatePageRole=body.pageRole;
   data={jobId:body.clientJobId,status:'running'};
 }
 if(p.startsWith('/ppt/material-outline/jobs/'))data={status:'completed',result:${JSON.stringify(outline)}};
 if(p.startsWith('/ppt/template-page/jobs/'))data={status:'completed',result:lastTemplatePageRole==='cover'?{...${JSON.stringify(pageResult)},keyPoints:['副标题']}:${JSON.stringify(pageResult)}};
 return {ok:true,status:200,json:async()=>({success:true,data})};
};`;
  let html = fs.readFileSync(path.join(root, 'taskpane.html'), 'utf8');
  html = html.replace('</head>', '<script>' + mock + '</script></head>');
  html = html.replace(/<script src="\.\/([^"?]+)[^"]*"><\/script>/g, (_, name) => {
    let code = fs.readFileSync(path.join(root, name), 'utf8');
    return '<script>' + code + '</script>';
  });
  html = html.replace(/<link rel="stylesheet"[^>]+>/, '<style>' + fs.readFileSync(path.join(root, 'taskpane.css'), 'utf8') + '</style>');
  const page = path.join(temp, 'pane.html');
  fs.writeFileSync(page, html);
  try {
    run('open', require('node:url').pathToFileURL(page).href + '?mode=pptMaterialOutline');
    run('set', 'viewport', '360', '900');
    waitFor('!document.querySelector("#btn-run-outline").disabled && document.querySelector("#outline-material-list").textContent.includes("依据.docx")');
    run('fill', '#ppt-outline-instruction', '核对架构依据');
    run('eval', 'document.querySelector("#btn-run-outline").click()');
    waitFor('document.querySelectorAll("[data-title-page]").length === 2');
    run('eval', 'document.querySelector("#btn-confirm-outline").click()');
    waitFor('!document.querySelector("#ppt-template-page-card").hidden');
    run('eval', 'document.querySelector("#btn-ppt-generate-template-deck").click()');
    waitFor('document.querySelector("#ppt-template-deck-preview").textContent.includes("架构")');
    assert.match(run('get', 'text', '#ppt-template-deck-preview'), /分层.*隔离.*讲稿/s);
    assert.match(run('get', 'text', '#ppt-template-deck-preview'), /依据\.docx.*待补数据/s);
    assert.equal(run('eval', 'document.querySelectorAll("#ppt-template-deck-preview img").length').trim(), '0');
    assert.equal(run('eval', 'document.querySelector("#ppt-template-page-select").options.length').trim(), '1');
    run('eval', 'document.querySelector("#btn-ppt-generate-template-page").click()');
    waitFor('!document.querySelector("#ppt-template-page-preview").hidden');
    assert.equal(run('eval', 'confirmCalls').trim(), '0');
    assert.match(run('get', 'text', '#ppt-template-page-preview-content'), /依据.docx.*第一章/s);
    assert.match(run('get', 'text', '#ppt-template-page-preview-content'), /待补数据/);
    assert.equal(run('eval', 'document.querySelectorAll("#ppt-template-page-preview-content img").length').trim(), '0');
    run('eval', 'document.querySelector("#btn-ppt-append-slide-confirm").click()');
    assert.equal(run('eval', 'mockPres.Slides.Count').trim(), '3');
    run('eval', 'allowAppend=true');
    run('eval', 'document.querySelector("#btn-ppt-append-slide-confirm").click()');
    assert.equal(run('eval', 'mockPres.Slides.Count').trim(), '4');
    assert.equal(run('eval', 'writtenSlides[0].NotesPage.Shapes.Item(1).TextFrame.TextRange.Text').trim(), '"讲稿"');
    assert.equal(run('eval', 'document.querySelector("#btn-ppt-append-slide-confirm").hidden').trim(), 'true');
    run('eval', 'document.querySelector("#btn-ppt-confirm-template-deck").click()');
    run('eval', 'window.failDeckContent=true;document.querySelector("#btn-ppt-append-template-deck").click()');
    assert.match(run('get', 'text', '#ppt-template-deck-preview'), /已追加第 5 至 5 页/);
    assert.match(run('get', 'text', '#ppt-template-deck-preview'), /继续追加剩余页/);
    assert.equal(run('eval', 'mockPres.Slides.Count').trim(), '5');
    assert.equal(run('eval', 'JSON.stringify(paneErrors)').trim(), '"[]"');
  } finally {
    try { run('close'); } finally { fs.rmSync(temp, { recursive: true, force: true }); }
  }
});

test('recovery block belongs to the affected presentation and does not poison another one', async () => {
  const { h, controller } = generationHarness();
  await controller.startGenerate({ pageIndex: 2 });
  controller.appendSlide(regressionPresentation({ notesError: true, deleteError: true }).app);
  h.session = 'other-presentation';
  await controller.startGenerate({ pageIndex: 2 });
  const target = regressionPresentation();
  assert.equal(controller.appendSlide(target.app).success, true);
  assert.equal(target.pres.Slides.Count, 4);
  h.session = 'sess-ppt-template-1';
  assert.equal(controller.getState().recoveryRequired, true);
});
