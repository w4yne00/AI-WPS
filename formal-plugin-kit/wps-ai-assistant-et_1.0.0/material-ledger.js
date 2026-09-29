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
        var interruptedWrite = saved && (saved.writeStatus === "writing" || saved.writeStatus === "interrupted");
        states[sessionId] = {
          documentSessionId: sessionId,
          headers: (saved && Array.isArray(saved.headers) && saved.headers.length) ? saved.headers.slice() : DEFAULT_LEDGER_HEADERS.slice(),
          uncheckedHeaders: (saved && saved.uncheckedHeaders) || [],
          instruction: (saved && saved.instruction) || "",
          userFacts: (saved && saved.userFacts) || "",
          catalogSummary: catalogSummary,
          catalogLabel: formatCatalogLabel(catalogSummary),
          reusableSources: [],
          conflicts: [],
          conflictResolutions: (saved && saved.conflictResolutions) || [],
          jobId: (saved && saved.jobId) || "",
          clientJobId: (saved && saved.clientJobId) || "",
          status: (saved && saved.status) || ((saved && saved.jobId) ? "running" : "idle"),
          phase: (saved && saved.phase) || "",
          phaseLabel: (saved && saved.phase) ? (LEDGER_PHASE_TEXT[saved.phase] || saved.phase) : "",
          result: (saved && saved.result) || null,
          error: (saved && saved.error) || "",
          pendingRequest: (saved && saved.pendingRequest) || null,
          busy: Boolean(saved && saved.jobId && (!saved.status || saved.status === "running" || saved.status === "queued")),
          pollScheduled: false,
          activeDrawerRowIndex: null,
          includeHeaders: (saved && typeof saved.includeHeaders === "boolean") ? saved.includeHeaders : true,
          targetRangeInfo: null,
          writing: false,
          writeStatus: interruptedWrite ? "interrupted" : (saved && saved.writeReport && saved.writeReport.success ? "success" : ""),
          writeError: interruptedWrite ? "上次写入的完成状态未能确认，请先核对工作表，再重新生成台账。" : "",
          writeReport: (saved && saved.writeReport) || null,
          partialWriteAddresses: []
        };
      }
      return states[sessionId];
    }

    function current() {
      return stateFor(getSessionId());
    }

    function persist(s, requireSaved) {
      try {
        storage.setItem("excel.material-ledger:" + s.documentSessionId, JSON.stringify({
          headers: s.headers,
          uncheckedHeaders: s.uncheckedHeaders,
          instruction: s.instruction,
          userFacts: s.userFacts,
          catalogSummary: s.catalogSummary,
          conflictResolutions: s.conflictResolutions,
          jobId: s.jobId,
          clientJobId: s.clientJobId,
          result: s.result,
          status: s.status,
          phase: s.phase,
          error: s.error,
          pendingRequest: s.pendingRequest,
          includeHeaders: s.includeHeaders,
          writeReport: s.writeReport,
          writeStatus: s.writeStatus
        }));
      } catch (e) {
        if (requireSaved) throw e;
        // Storage might fail in sandboxed iframe
      }
    }

    function notify(s) {
      s.catalogLabel = formatCatalogLabel(s.catalogSummary);
      s.phaseLabel = LEDGER_PHASE_TEXT[s.phase] || (s.phase ? s.phase : (s.status === "running" ? "处理中..." : ""));
      if (s.documentSessionId === getSessionId()) render(clone(s));
    }

    function setHeaders(headers) {
      var s = current();
      if (Array.isArray(headers) && headers.length) {
        var clean = headers.map(function (h) { return String(h || "").trim(); });
        if (clean.some(function (h) { return !h; })) throw new Error("表头包含空白列，请修正后读取。");
        if (clean.some(function (h, i) { return clean.indexOf(h) !== i; })) throw new Error("表头存在重名，请修正后读取。");
        s.headers = clean;
        s.uncheckedHeaders = [];
      } else {
        s.headers = DEFAULT_LEDGER_HEADERS.slice();
      }
      s.conflicts = [];
      s.conflictResolutions = [];
      persist(s);
      notify(s);
      return s.headers;
    }

    function setHeaderSelected(index, selected) {
      var s = current();
      if (s.busy || !s.headers[index]) return;
      s.uncheckedHeaders = s.uncheckedHeaders.filter(function (h) { return h !== s.headers[index]; });
      if (!selected) s.uncheckedHeaders.push(s.headers[index]);
      persist(s);
      notify(s);
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
      if (!app || !app.Selection || !app.Selection.Rows || Number(app.Selection.Rows.Count) !== 1) throw new Error("请选择单行表头。");
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
            extracted.push(val);
          } catch (e) { throw new Error("无法读取所选表头。"); }
        }
      }
      if (extracted.length !== Number(app.Selection.Columns.Count)) throw new Error("表头包含空白或重名列，请修正后读取。");
      if (extracted.length) {
        setHeaders(extracted);
      }
      return extracted;
    }

    function setInstruction(text) {
      var s = current();
      s.instruction = String(text || "").trim();
      s.conflicts = [];
      s.conflictResolutions = [];
      persist(s);
      notify(s);
    }

    function setUserFacts(text) {
      var s = current();
      s.userFacts = String(text || "").trim();
      s.conflicts = [];
      s.conflictResolutions = [];
      persist(s);
      notify(s);
    }

    function setConflictResolutions(resolutions) {
      var s = current();
      s.conflictResolutions = Array.isArray(resolutions) ? resolutions : [];
      persist(s);
      notify(s);
    }

    async function checkConflicts(sessionId) {
      var s = stateFor(sessionId || getSessionId());
      var userFacts = s.userFacts;
      try {
        var res = await request(
          "/excel/material-ledger/conflicts?documentSessionId=" + encodeURIComponent(s.documentSessionId) +
          "&userFacts=" + encodeURIComponent(userFacts || ""),
          null,
          { method: "GET" }
        );
        if (s.userFacts !== userFacts) return [];
        var previous = JSON.stringify(s.conflicts);
        if (res && res.data && res.data.conflicts) {
          s.conflicts = res.data.conflicts;
        } else if (res && Array.isArray(res.data)) {
          s.conflicts = res.data;
        }
        if (previous !== JSON.stringify(s.conflicts)) s.conflictResolutions = [];
        notify(s);
        return s.conflicts;
      } catch (err) {
        s.error = (err && err.message) || "核对事实差异失败";
        notify(s);
        throw err;
      }
    }

    async function listReusableSources(sessionId) {
      var s = stateFor(sessionId || getSessionId());
      try {
        var res = await request("/materials/reusable-sources", null, { method: "GET" });
        var list = ((res && res.data && res.data.sources) || []).filter(function (source) {
          return source.sourceSessionId !== s.documentSessionId;
        });
        s.reusableSources = list;
        notify(s);
        return list;
      } catch (err) {
        s.error = (err && err.message) || "读取可复用资料失败";
        notify(s);
        return [];
      }
    }

    async function cloneFromSource(sourceSessionId) {
      var s = current();
      if (s.busy) throw new Error("当前工作簿正在处理任务，请稍后变更资料。");
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
        s.conflicts = [];
        s.conflictResolutions = [];
        persist(s);
        notify(s);
        await checkConflicts(s.documentSessionId);
        return s.catalogSummary;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "复用资料失败";
        notify(s);
        throw err;
      }
    }

    async function finishDocConversion(stage, sessionId, materialId) {
      var url = materialId ? "/excel/materials/" + encodeURIComponent(materialId) : "/excel/materials/import";
      var method = { method: materialId ? "PUT" : "POST" };
      try {
        var app = typeof opts.getWordApp === "function" ? opts.getWordApp() : null;
        if (!app || !app.Documents || typeof app.Documents.Open !== "function") {
          throw new Error("当前 Excel 无法调用 WPS DOC 转换，请另存为 DOCX 后上传。");
        }
        var security = app.AutomationSecurity, alerts = app.DisplayAlerts, hostOptions = app.Options;
        if ([1, 2, 3].indexOf(security) < 0 || !hostOptions || typeof hostOptions.UpdateLinksAtOpen !== "boolean") {
          throw new Error("无法核验 DOC 转换的宏和外链保护，请另存为 DOCX 后上传。");
        }
        var links = hostOptions.UpdateLinksAtOpen, active = app.ActiveDocument, temporary = null;
        try {
          app.AutomationSecurity = 3;
          hostOptions.UpdateLinksAtOpen = false;
          if (app.AutomationSecurity !== 3 || hostOptions.UpdateLinksAtOpen !== false) throw new Error("DOC 转换安全设置未生效。");
          app.DisplayAlerts = 0;
          temporary = app.Documents.Open(stage.sourcePath, false, true, false, "", "", false, "", "", undefined, undefined, false);
          if (!temporary || typeof temporary.SaveAs2 !== "function") throw new Error("WPS 未提供 DOC 转换能力。");
          temporary.SaveAs2(stage.targetPath, 12, false, "", false);
        } finally {
          try { if (temporary) temporary.Close(0); }
          finally {
            app.AutomationSecurity = security;
            hostOptions.UpdateLinksAtOpen = links;
            app.DisplayAlerts = alerts;
            if (active && typeof active.Activate === "function") active.Activate();
          }
        }
        return await request(url, {documentSessionId:sessionId, conversionId:stage.conversionId}, method);
      } catch (error) {
        try { await request(url, {documentSessionId:sessionId, conversionId:stage.conversionId, cancelConversion:true}, method); }
        catch (cleanupError) { throw new Error(error.message + "；临时副本清理未确认，请重试。"); }
        throw error;
      }
    }

    async function importMaterial(upload, materialId, sessionId) {
      var s = stateFor(sessionId || getSessionId());
      if (s.busy) throw new Error("当前工作簿正在处理任务，请稍后变更资料。");
      s.busy = true;
      notify(s);
      try {
        var fileName = upload.fileName || upload.name;
        var contentBase64 = upload.contentBase64;
        if (!contentBase64) {
          if (typeof upload.arrayBuffer === "function") {
            var bytes = new Uint8Array(await upload.arrayBuffer());
            var binary = "";
            for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
            contentBase64 = btoa(binary);
          } else {
            contentBase64 = await new Promise(function (resolve, reject) {
              var reader = new FileReader();
              reader.onload = function () { resolve(String(reader.result || "").split(",").pop()); };
              reader.onerror = function () { reject(new Error("读取资料文件失败")); };
              reader.readAsDataURL(upload);
            });
          }
        }
        var res = await request(materialId ? "/excel/materials/" + encodeURIComponent(materialId) : "/excel/materials/import", {
          documentSessionId: s.documentSessionId,
          fileName: fileName,
          contentBase64: contentBase64
        }, { method: materialId ? "PUT" : "POST" });
        if (res && res.data && res.data.conversionRequired) {
          res = await finishDocConversion(res.data, s.documentSessionId, materialId);
        }
        if (res && res.data && res.data.catalogSummary) {
          s.catalogSummary = res.data.catalogSummary;
        } else {
          await loadCatalog(s.documentSessionId);
        }
        s.busy = false;
        s.conflicts = [];
        s.conflictResolutions = [];
        persist(s);
        notify(s);
        await checkConflicts(s.documentSessionId);
        return res && res.data;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "导入资料失败";
        notify(s);
        throw err;
      }
    }

    async function updateMaterial(materialId, upload, sessionId) {
      return importMaterial(upload, materialId, sessionId);
    }

    async function deleteMaterial(materialId) {
      var s = current();
      if (s.busy) throw new Error("当前工作簿正在处理任务，请稍后变更资料。");
      s.busy = true;
      notify(s);
      try {
        var res = await request("/excel/materials/" + encodeURIComponent(materialId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "DELETE" });
        if (res && res.data && res.data.catalogSummary) {
          s.catalogSummary = res.data.catalogSummary;
        } else {
          await loadCatalog(s.documentSessionId);
        }
        s.busy = false;
        s.conflicts = [];
        s.conflictResolutions = [];
        persist(s);
        notify(s);
        await checkConflicts(s.documentSessionId);
        return res && res.data;
      } catch (err) {
        s.busy = false;
        s.error = (err && err.message) || "删除资料失败";
        notify(s);
        throw err;
      }
    }

    async function loadCatalog(sessionId) {
      var s = stateFor(sessionId || getSessionId());
      try {
        var res = await request("/excel/materials/catalog?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "GET" });
        if (res && res.data) {
          s.catalogSummary = res.data;
          persist(s);
          notify(s);
        }
      } catch (err) {
        s.error = (err && err.message) || "读取资料目录失败";
        notify(s);
        throw err;
      }
    }

    function finishJob(s, job) {
      s.status = job.status;
      s.phase = job.phase || job.status;
      s.busy = job.status === "running" || job.status === "queued";
      if (job.status === "completed") {
        resetLedgerWriteState(s);
        s.result = job.result;
        s.error = "";
      } else if (job.status === "failed") {
        s.error = (job.error && job.error.message) || job.error || "台账提取失败";
      }
      if (!s.busy) {
        s.jobId = "";
        s.pendingRequest = null;
      }
      persist(s);
      notify(s);
    }

    async function generate() {
      var s = current();
      if (s.busy) return;
      var payload = s.pendingRequest;
      var selectedHeaders = s.headers.filter(function (h) { return s.uncheckedHeaders.indexOf(h) < 0; });
      if (!payload && !selectedHeaders.length) { s.error = "至少选择一列台账表头。"; notify(s); return; }
      s.activeDrawerRowIndex = null;
      s.busy = true;
      s.error = "";
      notify(s);
      if (!payload) {
        try {
          await checkConflicts(s.documentSessionId);
        } catch (err) { s.busy = false; notify(s); return; }
        if (s.conflicts.length && s.conflictResolutions.length !== s.conflicts.length) {
          s.busy = false;
          s.error = "资料存在事实差异，请先选择依据后再生成。";
          notify(s);
          return;
        }
        payload = clone({
          documentSessionId: s.documentSessionId,
          clientJobId: "job_" + Math.random().toString(36).slice(2, 10),
          headers: selectedHeaders,
          instruction: s.instruction,
          userFacts: s.userFacts,
          conflictResolutions: s.conflictResolutions
        });
      }
      s.pendingRequest = payload;
      s.clientJobId = payload.clientJobId;
      s.jobId = payload.clientJobId;
      s.status = "running";
      s.phase = "preparing";
      s.error = "";
      s.result = null;
      resetLedgerWriteState(s);
      s.busy = true;
      persist(s);
      notify(s);
      try {
        var res = await request("/excel/material-ledger/jobs", payload, { method: "POST" });
        var job = res && res.data;
        if (!job || !job.jobId) throw new Error("未返回任务编号，请恢复查询。");
        s.jobId = job.jobId;
        s.pendingRequest = null;
        finishJob(s, job);
        if (s.busy) pollJob(s.jobId, s.documentSessionId);
      } catch (err) {
        s.status = "interrupted";
        s.phase = "";
        s.busy = false;
        if (err && err.status >= 400 && err.status < 500) {
          s.pendingRequest = null;
          s.jobId = "";
          s.status = "failed";
        }
        s.error = (err && err.message) || "提交响应未确认，重试将恢复原任务。";
        persist(s);
        notify(s);
      }
    }

    function pollJob(jobId, sessionId) {
      var s = stateFor(sessionId || getSessionId());
      if (!jobId || s.jobId !== jobId || s.pollScheduled || !s.busy) return;
      s.pollScheduled = true;
      schedule(async function () {
        s.pollScheduled = false;
        if (s.jobId !== jobId || !s.busy) return;
        try {
          var res = await request("/excel/material-ledger/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "GET" });
          if (s.jobId !== jobId) return;
          if (!res || !res.data) throw new Error("任务状态响应无效");
          finishJob(s, res.data);
          if (s.busy) pollJob(jobId, s.documentSessionId);
        } catch (err) {
          if (s.jobId !== jobId) return;
          if (err && err.status === 404) {
            s.jobId = "";
            s.status = "interrupted";
            s.phase = "";
            s.busy = false;
            s.error = "原任务不存在，可能因 Adapter 重启而中断，请重新提交。";
            persist(s);
            notify(s);
          } else {
            s.error = (err && err.message) || "状态查询暂时失败，正在恢复。";
            notify(s);
            pollJob(jobId, s.documentSessionId);
          }
        }
      }, 1000);
    }

    async function cancel() {
      var s = current();
      if (!s.jobId) return;
      try {
        var res = await request("/excel/material-ledger/jobs/" + encodeURIComponent(s.jobId) + "/cancel", {
          documentSessionId: s.documentSessionId
        }, { method: "POST" });
        if (!res || !res.data) throw new Error("取消响应无效");
        finishJob(s, res.data);
        if (s.busy) pollJob(s.jobId, s.documentSessionId);
      } catch (err) {
        s.error = "取消失败：" + ((err && err.message) || "请稍后重试");
        notify(s);
      }
    }

    function setResult(result) {
      var s = current();
      finishJob(s, { status: "completed", result: result });
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

    function resetLedgerWriteState(s) {
      s.targetRangeInfo = null;
      s.writing = false;
      s.writeStatus = "";
      s.writeError = "";
      s.writeReport = null;
      s.partialWriteAddresses = [];
    }

    function setIncludeHeaders(val) {
      var s = current();
      if ((s.writeReport && s.writeReport.success) || s.writeStatus === "interrupted") {
        notify(s);
        return s.includeHeaders;
      }
      s.includeHeaders = Boolean(val);
      s.targetRangeInfo = null;
      s.writeStatus = "";
      persist(s);
      notify(s);
      return s.includeHeaders;
    }

    function inspectTargetRange(app) {
      var s = current();
      if (s.writeStatus === "interrupted") {
        notify(s);
        return { valid: false, error: s.writeError };
      }
      if (s.writeReport && s.writeReport.success) {
        notify(s);
        return { valid: false, error: "本次台账已完成写入，请生成新台账。" };
      }
      var h = opts.helpers || (typeof window !== "undefined" && window.WpsAiAssistantHelpers) || (typeof globalThis !== "undefined" && globalThis.WpsAiAssistantHelpers) || {};
      if (!s.result || !Array.isArray(s.result.rows) || !s.result.rows.length) {
        s.targetRangeInfo = null;
        s.writeStatus = "error";
        s.writeError = "尚未生成台账结果";
        notify(s);
        return { valid: false, error: s.writeError };
      }
      var rowCount = s.result.rows.length + (s.includeHeaders ? 1 : 0);
      var colCount = (Array.isArray(s.result.headers) && s.result.headers.length) ? s.result.headers.length : (Array.isArray(s.headers) ? s.headers.length : 1);
      try {
        if (typeof h.resolveExcelLedgerTargetRange !== "function") {
          throw new Error("目标区域解析函数不可用");
        }
        var info = h.resolveExcelLedgerTargetRange(app, rowCount, colCount);
        if (typeof h.validateExcelLedgerTargetBlank === "function") {
          h.validateExcelLedgerTargetBlank(app, info, { documentSessionId: s.documentSessionId });
        }
        s.targetRangeInfo = info;
        s.writeStatus = "ready";
        s.writeError = "";
        notify(s);
        return { valid: true, info: info };
      } catch (err) {
        s.targetRangeInfo = null;
        s.writeStatus = "error";
        s.writeError = (err && err.message) || String(err);
        notify(s);
        return { valid: false, error: s.writeError };
      }
    }

    async function writeToSheet(app, options) {
      var s = current();
      if (s.status !== "completed" || !s.result || !Array.isArray(s.result.rows) || !s.result.rows.length) {
        throw new Error("没有可写入的已完成台账");
      }
      if (s.writeReport && s.writeReport.success) {
        return s.writeReport;
      }
      if (s.writeStatus === "interrupted") {
        throw new Error(s.writeError);
      }
      if (s.writing) {
        return s.writeReport;
      }
      if (!s.targetRangeInfo) {
        throw new Error("请先检测并确认目标区域。");
      }
      var h = opts.helpers || (typeof window !== "undefined" && window.WpsAiAssistantHelpers) || (typeof globalThis !== "undefined" && globalThis.WpsAiAssistantHelpers) || {};
      s.writing = true;
      s.writeStatus = "writing";
      notify(s);
      try {
        if (typeof h.writeExcelMaterialLedger !== "function") {
          throw new Error("写入辅助函数不可用");
        }
        try {
          persist(s, true);
        } catch (storageErr) {
          throw new Error("无法保存台账写入状态，本次未执行写入，请检查窗格存储后重试。");
        }
        var report = h.writeExcelMaterialLedger(app, s.result, {
          includeHeaders: s.includeHeaders,
          documentSessionId: s.documentSessionId,
          targetRangeInfo: s.targetRangeInfo
        });
        s.writing = false;
        s.writeStatus = "success";
        s.writeError = "";
        s.partialWriteAddresses = [];
        s.writeReport = report;
        try {
          persist(s, true);
        } catch (storageErr) {
          report.persistenceWarning = "完成状态未能保存；重开窗格后请先核对工作表，再重新生成台账。";
        }
        notify(s);
        return report;
      } catch (err) {
        s.writing = false;
        s.writeStatus = "error";
        s.writeError = (err && err.message) || "写入失败，请检查工作表";
        s.partialWriteAddresses = (err && err.rollbackFailures) || [];
        try {
          persist(s, true);
        } catch (storageErr) {
          s.writeError += " 写入状态未能保存，重开窗格后需先核对工作表。";
        }
        notify(s);
        throw err;
      }
    }

    async function restore() {
      var s = current();
      notify(s);
      await loadCatalog(s.documentSessionId);
      await listReusableSources(s.documentSessionId);
      if (s.jobId && s.busy) {
        pollJob(s.jobId, s.documentSessionId);
      }
    }

    // Initial render
    notify(current());

    return {
      getState: current,
      setHeaders: setHeaders,
      setHeaderSelected: setHeaderSelected,
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
      updateMaterial: updateMaterial,
      loadCatalog: loadCatalog,
      generate: generate,
      cancel: cancel,
      setResult: setResult,
      formatTsv: formatTsv,
      copyTsv: copyTsv,
      openSourceDrawer: openSourceDrawer,
      closeSourceDrawer: closeSourceDrawer,
      setIncludeHeaders: setIncludeHeaders,
      inspectTargetRange: inspectTargetRange,
      writeToSheet: writeToSheet,
      restore: restore
    };
  }

  return {
    createMaterialLedger: createMaterialLedger,
    DEFAULT_LEDGER_HEADERS: DEFAULT_LEDGER_HEADERS,
    LEDGER_PHASE_TEXT: LEDGER_PHASE_TEXT
  };
});
