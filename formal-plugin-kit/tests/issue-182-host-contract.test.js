const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { etRoot, wordRoot, pptRoot } = require("./support/plugin-roots");

const hosts = [
  {
    name: "Word",
    root: wordRoot,
    historyViewId: "word-history-view",
    historyContentId: "word-history-content",
    taskType: "word.smart_write",
    loadFn: "loadAndRenderWritingHistory",
    clearFn: "handleClearWritingHistory",
    copyFn: "handleWritingHistoryCopyItem",
    deleteFn: "handleWritingHistoryDeleteItem",
    viewFn: "handleWritingHistoryViewItem",
    cardClass: "word-history-card",
    detailNeedle: "可复制正文",
    sample: {
      id: "hist_1_word",
      taskType: "word.smart_write",
      result: { rewrittenText: "可复制正文", plainText: "可复制正文" },
    },
  },
  {
    name: "Excel",
    root: etRoot,
    historyViewId: "excel-history-view",
    historyContentId: "excel-history-content",
    taskType: "excel.analysis",
    loadFn: "loadAndRenderSmartFillHistory",
    clearFn: "handleClearSmartFillHistory",
    copyFn: "handleSmartFillHistoryCopyItem",
    deleteFn: "handleSmartFillHistoryDeleteItem",
    viewFn: "handleSmartFillHistoryViewItem",
    cardClass: "excel-history-card",
    detailNeedle: "可复制分析",
    sample: {
      id: "hist_1_excel",
      taskType: "excel.analysis",
      result: { plainText: "可复制分析" },
    },
  },
  {
    name: "PPT",
    root: pptRoot,
    historyViewId: "ppt-history-view",
    historyContentId: "ppt-history-content",
    taskType: "ppt.slide_assistant",
    loadFn: "loadAndRenderHistory",
    clearFn: "handleClearHistory",
    copyFn: "handleHistoryCopyItem",
    deleteFn: "handleHistoryDeleteItem",
    viewFn: "handleHistoryViewItem",
    cardClass: "ppt-history-card",
    detailNeedle: "可复制总结",
    sample: {
      id: "hist_1_ppt",
      taskType: "ppt.slide_assistant",
      result: { resultType: "slide", summary: "可复制总结", plainText: "可复制总结" },
    },
  },
];

function readHost(root) {
  return {
    html: fs.readFileSync(path.join(root, "taskpane.html"), "utf8"),
    js: fs.readFileSync(path.join(root, "taskpane.js"), "utf8"),
  };
}

function functionSource(source, name) {
  let start = source.indexOf(`  function ${name}(`);
  if (start < 0) {
    start = source.indexOf(`function ${name}(`);
  }
  assert.ok(start >= 0, `missing function ${name}`);
  const next = source.indexOf("\n  function ", start + 3);
  return source.slice(start, next === -1 ? source.length : next);
}

function historyPanel(html, historyViewId) {
  const marker = `id="${historyViewId}"`;
  const start = html.indexOf(marker);
  assert.ok(start >= 0, `missing ${historyViewId}`);
  return html.slice(Math.max(0, start - 80), start + 4000);
}

function makeHistoryCard(cardClass) {
  const card = {
    className: cardClass,
    _detail: null,
    _actions: { className: `${cardClass}-actions` },
    querySelector(sel) {
      if (String(sel).endsWith("-card-detail")) {
        return this._detail;
      }
      if (String(sel).endsWith("-card-actions")) {
        return this._actions;
      }
      return null;
    },
    insertBefore(child) {
      this._detail = child;
      return child;
    },
    appendChild(child) {
      this._detail = child;
      return child;
    },
  };
  return card;
}

function makeViewButton(card, cardClass) {
  return {
    textContent: "查看",
    closest(sel) {
      return sel === `.${cardClass}` ? card : null;
    },
  };
}

test("three hosts expose one shared direct-service home and a single Key field", () => {
  hosts.forEach((host) => {
    const { html, js } = readHost(host.root);
    const source = html + "\n" + js;
    assert.match(html, /id="direct-services-card"/, `${host.name} missing shared service card`);
    assert.match(html, /id="btn-new-direct-service"/, `${host.name} missing create service button`);
    assert.match(html, /id="direct-service-key"/, `${host.name} missing Key field`);
    assert.equal(
      source.includes("direct-service-key-confirm"),
      false,
      `${host.name} must not confirm shared Key twice`
    );
    assert.match(
      source,
      /id="workflow-editor-key-confirm"|data-workflow-editor-key-confirm/,
      `${host.name} must keep per-task workflow Key confirmation`
    );
  });
});

test("three hosts keep history in the result area with copy and clear, without write-back", async () => {
  for (const host of hosts) {
    const { html, js } = readHost(host.root);
    assert.match(html, new RegExp(`id="${host.historyViewId}"`), `${host.name} missing history view`);
    assert.match(html, /id="btn-view-history"/, `${host.name} missing history entry`);
    assert.match(html, /id="btn-clear-history"/, `${host.name} missing clear-history`);
    assert.match(html, /id="btn-history-back"/, `${host.name} missing return-to-active`);

    const panel = historyPanel(html, host.historyViewId);
    assert.equal(panel.includes("写回"), false, `${host.name} history markup must not offer write-back`);

    const loadSrc = functionSource(js, host.loadFn);
    const clearSrc = functionSource(js, host.clearFn);
    const copySrc = functionSource(js, host.copyFn);
    const deleteSrc = functionSource(js, host.deleteFn);
    const viewSrc = functionSource(js, host.viewFn);
    const historyFns = [loadSrc, clearSrc, copySrc, deleteSrc, viewSrc].join("\n");
    assert.equal(historyFns.includes("写回"), false, `${host.name} history handlers must not offer write-back`);
    assert.match(loadSrc, /\/history\?taskType=/);
    assert.match(clearSrc, /method:\s*"DELETE"/);
    assert.match(clearSrc, /\/history\?taskType=/);
    assert.match(deleteSrc, /\/history\/" \+ encodeURIComponent\(id\)/);
    assert.match(deleteSrc, /method:\s*"DELETE"/);

    const calls = [];
    const elements = {};
    const byId = (id) => {
      if (!elements[id]) {
        elements[id] = {
          id,
          innerHTML: "",
          textContent: "",
          hidden: false,
          querySelector() {
            return this._child || null;
          },
          closest() {
            return this;
          },
          appendChild(child) {
            this._child = child;
            return child;
          },
          insertBefore(child) {
            this._child = child;
            return child;
          },
        };
      }
      return elements[id];
    };
    const sandbox = {
      state: {
        historyItems: [host.sample],
        historyTaskType: host.taskType,
        historyRequestId: 0,
        historyLoadSequence: 0,
        currentMode: "smartWrite",
      },
      calls,
      copied: "",
      PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
      EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
      EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
      EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
      encodeURIComponent,
      Promise,
      JSON,
      Array,
      String,
      Boolean,
      Object,
      Number,
      setTimeout,
      clearTimeout,
      console,
      Date,
      document: {
        createElement() {
          return {
            className: "",
            style: {},
            innerHTML: "",
            hidden: false,
            querySelector() {
              return this._child || null;
            },
            addEventListener() {},
          };
        },
      },
      navigator: {
        clipboard: {
          writeText(text) {
            sandbox.copied = text;
            return Promise.resolve();
          },
        },
      },
      helpers: {
        renderWritingHistoryList() {
          return "word-list";
        },
        renderHistoryList() {
          return "ppt-list";
        },
        renderExcelAnalysisHistoryList() {
          return "excel-list";
        },
        renderExcelFormulaHistoryList() {
          return "excel-list";
        },
        renderSmartFillHistoryList() {
          return "excel-list";
        },
        renderMarkdown(text) {
          return text;
        },
        escapeHtml(text) {
          return String(text);
        },
        buildPptSlidePlainText(res) {
          return res.plainText || res.summary || "";
        },
        buildPptSlideMarkdown(res) {
          return res.plainText || res.summary || "";
        },
        buildPptDocumentPlainText(res) {
          return res.plainText || "";
        },
      },
      byId,
      failReport: false,
      request(url, _body, opts) {
        const method = (opts && opts.method) || "GET";
        calls.push({ url, method });
        if (sandbox.failReport) {
          return Promise.reject(new Error("report expired"));
        }
        if (String(url).indexOf("/report") >= 0) {
          return Promise.resolve({
            success: true,
            data: {
              issueCount: 2,
              summary: { issueCount: 2, complianceStatus: "violations_found" },
            },
          });
        }
        return Promise.resolve({
          success: true,
          data: { items: sandbox.state.historyItems, total: sandbox.state.historyItems.length },
        });
      },
      getCurrentWorkflowTaskType() {
        return host.taskType;
      },
      renderCurrentTaskHistoryList() {
        return "excel-list";
      },
      setStatus() {},
      copyText(text) {
        sandbox.copied = text;
      },
      fallbackCopy(text, done) {
        sandbox.copied = text;
        if (typeof done === "function") {
          done();
        }
      },
    };
    vm.createContext(sandbox);
    vm.runInContext(
      `${loadSrc}\n${clearSrc}\n${copySrc}\n${deleteSrc}\n${viewSrc}\nthis._load = ${host.loadFn};\nthis._clear = ${host.clearFn};\nthis._copy = ${host.copyFn};\nthis._delete = ${host.deleteFn};\nthis._view = ${host.viewFn};`,
      sandbox
    );

    await sandbox._load(host.taskType);
    const loadCall = calls.find((item) => item.method === "GET" && String(item.url).startsWith("/history?"));
    assert.ok(loadCall, `${host.name} must GET /history`);
    assert.equal(loadCall.url, `/history?taskType=${encodeURIComponent(host.taskType)}`);

    sandbox._copy(host.sample.id);
    assert.ok(String(sandbox.copied).length > 0, `${host.name} copy must produce text`);

    sandbox.state.historyItems = [host.sample];
    const card = makeHistoryCard(host.cardClass);
    const btn = makeViewButton(card, host.cardClass);
    await sandbox._view(host.sample.id, btn);
    assert.ok(card._detail, `${host.name} view must create a detail panel`);
    assert.match(String(card._detail.innerHTML), new RegExp(host.detailNeedle));
    assert.equal(btn.textContent, "收起", `${host.name} view should expand`);
    sandbox._view(host.sample.id, btn);
    assert.equal(card._detail.hidden, true, `${host.name} view should collapse`);
    assert.equal(btn.textContent, "查看", `${host.name} collapsed label`);
    sandbox._view(host.sample.id, btn);
    assert.equal(card._detail.hidden, false, `${host.name} view should expand again`);
    assert.equal(btn.textContent, "收起", `${host.name} expanded label`);

    if (host.name === "Word") {
      const formatItem = {
        id: "hist_fmt_word",
        taskType: "word.format_review",
        jobId: "fmt-job-1",
        result: {
          reportType: "format_review",
          reportId: "fmt-job-1",
          issueCount: 2,
        },
      };
      sandbox.state.historyItems = [formatItem];
      const formatCard = makeHistoryCard(host.cardClass);
      const formatBtn = makeViewButton(formatCard, host.cardClass);
      await sandbox._view(formatItem.id, formatBtn);
      const reportCall = calls.find(
        (item) => String(item.url).indexOf("/word/format-review/jobs/") >= 0 && String(item.url).indexOf("/report") >= 0
      );
      assert.ok(reportCall, "format review view must request the dedicated report");
      assert.equal(
        reportCall.url,
        "/word/format-review/jobs/fmt-job-1/report?format=summary"
      );
      assert.match(String(formatCard._detail.innerHTML), /格式审查报告/);
      assert.equal(formatBtn.textContent, "收起");

      sandbox.failReport = true;
      const expiredCard = makeHistoryCard(host.cardClass);
      const expiredBtn = makeViewButton(expiredCard, host.cardClass);
      await sandbox._view(formatItem.id, expiredBtn);
      assert.match(String(expiredCard._detail.innerHTML), /history-report-expired/);
      assert.match(String(expiredCard._detail.innerHTML), /专用报告已过期/);
      sandbox.failReport = false;
    }

    await sandbox._delete(host.sample.id);
    const deleteCall = calls.find((item) => item.method === "DELETE" && item.url.startsWith("/history/"));
    assert.ok(deleteCall, `${host.name} must DELETE /history/{id}`);
    assert.equal(deleteCall.url, `/history/${encodeURIComponent(host.sample.id)}`);

    sandbox.state.historyItems = [host.sample];
    await sandbox._clear();
    const clearCall = calls.find((item) => item.method === "DELETE" && item.url.startsWith("/history?taskType="));
    assert.ok(clearCall, `${host.name} must DELETE /history?taskType=`);
    assert.equal(clearCall.url, `/history?taskType=${encodeURIComponent(host.taskType)}`);
  }
});
