(function (root, factory) {
  var exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  if (typeof window !== "undefined") {
    window.createMaterialLedger = exports.createMaterialLedger;
    window.DEFAULT_LEDGER_HEADERS = exports.DEFAULT_LEDGER_HEADERS;
    window.LEDGER_PHASE_TEXT = exports.LEDGER_PHASE_TEXT;
  }
  if (root) {
    root.createMaterialLedger = exports.createMaterialLedger;
    root.DEFAULT_LEDGER_HEADERS = exports.DEFAULT_LEDGER_HEADERS;
    root.LEDGER_PHASE_TEXT = exports.LEDGER_PHASE_TEXT;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var DEFAULT_LEDGER_HEADERS = ["工作事项", "责任部门", "完成时间", "交付物验收"];

  var LEDGER_PHASE_TEXT = {
    queued: "正在排队...",
    preparing: "正在分析资料并建立索引...",
    provider_processing: "正在提取任务台账...",
    parsing: "正在核对字段与出处...",
    completed: "台账提取完成",
    failed: "提取失败",
    cancelled: "任务已取消"
  };

  function createMaterialLedger(options) {
    var opts = options || {};
    var request = opts.request || function () { return Promise.reject(new Error("no request")); };
    var storage = opts.storage || { getItem: function () {}, setItem: function () {}, removeItem: function () {} };
    var getSessionId = opts.getSessionId || function () { return "default"; };
    var render = opts.render || function () {};
    var copyText = opts.copyText || function () {};
    var schedule = opts.schedule || function (fn, ms) { return setTimeout(fn, ms || 0); };

    var states = {};

    function clone(obj) {
      try {
        return JSON.parse(JSON.stringify(obj));
      } catch (e) {
        return {};
      }
    }

    function formatCatalogLabel(summary) {
      if (!summary || !summary.totalDocuments) return "未添加资料";
      var totalChars = typeof summary.totalCharacters === "number" ? summary.totalCharacters.toLocaleString() : "0";
      return "已添加 " + summary.totalDocuments + "/5 份资料，合计 " + totalChars + "/100,000 字";
    }

    function stateFor(sessionId) {
      if (!states[sessionId]) {
        var raw = storage.getItem("excel.material-ledger:" + sessionId);
        var saved = null;
        if (raw) {
          try {
            saved = JSON.parse(raw);
          } catch (e) {
            saved = null;
          }
        }
        var catalogSummary = (saved && saved.catalogSummary) || { totalDocuments: 0, totalCharacters: 0, documents: [] };
        states[sessionId] = {
          documentSessionId: sessionId,
          headers: (saved && Array.isArray(saved.headers) && saved.headers.length) ? saved.headers.slice() : DEFAULT_LEDGER_HEADERS.slice(),
          instruction: (saved && saved.instruction) || "",
          userFacts: (saved && saved.userFacts) || "",
          catalogSummary: catalogSummary,
          catalogLabel: formatCatalogLabel(catalogSummary),
          reusableSources: [],
          conflicts: [],
          conflictResolutions: (saved && saved.conflictResolutions) || [],
          jobId: (saved && saved.jobId) || "",
          clientJobId: (saved && saved.clientJobId) || "",
          status: (saved && saved.jobId) ? "running" : "idle",
          phase: (saved && saved.phase) || "",
          phaseLabel: (saved && saved.phase) ? (LEDGER_PHASE_TEXT[saved.phase] || saved.phase) : "",
          result: (saved && saved.result) || null,
          error: "",
          busy: false,
          activeDrawerRowIndex: null
        };
      }
      return states[sessionId];
    }

    function current() {
      return stateFor(getSessionId());
    }

    function persist(s) {
      try {
        storage.setItem("excel.material-ledger:" + s.documentSessionId, JSON.stringify({
          headers: s.headers,
          instruction: s.instruction,
          userFacts: s.userFacts,
          catalogSummary: s.catalogSummary,
          conflictResolutions: s.conflictResolutions,
          jobId: s.jobId,
          clientJobId: s.clientJobId,
          result: s.result
        }));
      } catch (e) {
        // Storage might fail in sandboxed iframe
      }
    }

    function notify(s) {
      s.catalogLabel = formatCatalogLabel(s.catalogSummary);
      s.phaseLabel = LEDGER_PHASE_TEXT[s.phase] || (s.phase ? s.phase : (s.status === "running" ? "处理中..." : ""));
      render(clone(s));
    }

    function setHeaders(headers) {
      var s = current();
      if (Array.isArray(headers) && headers.length) {
        s.headers = headers.map(function (h) { return String(h || "").trim(); }).filter(Boolean);
      } else {
        s.headers = DEFAULT_LEDGER_HEADERS.slice();
      }
      persist(s);
      notify(s);
      return s.headers;
    }

    function addHeader(name) {
      var s = current();
      var trimmed = String(name || "").trim();
      if (trimmed && s.headers.indexOf(trimmed) < 0) {
        s.headers.push(trimmed);
        persist(s);
        notify(s);
      }
      return s.headers;
    }

    function removeHeader(index) {
      var s = current();
      if (index >= 0 && index < s.headers.length) {
        s.headers.splice(index, 1);
        if (s.headers.length === 0) {
          s.headers = DEFAULT_LEDGER_HEADERS.slice();
        }
        persist(s);
        notify(s);
      }
      return s.headers;
    }

    function readSelectionHeaders(app) {
      var helpers = (typeof window !== "undefined" && window.WpsAiAssistantHelpers) || {};
      var extracted = [];
      if (typeof helpers.readSelectionHeaders === "function") {
        extracted = helpers.readSelectionHeaders(app);
      } else if (app && app.Selection) {
        var range = app.Selection;
        var cols = range.Columns ? (range.Columns.Count || range.Columns.count || 1) : 1;
        var cells = range.Cells || range;
        for (var c = 1; c <= cols; c += 1) {
          try {
            var cell = typeof cells.Item === "function" ? cells.Item(1, c) : (cells.item ? cells.item(1, c) : null);
            var val = cell ? String(cell.Text || cell.Value2 || cell.Value || "").trim() : "";
            if (val) extracted.push(val);
          } catch (e) {}
        }
      }
      if (extracted.length) {
        setHeaders(extracted);
      }
      return extracted;
    }

    function setInstruction(text) {
      var s = current();
      s.instruction = String(text || "").trim();
      persist(s);
      notify(s);
    }

    function setUserFacts(text) {
      var s = current();
      s.userFacts = String(text || "").trim();
      persist(s);
      notify(s);
    }

    function setConflictResolutions(resolutions) {
      var s = current();
      s.conflictResolutions = Array.isArray(resolutions) ? resolutions : [];
      persist(s);
      notify(s);
    }

    async function checkConflicts() {
      var s = current();
      try {
        var res = await request(
          "/excel/material-ledger/conflicts?documentSessionId=" + encodeURIComponent(s.documentSessionId) +
          "&userFacts=" + encodeURIComponent(s.userFacts || ""),
          null,
          { method: "GET" }
        );
        if (res && res.data && res.data.conflicts) {
          s.conflicts = res.data.conflicts;
        } else if (res && Array.isArray(res.data)) {
          s.conflicts = res.data;
        }
        notify(s);
        return s.conflicts;
      } catch (err) {
        s.conflicts = [];
        notify(s);
        return [];
      }
    }

    async function listReusableSources() {
      var s = current();
      try {
        var res = await request("/materials/reusable-sources", null, { method: "GET" });
        var list = (res && res.data && res.data.sources) || [];
        s.reusableSources = list;
        notify(s);
        return list;
      } catch (err) {
        s.reusableSources = [];
        notify(s);
        return [];
      }
    }

    async function cloneFromSource(sourceSessionId) {
      var s = current();
      s.busy = true;
      notify(s);
      try {
        var res = await request("/excel/materials/clone-from-source", {
          sourceSessionId: sourceSessionId,
          targetDocumentSessionId: s.documentSessionId
        }, { method: "POST" });
        if (res && res.data && res.data.catalogSummary) {
          s.catalogSummary = res.data.catalogSummary;
        } else if (res && res.data) {
          s.catalogSummary = res.data;
        }
        s.busy = false;
        persist(s);
        notify(s);
        return s.catalogSummary;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "复用资料失败";
        notify(s);
        throw err;
      }
    }

    async function importMaterial(upload) {
      var s = current();
      s.busy = true;
      notify(s);
      try {
        var res = await request("/excel/materials/import", {
          documentSessionId: s.documentSessionId,
          fileName: upload.fileName,
          contentBase64: upload.contentBase64
        }, { method: "POST" });
        if (res && res.data && res.data.catalogSummary) {
          s.catalogSummary = res.data.catalogSummary;
        } else {
          await loadCatalog();
        }
        s.busy = false;
        persist(s);
        notify(s);
        return res && res.data;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "导入资料失败";
        notify(s);
        throw err;
      }
    }

    async function deleteMaterial(materialId) {
      var s = current();
      s.busy = true;
      notify(s);
      try {
        var res = await request("/excel/materials/" + encodeURIComponent(materialId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "DELETE" });
        if (res && res.data && res.data.catalogSummary) {
          s.catalogSummary = res.data.catalogSummary;
        } else {
          await loadCatalog();
        }
        s.busy = false;
        persist(s);
        notify(s);
        return res && res.data;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "删除资料失败";
        notify(s);
        throw err;
      }
    }

    async function loadCatalog() {
      var s = current();
      try {
        var res = await request("/excel/materials/catalog?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "GET" });
        if (res && res.data) {
          s.catalogSummary = res.data;
          persist(s);
          notify(s);
        }
      } catch (err) {}
    }

    async function generate() {
      var s = current();
      var clientJobId = "job_" + Math.random().toString(36).slice(2, 10);
      s.clientJobId = clientJobId;
      s.status = "running";
      s.phase = "preparing";
      s.error = "";
      s.result = null;
      s.busy = true;
      persist(s);
      notify(s);

      try {
        var payload = {
          documentSessionId: s.documentSessionId,
          clientJobId: clientJobId,
          headers: s.headers,
          instruction: s.instruction,
          userFacts: s.userFacts,
          conflictResolutions: s.conflictResolutions
        };
        var res = await request("/excel/material-ledger/jobs", payload, { method: "POST" });
        if (res && res.data) {
          s.jobId = res.data.jobId || clientJobId;
          s.status = res.data.status || "running";
          s.phase = res.data.phase || s.phase;
          persist(s);
          notify(s);
          pollJob(s.jobId);
        }
      } catch (err) {
        s.status = "failed";
        s.busy = false;
        s.error = (err && err.message) || "提交台账提取任务失败";
        persist(s);
        notify(s);
      }
    }

    function pollJob(jobId) {
      var s = current();
      if (!jobId || s.jobId !== jobId || s.status === "completed" || s.status === "failed" || s.status === "cancelled") {
        return;
      }

      schedule(async function () {
        if (s.jobId !== jobId) return;
        try {
          var res = await request("/excel/material-ledger/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "GET" });
          if (!res || !res.data) {
            pollJob(jobId);
            return;
          }
          var job = res.data;
          s.status = job.status;
          s.phase = job.phase || s.phase;
          if (job.status === "completed") {
            s.busy = false;
            setResult(job.result);
          } else if (job.status === "failed") {
            s.busy = false;
            s.error = job.error || "台账提取失败";
            persist(s);
            notify(s);
          } else if (job.status === "cancelled") {
            s.busy = false;
            persist(s);
            notify(s);
          } else {
            notify(s);
            pollJob(jobId);
          }
        } catch (err) {
          pollJob(jobId);
        }
      }, 1000);
    }

    async function cancel() {
      var s = current();
      if (!s.jobId) {
        s.status = "cancelled";
        s.busy = false;
        persist(s);
        notify(s);
        return;
      }
      try {
        var res = await request("/excel/material-ledger/jobs/" + encodeURIComponent(s.jobId) + "/cancel", {
          documentSessionId: s.documentSessionId
        }, { method: "POST" });
        s.status = "cancelled";
        s.busy = false;
        persist(s);
        notify(s);
      } catch (err) {
        s.status = "cancelled";
        s.busy = false;
        persist(s);
        notify(s);
      }
    }

    function setResult(result) {
      var s = current();
      s.result = result;
      s.status = "completed";
      s.busy = false;
      s.phase = "completed";
      persist(s);
      notify(s);
    }

    function formatTsv(result) {
      if (!result || !Array.isArray(result.rows) || !Array.isArray(result.headers)) {
        return "";
      }
      var headers = result.headers;
      var lines = [headers.join("\t")];
      for (var i = 0; i < result.rows.length; i++) {
        var row = result.rows[i];
        var values = row.values || {};
        var rowCells = [];
        for (var j = 0; j < headers.length; j++) {
          var h = headers[j];
          var cellVal = String(values[h] != null ? values[h] : "").replace(/[\r\n\t]/g, " ");
          rowCells.push(cellVal);
        }
        lines.push(rowCells.join("\t"));
      }
      return lines.join("\n");
    }

    function copyTsv() {
      var s = current();
      if (!s.result) return false;
      var tsv = formatTsv(s.result);
      copyText(tsv);
      return true;
    }

    function openSourceDrawer(rowIndex) {
      var s = current();
      s.activeDrawerRowIndex = rowIndex;
      notify(s);
    }

    function closeSourceDrawer() {
      var s = current();
      s.activeDrawerRowIndex = null;
      notify(s);
    }

    async function restore() {
      var s = current();
      notify(s);
      await loadCatalog();
      if (s.jobId && s.status === "running") {
        pollJob(s.jobId);
      }
    }

    // Initial render
    notify(current());

    return {
      getState: current,
      setHeaders: setHeaders,
      addHeader: addHeader,
      removeHeader: removeHeader,
      readSelectionHeaders: readSelectionHeaders,
      setInstruction: setInstruction,
      setUserFacts: setUserFacts,
      setConflictResolutions: setConflictResolutions,
      checkConflicts: checkConflicts,
      listReusableSources: listReusableSources,
      cloneFromSource: cloneFromSource,
      importMaterial: importMaterial,
      deleteMaterial: deleteMaterial,
      loadCatalog: loadCatalog,
      generate: generate,
      cancel: cancel,
      setResult: setResult,
      formatTsv: formatTsv,
      copyTsv: copyTsv,
      openSourceDrawer: openSourceDrawer,
      closeSourceDrawer: closeSourceDrawer,
      restore: restore
    };
  }

  return {
    createMaterialLedger: createMaterialLedger,
    DEFAULT_LEDGER_HEADERS: DEFAULT_LEDGER_HEADERS,
    LEDGER_PHASE_TEXT: LEDGER_PHASE_TEXT
  };
});
