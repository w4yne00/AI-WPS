(function () {
  "use strict";

  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.23.1-alpha";
  var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";
  var PPT_STRUCTURE_WORKFLOW_TASK_TYPE = "ppt.structure_review";
  var TASK_API_KEY_DEFS = [
    { taskType: "ppt.slide_assistant", label: "智能总结" },
    { taskType: "ppt.structure_review", label: "结构审查" }
  ];
  var PPT_SLIDE_POLL_INTERVAL_MS = 3000;
  var PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS = 10000;
  var SETTINGS_REFRESH_REQUEST_TIMEOUT_MS = 8000;
  var PPT_SLIDE_POLL_MAX_ERRORS = 240;
  var PPT_SLIDE_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY = "ai-wps-ppt-slide-assistant-active-job-v1";
  var PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY = "ai-wps-ppt-structure-review-active-job-v1";
  var PPT_STRUCTURE_MAX_SLIDES = 60;
  var PPT_STRUCTURE_MAX_FALLBACK_CHARS = 120;
  var PPT_STRUCTURE_MAX_FALLBACK_SLIDES = 10;
  var PPT_DOCUMENT_SLIDE_COUNTS = { 5: true, 8: true, 10: true, 12: true, 15: true };
  var PPT_EXTRACTION_LIMITS = {
    maxTitleLength: 200,
    maxSubtitleLength: 300,
    maxBlockLength: 1000,
    maxBodyLength: 3000,
    maxAdjacentTitleLength: 200
  };
  var helpers = window.WpsAiPptHelpers || {};
  var state = {
    result: null,
    structureResult: null,
    structureResultView: null,
    taskMode: "pptSlideAssistant",
    workflowTaskType: PPT_WORKFLOW_TASK_TYPE,
    resultMode: "preview",
    sourceMode: "slide",
    selectedDocument: null,
    jobId: "",
    jobSourceMode: "",
    busy: false,
    startedAt: 0,
    pollErrors: 0,
    resumeExpected: false,
    currentView: "home",
    profiles: { activeProfileId: "", profiles: [] },
    profilesByTask: {},
    selectedProfileId: "",
    workflowProfileMutationBusy: false,
    workflowProfileActivationTimer: null,
    profileLoadRequestId: 0,
    workflowEditor: { open: false, mode: "create", profileId: "", dirty: false },
    providerBaseUrl: "",
    adapterHealthStatus: "unknown",
    configurationMutationsAllowed: true,
    modelTasksAllowed: true,
    writingPolicyMutationsAllowed: true,
    diagnosticsText: "",
    configRefreshRequestId: 0,
    configRefreshPromise: null,
    configRefreshActiveRequestId: 0,
    configRefreshActiveSilent: false,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    modelInterfaceDetectable: false,
    settingsRefreshController: null,
    workflowHelpPinned: false,
    providerUrlEditorOpen: false
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

  function safeText(value) {
    return String(value === null || typeof value === "undefined" ? "" : value)
      .replace(/\r/g, "")
      .trim();
  }

  function describeSettingsError(error) {
    var message = safeText(error && error.message);
    if (error && error.name === "AbortError") {
      return "请求超时，请确认本地 adapter 正常运行。";
    }
    if (/failed to fetch|networkerror|load failed/i.test(message)) {
      return "无法连接本地 adapter，请确认服务已启动。";
    }
    return message || "请求失败，请稍后重试。";
  }

  function setStatus(message) {
    var homeStatus = byId("status-line");
    var settingsStatus = byId("settings-status-line");
    setNodeTextIfChanged(homeStatus, message || "");
    setNodeTextIfChanged(settingsStatus, message || "");
  }

  function setSettingsStatus(message) {
    setNodeTextIfChanged(byId("settings-status-line"), message || "");
  }

  function setHealthBadge(className, text) {
    var node = byId("health-indicator");
    if (!node) {
      return;
    }
    setNodeClassNameIfChanged(node, "badge " + className);
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

  function getWppApplication() {
    return window.Application || window.wps || {};
  }

  function queryMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    return match ? decodeURIComponent(match[1]) : "pptSlideAssistant";
  }

  function homeTaskTitle() {
    return state.taskMode === "pptStructureReview" ? "结构审查" : "智能总结";
  }

  function homeWorkflowTaskType() {
    return state.taskMode === "pptStructureReview"
      ? PPT_STRUCTURE_WORKFLOW_TASK_TYPE
      : PPT_WORKFLOW_TASK_TYPE;
  }

  function setHomeTaskMode(mode) {
    var structureMode = mode === "pptStructureReview";
    state.taskMode = structureMode ? "pptStructureReview" : "pptSlideAssistant";
    state.workflowTaskType = homeWorkflowTaskType();
    byId("summary-source-segments").hidden = structureMode;
    byId("summary-controls").hidden = structureMode;
    byId("summary-result-section").hidden = structureMode;
    byId("structure-review-controls").hidden = !structureMode;
    byId("structure-result-section").hidden = !structureMode;
    document.body.setAttribute("data-task-mode", state.taskMode);
  }

  function request(path, payload, options) {
    var settings = options || {};
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () {
      if (controller) {
        controller.abort();
      }
    }, settings.timeoutMs || 15000);
    var fetchOptions = {
      method: settings.method || (payload === null || typeof payload === "undefined" ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" }
    };
    var normalizedMethod = String(fetchOptions.method || "GET").toUpperCase();
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
      clearTimeout(timer);
      var blockedError = new Error(
        "Adapter 当前处于恢复模式，配置变更和模型任务已被安全阻止。"
      );
      blockedError.adapterCode = blockedCode;
      return Promise.reject(blockedError);
    }
    if (controller) {
      fetchOptions.signal = controller.signal;
    }
    if (payload !== null && typeof payload !== "undefined") {
      fetchOptions.body = JSON.stringify(payload);
    }
    return fetch(ADAPTER_BASE_URL + path, fetchOptions).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        var error;
        if (!response.ok || body.success === false) {
          error = new Error(
            (body.errors && body.errors[0] && body.errors[0].message) ||
            body.message ||
            ("HTTP " + response.status)
          );
          error.adapterCode = body.errors && body.errors[0] && body.errors[0].code;
          throw error;
        }
        return body;
      });
    }).finally(function () {
      clearTimeout(timer);
    });
  }

  function buildPptSlideClientJobId(sourceMode) {
    var prefix = sourceMode === "document" ? "client-ppt-document" : "client-ppt-slide";
    return [prefix, Date.now().toString(36), Math.random().toString(36).slice(2, 10)].join("-");
  }

  function loadActiveJob() {
    try {
      var raw = window.localStorage && window.localStorage.getItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveActiveJob(job) {
    try {
      if (window.localStorage && job && job.jobId) {
        window.localStorage.setItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY, JSON.stringify(job));
      }
    } catch (error) {
      // In-memory polling remains available.
    }
  }

  function clearActiveJob(jobId) {
    try {
      var active = loadActiveJob();
      if (!jobId || !active || !active.jobId || active.jobId === jobId) {
        window.localStorage.removeItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY);
      }
    } catch (error) {
      // Cleanup must not block result rendering.
    }
  }

  function loadStructureActiveJob() {
    try {
      var raw = window.localStorage && window.localStorage.getItem(PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveStructureActiveJob(job) {
    try {
      if (window.localStorage && job && job.jobId) {
        window.localStorage.setItem(PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY, JSON.stringify(job));
      }
    } catch (error) {
      // In-memory polling remains available.
    }
  }

  function clearStructureActiveJob(jobId) {
    try {
      var active = loadStructureActiveJob();
      if (!jobId || !active || !active.jobId || active.jobId === jobId) {
        window.localStorage.removeItem(PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY);
      }
    } catch (error) {
      // Cleanup must not block result rendering.
    }
  }

  function setRunDisabled(disabled) {
    var isDisabled = Boolean(disabled);
    state.busy = isDisabled;
    [
      "btn-run-primary",
      "ppt-source-slide",
      "ppt-source-document",
      "ppt-document-file",
      "ppt-slide-count",
      "ppt-slide-instruction",
      "workflow-profile-select",
      "btn-open-settings",
      "btn-run-structure-review",
      "ppt-structure-start-slide",
      "ppt-structure-end-slide"
    ].forEach(function (id) {
      if (byId(id)) {
        byId(id).disabled = isDisabled;
      }
    });
    byId("btn-run-primary").disabled = state.busy || state.workflowProfileMutationBusy;
    byId("btn-run-structure-review").disabled = state.busy || state.workflowProfileMutationBusy;
    renderProfileStrip();
  }

  function setPptJobActionVisibility(job) {
    var cancelButton = byId("btn-cancel-ppt-slide-job");
    if (cancelButton) {
      cancelButton.hidden = !(job && job.status === "queued" && job.canCancel);
      cancelButton.disabled = false;
    }
  }

  function setInterruptedRetryVisible(visible) {
    var button = byId("btn-resubmit-interrupted-job");
    if (button) {
      button.hidden = !visible;
    }
  }

  function showProgressText(text) {
    if (!state.result) {
      setPlainResult(text);
    }
  }

  function setSummary(payload) {
    var slide = payload && payload.slide ? payload.slide : {};
    var adjacent = [
      slide.previousTitle ? "前一页" : "",
      slide.nextTitle ? "后一页" : ""
    ].filter(Boolean).join("、") || "无";
    byId("ppt-slide-summary").textContent = [
      "第 " + (slide.index || 0) + " 页",
      "主标题：" + (slide.title || "未识别"),
      "副标题：" + (slide.subtitle || "无"),
      "正文字数：" + (slide.bodyCharacterCount || 0),
      "相邻标题：" + adjacent,
      slide.truncated ? "已按本页内容上限读取" : "未截断"
    ].join(" ｜ ");
  }

  function setPlainResult(text) {
    var output = byId("result-output");
    output.classList.add("plain-output");
    output.classList.remove("markdown-output");
    output.innerHTML = "";
    output.textContent = text || "";
  }

  function applyPptSummaryResultView() {
    var presented = helpers.presentPptSummaryResultView({
      result: state.result,
      view: state.resultMode
    });
    var output = byId("result-output");
    if (presented.presentation === "source") {
      setPlainResult(presented.sourceText || "");
      return;
    }
    output.classList.remove("plain-output");
    output.classList.add("markdown-output");
    output.innerHTML = presented.html || "";
  }

  function createTextElement(tagName, className, text) {
    var node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    node.textContent = text || "";
    return node;
  }

  function appendDocumentField(parent, label, value) {
    var row;
    var strong;
    if (!safeText(value)) {
      return;
    }
    row = document.createElement("div");
    row.className = "document-slide-field";
    strong = createTextElement("strong", "", label + "：");
    row.appendChild(strong);
    row.appendChild(document.createTextNode(value));
    parent.appendChild(row);
  }

  function hasStructuredDocumentResult(result) {
    return Boolean(
      result &&
      !result.parseFallbackReason &&
      (result.deckTitle || result.documentSummary || result.globalStyleAdvice || (result.slides || []).length)
    );
  }

  function renderDocumentPreview() {
    var result = state.result || {};
    var output = byId("result-output");
    var header;
    var slidesContainer;
    if (!hasStructuredDocumentResult(result)) {
      if (!(result.plainText || result.rawAnswer)) {
        setPlainResult("模型后台未返回可显示的文档总结结果。");
        return;
      }
      applyPptSummaryResultView();
      return;
    }
    output.classList.remove("plain-output");
    output.classList.remove("markdown-output");
    output.innerHTML = "";
    header = document.createElement("section");
    header.className = "document-summary-header";
    header.appendChild(createTextElement("h3", "", result.deckTitle || "文档总结方案"));
    if (result.documentSummary) {
      appendDocumentField(header, "文档摘要", result.documentSummary);
    }
    if (result.globalStyleAdvice) {
      appendDocumentField(header, "全局风格建议", result.globalStyleAdvice);
    }
    header.appendChild(createTextElement(
      "p",
      "document-summary-meta",
      "共 " + (result.slides || []).length + " 页" +
        (result.recommendedSlideCount ? " ｜ 建议页数 " + result.recommendedSlideCount : "")
    ));
    output.appendChild(header);

    slidesContainer = document.createElement("div");
    slidesContainer.className = "document-slides";
    (result.slides || []).forEach(function (slide, position) {
      var article = document.createElement("article");
      var head = document.createElement("div");
      var titleWrap = document.createElement("div");
      var list;
      var actions;
      article.className = "document-slide";
      head.className = "document-slide-head";
      titleWrap.className = "document-slide-title";
      head.appendChild(createTextElement("span", "document-slide-index", "第 " + slide.index + " 页"));
      titleWrap.appendChild(createTextElement("h3", "", slide.title || "未命名页面"));
      if (slide.subtitle) {
        titleWrap.appendChild(createTextElement("p", "document-slide-subtitle", slide.subtitle));
      }
      head.appendChild(titleWrap);
      if (slide.role) {
        head.appendChild(createTextElement("span", "document-slide-role", slide.role));
      }
      article.appendChild(head);
      if (slide.bullets && slide.bullets.length) {
        list = document.createElement("ul");
        slide.bullets.forEach(function (bullet) {
          list.appendChild(createTextElement("li", "", bullet));
        });
        article.appendChild(list);
      }
      appendDocumentField(article, "结论", slide.conclusion);
      appendDocumentField(article, "版式建议", slide.layoutSuggestion);
      appendDocumentField(article, "视觉建议", slide.visualSuggestion);
      actions = document.createElement("div");
      actions.className = "document-slide-actions";
      [
        { action: "title", label: "复制标题" },
        { action: "body", label: "复制正文" },
        { action: "page", label: "复制本页" }
      ].forEach(function (definition) {
        var button = createTextElement("button", "ghost-action", definition.label);
        button.type = "button";
        button.setAttribute("data-document-copy", definition.action);
        button.setAttribute("data-slide-position", String(position));
        button.setAttribute("title", definition.label);
        button.setAttribute("aria-label", definition.label + "，第 " + slide.index + " 页");
        actions.appendChild(button);
      });
      article.appendChild(actions);
      slidesContainer.appendChild(article);
    });
    output.appendChild(slidesContainer);
  }

  function updateCopyButtons(rawOnly) {
    var documentMode = Boolean(state.result && state.result.resultType === "document");
    var documentText;
    byId("slide-copy-toolbar").hidden = documentMode;
    byId("document-copy-toolbar").hidden = !documentMode;
    if (documentMode) {
      documentText = helpers.buildPptDocumentPlainText(state.result);
      byId("btn-copy-outline").disabled = !hasStructuredDocumentResult(state.result);
      byId("btn-copy-document-result").disabled = !safeText(documentText);
      return;
    }
    ["btn-copy-title", "btn-copy-bullets", "btn-copy-conclusion"].forEach(function (id) {
      byId(id).disabled = !state.result || rawOnly;
    });
    byId("btn-copy-result").disabled = !state.result;
  }

  function renderResult(result) {
    if (result && result.resultType === "document") {
      state.result = helpers.normalizePptDocumentResult(result);
    } else {
      state.result = result || {};
    }
    state.resultMode = "preview";
    byId("result-view-switch").hidden = false;
    if (state.result.resultType === "document" && hasStructuredDocumentResult(state.result)) {
      renderDocumentPreview();
      updateCopyButtons(false);
    } else {
      applyPptSummaryResultView();
      updateCopyButtons(state.result.resultType === "document" || !(
        state.result.suggestedTitle ||
        (state.result.bullets && state.result.bullets.length) ||
        state.result.conclusion
      ));
    }
    updateViewButtons();
  }

  function updateViewButtons() {
    ["preview", "plain"].forEach(function (mode) {
      var button = byId(mode === "preview" ? "btn-result-preview" : "btn-result-plain");
      var active = state.resultMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function setResultMode(mode) {
    if (!state.result) {
      return;
    }
    state.resultMode = mode === "plain" ? "plain" : "preview";
    if (state.result.resultType === "document" && hasStructuredDocumentResult(state.result)) {
      if (state.resultMode === "plain") {
        setPlainResult(helpers.buildPptDocumentPlainText(state.result));
      } else {
        renderDocumentPreview();
      }
    } else {
      applyPptSummaryResultView();
    }
    updateViewButtons();
  }

  function setSourceMode(mode) {
    var documentMode = mode === "document";
    if (state.busy) {
      return;
    }
    state.sourceMode = documentMode ? "document" : "slide";
    byId("ppt-source-slide").classList.toggle("active", !documentMode);
    byId("ppt-source-document").classList.toggle("active", documentMode);
    byId("ppt-source-slide").setAttribute("aria-selected", documentMode ? "false" : "true");
    byId("ppt-source-document").setAttribute("aria-selected", documentMode ? "true" : "false");
    byId("slide-summary-controls").hidden = documentMode;
    byId("document-summary-controls").hidden = !documentMode;
    byId("ppt-instruction-label").textContent = documentMode ? "总结要求" : "补充要求";
    byId("btn-run-primary").textContent = documentMode ? "生成文档方案" : "生成本页总结";
  }

  function formatFileSize(size) {
    if (size >= 1024 * 1024) {
      return (size / (1024 * 1024)).toFixed(1) + " MB";
    }
    return Math.max(1, Math.ceil(size / 1024)) + " KB";
  }

  function handleDocumentFileChange(event) {
    var file = event.target.files && event.target.files[0];
    var validation;
    if (!file) {
      state.selectedDocument = null;
      byId("ppt-document-file-summary").textContent = "尚未选择文件";
      return;
    }
    validation = helpers.validatePptDocumentFile(file);
    if (!validation.valid) {
      state.selectedDocument = null;
      event.target.value = "";
      byId("ppt-document-file-summary").textContent = validation.message;
      setStatus(validation.message);
      return;
    }
    state.selectedDocument = file;
    byId("ppt-document-file-summary").textContent =
      file.name + " ｜ " + formatFileSize(file.size) + " ｜ 已通过本地校验";
    setStatus("文档已选择，可以开始总结。");
  }

  function readFileAsBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        var value = safeText(reader.result);
        resolve(value.indexOf(",") >= 0 ? value.split(",").pop() : value);
      };
      reader.onerror = function () {
        reject(new Error("读取文件失败，请重新选择文件。"));
      };
      reader.readAsDataURL(file);
    });
  }

  function isFatalPollError(error) {
    return error && (
      error.adapterCode === "PPT_SLIDE_JOB_NOT_FOUND" ||
      error.adapterCode === "PPT_SLIDE_JOB_INTERRUPTED" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "PPT_SLIDE_JOB_CAPACITY" ||
      error.adapterCode === "PPT_DOCUMENT_FILE_REQUIRED" ||
      error.adapterCode === "PPT_DOCUMENT_FILE_EXPIRED"
    );
  }

  function schedulePoll(jobId, delay) {
    setTimeout(function () {
      pollPptSlideJob(jobId);
    }, delay);
  }

  function finishJob(jobId, result) {
    clearActiveJob(jobId);
    state.jobId = "";
    state.jobSourceMode = "";
    state.resumeExpected = false;
    setPptJobActionVisibility(null);
    setRunDisabled(false);
    renderResult(result || {});
    setStatus(result && result.resultType === "document" ? "文档总结已完成。" : "当前页总结已完成。");
  }

  function failJob(jobId, message, statusMessage) {
    var failureMessage = safeText(message) || "后台任务执行失败。";
    clearActiveJob(jobId);
    state.jobId = "";
    state.jobSourceMode = "";
    state.resumeExpected = false;
    setPptJobActionVisibility(null);
    setRunDisabled(false);
    setStatus((statusMessage || "总结失败") + "：" + failureMessage);
    if (!state.result) {
      setPlainResult(failureMessage);
    }
  }

  function pollPptSlideJob(jobId) {
    if (!jobId || state.jobId !== jobId) {
      return;
    }
    request(
      "/ppt/slide-assistant/jobs/" + encodeURIComponent(jobId) +
        (state.resumeExpected ? "?resume=1" : ""),
      null,
      { timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS }
    ).then(function (body) {
      var job = body.data || {};
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors = 0;
      saveActiveJob({
        jobId: jobId,
        traceId: body.traceId || job.traceId || "",
        startedAt: state.startedAt,
        sourceMode: state.jobSourceMode || state.sourceMode,
        stage: "job"
      });
      if (job.status === "completed") {
        finishJob(jobId, job.result || {});
        return;
      }
      if (job.status === "failed") {
        failJob(jobId, job.error && job.error.message, "总结失败");
        return;
      }
      if (job.status === "cancelled") {
        failJob(jobId, "任务已取消。", "智能总结已取消");
        return;
      }
      var progress = helpers.describePptJobProgress(
        job,
        state.jobSourceMode || state.sourceMode,
        jobId
      );
      setStatus(progress.status);
      setPptJobActionVisibility(job);
      showProgressText(progress.detail);
      schedulePoll(jobId, PPT_SLIDE_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed = Date.now() - (state.startedAt || Date.now());
      var within;
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors += 1;
      if (error && error.adapterCode === "PPT_SLIDE_JOB_INTERRUPTED") {
        clearActiveJob(jobId);
        state.jobId = "";
        state.jobSourceMode = "";
        state.resumeExpected = false;
        setRunDisabled(false);
        setPptJobActionVisibility(null);
        setInterruptedRetryVisible(true);
        setStatus("adapter 已重启，原智能总结任务已中断，请重新提交。");
        setPlainResult("adapter 已重启，原智能总结任务无法恢复，请使用“重新提交总结”。\n任务编号：" + jobId);
        return;
      }
      if (isFatalPollError(error)) {
        failJob(jobId, error.message, "状态查询失败");
        return;
      }
      within = state.pollErrors <= PPT_SLIDE_POLL_MAX_ERRORS && elapsed <= PPT_SLIDE_POLL_MAX_WAIT_MS;
      saveActiveJob({
        jobId: jobId,
        startedAt: state.startedAt,
        sourceMode: state.jobSourceMode || state.sourceMode,
        stage: "job"
      });
      setStatus(within
        ? "状态查询暂时未连接本地 adapter，继续等待模型后台..."
        : "连接中断，正在低频恢复查询...");
      showProgressText("任务编号已保留，不会重复提交。\n最近错误：" + error.message);
      schedulePoll(
        jobId,
        within ? PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS : PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS
      );
    });
  }

  function submitPptSlideJob(payload) {
    var clientJobId = payload.clientJobId;
    state.jobSourceMode = payload.sourceMode || "slide";
    state.jobId = clientJobId;
    state.startedAt = Date.now();
    state.pollErrors = 0;
    state.resumeExpected = true;
    setInterruptedRetryVisible(false);
    setPptJobActionVisibility(null);
    saveActiveJob({
      jobId: clientJobId,
      startedAt: state.startedAt,
      sourceMode: state.jobSourceMode,
      stage: "job"
    });
    setStatus(payload.sourceMode === "document" ? "正在提交文档总结任务..." : "正在提交当前页总结任务...");
    request(
      "/ppt/slide-assistant/jobs",
      payload,
      { timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS }
    ).then(function (body) {
      var job = body.data || {};
      var jobId = job.jobId || clientJobId;
      if (state.jobId !== clientJobId) {
        return;
      }
      state.jobId = jobId;
      saveActiveJob({
        jobId: jobId,
        traceId: body.traceId || "",
        startedAt: state.startedAt,
        sourceMode: state.jobSourceMode,
        stage: "job"
      });
      if (job.status === "completed") {
        finishJob(jobId, job.result || {});
        return;
      }
      var progress = helpers.describePptJobProgress(job, state.jobSourceMode, jobId);
      setStatus(progress.status);
      setPptJobActionVisibility(job);
      showProgressText(progress.detail);
      pollPptSlideJob(jobId);
    }).catch(function (error) {
      if (isFatalPollError(error)) {
        failJob(clientJobId, error.message, "提交失败");
        return;
      }
      setStatus("提交响应未确认，正在按任务编号恢复查询...");
      pollPptSlideJob(clientJobId);
    });
  }

  function runCurrentSlideSummary() {
    setRunDisabled(true);
    setStatus("正在读取当前幻灯片...");
    showProgressText("正在读取当前幻灯片，请稍候。");
    setTimeout(function () {
      var payload;
      var instruction;
      var bodyCount;
      try {
        payload = helpers.extractPresentationSlide(getWppApplication(), PPT_EXTRACTION_LIMITS);
        instruction = safeText(byId("ppt-slide-instruction").value);
        bodyCount = (payload.slide.textBlocks || []).join("").replace(/\s/g, "").length;
        setSummary(payload);
        if (bodyCount < 20 && !instruction) {
          setRunDisabled(false);
          setStatus("请填写本页主题或生成要求。");
          if (!state.result) {
            setPlainResult("当前页正文内容不足，请填写本页主题或生成要求。");
          }
          return;
        }
        payload.sourceMode = "slide";
        payload.userInstruction = instruction.slice(0, 1000);
        payload.clientJobId = buildPptSlideClientJobId("slide");
        submitPptSlideJob(payload);
      } catch (error) {
        setRunDisabled(false);
        setStatus("读取失败");
        if (!state.result) {
          setPlainResult("读取当前幻灯片失败：" + error.message);
        }
      }
    }, 0);
  }

  function runDocumentSummary() {
    var file = state.selectedDocument;
    var validation = helpers.validatePptDocumentFile(file);
    var instruction = safeText(byId("ppt-slide-instruction").value);
    var count = Number(byId("ppt-slide-count").value);
    var clientJobId;
    if (!validation.valid) {
      setStatus(validation.message);
      byId("ppt-document-file-summary").textContent = validation.message;
      return;
    }
    if (instruction.length > 1000) {
      setStatus("总结要求不能超过 1000 个字符。");
      return;
    }
    if (!PPT_DOCUMENT_SLIDE_COUNTS[count]) {
      count = 10;
      byId("ppt-slide-count").value = "10";
    }
    clientJobId = buildPptSlideClientJobId("document");
    setRunDisabled(true);
    saveActiveJob({
      jobId: clientJobId,
      sourceMode: "document",
      stage: "uploading",
      startedAt: Date.now()
    });
    setStatus("正在读取文档...");
    showProgressText("正在读取文档并准备上传，请稍候。");
    readFileAsBase64(file).then(function (contentBase64) {
      setStatus("正在上传文档到本地 adapter...");
      return request("/ppt/document-files", {
        fileName: file.name,
        mimeType: validation.mimeType,
        sizeBytes: file.size,
        contentBase64: contentBase64
      }, { timeoutMs: 60000 });
    }).then(function (body) {
      var upload = body.data || {};
      if (!upload.fileToken) {
        throw new Error("本地 adapter 未返回可用的文件凭证。");
      }
      saveActiveJob({
        jobId: clientJobId,
        sourceMode: "document",
        stage: "uploaded",
        startedAt: Date.now(),
        fileToken: upload.fileToken,
        requestedSlideCount: count,
        userInstruction: instruction
      });
      submitPptSlideJob({
        presentationId: "active-presentation",
        scene: "ppt",
        sourceMode: "document",
        fileToken: upload.fileToken,
        requestedSlideCount: count,
        userInstruction: instruction,
        clientJobId: clientJobId
      });
    }).catch(function (error) {
      if (state.jobId) {
        return;
      }
      clearActiveJob(clientJobId);
      setRunDisabled(false);
      setStatus("文档上传失败：" + error.message);
      if (!state.result) {
        setPlainResult("文档上传失败：" + error.message);
      }
    });
  }

  function runPptSlideAssistant() {
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    if (state.workflowProfileMutationBusy) {
      setStatus("模型配置正在更新，请稍后再运行智能总结。");
      return;
    }
    setInterruptedRetryVisible(false);
    if (state.jobId) {
      setStatus("已有智能总结任务正在运行，请等待当前任务完成。");
      return;
    }
    if (state.sourceMode === "document") {
      runDocumentSummary();
    } else {
      runCurrentSlideSummary();
    }
  }

  function setStructureJobActionVisibility(job) {
    var cancelButton = byId("btn-cancel-structure-review-job");
    cancelButton.hidden = !(job && job.status === "queued" && job.canCancel);
    cancelButton.disabled = false;
  }

  function appendStructureList(parent, title, items, formatter, ordered) {
    var values = Array.isArray(items) ? items : [];
    var section;
    var list;
    if (!values.length) {
      return;
    }
    section = document.createElement("section");
    section.className = "structure-review-section";
    section.appendChild(createTextElement("h3", "", title));
    list = document.createElement(ordered ? "ol" : "ul");
    values.forEach(function (item, index) {
      list.appendChild(createTextElement("li", "", formatter(item || {}, index)));
    });
    section.appendChild(list);
    parent.appendChild(section);
  }

  function appendPresentedHtml(parent, html) {
    var holder;
    var node;
    if (!html) {
      return;
    }
    holder = document.createElement("div");
    holder.innerHTML = html;
    node = holder.firstChild;
    while (node) {
      parent.appendChild(node);
      node = holder.firstChild;
    }
  }

  function renderStructureResult(result) {
    var output = byId("structure-result-output");
    var data = result || {};
    var range = data.reviewedRange || {};
    var view = helpers.presentPptStructureReviewResultView
      ? helpers.presentPptStructureReviewResultView({ result: data })
      : null;
    state.structureResult = data;
    state.structureResultView = view;
    output.innerHTML = "";
    output.appendChild(createTextElement(
      "p",
      "document-summary-meta",
      helpers.formatPptStructureRange(range)
    ));
    appendPresentedHtml(output, view && view.listHtml);
    if (data.rawAnswer) {
      output.appendChild(createTextElement(
        "div",
        "structure-review-raw",
        data.rawAnswer
      ));
    } else {
      if (data.overallStoryline) {
        appendStructureList(output, "整体主线", [data.overallStoryline], function (item) {
          return safeText(item);
        }, false);
      }
      appendStructureList(output, "推断章节", data.inferredChapters, function (item) {
        var rangeText = item.startSlide && item.endSlide
          ? "（第 " + item.startSlide + "-" + item.endSlide + " 页）"
          : "";
        return safeText(item.title) + rangeText;
      }, true);
      appendStructureList(output, "高优先级问题", data.highPriorityIssues, function (item) {
        return safeText(item.message);
      }, false);
      appendStructureList(output, "一般建议", data.generalSuggestions, function (item) {
        return safeText(item.message);
      }, false);
      if (view && view.recommendationHtml) {
        appendPresentedHtml(output, view.recommendationHtml);
      } else if (!view) {
        appendStructureList(output, "逐页调整意见", data.slideRecommendations, function (item) {
          return "第 " + (item.slideNumber || "-") + " 页：" + safeText(item.suggestion);
        }, false);
      }
      appendStructureList(output, "推荐目录", data.recommendedOutline, function (item) {
        return safeText(item.title);
      }, true);
    }
    byId("btn-copy-review-conclusion").disabled = !safeText(
      view && view.copyConclusionText || data.reviewConclusion || data.plainText
    );
    byId("btn-copy-recommended-outline").disabled = !safeText(
      view && view.copyOutlineText || data.outlineText
    );
  }

  function describeStructureProgress(job, jobId) {
    var phase = safeText(job && job.phase) || "provider_processing";
    var status = "模型后台正在审查 PPT 结构...";
    if (phase === "queued") {
      status = "结构审查任务正在排队...";
    } else if (phase === "preparing") {
      status = "正在准备结构审查任务...";
    } else if (phase === "parsing") {
      status = "正在合并本地检查与模型审查结果...";
    }
    return {
      status: status,
      detail: [
        job && job.queuePosition ? "队列位置：第 " + job.queuePosition + " 位" : "任务已进入共享长任务队列。",
        "已等待：" + (Number(job && job.elapsedSeconds) || 0) + " 秒",
        "任务编号：" + jobId
      ].join("\n")
    };
  }

  function finishStructureJob(jobId, result) {
    clearStructureActiveJob(jobId);
    state.jobId = "";
    state.resumeExpected = false;
    setStructureJobActionVisibility(null);
    setRunDisabled(false);
    renderStructureResult(result || {});
    setStatus("结构审查已完成。");
  }

  function failStructureJob(jobId, message, statusMessage) {
    var failureMessage = safeText(message) || "结构审查后台任务执行失败。";
    clearStructureActiveJob(jobId);
    state.jobId = "";
    state.resumeExpected = false;
    setStructureJobActionVisibility(null);
    setRunDisabled(false);
    setStatus((statusMessage || "结构审查失败") + "：" + failureMessage);
    if (!state.structureResult) {
      byId("structure-result-output").textContent = failureMessage;
    }
  }

  function isFatalStructurePollError(error) {
    return error && (
      error.adapterCode === "PPT_STRUCTURE_JOB_NOT_FOUND" ||
      error.adapterCode === "PPT_STRUCTURE_JOB_INTERRUPTED" ||
      error.adapterCode === "PPT_STRUCTURE_RANGE_INVALID" ||
      error.adapterCode === "PPT_STRUCTURE_RANGE_TOO_LARGE" ||
      error.adapterCode === "PPT_STRUCTURE_SLIDES_INCOMPLETE" ||
      error.adapterCode === "PPT_STRUCTURE_AUTH_SNAPSHOT_FAILED" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL"
    );
  }

  function pollStructureReviewJob(jobId) {
    if (!jobId || state.jobId !== jobId || state.taskMode !== "pptStructureReview") {
      return;
    }
    request(
      "/ppt/structure-review/jobs/" + encodeURIComponent(jobId) +
        (state.resumeExpected ? "?resume=1" : ""),
      null,
      { timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS }
    ).then(function (body) {
      var job = body.data || {};
      var progress;
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors = 0;
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt });
      if (job.status === "completed") {
        finishStructureJob(jobId, job.result || {});
        return;
      }
      if (job.status === "failed") {
        failStructureJob(jobId, job.error && job.error.message, "结构审查失败");
        return;
      }
      if (job.status === "cancelled") {
        failStructureJob(jobId, "排队中的结构审查任务已取消。", "结构审查已取消");
        return;
      }
      progress = describeStructureProgress(job, jobId);
      setStatus(progress.status);
      setStructureJobActionVisibility(job);
      byId("structure-result-output").textContent = progress.detail;
      setTimeout(function () { pollStructureReviewJob(jobId); }, PPT_SLIDE_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed = Date.now() - (state.startedAt || Date.now());
      var within;
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors += 1;
      if (error && error.adapterCode === "PPT_STRUCTURE_JOB_INTERRUPTED") {
        clearStructureActiveJob(jobId);
        state.jobId = "";
        state.resumeExpected = false;
        setRunDisabled(false);
        byId("btn-resubmit-structure-review").hidden = false;
        setStatus("adapter 已重启，原结构审查任务已中断，请重新提交。");
        byId("structure-result-output").textContent = "任务编号：" + jobId;
        return;
      }
      if (isFatalStructurePollError(error)) {
        failStructureJob(jobId, error.message, "状态查询失败");
        return;
      }
      within = state.pollErrors <= PPT_SLIDE_POLL_MAX_ERRORS && elapsed <= PPT_SLIDE_POLL_MAX_WAIT_MS;
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt });
      setStatus(within
        ? "状态查询暂时未连接本地 adapter，继续等待模型后台..."
        : "连接中断，正在低频恢复查询...");
      setTimeout(
        function () { pollStructureReviewJob(jobId); },
        within ? PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS : PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS
      );
    });
  }

  function submitStructureReviewJob(payload) {
    var clientJobId = payload.clientJobId;
    state.jobId = clientJobId;
    state.startedAt = Date.now();
    state.pollErrors = 0;
    state.resumeExpected = true;
    byId("btn-resubmit-structure-review").hidden = true;
    saveStructureActiveJob({ jobId: clientJobId, startedAt: state.startedAt });
    setStatus("正在提交结构审查任务...");
    request("/ppt/structure-review/jobs", payload, {
      timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      var jobId = job.jobId || clientJobId;
      var progress;
      if (state.jobId !== clientJobId) {
        return;
      }
      state.jobId = jobId;
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt });
      if (job.status === "completed") {
        finishStructureJob(jobId, job.result || {});
        return;
      }
      progress = describeStructureProgress(job, jobId);
      setStatus(progress.status);
      setStructureJobActionVisibility(job);
      byId("structure-result-output").textContent = progress.detail;
      pollStructureReviewJob(jobId);
    }).catch(function (error) {
      if (isFatalStructurePollError(error)) {
        failStructureJob(clientJobId, error.message, "提交失败");
        return;
      }
      setStatus("提交响应未确认，正在按任务编号恢复查询...");
      pollStructureReviewJob(clientJobId);
    });
  }

  function runPptStructureReview() {
    var startSlide;
    var endSlide;
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    if (state.workflowProfileMutationBusy) {
      setStatus("模型配置正在更新，请稍后再运行结构审查。");
      return;
    }
    if (state.jobId) {
      setStatus("已有结构审查任务正在运行，请等待当前任务完成。");
      return;
    }
    startSlide = safeText(byId("ppt-structure-start-slide").value);
    endSlide = safeText(byId("ppt-structure-end-slide").value);
    setRunDisabled(true);
    setStatus("正在只读提取 PPT 页面结构...");
    byId("structure-result-output").textContent = "正在读取页码、主标题和可选副标题。";
    setTimeout(function () {
      var payload;
      var titledCount;
      try {
        payload = helpers.extractPresentationStructure(
          getWppApplication(),
          startSlide,
          endSlide,
          {
            maxSlides: PPT_STRUCTURE_MAX_SLIDES,
            maxTitleLength: 200,
            maxSubtitleLength: 300,
            maxFallbackLength: PPT_STRUCTURE_MAX_FALLBACK_CHARS,
            maxFallbackSlides: PPT_STRUCTURE_MAX_FALLBACK_SLIDES
          }
        );
        titledCount = payload.slides.filter(function (slide) { return Boolean(slide.title); }).length;
        byId("ppt-structure-end-slide").value = String(payload.scope.endSlide);
        byId("ppt-structure-summary").textContent =
          "将审查第 " + payload.scope.startSlide + "-" + payload.scope.endSlide + " 页" +
          " ｜ 已识别主标题 " + titledCount + "/" + payload.slides.length + " 页" +
          " ｜ 演示文稿共 " + payload.scope.totalSlides + " 页";
        payload.clientJobId = buildPptSlideClientJobId("structure");
        submitStructureReviewJob(payload);
      } catch (error) {
        setRunDisabled(false);
        setStatus("读取失败：" + error.message);
        byId("structure-result-output").textContent = error.message;
      }
    }, 0);
  }

  function cancelQueuedStructureReviewJob() {
    var jobId = state.jobId;
    var button = byId("btn-cancel-structure-review-job");
    if (!jobId) {
      return;
    }
    button.disabled = true;
    request("/ppt/structure-review/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (state.jobId === jobId && (body.data || {}).status === "cancelled") {
        failStructureJob(jobId, "排队中的结构审查任务已取消，未调用模型后台。", "结构审查已取消");
      }
    }).catch(function (error) {
      button.removeAttribute("disabled");
      setStatus("取消排队任务失败：" + error.message);
    });
  }

  function copyText(text, successMessage, feedback) {
    var value = safeText(text);
    var report = typeof feedback === "function" ? feedback : setStatus;
    if (!value) {
      report("暂无可复制的内容。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value).then(function () {
        report(successMessage);
      }).catch(function () {
        copyTextFallback(value, successMessage, report);
      });
    }
    copyTextFallback(value, successMessage, report);
  }

  function copyTextFallback(value, message, feedback) {
    var area = document.createElement("textarea");
    var report = typeof feedback === "function" ? feedback : setStatus;
    area.value = value;
    area.setAttribute("readonly", "readonly");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      report(message);
    } catch (error) {
      report("复制失败，请手动选择结果文本。");
    }
    document.body.removeChild(area);
  }

  function buildDocumentSlideBodyText(slide) {
    var sections = [];
    if (slide.bullets && slide.bullets.length) {
      sections.push(slide.bullets.map(function (item, index) {
        return (index + 1) + ". " + item;
      }).join("\n"));
    }
    if (slide.conclusion) {
      sections.push("结论：" + slide.conclusion);
    }
    return sections.join("\n\n");
  }

  function handleDocumentResultCopy(event) {
    var button = event.target;
    var action = button && button.getAttribute("data-document-copy");
    var position;
    var slide;
    if (!action || !state.result || state.result.resultType !== "document") {
      return;
    }
    position = Number(button.getAttribute("data-slide-position"));
    slide = state.result.slides && state.result.slides[position];
    if (!slide) {
      return;
    }
    if (action === "title") {
      copyText(slide.title, "第 " + slide.index + " 页标题已复制。");
    } else if (action === "body") {
      copyText(buildDocumentSlideBodyText(slide), "第 " + slide.index + " 页正文已复制。");
    } else {
      copyText(helpers.buildPptDocumentSlidePlainText(slide), "第 " + slide.index + " 页方案已复制。");
    }
  }

  function activeProfileName() {
    var found = (state.profiles.profiles || []).filter(function (item) {
      return item.id === state.profiles.activeProfileId;
    })[0];
    return found ? found.name : "尚未配置";
  }

  function workflowProfileOptionState(profile) {
    if (helpers.workflowProfileOptionState) {
      return helpers.workflowProfileOptionState(profile, state.profiles.activeProfileId);
    }
    return {
      id: safeText(profile && profile.id),
      label: safeText(profile && profile.name || "未命名配置") + " · " +
        (profile && profile.accessMethod === "direct_model" ? "模型直连" : "工作流平台"),
      active: Boolean(profile && profile.id === state.profiles.activeProfileId),
      disabled: !Boolean(profile && profile.complete)
    };
  }

  function validateWorkflowProfileDraft(draft, mode) {
    if (helpers.validateWorkflowProfileDraft) {
      return helpers.validateWorkflowProfileDraft(draft, mode);
    }
    if (!safeText(draft.name)) {
      return { ok: false, field: "name", message: "请输入模型配置名称。" };
    }
    return {
      ok: true,
      name: safeText(draft.name),
      note: safeText(draft.note),
      apiKey: safeText(draft.apiKey)
    };
  }

  function shouldActivateNewWorkflowProfile(profileCount, requested) {
    if (helpers.shouldActivateNewWorkflowProfile) {
      return helpers.shouldActivateNewWorkflowProfile(profileCount, requested);
    }
    return Number(profileCount || 0) === 0 || Boolean(requested);
  }

  function profileById(profileId) {
    return (state.profiles.profiles || []).filter(function (profile) {
      return profile.id === profileId;
    })[0] || null;
  }

  function escaped(value) {
    if (helpers.escapeHtml) {
      return helpers.escapeHtml(value);
    }
    return String(value === null || typeof value === "undefined" ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setProviderBaseUrl(baseUrl) {
    var summary = byId("provider-summary-url");
    state.providerBaseUrl = safeText(baseUrl);
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    if (!state.providerUrlEditorOpen && byId("provider-base-url").value !== state.providerBaseUrl) {
      byId("provider-base-url").value = state.providerBaseUrl;
    }
  }

  function renderModelInterfaceState(detectable) {
    var profilesByTask = {};
    var result;
    var badge = byId("provider-readiness-badge");
    var summary = byId("provider-summary-url");
    TASK_API_KEY_DEFS.forEach(function (definition) {
      profilesByTask[definition.taskType] = state.profilesByTask[definition.taskType] || {
        taskType: definition.taskType,
        activeProfileId: "",
        profileCount: 0,
        profiles: []
      };
    });
    result = helpers.deriveModelInterfaceState({
      detectable: detectable,
      providerBaseUrl: state.providerBaseUrl,
      taskTypes: TASK_API_KEY_DEFS.map(function (definition) {
        return definition.taskType;
      }),
      profilesByTask: profilesByTask
    });
    setNodeClassNameIfChanged(badge, "readiness-badge is-" + result.code);
    setNodeTextIfChanged(badge, result.label);
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    setNodeTextIfChanged(byId("diagnostics-summary"), result.label);
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
        // Older WPS WebViews may not support the options overload.
      }
    }
  }

  function handleWorkflowTaskTabClick(event) {
    var taskType = event.target.getAttribute("data-workflow-task-tab");
    if (!taskType || state.workflowProfileMutationBusy || taskType === state.workflowTaskType) {
      return;
    }
    state.workflowTaskType = taskType;
    state.profiles = { taskType: taskType, activeProfileId: "", profileCount: 0, profiles: [] };
    state.selectedProfileId = "";
    renderWorkflowTaskTabs();
    renderProfileStrip();
    renderProfileManager();
    scrollWorkflowTaskTabIntoView(event.target);
    loadProfiles();
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

  function renderProfileStrip() {
    var select = byId("workflow-profile-select");
    var selectedProfileId = state.selectedProfileId || state.profiles.activeProfileId;
    var availableProfiles = state.profiles.profiles.filter(function (profile) { return profile.complete; });
    var optionModels = [];
    if (!select) {
      return;
    }
    select.setAttribute(
      "aria-label",
      state.workflowTaskType === PPT_STRUCTURE_WORKFLOW_TASK_TYPE
        ? "选择结构审查模型配置"
        : "选择智能总结模型配置"
    );
    if (!availableProfiles.length) {
      optionModels.push({
        value: "",
        text: state.profiles.loadError ? "配置读取失败" : "未配置",
        selected: true,
        disabled: false
      });
    } else {
      availableProfiles.forEach(function (profile) {
        var optionState = workflowProfileOptionState(profile);
        optionModels.push({
          value: optionState.id,
          text: optionState.label,
          disabled: optionState.disabled,
          selected: optionState.id === selectedProfileId
        });
      });
    }
    syncWorkflowProfileSelectOptions(select, optionModels);
    select.disabled = state.busy || state.workflowProfileMutationBusy || !availableProfiles.length;
    setNodeTextIfChanged(byId("workflow-switch-feedback"), "当前配置：" + activeProfileName());
  }

  function renderProfileManager() {
    var manager = byId("workflow-profile-manager");
    var html = [];
    if (!manager) {
      return;
    }
    byId("btn-new-workflow-profile").disabled = state.workflowProfileMutationBusy ||
      Boolean(state.profiles.loadError);
    byId("workflow-profile-count").textContent = state.profiles.loadError
      ? "读取失败"
      : (state.profiles.profiles.length + " 个模型配置");
    if (state.profiles.loadError) {
      html.push('<div class="workflow-load-error"><p class="workflow-profile-error">无法读取模型配置：' +
        escaped(state.profiles.loadError) + '</p><button type="button" class="ghost-action" ' +
        'data-profile-action="retry">重新读取</button></div>');
    }
    if (!state.profiles.profiles.length) {
      html.push('<p class="workflow-empty-state">尚未建立' +
        (state.workflowTaskType === PPT_STRUCTURE_WORKFLOW_TASK_TYPE ? "结构审查" : "智能总结") +
        '模型配置。</p>');
      manager.innerHTML = html.join("");
      return;
    }
    html.push('<div class="workflow-profile-list">');
    state.profiles.profiles.forEach(function (profile) {
      var id = escaped(profile.id);
      var active = profile.id === state.profiles.activeProfileId;
      var status = active ? "当前" : (profile.complete ? "配置完整" : "配置不完整");
      var disabled = state.workflowProfileMutationBusy ? ' disabled' : '';
      html.push('<div class="workflow-profile-list-row" data-profile-id="' + id + '">');
      html.push('<div class="workflow-profile-copy"><div class="workflow-profile-name-line"><strong>' +
        escaped(profile.name || "未命名配置") + '</strong><span class="workflow-profile-state">' +
        status + '</span></div>');
      html.push('<p class="workflow-profile-note">' +
        (profile.accessMethod === "direct_model" ? "模型直连" + (profile.modelName ? " · " + escaped(profile.modelName) : "") : "工作流平台") + '</p>');
      if (profile.note) {
        html.push('<p class="workflow-profile-note">' + escaped(profile.note) + '</p>');
      }
      html.push('</div>');
      html.push('<div class="workflow-profile-actions">');
      html.push('<button type="button" class="ghost-action" data-profile-action="edit" data-profile-id="' + id + '"' + disabled + '>编辑</button>');
      html.push('<button type="button" class="ghost-action" data-profile-action="copy" data-profile-id="' + id + '"' + disabled + '>复制</button>');
      if (!active) {
        html.push('<button type="button" data-profile-action="activate" data-profile-id="' + id + '"' +
          (profile.complete ? disabled : ' disabled title="请先补全模型配置"') + '>设为当前</button>');
      }
      html.push('<button type="button" class="ghost-action danger-action" data-profile-action="delete" data-profile-id="' + id + '"' +
        (active ? ' disabled title="请先切换到其他模型配置"' : disabled) + '>删除</button>');
      html.push('</div></div>');
    });
    html.push('</div>');
    manager.innerHTML = html.join("");
  }

  function loadProfiles(configRefreshRequestId, requestOptions) {
    var requestId = state.profileLoadRequestId + 1;
    var previousProfiles = state.profiles;
    var previousProfilesByTask = state.profilesByTask;
    var previousSelection = state.selectedProfileId;
    state.profileLoadRequestId = requestId;
    return Promise.all(TASK_API_KEY_DEFS.map(function (definition) {
      return request(
        "/provider/model-configurations?taskType=" + encodeURIComponent(definition.taskType),
        null,
        requestOptions
      );
    })).then(function (bodies) {
      var nextProfilesByTask = {};
      if (requestId !== state.profileLoadRequestId ||
          (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
        return { superseded: true };
      }
      TASK_API_KEY_DEFS.forEach(function (definition, index) {
        nextProfilesByTask[definition.taskType] = helpers.normalizeWorkflowProfiles(
          (bodies[index] && bodies[index].data) || {}
        );
      });
      state.profilesByTask = nextProfilesByTask;
      state.profiles = state.profilesByTask[state.workflowTaskType] || {
        taskType: state.workflowTaskType,
        activeProfileId: "",
        profileCount: 0,
        profiles: []
      };
      state.selectedProfileId = state.profiles.activeProfileId;
      renderProfileStrip();
      renderProfileManager();
      renderModelInterfaceState(state.modelInterfaceDetectable);
      return state.profiles;
    }).catch(function (error) {
      var preservedProfiles;
      if (requestId !== state.profileLoadRequestId ||
          (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
        return { superseded: true };
      }
      if (previousProfiles) {
        preservedProfiles = {};
        Object.keys(previousProfiles).forEach(function (key) {
          preservedProfiles[key] = previousProfiles[key];
        });
        preservedProfiles.loadError = describeSettingsError(error);
        state.profiles = preservedProfiles;
        state.profilesByTask = previousProfilesByTask || {};
        state.profilesByTask[state.workflowTaskType] = preservedProfiles;
        state.selectedProfileId = previousSelection;
      } else {
        state.profiles = {
          taskType: state.workflowTaskType,
          activeProfileId: "",
          profileCount: 0,
          profiles: [],
          loadError: describeSettingsError(error)
        };
        state.profilesByTask = previousProfilesByTask || {};
        state.profilesByTask[state.workflowTaskType] = state.profiles;
        state.selectedProfileId = "";
      }
      state.modelInterfaceDetectable = false;
      renderProfileStrip();
      renderProfileManager();
      renderModelInterfaceState(state.modelInterfaceDetectable);
      return { failed: true };
    });
  }

  function updateWorkflowEditorControls() {
    var disabled = state.workflowProfileMutationBusy;
    [
      "btn-back-workflow-editor",
      "workflow-editor-name",
      "workflow-editor-method",
      "workflow-editor-url",
      "workflow-editor-model",
      "workflow-editor-note",
      "workflow-editor-key",
      "workflow-editor-key-confirm",
      "workflow-editor-temperature",
      "workflow-editor-max-output",
      "workflow-editor-context",
      "workflow-editor-activate",
      "btn-toggle-workflow-key",
      "btn-validate-model-configuration",
      "btn-cancel-workflow-editor",
      "btn-save-workflow-editor"
    ].forEach(function (id) {
      if (byId(id)) {
        byId(id).disabled = disabled;
      }
    });
  }

  function setWorkflowProfileMutationBusy(busy) {
    state.workflowProfileMutationBusy = Boolean(busy);
    byId("btn-run-primary").disabled = state.busy || state.workflowProfileMutationBusy;
    byId("btn-run-structure-review").disabled = state.busy || state.workflowProfileMutationBusy;
    renderProfileStrip();
    renderProfileManager();
    renderWorkflowTaskTabs();
    updateWorkflowEditorControls();
    syncSettingsRefreshController();
  }

  function showWorkflowSettingsHome() {
    byId("workflow-settings-home").hidden = false;
    byId("workflow-editor-view").hidden = true;
  }

  function openWorkflowEditor(profileId) {
    var profile = profileById(profileId);
    var editing = Boolean(profile);
    if (!editing && state.profiles.loadError) {
      setStatus("模型配置读取失败，请重新读取后再新建。");
      return;
    }
    state.workflowEditor = {
      open: true,
      mode: editing ? "edit" : "create",
      profileId: editing ? profile.id : "",
      dirty: false,
      originalAccessMethod: editing ? profile.accessMethod : "workflow_platform",
      currentAccessMethod: editing ? profile.accessMethod : "workflow_platform"
    };
    byId("workflow-editor-title").textContent = editing ? "编辑模型配置" : "新建模型配置";
    byId("workflow-editor-name").value = editing ? profile.name : "";
    byId("workflow-editor-note").value = editing ? profile.note : "";
    byId("workflow-editor-method").value = editing ? profile.accessMethod : "workflow_platform";
    byId("workflow-editor-url").value = editing ? profile.serviceBaseUrl : "";
    byId("workflow-editor-model").value = editing ? profile.modelName : "";
    byId("workflow-editor-model-row").hidden = byId("workflow-editor-method").value !== "direct_model";
    byId("workflow-editor-direct-advanced").hidden = byId("workflow-editor-method").value !== "direct_model";
    byId("workflow-editor-temperature").value = editing && profile.temperature !== null ? profile.temperature : "";
    byId("workflow-editor-max-output").value = editing && profile.maxOutputTokens ? profile.maxOutputTokens : "";
    byId("workflow-editor-context").value = editing ? profile.contextWindowTokens : 40000;
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key-confirm").value = "";
    byId("workflow-editor-key").type = "password";
    byId("btn-toggle-workflow-key").textContent = "显示";
    byId("btn-toggle-workflow-key").setAttribute("aria-pressed", "false");
    byId("workflow-editor-key").placeholder = editing ? "输入新 API Key（选填）" : "输入 API Key（可稍后配置）";
    byId("workflow-editor-key-status").textContent = editing
      ? (profile.keyConfigured ? "API Key 已配置" : "API Key 未配置，可保存后继续补充")
      : "API Key 可稍后配置";
    byId("btn-validate-model-configuration").disabled = !editing || !profile.complete;
    byId("model-validation-summary").textContent = editing && profile.lastValidation
      ? profile.lastValidation.message || "已有最近验证记录"
      : "尚未验证";
    byId("workflow-editor-error").textContent = "";
    byId("workflow-editor-activate-row").hidden = editing;
    byId("workflow-editor-activate").checked = editing ? false :
      !state.profiles.loadError && shouldActivateNewWorkflowProfile(state.profiles.profileCount, false);
    byId("workflow-settings-home").hidden = true;
    byId("workflow-editor-view").hidden = false;
    updateWorkflowEditorControls();
    syncSettingsRefreshController();
    byId("workflow-editor-name").focus();
  }

  function closeWorkflowEditor(force) {
    if (!force && state.workflowEditor.dirty && window.confirm &&
        !window.confirm("当前模型配置尚未保存，确认放弃修改并返回吗？")) {
      return false;
    }
    state.workflowEditor = { open: false, mode: "create", profileId: "", dirty: false };
    byId("workflow-editor-key").value = "";
    byId("workflow-editor-key-confirm").value = "";
    byId("workflow-editor-error").textContent = "";
    showWorkflowSettingsHome();
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
    setWorkflowProfileMutationBusy(true);
    setStatus("正在验证模型配置，模型响应较慢时请耐心等待...");
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/validate", {})
      .then(function (body) {
        var duration = Number(body && body.data && body.data.durationMs || 0);
        return loadProfiles().then(function () {
          var profile = profileById(profileId);
          setWorkflowProfileMutationBusy(false);
          state.workflowEditor.dirty = false;
          byId("model-validation-summary").textContent = "验证成功，用时 " + (duration / 1000).toFixed(1) + " 秒";
          byId("btn-validate-model-configuration").disabled = !profile || !profile.complete;
          setStatus("模型配置验证成功。");
        });
      }).catch(function (error) {
        setWorkflowProfileMutationBusy(false);
        byId("model-validation-summary").textContent = "验证失败：" + describeSettingsError(error);
        setStatus("验证失败：" + describeSettingsError(error));
      });
  }

  function copyModelConfiguration(profileId) {
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/copy", {
      targetTaskType: state.workflowTaskType
    }).then(function () {
      return loadProfiles();
    }).then(function () {
      setWorkflowProfileMutationBusy(false);
      setStatus("模型配置副本已创建，请检查后再启用。");
    }).catch(function (error) {
      setWorkflowProfileMutationBusy(false);
      setStatus("复制模型配置失败：" + describeSettingsError(error));
    });
  }

  function focusWorkflowEditorField(field) {
    var fieldIds = {
      name: "workflow-editor-name",
      note: "workflow-editor-note",
      apiKey: "workflow-editor-key"
    };
    if (fieldIds[field] && byId(fieldIds[field])) {
      byId(fieldIds[field]).focus();
    }
  }

  function finishWorkflowEditorSave(message) {
    state.workflowEditor.dirty = false;
    setWorkflowProfileMutationBusy(false);
    return loadProfiles().then(function () {
      closeWorkflowEditor(true);
      updateWorkflowEditorControls();
      setStatus(message);
    });
  }

  function saveWorkflowEditor() {
    var mode = state.workflowEditor.mode;
    var profileId = state.workflowEditor.profileId;
    var rawDraft = {
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
    var draft = validateWorkflowProfileDraft(rawDraft, mode);
    if (!draft.ok) {
      setStatus(draft.message);
      byId("workflow-editor-error").textContent = draft.message;
      focusWorkflowEditorField(draft.field);
      return;
    }
    if (rawDraft.apiKey !== rawDraft.apiKeyConfirm) {
      byId("workflow-editor-error").textContent = "两次输入的 API Key 不一致。";
      focusWorkflowEditorField("apiKey");
      return;
    }
    var configurationPayload = {
      taskType: state.workflowTaskType,
      name: draft.name,
      note: draft.note,
      accessMethod: rawDraft.accessMethod,
      serviceBaseUrl: rawDraft.serviceBaseUrl,
      modelName: rawDraft.accessMethod === "direct_model" ? rawDraft.modelName : "",
      temperature: rawDraft.accessMethod === "direct_model" && rawDraft.temperature !== "" ? Number(rawDraft.temperature) : null,
      maxOutputTokens: rawDraft.accessMethod === "direct_model" && rawDraft.maxOutputTokens !== "" ? Number(rawDraft.maxOutputTokens) : null,
      contextWindowTokens: rawDraft.accessMethod === "direct_model" ? Number(rawDraft.contextWindowTokens) : 40000
    };
    setWorkflowProfileMutationBusy(true);
    if (mode === "create") {
      request("/provider/model-configurations", configurationPayload).then(function (body) {
        var configuration = body.data.configuration;
        var saveKey = rawDraft.apiKey ? request("/provider/model-configurations/" + encodeURIComponent(configuration.id) + "/api-key", { apiKey: rawDraft.apiKey }) : Promise.resolve();
        return saveKey.then(function () {
          var shouldActivate = !state.profiles.loadError && shouldActivateNewWorkflowProfile(
            state.profiles.profileCount, byId("workflow-editor-activate").checked
          );
          var complete = Boolean(rawDraft.serviceBaseUrl && rawDraft.apiKey &&
            (rawDraft.accessMethod !== "direct_model" || rawDraft.modelName));
          return shouldActivate && complete
            ? request("/provider/model-configurations/" + encodeURIComponent(configuration.id) + "/activate", {})
            : null;
        });
      }).then(function () {
        return finishWorkflowEditorSave("模型配置已创建。");
      }).catch(function (error) {
        setWorkflowProfileMutationBusy(false);
        setStatus("创建模型配置失败：" + error.message);
      });
      return;
    }
    request("/provider/model-configurations/" + encodeURIComponent(profileId), configurationPayload, { method: "PATCH" }).then(function () {
      if (!rawDraft.apiKey) {
        return finishWorkflowEditorSave("模型配置已保存，API Key 保持不变。");
      }
      return request(
        "/provider/model-configurations/" + encodeURIComponent(profileId) + "/api-key",
        { apiKey: rawDraft.apiKey }
      ).then(function () {
        return finishWorkflowEditorSave("模型配置和 API Key 已保存。");
      }).catch(function (error) {
        var message = "模型配置已保存，但 API Key 更换失败；原 Key 保持不变：" + error.message;
        state.workflowEditor.dirty = true;
        setWorkflowProfileMutationBusy(false);
        byId("workflow-editor-error").textContent = message;
        setStatus(message);
        focusWorkflowEditorField("apiKey");
      });
    }).catch(function (error) {
      setWorkflowProfileMutationBusy(false);
      setStatus("保存模型配置失败：" + error.message);
    });
  }

  function activateWorkflowProfile(profileId) {
    var previousProfileId = state.profiles.activeProfileId;
    var profile = profileById(profileId);
    var optionState = profile ? workflowProfileOptionState(profile) : null;
    if (state.busy || state.workflowProfileMutationBusy) {
      state.selectedProfileId = previousProfileId;
      renderProfileStrip();
      return;
    }
    if (!profile || !optionState || optionState.disabled) {
      state.selectedProfileId = previousProfileId;
      renderProfileStrip();
      setStatus("该模型配置不完整，暂时不可切换。");
      return;
    }
    if (profileId === previousProfileId) {
      state.selectedProfileId = previousProfileId;
      renderProfileStrip();
      return;
    }
    state.selectedProfileId = profileId;
    state.profileLoadRequestId += 1;
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/activate", {})
      .then(function () {
        return loadProfiles();
      })
      .then(function () {
        setWorkflowProfileMutationBusy(false);
        byId("workflow-switch-feedback").textContent = "已切换至：" + profile.name;
        setStatus("已切换至：" + profile.name);
      })
      .catch(function (error) {
        state.selectedProfileId = previousProfileId;
        setWorkflowProfileMutationBusy(false);
        byId("workflow-switch-feedback").textContent = "切换失败，当前：" + activeProfileName();
        setStatus("切换模型配置失败：" + error.message);
      });
  }

  function cancelWorkflowProfileActivation() {
    if (state.workflowProfileActivationTimer !== null) {
      window.clearTimeout(state.workflowProfileActivationTimer);
      state.workflowProfileActivationTimer = null;
    }
  }

  function scheduleWorkflowProfileActivation(profileId) {
    cancelWorkflowProfileActivation();
    state.workflowProfileActivationTimer = window.setTimeout(function () {
      state.workflowProfileActivationTimer = null;
      activateWorkflowProfile(profileId);
    }, 0);
  }

  function deleteWorkflowProfile(profileId) {
    var profile = profileById(profileId);
    if (!profile) {
      return;
    }
    if (profile.id === state.profiles.activeProfileId) {
      setStatus("当前模型配置不可删除，请先切换到其他模型配置。");
      return;
    }
    if (window.confirm && !window.confirm(
      "确认删除模型配置“" + profile.name + "”？这将删除" +
        (state.workflowTaskType === PPT_STRUCTURE_WORKFLOW_TASK_TYPE ? "结构审查" : "智能总结") +
        "下的该档案及对应 Key，且无法恢复。"
    )) {
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId), null, { method: "DELETE" })
      .then(function () {
        return loadProfiles();
      })
      .then(function () {
        setWorkflowProfileMutationBusy(false);
        setStatus("模型配置“" + profile.name + "”已删除。");
      })
      .catch(function (error) {
        setWorkflowProfileMutationBusy(false);
        setStatus("删除模型配置失败：" + error.message);
      });
  }

  function handleWorkflowProfileAction(event) {
    var target = event.target;
    var action = target && target.getAttribute("data-profile-action");
    var profileId = target && target.getAttribute("data-profile-id") || "";
    if (!action || state.workflowProfileMutationBusy) {
      return;
    }
    if (action === "retry") {
      loadProfiles();
    } else if (action === "edit") {
      openWorkflowEditor(profileId);
    } else if (action === "copy") {
      copyModelConfiguration(profileId);
    } else if (action === "activate") {
      activateWorkflowProfile(profileId);
    } else if (action === "delete") {
      deleteWorkflowProfile(profileId);
    }
  }

  function renderProviderDiagnostics(items) {
    var debug = (items[0] && items[0].data) || {};
    var status = (items[1] && items[1].data) || {};
    var routes = (items[2] && items[2].data) || {};
    var taskKeys = (items[3] && items[3].data) || {};
    var longTasks = routes.longTaskCoordinator || {};
    var lines = ["最近一次任务诊断", ""];

    lines.push("- 前端版本：" + FRONTEND_BUILD_VERSION);
    lines.push("- 任务类型：" + (debug.taskType || "未记录"));
    lines.push("- traceId：" + (debug.traceId || "未记录"));
    lines.push("- provider 已配置：" + (status.configured ? "是" : "否"));
    lines.push("- 统一 API URL 已配置：" + (routes.providerBaseUrlConfigured ? "是" : "否"));
    lines.push("- 请求路径：" + (debug.url || routes.url || "未进入模型后台请求"));

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
      lines.push("- " + taskType + "：已配置 " + (item.configured ? "是" : "否"));
    });
    return lines.join("\n");
  }

  function refreshDiagnostics() {
    return Promise.all([
      request("/provider/debug-last", null, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
      request("/provider/status", null, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
      request("/provider/route-diagnostics", null, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
      request("/provider/task-api-keys", null, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS })
    ]).then(function (items) {
      state.diagnosticsText = renderProviderDiagnostics(items);
      byId("diagnostics-output").textContent = state.diagnosticsText;
      setSettingsStatus("诊断信息已刷新。");
    }).catch(function (error) {
      byId("diagnostics-output").textContent = "诊断读取失败：" + describeSettingsError(error);
      setSettingsStatus("诊断读取失败：" + describeSettingsError(error));
    });
  }

  function handleDiagnosticsDisclosureToggle(event) {
    if (event.currentTarget.open) {
      refreshDiagnostics();
    }
  }

  function copyDiagnostics() {
    copyText(state.diagnosticsText, "诊断信息已复制。", setSettingsStatus);
  }

  function invalidateSettingsRefresh() {
    state.configRefreshRequestId += 1;
    state.configRefreshQueued = false;
    state.configRefreshQueuedSilent = true;
  }

  function isSettingsRefreshEligible() {
    return Boolean(
      state.currentView === "settings" &&
      document.visibilityState !== "hidden" &&
      !state.workflowEditor.open &&
      !state.providerUrlEditorOpen &&
      !state.workflowProfileMutationBusy
    );
  }

  function syncSettingsRefreshController() {
    if (!state.settingsRefreshController) {
      return;
    }
    if (isSettingsRefreshEligible()) {
      state.settingsRefreshController.start();
    } else if (state.settingsRefreshController.isRunning()) {
      state.settingsRefreshController.stop();
      invalidateSettingsRefresh();
    }
  }

  function refreshSettings(options) {
    var requestId;
    var refreshOperation;
    var refreshPromise;
    var healthConnected = false;
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
        return refreshSettings({ silent: restartSilent });
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
      var healthData = health.data || {};
      var healthState = applyAdapterHealthState(healthData, true);
      healthConnected = true;
      if (healthState.status === "recovery") {
        return null;
      }
      return Promise.all([
        request("/config", null, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
        loadProfiles(requestId, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS })
      ]);
    }).then(function (items) {
      if (!items) {
        return null;
      }
      var profileResult = items[1];
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (profileResult && profileResult.superseded) {
        return null;
      }
      if (!profileResult || profileResult.failed) {
        throw new Error("模型配置读取失败");
      }
      setProviderBaseUrl(items[0].data && items[0].data.providerBaseUrl);
      state.modelInterfaceDetectable = true;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      if (!state.configRefreshActiveSilent) {
        setSettingsStatus(state.adapterHealthStatus === "degraded"
          ? "增强能力降级，核心功能可用。"
          : "就绪");
      }
      return items;
    }).catch(function (error) {
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      if (!healthConnected) {
        applyAdapterHealthState(null, false);
      }
      setSettingsStatus("配置刷新失败：" + describeSettingsError(error));
      return null;
    });

    refreshPromise = refreshOperation.then(releaseRefresh, function (error) {
      if (state.configRefreshRequestId === requestId) {
        state.modelInterfaceDetectable = false;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        if (!healthConnected) {
          applyAdapterHealthState(null, false);
        }
        setSettingsStatus("配置刷新失败：" + describeSettingsError(error));
      }
      return releaseRefresh(null);
    });
    state.configRefreshPromise = refreshPromise;
    return refreshPromise;
  }

  function showProviderUrlEditor() {
    state.providerUrlEditorOpen = true;
    byId("provider-url-editor").hidden = false;
    byId("btn-edit-provider-url").hidden = true;
    byId("provider-base-url").focus();
    syncSettingsRefreshController();
  }

  function hideProviderUrlEditor(resetValue, suppressRefreshSync) {
    state.providerUrlEditorOpen = false;
    if (resetValue) {
      byId("provider-base-url").value = state.providerBaseUrl;
    }
    byId("provider-url-editor").hidden = true;
    byId("btn-edit-provider-url").hidden = false;
    if (suppressRefreshSync !== true) {
      syncSettingsRefreshController();
    }
  }

  function checkHealth() {
    setHealthBadge("badge-warn", "检测中");
    return request("/health", null, { timeoutMs: 5000 }).then(function (health) {
      applyAdapterHealthState(health.data || {}, true);
    }).catch(function () {
      applyAdapterHealthState(null, false);
    });
  }

  function resumeJob() {
    var active;
    if (state.taskMode === "pptStructureReview") {
      resumeStructureReviewJob();
      return;
    }
    if (state.jobId) {
      return;
    }
    active = loadActiveJob();
    if (!active || !active.jobId || state.currentView === "settings") {
      return;
    }
    setSourceMode(active.sourceMode === "document" ? "document" : "slide");
    if (active.stage === "uploading") {
      clearActiveJob(active.jobId);
      setStatus("上次文档上传未确认，请重新选择文件后提交。");
      return;
    }
    if (active.stage === "uploaded" && active.fileToken) {
      setRunDisabled(true);
      submitPptSlideJob({
        presentationId: "active-presentation",
        scene: "ppt",
        sourceMode: "document",
        fileToken: active.fileToken,
        requestedSlideCount: active.requestedSlideCount,
        userInstruction: active.userInstruction || "",
        clientJobId: active.jobId
      });
      return;
    }
    state.jobSourceMode = active.sourceMode === "document" ? "document" : "slide";
    state.jobId = active.jobId;
    state.startedAt = active.startedAt || Date.now();
    state.pollErrors = 0;
    state.resumeExpected = true;
    setInterruptedRetryVisible(false);
    setRunDisabled(true);
    setStatus("正在恢复未完成的智能总结任务...");
    showProgressText("任务编号已恢复，正在继续查询模型后台状态。");
    pollPptSlideJob(active.jobId);
  }

  function resumeStructureReviewJob() {
    var active;
    if (state.jobId || state.currentView === "settings") {
      return;
    }
    active = loadStructureActiveJob();
    if (!active || !active.jobId) {
      return;
    }
    state.jobId = active.jobId;
    state.startedAt = active.startedAt || Date.now();
    state.pollErrors = 0;
    state.resumeExpected = true;
    byId("btn-resubmit-structure-review").hidden = true;
    setRunDisabled(true);
    setStatus("正在恢复未完成的结构审查任务...");
    byId("structure-result-output").textContent =
      "任务编号已恢复，正在继续查询模型后台状态。\n任务编号：" + active.jobId;
    pollStructureReviewJob(active.jobId);
  }

  function cancelQueuedPptSlideJob() {
    var jobId = state.jobId;
    var button = byId("btn-cancel-ppt-slide-job");
    if (!jobId) {
      return;
    }
    button.disabled = true;
    request("/ppt/slide-assistant/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (state.jobId === jobId && (body.data || {}).status === "cancelled") {
        failJob(jobId, "排队中的智能总结任务已取消，未调用模型后台。", "智能总结已取消");
      }
    }).catch(function (error) {
      if (state.jobId === jobId) {
        button.removeAttribute("disabled");
        setStatus("取消排队任务失败：" + error.message);
      }
    });
  }

  function switchView(viewName) {
    var settingsMode = viewName === "settings";
    var returnTitle = homeTaskTitle();
    state.currentView = settingsMode ? "settings" : "home";
    byId("home-view").classList.toggle("active", !settingsMode);
    byId("settings-view").classList.toggle("active", settingsMode);
    document.body.setAttribute("data-task-mode", settingsMode ? "settings" : state.taskMode);
    byId("task-title").textContent = settingsMode ? "设置" : returnTitle;
    byId("btn-open-settings").classList.toggle("is-back", settingsMode);
    byId("btn-open-settings").setAttribute("title", settingsMode ? "返回" + returnTitle : "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回" + returnTitle : "打开设置");
    if (settingsMode) {
      closeWorkflowEditor(true);
      hideProviderUrlEditor(true, true);
      byId("diagnostics-disclosure").open = false;
    } else {
      if (state.workflowTaskType !== homeWorkflowTaskType()) {
        state.workflowTaskType = homeWorkflowTaskType();
        state.profiles = { taskType: state.workflowTaskType, activeProfileId: "", profileCount: 0, profiles: [] };
        state.selectedProfileId = "";
        loadProfiles();
      }
      resumeJob();
    }
    renderWorkflowTaskTabs();
    syncSettingsRefreshController();
  }

  function bindEvents() {
    var workflowHelpButton = byId("workflow-help-button");
    var workflowHelpPopover = byId("workflow-help-popover");
    var workflowHelpHeading = document.querySelector(".workflow-settings-heading");
    byId("btn-open-settings").addEventListener("click", function () {
      if (state.currentView === "settings" && !byId("workflow-editor-view").hidden &&
          !closeWorkflowEditor(false)) {
        return;
      }
      switchView(state.currentView === "settings" ? "home" : "settings");
    });
    byId("ppt-source-slide").addEventListener("click", function () {
      setSourceMode("slide");
    });
    byId("ppt-source-document").addEventListener("click", function () {
      setSourceMode("document");
    });
    byId("ppt-document-file").addEventListener("change", handleDocumentFileChange);
    byId("btn-run-primary").addEventListener("click", runPptSlideAssistant);
    byId("btn-run-structure-review").addEventListener("click", runPptStructureReview);
    byId("btn-cancel-structure-review-job").addEventListener("click", cancelQueuedStructureReviewJob);
    byId("btn-resubmit-structure-review").addEventListener("click", runPptStructureReview);
    byId("btn-cancel-ppt-slide-job").addEventListener("click", cancelQueuedPptSlideJob);
    byId("btn-resubmit-interrupted-job").addEventListener("click", runPptSlideAssistant);
    byId("btn-result-preview").addEventListener("click", function () {
      setResultMode("preview");
    });
    byId("btn-result-plain").addEventListener("click", function () {
      setResultMode("plain");
    });
    byId("btn-copy-title").addEventListener("click", function () {
      copyText(state.result && state.result.suggestedTitle, "标题已复制。");
    });
    byId("btn-copy-bullets").addEventListener("click", function () {
      copyText(state.result && (state.result.bullets || []).map(function (item, index) {
        return (index + 1) + ". " + item;
      }).join("\n"), "要点已复制。");
    });
    byId("btn-copy-conclusion").addEventListener("click", function () {
      copyText(state.result && state.result.conclusion, "结论已复制。");
    });
    byId("btn-copy-result").addEventListener("click", function () {
      copyText(
        state.result && (
          state.result.rawAnswer ||
          state.result.plainText ||
          helpers.buildPptSlidePlainText(state.result)
        ),
        "完整结果已复制。"
      );
    });
    byId("btn-copy-outline").addEventListener("click", function () {
      copyText(helpers.buildPptDocumentOutline(state.result), "文档大纲已复制。");
    });
    byId("btn-copy-document-result").addEventListener("click", function () {
      copyText(helpers.buildPptDocumentPlainText(state.result), "完整方案已复制。");
    });
    byId("btn-copy-review-conclusion").addEventListener("click", function () {
      copyText(
        state.structureResultView && state.structureResultView.copyConclusionText ||
          (state.structureResult && (state.structureResult.reviewConclusion || state.structureResult.plainText)),
        "审查结论已复制。"
      );
    });
    byId("btn-copy-recommended-outline").addEventListener("click", function () {
      copyText(
        state.structureResultView && state.structureResultView.copyOutlineText ||
          (state.structureResult && state.structureResult.outlineText),
        "推荐目录已复制。"
      );
    });
    byId("result-output").addEventListener("click", handleDocumentResultCopy);
    byId("workflow-profile-select").addEventListener("change", function (event) {
      state.selectedProfileId = event.target.value;
      scheduleWorkflowProfileActivation(event.target.value);
    });
    byId("workflow-profile-manager").addEventListener("click", handleWorkflowProfileAction);
    byId("btn-new-workflow-profile").addEventListener("click", function () {
      openWorkflowEditor("");
    });
    byId("btn-back-workflow-editor").addEventListener("click", function () {
      closeWorkflowEditor(false);
    });
    byId("btn-cancel-workflow-editor").addEventListener("click", function () {
      closeWorkflowEditor(false);
    });
    byId("btn-save-workflow-editor").addEventListener("click", saveWorkflowEditor);
    ["workflow-editor-name", "workflow-editor-note", "workflow-editor-url", "workflow-editor-model",
      "workflow-editor-key", "workflow-editor-key-confirm", "workflow-editor-temperature",
      "workflow-editor-max-output", "workflow-editor-context"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        state.workflowEditor.dirty = true;
        byId("workflow-editor-error").textContent = "";
        byId("btn-validate-model-configuration").disabled = true;
      });
    });
    byId("workflow-editor-method").addEventListener("change", handleModelAccessMethodChange);
    byId("btn-validate-model-configuration").addEventListener("click", validateCurrentModelConfiguration);
    byId("workflow-editor-activate").addEventListener("change", function () {
      state.workflowEditor.dirty = true;
    });
    byId("btn-toggle-workflow-key").addEventListener("click", function () {
      var input = byId("workflow-editor-key");
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      byId("btn-toggle-workflow-key").textContent = showing ? "显示" : "隐藏";
      byId("btn-toggle-workflow-key").setAttribute("aria-pressed", showing ? "false" : "true");
    });
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
    byId("btn-recovery-refresh").addEventListener("click", function () {
      refreshConfig({ silent: false });
    });
    byId("btn-recovery-backup").addEventListener("click", createRecoveryBackup);
    byId("btn-recovery-diagnostics").addEventListener("click", exportRecoveryDiagnostics);
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
    byId("btn-edit-provider-url").addEventListener("click", showProviderUrlEditor);
    byId("btn-cancel-provider-url").addEventListener("click", function () {
      hideProviderUrlEditor(true);
    });
    byId("btn-save-provider-url").addEventListener("click", function () {
      request("/provider/base-url", {
        baseUrl: safeText(byId("provider-base-url").value),
        providerName: "企业大模型接口"
      }).then(function () {
        var savedBaseUrl = safeText(byId("provider-base-url").value);
        setProviderBaseUrl(savedBaseUrl);
        hideProviderUrlEditor(false, true);
        setSettingsStatus("API URL 已保存。");
        invalidateSettingsRefresh();
        refreshSettings({ silent: false });
        syncSettingsRefreshController();
      }).catch(function (error) {
        setSettingsStatus("API URL 保存失败：" + describeSettingsError(error));
      });
    });
  }

  function initialize() {
    var requestedMode = queryMode();
    var initialView = requestedMode === "settings" ? "settings" : "home";
    setHomeTaskMode(requestedMode === "pptStructureReview" ? "pptStructureReview" : "pptSlideAssistant");
    bindEvents();
    setSourceMode("slide");
    state.settingsRefreshController = helpers.createSettingsRefreshController({
      intervalMs: 30000,
      refresh: function () {
        checkHealth();
        return refreshSettings({ silent: true });
      }
    });
    switchView(initialView);
    if (initialView === "home") {
      checkHealth();
      loadProfiles();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
}());
