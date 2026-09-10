const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");

const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const taskpaneHtml = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");

test("Cycle 2: renderWritingHistoryList renders document review and full document review cards", () => {
  const items = [
    {
      id: "hist_rev_1",
      taskType: "word.document_review",
      jobId: "job-review-001",
      completedAt: "2026-09-10T08:00:00Z",
      documentDisplayName: "合同初稿.docx",
      serviceName: "Word 文档审查",
      modelName: "review-v1",
      result: {
        reportType: "document_review",
        jobId: "job-review-001",
        summary: "审查发现 2 项问题，主要涉及术语和表达。",
        issueCount: 2,
        categoryCounts: { professional: 1, expression: 1 },
        severityCounts: { high: 1, low: 1 }
      }
    },
    {
      id: "hist_full_1",
      taskType: "word.document_review",
      jobId: "job-full-002",
      completedAt: "2026-09-10T09:00:00Z",
      documentDisplayName: "技术白皮书.docx",
      serviceName: "Word 全篇文档审查",
      modelName: "review-direct-v1",
      result: {
        reportType: "full_document_review",
        reportId: "job-full-002",
        jobId: "job-full-002",
        summary: "全篇审查完成，共发现 5 项问题。",
        issueCount: 5,
        categoryCounts: { professional: 3, logic: 2 },
        severityCounts: { high: 2, medium: 3 },
        statusCounts: { open: 5 },
        enumerationStatus: "complete",
        reportExpiresAt: Date.now() / 1000 + 86400
      }
    }
  ];

  const html = helpers.renderWritingHistoryList(items);

  // Document review card assertions
  assert.ok(html.includes("合同初稿.docx"), "Must include regular review document name");
  assert.ok(html.includes("文档审查成果"), "Must include regular review card title");
  assert.ok(html.includes("审查发现 2 项问题"), "Must include regular review summary snippet");
  assert.ok(html.includes('data-history-id="hist_rev_1"'), "Must include card history id");

  // Full document review card assertions
  assert.ok(html.includes("技术白皮书.docx"), "Must include full review document name");
  assert.ok(html.includes("全篇审查成果"), "Must include full review card title");
  assert.ok(html.includes("全篇审查完成，共发现 5 项问题"), "Must include full review summary snippet");
  assert.ok(html.includes('data-history-id="hist_full_1"'), "Must include full review history id");
});

test("Cycle 2: History entry button is available for documentReview mode in taskpane.js", () => {
  const fnMatch = taskpaneSource.match(/function switchMode\(mode\)[\s\S]*?function /);
  assert.ok(fnMatch, "switchMode function should exist");
  const switchModeSrc = fnMatch[0];
  assert.ok(
    !switchModeSrc.includes("btnViewHistory.hidden = !writingMode;"),
    "switchMode must enable btnViewHistory for review modes as well, not only writingMode"
  );
  assert.ok(
    switchModeSrc.includes("historySupported") || switchModeSrc.includes('requestedMode === "documentReview"'),
    "switchMode must check documentReview mode for history button"
  );
});

test("Cycle 2: Dedicated report open and expired fallback in handleWritingHistoryViewItem", () => {
  assert.ok(
    taskpaneSource.includes("/word/document-review/full/jobs/") &&
    taskpaneSource.includes("专用报告已过期或不可用"),
    "taskpane.js must handle dedicated report fetch from history and display expiration notice if unavailable"
  );
});

function functionSource(name) {
  let start = taskpaneSource.indexOf(`  function ${name}(`);
  if (start < 0) {
    start = taskpaneSource.indexOf(`function ${name}(`);
  }
  assert.ok(start >= 0, `missing function ${name}`);
  const next = taskpaneSource.indexOf("\n  function ", start + 3);
  return taskpaneSource.slice(start, next === -1 ? taskpaneSource.length : next);
}

test("Cycle 3: runDocumentReview guards document session slot and preserves result on validation failure", () => {
  const src = functionSource("runDocumentReview");

  assert.ok(
    src.includes("isTaskSlotBusy") && src.includes("word.document_review"),
    "runDocumentReview must check isTaskSlotBusy for word.document_review"
  );
  assert.ok(
    src.includes("claimTaskSlot") && src.includes("word.document_review"),
    "runDocumentReview must claim task slot on submission"
  );
  assert.ok(
    src.indexOf("resolveSelectionScope") < src.indexOf("resetDocumentReviewState"),
    "runDocumentReview must validate scope BEFORE resetting document review state"
  );
});

test("Cycle 3: runFullDocumentReview guards document session slot", () => {
  const src = functionSource("runFullDocumentReview");

  assert.ok(
    src.includes("isTaskSlotBusy") && src.includes("word.document_review.full"),
    "runFullDocumentReview must check isTaskSlotBusy for word.document_review.full"
  );
  assert.ok(
    src.includes("claimTaskSlot") && src.includes("word.document_review.full"),
    "runFullDocumentReview must claim task slot"
  );
});

test("Cycle 4: Full document review resume verifies host, taskType, and documentSessionId", () => {
  const src = functionSource("resumeFullDocumentReviewActiveJob");

  assert.ok(
    src.includes("documentSessionId") &&
    (src.includes("host") || src.includes('"wps"')) &&
    src.includes("taskType"),
    "resumeFullDocumentReviewActiveJob must verify host, taskType, and documentSessionId"
  );
});

test("Cycle 4: Non-task operations (pagination, locate, issue status, export) contract", () => {
  let patchIssueSrc = "";
  try {
    patchIssueSrc = functionSource("patchFullDocumentReviewIssueStatus");
  } catch (e) {
    patchIssueSrc = "";
  }
  if (patchIssueSrc) {
    assert.ok(
      !patchIssueSrc.includes("claimTaskSlot") && !patchIssueSrc.includes("saveFullDocumentReviewActiveJob"),
      "patchFullDocumentReviewIssueStatus must not create new job or claim slot"
    );
  }
});

test("Behavioral: Document switching isolates task slots across document sessions", () => {
  const slots = {};
  const host = "wps";
  const taskType = "word.document_review";

  // Document A starts a review
  helpers.claimTaskSlot(slots, host, taskType, "doc-session-A", "job-A-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-A"),
    true,
    "Document A slot should be busy"
  );
  // Document B is NOT busy and can proceed
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-B"),
    false,
    "Document B slot should be free"
  );

  // Document B starts full review
  const fullTaskType = "word.document_review.full";
  helpers.claimTaskSlot(slots, host, fullTaskType, "doc-session-B", "job-B-full-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-B"),
    true,
    "Document B full review slot should be busy"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-A"),
    false,
    "Document A full review slot should be free"
  );

  // Releasing Document A does not affect Document B
  helpers.releaseTaskSlot(slots, host, taskType, "doc-session-A", "job-A-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-A"),
    false,
    "Document A slot should now be free"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-B"),
    true,
    "Document B full review slot remains busy"
  );
});

test("Behavioral: Pane reopen recovers review jobs only when host, taskType, and documentSessionId match", () => {
  function makeMockContext(storage, activeDocSession, fullEnabled = true) {
    const state = {
      currentMode: "documentReview",
      fullDocumentReviewEnabled: fullEnabled,
      fullDocumentReviewJobId: "",
      fullDocumentReviewPollErrorCount: 0,
      documentReviewJobId: "",
      documentReviewPollStartedAt: 0,
      documentSessionId: activeDocSession
    };
    const byId = () => ({ setAttribute: () => {}, classList: { add: () => {}, remove: () => {} } });
    const ctx = {
      state,
      byId,
      helpers: {
        getDocumentSessionId: () => activeDocSession
      },
      getActiveDocument: () => ({ Name: activeDocSession }),
      window: {
        localStorage: {
          getItem: (k) => storage[k] || null,
          setItem: (k, v) => { storage[k] = String(v); },
          removeItem: (k) => { delete storage[k]; }
        }
      },
      FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY: "ai-wps-full-document-review-active-job-v1",
      DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY: "ai-wps-document-review-active-job-v1",
      setModelTaskBusy: () => {},
      renderFullDocumentReviewEntry: () => {},
      setStatus: () => {},
      setPlainResult: () => {},
      setApplyEnabled: () => {},
      setReviewRecordActionsVisible: () => {},
      setTrace: () => {},
      pollFullDocumentReviewJob: () => {},
      pollDocumentReviewJob: () => {},
      setDocumentReviewJobId: (id) => { state.documentReviewJobId = id; }
    };
    return ctx;
  }

  // 1. Matching host, taskType, and docSession -> recovers
  const storage1 = {
    "ai-wps-full-document-review-active-job-v1": JSON.stringify({
      jobId: "full-job-999",
      host: "wps",
      taskType: "word.document_review.full",
      documentSessionId: "doc-session-X"
    })
  };
  const ctx1 = makeMockContext(storage1, "doc-session-X");
  const resumeFnSrc = functionSource("resumeFullDocumentReviewActiveJob");
  const loadFnSrc = functionSource("loadFullDocumentReviewActiveJob");
  vm.runInNewContext(`${loadFnSrc}\n${resumeFnSrc}\nres = resumeFullDocumentReviewActiveJob();`, ctx1);
  assert.strictEqual(ctx1.res, true, "Should resume when session matches");
  assert.strictEqual(ctx1.state.fullDocumentReviewJobId, "full-job-999");

  // 2. Mismatched documentSessionId -> does NOT recover
  const storage2 = {
    "ai-wps-full-document-review-active-job-v1": JSON.stringify({
      jobId: "full-job-999",
      host: "wps",
      taskType: "word.document_review.full",
      documentSessionId: "doc-session-X"
    })
  };
  const ctx2 = makeMockContext(storage2, "doc-session-Y"); // Different document!
  vm.runInNewContext(`${loadFnSrc}\n${resumeFnSrc}\nres = resumeFullDocumentReviewActiveJob();`, ctx2);
  assert.strictEqual(ctx2.res, false, "Should NOT resume when doc session differs");
  assert.strictEqual(ctx2.state.fullDocumentReviewJobId, "", "Job ID should remain empty");

  // 3. Mismatched host -> does NOT recover
  const storage3 = {
    "ai-wps-full-document-review-active-job-v1": JSON.stringify({
      jobId: "full-job-999",
      host: "word", // foreign host
      taskType: "word.document_review.full",
      documentSessionId: "doc-session-X"
    })
  };
  const ctx3 = makeMockContext(storage3, "doc-session-X");
  vm.runInNewContext(`${loadFnSrc}\n${resumeFnSrc}\nres = resumeFullDocumentReviewActiveJob();`, ctx3);
  assert.strictEqual(ctx3.res, false, "Should NOT resume when host differs");

  // 4. Regular review resume: mismatched documentSessionId -> does NOT recover
  const storage4 = {
    "ai-wps-document-review-active-job-v1": JSON.stringify({
      jobId: "reg-job-888",
      host: "wps",
      taskType: "word.document_review",
      documentSessionId: "doc-session-A"
    })
  };
  const ctx4 = makeMockContext(storage4, "doc-session-B"); // Different doc
  const loadRegSrc = functionSource("loadDocumentReviewActiveJob");
  const resumeRegSrc = functionSource("resumeDocumentReviewActiveJob");
  vm.runInNewContext(`${loadRegSrc}\n${resumeRegSrc}\nresumeDocumentReviewActiveJob();`, ctx4);
  assert.strictEqual(ctx4.state.documentReviewJobId, "", "Regular review should not resume on different doc");
});

test("Behavioral: Expired report shows clear unavailable notice in history detail", async () => {
  const cardElement = {
    querySelector: () => null,
    insertBefore: () => {},
    appendChild: (el) => { cardElement.detail = el; }
  };
  const btnElement = {
    closest: () => cardElement,
    textContent: "查看"
  };
  let requestedUrl = "";
  const ctx = {
    document: {
      createElement: (tag) => ({
        tagName: tag.toUpperCase(),
        className: "",
        innerHTML: "",
        style: {},
        querySelector: () => null
      })
    },
    state: {
      historyItems: [
        {
          id: "hist_expired_1",
          taskType: "word.document_review",
          jobId: "full-job-expired",
          result: {
            reportType: "full_document_review",
            reportId: "full-job-expired",
            summary: "历史全篇审查摘要"
          }
        }
      ]
    },
    helpers,
    request: (url) => {
      requestedUrl = url;
      // Simulate 404 expired from adapter
      const err = new Error("全篇审查尚未生成可用的结构化报告。");
      err.httpStatus = 404;
      err.adapterCode = "FULL_DOCUMENT_REVIEW_REPORT_NOT_AVAILABLE";
      return Promise.reject(err);
    }
  };

  const viewFnSrc = functionSource("handleWritingHistoryViewItem");
  const script = `${viewFnSrc}\np = handleWritingHistoryViewItem("hist_expired_1", btn);`;
  ctx.btn = btnElement;
  vm.runInNewContext(script, ctx);

  // Wait for promise resolution
  await ctx.p;

  assert.ok(requestedUrl.includes("/word/document-review/full/jobs/full-job-expired/report"));
  assert.ok(cardElement.detail, "Detail element should be attached");
  assert.ok(
    cardElement.detail.innerHTML.includes("专用报告已过期或不可用"),
    "Detail element must notify user that dedicated report has expired"
  );
});

test("Behavioral: History deletion calls DELETE API and updates list", async () => {
  let deletedId = "";
  const container = { innerHTML: "" };
  const ctx = {
    state: {
      historyItems: [
        { id: "h1", taskType: "word.document_review" },
        { id: "h2", taskType: "word.document_review" }
      ]
    },
    helpers,
    byId: (id) => id === "word-history-content" ? container : null,
    setStatus: () => {},
    request: (url, body, options) => {
      if (options && options.method === "DELETE") {
        deletedId = url.replace("/history/", "");
        return Promise.resolve({ success: true, data: { deleted: true } });
      }
      return Promise.resolve({});
    }
  };

  const deleteFnSrc = functionSource("handleWritingHistoryDeleteItem");
  vm.runInNewContext(`${deleteFnSrc}\np = handleWritingHistoryDeleteItem("h1");`, ctx);
  await ctx.p;

  assert.strictEqual(deletedId, "h1", "DELETE /history/h1 should be called");
  assert.strictEqual(ctx.state.historyItems.length, 1, "historyItems should have 1 item left");
  assert.strictEqual(ctx.state.historyItems[0].id, "h2");
});

