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
