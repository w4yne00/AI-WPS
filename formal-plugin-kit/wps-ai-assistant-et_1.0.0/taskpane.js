(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.18.0-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var EXCEL_ANALYSIS_POLL_INTERVAL_MS = 3000;
  var EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS = 10000;
  var EXCEL_ANALYSIS_POLL_MAX_ERRORS = 240;
  var EXCEL_ANALYSIS_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY = "ai-wps-excel-analysis-active-job-v1";
  var EXCEL_EXTRACTION_OPTIONS = {
    maxRows: 120,
    maxColumns: 30,
    maxCellTextLength: 120,
    maxTotalTextLength: 20000
  };
  var TASK_API_KEY_DEFS = [
    { taskType: "excel.analysis", label: "智能分析" }
  ];
  var EXCEL_WORKFLOW_TASK_TYPE = "excel.analysis";
  var state = {
    currentMode: "excelAnalysis",
    traceId: "",
    copyText: "",
    diagnosticsCopyText: "",
    analysisRequirement: "",
    analysisResult: null,
    resultViewMode: "preview",
    latestExcelPayload: null,
    providerBaseUrl: "",
    taskApiKeys: {},
    workflowProfiles: null,
    workflowProfileSelection: "",
    workflowProfileLoadSequence: 0,
    workflowProfileMutationBusy: false,
    workflowEditor: { open: false, mode: "create", profileId: "", dirty: false },
    workflowDeleteCandidate: null,
    busy: false,
    scopeWatcher: null,
    excelAnalysisJobId: "",
    excelAnalysisPollStartedAt: 0,
    excelAnalysisPollErrorCount: 0
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function isTaskpanePage() {
    return Boolean(byId(TASKPANE_ROOT_ID));
  }

  function safeCall(fn, thisArg, args) {
    if (typeof fn !== "function") {
      return undefined;
    }
    try {
      return fn.apply(thisArg, args || []);
    } catch (error) {
      return undefined;
    }
  }

  function safeRead(object, key) {
    if (!object) {
      return undefined;
    }
    try {
      return object[key];
    } catch (error) {
      return undefined;
    }
  }

  function resolveValue(value, thisArg) {
    return typeof value === "function" ? safeCall(value, thisArg) : value;
  }

  function resolveScalarValue(value, depth) {
    var resolved = typeof value === "function" ? safeCall(value, null) : value;
    var keys;
    var index;
    var nested;
    var primitive;
    depth = depth || 0;
    if (typeof resolved === "undefined" || resolved === null) {
      return resolved;
    }
    if (typeof resolved === "string" || typeof resolved === "number" || typeof resolved === "boolean") {
      return resolved;
    }
    if (depth >= 3 || Array.isArray(resolved) || typeof resolved !== "object") {
      return undefined;
    }
    keys = ["value", "Value", "text", "Text"];
    for (index = 0; index < keys.length; index += 1) {
      nested = safeRead(resolved, keys[index]);
      if (typeof nested !== "undefined" && nested !== null) {
        return resolveScalarValue(nested, depth + 1);
      }
    }
    if (typeof resolved.valueOf === "function" && resolved.valueOf !== Object.prototype.valueOf) {
      primitive = safeCall(resolved.valueOf, resolved);
      if (primitive !== resolved) {
        return resolveScalarValue(primitive, depth + 1);
      }
    }
    if (typeof resolved.toString === "function" && resolved.toString !== Object.prototype.toString) {
      primitive = safeCall(resolved.toString, resolved);
      if (primitive && primitive !== "[object Object]") {
        return primitive;
      }
    }
    return undefined;
  }

  function safeText(value, fallback) {
    var resolved = resolveScalarValue(value);
    if (typeof resolved === "undefined" || resolved === null) {
      return fallback || "";
    }
    return String(resolved).replace(/\r/g, "").trim();
  }

  function readNumber(value) {
    var resolved = resolveScalarValue(value);
    var numeric = Number(resolved);
    return isNaN(numeric) || numeric < 0 ? 0 : Math.floor(numeric);
  }

  function truncateText(text, maxLength) {
    var value = String(text || "");
    if (maxLength && value.length > maxLength) {
      return value.slice(0, maxLength);
    }
    return value;
  }

  function setStatus(message) {
    byId("status-line").textContent = message || "";
    byId("settings-status-line").textContent = message || "";
  }

  function setAnalysisBusy(isBusy) {
    state.busy = Boolean(isBusy);
    byId("btn-run-primary").disabled = state.busy || state.workflowProfileMutationBusy;
    renderWorkflowProfileStrip();
  }

  function setTrace(traceId) {
    state.traceId = traceId || "";
    byId("trace-line").textContent = traceId || "未检测";
  }

  function buildExcelAnalysisClientJobId() {
    return [
      "client-excel-analysis",
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 10)
    ].join("-");
  }

  function loadExcelAnalysisActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveExcelAnalysisActiveJob(job) {
    if (!job || !job.jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY, JSON.stringify({
          jobId: job.jobId,
          traceId: job.traceId || "",
          startedAt: job.startedAt || Date.now(),
          frontendVersion: FRONTEND_BUILD_VERSION
        }));
      }
    } catch (error) {
      // Some WPS WebView modes disable localStorage; in-memory polling remains available.
    }
  }

  function clearExcelAnalysisActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      if (jobId) {
        active = loadExcelAnalysisActiveJob();
        if (active && active.jobId && active.jobId !== jobId) {
          return;
        }
      }
      window.localStorage.removeItem(EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Storage cleanup must not block result rendering.
    }
  }

  function setHealthBadge(mode, text) {
    var node = byId("health-indicator");
    node.className = "badge " + mode;
    node.textContent = text;
  }

  function setScopeLine(label) {
    var text = label || "未检测";
    byId("scope-line").textContent = text;
    byId("settings-scope-line").textContent = text;
  }

  function setResult(markdown, copyText) {
    var output = byId("result-output");
    output.hidden = false;
    output.classList.remove("plain-output");
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(markdown || "");
    } else {
      output.textContent = markdown || "";
    }
    state.copyText = typeof copyText === "string" ? copyText : (markdown || "");
  }

  function setPlainResult(text, copyText) {
    var output = byId("result-output");
    output.hidden = false;
    output.classList.add("plain-output");
    output.textContent = text || "";
    state.copyText = typeof copyText === "string" ? copyText : (text || "");
  }

  function request(path, payload, requestOptions) {
    var timeoutMs = requestOptions && requestOptions.timeoutMs;
    var requestMethod = requestOptions && requestOptions.method;
    var controller = null;
    var timeoutId = null;
    var options = {
      method: requestMethod || (payload ? "POST" : "GET")
    };
    if (payload) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    }
    if (timeoutMs && typeof AbortController !== "undefined") {
      controller = new AbortController();
      options.signal = controller.signal;
      timeoutId = setTimeout(function () {
        controller.abort();
      }, timeoutMs);
    }
    return fetch(ADAPTER_BASE_URL + path, options).then(function (response) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      return response.json().then(function (body) {
        if (!response.ok) {
          var validation = body.data && body.data.validation;
          var adapterError = (body.errors && body.errors[0]) || {};
          var details;
          var requestError;
          if (validation && validation.errors && validation.errors.length) {
            details = validation.errors.map(function (item) {
              return [item.loc, item.type, item.message].filter(Boolean).join(" | ");
            }).join("\n");
            requestError = new Error("HTTP " + response.status + " 请求数据校验失败：\n" + details);
            requestError.adapterCode = "REQUEST_VALIDATION_FAILED";
            throw requestError;
          }
          requestError = new Error(adapterError.message || body.message || ("HTTP " + response.status));
          requestError.adapterCode = adapterError.code || "";
          throw requestError;
        }
        return body;
      });
    }, function (error) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      throw error;
    });
  }

  function describeFetchError(error) {
    var message = error && error.message ? error.message : String(error || "");
    if (message === "Failed to fetch" || message.indexOf("NetworkError") >= 0) {
      return "插件无法访问 http://127.0.0.1:18100。请确认 adapter 正在运行、端口为 18100，并重新打开任务窗格。";
    }
    return message;
  }

  function describeExcelAnalysisPollError(error) {
    var message = describeFetchError(error);
    if (error && error.name === "AbortError") {
      return "状态查询请求超过 10 秒未返回，将继续自动刷新。";
    }
    if (error && error.adapterCode === "PROVIDER_TIMEOUT") {
      return "模型后台智能分析仍未按时返回，adapter 可能仍在等待或已返回超时诊断。";
    }
    if (message.indexOf("插件无法访问 http://127.0.0.1:18100") === 0) {
      return "状态查询暂时未连上本地 adapter；这不代表模型后台任务失败，将继续自动刷新。";
    }
    return message;
  }

  function readAdapterJson(path) {
    return request(path).catch(function (error) {
      return {
        success: false,
        data: {},
        errors: [{ message: describeFetchError(error) }]
      };
    });
  }

  function getEtApplication() {
    return window.Application || window.wps || {};
  }

  function getActiveWorkbook(app) {
    return resolveValue(safeRead(app, "ActiveWorkbook"), app) ||
      resolveValue(safeRead(app, "activeWorkbook"), app) ||
      {};
  }

  function getActiveSheet(app) {
    return resolveValue(safeRead(app, "ActiveSheet"), app) ||
      resolveValue(safeRead(app, "activeSheet"), app) ||
      {};
  }

  function getSelectionRange(app) {
    var activeWindow = resolveValue(safeRead(app, "ActiveWindow"), app) || {};
    return resolveValue(safeRead(app, "Selection"), app) ||
      resolveValue(safeRead(app, "selection"), app) ||
      resolveValue(safeRead(activeWindow, "Selection"), activeWindow) ||
      resolveValue(safeRead(activeWindow, "selection"), activeWindow) ||
      null;
  }

  function getUsedRange(sheet) {
    return resolveValue(safeRead(sheet, "UsedRange"), sheet) ||
      resolveValue(safeRead(sheet, "usedRange"), sheet) ||
      null;
  }

  function getCollectionCount(collection) {
    var count;
    if (!collection) {
      return 0;
    }
    count = safeRead(collection, "Count");
    if (typeof count === "function") {
      count = safeCall(count, collection);
    }
    if (typeof count === "undefined" || count === null || count === "") {
      count = safeRead(collection, "count");
      if (typeof count === "function") {
        count = safeCall(count, collection);
      }
    }
    if (typeof count === "undefined" || count === null || count === "") {
      count = safeRead(collection, "length");
    }
    return readNumber(count);
  }

  function getRangeCell(range, rowIndex, columnIndex) {
    var cells = resolveValue(safeRead(range, "Cells"), range) || range;
    var item = safeRead(cells, "Item") || safeRead(cells, "item");
    var cell;
    if (typeof item === "function") {
      cell = safeCall(item, cells, [rowIndex, columnIndex]);
      if (cell) {
        return cell;
      }
    }
    if (typeof cells === "function") {
      cell = safeCall(cells, range, [rowIndex, columnIndex]);
      if (cell) {
        return cell;
      }
    }
    return safeRead(cells, rowIndex + "," + columnIndex) ||
      safeRead(safeRead(cells, rowIndex), columnIndex) ||
      safeRead(safeRead(cells, rowIndex - 1), columnIndex - 1) ||
      null;
  }

  function readCellText(cell) {
    return truncateText(safeText(
      safeRead(cell, "Text") ||
      safeRead(cell, "text") ||
      safeRead(cell, "Value2") ||
      safeRead(cell, "value2") ||
      safeRead(cell, "Value") ||
      safeRead(cell, "value")
    ), EXCEL_EXTRACTION_OPTIONS.maxCellTextLength);
  }

  function getRangeAddress(range) {
    return safeText(
      resolveValue(safeRead(range, "Address"), range) ||
      resolveValue(safeRead(range, "address"), range),
      ""
    );
  }

  function readRangeMatrix(range) {
    var rows = resolveValue(safeRead(range, "Rows"), range) || resolveValue(safeRead(range, "rows"), range);
    var columns = resolveValue(safeRead(range, "Columns"), range) || resolveValue(safeRead(range, "columns"), range);
    var rowCount = getCollectionCount(rows);
    var columnCount = getCollectionCount(columns);
    var maxRows = Math.min(rowCount, EXCEL_EXTRACTION_OPTIONS.maxRows);
    var maxColumns = Math.min(columnCount, EXCEL_EXTRACTION_OPTIONS.maxColumns);
    var values = [];
    var totalLength = 0;
    var totalTruncated = false;
    var rowIndex;
    var columnIndex;
    var row;
    var text;

    if (!range || !rowCount || !columnCount) {
      return { rows: [], rowCount: 0, columnCount: 0, truncated: false };
    }

    for (rowIndex = 1; rowIndex <= maxRows; rowIndex += 1) {
      row = [];
      for (columnIndex = 1; columnIndex <= maxColumns; columnIndex += 1) {
        text = readCellText(getRangeCell(range, rowIndex, columnIndex));
        totalLength += text.length;
        if (totalLength > EXCEL_EXTRACTION_OPTIONS.maxTotalTextLength) {
          text = "";
          totalTruncated = true;
        }
        row.push(text);
      }
      values.push(row);
      if (totalTruncated) {
        break;
      }
    }

    return {
      rows: values,
      rowCount: rowCount,
      columnCount: columnCount,
      truncated: totalTruncated ||
        rowCount > EXCEL_EXTRACTION_OPTIONS.maxRows ||
        columnCount > EXCEL_EXTRACTION_OPTIONS.maxColumns
    };
  }

  function hasUsableMatrix(matrix) {
    return Boolean(matrix && matrix.rowCount && matrix.columnCount && (matrix.rows || []).some(function (row) {
      return row.some(function (cell) {
        return Boolean(String(cell || "").trim());
      });
    }));
  }

  function normalizeMatrix(matrix) {
    var rows = matrix.rows || [];
    var headers = rows.length ? rows[0].map(function (cell, index) {
      return cell || "列" + (index + 1);
    }) : [];
    var bodyRows = rows.slice(1);
    return {
      headers: headers,
      rows: bodyRows,
      rowCount: Math.max((matrix.rowCount || 0) - 1, bodyRows.length),
      columnCount: matrix.columnCount || 0,
      truncated: Boolean(matrix.truncated)
    };
  }

  function summarizeExcelPayload(payload) {
    var scope = payload.scope || {};
    var table = payload.table || {};
    var parts = [
      scope.type === "selection" ? "选区" : "已用范围",
      scope.sheetName || "当前工作表",
      scope.address || "未识别地址",
      (table.rowCount || 0) + " 行",
      (table.columnCount || 0) + " 列"
    ];
    if (table.truncated) {
      parts.push("已截断");
    }
    return parts.join(" / ");
  }

  function summarizeExcelRange() {
    var app = getEtApplication();
    var sheet = getActiveSheet(app);
    var selection = getSelectionRange(app);
    var range = selection || getUsedRange(sheet);
    var rows = range && (resolveValue(safeRead(range, "Rows"), range) || resolveValue(safeRead(range, "rows"), range));
    var columns = range && (resolveValue(safeRead(range, "Columns"), range) || resolveValue(safeRead(range, "columns"), range));
    var rowCount = getCollectionCount(rows);
    var columnCount = getCollectionCount(columns);
    if (!range || !rowCount || !columnCount) {
      return "未检测到可分析范围";
    }
    return [
      selection ? "选区" : "已用范围",
      safeText(safeRead(sheet, "Name") || safeRead(sheet, "name"), "当前工作表"),
      getRangeAddress(range) || "未识别地址",
      rowCount + " 行",
      columnCount + " 列"
    ].join(" / ");
  }

  function updateScopeIndicator() {
    try {
      setScopeLine(summarizeExcelRange());
    } catch (error) {
      setScopeLine("未检测到可分析范围");
    }
  }

  function startScopeWatcher() {
    if (state.scopeWatcher) {
      return;
    }
    updateScopeIndicator();
    state.scopeWatcher = setInterval(updateScopeIndicator, 1200);
  }

  function extractExcelRange() {
    var app = getEtApplication();
    var workbook = getActiveWorkbook(app);
    var sheet = getActiveSheet(app);
    var range = getSelectionRange(app);
    var scopeType = "selection";
    var matrix = readRangeMatrix(range);
    var table;

    if (!hasUsableMatrix(matrix)) {
      range = getUsedRange(sheet);
      scopeType = "usedRange";
      matrix = readRangeMatrix(range);
    }

    if (!hasUsableMatrix(matrix)) {
      throw new Error("未检测到可分析的选区或已用范围。");
    }

    table = normalizeMatrix(matrix);
    return {
      workbookId: safeText(safeRead(workbook, "Name") || safeRead(workbook, "name"), "active-workbook") || "active-workbook",
      scene: "excel",
      scope: {
        type: scopeType,
        sheetName: safeText(safeRead(sheet, "Name") || safeRead(sheet, "name"), "Sheet1") || "Sheet1",
        address: getRangeAddress(range)
      },
      table: table,
      options: {
        analysisRequirement: state.analysisRequirement
      }
    };
  }

  function normalizeReportList(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) {
        return String(item || "").trim();
      }).filter(Boolean);
    }
    if (typeof value === "string" && value.trim()) {
      return [value.trim()];
    }
    return [];
  }

  function buildExcelAnalysisMarkdown(data) {
    var report = (data && data.structuredReport) || {};
    var findings = normalizeReportList(report.findings);
    var risks = normalizeReportList(report.risks);
    var actions = normalizeReportList(report.actions);
    return [
      "## 数据概览",
      report.overview || "未返回数据概览。",
      "",
      "## 关键发现",
      findings.length ? findings.map(function (item) { return "- " + item; }).join("\n") : "- 未返回关键发现。",
      "",
      "## 风险异常",
      risks.length ? risks.map(function (item) { return "- " + item; }).join("\n") : "- 未返回风险异常。",
      "",
      "## 建议动作",
      actions.length ? actions.map(function (item) { return "- " + item; }).join("\n") : "- 未返回建议动作。"
    ].join("\n");
  }

  function updateResultViewButtons() {
    [
      { id: "btn-result-preview", mode: "preview" },
      { id: "btn-result-plain", mode: "plain" }
    ].forEach(function (item) {
      var button = byId(item.id);
      var active = state.resultViewMode === item.mode;
      if (button) {
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      }
    });
  }

  function renderExcelAnalysisResult(data) {
    var markdown = buildExcelAnalysisMarkdown(data || {});
    state.analysisResult = data || {};
    state.resultViewMode = "preview";
    byId("result-view-switch").hidden = false;
    updateResultViewButtons();
    setResult(markdown, markdown);
  }

  function startExcelAnalysisWaitFeedback() {
    var timers = [];
    timers.push(setTimeout(function () {
      setStatus("模型后台正在处理智能分析，请继续等待...");
      setPlainResult("智能分析请求已提交，模型后台正在处理。数据量较大或繁忙时可能需要更久，请保持 WPS 和 adapter 打开。");
    }, 8000));
    timers.push(setTimeout(function () {
      setStatus("智能分析仍在等待模型后台返回...");
      setPlainResult("智能分析仍在等待模型后台返回。任务窗格会继续自动刷新，无需重复点击分析按钮。");
    }, 30000));
    return function () {
      timers.forEach(function (timer) {
        clearTimeout(timer);
      });
    };
  }

  function scheduleExcelAnalysisPoll(jobId, stopWaiting, delayMs) {
    setTimeout(function () {
      pollExcelAnalysisJob(jobId, stopWaiting);
    }, delayMs);
  }

  function isFatalExcelAnalysisPollError(error) {
    return error && (
      error.adapterCode === "EXCEL_ANALYSIS_JOB_NOT_FOUND" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function pollExcelAnalysisJob(jobId, stopWaiting) {
    if (!jobId || state.excelAnalysisJobId !== jobId) {
      return;
    }
    request("/excel/analysis/jobs/" + encodeURIComponent(jobId), null, {
      timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
    })
      .then(function (body) {
        var job = body.data || {};
        if (state.excelAnalysisJobId !== jobId) {
          return;
        }
        state.excelAnalysisPollErrorCount = 0;
        setTrace(body.traceId || job.traceId || jobId);
        saveExcelAnalysisActiveJob({
          jobId: jobId,
          traceId: body.traceId || job.traceId || "",
          startedAt: state.excelAnalysisPollStartedAt || Date.now()
        });
        if (job.status === "completed") {
          clearExcelAnalysisActiveJob(jobId);
          state.excelAnalysisJobId = "";
          state.excelAnalysisPollStartedAt = 0;
          stopWaiting();
          renderExcelAnalysisResult(job.result || {});
          setStatus("智能分析报告已生成。");
          refreshDiagnostics().then(function () {
            setStatus("智能分析报告已生成。");
          });
          return;
        }
        if (job.status === "failed") {
          clearExcelAnalysisActiveJob(jobId);
          state.excelAnalysisJobId = "";
          state.excelAnalysisPollStartedAt = 0;
          stopWaiting();
          setStatus("智能分析失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
          setResult((job.error && job.error.message) || "后台任务执行失败。");
          return;
        }
        setStatus("智能分析仍在模型后台处理中...");
        setPlainResult([
          job.runningMessage || "模型后台正在处理智能分析。",
          "已等待：" + (job.elapsedSeconds || 0) + " 秒",
          "adapter 等待预算：" + (job.providerTimeoutSeconds || 1800) + " 秒",
          "任务编号：" + jobId
        ].join("\n"));
        scheduleExcelAnalysisPoll(jobId, stopWaiting, EXCEL_ANALYSIS_POLL_INTERVAL_MS);
      })
      .catch(function (error) {
        var elapsed;
        var message;
        var withinRetryBudget;
        var retryDelay;
        if (state.excelAnalysisJobId !== jobId) {
          return;
        }
        message = describeExcelAnalysisPollError(error);
        state.excelAnalysisPollErrorCount = (state.excelAnalysisPollErrorCount || 0) + 1;
        elapsed = Date.now() - (state.excelAnalysisPollStartedAt || Date.now());
        if (!isFatalExcelAnalysisPollError(error)) {
          withinRetryBudget = (
            state.excelAnalysisPollErrorCount <= EXCEL_ANALYSIS_POLL_MAX_ERRORS &&
            elapsed <= EXCEL_ANALYSIS_POLL_MAX_WAIT_MS
          );
          retryDelay = withinRetryBudget
            ? EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS
            : EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS;
          saveExcelAnalysisActiveJob({
            jobId: jobId,
            traceId: state.traceId || "",
            startedAt: state.excelAnalysisPollStartedAt || Date.now()
          });
          setStatus(withinRetryBudget
            ? "智能分析状态查询暂时失败，正在继续等待模型后台返回..."
            : "智能分析任务连接中断，正在尝试恢复状态查询...");
          setPlainResult([
            withinRetryBudget
              ? "智能分析状态查询暂时失败，adapter 后台任务可能仍在执行，将继续自动刷新。"
              : "智能分析任务连接中断，前台不会丢弃任务编号，将继续低频自动刷新。",
            "这不代表模型后台任务失败；如果模型后台已收到请求，请保持 WPS 和 adapter 打开。",
            "已重试：" + state.excelAnalysisPollErrorCount + "/" + EXCEL_ANALYSIS_POLL_MAX_ERRORS,
            "任务编号：" + jobId,
            "最近错误：" + message
          ].join("\n"));
          scheduleExcelAnalysisPoll(jobId, stopWaiting, retryDelay);
          return;
        }
        clearExcelAnalysisActiveJob(jobId);
        state.excelAnalysisJobId = "";
        state.excelAnalysisPollStartedAt = 0;
        state.excelAnalysisPollErrorCount = 0;
        stopWaiting();
        setStatus("智能分析状态查询持续失败，请查看最近一次任务诊断。");
        setResult(message);
      });
  }

  function resumeExcelAnalysisActiveJob() {
    var active = loadExcelAnalysisActiveJob();
    if (!active || !active.jobId || state.currentMode !== "excelAnalysis") {
      return;
    }
    state.excelAnalysisJobId = active.jobId;
    state.excelAnalysisPollStartedAt = active.startedAt || Date.now();
    state.excelAnalysisPollErrorCount = 0;
    setAnalysisBusy(true);
    setTrace(active.traceId || active.jobId);
    setStatus("已恢复未完成的智能分析任务，正在查询模型后台结果...");
    setPlainResult([
      "检测到未完成的智能分析任务，将继续查询 adapter 后台状态。",
      "如果模型后台仍在处理，请保持 WPS 和 adapter 打开。",
      "任务编号：" + active.jobId
    ].join("\n"));
    pollExcelAnalysisJob(active.jobId, function () {
      setAnalysisBusy(false);
    });
  }

  function setResultViewMode(mode) {
    var plainText;
    state.resultViewMode = mode === "plain" ? "plain" : "preview";
    updateResultViewButtons();
    if (!state.analysisResult) {
      return;
    }
    if (state.resultViewMode === "plain") {
      plainText = state.analysisResult.plainText || "";
      setPlainResult(plainText || "模型后台未返回汇报段落。", plainText);
      return;
    }
    setResult(buildExcelAnalysisMarkdown(state.analysisResult), buildExcelAnalysisMarkdown(state.analysisResult));
  }

  function runExcelAnalysisAction() {
    var stopWaiting;
    var clientJobId;
    var startedAt;
    if (state.busy || state.workflowProfileMutationBusy) {
      return;
    }
    setAnalysisBusy(true);
    state.analysisRequirement = safeText(byId("excel-analysis-requirement").value);
    state.analysisResult = null;
    clearExcelAnalysisActiveJob();
    state.excelAnalysisJobId = "";
    state.excelAnalysisPollStartedAt = 0;
    state.excelAnalysisPollErrorCount = 0;
    byId("result-view-switch").hidden = true;
    setStatus("正在读取 Excel 表格范围...");
    setPlainResult("正在读取 Excel 表格范围，请稍候。");

    setTimeout(function () {
      try {
        state.latestExcelPayload = extractExcelRange();
        byId("excel-range-summary").textContent = summarizeExcelPayload(state.latestExcelPayload);
        setScopeLine(summarizeExcelPayload(state.latestExcelPayload));
      } catch (error) {
        setAnalysisBusy(false);
        setStatus("读取 Excel 表格失败：" + error.message);
        setResult("读取 Excel 表格失败：" + error.message);
        return;
      }

      setStatus("正在提交智能分析请求...");
      setPlainResult("正在等待模型后台生成分析报告。");
      stopWaiting = startExcelAnalysisWaitFeedback();
      (function (stopFeedback) {
        stopWaiting = function () {
          stopFeedback();
          setAnalysisBusy(false);
        };
      })(stopWaiting);
      clientJobId = buildExcelAnalysisClientJobId();
      startedAt = Date.now();
      state.latestExcelPayload.clientJobId = clientJobId;
      state.excelAnalysisJobId = clientJobId;
      state.excelAnalysisPollStartedAt = startedAt;
      state.excelAnalysisPollErrorCount = 0;
      saveExcelAnalysisActiveJob({
        jobId: clientJobId,
        traceId: "",
        startedAt: startedAt
      });
      request("/excel/analysis/jobs", state.latestExcelPayload, {
        timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
      })
        .then(function (body) {
          var job = body.data || {};
          var jobId = job.jobId || clientJobId || body.traceId;
          if (state.excelAnalysisJobId !== clientJobId) {
            return;
          }
          setTrace(body.traceId || job.traceId || jobId);
          if (!jobId) {
            clearExcelAnalysisActiveJob(clientJobId);
            stopWaiting();
            setStatus("智能分析失败：adapter 未返回后台任务编号。");
            setResult("adapter 未返回后台任务编号，请重试或查看最近一次任务诊断。");
            return;
          }
          state.excelAnalysisJobId = jobId;
          saveExcelAnalysisActiveJob({
            jobId: jobId,
            traceId: body.traceId || job.traceId || "",
            startedAt: startedAt
          });
          if (job.status === "completed") {
            clearExcelAnalysisActiveJob(jobId);
            state.excelAnalysisJobId = "";
            state.excelAnalysisPollStartedAt = 0;
            stopWaiting();
            renderExcelAnalysisResult(job.result || {});
            setStatus("智能分析报告已生成。");
            return;
          }
          setStatus("智能分析任务已提交，模型后台处理中...");
          setPlainResult("智能分析任务已提交。adapter 会在后台等待模型后台返回，此处将自动刷新结果。");
          pollExcelAnalysisJob(jobId, stopWaiting);
        })
        .catch(function (error) {
          var message = describeExcelAnalysisPollError(error);
          if (state.excelAnalysisJobId !== clientJobId) {
            return;
          }
          if (isFatalExcelAnalysisPollError(error)) {
            clearExcelAnalysisActiveJob(clientJobId);
            state.excelAnalysisJobId = "";
            state.excelAnalysisPollStartedAt = 0;
            stopWaiting();
            setStatus("智能分析失败：" + message);
            setResult(message);
            return;
          }
          setStatus("智能分析提交响应未确认，正在按任务编号恢复状态查询...");
          setPlainResult([
            "智能分析任务可能已经提交到 adapter，但任务窗格没有收到确认响应。",
            "将按本地任务编号继续查询；如果 adapter 未收到请求，会返回任务不存在。",
            "任务编号：" + clientJobId,
            "最近错误：" + message
          ].join("\n"));
          pollExcelAnalysisJob(clientJobId, stopWaiting);
        });
    }, 0);
  }

  function fallbackCopy(text) {
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      setStatus("结果已复制。");
    } catch (error) {
      setStatus("复制失败，请手动选择结果文本。");
    }
    document.body.removeChild(textarea);
  }

  function copyResult() {
    var text = state.copyText || byId("result-output").textContent || "";
    if (!text.trim()) {
      setStatus("暂无可复制的结果。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("结果已复制。");
      }).catch(function () {
        fallbackCopy(text);
      });
      return;
    }
    fallbackCopy(text);
  }

  function setProviderLine(providerName, configured) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "模型接口",
      "enterprise-dify-workflow": "模型工作流",
      mock: "模拟接口"
    };
    var detail = providerText[providerName] || providerName || "未检测";
    if (typeof configured === "boolean") {
      detail += configured ? " / 已配置" : " / 未配置";
    }
    byId("provider-line").textContent = "接口：" + detail;
    byId("settings-provider-line").textContent = "接口：" + detail;
  }

  function setProviderBaseUrl(baseUrl) {
    state.providerBaseUrl = baseUrl || "";
    byId("provider-summary-url").textContent = state.providerBaseUrl || "未配置大模型 API URL";
    byId("provider-base-url").value = state.providerBaseUrl;
  }

  function applyProviderConfig(configData) {
    var config = configData || {};
    setProviderBaseUrl(config.providerBaseUrl || "");
    state.taskApiKeys = config.taskApiKeys || {};
    renderWorkflowProfileManager();
    renderWorkflowProfileStrip();
  }

  function emptyWorkflowProfileData() {
    return {
      taskType: EXCEL_WORKFLOW_TASK_TYPE,
      activeProfileId: "",
      profileCount: 0,
      profiles: []
    };
  }

  function normalizeWorkflowProfileData(data) {
    if (helpers.normalizeWorkflowProfileData) {
      return helpers.normalizeWorkflowProfileData(data, EXCEL_WORKFLOW_TASK_TYPE);
    }
    return data || emptyWorkflowProfileData();
  }

  function getWorkflowProfileData() {
    return state.workflowProfiles || emptyWorkflowProfileData();
  }

  function getActiveWorkflowProfileName(data) {
    if (helpers.getActiveWorkflowProfileName) {
      return helpers.getActiveWorkflowProfileName(data);
    }
    return "尚未配置";
  }

  function loadWorkflowProfiles() {
    var requestSequence = ++state.workflowProfileLoadSequence;
    return request("/provider/workflow-profiles?taskType=" + encodeURIComponent(EXCEL_WORKFLOW_TASK_TYPE))
      .then(function (body) {
        if (requestSequence !== state.workflowProfileLoadSequence) {
          return null;
        }
        state.workflowProfiles = normalizeWorkflowProfileData(body.data || {});
        state.workflowProfileSelection = state.workflowProfiles.activeProfileId || "";
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        return state.workflowProfiles;
      })
      .catch(function (error) {
        if (requestSequence !== state.workflowProfileLoadSequence) {
          return null;
        }
        state.workflowProfiles = emptyWorkflowProfileData();
        state.workflowProfiles.loadError = describeFetchError(error);
        state.workflowProfileSelection = "";
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        return null;
      });
  }

  function renderWorkflowProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var select = byId("workflow-profile-select");
    var feedback = byId("workflow-switch-feedback");
    var data = getWorkflowProfileData();
    var selectedId = state.workflowProfileSelection || data.activeProfileId || "";
    if (!strip || !select || !feedback) {
      return;
    }
    strip.hidden = state.currentMode !== "excelAnalysis";
    select.innerHTML = "";
    if (!data.profiles.length) {
      var emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = data.loadError ? "档案读取失败" : "尚未配置工作流";
      select.appendChild(emptyOption);
    } else {
      data.profiles.forEach(function (profile) {
        var option = document.createElement("option");
        var optionState = helpers.workflowProfileOptionState
          ? helpers.workflowProfileOptionState(profile, data.activeProfileId)
          : {
            id: profile.id,
            label: (profile.id === data.activeProfileId ? "✓ " : "") + profile.name +
              (profile.keyConfigured ? "" : "（Key 未配置）"),
            disabled: !profile.keyConfigured
          };
        option.value = optionState.id;
        option.textContent = optionState.label;
        option.disabled = optionState.disabled;
        option.selected = optionState.id === selectedId;
        select.appendChild(option);
      });
    }
    select.disabled = state.busy || state.workflowProfileMutationBusy || !data.profiles.length;
    feedback.textContent = state.workflowProfileMutationBusy
      ? "正在切换..."
      : "当前：" + getActiveWorkflowProfileName(data);
  }

  function escaped(value) {
    return helpers.escapeHtml ? helpers.escapeHtml(value) : String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderWorkflowProfileManager() {
    var manager = byId("workflow-profile-manager");
    var data = getWorkflowProfileData();
    var rows = [];
    var summary = byId("workflow-manager-summary");
    if (!manager) {
      return;
    }
    summary.textContent = "当前：" + getActiveWorkflowProfileName(data) + "，共 " + data.profileCount + " 个";
    if (data.loadError) {
      rows.push('<div class="workflow-empty-state"><p>无法读取工作流配置：' + escaped(data.loadError) +
        '</p><button type="button" class="ghost-action" data-workflow-action="retry">重新读取</button></div>');
    } else if (!data.profiles.length) {
      rows.push('<div class="workflow-empty-state"><p>尚未配置工作流。</p></div>');
    }
    rows.push('<div class="workflow-profile-list">');
    data.profiles.forEach(function (profile) {
      var id = escaped(profile.id);
      var isActive = profile.id === data.activeProfileId;
      var canDelete = helpers.canDeleteWorkflowProfile
        ? helpers.canDeleteWorkflowProfile(profile, data.activeProfileId)
        : !isActive;
      rows.push('<div class="workflow-profile-list-row" data-profile-id="' + id + '">');
      rows.push('<div class="workflow-profile-copy"><div class="workflow-profile-title"><strong>' +
        escaped(profile.name) + '</strong><span class="provider-badge">' +
        (isActive ? "当前" : (profile.keyConfigured ? "可用" : "Key 未配置")) + '</span></div>');
      rows.push('<p class="workflow-profile-note" title="' + escaped(profile.note || "无备注") + '">' +
        escaped(profile.note || "无备注") + '</p></div>');
      rows.push('<div class="workflow-profile-actions">');
      if (!isActive) {
        rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="activate" data-profile-id="' + id + '"' +
          (profile.keyConfigured ? "" : " disabled") + '>设为当前</button>');
      }
      rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="edit" data-profile-id="' + id + '">编辑</button>');
      rows.push('<button type="button" class="ghost-action mini-button danger-action" data-workflow-action="delete" data-profile-id="' + id + '"' +
        (canDelete ? "" : ' disabled title="当前工作流不能删除"') + '>删除</button>');
      rows.push('</div></div>');
    });
    rows.push('</div>');
    manager.innerHTML = rows.join("");
    byId("btn-new-workflow-profile").disabled =
      state.workflowProfileMutationBusy || Boolean(data.loadError);
  }

  function setWorkflowMutationBusy(isBusy) {
    state.workflowProfileMutationBusy = Boolean(isBusy);
    byId("btn-save-workflow-editor").disabled = state.workflowProfileMutationBusy;
    byId("btn-cancel-workflow-editor").disabled = state.workflowProfileMutationBusy;
    byId("btn-workflow-editor-back").disabled = state.workflowProfileMutationBusy;
    byId("btn-confirm-workflow-delete").disabled = state.workflowProfileMutationBusy;
    byId("btn-cancel-workflow-delete").disabled = state.workflowProfileMutationBusy;
    byId("btn-run-primary").disabled = state.busy || state.workflowProfileMutationBusy;
    renderWorkflowProfileStrip();
    renderWorkflowProfileManager();
  }

  function finishWorkflowMutation(message) {
    return loadWorkflowProfiles().then(function () {
      setWorkflowMutationBusy(false);
      setStatus(message);
    });
  }

  function failWorkflowMutation(prefix, error) {
    setWorkflowMutationBusy(false);
    setStatus(prefix + "：" + describeFetchError(error));
  }

  function findWorkflowProfile(profileId) {
    var profiles = getWorkflowProfileData().profiles;
    var index;
    for (index = 0; index < profiles.length; index += 1) {
      if (profiles[index].id === profileId) {
        return profiles[index];
      }
    }
    return null;
  }

  function showWorkflowEditorError(field, message) {
    var fieldIds = {
      name: "workflow-editor-name",
      note: "workflow-editor-note",
      apiKey: "workflow-editor-key"
    };
    var input = fieldIds[field] ? byId(fieldIds[field]) : null;
    byId("workflow-editor-error").textContent = message || "";
    if (input && input.focus) {
      input.focus();
    }
  }

  function openWorkflowEditor(mode, profileId) {
    var data = getWorkflowProfileData();
    var profile = mode === "edit" ? findWorkflowProfile(profileId) : null;
    var activateChecked;
    if (mode === "edit" && !profile) {
      setStatus("未找到要编辑的工作流，请刷新后重试。");
      return;
    }
    activateChecked = helpers.shouldActivateNewWorkflowProfile
      ? helpers.shouldActivateNewWorkflowProfile(data.profileCount, false)
      : data.profileCount === 0;
    state.workflowEditor = {
      open: true,
      mode: mode === "edit" ? "edit" : "create",
      profileId: profile ? profile.id : "",
      dirty: false
    };
    byId("workflow-settings-home").hidden = true;
    byId("workflow-editor-view").hidden = false;
    byId("workflow-editor-title").textContent = profile ? "编辑工作流" : "新建工作流";
    byId("workflow-editor-name").value = profile ? profile.name : "";
    byId("workflow-editor-note").value = profile ? profile.note : "";
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key-label").textContent = profile ? "新 API Key（选填）" : "API Key";
    byId("workflow-editor-key-status").textContent = profile
      ? (profile.keyConfigured ? "Key 已配置；留空则保持不变。" : "Key 未配置；填写后才能切换使用。")
      : "新建工作流必须填写 API Key。";
    byId("workflow-editor-activate").checked = profile
      ? profile.id === data.activeProfileId
      : activateChecked;
    byId("workflow-editor-activate").parentNode.hidden = Boolean(profile);
    byId("workflow-editor-error").textContent = "";
  }

  function closeWorkflowEditor(force) {
    if (!force && state.workflowEditor.dirty && window.confirm &&
        !window.confirm("当前修改尚未保存，确认返回工作流列表？")) {
      return false;
    }
    state.workflowEditor = { open: false, mode: "create", profileId: "", dirty: false };
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key").type = "password";
    byId("workflow-settings-home").hidden = false;
    byId("workflow-editor-view").hidden = true;
    byId("workflow-editor-error").textContent = "";
    return true;
  }

  function finishWorkflowEditorSave(message) {
    return loadWorkflowProfiles().then(function () {
      setWorkflowMutationBusy(false);
      closeWorkflowEditor(true);
      setStatus(message);
    });
  }

  function failWorkflowEditorSave(prefix, error) {
    setWorkflowMutationBusy(false);
    showWorkflowEditorError("", prefix + "：" + describeFetchError(error));
  }

  function showPartialKeyFailure(error, prefix) {
    var message = prefix + "：" + describeFetchError(error);
    return loadWorkflowProfiles().then(function () {
      setWorkflowMutationBusy(false);
      showWorkflowEditorError("apiKey", message);
      setStatus(message);
    });
  }

  function saveWorkflowEditor() {
    var data = getWorkflowProfileData();
    var draft = {
      name: byId("workflow-editor-name").value,
      note: byId("workflow-editor-note").value,
      apiKey: byId("workflow-editor-key").value
    };
    var checked = helpers.validateWorkflowProfileDraft
      ? helpers.validateWorkflowProfileDraft(draft, state.workflowEditor.mode)
      : { ok: Boolean(draft.name.trim() && (state.workflowEditor.mode === "edit" || draft.apiKey.trim())), name: draft.name.trim(), note: draft.note.trim(), apiKey: draft.apiKey.trim() };
    var profileId = state.workflowEditor.profileId;
    var activateChecked = byId("workflow-editor-activate").checked;
    if (!checked.ok) {
      showWorkflowEditorError(checked.field, checked.message || "请检查工作流配置。");
      return;
    }
    setWorkflowMutationBusy(true);
    if (state.workflowEditor.mode === "create") {
      request("/provider/workflow-profiles", {
        taskType: EXCEL_WORKFLOW_TASK_TYPE,
        name: checked.name,
        note: checked.note,
        apiKey: checked.apiKey,
        activate: helpers.shouldActivateNewWorkflowProfile
          ? helpers.shouldActivateNewWorkflowProfile(data.profileCount, activateChecked)
          : data.profileCount === 0 || activateChecked
      }).then(function () {
        return finishWorkflowEditorSave("工作流已新建。");
      }).catch(function (error) {
        failWorkflowEditorSave("新建工作流失败", error);
      });
      return;
    }
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId), {
      name: checked.name,
      note: checked.note
    }, { method: "PATCH" }).then(function () {
      if (!checked.apiKey) {
        return finishWorkflowEditorSave("工作流名称和备注已保存，Key 保持不变。");
      }
      return request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/api-key", {
        apiKey: checked.apiKey
      }).then(function () {
        return finishWorkflowEditorSave("工作流名称、备注和 Key 已保存。");
      }).catch(function (error) {
        return showPartialKeyFailure(error, "名称和备注已保存，但 Key 更换失败，原 Key 仍然有效");
      });
    }).catch(function (error) {
      failWorkflowEditorSave("保存工作流失败", error);
    });
  }

  function activateWorkflowProfile(profileId, previousProfileId) {
    var profile = findWorkflowProfile(profileId);
    previousProfileId = previousProfileId || getWorkflowProfileData().activeProfileId || "";
    if (!profileId || profileId === previousProfileId) {
      state.workflowProfileSelection = previousProfileId;
      renderWorkflowProfileStrip();
      return;
    }
    if (!profile || !profile.keyConfigured || state.busy || state.workflowProfileMutationBusy) {
      state.workflowProfileSelection = previousProfileId;
      renderWorkflowProfileStrip();
      setStatus(!profile || !profile.keyConfigured ? "该工作流未配置 Key，不能切换。" : "当前正忙，请稍后切换工作流。");
      byId("workflow-switch-feedback").textContent = "当前：" + getActiveWorkflowProfileName(getWorkflowProfileData());
      return;
    }
    state.workflowProfileSelection = profileId;
    state.workflowProfileLoadSequence += 1;
    setWorkflowMutationBusy(true);
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/activate", {})
      .then(function () {
        return loadWorkflowProfiles();
      }).then(function () {
        state.workflowProfileSelection = getWorkflowProfileData().activeProfileId;
        setWorkflowMutationBusy(false);
        setStatus("工作流已切换，从下一次任务开始生效。");
      }).catch(function (error) {
        state.workflowProfileSelection = previousProfileId;
        setWorkflowMutationBusy(false);
        setStatus("切换工作流失败：" + describeFetchError(error));
        byId("workflow-switch-feedback").textContent = "切换失败，当前：" +
          getActiveWorkflowProfileName(getWorkflowProfileData());
      });
  }

  function showWorkflowDeleteDialog(profileId) {
    var data = getWorkflowProfileData();
    var profile = findWorkflowProfile(profileId);
    if (!profile) {
      return;
    }
    if (profile.id === data.activeProfileId) {
      setStatus("当前工作流不能删除，请先切换到其他工作流。");
      return;
    }
    state.workflowDeleteCandidate = { id: profile.id, name: profile.name };
    byId("workflow-delete-name").textContent = profile.name;
    byId("workflow-delete-dialog").hidden = false;
  }

  function hideWorkflowDeleteDialog() {
    state.workflowDeleteCandidate = null;
    byId("workflow-delete-dialog").hidden = true;
  }

  function confirmWorkflowProfileDelete() {
    var candidate = state.workflowDeleteCandidate;
    var activeProfileId = getWorkflowProfileData().activeProfileId;
    if (!candidate || state.workflowProfileMutationBusy) {
      return;
    }
    if (candidate.id === activeProfileId) {
      hideWorkflowDeleteDialog();
      setStatus("当前工作流不能删除，请先切换到其他工作流。");
      return;
    }
    setWorkflowMutationBusy(true);
    request("/provider/workflow-profiles/" + encodeURIComponent(candidate.id), null, { method: "DELETE" })
      .then(function () {
        hideWorkflowDeleteDialog();
        return finishWorkflowMutation("工作流“" + candidate.name + "”已删除。");
      }).catch(function (error) {
        hideWorkflowDeleteDialog();
        failWorkflowMutation("删除工作流失败", error);
      });
  }

  function handleWorkflowProfileAction(event) {
    var action = event.target.getAttribute("data-workflow-action");
    var profileId = event.target.getAttribute("data-profile-id") || "";
    if (!action || state.workflowProfileMutationBusy) {
      return;
    }
    if (action === "retry") {
      loadWorkflowProfiles();
    } else if (action === "activate") {
      activateWorkflowProfile(profileId, getWorkflowProfileData().activeProfileId);
    } else if (action === "edit") {
      openWorkflowEditor("edit", profileId);
    } else if (action === "delete") {
      showWorkflowDeleteDialog(profileId);
    }
  }

  function showProviderEditor() {
    byId("provider-edit-view").hidden = false;
    byId("provider-summary-card").classList.add("editing");
  }

  function hideProviderEditor() {
    byId("provider-edit-view").hidden = true;
    byId("provider-summary-card").classList.remove("editing");
  }

  function setAdapterUnavailableState(error) {
    var message = error && error.message ? error.message : "端口未监听";
    setHealthBadge("badge-warn", "待启动");
    setTrace("");
    setProviderLine("mock", false);
    setStatus("本地适配服务暂不可用。");
    setResult([
      "本地适配服务暂不可用，插件无法访问 http://127.0.0.1:18100。",
      "请确认已执行 adapter 一键启动脚本，并用健康检查确认 /health 可访问。",
      "后台返回：" + message
    ].join("\n"));
  }

  function refreshConfig() {
    setStatus("正在刷新配置...");
    return request("/health").then(function (health) {
      return Promise.all([
        Promise.resolve(health),
        readAdapterJson("/config")
      ]);
    }).then(function (results) {
      var health = results[0];
      var config = results[1];
      var healthData = health.data || {};
      setHealthBadge("badge-ok", "已连接");
      setTrace(health.traceId || "");
      setProviderLine(healthData.providerType || "未检测", healthData.providerConfigured);
      if (config.success === false) {
        applyProviderConfig({
          providerBaseUrl: state.providerBaseUrl
        });
      } else {
        applyProviderConfig(config.data || {});
      }
      updateScopeIndicator();
      return loadWorkflowProfiles().then(function () {
        setStatus("就绪");
        refreshDiagnostics();
      });
    }).catch(function (error) {
      setAdapterUnavailableState(error);
    });
  }

  function saveProviderBaseUrl() {
    var baseUrl = (byId("provider-base-url").value || "").trim();
    setStatus("正在保存大模型 API URL...");
    request("/provider/base-url", { baseUrl: baseUrl })
      .then(function (body) {
        var data = body.data || {};
        setProviderBaseUrl(typeof data.providerBaseUrl === "string" ? data.providerBaseUrl : baseUrl);
        setStatus("大模型 API URL 已保存。");
        return refreshConfig();
      })
      .catch(function (error) {
        setStatus("保存大模型 API URL 失败：" + describeFetchError(error));
      });
  }

  function yesNo(value) {
    return value ? "是" : "否";
  }

  function describeAuthSource(value) {
    return {
      env: "环境变量",
      file: "统一密钥文件",
      "task-file": "任务级密钥文件",
      "route-file": "任务级密钥文件",
      none: "未配置"
    }[value] || value || "未检测";
  }

  function firstErrorMessage(result) {
    if (!result || result.success !== false) {
      return "";
    }
    return result.errors && result.errors[0] && result.errors[0].message
      ? result.errors[0].message
      : "请求失败";
  }

  function renderProviderDiagnostics(debugResult, statusResult, routesResult, taskKeysResult) {
    var debug = (debugResult && debugResult.data) || {};
    var status = (statusResult && statusResult.data) || {};
    var routes = (routesResult && routesResult.data) || {};
    var taskKeys = (taskKeysResult && taskKeysResult.data) || {};
    var lines = ["最近一次任务诊断", ""];

    if (firstErrorMessage(debugResult)) {
      lines.push("- debug-last：" + firstErrorMessage(debugResult));
    }
    if (firstErrorMessage(statusResult)) {
      lines.push("- provider/status：" + firstErrorMessage(statusResult));
    }
    if (firstErrorMessage(routesResult)) {
      lines.push("- route-diagnostics：" + firstErrorMessage(routesResult));
    }
    if (firstErrorMessage(taskKeysResult)) {
      lines.push("- task-api-keys：" + firstErrorMessage(taskKeysResult));
    }

    lines.push("- 任务类型：" + (debug.taskType || "未记录"));
    lines.push("- traceId：" + (debug.traceId || "未记录"));
    lines.push("- adapter 状态：" + (status.configured ? "provider 已配置" : "provider 未配置"));
    lines.push("- provider 类型：" + (status.providerType || routes.providerType || "未检测"));
    lines.push("- provider 名称：" + (status.providerName || "未检测"));
    lines.push("- 统一 API URL 已配置：" + yesNo(routes.providerBaseUrlConfigured || debug.providerBaseUrlConfigured));
    lines.push("- 认证来源：" + describeAuthSource(debug.taskAuthSource || debug.authSource || status.authSource || routes.authSource));
    lines.push("- 请求路径：" + (debug.url || routes.url || "未进入模型后台请求"));
    lines.push("- fallback 原因：" + (debug.skipReason || "无"));

    if (debug.request) {
      lines.push("");
      lines.push("## 请求摘要");
      lines.push("- body 字段：" + (debug.request.bodyKeys || []).join(", "));
      lines.push("- inputs 字段：" + (debug.request.inputsKeys || []).join(", "));
      lines.push("- query 长度：" + (debug.request.queryLength || 0));
      lines.push("- query 预览：" + (debug.request.queryPreview || "空"));
      lines.push("- response_mode：" + (debug.request.responseMode || "未记录"));
    }

    if (debug.response) {
      lines.push("");
      lines.push("## 响应摘要");
      lines.push("- HTTP 状态：" + (debug.response.status || "未记录"));
      lines.push("- body 字段：" + (debug.response.bodyKeys || []).join(", "));
      lines.push("- answer 长度：" + (debug.response.answerLength || 0));
    }

    if (debug.error) {
      lines.push("");
      lines.push("## 错误摘要");
      lines.push("- 类型：" + (debug.error.type || "未记录"));
      lines.push("- 状态：" + (debug.error.status || "未记录"));
      lines.push("- 信息：" + (debug.error.message || "未记录"));
    }

    lines.push("");
    lines.push("## 任务密钥状态");
    Object.keys(taskKeys).forEach(function (taskType) {
      var item = taskKeys[taskType] || {};
      lines.push("- " + taskType + "：" + describeAuthSource(item.authSource) + "，已配置：" + yesNo(item.configured));
    });

    return lines.join("\n");
  }

  function setDiagnosticsResult(text) {
    var output = byId("last-task-diagnostics-output");
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(text);
    } else {
      output.textContent = text;
    }
    state.diagnosticsCopyText = text || "";
  }

  function refreshDiagnostics() {
    setDiagnosticsResult("正在刷新最近一次任务诊断...");
    return Promise.all([
      readAdapterJson("/provider/debug-last"),
      readAdapterJson("/provider/status"),
      readAdapterJson("/provider/route-diagnostics"),
      readAdapterJson("/provider/task-api-keys")
    ]).then(function (results) {
      setDiagnosticsResult(renderProviderDiagnostics(results[0], results[1], results[2], results[3]));
      setStatus("诊断信息已刷新。");
    });
  }

  function copyDiagnostics() {
    var text = state.diagnosticsCopyText || byId("last-task-diagnostics-output").textContent || "";
    if (!text.trim()) {
      setStatus("暂无可复制的诊断信息。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("诊断信息已复制。");
      }).catch(function () {
        fallbackCopy(text);
      });
      return;
    }
    fallbackCopy(text);
  }

  function switchView(viewName) {
    byId("home-view").classList.toggle("active", viewName === "home");
    byId("settings-view").classList.toggle("active", viewName === "settings");
  }

  function getInitialMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    var mode = match ? decodeURIComponent(match[1]) : "excelAnalysis";
    return mode === "settings" ? "settings" : "excelAnalysis";
  }

  function switchMode(mode) {
    var settingsMode = mode === "settings";
    state.currentMode = settingsMode ? "settings" : "excelAnalysis";
    document.body.setAttribute("data-task-mode", state.currentMode);
    byId("task-title").textContent = settingsMode ? "设置" : "智能分析";
    byId("btn-open-settings").classList.toggle("is-back", settingsMode);
    byId("btn-open-settings").setAttribute("title", settingsMode ? "返回智能分析" : "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回智能分析" : "打开设置");
    switchView(settingsMode ? "settings" : "home");
    renderWorkflowProfileStrip();
    renderWorkflowProfileManager();
    if (!settingsMode) {
      updateScopeIndicator();
      resumeExcelAnalysisActiveJob();
      loadWorkflowProfiles();
    }
  }

  function bindEvents() {
    byId("btn-open-settings").addEventListener("click", function () {
      if (state.currentMode === "settings" && state.workflowEditor.open && !closeWorkflowEditor(false)) {
        return;
      }
      switchMode(state.currentMode === "settings" ? "excelAnalysis" : "settings");
    });
    byId("excel-analysis-requirement").addEventListener("input", function (event) {
      state.analysisRequirement = event.target.value;
    });
    byId("btn-run-primary").addEventListener("click", runExcelAnalysisAction);
    byId("btn-copy-result").addEventListener("click", copyResult);
    byId("btn-result-preview").addEventListener("click", function () {
      setResultViewMode("preview");
    });
    byId("btn-result-plain").addEventListener("click", function () {
      setResultViewMode("plain");
    });
    byId("btn-save-provider-url").addEventListener("click", saveProviderBaseUrl);
    byId("btn-refresh").addEventListener("click", refreshConfig);
    byId("btn-edit-provider").addEventListener("click", showProviderEditor);
    byId("btn-back-provider-summary").addEventListener("click", hideProviderEditor);
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
    byId("workflow-profile-select").addEventListener("change", function (event) {
      activateWorkflowProfile(event.target.value, getWorkflowProfileData().activeProfileId);
    });
    byId("btn-new-workflow-profile").addEventListener("click", function () {
      openWorkflowEditor("create", "");
    });
    byId("workflow-profile-manager").addEventListener("click", handleWorkflowProfileAction);
    byId("btn-workflow-editor-back").addEventListener("click", function () {
      closeWorkflowEditor(false);
    });
    byId("btn-cancel-workflow-editor").addEventListener("click", function () {
      closeWorkflowEditor(false);
    });
    byId("btn-save-workflow-editor").addEventListener("click", saveWorkflowEditor);
    ["workflow-editor-name", "workflow-editor-note", "workflow-editor-key", "workflow-editor-activate"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        state.workflowEditor.dirty = true;
        byId("workflow-editor-error").textContent = "";
      });
    });
    byId("btn-cancel-workflow-delete").addEventListener("click", hideWorkflowDeleteDialog);
    byId("btn-confirm-workflow-delete").addEventListener("click", confirmWorkflowProfileDelete);
  }

  if (!isTaskpanePage()) {
    window.openTaskpane = function (mode) {
      return switchMode(mode || "excelAnalysis");
    };
    return;
  }

  bindEvents();
  byId("frontend-version-line").textContent = FRONTEND_BUILD_VERSION;
  renderWorkflowProfileManager();
  switchMode(getInitialMode());
  refreshConfig();
  startScopeWatcher();
})();
