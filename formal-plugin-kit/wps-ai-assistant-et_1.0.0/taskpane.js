(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.23.1-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var EXCEL_ANALYSIS_POLL_INTERVAL_MS = 3000;
  var EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS = 10000;
  var SETTINGS_REFRESH_REQUEST_TIMEOUT_MS = 8000;
  var EXCEL_ANALYSIS_POLL_MAX_ERRORS = 240;
  var EXCEL_ANALYSIS_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY = "ai-wps-excel-analysis-active-job-v1";
  var EXCEL_FORMULA_ACTIVE_JOB_STORAGE_KEY = "ai-wps-excel-formula-active-job-v1";
  var EXCEL_SMART_FILL_ACTIVE_JOB_STORAGE_KEY = "ai-wps-excel-smart-fill-active-job-v1";
  var EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS = 10000;
  var EXCEL_SMART_FILL_EXTRACTION_OPTIONS = {
    maxItems: 500,
    maxSourceRows: 500,
    maxSourceColumns: 50,
    maxCellTextLength: 2000,
    maxTotalTextLength: 200000
  };
  var EXCEL_ANALYSIS_PHASE_TEXT = {
    queued: "排队等待",
    preparing: "准备表格数据",
    provider_processing: "模型后台处理",
    parsing: "解析并整理分析结果",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消"
  };
  var EXCEL_EXTRACTION_OPTIONS = {
    maxRows: 120,
    maxColumns: 30,
    maxCellTextLength: 120,
    maxTotalTextLength: 20000
  };
  var EXCEL_FORMULA_EXTRACTION_OPTIONS = {
    maxRows: 30,
    maxColumns: 20,
    maxCellTextLength: 120,
    maxFormulaLength: 1000,
    maxTotalTextLength: 20000
  };
  var FORMULA_MODE_UI = {
    generate: {
      requirementLabel: "计算需求",
      placeholder: "例如：汇总金额列，并忽略空白单元格。",
      actionLabel: "生成推荐公式",
      submitStatus: "正在提交公式助手请求...",
      submitResult: "正在等待模型后台生成推荐公式。",
      waitingStatus: "模型后台正在生成推荐公式，请继续等待...",
      stillWaitingStatus: "公式助手仍在等待模型后台返回...",
      completionStatus: "推荐公式已生成。"
    },
    explain: {
      requirementLabel: "排错说明（选填）",
      placeholder: "例如：说明这条公式为何出现 #VALUE!，并给出有依据的修正建议。",
      actionLabel: "解释并排错",
      submitStatus: "正在提交公式解释排错请求...",
      submitResult: "正在等待模型后台解释并排查已有公式。",
      waitingStatus: "模型后台正在解释并排查公式，请继续等待...",
      stillWaitingStatus: "公式解释排错仍在等待模型后台返回...",
      completionStatus: "公式解释排错已完成。"
    }
  };
  var TASK_API_KEY_DEFS = [
    { taskType: "excel.analysis", label: "智能分析" },
    { taskType: "excel.formula_assistant", label: "公式助手" },
    { taskType: "excel.smart_fill", label: "智能填写" }
  ];
  var EXCEL_WORKFLOW_TASK_TYPE = "excel.analysis";
  var EXCEL_FORMULA_WORKFLOW_TASK_TYPE = "excel.formula_assistant";
  var EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE = "excel.smart_fill";
  var state = {
    currentMode: "excelAnalysis",
    lastTaskMode: "excelAnalysis",
    traceId: "",
    copyText: "",
    diagnosticsCopyText: "",
    analysisRequirement: "",
    analysisResult: null,
    formulaMode: "generate",
    formulaRequirement: "",
    formulaResult: null,
    resultViewMode: "preview",
    latestExcelPayload: null,
    providerBaseUrl: "",
    adapterHealthStatus: "unknown",
    configurationMutationsAllowed: true,
    modelTasksAllowed: true,
    writingPolicyMutationsAllowed: true,
    taskApiKeys: {},
    configRefreshRequestId: 0,
    configRefreshPromise: null,
    configRefreshActiveRequestId: 0,
    configRefreshActiveSilent: false,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    modelInterfaceDetectable: false,
    modelInterfaceConfigDetectable: false,
    settingsRefreshController: null,
    workflowHelpPinned: false,
    providerUrlEditorOpen: false,
    settingsProbeTraceId: "",
    workflowProfilesByTask: {},
    workflowProfileSelections: {},
    workflowProfileLoadSequences: {},
    workflowTaskType: EXCEL_WORKFLOW_TASK_TYPE,
    workflowProfileMutationBusy: false,
    workflowProfileActivationTimer: null,
    workflowEditor: { open: false, mode: "create", profileId: "", dirty: false },
    workflowDeleteCandidate: null,
    busy: false,
    scopeWatcher: null,
    excelAnalysisJobId: "",
    excelAnalysisPollStartedAt: 0,
    excelAnalysisPollErrorCount: 0,
    excelAnalysisResumeExpected: false,
    excelFormulaJobId: "",
    excelFormulaPollStartedAt: 0,
    excelFormulaPollErrorCount: 0,
    excelFormulaResumeExpected: false,
    smartFillTarget: null,
    smartFillSource: null,
    smartFillItems: [],
    smartFillLiveSource: null,
    smartFillWorkbookId: "",
    smartFillInstruction: "",
    smartFillResult: null,
    smartFillPreview: null,
    smartFillDraftItems: [],
    smartFillRetryItemId: "",
    smartFillRetryBaseResult: null,
    smartFillRetryBaseDraftItems: null,
    excelSmartFillJobId: "",
    excelSmartFillPollStartedAt: 0,
    excelSmartFillPollErrorCount: 0,
    excelSmartFillResumeExpected: false
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setNodeTextIfChanged(node, value) {
    var nextValue = value || "";
    if (node && node.textContent !== nextValue) {
      node.textContent = nextValue;
      return true;
    }
    return false;
  }

  function setNodeClassNameIfChanged(node, value) {
    var nextValue = value || "";
    if (node && node.className !== nextValue) {
      node.className = nextValue;
      return true;
    }
    return false;
  }

  function setNodeAttributeIfChanged(node, name, value) {
    var nextValue = value || "";
    if (node && node.getAttribute && node.getAttribute(name) === nextValue) {
      return false;
    }
    if (node && node.setAttribute) {
      node.setAttribute(name, nextValue);
      return true;
    }
    return false;
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
    setNodeTextIfChanged(byId("status-line"), message || "");
    setNodeTextIfChanged(byId("settings-status-line"), message || "");
  }

  function setSettingsStatus(message) {
    setNodeTextIfChanged(byId("settings-status-line"), message || "");
  }

  function setAnalysisBusy(isBusy) {
    state.busy = Boolean(isBusy);
    byId("btn-run-primary").disabled = state.busy || state.workflowProfileMutationBusy;
    if (state.currentMode === "excelSmartFill") {
      updateSmartFillGenerateEnabled();
    }
    setSmartFillWriteButtonState();
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-formula-mode]"),
      function (button) {
        button.disabled = state.busy || state.workflowProfileMutationBusy;
      }
    );
    renderWorkflowProfileStrip();
    syncScopeWatcher();
  }

  function setExcelAnalysisCancelVisible(visible, disabled) {
    var button = byId("btn-cancel-excel-analysis-job");
    if (button) {
      button.hidden = !visible;
      button.disabled = Boolean(disabled);
    }
  }

  function setExcelFormulaCancelVisible(visible, disabled) {
    var button = byId("btn-cancel-excel-formula-job");
    if (button) {
      button.hidden = !visible;
      button.disabled = Boolean(disabled);
    }
  }

  function setInterruptedRetryVisible(visible) {
    var button = byId("btn-resubmit-interrupted-job");
    if (button) {
      button.hidden = !visible;
    }
  }

  function setFormulaInterruptedRetryVisible(visible) {
    var button = byId("btn-resubmit-interrupted-formula-job");
    if (button) {
      button.hidden = !visible;
    }
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

  function buildExcelFormulaClientJobId() {
    return [
      "client-excel-formula",
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

  function loadExcelFormulaActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(EXCEL_FORMULA_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveExcelFormulaActiveJob(job) {
    if (!job || !job.jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(EXCEL_FORMULA_ACTIVE_JOB_STORAGE_KEY, JSON.stringify({
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

  function clearExcelFormulaActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      if (jobId) {
        active = loadExcelFormulaActiveJob();
        if (active && active.jobId && active.jobId !== jobId) {
          return;
        }
      }
      window.localStorage.removeItem(EXCEL_FORMULA_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Storage cleanup must not block result rendering.
    }
  }

  function setExcelSmartFillCancelVisible(visible, disabled) {
    var button = byId("btn-cancel-excel-smart-fill-job");
    if (button) {
      button.hidden = !visible;
      button.disabled = Boolean(disabled);
    }
  }

  function setSmartFillInterruptedRetryVisible(visible) {
    var button = byId("btn-resubmit-interrupted-smart-fill-job");
    if (button) {
      button.hidden = !visible;
    }
  }

  function buildExcelSmartFillClientJobId() {
    return [
      "client-excel-smart-fill",
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 10)
    ].join("-");
  }

  function loadExcelSmartFillActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(EXCEL_SMART_FILL_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveExcelSmartFillActiveJob(job) {
    if (!job || !job.jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(EXCEL_SMART_FILL_ACTIVE_JOB_STORAGE_KEY, JSON.stringify({
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

  function clearExcelSmartFillActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      if (jobId) {
        active = loadExcelSmartFillActiveJob();
        if (active && active.jobId && active.jobId !== jobId) {
          return;
        }
      }
      window.localStorage.removeItem(EXCEL_SMART_FILL_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Storage cleanup must not block result rendering.
    }
  }

  function setHealthBadge(mode, text) {
    var node = byId("health-indicator");
    setNodeClassNameIfChanged(node, "badge " + mode);
    setNodeTextIfChanged(node, text);
  }

  function applyAdapterHealthState(data, connected) {
    var healthState = helpers.normalizeAdapterHealth(data, connected);
    state.adapterHealthStatus = healthState.status;
    state.configurationMutationsAllowed = healthState.configurationMutationsAllowed;
    state.modelTasksAllowed = healthState.modelTasksAllowed;
    state.writingPolicyMutationsAllowed = healthState.writingPolicyMutationsAllowed;
    setHealthBadge(healthState.badgeClass, healthState.badgeLabel);
    if (typeof renderRecoveryActions === "function") {
      renderRecoveryActions(data || {}, healthState.status === "recovery");
    }
    if (healthState.status === "recovery") {
      state.modelInterfaceConfigDetectable = false;
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(false);
      setSettingsStatus(healthState.summary);
    }
    return healthState;
  }

  function renderRecoveryActions(data, visible) {
    var card = byId("recovery-actions-card");
    var subsystemLine = byId("recovery-subsystem-status");
    var backupLine = byId("recovery-backup-status");
    var subsystems = data && data.subsystems || {};
    var labels = {
      modelConfigurations: "模型配置",
      taskRoutes: "任务路由",
      writingPolicies: "写作规范"
    };
    var failures = Object.keys(labels).filter(function (name) {
      return subsystems[name] && subsystems[name].status !== "ready";
    }).map(function (name) {
      var item = subsystems[name];
      return labels[name] + "（" + (item.stage || item.errorCode || "状态异常") + "）";
    });
    var backup = data && data.backupStatus || {};
    if (!card) {
      return;
    }
    card.hidden = !visible;
    if (!visible) {
      return;
    }
    setNodeTextIfChanged(
      subsystemLine,
      failures.length ? "故障子系统：" + failures.join("、") : "核心运行数据需要恢复。"
    );
    setNodeTextIfChanged(
      backupLine,
      backup.latestValid && backup.latestValid.snapshotId
        ? "最近有效备份：" + backup.latestValid.snapshotId
        : (backup.latestVerified && backup.latestVerified.snapshotId
          ? "无有效备份；最近只读备份不可恢复：" + backup.latestVerified.snapshotId
          : "尚无有效备份")
    );
  }

  function createRecoveryBackup() {
    var button = byId("btn-recovery-backup");
    button.disabled = true;
    setSettingsStatus("正在创建只读整体备份...");
    return request("/recovery/backups", {}).then(function (response) {
      var data = response.data || {};
      renderRecoveryActions({
        status: "recovery",
        subsystems: {},
        backupStatus: data.backupStatus || {}
      }, true);
      setSettingsStatus("只读备份已创建：" + (data.snapshotId || "已完成"));
    }).catch(function (error) {
      setSettingsStatus(error && error.message || "只读备份创建失败，请重试。");
    }).then(function () {
      button.removeAttribute("disabled");
    });
  }

  function exportRecoveryDiagnostics() {
    setSettingsStatus("正在生成脱敏诊断...");
    return request("/recovery/diagnostics", null).then(function (response) {
      var text = JSON.stringify(response.data || {}, null, 2);
      var blob = new Blob([text], { type: "application/json;charset=utf-8" });
      var objectUrl = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = objectUrl;
      link.download = "ai-wps-recovery-diagnostics.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
      setSettingsStatus("脱敏诊断已导出。");
    }).catch(function (error) {
      setSettingsStatus(error && error.message || "脱敏诊断导出失败，请重试。");
    });
  }

  function setScopeLine(label) {
    var text = label || "未检测";
    setNodeTextIfChanged(byId("scope-line"), text);
    setNodeTextIfChanged(byId("settings-scope-line"), text);
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
    var normalizedMethod = String(options.method || "GET").toUpperCase();
    var mutating = ["POST", "PUT", "PATCH", "DELETE"].indexOf(normalizedMethod) >= 0;
    var blockedCode = "";
    if (mutating && path.indexOf("/provider/") === 0 && !state.configurationMutationsAllowed) {
      blockedCode = "ADAPTER_RECOVERY_MODE";
    } else if (
      normalizedMethod === "POST" &&
      ["/word/", "/excel/", "/ppt/"].some(function (prefix) {
        return path.indexOf(prefix) === 0;
      }) &&
      !state.modelTasksAllowed
    ) {
      blockedCode = "ADAPTER_RECOVERY_MODE";
    }
    if (blockedCode) {
      var blockedError = new Error(
        "Adapter 当前处于恢复模式，配置变更和模型任务已被安全阻止。"
      );
      blockedError.adapterCode = blockedCode;
      return Promise.reject(blockedError);
    }
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

  function describeExcelFormulaPollError(error) {
    var message = describeFetchError(error);
    if (error && error.name === "AbortError") {
      return "状态查询请求超过 10 秒未返回，将继续自动刷新。";
    }
    if (error && error.adapterCode === "PROVIDER_TIMEOUT") {
      return "模型后台公式生成仍未按时返回，adapter 可能仍在等待或已返回超时诊断。";
    }
    if (message.indexOf("插件无法访问 http://127.0.0.1:18100") === 0) {
      return "状态查询暂时未连上本地 adapter；这不代表模型后台任务失败，将继续自动刷新。";
    }
    return message;
  }

  function readAdapterJson(path, requestOptions) {
    return request(path, null, requestOptions).catch(function (error) {
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
    var explicitSelectionMode = state.currentMode === "excelFormulaAssistant" || state.currentMode === "excelSmartFill";
    var range = explicitSelectionMode
      ? selection
      : (selection || getUsedRange(sheet));
    var rows = range && (resolveValue(safeRead(range, "Rows"), range) || resolveValue(safeRead(range, "rows"), range));
    var columns = range && (resolveValue(safeRead(range, "Columns"), range) || resolveValue(safeRead(range, "columns"), range));
    var rowCount = getCollectionCount(rows);
    var columnCount = getCollectionCount(columns);
    if (!range || !rowCount || !columnCount) {
      return explicitSelectionMode
        ? (state.currentMode === "excelSmartFill" ? "未检测到当前选区" : "未检测到明确选区")
        : "未检测到可分析范围";
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
    var scopeStrip = byId("scope-strip");
    if (state.currentMode === "excelSmartFill") {
      if (scopeStrip) {
        scopeStrip.hidden = true;
      }
      refreshExcelSmartFillSourceSelection();
      return;
    }
    if (scopeStrip) {
      scopeStrip.hidden = false;
    }
    try {
      setScopeLine(summarizeExcelRange());
    } catch (error) {
      setScopeLine(state.currentMode === "excelFormulaAssistant" ? "未检测到明确选区" : "未检测到可分析范围");
    }
  }

  function getExcelSelectionEventSources() {
    return [
      window.wps && window.wps.ApiEvent,
      window.et && window.et.ApiEvent,
      window.Application && window.Application.ApiEvent
    ];
  }

  function isScopeWatcherEligible() {
    var homeView = byId("home-view");
    return Boolean(
      homeView &&
      homeView.classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      !state.busy
    );
  }

  function syncScopeWatcher() {
    if (!state.scopeWatcher) {
      return;
    }
    if (isScopeWatcherEligible()) {
      state.scopeWatcher.start();
    } else if (state.scopeWatcher.isRunning()) {
      state.scopeWatcher.stop();
    }
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

  function extractExcelFormulaRange() {
    var app = getEtApplication();
    var workbook = getActiveWorkbook(app);
    var sheet = getActiveSheet(app);
    var range = getSelectionRange(app);
    var selection;

    if (!helpers.extractExcelFormulaSelection) {
      throw new Error("公式助手选区读取组件不可用，请重新打开任务窗格。");
    }
    selection = helpers.extractExcelFormulaSelection(range, {
      sheetName: safeText(safeRead(sheet, "Name") || safeRead(sheet, "name"), "Sheet1") || "Sheet1",
      maxRows: EXCEL_FORMULA_EXTRACTION_OPTIONS.maxRows,
      maxColumns: EXCEL_FORMULA_EXTRACTION_OPTIONS.maxColumns,
      maxCellTextLength: EXCEL_FORMULA_EXTRACTION_OPTIONS.maxCellTextLength,
      maxFormulaLength: EXCEL_FORMULA_EXTRACTION_OPTIONS.maxFormulaLength,
      maxTotalTextLength: EXCEL_FORMULA_EXTRACTION_OPTIONS.maxTotalTextLength
    });
    return {
      workbookId: safeText(safeRead(workbook, "Name") || safeRead(workbook, "name"), "active-workbook") || "active-workbook",
      scene: "excel",
      selection: selection,
      options: {
        mode: state.formulaMode,
        requirement: state.formulaRequirement
      }
    };
  }

  function extractExcelSmartFillSelection(role) {
    var app = getEtApplication();
    var workbook = getActiveWorkbook(app);
    var sheet = getActiveSheet(app);
    var range = getSelectionRange(app);
    var workbookId = readSmartFillWorkbookId(workbook);
    var sheetName = readSmartFillSheetName(sheet);
    if (!workbookId) {
      throw new Error("无法安全读取当前工作簿标识，请重新打开任务窗格后重试。");
    }
    if (!sheetName) {
      throw new Error("无法安全读取当前工作表标识，请重新打开任务窗格后重试。");
    }
    var options = {
      workbookId: workbookId,
      targetSheetName: sheetName,
      sourceSheetName: sheetName,
      maxItems: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxItems,
      maxSourceRows: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceRows,
      maxSourceColumns: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceColumns,
      maxCellTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxCellTextLength,
      maxTotalTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxTotalTextLength
    };
    if (!helpers.extractExcelSmartFillPayload) {
      throw new Error("智能填写选区读取组件不可用，请重新打开任务窗格。");
    }
    if (role === "target") {
      options.targetOnly = true;
      return helpers.extractExcelSmartFillPayload(range, null, options);
    }
    options.sourceOnly = true;
    return helpers.extractExcelSmartFillPayload(null, range, options);
  }

  function getSmartFillSheetCell(sheet, row, column) {
    var cells = resolveValue(safeRead(sheet, "Cells"), sheet) || resolveValue(safeRead(sheet, "cells"), sheet);
    var item = cells && (safeRead(cells, "Item") || safeRead(cells, "item"));
    var cell;
    if (typeof item === "function") {
      cell = safeCall(item, cells, [row, column]);
      if (cell) {
        return cell;
      }
    }
    if (typeof cells === "function") {
      cell = safeCall(cells, sheet, [row, column]);
      if (cell) {
        return cell;
      }
    }
    return null;
  }

  function readSmartFillPropertyState(owner, keys, preserveObject) {
    var index;
    var rawValue;
    var value;
    if (!owner) {
      return { known: true, present: false, value: undefined };
    }
    for (index = 0; index < keys.length; index += 1) {
      try {
        rawValue = owner[keys[index]];
        if (typeof rawValue === "function") {
          rawValue = rawValue.call(owner);
        }
      } catch (error) {
        return { known: false, present: true, value: undefined };
      }
      if (typeof rawValue === "undefined" || rawValue === null) {
        continue;
      }
      if (preserveObject) {
        return { known: true, present: true, value: rawValue };
      }
      value = resolveScalarValue(rawValue);
      if (typeof value === "undefined" || value === null) {
        return { known: false, present: true, value: undefined };
      }
      return { known: true, present: true, value: value };
    }
    return { known: true, present: false, value: undefined };
  }

  function readSmartFillObjectState(owner, keys) {
    return readSmartFillPropertyState(owner, keys, true);
  }

  function readSmartFillBooleanState(owner, keys) {
    var state = readSmartFillPropertyState(owner, keys, false);
    var value;
    if (!state.known || !state.present) {
      return { known: state.known, present: state.present, value: null };
    }
    value = state.value;
    if (typeof value === "boolean") {
      return { known: true, present: true, value: value };
    }
    if (typeof value === "number" && isFinite(value)) {
      return { known: true, present: true, value: value !== 0 };
    }
    if (typeof value === "string") {
      if (/^(true|yes|1|是)$/i.test(value.trim())) {
        return { known: true, present: true, value: true };
      }
      if (/^(false|no|0|否)$/i.test(value.trim())) {
        return { known: true, present: true, value: false };
      }
    }
    return { known: false, present: true, value: null };
  }

  function readSmartFillSheetName(sheet) {
    var state = readSmartFillPropertyState(sheet, ["Name", "name"]);
    return state.known && state.present ? safeText(state.value, "") : "";
  }

  function isSmartFillHostCellHidden(cell) {
    var direct = readSmartFillBooleanState(cell, ["Hidden", "hidden"]);
    var rowOwner = readSmartFillObjectState(cell, ["EntireRow", "entireRow"]);
    var columnOwner = readSmartFillObjectState(cell, ["EntireColumn", "entireColumn"]);
    var rowHidden;
    var columnHidden;
    if (!direct.known || !rowOwner.known || !columnOwner.known) {
      return true;
    }
    rowHidden = readSmartFillBooleanState(rowOwner.present ? rowOwner.value : null, ["Hidden", "hidden"]);
    columnHidden = readSmartFillBooleanState(columnOwner.present ? columnOwner.value : null, ["Hidden", "hidden"]);
    return !rowHidden.known || !columnHidden.known || direct.value === true ||
      rowHidden.value === true || columnHidden.value === true;
  }

  function readSmartFillDisplayedValue(cell) {
    var formulaState;
    var hasFormula;
    var valueState;
    var displayed;
    if (!cell || isSmartFillHostCellHidden(cell)) {
      return "";
    }
    hasFormula = readSmartFillBooleanState(cell, ["HasFormula", "hasFormula"]);
    formulaState = readSmartFillPropertyState(cell, [
      "Formula", "formula", "FormulaLocal", "formulaLocal", "FormulaR1C1", "formulaR1C1"
    ]);
    if (!hasFormula.known || !formulaState.known) {
      return "";
    }
    if (hasFormula.value === true ||
        String(formulaState.value || "").trim().charAt(0) === "=") {
      return "";
    }
    valueState = readSmartFillPropertyState(cell, [
      "Text", "text"
    ]);
    if (!valueState.known) {
      return "";
    }
    displayed = valueState.present ? safeText(valueState.value) : "";
    if (Array.from(String(displayed)).length > EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxCellTextLength) {
      throw new Error("智能填写单元格文本最多 2000 个字符，不能静默截断。");
    }
    return displayed;
  }

  function makeSmartFillTextHash(value) {
    var text = String(value || "");
    var hash = 2166136261;
    var index;
    for (index = 0; index < text.length; index += 1) {
      hash = Math.imul(hash ^ text.charCodeAt(index), 16777619) >>> 0;
    }
    return ("00000000" + hash.toString(16)).slice(-8);
  }

  function makeSmartFillSourceSnapshotHash(source) {
    return makeSmartFillTextHash(JSON.stringify({
      sheetName: source && source.sheetName || "",
      address: source && source.address || "",
      headers: source && source.headers || [],
      rows: source && source.rows || []
    }));
  }

  function buildSmartFillDefaultSource(sheet, target) {
    if (!helpers.buildExcelSmartFillDefaultSource) {
      throw new Error("智能填写默认来源组件不可用，请重新打开任务窗格。");
    }
    return helpers.buildExcelSmartFillDefaultSource(target, function (row, column) {
      var cell = getSmartFillSheetCell(sheet, row, column);
      var formulaState;
      var hasFormula;
      if (!cell) {
        return { text: "", hidden: false, hasFormula: false, formula: "", comment: "" };
      }
      hasFormula = readSmartFillBooleanState(cell, ["HasFormula", "hasFormula"]);
      formulaState = readSmartFillPropertyState(cell, [
        "Formula", "formula", "FormulaLocal", "formulaLocal", "FormulaR1C1", "formulaR1C1"
      ]);
      return helpers.describeExcelSmartFillHostCell(readSmartFillDisplayedValue(cell), {
        hidden: isSmartFillHostCellHidden(cell),
        hasFormula: hasFormula.value === true,
        formula: String(formulaState.value || "")
      });
    });
  }

  function summarizeSmartFillSource(source) {
    var rowCount = source && source.rowCount || 0;
    var sheetName = source && source.sheetName || "当前工作表";
    var address = helpers.displayExcelSmartFillSourceAddress
      ? helpers.displayExcelSmartFillSourceAddress(source.address)
      : String((source && source.address) || "").replace(/\$/g, "");
    return source
      ? "数据范围：" + sheetName + "!" + (address || "未识别地址") + " · 1 行表头 · " + rowCount + " 行数据"
      : "数据范围：未检测到当前选区";
  }

  function updateSmartFillGenerateEnabled() {
    var button = byId("btn-run-primary");
    var instruction = safeText(byId("excel-smart-fill-instruction") && byId("excel-smart-fill-instruction").value);
    var sourceOk = Boolean(state.smartFillLiveSource && state.smartFillLiveSource.ok);
    var instructionOk = Boolean(instruction.trim());
    if (!button || state.currentMode !== "excelSmartFill") {
      return;
    }
    button.disabled = state.busy || state.workflowProfileMutationBusy || !sourceOk || !instructionOk;
    if (state.busy) {
      return;
    }
    if (!sourceOk && state.smartFillLiveSource && state.smartFillLiveSource.error) {
      setNodeTextIfChanged(byId("smart-fill-validation-line"), state.smartFillLiveSource.error);
    } else if (!instructionOk) {
      setNodeTextIfChanged(byId("smart-fill-validation-line"), "请填写需要生成什么。");
    } else {
      setNodeTextIfChanged(byId("smart-fill-validation-line"), "");
    }
  }

  function refreshExcelSmartFillSourceSelection() {
    var range;
    var inspection;
    if (state.currentMode !== "excelSmartFill") {
      return;
    }
    if (!helpers.inspectExcelSmartFillSourceSelection) {
      inspection = {
        ok: false,
        summary: "数据范围：未检测到当前选区",
        error: "智能填写来源校验组件不可用，请重新打开任务窗格。"
      };
    } else {
      try {
        range = getSelectionRange(getEtApplication());
        inspection = helpers.inspectExcelSmartFillSourceSelection(range, {
          sourceSheetName: readSmartFillSheetName(getActiveSheet(getEtApplication()))
        });
      } catch (error) {
        inspection = {
          ok: false,
          summary: "数据范围：未检测到当前选区",
          error: error && error.message ? error.message : "未读取到明确来源区域，请先选中来源数据。"
        };
      }
    }
    state.smartFillLiveSource = inspection;
    setNodeTextIfChanged(byId("smart-fill-source-summary"), inspection.summary);
    updateSmartFillGenerateEnabled();
  }

  function renderSmartFillCaptureState() {
    refreshExcelSmartFillSourceSelection();
    setSmartFillWriteButtonState();
  }

  function buildExcelSmartFillRequest(clientJobId) {
    var app = getEtApplication();
    var workbook = getActiveWorkbook(app);
    var sheet = getActiveSheet(app);
    var range = getSelectionRange(app);
    var workbookId = readSmartFillWorkbookId(workbook);
    var sheetName = readSmartFillSheetName(sheet);
    var instruction;
    var payload;
    var retryItem;
    if (!helpers.extractExcelSmartFillSourcePayload) {
      throw new Error("智能填写来源校验组件不可用，请重新打开任务窗格。");
    }
    instruction = helpers.requireExcelSmartFillInstruction
      ? helpers.requireExcelSmartFillInstruction(safeText(byId("excel-smart-fill-instruction").value))
      : safeText(byId("excel-smart-fill-instruction").value);
    if (state.smartFillRetryItemId && state.smartFillSource && state.smartFillItems) {
      retryItem = (state.smartFillItems || []).filter(function (item) {
        return item.itemId === state.smartFillRetryItemId;
      })[0];
      if (!retryItem) {
        throw new Error("未找到需要重试的智能填写项。");
      }
      if (!state.smartFillWorkbookId) {
        throw new Error("当前工作簿标识不可用，请重新选择来源范围。");
      }
      if (!helpers.sliceExcelSmartFillSourceForRetry) {
        throw new Error("智能填写来源校验组件不可用，请重新打开任务窗格。");
      }
      return {
        workbookId: state.smartFillWorkbookId,
        scene: "excel",
        clientJobId: clientJobId || "",
        source: helpers.sliceExcelSmartFillSourceForRetry(state.smartFillSource, retryItem),
        items: [retryItem],
        userInstruction: instruction
      };
    }
    if (!workbookId) {
      throw new Error("当前工作簿标识不可用，请重新选择来源范围。");
    }
    payload = helpers.extractExcelSmartFillSourcePayload(range, {
      workbookId: workbookId,
      sourceSheetName: sheetName,
      maxItems: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxItems,
      maxSourceRows: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceRows,
      maxSourceColumns: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceColumns,
      maxCellTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxCellTextLength,
      maxTotalTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxTotalTextLength
    });
    state.smartFillSource = payload.source;
    state.smartFillItems = payload.items;
    state.smartFillWorkbookId = workbookId;
    return {
      workbookId: workbookId,
      scene: "excel",
      clientJobId: clientJobId || "",
      source: JSON.parse(JSON.stringify(payload.source)),
      items: JSON.parse(JSON.stringify(payload.items)),
      userInstruction: instruction
    };
  }

  function summarizeExcelFormulaPayload(payload) {
    var selection = (payload && payload.selection) || {};
    var parts = [
      "明确选区",
      selection.sheetName || "当前工作表",
      selection.address || "未识别地址",
      (selection.rowCount || 0) + " 行",
      (selection.columnCount || 0) + " 列"
    ];
    if (selection.truncated) {
      parts.push("已截断为 30 行 × 20 列以内上下文");
    }
    return parts.join(" / ");
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
    if (helpers.buildExcelAnalysisMarkdown) {
      return helpers.buildExcelAnalysisMarkdown(data);
    }
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

  function setExcelResultViewSwitchForMode(mode) {
    var node = byId("result-view-switch");
    if (!node) {
      return;
    }
    if (helpers.shouldShowExcelResultViewSwitch) {
      node.hidden = !helpers.shouldShowExcelResultViewSwitch(mode);
      return;
    }
    node.hidden = mode !== "excelAnalysis";
  }

  function renderExcelAnalysisResult(data) {
    state.analysisResult = data || {};
    setExcelResultViewSwitchForMode("excelAnalysis");
    setResultViewMode("preview");
  }

  function buildExcelFormulaMarkdown(data) {
    var mode = (data && data.mode) || state.formulaMode;
    var components = normalizeReportList(data && data.components);
    var referenceRanges = normalizeReportList(data && data.referenceRanges);
    var issues = normalizeReportList(data && data.issues);
    var assumptions = normalizeReportList(data && data.assumptions);
    var compatibilityNotes = normalizeReportList(data && data.compatibilityNotes);
    var localCheck = (data && data.localCheck) || {};
    var localRisks = normalizeReportList((localCheck.risks || []).map(function (risk) {
      var message = String((risk && risk.message) || "发现基础风险。");
      var evidence = String((risk && risk.evidence) || "");
      return evidence ? message + "（依据：" + evidence + "）" : message;
    }));
    var lines;
    if (data && data.parseDiagnostic) {
      return [
        "## 原始最终结果",
        data.rawFinalResult || "模型后台未返回可展示的最终结果。",
        "",
        "## 中文诊断",
        data.parseDiagnostic,
        "",
        "> 原始最终结果仅供复制和人工核对，未通过结构化公式检查。公式助手不会修改工作簿。"
      ].join("\n");
    }
    lines = [];
    if (mode === "explain") {
      lines.push(
        "## 原公式",
        (data && data.originalFormula) ? "```\n" + data.originalFormula + "\n```" : "未读取到原公式。",
        "",
        "## 组件说明",
        components.length ? components.map(function (item) { return "- " + item; }).join("\n") : "- 未返回组件说明。",
        "",
        "## 引用范围",
        referenceRanges.length ? referenceRanges.map(function (item) { return "- " + item; }).join("\n") : "- 未识别引用范围。",
        "",
        "## 发现问题",
        issues.length ? issues.map(function (item) { return "- " + item; }).join("\n") : "- 模型未指出额外问题；仍需人工核对业务逻辑。",
        ""
      );
    }
    lines = lines.concat([
      mode === "explain" ? "## 修正或保留的主公式" : "## 主推荐公式",
      (data && data.primaryFormula) ? "```\n" + data.primaryFormula + "\n```" : "未返回可复制的主公式。",
      "",
      "## 建议位置",
      (data && data.suggestedTarget) || "请根据当前工作表结构人工确认。",
      "",
      "## 逻辑解释",
      (data && data.explanation) || "未返回公式逻辑解释。",
      "",
      "## 本地基础检查",
      localRisks.length
        ? localRisks.map(function (item) { return "- " + item; }).join("\n")
        : (localCheck.summary || "未执行基础检查。"),
      "",
      "## 引用假设",
      assumptions.length ? assumptions.map(function (item) { return "- " + item; }).join("\n") : "- 未声明额外假设。",
      "",
      "## 兼容提示",
      compatibilityNotes.length ? compatibilityNotes.map(function (item) { return "- " + item; }).join("\n") : "- 未返回额外兼容提示。",
      "",
      "> 本地检查只覆盖基础语法、引用和兼容风险，不证明公式或计算结果正确；公式助手不会修改工作簿。"
    ]);
    return lines.join("\n");
  }

  function renderExcelFormulaResult(data) {
    var result = data || {};
    var markdown = buildExcelFormulaMarkdown(result);
    var alternative = String(result.alternativeFormula || "").trim();
    var alternativePanel = byId("excel-formula-alternative");
    var hasCopyText = Boolean(String(result.copyText || result.primaryFormula || "").trim());
    state.formulaResult = result;
    setExcelResultViewSwitchForMode("excelFormulaAssistant");
    byId("btn-copy-formula").hidden = !hasCopyText;
    byId("btn-copy-formula").textContent = result.parseDiagnostic ? "复制原始结果" : "复制公式";
    byId("btn-copy-formula").setAttribute("title", result.parseDiagnostic ? "复制原始最终结果" : "复制主公式");
    byId("btn-copy-formula").setAttribute("aria-label", result.parseDiagnostic ? "复制原始最终结果" : "复制主公式");
    alternativePanel.hidden = !alternative || alternative === String(result.primaryFormula || "").trim();
    alternativePanel.open = false;
    byId("excel-formula-alternative-code").textContent = alternativePanel.hidden ? "" : alternative;
    setResult(markdown, result.parseDiagnostic ? (result.copyText || "") : markdown);
  }

  function getSmartFillTargetSheet(sheetName) {
    var app = getEtApplication();
    var activeSheet = getActiveSheet(app);
    var activeName = safeText(safeRead(activeSheet, "Name") || safeRead(activeSheet, "name"), "");
    var workbook;
    var sheets;
    var item;
    if (!sheetName) {
      return null;
    }
    if (activeName && sheetName === activeName) {
      return activeSheet;
    }
    workbook = getActiveWorkbook(app);
    sheets = resolveValue(safeRead(workbook, "Worksheets"), workbook) ||
      resolveValue(safeRead(workbook, "worksheets"), workbook);
    item = sheets && (safeRead(sheets, "Item") || safeRead(sheets, "item"));
    if (typeof item === "function") {
      return safeCall(item, sheets, [sheetName]) || null;
    }
    return null;
  }

  function getSmartFillTargetCell(item) {
    var target = state.smartFillTarget || {};
    var sheet = getSmartFillTargetSheet(target.sheetName);
    var address = item && item.address;
    var rangeFactory;
    var cell;
    if (!sheet || !address) {
      return null;
    }
    rangeFactory = safeRead(sheet, "Range") || safeRead(sheet, "range") ||
      safeRead(sheet, "getRange") || safeRead(sheet, "GetRange");
    if (typeof rangeFactory === "function") {
      cell = safeCall(rangeFactory, sheet, [address]);
      if (cell) {
        return cell;
      }
    }
    return null;
  }

  function smartFillResultAddress(itemId) {
    var items = state.smartFillItems || [];
    var item = items.filter(function (candidate) {
      return candidate.itemId === itemId;
    })[0];
    return item ? (item.sourceRowLabel || item.itemId) : itemId;
  }

  function buildExcelSmartFillMarkdown(data) {
    var result = data || {};
    var items = Array.isArray(result.items) ? result.items : [];
    var completedCount = items.filter(function (item) { return item.status === "completed"; }).length;
    var lines = [
      "## 智能填写预览",
      "已生成 " + completedCount + " 个预览结果；本版本按来源行展示，不绑定写入地址。",
      ""
    ];
    if (!items.length) {
      lines.push("未返回可展示的目标结果。");
      return lines.join("\n");
    }
    items.forEach(function (item) {
      var address = smartFillResultAddress(item.itemId);
      var value = item.status === "completed"
        ? String(item.value)
        : (item.status === "unprocessed" ? "未处理，未写入" : "信息不足，未写入");
      lines.push(
        "- " + address + "：" + value +
        (item.status === "completed" ? "" : "（" + item.status + "）")
      );
    });
    lines.push("", "> 预览不会自动修改工作簿。本版本只生成来源先行预览，写入位置在后续步骤选择。");
    return lines.join("\n");
  }

  function smartFillResultById(data, itemId) {
    var items = data && Array.isArray(data.items) ? data.items : [];
    return items.filter(function (item) {
      return item && item.itemId === itemId;
    })[0] || null;
  }

  function smartFillDraftById(itemId) {
    return (state.smartFillDraftItems || []).filter(function (item) {
      return item && item.itemId === itemId;
    })[0] || null;
  }

  function escapeSmartFillHtml(value) {
    return String(value === null || typeof value === "undefined" ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function isSmartFillDraftWriteable(draft) {
    var value;
    if (!draft || !draft.selected) {
      return false;
    }
    value = String(draft.value === null || typeof draft.value === "undefined" ? "" : draft.value);
    if (!value.trim()) {
      return false;
    }
    if (draft.valueType === "number") {
      return isFinite(Number(value));
    }
    return draft.valueType === "text";
  }

  function buildSmartFillPreviewEditor(data) {
    var items = data && Array.isArray(data.items) ? data.items : [];
    var html = [
      '<div class="smart-fill-preview-head">',
      '<strong>智能填写预览</strong>',
      '<span class="field-hint">可编辑、取消勾选或逐项重试；未勾选项不会写入。</span>',
      "</div>"
    ];
    if (!items.length) {
      html.push('<p class="field-hint">未返回可展示的目标结果。</p>');
      return html.join("");
    }
    html.push('<div class="smart-fill-result-list">');
    items.forEach(function (item) {
      var target = (state.smartFillTarget && state.smartFillTarget.items || []).filter(function (candidate) {
        return candidate.itemId === item.itemId;
      })[0] || {};
      var draft = smartFillDraftById(item.itemId) || {};
      var completed = item.status === "completed";
      var isUnprocessed = item.status === "unprocessed";
      var value = typeof draft.value === "undefined"
        ? (completed ? item.value : "")
        : draft.value;
      var inputType = (draft.valueType || item.valueType) === "number" ? "number" : "text";
      var checked = draft.selected !== false && !isUnprocessed;
      var statusLabel = completed ? "可写入" : (isUnprocessed ? "未处理" : "信息不足");
      var statusClass = completed ? "is-complete" : (isUnprocessed ? "is-unprocessed" : "is-insufficient");
      html.push(
        '<article class="smart-fill-result-item" data-smart-fill-item-id="' +
          escapeSmartFillHtml(item.itemId) + '">',
        '<div class="smart-fill-result-meta">',
        '<label class="smart-fill-result-select">',
        '<input type="checkbox" data-smart-fill-select="' + escapeSmartFillHtml(item.itemId) + '"' +
          (checked ? " checked" : "") + ' aria-label="选择 ' + escapeSmartFillHtml(item.sourceRowLabel || item.itemId) + '">',
        '<span>' + escapeSmartFillHtml(item.sourceRowLabel || item.itemId) + '</span>',
        '</label>',
        '<span class="smart-fill-result-status ' + statusClass + '">' +
          statusLabel + "</span>",
        '</div>',
        '<div class="smart-fill-result-edit">',
        '<input class="smart-fill-result-value" type="' + inputType + '" data-smart-fill-value-input="' +
          escapeSmartFillHtml(item.itemId) + '" value="' + escapeSmartFillHtml(value) + '"' +
          (inputType === "number" ? ' step="any"' : "") +
          ' aria-label="编辑 ' + escapeSmartFillHtml(item.sourceRowLabel || item.itemId) + '">',
        '<button type="button" class="ghost-action mini-button" data-smart-fill-retry="' +
          escapeSmartFillHtml(item.itemId) + '">重新生成此项</button>',
        '</div>',
        '</article>'
      );
    });
    html.push("</div>");
    return html.join("");
  }

  function setSmartFillWriteButtonState() {
    var button = byId("btn-write-smart-fill");
    var drafts = state.smartFillDraftItems || [];
    var targetItems = state.smartFillTarget && state.smartFillTarget.items || [];
    var summary = helpers.calculateExcelSmartFillDraftsSummary
      ? helpers.calculateExcelSmartFillDraftsSummary(drafts, targetItems)
      : {
          writableCount: drafts.filter(isSmartFillDraftWriteable).length,
          canWrite: drafts.filter(isSmartFillDraftWriteable).length > 0,
          summaryText: "将写入 " + drafts.filter(isSmartFillDraftWriteable).length + " 个单元格；未勾选或信息不足项不会写入。"
        };
    var writableCount = summary.writableCount;
    var writeBound = Boolean(state.smartFillTarget && state.smartFillTarget.items && state.smartFillTarget.items.length);
    if (!button) {
      return;
    }
    button.hidden = state.currentMode !== "excelSmartFill" || !state.smartFillResult || !writeBound;
    button.textContent = writableCount ? "写入内容（" + writableCount + "）" : "写入内容";
    button.disabled = !writeBound || !summary.canWrite || state.busy || state.workflowProfileMutationBusy;
    setNodeTextIfChanged(
      byId("smart-fill-write-summary"),
      !state.smartFillResult
        ? "尚无可写入的智能填写预览。"
        : (writeBound ? summary.summaryText : "本版本只生成预览，写入目标需在后续步骤选择。")
    );
  }

  function renderExcelSmartFillResult(data, preservedDrafts, focusItemId) {
    var markdown;
    var output;
    var items;
    var preservedMap = {};
    if (Array.isArray(preservedDrafts)) {
      preservedDrafts.forEach(function (draft) {
        if (draft && draft.itemId) {
          preservedMap[draft.itemId] = draft;
        }
      });
    }
    state.smartFillResult = data || {};
    items = Array.isArray(state.smartFillResult.items) ? state.smartFillResult.items : [];
    state.smartFillDraftItems = items.map(function (item) {
      var preserved = preservedMap[item.itemId];
      if (preserved) {
        return {
          itemId: item.itemId,
          status: typeof preserved.status !== "undefined" ? preserved.status : item.status,
          valueType: (preserved.valueType || item.valueType) === "number" ? "number" : "text",
          value: typeof preserved.value !== "undefined"
            ? preserved.value
            : (item.status === "completed" ? item.value : ""),
          selected: typeof preserved.selected !== "undefined"
            ? Boolean(preserved.selected)
            : item.status === "completed"
        };
      }
      return {
        itemId: item.itemId,
        status: item.status,
        valueType: item.valueType === "number" ? "number" : "text",
        value: item.status === "completed" ? item.value : "",
        selected: item.status === "completed"
      };
    });
    setExcelResultViewSwitchForMode("excelSmartFill");
    byId("btn-copy-formula").hidden = true;
    markdown = buildExcelSmartFillMarkdown(state.smartFillResult);
    setResult(markdown, markdown);
    output = byId("result-output");
    state.smartFillPreview = helpers.createExcelSmartFillPreview(state.smartFillResult);
    if (helpers.buildExcelSmartFillEditorPreview) {
      output.innerHTML = helpers.buildExcelSmartFillEditorPreview(
        state.smartFillResult,
        state.smartFillItems || [],
        state.smartFillDraftItems
      );
    } else if (helpers.buildExcelSmartFillReadonlyPreview) {
      output.innerHTML = helpers.buildExcelSmartFillReadonlyPreview(
        state.smartFillResult,
        state.smartFillItems || []
      );
    } else {
      output.innerHTML = buildSmartFillPreviewEditor(state.smartFillResult);
    }
    setSmartFillWriteButtonState();
    if (focusItemId && typeof document !== "undefined") {
      try {
        var focusInput = document.querySelector('[data-smart-fill-value-input="' + focusItemId + '"]') ||
          document.querySelector('[data-smart-fill-retry="' + focusItemId + '"]');
        if (focusInput && typeof focusInput.focus === "function") {
          focusInput.focus();
        }
      } catch (focusError) {
        // Focus restoration is best-effort.
      }
    }
  }

  function buildExcelSmartFillWriteResults() {
    var items = state.smartFillTarget && state.smartFillTarget.items || [];
    var results = state.smartFillResult && state.smartFillResult.items || [];
    var resultById = {};
    results.forEach(function (item) {
      resultById[item.itemId] = item;
    });
    return items.map(function (item) {
      var result = resultById[item.itemId];
      var draft = smartFillDraftById(item.itemId);
      var value;
      var valueType;
      if (!result) {
        throw new Error("智能填写结果缺少目标 " + (item.address || item.itemId) + "。");
      }
      if (!draft || !draft.selected) {
        return {
          itemId: item.itemId,
          status: "insufficient_information",
          valueType: result.valueType === "number" ? "number" : "text",
          value: ""
        };
      }
      value = String(draft.value === null || typeof draft.value === "undefined" ? "" : draft.value);
      if (!value.trim()) {
        if (result.status === "completed") {
          throw new Error("请为 " + (item.address || item.itemId) + " 保留填写值或取消勾选。");
        }
        return {
          itemId: item.itemId,
          status: "insufficient_information",
          valueType: draft.valueType === "number" ? "number" : "text",
          value: ""
        };
      }
      valueType = draft.valueType === "number" ? "number" : "text";
      if (valueType === "number") {
        value = Number(value);
        if (!isFinite(value)) {
          throw new Error("目标 " + (item.address || item.itemId) + " 的数字结果无效。");
        }
      }
      return {
        itemId: item.itemId,
        status: "completed",
        valueType: valueType,
        value: value
      };
    });
  }

  function getSmartFillSheetRange(sheet, address) {
    var rangeFactory;
    if (!sheet || !address) {
      return null;
    }
    rangeFactory = safeRead(sheet, "Range") || safeRead(sheet, "range") ||
      safeRead(sheet, "getRange") || safeRead(sheet, "GetRange");
    return typeof rangeFactory === "function" ? safeCall(rangeFactory, sheet, [address]) : null;
  }

  function getSmartFillCurrentSource() {
    var source = state.smartFillSource || {};
    var target = state.smartFillTarget || {};
    var sheet = getSmartFillTargetSheet(source.sheetName);
    var range;
    var payload;
    var targetCopy;
    if (!sheet) {
      return null;
    }
    if (!source.address) {
      targetCopy = JSON.parse(JSON.stringify(target));
      return buildSmartFillDefaultSource(sheet, targetCopy);
    }
    range = getSmartFillSheetRange(sheet, source.address);
    if (!range || !helpers.extractExcelSmartFillPayload) {
      return null;
    }
    payload = helpers.extractExcelSmartFillPayload(null, range, {
      sourceOnly: true,
      sourceSheetName: source.sheetName,
      maxItems: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxItems,
      maxSourceRows: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceRows,
      maxSourceColumns: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxSourceColumns,
      maxCellTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxCellTextLength,
      maxTotalTextLength: EXCEL_SMART_FILL_EXTRACTION_OPTIONS.maxTotalTextLength
    });
    if (!helpers.sanitizeExcelSmartFillSource) {
      throw new Error("智能填写来源校验组件不可用，请重新打开任务窗格。");
    }
    return helpers.sanitizeExcelSmartFillSource(payload.source, target);
  }

  function readSmartFillWorkbookId(workbook) {
    var keys = ["Name", "name"];
    var index;
    var value;
    if (!workbook) {
      return "";
    }
    for (index = 0; index < keys.length; index += 1) {
      try {
        value = workbook[keys[index]];
        if (typeof value === "function") {
          value = value.call(workbook);
        }
      } catch (error) {
        return "";
      }
      if (typeof value !== "undefined" && value !== null && safeText(value, "")) {
        return safeText(value, "");
      }
    }
    return "";
  }

  function getSmartFillActiveWorkbookId() {
    return readSmartFillWorkbookId(getActiveWorkbook(getEtApplication()));
  }

  function checkSmartFillPreflight() {
    var source;
    var sourceHash;
    if (state.smartFillWorkbookId &&
        getSmartFillActiveWorkbookId() !== state.smartFillWorkbookId) {
      return {
        ok: false,
        reason: "workbook_changed",
        message: "当前工作簿已变化，请重新捕获目标和来源区域。"
      };
    }
    if (!getSmartFillTargetSheet(state.smartFillTarget && state.smartFillTarget.sheetName)) {
      return {
        ok: false,
        reason: "sheet_unavailable",
        message: "目标工作表不可用，请重新捕获目标区域。"
      };
    }
    if (!state.smartFillSource || !state.smartFillSource.snapshotHash) {
      return { ok: true };
    }
    source = getSmartFillCurrentSource();
    if (!source) {
      return {
        ok: false,
        reason: "source_unavailable",
        message: "来源区域不可用，请重新捕获来源区域。"
      };
    }
    sourceHash = makeSmartFillSourceSnapshotHash(source);
    if (sourceHash !== state.smartFillSource.snapshotHash) {
      return {
        ok: false,
        reason: "source_changed",
        message: "来源区域内容已变化，请重新生成预览后再写入。"
      };
    }
    return { ok: true };
  }

  function writeExcelSmartFillResult() {
    var items = state.smartFillTarget && state.smartFillTarget.items || [];
    var results;
    var writeResult;
    var overwriteCount;
    var conflictReport;
    var conflictItemIds;
    var output;
    var preflight;
    var writableItemIds;
    if (state.busy || state.workflowProfileMutationBusy || !state.smartFillResult) {
      return;
    }
    if (!items.length || !state.smartFillResult.items || !state.smartFillResult.items.length) {
      setStatus("暂无可写入的智能填写预览。" );
      return;
    }
    if (!helpers.writeExcelSmartFillCells) {
      setStatus("智能填写写回组件不可用，请重新打开任务窗格。" );
      return;
    }
    try {
      preflight = checkSmartFillPreflight();
      if (!preflight.ok) {
        state.smartFillDraftItems.forEach(function (draft) {
          draft.status = "write_conflict";
          draft.selected = false;
        });
        output = byId("result-output");
        if (output && helpers.buildExcelSmartFillEditorPreview) {
          output.innerHTML = helpers.buildExcelSmartFillEditorPreview(
            state.smartFillResult,
            state.smartFillTarget && state.smartFillTarget.items || [],
            state.smartFillDraftItems
          );
        }
        setSmartFillWriteButtonState();
        setStatus("检测到写入冲突：" + preflight.message);
        return;
      }

      results = buildExcelSmartFillWriteResults();
      writableItemIds = results.filter(function (r) {
        return r.status === "completed";
      }).map(function (r) {
        return r.itemId;
      });

      if (!writableItemIds.length) {
        setStatus("未选择任何可写入的有效项。");
        return;
      }

      if (helpers.detectExcelSmartFillConflicts) {
        conflictReport = helpers.detectExcelSmartFillConflicts(items, getSmartFillTargetCell, writableItemIds);
        if (conflictReport && conflictReport.hasConflict) {
          conflictItemIds = conflictReport.conflicts.map(function (c) { return c.itemId; });
          state.smartFillDraftItems.forEach(function (draft) {
            if (conflictItemIds.indexOf(draft.itemId) >= 0) {
              draft.status = "write_conflict";
              draft.selected = false;
            }
          });
          output = byId("result-output");
          if (output && helpers.buildExcelSmartFillEditorPreview) {
            output.innerHTML = helpers.buildExcelSmartFillEditorPreview(
              state.smartFillResult,
              state.smartFillTarget && state.smartFillTarget.items || [],
              state.smartFillDraftItems
            );
          }
          setSmartFillWriteButtonState();
          setStatus("部分目标单元格已变化，变化项已标记为写入冲突；未冲突项可重新确认写入。");
          return;
        }
      }

      overwriteCount = results.filter(function (result) {
        var item = items.filter(function (candidate) {
          return candidate.itemId === result.itemId;
        })[0] || {};
        return result.status === "completed" &&
          ["text", "number", "boolean", "date"].indexOf(item.originalValueType) >= 0 &&
          String(item.originalValue || "").trim();
      }).length;
      if (overwriteCount) {
        if (typeof window.confirm !== "function") {
          throw new Error("当前环境无法完成覆盖确认，为避免误写入本次操作已停止。");
        }
        if (!window.confirm("将覆盖 " + overwriteCount + " 个已有文本或数字单元格，确认写入吗？")) {
          setStatus("已取消智能填写写回。" );
          return;
        }
      }
      writeResult = helpers.writeExcelSmartFillCells(items, results, getSmartFillTargetCell);
    } catch (error) {
      if (error && error.code === "COMPENSATION_FAILED") {
        var failureAddresses = (error.rollbackFailures || error.manualReviewAddresses || []).join("、");
        setStatus("智能填写写入异常：内部故障处理未能完全恢复，请人工核对单元格。");
        setPlainResult([
          "智能填写写入异常，内部故障处理未能完全恢复以下单元格：",
          failureAddresses || "部分单元格",
          "",
          "详细原因：" + (error.message || "写回异常")
        ].join("\n"));
      } else if (error && error.code === "COMPENSATION_SUCCEEDED") {
        setStatus("智能填写写入中断：已通过内部故障处理恢复原值。");
        setPlainResult([
          "智能填写写入中断，已通过内部故障处理恢复全部已改动单元格。",
          "工作簿内容未保留本次写入修改。",
          "",
          "详细原因：" + (error.message || "写回中断")
        ].join("\n"));
      } else {
        setStatus("智能填写未写入：" + (error && error.message ? error.message : ""));
        setPlainResult("为避免覆盖用户修改，本次写回已停止。\n" + (error && error.message ? error.message : ""));
      }
      setSmartFillWriteButtonState();
      return;
    }
    helpers.finalizeExcelSmartFillWriteSuccess(
      state.smartFillPreview || helpers.createExcelSmartFillPreview(state.smartFillResult)
    );
    state.smartFillResult = null;
    state.smartFillPreview = null;
    state.smartFillDraftItems = [];
    byId("btn-write-smart-fill").hidden = true;
    setPlainResult([
      "智能填写内容已写入工作簿。",
      "写入单元格：" + writeResult.writtenCount,
      "信息不足而跳过：" + writeResult.skippedCount,
      "未写入公式；如需再次生成，请重新捕获目标和来源区域。"
    ].join("\n"));
    setStatus("智能填写已写入 " + writeResult.writtenCount + " 个单元格。");
    setSmartFillWriteButtonState();
  }

  function handleSmartFillResultInput(event) {
    var input = event && event.target;
    var itemId = input && input.getAttribute && input.getAttribute("data-smart-fill-value-input");
    var draft = itemId && smartFillDraftById(itemId);
    if (!draft) {
      return;
    }
    draft.value = input.value;
    setSmartFillWriteButtonState();
  }

  function handleSmartFillResultChange(event) {
    var input = event && event.target;
    var itemId = input && input.getAttribute && input.getAttribute("data-smart-fill-select");
    var draft = itemId && smartFillDraftById(itemId);
    if (!draft) {
      return;
    }
    draft.selected = Boolean(input.checked);
    setSmartFillWriteButtonState();
  }

  function cloneSmartFillResult(data) {
    return data ? JSON.parse(JSON.stringify(data)) : null;
  }

  function cloneSmartFillDraftItems(items) {
    return Array.isArray(items) ? JSON.parse(JSON.stringify(items)) : [];
  }

  function restoreSmartFillRetryResult() {
    var retryItemId = state.smartFillRetryItemId;
    var base = state.smartFillRetryBaseResult;
    var baseDraftItems = state.smartFillRetryBaseDraftItems;
    state.smartFillRetryItemId = "";
    state.smartFillRetryBaseResult = null;
    state.smartFillRetryBaseDraftItems = null;
    if (base) {
      renderExcelSmartFillResult(base, baseDraftItems, retryItemId);
    }
  }
  function tryRebindSmartFillTarget(result) {
    return false;
  }

  function finalizeExcelSmartFillResult(data) {
    var retryItemId = state.smartFillRetryItemId;
    var base = state.smartFillRetryBaseResult;
    var baseDraftItems = state.smartFillRetryBaseDraftItems;
    var replacement;
    var merged;
    var nextPreservedDrafts = null;
    tryRebindSmartFillTarget(data || {});
    if (!retryItemId || !base) {
      state.smartFillRetryItemId = "";
      state.smartFillRetryBaseResult = null;
      state.smartFillRetryBaseDraftItems = null;
      renderExcelSmartFillResult(data || {});
      return;
    }
    replacement = smartFillResultById(data || {}, retryItemId);
    merged = cloneSmartFillResult(base) || {};
    if (replacement && Array.isArray(merged.items)) {
      merged.items = merged.items.map(function (item) {
        return item.itemId === retryItemId ? replacement : item;
      });
      merged.provider = data.provider || merged.provider || "";
      merged.partial = Boolean(data.partial);
      merged.stopReason = data.stopReason || "";
    }
    if (baseDraftItems) {
      nextPreservedDrafts = baseDraftItems.filter(function (draft) {
        return draft.itemId !== retryItemId;
      });
    }
    state.smartFillRetryItemId = "";
    state.smartFillRetryBaseResult = null;
    state.smartFillRetryBaseDraftItems = null;
    renderExcelSmartFillResult(merged, nextPreservedDrafts, retryItemId);
  }

  function retryExcelSmartFillItem(itemId) {
    if (!itemId || state.busy || state.workflowProfileMutationBusy || !state.smartFillResult) {
      return;
    }
    if (!smartFillResultById(state.smartFillResult, itemId)) {
      setStatus("未找到需要重试的智能填写项。" );
      return;
    }
    state.smartFillRetryItemId = itemId;
    state.smartFillRetryBaseResult = cloneSmartFillResult(state.smartFillResult);
    state.smartFillRetryBaseDraftItems = cloneSmartFillDraftItems(state.smartFillDraftItems);
    setStatus("正在重新生成 " + smartFillResultAddress(itemId) + " 的填写结果..." );
    runExcelSmartFillAction();
  }

  function handleSmartFillResultClick(event) {
    var target = event && event.target;
    var itemId = target && target.getAttribute && target.getAttribute("data-smart-fill-retry");
    if (itemId) {
      retryExcelSmartFillItem(itemId);
    }
  }

  function getFormulaModeUi(mode) {
    return FORMULA_MODE_UI[mode === "explain" ? "explain" : "generate"];
  }

  function setFormulaAssistantMode(mode, focusSelected) {
    var nextMode = mode === "explain" ? "explain" : "generate";
    var modeUi = getFormulaModeUi(nextMode);
    state.formulaMode = nextMode;
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-formula-mode]"),
      function (button) {
        var selected = button.getAttribute("data-formula-mode") === nextMode;
        button.setAttribute("aria-selected", selected ? "true" : "false");
        button.setAttribute("tabindex", selected ? "0" : "-1");
        button.classList.toggle("active", selected);
        if (selected && focusSelected) {
          button.focus();
        }
      }
    );
    byId("excel-formula-requirement-label").textContent = modeUi.requirementLabel;
    byId("excel-formula-requirement").setAttribute(
      "placeholder",
      modeUi.placeholder
    );
    if (state.currentMode === "excelFormulaAssistant") {
      byId("btn-run-primary").textContent = modeUi.actionLabel;
    }
  }

  function handleFormulaModeKeydown(event) {
    var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-formula-mode]"));
    var currentIndex = buttons.indexOf(event.target);
    var nextIndex = currentIndex;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % buttons.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = buttons.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    setFormulaAssistantMode(buttons[nextIndex].getAttribute("data-formula-mode"), true);
  }

  function startExcelFormulaWaitFeedback() {
    var timers = [];
    var modeUi = getFormulaModeUi(state.formulaMode);
    timers.push(setTimeout(function () {
      setStatus(modeUi.waitingStatus);
      setPlainResult("公式助手请求已提交，模型后台正在处理。请保持 WPS 和 adapter 打开。");
    }, 8000));
    timers.push(setTimeout(function () {
      setStatus(modeUi.stillWaitingStatus);
      setPlainResult("公式助手仍在等待模型后台返回。任务窗格会继续自动刷新，无需重复提交。");
    }, 30000));
    return function () {
      timers.forEach(clearTimeout);
    };
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
      error.adapterCode === "EXCEL_ANALYSIS_JOB_INTERRUPTED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "EXCEL_ANALYSIS_AUTH_SNAPSHOT_FAILED" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function renderExcelAnalysisJobProgress(job, jobId) {
    var phaseText = EXCEL_ANALYSIS_PHASE_TEXT[job.phase] || job.phase || "等待状态更新";
    var elapsedSeconds = Number(job.elapsedSeconds || 0);
    var phaseElapsedSeconds = Number(job.phaseElapsedSeconds || 0);
    var lines = [];
    if (job.status === "queued") {
      setStatus("智能分析正在排队，当前位置：" + (job.queuePosition || 1) + "。");
      lines.push("智能分析已进入共享任务队列。", "排队位置：" + (job.queuePosition || 1));
    } else {
      setStatus("智能分析正在处理，当前阶段：" + phaseText + "。");
      lines.push(job.runningMessage || "adapter 正在执行智能分析。", "当前阶段：" + phaseText);
    }
    lines.push(
      "总耗时：" + elapsedSeconds + " 秒",
      "本阶段耗时：" + phaseElapsedSeconds + " 秒",
      "adapter 等待预算：" + (job.providerTimeoutSeconds || 1800) + " 秒",
      "任务编号：" + jobId
    );
    setExcelAnalysisCancelVisible(job.status === "queued" && job.canCancel, false);
    setPlainResult(lines.join("\n"));
  }

  function finishCancelledExcelAnalysis(jobId, stopWaiting) {
    clearExcelAnalysisActiveJob(jobId);
    state.excelAnalysisJobId = "";
    state.excelAnalysisPollStartedAt = 0;
    state.excelAnalysisPollErrorCount = 0;
    state.excelAnalysisResumeExpected = false;
    setExcelAnalysisCancelVisible(false);
    stopWaiting();
    setStatus("智能分析任务已取消。");
    setPlainResult("排队中的智能分析任务已取消，未调用模型后台。\n任务编号：" + jobId);
  }

  function cancelQueuedExcelAnalysisJob() {
    var jobId = state.excelAnalysisJobId;
    if (!jobId) {
      return;
    }
    setExcelAnalysisCancelVisible(true, true);
    request("/excel/analysis/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (state.excelAnalysisJobId !== jobId) {
        return;
      }
      if ((body.data || {}).status === "cancelled") {
        finishCancelledExcelAnalysis(jobId, function () {
          setAnalysisBusy(false);
        });
      }
    }).catch(function (error) {
      if (state.excelAnalysisJobId === jobId) {
        setExcelAnalysisCancelVisible(true, false);
        setStatus("取消排队任务失败：" + describeExcelAnalysisPollError(error));
      }
    });
  }

  function pollExcelAnalysisJob(jobId, stopWaiting) {
    if (!jobId || state.excelAnalysisJobId !== jobId) {
      return;
    }
    request(
      "/excel/analysis/jobs/" + encodeURIComponent(jobId) +
        (state.excelAnalysisResumeExpected ? "?resume=1" : ""),
      null,
      {
      timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
      }
    )
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
          state.excelAnalysisResumeExpected = false;
          setExcelAnalysisCancelVisible(false);
          stopWaiting();
          renderExcelAnalysisResult(job.result || {});
          setStatus("智能分析报告已生成。");
          refreshDiagnostics().then(function () {
            setStatus("智能分析报告已生成。");
          });
          return;
        }
        if (job.status === "cancelled") {
          finishCancelledExcelAnalysis(jobId, stopWaiting);
          return;
        }
        if (job.status === "failed") {
          clearExcelAnalysisActiveJob(jobId);
          state.excelAnalysisJobId = "";
          state.excelAnalysisPollStartedAt = 0;
          state.excelAnalysisResumeExpected = false;
          setExcelAnalysisCancelVisible(false);
          stopWaiting();
          setStatus("智能分析失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
          setResult((job.error && job.error.message) || "后台任务执行失败。");
          return;
        }
        renderExcelAnalysisJobProgress(job, jobId);
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
        if (error && error.adapterCode === "EXCEL_ANALYSIS_JOB_INTERRUPTED") {
          clearExcelAnalysisActiveJob(jobId);
          state.excelAnalysisJobId = "";
          state.excelAnalysisPollStartedAt = 0;
          state.excelAnalysisPollErrorCount = 0;
          state.excelAnalysisResumeExpected = false;
          setExcelAnalysisCancelVisible(false);
          setInterruptedRetryVisible(true);
          stopWaiting();
          setStatus("adapter 已重启，原智能分析任务已中断，请重新提交。");
          setPlainResult("adapter 已重启，原智能分析任务无法恢复，请使用“重新提交分析”。\n任务编号：" + jobId);
          return;
        }
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
    state.excelAnalysisResumeExpected = true;
    setInterruptedRetryVisible(false);
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
    var presented;
    var plainText;
    state.resultViewMode = mode === "plain" ? "plain" : "preview";
    updateResultViewButtons();
    if (!state.analysisResult) {
      return;
    }
    if (helpers.presentExcelAnalysisResultView) {
      presented = helpers.presentExcelAnalysisResultView({
        result: state.analysisResult,
        view: state.resultViewMode
      });
      if (presented.presentation === "source") {
        setPlainResult(presented.sourceText || "模型后台未返回汇报段落。", presented.copyText);
      } else {
        setResult(presented.displayMarkdown, presented.copyText);
      }
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
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    var startedAt;
    if (state.busy || state.workflowProfileMutationBusy) {
      return;
    }
    setInterruptedRetryVisible(false);
    setExcelAnalysisCancelVisible(false);
    setAnalysisBusy(true);
    state.analysisRequirement = safeText(byId("excel-analysis-requirement").value);
    state.analysisResult = null;
    clearExcelAnalysisActiveJob();
    state.excelAnalysisJobId = "";
    state.excelAnalysisPollStartedAt = 0;
    state.excelAnalysisPollErrorCount = 0;
    state.excelAnalysisResumeExpected = false;
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
      state.excelAnalysisResumeExpected = true;
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
          renderExcelAnalysisJobProgress(job, jobId);
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

  function scheduleExcelFormulaPoll(jobId, stopWaiting, delayMs) {
    setTimeout(function () {
      pollExcelFormulaJob(jobId, stopWaiting);
    }, delayMs);
  }

  function isFatalExcelFormulaPollError(error) {
    return error && (
      error.adapterCode === "EXCEL_FORMULA_JOB_NOT_FOUND" ||
      error.adapterCode === "EXCEL_FORMULA_JOB_INTERRUPTED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "EXCEL_FORMULA_AUTH_SNAPSHOT_FAILED" ||
      error.adapterCode === "EXCEL_FORMULA_REQUIREMENT_REQUIRED" ||
      error.adapterCode === "EXCEL_FORMULA_SELECTION_REQUIRED" ||
      error.adapterCode === "EXCEL_FORMULA_TO_EXPLAIN_REQUIRED" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function getExcelFormulaCompletionStatus(result) {
    return getFormulaModeUi((result || {}).mode).completionStatus;
  }

  function renderExcelFormulaJobProgress(job, jobId) {
    var phaseText = EXCEL_ANALYSIS_PHASE_TEXT[job.phase] || job.phase || "等待状态更新";
    var lines = [];
    if (job.status === "queued") {
      setStatus("公式助手正在排队，当前位置：" + (job.queuePosition || 1) + "。");
      lines.push("公式助手已进入共享任务队列。", "排队位置：" + (job.queuePosition || 1));
    } else {
      setStatus("公式助手正在处理，当前阶段：" + phaseText + "。");
      lines.push(job.runningMessage || "adapter 正在处理公式任务。", "当前阶段：" + phaseText);
    }
    lines.push(
      "总耗时：" + Number(job.elapsedSeconds || 0) + " 秒",
      "本阶段耗时：" + Number(job.phaseElapsedSeconds || 0) + " 秒",
      "adapter 等待预算：" + (job.providerTimeoutSeconds || 1800) + " 秒",
      "任务编号：" + jobId
    );
    setExcelFormulaCancelVisible(job.status === "queued" && job.canCancel, false);
    setPlainResult(lines.join("\n"));
  }

  function finishCancelledExcelFormula(jobId, stopWaiting) {
    clearExcelFormulaActiveJob(jobId);
    state.excelFormulaJobId = "";
    state.excelFormulaPollStartedAt = 0;
    state.excelFormulaPollErrorCount = 0;
    state.excelFormulaResumeExpected = false;
    setExcelFormulaCancelVisible(false);
    stopWaiting();
    setStatus("公式助手任务已取消。");
    setPlainResult("排队中的公式助手任务已取消，未调用模型后台。\n任务编号：" + jobId);
  }

  function cancelQueuedExcelFormulaJob() {
    var jobId = state.excelFormulaJobId;
    if (!jobId) {
      return;
    }
    setExcelFormulaCancelVisible(true, true);
    request("/excel/formula-assistant/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (state.excelFormulaJobId === jobId && (body.data || {}).status === "cancelled") {
        finishCancelledExcelFormula(jobId, function () {
          setAnalysisBusy(false);
        });
      }
    }).catch(function (error) {
      if (state.excelFormulaJobId === jobId) {
        setExcelFormulaCancelVisible(true, false);
        setStatus("取消排队任务失败：" + describeExcelFormulaPollError(error));
      }
    });
  }

  function pollExcelFormulaJob(jobId, stopWaiting) {
    if (!jobId || state.excelFormulaJobId !== jobId) {
      return;
    }
    request(
      "/excel/formula-assistant/jobs/" + encodeURIComponent(jobId) +
        (state.excelFormulaResumeExpected ? "?resume=1" : ""),
      null,
      { timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS }
    ).then(function (body) {
      var job = body.data || {};
      if (state.excelFormulaJobId !== jobId) {
        return;
      }
      state.excelFormulaPollErrorCount = 0;
      setTrace(body.traceId || job.traceId || jobId);
      saveExcelFormulaActiveJob({
        jobId: jobId,
        traceId: body.traceId || job.traceId || "",
        startedAt: state.excelFormulaPollStartedAt || Date.now()
      });
      if (job.status === "completed") {
        clearExcelFormulaActiveJob(jobId);
        state.excelFormulaJobId = "";
        state.excelFormulaPollStartedAt = 0;
        state.excelFormulaResumeExpected = false;
        setExcelFormulaCancelVisible(false);
        stopWaiting();
        renderExcelFormulaResult(job.result || {});
        setStatus(getExcelFormulaCompletionStatus(job.result));
        refreshDiagnostics().then(function () {
          setStatus(getExcelFormulaCompletionStatus(job.result));
        });
        return;
      }
      if (job.status === "cancelled") {
        finishCancelledExcelFormula(jobId, stopWaiting);
        return;
      }
      if (job.status === "failed") {
        clearExcelFormulaActiveJob(jobId);
        state.excelFormulaJobId = "";
        state.excelFormulaPollStartedAt = 0;
        state.excelFormulaResumeExpected = false;
        setExcelFormulaCancelVisible(false);
        stopWaiting();
        setStatus("公式助手失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
        setResult((job.error && job.error.message) || "后台任务执行失败。");
        return;
      }
      renderExcelFormulaJobProgress(job, jobId);
      scheduleExcelFormulaPoll(jobId, stopWaiting, EXCEL_ANALYSIS_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed;
      var withinRetryBudget;
      var retryDelay;
      var message;
      if (state.excelFormulaJobId !== jobId) {
        return;
      }
      message = describeExcelFormulaPollError(error);
      state.excelFormulaPollErrorCount += 1;
      elapsed = Date.now() - (state.excelFormulaPollStartedAt || Date.now());
      if (error && error.adapterCode === "EXCEL_FORMULA_JOB_INTERRUPTED") {
        clearExcelFormulaActiveJob(jobId);
        state.excelFormulaJobId = "";
        state.excelFormulaPollStartedAt = 0;
        state.excelFormulaPollErrorCount = 0;
        state.excelFormulaResumeExpected = false;
        setExcelFormulaCancelVisible(false);
        setFormulaInterruptedRetryVisible(true);
        stopWaiting();
        setStatus("adapter 已重启，原公式助手任务已中断，请重新提交。");
        setPlainResult("adapter 已重启，原公式助手任务无法恢复，请重新提交计算需求。\n任务编号：" + jobId);
        return;
      }
      if (!isFatalExcelFormulaPollError(error)) {
        withinRetryBudget = (
          state.excelFormulaPollErrorCount <= EXCEL_ANALYSIS_POLL_MAX_ERRORS &&
          elapsed <= EXCEL_ANALYSIS_POLL_MAX_WAIT_MS
        );
        retryDelay = withinRetryBudget
          ? EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS
          : EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS;
        saveExcelFormulaActiveJob({
          jobId: jobId,
          traceId: state.traceId || "",
          startedAt: state.excelFormulaPollStartedAt || Date.now()
        });
        setStatus("公式助手状态查询暂时失败，正在继续恢复...");
        setPlainResult([
          "公式助手任务编号仍已保留，将继续自动刷新。",
          "这不代表模型后台任务失败；请保持 WPS 和 adapter 打开。",
          "任务编号：" + jobId,
          "最近错误：" + message
        ].join("\n"));
        scheduleExcelFormulaPoll(jobId, stopWaiting, retryDelay);
        return;
      }
      clearExcelFormulaActiveJob(jobId);
      state.excelFormulaJobId = "";
      state.excelFormulaPollStartedAt = 0;
      state.excelFormulaPollErrorCount = 0;
      stopWaiting();
      setStatus("公式助手状态查询持续失败，请查看最近一次任务诊断。");
      setResult(message);
    });
  }

  function resumeExcelFormulaActiveJob() {
    var active = loadExcelFormulaActiveJob();
    if (!active || !active.jobId || state.currentMode !== "excelFormulaAssistant") {
      return;
    }
    state.excelFormulaJobId = active.jobId;
    state.excelFormulaPollStartedAt = active.startedAt || Date.now();
    state.excelFormulaPollErrorCount = 0;
    state.excelFormulaResumeExpected = true;
    setFormulaInterruptedRetryVisible(false);
    setAnalysisBusy(true);
    setTrace(active.traceId || active.jobId);
    setStatus("已恢复未完成的公式助手任务，正在查询模型后台结果...");
    setPlainResult("检测到未完成的公式助手任务，将继续查询 adapter 后台状态。\n任务编号：" + active.jobId);
    pollExcelFormulaJob(active.jobId, function () {
      setAnalysisBusy(false);
    });
  }

  function runExcelFormulaAction() {
    var stopWaiting;
    var clientJobId;
    var startedAt;
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    if (state.busy || state.workflowProfileMutationBusy) {
      return;
    }
    state.formulaRequirement = safeText(byId("excel-formula-requirement").value);
    if (state.formulaMode === "generate" && !state.formulaRequirement) {
      setStatus("请填写计算需求。");
      setPlainResult("请说明需要计算的内容，再生成推荐公式。");
      return;
    }
    setFormulaInterruptedRetryVisible(false);
    setExcelFormulaCancelVisible(false);
    setAnalysisBusy(true);
    state.formulaResult = null;
    byId("btn-copy-formula").hidden = true;
    byId("excel-formula-alternative").hidden = true;
    clearExcelFormulaActiveJob();
    state.excelFormulaJobId = "";
    state.excelFormulaPollStartedAt = 0;
    state.excelFormulaPollErrorCount = 0;
    state.excelFormulaResumeExpected = false;
    byId("result-view-switch").hidden = true;
    setStatus("正在读取明确选区...");
    setPlainResult("公式助手正在读取明确选区，不会读取工作表已用范围。");

    setTimeout(function () {
      var payload;
      try {
        payload = extractExcelFormulaRange();
        byId("excel-formula-range-summary").textContent = summarizeExcelFormulaPayload(payload);
        setScopeLine(summarizeExcelFormulaPayload(payload));
      } catch (error) {
        setAnalysisBusy(false);
        setStatus("读取公式上下文失败：" + error.message);
        setPlainResult("读取公式上下文失败：" + error.message);
        return;
      }

      setStatus(getFormulaModeUi(state.formulaMode).submitStatus);
      setPlainResult(getFormulaModeUi(state.formulaMode).submitResult);
      stopWaiting = startExcelFormulaWaitFeedback();
      (function (stopFeedback) {
        stopWaiting = function () {
          stopFeedback();
          setAnalysisBusy(false);
        };
      })(stopWaiting);
      clientJobId = buildExcelFormulaClientJobId();
      startedAt = Date.now();
      payload.clientJobId = clientJobId;
      state.excelFormulaJobId = clientJobId;
      state.excelFormulaPollStartedAt = startedAt;
      state.excelFormulaResumeExpected = true;
      saveExcelFormulaActiveJob({ jobId: clientJobId, startedAt: startedAt });
      request("/excel/formula-assistant/jobs", payload, {
        timeoutMs: EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS
      }).then(function (body) {
        var job = body.data || {};
        var jobId = job.jobId || clientJobId || body.traceId;
        if (state.excelFormulaJobId !== clientJobId) {
          return;
        }
        setTrace(body.traceId || job.traceId || jobId);
        state.excelFormulaJobId = jobId;
        saveExcelFormulaActiveJob({
          jobId: jobId,
          traceId: body.traceId || job.traceId || "",
          startedAt: startedAt
        });
        if (job.status === "completed") {
          clearExcelFormulaActiveJob(jobId);
          state.excelFormulaJobId = "";
          state.excelFormulaPollStartedAt = 0;
          stopWaiting();
          renderExcelFormulaResult(job.result || {});
          setStatus(getExcelFormulaCompletionStatus(job.result));
          return;
        }
        renderExcelFormulaJobProgress(job, jobId);
        pollExcelFormulaJob(jobId, stopWaiting);
      }).catch(function (error) {
        var message = describeExcelFormulaPollError(error);
        if (state.excelFormulaJobId !== clientJobId) {
          return;
        }
        if (isFatalExcelFormulaPollError(error)) {
          clearExcelFormulaActiveJob(clientJobId);
          state.excelFormulaJobId = "";
          state.excelFormulaPollStartedAt = 0;
          stopWaiting();
          setStatus("公式助手失败：" + message);
          setResult(message);
          return;
        }
        setStatus("公式助手提交响应未确认，正在按任务编号恢复状态查询...");
        setPlainResult("任务可能已经提交，将按本地任务编号继续查询。\n任务编号：" + clientJobId + "\n最近错误：" + message);
        pollExcelFormulaJob(clientJobId, stopWaiting);
      });
    }, 0);
  }

  function describeExcelSmartFillPollError(error) {
    var message = describeFetchError(error);
    if (error && error.name === "AbortError") {
      return "状态查询请求超过 10 秒未返回，将继续自动刷新。";
    }
    if (error && error.adapterCode === "PROVIDER_TIMEOUT") {
      return "模型后台智能填写仍未按时返回，adapter 可能仍在等待或已返回超时诊断。";
    }
    if (message.indexOf("插件无法访问 http://127.0.0.1:18100") === 0) {
      return "状态查询暂时未连上本地 adapter；这不代表模型后台任务失败，将继续自动刷新。";
    }
    return message;
  }

  function startExcelSmartFillWaitFeedback() {
    var timers = [];
    timers.push(setTimeout(function () {
      setStatus("模型后台正在处理智能填写，请继续等待..." );
      setPlainResult("智能填写请求已提交，模型后台正在处理。请保持 WPS 和 adapter 打开。" );
    }, 8000));
    timers.push(setTimeout(function () {
      setStatus("智能填写仍在等待模型后台返回..." );
      setPlainResult("智能填写仍在等待模型后台返回。任务窗格会继续自动刷新，无需重复提交。" );
    }, 30000));
    return function () {
      timers.forEach(function (timer) {
        clearTimeout(timer);
      });
    };
  }

  function isFatalExcelSmartFillPollError(error) {
    return error && (
      error.adapterCode === "EXCEL_SMART_FILL_JOB_NOT_FOUND" ||
      error.adapterCode === "EXCEL_SMART_FILL_JOB_INTERRUPTED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "EXCEL_SMART_FILL_AUTH_SNAPSHOT_FAILED" ||
      error.adapterCode === "EXCEL_SMART_FILL_TARGET_UNSAFE" ||
      error.adapterCode === "EXCEL_SMART_FILL_TARGET_SHAPE_INVALID" ||
      error.adapterCode === "EXCEL_SMART_FILL_CROSS_SHEET" ||
      error.adapterCode === "EXCEL_SMART_FILL_INSTRUCTION_REQUIRED" ||
      error.adapterCode === "EXCEL_SMART_FILL_ITEMS_TOO_MANY" ||
      error.adapterCode === "EXCEL_SMART_FILL_BATCH_TOO_LARGE" ||
      error.adapterCode === "EXCEL_SMART_FILL_INSTRUCTION_TOO_LONG" ||
      error.adapterCode === "EXCEL_SMART_FILL_SOURCE_TRUNCATED" ||
      error.adapterCode === "EXCEL_SMART_FILL_SOURCE_SHAPE_INVALID" ||
      error.adapterCode === "EXCEL_SMART_FILL_CELL_TEXT_TOO_LONG" ||
      error.adapterCode === "EXCEL_SMART_FILL_TEXT_TOO_LARGE" ||
      error.adapterCode === "EXCEL_SMART_FILL_REQUEST_TOO_LARGE" ||
      error.adapterCode === "EXCEL_SMART_FILL_CONTEXT_TOO_LARGE" ||
      error.adapterCode === "EXCEL_SMART_FILL_RESULT_TOO_LARGE" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function renderExcelSmartFillJobProgress(job, jobId) {
    var phaseText = EXCEL_ANALYSIS_PHASE_TEXT[job.phase] || job.phase || "等待状态更新";
    var lines = [];
    if (job.status === "queued") {
      setStatus("智能填写正在排队，当前位置：" + (job.queuePosition || 1) + "。" );
      lines.push("智能填写已进入共享任务队列。", "排队位置：" + (job.queuePosition || 1));
    } else {
      setStatus("智能填写正在处理，当前阶段：" + phaseText + "。" );
      lines.push(job.runningMessage || "adapter 正在执行智能填写。", "当前阶段：" + phaseText);
    }
    if (job.totalBatches && job.totalBatches > 1) {
      var currentBatch = job.currentBatch || (Number(job.completedBatchCount || 0) + 1);
      lines.push("批次进度：第 " + currentBatch + " 批 / 共 " + job.totalBatches + " 批");
    }
    lines.push(
      "总耗时：" + Number(job.elapsedSeconds || 0) + " 秒",
      "本阶段耗时：" + Number(job.phaseElapsedSeconds || 0) + " 秒",
      "adapter 等待预算：" + (job.providerTimeoutSeconds || 1800) + " 秒",
      "任务编号：" + jobId
    );
    setExcelSmartFillCancelVisible((job.status === "queued" || job.status === "running") && job.canCancel, false);
    setPlainResult(lines.join("\n"));
  }

  function finishCancelledExcelSmartFill(jobId, stopWaiting, partialResult) {
    clearExcelSmartFillActiveJob(jobId);
    state.excelSmartFillJobId = "";
    state.excelSmartFillPollStartedAt = 0;
    state.excelSmartFillPollErrorCount = 0;
    state.excelSmartFillResumeExpected = false;
    setExcelSmartFillCancelVisible(false);
    stopWaiting();
    if (partialResult && Array.isArray(partialResult.items) && partialResult.items.length) {
      finalizeExcelSmartFillResult(partialResult);
      setStatus("智能填写任务已取消，已保留部分预览；未完成项不会写入。" );
      return;
    }
    setStatus("智能填写任务已取消。" );
    setPlainResult("智能填写任务已取消，未写入工作簿。\n任务编号：" + jobId);
  }

  function cancelExcelSmartFillJob() {
    var jobId = state.excelSmartFillJobId;
    if (!jobId) {
      return;
    }
    setExcelSmartFillCancelVisible(true, true);
    request("/excel/smart-fill/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (state.excelSmartFillJobId === jobId) {
        var job = (body && body.data) || {};
        if (job.status === "cancelled") {
          finishCancelledExcelSmartFill(jobId, function () {
            setAnalysisBusy(false);
          }, job.result || null);
        } else if (job.status === "running" && job.cancelRequested) {
          setStatus("智能填写正在停止，当前批次完成后将保留部分预览。");
        }
      }
    }).catch(function (error) {
      if (state.excelSmartFillJobId === jobId) {
        setExcelSmartFillCancelVisible(true, false);
        setStatus("取消智能填写任务失败：" + describeExcelSmartFillPollError(error));
      }
    });
  }

  function pollExcelSmartFillJob(jobId, stopWaiting) {
    if (!jobId || state.excelSmartFillJobId !== jobId) {
      return;
    }
    request(
      "/excel/smart-fill/jobs/" + encodeURIComponent(jobId) +
        (state.excelSmartFillResumeExpected ? "?resume=1" : ""),
      null,
      { timeoutMs: EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS }
    ).then(function (body) {
      var job = body.data || {};
      if (state.excelSmartFillJobId !== jobId) {
        return;
      }
      state.excelSmartFillPollErrorCount = 0;
      setTrace(body.traceId || job.traceId || jobId);
      saveExcelSmartFillActiveJob({
        jobId: jobId,
        traceId: body.traceId || job.traceId || "",
        startedAt: state.excelSmartFillPollStartedAt || Date.now()
      });
      if (job.status === "completed") {
        clearExcelSmartFillActiveJob(jobId);
        state.excelSmartFillJobId = "";
        state.excelSmartFillPollStartedAt = 0;
        state.excelSmartFillResumeExpected = false;
        setExcelSmartFillCancelVisible(false);
        stopWaiting();
        finalizeExcelSmartFillResult(job.result || {});
        setStatus("智能填写预览已生成，请确认后写入。" );
        refreshDiagnostics().then(function () {
          setStatus("智能填写预览已生成，请确认后写入。" );
        });
        return;
      }
      if (job.status === "cancelled") {
        finishCancelledExcelSmartFill(jobId, stopWaiting, job.result || null);
        return;
      }
      if (job.status === "failed") {
        clearExcelSmartFillActiveJob(jobId);
        state.excelSmartFillJobId = "";
        state.excelSmartFillPollStartedAt = 0;
        state.excelSmartFillResumeExpected = false;
        setExcelSmartFillCancelVisible(false);
        stopWaiting();
        var overflowFailed = job.error && (
          job.error.code === "EXCEL_SMART_FILL_RESULT_TOO_LARGE" ||
          job.error.code === "EXCEL_SMART_FILL_CONTEXT_TOO_LARGE"
        );
        if (!overflowFailed && job.result && Array.isArray(job.result.items) && job.result.items.length) {
          finalizeExcelSmartFillResult(job.result);
          setStatus("智能填写任务失败，已保留部分预览；未完成项不会写入。" );
        } else {
          if (state.smartFillRetryItemId) {
            restoreSmartFillRetryResult();
          }
          setStatus("智能填写失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
          setPlainResult((job.error && job.error.message) || "后台任务执行失败。" );
        }
        return;
      }
      renderExcelSmartFillJobProgress(job, jobId);
      setTimeout(function () {
        pollExcelSmartFillJob(jobId, stopWaiting);
      }, EXCEL_ANALYSIS_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed;
      var withinRetryBudget;
      var retryDelay;
      var message;
      if (state.excelSmartFillJobId !== jobId) {
        return;
      }
      message = describeExcelSmartFillPollError(error);
      state.excelSmartFillPollErrorCount += 1;
      elapsed = Date.now() - (state.excelSmartFillPollStartedAt || Date.now());
      if (error && error.adapterCode === "EXCEL_SMART_FILL_JOB_INTERRUPTED") {
        clearExcelSmartFillActiveJob(jobId);
        state.excelSmartFillJobId = "";
        state.excelSmartFillPollStartedAt = 0;
        state.excelSmartFillPollErrorCount = 0;
        state.excelSmartFillResumeExpected = false;
        setExcelSmartFillCancelVisible(false);
        setSmartFillInterruptedRetryVisible(true);
        stopWaiting();
        if (state.smartFillRetryItemId) {
          restoreSmartFillRetryResult();
        }
        setStatus("adapter 已重启，原智能填写任务已中断，请重新提交。" );
        setPlainResult("adapter 已重启，原智能填写任务无法恢复，请重新提交智能填写。\n任务编号：" + jobId);
        return;
      }
      if (!isFatalExcelSmartFillPollError(error)) {
        withinRetryBudget = (
          state.excelSmartFillPollErrorCount <= EXCEL_ANALYSIS_POLL_MAX_ERRORS &&
          elapsed <= EXCEL_ANALYSIS_POLL_MAX_WAIT_MS
        );
        retryDelay = withinRetryBudget
          ? EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS
          : EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS;
        saveExcelSmartFillActiveJob({
          jobId: jobId,
          traceId: state.traceId || "",
          startedAt: state.excelSmartFillPollStartedAt || Date.now()
        });
        setStatus("智能填写状态查询暂时失败，正在继续恢复..." );
        setPlainResult([
          "智能填写任务编号仍已保留，将继续自动刷新。",
          "这不代表模型后台任务失败；请保持 WPS 和 adapter 打开。",
          "任务编号：" + jobId,
          "最近错误：" + message
        ].join("\n"));
        setTimeout(function () {
          pollExcelSmartFillJob(jobId, stopWaiting);
        }, retryDelay);
        return;
      }
      clearExcelSmartFillActiveJob(jobId);
      state.excelSmartFillJobId = "";
      state.excelSmartFillPollStartedAt = 0;
      state.excelSmartFillPollErrorCount = 0;
      setExcelSmartFillCancelVisible(false);
      stopWaiting();
      if (state.smartFillRetryItemId) {
        restoreSmartFillRetryResult();
      }
      setStatus("智能填写状态查询持续失败，请查看最近一次任务诊断。" );
      setPlainResult(message);
    });
  }

  function resumeExcelSmartFillActiveJob() {
    var active = loadExcelSmartFillActiveJob();
    if (!active || !active.jobId || state.currentMode !== "excelSmartFill") {
      return;
    }
    state.excelSmartFillJobId = active.jobId;
    state.excelSmartFillPollStartedAt = active.startedAt || Date.now();
    state.excelSmartFillPollErrorCount = 0;
    state.excelSmartFillResumeExpected = true;
    setSmartFillInterruptedRetryVisible(false);
    setAnalysisBusy(true);
    setTrace(active.traceId || active.jobId);
    setStatus("已恢复未完成的智能填写任务，正在查询模型后台结果..." );
    setPlainResult("检测到未完成的智能填写任务，将继续查询 adapter 后台状态。\n任务编号：" + active.jobId);
    pollExcelSmartFillJob(active.jobId, function () {
      setAnalysisBusy(false);
    });
  }

  function runExcelSmartFillAction() {
    var stopWaiting;
    var clientJobId = buildExcelSmartFillClientJobId();
    var payload;
    var startedAt;
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      if (state.smartFillRetryItemId) {
        restoreSmartFillRetryResult();
      }
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。" );
      return;
    }
    if (state.busy || state.workflowProfileMutationBusy) {
      return;
    }
    try {
      payload = buildExcelSmartFillRequest(clientJobId);
    } catch (error) {
      if (state.smartFillRetryItemId) {
        restoreSmartFillRetryResult();
      }
      setStatus(error.message);
      return;
    }
    state.smartFillInstruction = payload.userInstruction;
    setSmartFillInterruptedRetryVisible(false);
    setExcelSmartFillCancelVisible(false);
    setAnalysisBusy(true);
    state.smartFillResult = null;
    byId("btn-write-smart-fill").hidden = true;
    clearExcelSmartFillActiveJob();
    state.excelSmartFillJobId = clientJobId;
    state.excelSmartFillPollStartedAt = Date.now();
    state.excelSmartFillPollErrorCount = 0;
    state.excelSmartFillResumeExpected = true;
    startedAt = state.excelSmartFillPollStartedAt;
    saveExcelSmartFillActiveJob({ jobId: clientJobId, startedAt: startedAt });
    byId("result-view-switch").hidden = true;
    setScopeLine(summarizeSmartFillSource(payload.source));
    setStatus("正在提交智能填写请求..." );
    setPlainResult("正在等待模型后台生成智能填写预览。" );
    stopWaiting = startExcelSmartFillWaitFeedback();
    (function (stopFeedback) {
      stopWaiting = function () {
        stopFeedback();
        setAnalysisBusy(false);
      };
    })(stopWaiting);
    request("/excel/smart-fill/jobs", payload, {
      timeoutMs: EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      var jobId = job.jobId || clientJobId || body.traceId;
      if (state.excelSmartFillJobId !== clientJobId) {
        return;
      }
      setTrace(body.traceId || job.traceId || jobId);
      if (!jobId) {
        clearExcelSmartFillActiveJob(clientJobId);
        stopWaiting();
        if (state.smartFillRetryItemId) {
          restoreSmartFillRetryResult();
        }
        setStatus("智能填写失败：adapter 未返回后台任务编号。" );
        setPlainResult("adapter 未返回后台任务编号，请重试或查看最近一次任务诊断。" );
        return;
      }
      state.excelSmartFillJobId = jobId;
      saveExcelSmartFillActiveJob({
        jobId: jobId,
        traceId: body.traceId || job.traceId || "",
        startedAt: startedAt
      });
      if (job.status === "completed") {
        clearExcelSmartFillActiveJob(jobId);
        state.excelSmartFillJobId = "";
        state.excelSmartFillPollStartedAt = 0;
        state.excelSmartFillResumeExpected = false;
        stopWaiting();
        finalizeExcelSmartFillResult(job.result || {});
        setStatus("智能填写预览已生成，请确认后写入。" );
        return;
      }
      renderExcelSmartFillJobProgress(job, jobId);
      pollExcelSmartFillJob(jobId, stopWaiting);
    }).catch(function (error) {
      var message = describeExcelSmartFillPollError(error);
      if (state.excelSmartFillJobId !== clientJobId) {
        return;
      }
      if (isFatalExcelSmartFillPollError(error)) {
        clearExcelSmartFillActiveJob(clientJobId);
        state.excelSmartFillJobId = "";
        state.excelSmartFillPollStartedAt = 0;
        state.excelSmartFillResumeExpected = false;
        setExcelSmartFillCancelVisible(false);
        stopWaiting();
        if (state.smartFillRetryItemId) {
          restoreSmartFillRetryResult();
        }
        setStatus("智能填写失败：" + message);
        setPlainResult(message);
        return;
      }
      setStatus("智能填写提交响应未确认，正在按任务编号恢复状态查询..." );
      setPlainResult("任务可能已经提交，将按本地任务编号继续查询。\n任务编号：" + clientJobId + "\n最近错误：" + message);
      pollExcelSmartFillJob(clientJobId, stopWaiting);
    });
  }

  function fallbackCopy(text, feedback) {
    var textarea = document.createElement("textarea");
    var report = typeof feedback === "function" ? feedback : setStatus;
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      report("结果已复制。");
    } catch (error) {
      report("复制失败，请手动选择结果文本。");
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

  function copyPrimaryFormula() {
    var rawFallback = Boolean(state.formulaResult && state.formulaResult.parseDiagnostic);
    var formula = String((state.formulaResult && (state.formulaResult.copyText || state.formulaResult.primaryFormula)) || "").trim();
    var successMessage = rawFallback ? "原始结果已复制，请人工核对。" : "主公式已复制，工作簿未被修改。";
    if (!formula) {
      setStatus("暂无可复制的主公式。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(formula).then(function () {
        setStatus(successMessage);
      }).catch(function () {
        fallbackCopy(formula, function () {
          setStatus(successMessage);
        });
      });
      return;
    }
    fallbackCopy(formula, function () {
      setStatus(successMessage);
    });
  }

  function setProviderLine(providerName) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "模型接口",
      "enterprise-dify-workflow": "工作流平台",
      mock: "模拟接口"
    };
    var detail = providerText[providerName] || providerName || "未检测";
    setNodeTextIfChanged(byId("provider-line"), "接口：" + detail);
    setNodeTextIfChanged(byId("settings-provider-line"), "接口：" + detail);
  }

  function setProviderBaseUrl(baseUrl) {
    var summary = byId("provider-summary-url");
    state.providerBaseUrl = baseUrl || "";
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    if (byId("provider-base-url").value !== state.providerBaseUrl) {
      byId("provider-base-url").value = state.providerBaseUrl;
    }
  }

  function applyProviderConfig(configData) {
    var config = configData || {};
    setProviderBaseUrl(config.providerBaseUrl || "");
    state.taskApiKeys = config.taskApiKeys || {};
    renderWorkflowProfileManager();
    renderWorkflowProfileStrip();
  }

  function renderModelInterfaceState(detectable) {
    var profilesByTask = {};
    var modelState;
    var badge = byId("provider-readiness-badge");
    var summary = byId("provider-summary-url");
    TASK_API_KEY_DEFS.forEach(function (definition) {
      profilesByTask[definition.taskType] = getWorkflowProfileData(definition.taskType);
    });
    modelState = helpers.deriveModelInterfaceState({
      detectable: detectable,
      providerBaseUrl: state.providerBaseUrl,
      taskTypes: TASK_API_KEY_DEFS.map(function (definition) { return definition.taskType; }),
      profilesByTask: profilesByTask
    });
    setNodeClassNameIfChanged(badge, "readiness-badge is-" + modelState.code);
    setNodeTextIfChanged(badge, modelState.label);
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    setNodeTextIfChanged(byId("diagnostics-summary"), modelState.label);
  }

  function emptyWorkflowProfileData(taskType) {
    return {
      taskType: taskType || state.workflowTaskType || EXCEL_WORKFLOW_TASK_TYPE,
      activeProfileId: "",
      profileCount: 0,
      profiles: []
    };
  }

  function normalizeWorkflowProfileData(data, taskType) {
    if (helpers.normalizeWorkflowProfileData) {
      return helpers.normalizeWorkflowProfileData(data, taskType);
    }
    return data || emptyWorkflowProfileData(taskType);
  }

  function getWorkflowProfileData(taskType) {
    var targetTask = taskType || state.workflowTaskType || EXCEL_WORKFLOW_TASK_TYPE;
    return state.workflowProfilesByTask[targetTask] || emptyWorkflowProfileData(targetTask);
  }

  function getActiveWorkflowProfileName(data) {
    if (helpers.getActiveWorkflowProfileName) {
      return helpers.getActiveWorkflowProfileName(data);
    }
    return "尚未配置";
  }

  function loadWorkflowProfileForTask(taskType, configRefreshRequestId, requestOptions) {
    var requestSequence = (state.workflowProfileLoadSequences[taskType] || 0) + 1;
    var previousProfileData = state.workflowProfilesByTask[taskType];
    state.workflowProfileLoadSequences[taskType] = requestSequence;
    return request(
      "/provider/model-configurations?taskType=" + encodeURIComponent(taskType),
      null,
      requestOptions
    )
      .then(function (body) {
        if (requestSequence !== state.workflowProfileLoadSequences[taskType] ||
            (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
          return { superseded: true };
        }
        state.workflowProfilesByTask[taskType] = normalizeWorkflowProfileData(body.data || {}, taskType);
        state.workflowProfileSelections[taskType] = state.workflowProfilesByTask[taskType].activeProfileId || "";
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        renderModelInterfaceState(state.modelInterfaceDetectable);
        return state.workflowProfilesByTask[taskType];
      })
      .catch(function (error) {
        var preservedProfileData;
        if (requestSequence !== state.workflowProfileLoadSequences[taskType] ||
            (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
          return { superseded: true };
        }
        if (previousProfileData) {
          preservedProfileData = {};
          Object.keys(previousProfileData).forEach(function (key) {
            preservedProfileData[key] = previousProfileData[key];
          });
          preservedProfileData.loadError = describeFetchError(error);
          state.workflowProfilesByTask[taskType] = preservedProfileData;
        } else {
          state.workflowProfilesByTask[taskType] = emptyWorkflowProfileData(taskType);
          state.workflowProfilesByTask[taskType].loadError = describeFetchError(error);
        }
        state.modelInterfaceDetectable = false;
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        renderModelInterfaceState(state.modelInterfaceDetectable);
        return { failed: true };
      });
  }

  function loadWorkflowProfiles(configRefreshRequestId, requestOptions) {
    return Promise.all(TASK_API_KEY_DEFS.map(function (definition) {
      return loadWorkflowProfileForTask(
        definition.taskType,
        configRefreshRequestId,
        requestOptions
      );
    })).then(function (results) {
      if (results.some(function (item) { return item && item.superseded; })) {
        return { superseded: true, results: results };
      }
      if (results.some(function (item) { return item && item.failed; })) {
        state.modelInterfaceDetectable = false;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        return { failed: true, results: results };
      }
      state.modelInterfaceDetectable = state.modelInterfaceConfigDetectable;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      return { results: results };
    });
  }

  function getTaskPageWorkflowType() {
    if (state.currentMode === "excelFormulaAssistant") {
      return EXCEL_FORMULA_WORKFLOW_TASK_TYPE;
    }
    return state.currentMode === "excelSmartFill"
      ? EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE
      : EXCEL_WORKFLOW_TASK_TYPE;
  }

  function syncWorkflowProfileSelectOptions(select, optionModels) {
    var options = select.options || select.children || [];
    var canReuseOptions = options.length === optionModels.length;
    var index;
    var option;
    var model;
    if (canReuseOptions) {
      for (index = 0; index < optionModels.length; index += 1) {
        if (!options[index] || String(options[index].value || "") !== optionModels[index].value) {
          canReuseOptions = false;
          break;
        }
      }
    }
    if (!canReuseOptions) {
      select.innerHTML = "";
      for (index = 0; index < optionModels.length; index += 1) {
        option = document.createElement("option");
        option.value = optionModels[index].value;
        select.appendChild(option);
      }
      options = select.options || select.children || [];
    }
    for (index = 0; index < optionModels.length; index += 1) {
      option = options[index];
      model = optionModels[index];
      if (option.textContent !== model.text) {
        option.textContent = model.text;
      }
      if (option.selected !== model.selected) {
        option.selected = model.selected;
      }
      if (option.disabled !== model.disabled) {
        option.disabled = model.disabled;
      }
    }
  }

  function renderWorkflowProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var select = byId("workflow-profile-select");
    var feedback = byId("workflow-switch-feedback");
    var taskType = getTaskPageWorkflowType();
    var data = getWorkflowProfileData(taskType);
    var selectedId = state.workflowProfileSelections[taskType] || data.activeProfileId || "";
    var availableProfiles = data.profiles.filter(function (profile) { return profile.complete; });
    var optionModels = [];
    if (!strip || !select || !feedback) {
      return;
    }
    strip.hidden = state.currentMode === "settings";
    select.setAttribute("aria-label", taskType === EXCEL_FORMULA_WORKFLOW_TASK_TYPE
      ? "选择公式助手模型配置"
      : (taskType === "excel.smart_fill" ? "选择智能填写模型配置" : "选择智能分析模型配置"));
    if (!availableProfiles.length) {
      optionModels.push({
        value: "",
        text: data.loadError ? "配置读取失败" : "未配置",
        selected: true,
        disabled: false
      });
    } else {
      availableProfiles.forEach(function (profile) {
        var optionState = helpers.workflowProfileOptionState
          ? helpers.workflowProfileOptionState(profile, data.activeProfileId)
          : {
            id: profile.id,
            label: String(profile.name || "未命名配置") + " · " +
              (profile.accessMethod === "direct_model" ? "模型直连" : "工作流平台"),
            disabled: !profile.complete
          };
        optionModels.push({
          value: optionState.id,
          text: optionState.label,
          disabled: optionState.disabled,
          selected: optionState.id === selectedId
        });
      });
    }
    syncWorkflowProfileSelectOptions(select, optionModels);
    select.disabled = state.busy || state.workflowProfileMutationBusy || !availableProfiles.length;
    setNodeTextIfChanged(
      feedback,
      state.workflowProfileMutationBusy ? "正在切换..." : "当前配置：" + getActiveWorkflowProfileName(data)
    );
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
    var data = getWorkflowProfileData(state.workflowTaskType);
    var rows = [];
    var summary = byId("workflow-manager-summary");
    if (!manager) {
      return;
    }
    summary.textContent = "当前：" + getActiveWorkflowProfileName(data) + "，共 " + data.profileCount + " 个配置";
    if (data.loadError) {
      rows.push('<div class="workflow-empty-state"><p>无法读取模型配置：' + escaped(data.loadError) +
        '</p><button type="button" class="ghost-action" data-workflow-action="retry">重新读取</button></div>');
    } else if (!data.profiles.length) {
      rows.push('<div class="workflow-empty-state"><p>尚未建立模型配置。</p></div>');
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
        (isActive ? "当前" : (profile.complete ? "配置完整" : "配置不完整")) + '</span></div>');
      rows.push('<p class="workflow-profile-note">' +
        (profile.accessMethod === "direct_model" ? "模型直连" + (profile.modelName ? " · " + escaped(profile.modelName) : "") : "工作流平台") + '</p>');
      if (profile.note) {
        rows.push('<p class="workflow-profile-note" title="' + escaped(profile.note) + '">' +
          escaped(profile.note) + '</p>');
      }
      rows.push('</div>');
      rows.push('<div class="workflow-profile-actions">');
      if (!isActive) {
        rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="activate" data-profile-id="' + id + '"' +
          (profile.complete ? "" : " disabled") + '>设为当前</button>');
      }
      rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="edit" data-profile-id="' + id + '">编辑</button>');
      rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="copy" data-profile-id="' + id + '">复制</button>');
      rows.push('<button type="button" class="ghost-action mini-button danger-action" data-workflow-action="delete" data-profile-id="' + id + '"' +
        (canDelete ? "" : ' disabled title="当前模型配置不能删除"') + '>删除</button>');
      rows.push('</div></div>');
    });
    rows.push('</div>');
    manager.innerHTML = rows.join("");
    byId("btn-new-workflow-profile").disabled =
      state.workflowProfileMutationBusy || Boolean(data.loadError);
  }

  function renderWorkflowTaskTabs() {
    var tabs = byId("workflow-task-tabs");
    var buttons;
    var index;
    if (!tabs) {
      return;
    }
    buttons = tabs.querySelectorAll("[data-workflow-task-tab]");
    for (index = 0; index < buttons.length; index += 1) {
      var active = buttons[index].getAttribute("data-workflow-task-tab") === state.workflowTaskType;
      buttons[index].classList.toggle("active", active);
      buttons[index].setAttribute("aria-selected", active ? "true" : "false");
      buttons[index].tabIndex = active ? 0 : -1;
      buttons[index].disabled = state.workflowProfileMutationBusy;
    }
  }

  function scrollWorkflowTaskTabIntoView(button) {
    var reducedMotion = false;
    if (!button || typeof button.scrollIntoView !== "function") {
      return;
    }
    try {
      reducedMotion = Boolean(
        window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    } catch (error) {
      reducedMotion = false;
    }
    try {
      button.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "nearest",
        inline: "nearest"
      });
    } catch (error) {
      try {
        button.scrollIntoView(true);
      } catch (fallbackError) {
        // Older WPS WebViews may not expose a working scrollIntoView implementation.
      }
    }
  }

  function handleWorkflowTaskTabClick(event) {
    var taskType = event.target.getAttribute("data-workflow-task-tab");
    if (taskType !== EXCEL_WORKFLOW_TASK_TYPE &&
        taskType !== EXCEL_FORMULA_WORKFLOW_TASK_TYPE &&
        taskType !== EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE) {
      return;
    }
    state.workflowTaskType = taskType;
    renderWorkflowTaskTabs();
    renderWorkflowProfileManager();
    if (!state.workflowProfilesByTask[taskType]) {
      loadWorkflowProfileForTask(taskType);
    }
    scrollWorkflowTaskTabIntoView(event.target);
  }

  function handleWorkflowTaskTabKeydown(event) {
    var buttons = byId("workflow-task-tabs").querySelectorAll("[data-workflow-task-tab]");
    var currentIndex = Array.prototype.indexOf.call(buttons, event.target);
    var nextIndex = currentIndex;
    var nextButton;
    if (currentIndex < 0 || state.workflowProfileMutationBusy || !buttons.length) {
      return;
    }
    if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    } else if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % buttons.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = buttons.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    nextButton = buttons[nextIndex];
    nextButton.click();
    nextButton.focus();
    scrollWorkflowTaskTabIntoView(nextButton);
  }

  function setWorkflowHelpOpen(open, pinned) {
    var button = byId("workflow-help-button");
    var popover = byId("workflow-help-popover");
    if (typeof pinned === "boolean") {
      state.workflowHelpPinned = pinned;
    }
    popover.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
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
    renderWorkflowTaskTabs();
    syncSettingsRefreshController();
  }

  function finishWorkflowMutation(message) {
    return loadWorkflowProfiles().then(function () {
      setWorkflowMutationBusy(false);
      renderModelInterfaceState(state.modelInterfaceDetectable);
      setStatus(message);
    });
  }

  function failWorkflowMutation(prefix, error) {
    setWorkflowMutationBusy(false);
    setStatus(prefix + "：" + describeFetchError(error));
  }

  function findWorkflowProfile(profileId, taskType) {
    var profiles = getWorkflowProfileData(taskType || state.workflowTaskType).profiles;
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
    var data = getWorkflowProfileData(state.workflowTaskType);
    var profile = mode === "edit" ? findWorkflowProfile(profileId, state.workflowTaskType) : null;
    var activateChecked;
    if (mode === "edit" && !profile) {
      setStatus("未找到要编辑的模型配置，请重新进入设置。");
      return;
    }
    activateChecked = helpers.shouldActivateNewWorkflowProfile
      ? helpers.shouldActivateNewWorkflowProfile(data.profileCount, false)
      : data.profileCount === 0;
    state.workflowEditor = {
      open: true,
      mode: mode === "edit" ? "edit" : "create",
      profileId: profile ? profile.id : "",
      dirty: false,
      originalAccessMethod: profile ? profile.accessMethod : "workflow_platform",
      currentAccessMethod: profile ? profile.accessMethod : "workflow_platform"
    };
    byId("workflow-settings-home").hidden = true;
    byId("workflow-editor-view").hidden = false;
    byId("workflow-editor-title").textContent = profile ? "编辑模型配置" : "新建模型配置";
    byId("workflow-editor-name").value = profile ? profile.name : "";
    byId("workflow-editor-note").value = profile ? profile.note : "";
    byId("workflow-editor-method").value = profile ? profile.accessMethod : "workflow_platform";
    byId("workflow-editor-url").value = profile ? profile.serviceBaseUrl : "";
    byId("workflow-editor-model").value = profile ? profile.modelName : "";
    byId("workflow-editor-model-row").hidden = byId("workflow-editor-method").value !== "direct_model";
    byId("workflow-editor-direct-advanced").hidden = byId("workflow-editor-method").value !== "direct_model";
    byId("workflow-editor-temperature").value = profile && profile.temperature !== null ? profile.temperature : "";
    byId("workflow-editor-max-output").value = profile && profile.maxOutputTokens ? profile.maxOutputTokens : "";
    byId("workflow-editor-context").value = profile ? profile.contextWindowTokens : 40000;
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key-confirm").value = "";
    byId("workflow-editor-key-label").textContent = profile && profile.keyConfigured ? "更换 API Key（选填）" : "API Key（可稍后配置）";
    byId("workflow-editor-key-status").textContent = profile
      ? (profile.keyConfigured ? "API Key 已配置。" : "API Key 未配置，可保存后继续补充。")
      : "API Key 可稍后配置。";
    byId("btn-validate-model-configuration").disabled = !profile || !profile.complete;
    byId("model-validation-summary").textContent = profile && profile.lastValidation
      ? profile.lastValidation.message || "已有最近验证记录"
      : "尚未验证";
    byId("workflow-editor-activate").checked = profile
      ? profile.id === data.activeProfileId
      : activateChecked;
    byId("workflow-editor-activate").parentNode.hidden = Boolean(profile);
    byId("workflow-editor-error").textContent = "";
    syncSettingsRefreshController();
  }

  function closeWorkflowEditor(force) {
    if (!force && state.workflowEditor.dirty && window.confirm &&
        !window.confirm("当前模型配置尚未保存，确认放弃修改并返回？")) {
      return false;
    }
    state.workflowEditor = { open: false, mode: "create", profileId: "", dirty: false };
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key-confirm").value = "";
    byId("workflow-editor-key").type = "password";
    byId("workflow-settings-home").hidden = false;
    byId("workflow-editor-view").hidden = true;
    byId("workflow-editor-error").textContent = "";
    syncSettingsRefreshController();
    return true;
  }

  function handleModelAccessMethodChange() {
    var editor = state.workflowEditor;
    var input = byId("workflow-editor-method");
    var nextMethod = input.value;
    if (editor.currentAccessMethod && editor.currentAccessMethod !== nextMethod && window.confirm &&
        !window.confirm("切换接入方式会清空原方式的专属参数和 API Key，是否继续？")) {
      input.value = editor.currentAccessMethod;
      return;
    }
    editor.currentAccessMethod = nextMethod;
    editor.dirty = true;
    byId("workflow-editor-model-row").hidden = nextMethod !== "direct_model";
    byId("workflow-editor-direct-advanced").hidden = nextMethod !== "direct_model";
    byId("btn-validate-model-configuration").disabled = true;
    if (editor.originalAccessMethod && editor.originalAccessMethod !== nextMethod) {
      byId("workflow-editor-key").value = "";
      byId("workflow-editor-key-confirm").value = "";
      byId("workflow-editor-model").value = "";
      byId("workflow-editor-temperature").value = "";
      byId("workflow-editor-max-output").value = "";
    }
  }

  function validateCurrentModelConfiguration() {
    var profileId = state.workflowEditor.profileId;
    if (!profileId || state.workflowEditor.dirty) {
      setStatus("请先保存模型配置，再执行验证调用。");
      return;
    }
    if (window.confirm && !window.confirm("验证调用会向模型后台发送一条内置测试请求，是否继续？")) {
      return;
    }
    setWorkflowMutationBusy(true);
    setStatus("正在验证模型配置，模型响应较慢时请耐心等待...");
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/validate", {})
      .then(function (body) {
        var duration = Number(body && body.data && body.data.durationMs || 0);
        return loadWorkflowProfiles().then(function () {
          setWorkflowMutationBusy(false);
          var profile = findWorkflowProfile(profileId, state.workflowTaskType);
          state.workflowEditor.dirty = false;
          byId("model-validation-summary").textContent = "验证成功，用时 " + (duration / 1000).toFixed(1) + " 秒";
          byId("btn-validate-model-configuration").disabled = !profile || !profile.complete;
          setStatus("模型配置验证成功。");
        });
      }).catch(function (error) {
        setWorkflowMutationBusy(false);
        byId("model-validation-summary").textContent = "验证失败：" + describeFetchError(error);
        setStatus("验证失败：" + describeFetchError(error));
      });
  }

  function copyModelConfiguration(profileId) {
    setWorkflowMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/copy", {
      targetTaskType: state.workflowTaskType
    }).then(function () {
      return finishWorkflowMutation("模型配置副本已创建，请检查后再启用。");
    }).catch(function (error) {
      failWorkflowMutation("复制模型配置失败", error);
    });
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
    var data = getWorkflowProfileData(state.workflowTaskType);
    var draft = {
      name: byId("workflow-editor-name").value,
      note: byId("workflow-editor-note").value,
      apiKey: byId("workflow-editor-key").value.trim(),
      apiKeyConfirm: byId("workflow-editor-key-confirm").value.trim(),
      accessMethod: byId("workflow-editor-method").value,
      serviceBaseUrl: byId("workflow-editor-url").value.trim(),
      modelName: byId("workflow-editor-model").value.trim(),
      temperature: byId("workflow-editor-temperature").value,
      maxOutputTokens: byId("workflow-editor-max-output").value,
      contextWindowTokens: byId("workflow-editor-context").value || "40000"
    };
    var checked = helpers.validateWorkflowProfileDraft
      ? helpers.validateWorkflowProfileDraft(draft, state.workflowEditor.mode)
      : { ok: Boolean(draft.name.trim() && (state.workflowEditor.mode === "edit" || draft.apiKey.trim())), name: draft.name.trim(), note: draft.note.trim(), apiKey: draft.apiKey.trim() };
    var profileId = state.workflowEditor.profileId;
    var activateChecked = byId("workflow-editor-activate").checked;
    if (!checked.ok) {
      showWorkflowEditorError(checked.field, checked.message || "请检查模型配置。");
      return;
    }
    if (draft.apiKey !== draft.apiKeyConfirm) {
      showWorkflowEditorError("apiKey", "两次输入的 API Key 不一致。");
      return;
    }
    var configurationPayload = {
      taskType: state.workflowTaskType,
      name: checked.name,
      note: checked.note,
      accessMethod: draft.accessMethod,
      serviceBaseUrl: draft.serviceBaseUrl,
      modelName: draft.accessMethod === "direct_model" ? draft.modelName : "",
      temperature: draft.accessMethod === "direct_model" && draft.temperature !== "" ? Number(draft.temperature) : null,
      maxOutputTokens: draft.accessMethod === "direct_model" && draft.maxOutputTokens !== "" ? Number(draft.maxOutputTokens) : null,
      contextWindowTokens: draft.accessMethod === "direct_model" ? Number(draft.contextWindowTokens) : 40000
    };
    setWorkflowMutationBusy(true);
    if (state.workflowEditor.mode === "create") {
      request("/provider/model-configurations", configurationPayload).then(function (body) {
        var configuration = body.data.configuration;
        var saveKey = draft.apiKey ? request("/provider/model-configurations/" + encodeURIComponent(configuration.id) + "/api-key", { apiKey: draft.apiKey }) : Promise.resolve();
        return saveKey.then(function () {
          var shouldActivate = helpers.shouldActivateNewWorkflowProfile
            ? helpers.shouldActivateNewWorkflowProfile(data.profileCount, activateChecked)
            : data.profileCount === 0 || activateChecked;
          var complete = Boolean(draft.serviceBaseUrl && draft.apiKey &&
            (draft.accessMethod !== "direct_model" || draft.modelName));
          return shouldActivate && complete
            ? request("/provider/model-configurations/" + encodeURIComponent(configuration.id) + "/activate", {})
            : null;
        });
      }).then(function () {
        return finishWorkflowEditorSave("模型配置已新建。");
      }).catch(function (error) {
        failWorkflowEditorSave("新建模型配置失败", error);
      });
      return;
    }
    request("/provider/model-configurations/" + encodeURIComponent(profileId), configurationPayload, { method: "PATCH" }).then(function () {
      if (!draft.apiKey) {
        return finishWorkflowEditorSave("模型配置已保存，API Key 保持不变。");
      }
      return request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/api-key", {
        apiKey: draft.apiKey
      }).then(function () {
        return finishWorkflowEditorSave("模型配置和 API Key 已保存。");
      }).catch(function (error) {
        return showPartialKeyFailure(error, "模型配置已保存，但 API Key 更换失败，原 Key 仍然有效");
      });
    }).catch(function (error) {
      failWorkflowEditorSave("保存模型配置失败", error);
    });
  }

  function activateWorkflowProfile(profileId, previousProfileId, taskType) {
    var targetTask = taskType || getTaskPageWorkflowType();
    var profile = findWorkflowProfile(profileId, targetTask);
    previousProfileId = previousProfileId || getWorkflowProfileData(targetTask).activeProfileId || "";
    if (!profileId || profileId === previousProfileId) {
      state.workflowProfileSelections[targetTask] = previousProfileId;
      renderWorkflowProfileStrip();
      return;
    }
    if (!profile || !profile.complete || state.busy || state.workflowProfileMutationBusy) {
      state.workflowProfileSelections[targetTask] = previousProfileId;
      renderWorkflowProfileStrip();
      setStatus(!profile || !profile.complete ? "该模型配置不完整，不能切换。" : "当前正忙，请稍后切换模型配置。");
      setNodeTextIfChanged(
        byId("workflow-switch-feedback"),
        "当前：" + getActiveWorkflowProfileName(getWorkflowProfileData(targetTask))
      );
      return;
    }
    state.workflowProfileSelections[targetTask] = profileId;
    state.workflowProfileLoadSequences[targetTask] = (state.workflowProfileLoadSequences[targetTask] || 0) + 1;
    setWorkflowMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/activate", {})
      .then(function () {
        return loadWorkflowProfileForTask(targetTask);
      }).then(function () {
        state.workflowProfileSelections[targetTask] = getWorkflowProfileData(targetTask).activeProfileId;
        setWorkflowMutationBusy(false);
        renderModelInterfaceState(state.modelInterfaceDetectable);
        setStatus("模型配置已切换，从下一次任务开始生效。");
      }).catch(function (error) {
        state.workflowProfileSelections[targetTask] = previousProfileId;
        setWorkflowMutationBusy(false);
        setStatus("切换模型配置失败：" + describeFetchError(error));
        setNodeTextIfChanged(
          byId("workflow-switch-feedback"),
          "切换失败，当前：" + getActiveWorkflowProfileName(getWorkflowProfileData(targetTask))
        );
      });
  }

  function cancelWorkflowProfileActivation() {
    if (state.workflowProfileActivationTimer !== null) {
      window.clearTimeout(state.workflowProfileActivationTimer);
      state.workflowProfileActivationTimer = null;
    }
  }

  function scheduleWorkflowProfileActivation(profileId, previousProfileId, taskType) {
    cancelWorkflowProfileActivation();
    state.workflowProfileActivationTimer = window.setTimeout(function () {
      state.workflowProfileActivationTimer = null;
      activateWorkflowProfile(profileId, previousProfileId, taskType);
    }, 0);
  }

  function showWorkflowDeleteDialog(profileId) {
    var data = getWorkflowProfileData(state.workflowTaskType);
    var profile = findWorkflowProfile(profileId, state.workflowTaskType);
    if (!profile) {
      return;
    }
    if (profile.id === data.activeProfileId) {
      setStatus("当前模型配置不能删除，请先切换到其他模型配置。");
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
    var activeProfileId = getWorkflowProfileData(state.workflowTaskType).activeProfileId;
    if (!candidate || state.workflowProfileMutationBusy) {
      return;
    }
    if (candidate.id === activeProfileId) {
      hideWorkflowDeleteDialog();
      setStatus("当前模型配置不能删除，请先切换到其他模型配置。");
      return;
    }
    setWorkflowMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(candidate.id), null, { method: "DELETE" })
      .then(function () {
        hideWorkflowDeleteDialog();
        return finishWorkflowMutation("模型配置“" + candidate.name + "”已删除。");
      }).catch(function (error) {
        hideWorkflowDeleteDialog();
        failWorkflowMutation("删除模型配置失败", error);
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
      activateWorkflowProfile(
        profileId,
        getWorkflowProfileData(state.workflowTaskType).activeProfileId,
        state.workflowTaskType
      );
    } else if (action === "edit") {
      openWorkflowEditor("edit", profileId);
    } else if (action === "delete") {
      showWorkflowDeleteDialog(profileId);
    } else if (action === "copy") {
      copyModelConfiguration(profileId);
    }
  }

  function showProviderEditor() {
    state.providerUrlEditorOpen = true;
    byId("provider-edit-view").hidden = false;
    byId("provider-summary-card").classList.add("editing");
    byId("btn-edit-provider-url").hidden = true;
    byId("provider-base-url").focus();
    syncSettingsRefreshController();
  }

  function hideProviderEditor(suppressRefreshSync) {
    state.providerUrlEditorOpen = false;
    byId("provider-base-url").value = state.providerBaseUrl || "";
    byId("provider-edit-view").hidden = true;
    byId("provider-summary-card").classList.remove("editing");
    byId("btn-edit-provider-url").hidden = false;
    if (suppressRefreshSync !== true) {
      syncSettingsRefreshController();
    }
  }

  function setAdapterUnavailableState(error) {
    var message = error && error.message ? error.message : "端口未监听";
    setHealthBadge("badge-warn", "待启动");
    setTrace("");
    setProviderLine("mock");
    setStatus("本地适配服务暂不可用。");
    setResult([
      "本地适配服务暂不可用，插件无法访问 http://127.0.0.1:18100。",
      "请确认已执行 adapter 一键启动脚本，并用健康检查确认 /health 可访问。",
      "后台返回：" + message
    ].join("\n"));
  }

  function refreshConfig(options) {
    var requestId;
    var refreshOperation;
    var refreshPromise;
    var healthConnected = false;
    var configLoaded = false;
    var silent = Boolean(options && options.silent);

    function releaseRefresh(result) {
      var shouldRestart = false;
      var restartSilent = true;
      if (state.configRefreshPromise === refreshPromise) {
        state.configRefreshPromise = null;
        state.configRefreshActiveRequestId = 0;
        state.configRefreshActiveSilent = false;
        shouldRestart = state.configRefreshQueued;
        restartSilent = state.configRefreshQueuedSilent;
        state.configRefreshQueued = false;
        state.configRefreshQueuedSilent = true;
      }
      if (shouldRestart && isSettingsRefreshEligible()) {
        return refreshConfig({ silent: restartSilent });
      }
      return result;
    }

    if (state.configRefreshPromise) {
      if (state.configRefreshActiveRequestId !== state.configRefreshRequestId) {
        if (!state.configRefreshQueued) {
          state.configRefreshQueuedSilent = silent;
        } else {
          state.configRefreshQueuedSilent = state.configRefreshQueuedSilent && silent;
        }
        state.configRefreshQueued = true;
      } else if (!silent && state.configRefreshActiveSilent) {
        state.configRefreshActiveSilent = false;
        setSettingsStatus("正在刷新配置...");
      }
      return state.configRefreshPromise;
    }

    requestId = state.configRefreshRequestId + 1;
    state.configRefreshRequestId = requestId;
    state.configRefreshActiveRequestId = requestId;
    state.configRefreshActiveSilent = silent;
    if (!silent) {
      setSettingsStatus("正在刷新配置...");
    }
    refreshOperation = request("/health", null, {
      timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS
    }).then(function (health) {
      var healthData;
      var healthState;
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      healthData = health.data || {};
      healthConnected = true;
      state.settingsProbeTraceId = health.traceId || "";
      healthState = applyAdapterHealthState(healthData, true);
      setProviderLine(healthData.providerType || "未检测");
      if (healthState.status === "recovery") {
        return null;
      }
      return readAdapterJson("/config", {
        timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS
      });
    }).then(function (config) {
      if (!config || state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (config.success === false) {
        throw new Error(config.errors && config.errors[0] && config.errors[0].message || "配置读取失败");
      }
      applyProviderConfig(config.data || {});
      configLoaded = true;
      state.modelInterfaceConfigDetectable = true;
      return loadWorkflowProfiles(requestId, {
        timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS
      }).then(function (profileResult) {
        if (state.configRefreshRequestId !== requestId) {
          return null;
        }
        if (profileResult && profileResult.superseded) {
          return null;
        }
        if (!profileResult || profileResult.failed) {
          throw new Error("模型配置读取失败");
        }
        state.modelInterfaceDetectable = true;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        if (!state.configRefreshActiveSilent) {
          setSettingsStatus(state.adapterHealthStatus === "degraded"
            ? "增强能力降级，核心功能可用。"
            : "就绪");
        }
        return config;
      });
    }).catch(function (error) {
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (!healthConnected) {
        state.settingsProbeTraceId = "";
        applyAdapterHealthState(null, false);
      }
      if (!configLoaded) {
        state.modelInterfaceConfigDetectable = false;
      }
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      setSettingsStatus("配置刷新失败：" + describeFetchError(error));
      return null;
    });

    refreshPromise = refreshOperation.then(releaseRefresh, function (error) {
      if (state.configRefreshRequestId === requestId) {
        if (!healthConnected) {
          state.settingsProbeTraceId = "";
          applyAdapterHealthState(null, false);
        }
        if (!configLoaded) {
          state.modelInterfaceConfigDetectable = false;
        }
        state.modelInterfaceDetectable = false;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        setSettingsStatus("配置刷新失败：" + describeFetchError(error));
      }
      return releaseRefresh(null);
    });
    state.configRefreshPromise = refreshPromise;
    return refreshPromise;
  }

  function saveProviderBaseUrl() {
    var baseUrl = (byId("provider-base-url").value || "").trim();
    setSettingsStatus("正在保存大模型 API URL...");
    return request("/provider/base-url", { baseUrl: baseUrl })
      .then(function (body) {
        var data = body.data || {};
        var refreshPromise;
        setProviderBaseUrl(typeof data.providerBaseUrl === "string" ? data.providerBaseUrl : baseUrl);
        hideProviderEditor(true);
        setSettingsStatus("大模型 API URL 已保存。");
        invalidateConfigRefresh();
        refreshPromise = refreshConfig({ silent: false });
        syncSettingsRefreshController();
        return refreshPromise;
      })
      .catch(function (error) {
        setSettingsStatus("保存大模型 API URL 失败：" + describeFetchError(error));
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
    var longTasks = routes.longTaskCoordinator || {};
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

    if (typeof longTasks.maxRunning === "number") {
      lines.push("");
      lines.push("## 共享长任务协调器");
      lines.push("- 运行中：" + (longTasks.runningCount || 0) + "/" + longTasks.maxRunning);
      lines.push("- 排队中：" + (longTasks.queuedCount || 0) + "/" + longTasks.maxQueued);
      lines.push("- 终态保留：" + (longTasks.terminalCount || 0) + "/" + longTasks.maxTerminalJobs);
      lines.push("- 终态保留时长：" + (longTasks.terminalTtlSeconds || 0) + " 秒");
      lines.push("- 取消数：" + (longTasks.cancelledCount || 0));
      lines.push("- 拒绝数：" + (longTasks.rejectedCount || 0));
      lines.push("- 超时数：" + (longTasks.timedOutCount || 0));
      (longTasks.recentTerminalJobs || []).forEach(function (job) {
        lines.push(
          "- 最近任务 " + (job.taskType || "未记录") +
          "：" + (job.status || "未记录") +
          "，耗时 " + (job.elapsedSeconds || 0) + " 秒" +
          (job.errorCode ? "，错误码 " + job.errorCode : "")
        );
      });
    }

    if (debug.request) {
      lines.push("");
      lines.push("## 请求摘要");
      lines.push("- body 字段：" + (debug.request.bodyKeys || []).join(", "));
      lines.push("- inputs 字段：" + (debug.request.inputsKeys || []).join(", "));
      lines.push("- query 长度：" + (debug.request.queryLength || 0));
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
      setSettingsStatus("诊断信息已刷新。");
    });
  }

  function handleDiagnosticsDisclosureToggle(event) {
    if (event.currentTarget.open) {
      refreshDiagnostics();
    }
  }

  function copyDiagnostics() {
    var text = state.diagnosticsCopyText || byId("last-task-diagnostics-output").textContent || "";
    if (!text.trim()) {
      setSettingsStatus("暂无可复制的诊断信息。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        setSettingsStatus("诊断信息已复制。");
      }).catch(function () {
        fallbackCopy(text, setSettingsStatus);
      });
    }
    fallbackCopy(text, setSettingsStatus);
  }

  function switchView(viewName) {
    byId("home-view").classList.toggle("active", viewName === "home");
    byId("settings-view").classList.toggle("active", viewName === "settings");
    syncSettingsRefreshController();
    syncScopeWatcher();
  }

  function syncSettingsRefreshController() {
    var settingsView = byId("settings-view");
    var shouldRun;
    if (!state.settingsRefreshController) {
      return;
    }
    shouldRun = Boolean(
      settingsView &&
      byId("settings-view").classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      !state.workflowEditor.open &&
      !state.providerUrlEditorOpen &&
      !state.workflowProfileMutationBusy
    );
    if (shouldRun) {
      state.settingsRefreshController.start();
    } else if (state.settingsRefreshController.isRunning()) {
      state.settingsRefreshController.stop();
      invalidateConfigRefresh();
    }
  }

  function isSettingsRefreshEligible() {
    var settingsView = byId("settings-view");
    return Boolean(
      settingsView &&
      settingsView.classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      !state.workflowEditor.open &&
      !state.providerUrlEditorOpen &&
      !state.workflowProfileMutationBusy
    );
  }

  function invalidateConfigRefresh() {
    state.configRefreshRequestId += 1;
    state.configRefreshQueued = false;
    state.configRefreshQueuedSilent = true;
  }

  function getInitialMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    var mode = match ? decodeURIComponent(match[1]) : "excelAnalysis";
    if (mode === "excelFormulaAssistant") {
      return "excelFormulaAssistant";
    }
    if (mode === "excelSmartFill") {
      return "excelSmartFill";
    }
    return mode === "settings" ? "settings" : "excelAnalysis";
  }

  function switchMode(mode) {
    var settingsMode = mode === "settings";
    var formulaMode = mode === "excelFormulaAssistant";
    var smartFillMode = mode === "excelSmartFill";
    var taskTitle = formulaMode ? "公式助手" : (smartFillMode ? "智能填写" : "智能分析");
    var returnTaskLabel;
    if (settingsMode && state.currentMode !== "settings") {
      state.lastTaskMode = state.currentMode;
    }
    state.currentMode = settingsMode
      ? "settings"
      : (formulaMode ? "excelFormulaAssistant" : (smartFillMode ? "excelSmartFill" : "excelAnalysis"));
    if (!settingsMode) {
      state.lastTaskMode = state.currentMode;
      state.workflowTaskType = formulaMode
        ? EXCEL_FORMULA_WORKFLOW_TASK_TYPE
        : (smartFillMode ? EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE : EXCEL_WORKFLOW_TASK_TYPE);
    }
    returnTaskLabel = state.lastTaskMode === "excelFormulaAssistant"
      ? "公式助手"
      : (state.lastTaskMode === "excelSmartFill" ? "智能填写" : "智能分析");
    document.body.setAttribute("data-task-mode", state.currentMode);
    if (byId("scope-strip")) {
      byId("scope-strip").hidden = smartFillMode;
    }
    byId("task-title").textContent = settingsMode ? "设置" : taskTitle;
    byId("btn-open-settings").classList.toggle("is-back", settingsMode);
    byId("btn-open-settings").setAttribute("title", settingsMode ? "返回" + returnTaskLabel : "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回" + returnTaskLabel : "打开设置");
    byId("excel-analysis-options").hidden = settingsMode || formulaMode || smartFillMode;
    byId("excel-formula-options").hidden = settingsMode || !formulaMode;
    byId("excel-smart-fill-options").hidden = settingsMode || !smartFillMode;
    byId("btn-run-primary").textContent = formulaMode
      ? getFormulaModeUi(state.formulaMode).actionLabel
      : (smartFillMode ? "生成预览" : "生成分析报告");
    byId("btn-copy-formula").hidden = !formulaMode || !String((state.formulaResult && (state.formulaResult.copyText || state.formulaResult.primaryFormula)) || "").trim();
    if (formulaMode) {
      setExcelResultViewSwitchForMode("excelFormulaAssistant");
    } else if (smartFillMode) {
      setExcelResultViewSwitchForMode("excelSmartFill");
    } else if (!settingsMode && state.analysisResult) {
      setExcelResultViewSwitchForMode("excelAnalysis");
    }
    if (settingsMode) {
      byId("diagnostics-disclosure").open = false;
    }
    switchView(settingsMode ? "settings" : "home");
    if (settingsMode) {
      refreshConfig({ silent: false });
    }
    renderWorkflowProfileStrip();
    renderWorkflowProfileManager();
    renderWorkflowTaskTabs();
    renderSmartFillCaptureState();
    setSmartFillWriteButtonState();
    if (!settingsMode) {
      if (formulaMode) {
        setFormulaAssistantMode(state.formulaMode);
        resumeExcelFormulaActiveJob();
      } else if (smartFillMode) {
        resumeExcelSmartFillActiveJob();
      } else {
        resumeExcelAnalysisActiveJob();
      }
      loadWorkflowProfiles();
    }
  }

  function bindEvents() {
    var workflowHelpButton = byId("workflow-help-button");
    var workflowHelpPopover = byId("workflow-help-popover");
    var workflowHelpHeading = document.querySelector(".workflow-settings-heading");
    byId("btn-open-settings").addEventListener("click", function () {
      if (state.currentMode === "settings" && state.workflowEditor.open && !closeWorkflowEditor(false)) {
        return;
      }
      switchMode(state.currentMode === "settings" ? state.lastTaskMode : "settings");
    });
    byId("excel-analysis-requirement").addEventListener("input", function (event) {
      state.analysisRequirement = event.target.value;
    });
    byId("excel-formula-requirement").addEventListener("input", function (event) {
      state.formulaRequirement = event.target.value;
    });
    byId("excel-smart-fill-instruction").addEventListener("input", function (event) {
      state.smartFillInstruction = event.target.value;
      updateSmartFillGenerateEnabled();
      renderSmartFillCaptureState();
    });
    byId("excel-formula-mode-segment").addEventListener("click", function (event) {
      var mode = event.target && event.target.getAttribute("data-formula-mode");
      if (mode) {
        setFormulaAssistantMode(mode);
      }
    });
    byId("excel-formula-mode-segment").addEventListener("keydown", handleFormulaModeKeydown);
    byId("btn-run-primary").addEventListener("click", function () {
      if (state.currentMode === "excelFormulaAssistant") {
        runExcelFormulaAction();
      } else if (state.currentMode === "excelSmartFill") {
        runExcelSmartFillAction();
      } else {
        runExcelAnalysisAction();
      }
    });
    byId("btn-write-smart-fill").addEventListener("click", writeExcelSmartFillResult);
    byId("result-output").addEventListener("input", handleSmartFillResultInput);
    byId("result-output").addEventListener("change", handleSmartFillResultChange);
    byId("result-output").addEventListener("click", handleSmartFillResultClick);
    byId("btn-copy-result").addEventListener("click", copyResult);
    byId("btn-copy-formula").addEventListener("click", copyPrimaryFormula);
    byId("btn-result-preview").addEventListener("click", function () {
      setResultViewMode("preview");
    });
    byId("btn-result-plain").addEventListener("click", function () {
      setResultViewMode("plain");
    });
    byId("btn-save-provider-url").addEventListener("click", saveProviderBaseUrl);
    byId("btn-edit-provider-url").addEventListener("click", showProviderEditor);
    byId("btn-back-provider-summary").addEventListener("click", hideProviderEditor);
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
    byId("btn-recovery-refresh").addEventListener("click", function () {
      refreshConfig({ silent: false });
    });
    byId("btn-recovery-backup").addEventListener("click", createRecoveryBackup);
    byId("btn-recovery-diagnostics").addEventListener("click", exportRecoveryDiagnostics);
    byId("btn-cancel-excel-analysis-job").addEventListener("click", cancelQueuedExcelAnalysisJob);
    byId("btn-cancel-excel-formula-job").addEventListener("click", cancelQueuedExcelFormulaJob);
    byId("btn-cancel-excel-smart-fill-job").addEventListener("click", cancelExcelSmartFillJob);
    byId("btn-resubmit-interrupted-job").addEventListener("click", runExcelAnalysisAction);
    byId("btn-resubmit-interrupted-formula-job").addEventListener("click", runExcelFormulaAction);
    byId("btn-resubmit-interrupted-smart-fill-job").addEventListener("click", runExcelSmartFillAction);
    byId("diagnostics-disclosure").addEventListener("toggle", handleDiagnosticsDisclosureToggle);
    byId("workflow-task-tabs").addEventListener("click", handleWorkflowTaskTabClick);
    byId("workflow-task-tabs").addEventListener("keydown", handleWorkflowTaskTabKeydown);
    workflowHelpButton.addEventListener("click", function () {
      var pinned = !state.workflowHelpPinned;
      setWorkflowHelpOpen(pinned, pinned);
    });
    workflowHelpButton.addEventListener("mouseenter", function () {
      setWorkflowHelpOpen(true);
    });
    workflowHelpButton.addEventListener("focusin", function () {
      setWorkflowHelpOpen(true);
    });
    workflowHelpButton.addEventListener("mouseleave", function () {
      if (!state.workflowHelpPinned) {
        setWorkflowHelpOpen(false, false);
      }
    });
    workflowHelpButton.addEventListener("focusout", function (event) {
      if (!state.workflowHelpPinned && !workflowHelpButton.contains(event.relatedTarget)) {
        setWorkflowHelpOpen(false, false);
      }
    });
    document.addEventListener("click", function (event) {
      if (!workflowHelpHeading.contains(event.target) && !workflowHelpPopover.contains(event.target)) {
        setWorkflowHelpOpen(false, false);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !workflowHelpPopover.hidden) {
        setWorkflowHelpOpen(false, false);
        workflowHelpButton.focus();
      }
    });
    document.addEventListener("visibilitychange", syncSettingsRefreshController);
    document.addEventListener("visibilitychange", syncScopeWatcher);
    byId("workflow-profile-select").addEventListener("change", function (event) {
      var taskType = getTaskPageWorkflowType();
      scheduleWorkflowProfileActivation(
        event.target.value,
        getWorkflowProfileData(taskType).activeProfileId,
        taskType
      );
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
    ["workflow-editor-name", "workflow-editor-note", "workflow-editor-url", "workflow-editor-model",
      "workflow-editor-key", "workflow-editor-key-confirm", "workflow-editor-temperature",
      "workflow-editor-max-output", "workflow-editor-context", "workflow-editor-activate"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        state.workflowEditor.dirty = true;
        byId("workflow-editor-error").textContent = "";
        byId("btn-validate-model-configuration").disabled = true;
      });
    });
    byId("workflow-editor-method").addEventListener("change", handleModelAccessMethodChange);
    byId("btn-validate-model-configuration").addEventListener("click", validateCurrentModelConfiguration);
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
  state.settingsRefreshController = helpers.createSettingsRefreshController({
    intervalMs: 30000,
    refresh: function () {
      return refreshConfig({ silent: true });
    }
  });
  state.scopeWatcher = helpers.createExcelSelectionWatcher({
    intervalMs: 2000,
    getEventSources: getExcelSelectionEventSources,
    refresh: updateScopeIndicator
  });
  switchMode(getInitialMode());
  if (!state.settingsRefreshController.isRunning()) {
    refreshConfig({ silent: true });
  }
  syncScopeWatcher();
})();
