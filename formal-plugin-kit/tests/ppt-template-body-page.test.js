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
    SlideMaster: { CustomLayouts: { Count: 0 } },
    Slides: {
      Count: 5,
      Add: (index, layoutType) => {
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

  const mockPres = {
    SlideMaster: { CustomLayouts: { Count: 0 } },
    Slides: {
      Count: 2,
      Add: (idx, type) => {
        mockPres.Slides.Count++;
        const sTitle = { Name: "标题", TextFrame: { TextRange: { Text: "" } } };
        const sBody = { Name: "内容", TextFrame: { TextRange: { Text: "" } } };
        return {
          Index: idx,
          Shapes: {
            Count: 2,
            Item: (i) => (i === 1 ? sTitle : sBody),
          },
        };
      },
    },
  };

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
