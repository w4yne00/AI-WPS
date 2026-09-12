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
    activeTaskSlots: {},
    documentSessionId: "",
    documentDisplayName: "",
    historyOpen: false,
    historyItems: [],
    historyUnreadCount: 0,
    profiles: { activeProfileId: "", profiles: [] },
    profilesByTask: {},
    selectedProfileId: "",
    directServices: [],
    directServiceEditor: {
      open: false,
      mode: "create",
      serviceId: "",
      revision: 1,
      dirty: false
    },
    directServiceOperationId: 0,
    directServiceDeleteCandidate: null,
    taskModelSelections: {},
    lastValidatedCustomModel: null,
    workflowProfileMutationBusy: false,
    workflowProfileActivationTimer: null,
    profileLoadRequestId: 0,
    taskModelConfigStatusByTask: {},
    taskModelConfigMenu: { open: false, highlightedIndex: -1, itemCount: 0, items: [] },
    workflowProfileSelections: {},
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

  function getActivePresentation() {
    var app = getWppApplication();
    if (!app) {
      return null;
    }
    try {
      return app.ActivePresentation ||
        (app.Presentations && typeof app.Presentations.Count === "number" && app.Presentations.Count > 0
          ? app.Presentations.Item(1)
          : null);
    } catch (e) {
      return null;
    }
  }

  function releaseTaskSlotsForJob(jobId) {
    if (!state.activeTaskSlots) {
      return;
    }
    if (helpers.releaseTaskSlot && state.documentSessionId) {
      if (typeof PPT_WORKFLOW_TASK_TYPE !== "undefined") {
        helpers.releaseTaskSlot(state.activeTaskSlots, "wpp", PPT_WORKFLOW_TASK_TYPE, state.documentSessionId, jobId);
      }
      if (typeof PPT_STRUCTURE_WORKFLOW_TASK_TYPE !== "undefined") {
        helpers.releaseTaskSlot(state.activeTaskSlots, "wpp", PPT_STRUCTURE_WORKFLOW_TASK_TYPE, state.documentSessionId, jobId);
      }
    }
    for (var k in state.activeTaskSlots) {
      if (Object.prototype.hasOwnProperty.call(state.activeTaskSlots, k)) {
        if (state.activeTaskSlots[k] && state.activeTaskSlots[k].jobId === jobId) {
          delete state.activeTaskSlots[k];
        }
      }
    }
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

  function getCurrentWorkflowTaskType() {
    return homeWorkflowTaskType();
  }

  function getSettingsWorkflowTaskType() {
    return state.workflowTaskType || homeWorkflowTaskType();
  }

  function setHomeTaskMode(mode) {
    var structureMode = mode === "pptStructureReview";
    var historyView = byId("ppt-history-view");
    state.taskMode = structureMode ? "pptStructureReview" : "pptSlideAssistant";
    state.workflowTaskType = homeWorkflowTaskType();
    byId("summary-source-segments").hidden = structureMode;
    byId("summary-controls").hidden = structureMode;
    if (state.historyOpen) {
      byId("summary-result-section").hidden = true;
      byId("structure-result-section").hidden = true;
      if (historyView) {
        historyView.hidden = false;
      }
      loadAndRenderHistory();
    } else {
      byId("summary-result-section").hidden = structureMode;
      byId("structure-result-section").hidden = !structureMode;
      if (historyView) {
        historyView.hidden = true;
      }
    }
    byId("structure-review-controls").hidden = !structureMode;
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
        if (!job.documentSessionId) {
          var prev = loadActiveJob();
          job.documentSessionId = (prev && prev.documentSessionId) || state.documentSessionId || "";
        }
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

  function getStructureActiveJobStorageKey(docSessionId) {
    return [
      "ai-wps",
      "wpp",
      "ppt.structure_review",
      docSessionId || "default"
    ].join(":");
  }

  function loadStructureActiveJob(docSessionId) {
    try {
      if (!window.localStorage) {
        return null;
      }
      var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
      var currentDoc = docSessionId || (helpers.getDocumentSessionId && pres ? helpers.getDocumentSessionId(pres) : state.documentSessionId);
      if (currentDoc) {
        var scopedRaw = window.localStorage.getItem(getStructureActiveJobStorageKey(currentDoc));
        if (scopedRaw) {
          return JSON.parse(scopedRaw);
        }
      }
      var raw = window.localStorage.getItem(PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY);
      if (raw) {
        var legacy = JSON.parse(raw);
        if (!currentDoc || !legacy.documentSessionId || legacy.documentSessionId === currentDoc) {
          return legacy;
        }
      }
      return null;
    } catch (error) {
      return null;
    }
  }

  function saveStructureActiveJob(job) {
    try {
      if (window.localStorage && job && job.jobId) {
        var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
        var currentDoc = job.documentSessionId || (helpers.getDocumentSessionId && pres ? helpers.getDocumentSessionId(pres) : state.documentSessionId) || "";
        var record = JSON.stringify({
          jobId: job.jobId,
          host: "wpp",
          taskType: PPT_STRUCTURE_WORKFLOW_TASK_TYPE,
          documentSessionId: currentDoc,
          startedAt: job.startedAt || state.startedAt || Date.now()
        });
        if (currentDoc) {
          window.localStorage.setItem(getStructureActiveJobStorageKey(currentDoc), record);
        }
        window.localStorage.setItem(PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY, record);
      }
    } catch (error) {
      // In-memory polling remains available.
    }
  }

  function clearStructureActiveJob(jobId, docSessionId) {
    try {
      if (!window.localStorage) {
        return;
      }
      var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
      var currentDoc = docSessionId || (helpers.getDocumentSessionId && pres ? helpers.getDocumentSessionId(pres) : state.documentSessionId);
      if (currentDoc) {
        window.localStorage.removeItem(getStructureActiveJobStorageKey(currentDoc));
      }
      for (var i = window.localStorage.length - 1; i >= 0; i -= 1) {
        var k = window.localStorage.key(i);
        if (k && k.indexOf("ai-wps:wpp:ppt.structure_review:") === 0) {
          var val = window.localStorage.getItem(k);
          if (val) {
            try {
              var parsed = JSON.parse(val);
              if (!jobId || (parsed && parsed.jobId === jobId)) {
                window.localStorage.removeItem(k);
              }
            } catch (e) {}
          }
        }
      }
      var active = loadStructureActiveJob(currentDoc);
      if (!jobId || (active && active.jobId === jobId)) {
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
      "task-model-config-trigger",
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
    setPlainResult(text);
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
    releaseTaskSlotsForJob(jobId);
    state.jobId = "";
    state.jobSourceMode = "";
    state.resumeExpected = false;
    setPptJobActionVisibility(null);
    setRunDisabled(false);
    var statusText = (result && result.resultType === "document" ? "文档总结已完成。" : "当前页总结已完成。");
    if (result && result.historyNotice) {
      statusText += "（" + result.historyNotice + "）";
    }
    if (state.historyOpen) {
      state.historyUnreadCount = (state.historyUnreadCount || 0) + 1;
      updateHistoryBadge();
      var bgStatus = (result && result.resultType === "document" ? "文档总结已完成（请返回查看）。" : "当前页总结已完成（请返回查看）。");
      if (result && result.historyNotice) {
        bgStatus += "（" + result.historyNotice + "）";
      }
      setStatus(bgStatus);
      state.result = result || {};
      return;
    }
    renderResult(result || {});
    setStatus(statusText);
  }

  function failJob(jobId, message, statusMessage) {
    var failureMessage = safeText(message) || "后台任务执行失败。";
    clearActiveJob(jobId);
    releaseTaskSlotsForJob(jobId);
    state.jobId = "";
    state.jobSourceMode = "";
    state.resumeExpected = false;
    state.result = null;
    setPptJobActionVisibility(null);
    setRunDisabled(false);
    setStatus((statusMessage || "总结失败") + "：" + failureMessage);
    setPlainResult(failureMessage);
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
        stage: "job",
        documentSessionId: state.documentSessionId
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
        releaseTaskSlotsForJob(jobId);
        state.jobId = "";
        state.jobSourceMode = "";
        state.resumeExpected = false;
        state.result = null;
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
        stage: "job",
        documentSessionId: state.documentSessionId
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
    var readiness = typeof validateActiveDirectTaskSelection === "function"
      ? validateActiveDirectTaskSelection("ppt.slide_assistant")
      : { valid: true };
    if (readiness && !readiness.valid) {
      setStatus("无法提交任务：" + readiness.error);
      return;
    }
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
      stage: "job",
      documentSessionId: state.documentSessionId
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
        stage: "job",
        documentSessionId: state.documentSessionId
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
    var pres = getActivePresentation();
    var docSession = helpers.getDocumentSessionId ? helpers.getDocumentSessionId(pres) : "doc_default";
    var docName = helpers.getDocumentDisplayName ? helpers.getDocumentDisplayName(pres) : "当前演示文稿";
    state.documentSessionId = docSession;
    state.documentDisplayName = docName;

    if (helpers.isTaskSlotBusy && helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", state.workflowTaskType, docSession)) {
      setStatus("当前文档已有进行中的任务，请稍候。");
      return;
    }

    setRunDisabled(true);
    setStatus("正在读取当前幻灯片...");
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
        state.result = null;
        showProgressText("正在准备提交当前页总结...");
        payload.sourceMode = "slide";
        payload.userInstruction = instruction.slice(0, 1000);
        payload.clientJobId = buildPptSlideClientJobId("slide");
        payload.documentDisplayName = docName;
        if (helpers.claimTaskSlot) {
          helpers.claimTaskSlot(state.activeTaskSlots, "wpp", state.workflowTaskType, docSession, payload.clientJobId);
        }
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
    var pres = getActivePresentation();
    var docSession = helpers.getDocumentSessionId ? helpers.getDocumentSessionId(pres) : "doc_default";
    var docName = helpers.getDocumentDisplayName ? helpers.getDocumentDisplayName(pres) : "当前演示文稿";
    state.documentSessionId = docSession;
    state.documentDisplayName = docName;

    if (helpers.isTaskSlotBusy && helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", state.workflowTaskType, docSession)) {
      setStatus("当前文档已有进行中的任务，请稍候。");
      return;
    }

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
    state.result = null;
    clientJobId = buildPptSlideClientJobId("document");
    if (helpers.claimTaskSlot) {
      helpers.claimTaskSlot(state.activeTaskSlots, "wpp", state.workflowTaskType, docSession, clientJobId);
    }
    setRunDisabled(true);
    saveActiveJob({
      jobId: clientJobId,
      sourceMode: "document",
      stage: "uploading",
      startedAt: Date.now(),
      documentSessionId: docSession
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
        userInstruction: instruction,
        documentSessionId: docSession
      });
      submitPptSlideJob({
        presentationId: "active-presentation",
        scene: "ppt",
        sourceMode: "document",
        fileToken: upload.fileToken,
        requestedSlideCount: count,
        userInstruction: instruction,
        clientJobId: clientJobId,
        documentDisplayName: docName
      });
    }).catch(function (error) {
      releaseTaskSlotsForJob(clientJobId);
      if (state.jobId) {
        return;
      }
      clearActiveJob(clientJobId);
      setRunDisabled(false);
      setStatus("文档上传失败：" + error.message);
      setPlainResult("文档上传失败：" + error.message);
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

  function finishStructureJob(jobId, result, targetDocSession) {
    var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    var currentDocSession = (helpers.getDocumentSessionId && pres) ? helpers.getDocumentSessionId(pres) : state.documentSessionId;
    var jobSession = targetDocSession || currentDocSession;
    clearStructureActiveJob(jobId, jobSession);
    releaseTaskSlotsForJob(jobId);
    if (state.jobId === jobId) {
      state.jobId = "";
      state.resumeExpected = false;
      setStructureJobActionVisibility(null);
      setRunDisabled(false);
    }
    if (!state.structureResultsBySession) {
      state.structureResultsBySession = {};
    }
    state.structureResultsBySession[jobSession] = result || {};

    var statusText = "结构审查已完成。";
    if (result && result.historyNotice) {
      statusText += "（" + result.historyNotice + "）";
    }

    if (currentDocSession && jobSession && currentDocSession !== jobSession) {
      return;
    }

    state.structureResult = result || {};
    if (state.historyOpen) {
      state.historyUnreadCount = (state.historyUnreadCount || 0) + 1;
      updateHistoryBadge();
      var bgStatus = "结构审查已完成（请返回查看）。";
      if (result && result.historyNotice) {
        bgStatus += "（" + result.historyNotice + "）";
      }
      setStatus(bgStatus);
      return;
    }
    renderStructureResult(result || {});
    setStatus(statusText);
  }

  function failStructureJob(jobId, message, statusMessage, targetDocSession) {
    var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    var currentDocSession = (helpers.getDocumentSessionId && pres) ? helpers.getDocumentSessionId(pres) : state.documentSessionId;
    var jobSession = targetDocSession || currentDocSession;
    var failureMessage = safeText(message) || "结构审查后台任务执行失败。";
    clearStructureActiveJob(jobId, jobSession);
    releaseTaskSlotsForJob(jobId);
    if (state.jobId === jobId) {
      state.jobId = "";
      state.resumeExpected = false;
      setStructureJobActionVisibility(null);
      setRunDisabled(false);
    }
    if (state.structureResultsBySession) {
      delete state.structureResultsBySession[jobSession];
    }
    if (currentDocSession && jobSession && currentDocSession !== jobSession) {
      return;
    }
    state.structureResult = null;
    byId("btn-copy-review-conclusion").disabled = true;
    byId("btn-copy-recommended-outline").disabled = true;
    setStatus((statusMessage || "结构审查失败") + "：" + failureMessage);
    byId("structure-result-output").textContent = failureMessage;
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
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "PPT_STRUCTURE_REVIEW_DOCUMENT_TASK_BUSY"
    );
  }

  function pollStructureReviewJob(jobId, targetDocSession) {
    if (!jobId || state.jobId !== jobId || state.taskMode !== "pptStructureReview") {
      return;
    }
    var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    var docSession = targetDocSession || (helpers.getDocumentSessionId && pres ? helpers.getDocumentSessionId(pres) : state.documentSessionId);
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
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt, documentSessionId: docSession });
      if (job.status === "completed") {
        finishStructureJob(jobId, job.result || {}, docSession);
        return;
      }
      if (job.status === "failed") {
        failStructureJob(jobId, job.error && job.error.message, "结构审查失败", docSession);
        return;
      }
      if (job.status === "cancelled") {
        failStructureJob(jobId, "排队中的结构审查任务已取消。", "结构审查已取消", docSession);
        return;
      }
      progress = describeStructureProgress(job, jobId);
      setStatus(progress.status);
      setStructureJobActionVisibility(job);
      byId("structure-result-output").textContent = progress.detail;
      setTimeout(function () { pollStructureReviewJob(jobId, docSession); }, PPT_SLIDE_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed = Date.now() - (state.startedAt || Date.now());
      var within;
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors += 1;
      if (error && error.adapterCode === "PPT_STRUCTURE_JOB_INTERRUPTED") {
        clearStructureActiveJob(jobId, docSession);
        releaseTaskSlotsForJob(jobId);
        state.jobId = "";
        state.resumeExpected = false;
        setRunDisabled(false);
        byId("btn-resubmit-structure-review").hidden = false;
        setStatus("adapter 已重启，原结构审查任务已中断，请重新提交。");
        byId("structure-result-output").textContent = "任务编号：" + jobId;
        return;
      }
      if (isFatalStructurePollError(error)) {
        failStructureJob(jobId, error.message, "状态查询失败", docSession);
        return;
      }
      within = state.pollErrors <= PPT_SLIDE_POLL_MAX_ERRORS && elapsed <= PPT_SLIDE_POLL_MAX_WAIT_MS;
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt, documentSessionId: docSession });
      setStatus(within
        ? "状态查询暂时未连接本地 adapter，继续等待模型后台..."
        : "连接中断，正在低频恢复查询...");
      setTimeout(
        function () { pollStructureReviewJob(jobId, docSession); },
        within ? PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS : PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS
      );
    });
  }

  function submitStructureReviewJob(payload) {
    var readiness = typeof validateActiveDirectTaskSelection === "function"
      ? validateActiveDirectTaskSelection("ppt.structure_review")
      : { valid: true };
    if (readiness && !readiness.valid) {
      setStatus("无法提交任务：" + readiness.error);
      return;
    }
    var clientJobId = payload.clientJobId;
    var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    var docSession = payload.documentSessionId || (helpers.getDocumentSessionId && pres ? helpers.getDocumentSessionId(pres) : state.documentSessionId) || "";
    state.jobId = clientJobId;
    state.startedAt = Date.now();
    state.pollErrors = 0;
    state.resumeExpected = true;
    byId("btn-resubmit-structure-review").hidden = true;
    saveStructureActiveJob({ jobId: clientJobId, startedAt: state.startedAt, documentSessionId: docSession });
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
      saveStructureActiveJob({ jobId: jobId, startedAt: state.startedAt, documentSessionId: docSession });
      if (job.status === "completed") {
        finishStructureJob(jobId, job.result || {}, docSession);
        return;
      }
      progress = describeStructureProgress(job, jobId);
      setStatus(progress.status);
      setStructureJobActionVisibility(job);
      byId("structure-result-output").textContent = progress.detail;
      pollStructureReviewJob(jobId, docSession);
    }).catch(function (error) {
      if (isFatalStructurePollError(error)) {
        failStructureJob(clientJobId, error.message, "提交失败", docSession);
        return;
      }
      setStatus("提交响应未确认，正在按任务编号恢复查询...");
      pollStructureReviewJob(clientJobId, docSession);
    });
  }

  function runPptStructureReview() {
    var startSlide;
    var endSlide;
    var pres;
    var docSession;
    var docName;
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    if (state.workflowProfileMutationBusy) {
      setStatus("模型配置正在更新，请稍后再运行结构审查。");
      return;
    }
    pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    docSession = (helpers.getDocumentSessionId && pres) ? helpers.getDocumentSessionId(pres) : (state.documentSessionId || "");
    docName = (helpers.getDocumentDisplayName && pres) ? helpers.getDocumentDisplayName(pres) : "";
    if (docSession) {
      state.documentSessionId = docSession;
    }
    if (state.jobId) {
      setStatus("已有结构审查任务正在运行，请等待当前任务完成。");
      return;
    }
    if (helpers.isTaskSlotBusy && helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", PPT_STRUCTURE_WORKFLOW_TASK_TYPE, docSession)) {
      setStatus("当前文档已有进行中的任务，请稍候。");
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
        payload.documentSessionId = docSession;
        payload.documentDisplayName = docName;
        payload.host = "wpp";
        state.structureResult = null;
        byId("btn-copy-review-conclusion").disabled = true;
        byId("btn-copy-recommended-outline").disabled = true;
        byId("structure-result-output").textContent = "正在提交结构审查任务...";
        if (helpers.claimTaskSlot) {
          helpers.claimTaskSlot(state.activeTaskSlots, "wpp", PPT_STRUCTURE_WORKFLOW_TASK_TYPE, docSession, payload.clientJobId);
        }
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
      var active = buttons[index].getAttribute("data-workflow-task-tab") === getSettingsWorkflowTaskType();
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
    renderTaskModelSelectionSection();
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

  function findDirectService(serviceId) {
    var services = state.directServices || [];
    var i;
    for (i = 0; i < services.length; i += 1) {
      if (services[i].id === serviceId) {
        return services[i];
      }
    }
    return null;
  }

  function getWorkflowProfileData(taskType) {
    var type = taskType || getCurrentWorkflowTaskType();
    return (state.workflowProfiles && state.workflowProfiles[type]) || (state.profilesByTask && state.profilesByTask[type]) || state.profiles || {
      taskType: type,
      activeProfileId: "",
      profileCount: 0,
      profiles: []
    };
  }

  function getWorkflowProfileById(taskType, profileId) {
    var profiles = getWorkflowProfileData(taskType).profiles || [];
    var index;
    for (index = 0; index < profiles.length; index += 1) {
      if (profiles[index] && profiles[index].id === profileId) {
        return profiles[index];
      }
    }
    var directServices = state.directServices || [];
    for (index = 0; index < directServices.length; index += 1) {
      if (directServices[index] && directServices[index].id === profileId) {
        var svc = directServices[index];
        var selection = (state.taskModelSelections && state.taskModelSelections[taskType]) || {};
        var effModel = selection.effectiveModel || svc.defaultModel || "";
        return {
          id: svc.id,
          name: svc.name,
          accessMethod: "direct_model",
          effectiveModel: effModel,
          complete: Boolean(svc.serviceBaseUrl && svc.keyConfigured),
          serviceBaseUrl: svc.serviceBaseUrl,
          keyConfigured: svc.keyConfigured
        };
      }
    }
    return null;
  }

  function findWorkflowProfile(profileId, taskType) {
    return getWorkflowProfileById(taskType || getCurrentWorkflowTaskType(), profileId);
  }

  function currentTaskModelConfigProfile(data) {
    var taskType = (data && data.taskType) || getCurrentWorkflowTaskType();
    var selectedId = (state.workflowProfileSelections || {})[taskType] || (data && data.activeProfileId) || "";
    if (helpers.resolveCurrentTaskModelConfigProfile) {
      return helpers.resolveCurrentTaskModelConfigProfile(data, selectedId, {
        directServices: state.directServices,
        taskModelSelection: state.taskModelSelections && state.taskModelSelections[taskType]
      });
    }
    return getWorkflowProfileById(taskType, selectedId);
  }

  function resolveTaskModelConfigStatus(taskType, data, profile) {
    if (helpers.resolveTaskModelConfigViewStatus) {
      return helpers.resolveTaskModelConfigViewStatus({
        taskType: taskType,
        mutationBusy: state.workflowProfileMutationBusy,
        statusByTask: state.taskModelConfigStatusByTask,
        hasLoaded: Object.prototype.hasOwnProperty.call(state.profilesByTask || {}, taskType),
        loadError: Boolean(data && data.loadError),
        hasProfile: Boolean(profile)
      });
    }
    if (state.workflowProfileMutationBusy) {
      return "busy";
    }
    if ((state.taskModelConfigStatusByTask || {})[taskType] === "error") {
      return "error";
    }
    if (data && data.loadError) {
      return "loadError";
    }
    if (!profile) {
      return "empty";
    }
    return "ready";
  }

  function taskModelConfigOptionId(index) {
    return "task-model-config-option-" + index;
  }

  function updateTaskModelConfigMenuHighlight(highlightedIndex) {
    var menu = byId("task-model-config-menu");
    var trigger = byId("task-model-config-trigger");
    var options;
    var index;
    if (!menu) {
      return;
    }
    options = menu.querySelectorAll("[data-config-action]");
    for (index = 0; index < options.length; index += 1) {
      if (index === highlightedIndex) {
        options[index].classList.add("is-active");
      } else {
        options[index].classList.remove("is-active");
      }
    }
    if (highlightedIndex >= 0 && options[highlightedIndex]) {
      scrollWorkflowTaskTabIntoView(options[highlightedIndex]);
    }
    if (trigger) {
      if (highlightedIndex >= 0) {
        trigger.setAttribute("aria-activedescendant", taskModelConfigOptionId(highlightedIndex));
      } else {
        trigger.removeAttribute("aria-activedescendant");
      }
    }
  }

  function positionTaskModelConfigMenu() {
    var menu = byId("task-model-config-menu");
    var trigger = byId("task-model-config-trigger");
    var menuRect;
    var triggerRect;
    var viewportHeight;
    if (!menu || !trigger || typeof menu.getBoundingClientRect !== "function") {
      return;
    }
    menu.classList.remove("is-above");
    menuRect = menu.getBoundingClientRect();
    triggerRect = trigger.getBoundingClientRect();
    viewportHeight = window.innerHeight || 700;
    if (menuRect.bottom > viewportHeight - 8 && triggerRect.top > menuRect.height + 8) {
      menu.classList.add("is-above");
    }
  }

  function renderTaskModelConfigMenu(items, highlightedIndex) {
    var menu = byId("task-model-config-menu");
    var rows = [];
    var esc = typeof escaped === "function" ? escaped : function (v) {
      return helpers.escapeHtml ? helpers.escapeHtml(String(v || "")) : String(v || "");
    };
    if (!menu) {
      return;
    }
    items.forEach(function (item, index) {
      var isHighlighted = index === highlightedIndex;
      var isManage = item.action === "manage";
      var role = isManage ? "menuitem" : "menuitemradio";
      var checkedAttr = isManage ? "" : ' aria-checked="' + (item.selected ? "true" : "false") + '"';
      rows.push('<button type="button" class="task-model-config-option' +
        (item.selected ? " is-current" : "") +
        (isHighlighted ? " is-active" : "") +
        '" role="' + role + '" id="' + taskModelConfigOptionId(index) +
        '" tabindex="-1" data-config-action="' + esc(item.action) +
        '" data-profile-id="' + esc(item.id || "") + '"' +
        checkedAttr +
        (item.disabled ? " disabled" : "") + ">" + esc(item.label) + "</button>");
    });
    menu.innerHTML = rows.join("");
    menu.hidden = false;
    updateTaskModelConfigMenuHighlight(highlightedIndex);
    positionTaskModelConfigMenu();
  }

  function openTaskModelConfigMenu() {
    var taskType = getCurrentWorkflowTaskType();
    var data = getWorkflowProfileData(taskType);
    var activeId = (state.workflowProfileSelections || {})[taskType] || data.activeProfileId || "";
    var items = helpers.buildTaskModelConfigMenuItems
      ? helpers.buildTaskModelConfigMenuItems(data.profiles || [], {
        activeProfileId: activeId,
        taskType: taskType,
        directServices: state.directServices,
        taskModelSelection: state.taskModelSelections && state.taskModelSelections[taskType]
      })
      : [];
    var selectedIndex = 0;
    items.forEach(function (item, index) {
      if (item.selected && item.action === "select") {
        selectedIndex = index;
      }
    });
    var reduced = helpers.reduceTaskModelConfigMenuKey
      ? helpers.reduceTaskModelConfigMenuKey({
        open: false,
        itemCount: items.length,
        highlightedIndex: selectedIndex,
        items: items
      }, "Open")
      : { open: true, highlightedIndex: selectedIndex, itemCount: items.length };
    state.taskModelConfigMenu = {
      open: true,
      highlightedIndex: reduced.highlightedIndex,
      itemCount: items.length,
      items: items
    };
    byId("task-model-config-trigger").setAttribute("aria-expanded", "true");
    renderTaskModelConfigMenu(items, reduced.highlightedIndex);
  }

  function closeTaskModelConfigMenu(restoreFocus) {
    var menu = byId("task-model-config-menu");
    var trigger = byId("task-model-config-trigger");
    if (!state.taskModelConfigMenu) {
      state.taskModelConfigMenu = { open: false, highlightedIndex: -1, itemCount: 0, items: [] };
    }
    state.taskModelConfigMenu.open = false;
    state.taskModelConfigMenu.highlightedIndex = -1;
    if (menu) {
      menu.hidden = true;
      menu.innerHTML = "";
    }
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      if (restoreFocus) {
        focusTaskModelConfigTrigger();
      }
    }
  }

  function applyTaskModelConfigMenuItem(item, restoreFocus) {
    var taskType = getCurrentWorkflowTaskType();
    closeTaskModelConfigMenu(restoreFocus);
    if (!item) {
      return;
    }
    if (item.action === "manage") {
      state.workflowTaskType = taskType;
      switchView("settings");
      var targetTab = document.querySelector('[data-workflow-task-tab="' + taskType + '"]');
      if (targetTab && typeof targetTab.focus === "function") {
        targetTab.focus();
      } else {
        var backBtn = byId("btn-open-settings");
        if (backBtn && typeof backBtn.focus === "function") {
          backBtn.focus();
        }
      }
      return;
    }
    if (item.action === "select" && item.id) {
      scheduleWorkflowProfileActivation(
        item.id,
        taskType,
        getWorkflowProfileData(taskType).activeProfileId
      );
    }
  }

  function handleTaskModelConfigTriggerClick() {
    if (state.busy || state.workflowProfileMutationBusy) {
      return;
    }
    if (state.taskModelConfigMenu && state.taskModelConfigMenu.open) {
      closeTaskModelConfigMenu(true);
      return;
    }
    openTaskModelConfigMenu();
  }

  function handleTaskModelConfigMenuClick(event) {
    var node = event.target;
    var button = null;
    var action;
    var profileId;
    while (node && node.getAttribute) {
      if (node.getAttribute("data-config-action")) {
        button = node;
        break;
      }
      node = node.parentNode;
    }
    if (!button || !state.taskModelConfigMenu.open) {
      return;
    }
    action = button.getAttribute("data-config-action");
    profileId = button.getAttribute("data-profile-id");
    applyTaskModelConfigMenuItem({ action: action, id: profileId }, action !== "manage");
  }

  function handleTaskModelConfigKeydown(event) {
    var next;
    if (!state.taskModelConfigMenu || !state.taskModelConfigMenu.open) {
      return;
    }
    next = helpers.reduceTaskModelConfigMenuKey({
      open: true,
      itemCount: state.taskModelConfigMenu.itemCount,
      highlightedIndex: state.taskModelConfigMenu.highlightedIndex,
      items: state.taskModelConfigMenu.items
    }, event.key);
    if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === "Escape") {
      event.preventDefault();
    }
    state.taskModelConfigMenu.highlightedIndex = next.highlightedIndex;
    if (next.action === "close") {
      closeTaskModelConfigMenu(next.restoreFocus);
      return;
    }
    if (next.action === "select" || next.action === "manage") {
      applyTaskModelConfigMenuItem(
        state.taskModelConfigMenu.items[next.action === "select" ? next.selectedIndex : next.highlightedIndex],
        next.restoreFocus
      );
      return;
    }
    updateTaskModelConfigMenuHighlight(next.highlightedIndex);
  }

  function bindTaskModelConfigPress(element) {
    if (!element) {
      return;
    }
    element.addEventListener("pointerdown", function () {
      element.classList.add("is-pressed");
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach(function (type) {
      element.addEventListener(type, function () {
        element.classList.remove("is-pressed");
      });
    });
  }

  function focusTaskModelConfigTrigger() {
    var trigger = byId("task-model-config-trigger");
    if (trigger && typeof trigger.focus === "function") {
      trigger.focus();
    }
  }

  function renderProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var trigger = byId("task-model-config-trigger");
    var label = byId("task-model-config-label");
    var statusNode = byId("task-model-config-status");
    var feedback = byId("workflow-switch-feedback");
    var taskType = getCurrentWorkflowTaskType();
    var data = getWorkflowProfileData(taskType);
    var profile = currentTaskModelConfigProfile(data);
    var status = resolveTaskModelConfigStatus(taskType, data, profile);
    var entry = helpers.formatTaskModelConfigEntry
      ? helpers.formatTaskModelConfigEntry(profile, { status: status })
      : { visibleText: "未配置", statusText: "未配置", ariaLabel: "未配置" };
    var taskLabels = {
      "ppt.slide_assistant": "选择智能总结模型配置",
      "ppt.structure_review": "选择结构审查模型配置"
    };
    var taskLabel = taskLabels[taskType] || "选择模型配置";
    if (!strip || !trigger || !label || !statusNode || !feedback) {
      return;
    }
    strip.hidden = state.currentView === "settings";
    if (state.currentView === "settings") {
      closeTaskModelConfigMenu(false);
      return;
    }
    label.textContent = entry.visibleText;
    trigger.setAttribute("aria-label", taskLabel + "，" + entry.ariaLabel);
    statusNode.className = "task-model-config-status is-" + status;
    trigger.disabled = state.busy || state.workflowProfileMutationBusy || status === "loading";
    setNodeTextIfChanged(feedback, entry.statusText);
    if (state.taskModelConfigMenu && state.taskModelConfigMenu.open) {
      state.taskModelConfigMenu.items = helpers.buildTaskModelConfigMenuItems
        ? helpers.buildTaskModelConfigMenuItems(data.profiles || [], {
          activeProfileId: (state.workflowProfileSelections || {})[taskType] || data.activeProfileId || "",
          taskType: taskType,
          directServices: state.directServices,
          taskModelSelection: state.taskModelSelections && state.taskModelSelections[taskType]
        })
        : [];
      state.taskModelConfigMenu.itemCount = state.taskModelConfigMenu.items.length;
      renderTaskModelConfigMenu(state.taskModelConfigMenu.items, state.taskModelConfigMenu.highlightedIndex);
    }
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
        state.workflowProfileSelections[definition.taskType] =
          nextProfilesByTask[definition.taskType].activeProfileId || "";
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

  function activateWorkflowProfile(profileId, arg2, arg3) {
    var taskType;
    var previousProfileId;
    var data;
    var profile;
    var decision;
    if (typeof arg2 === "string" && (arg2.indexOf("ppt.") === 0 || arg2.indexOf("word.") === 0 || arg2.indexOf("excel.") === 0)) {
      taskType = arg2;
      previousProfileId = arg3;
    } else if (typeof arg3 === "string" && (arg3.indexOf("ppt.") === 0 || arg3.indexOf("word.") === 0 || arg3.indexOf("excel.") === 0)) {
      taskType = arg3;
      previousProfileId = arg2;
    } else {
      taskType = getSettingsWorkflowTaskType();
      previousProfileId = arg3 || arg2;
    }
    data = getWorkflowProfileData(taskType);
    profile = getWorkflowProfileById(taskType, profileId) || (typeof profileById === "function" ? profileById(profileId) : null);
    previousProfileId = typeof previousProfileId === "string"
      ? previousProfileId
      : ((state.workflowProfileSelections && state.workflowProfileSelections[taskType]) || data.activeProfileId || state.selectedProfileId || "");
    decision = helpers.evaluateTaskModelConfigSwitch
      ? helpers.evaluateTaskModelConfigSwitch({
        requestedId: profileId,
        previousId: previousProfileId,
        busy: state.busy || (typeof isWorkflowInteractionBlocked === "function" ? isWorkflowInteractionBlocked() : false),
        mutationBusy: state.workflowProfileMutationBusy,
        profileComplete: Boolean(profile && profile.complete)
      })
      : {
        allowed: Boolean(profileId && profileId !== previousProfileId && profile && profile.complete && !state.busy && !state.workflowProfileMutationBusy),
        reason: "activate",
        nextSelectionId: profileId,
        restoreFocus: false
      };
    if (!decision.allowed) {
      state.workflowProfileSelections[taskType] = decision.nextSelectionId;
      state.selectedProfileId = decision.nextSelectionId;
      if (typeof renderWorkflowProfileStrip === "function") {
        renderWorkflowProfileStrip();
      } else if (typeof renderProfileStrip === "function") {
        renderProfileStrip();
      }
      if (decision.reason === "incomplete") {
        setStatus("该模型配置不完整，暂时不可切换。");
      } else if (decision.reason === "busy") {
        setStatus("当前正忙，请稍后切换模型配置。");
      }
      if (decision.restoreFocus && state.currentView !== "settings" && typeof focusTaskModelConfigTrigger === "function") {
        focusTaskModelConfigTrigger();
      }
      return Promise.resolve();
    }
    state.taskModelConfigStatusByTask[taskType] = "";
    state.workflowProfileSelections[taskType] = profileId;
    state.selectedProfileId = profileId;
    if (typeof state.profileLoadRequestId === "number") {
      state.profileLoadRequestId += 1;
    }
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }

    var isDirectService = String(profileId || "").indexOf("direct_svc_") === 0;
    var activationPromise = isDirectService
      ? request("/provider/direct-services/" + encodeURIComponent(profileId) + "/activate", {
        taskType: taskType,
        taskModelSelection: {
          serviceId: profileId,
          modelName: "",
          customModel: false,
          temperature: null,
          maxOutputTokens: null,
          contextWindowTokens: null
        }
      })
      : request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/activate", {});

    return activationPromise
      .then(function (body) {
        if (isDirectService) {
          state.workflowProfileSelections[taskType] = profileId;
          state.selectedProfileId = profileId;
          state.taskModelConfigStatusByTask[taskType] = "";
          if (body && body.data && body.data.taskModelSelection) {
            state.taskModelSelections[taskType] = body.data.taskModelSelection;
          }
          if (state.taskApiKeys && state.taskApiKeys[taskType]) {
            state.taskApiKeys[taskType].activeProfileId = profileId;
          }
        } else {
          var nextData = helpers.normalizeWorkflowProfiles
            ? helpers.normalizeWorkflowProfiles((body && body.data) || {})
            : data;
          if (!nextData.taskType) {
            nextData.taskType = taskType;
          }
          state.profilesByTask[taskType] = nextData;
          if (state.workflowTaskType === taskType || getCurrentWorkflowTaskType() === taskType) {
            state.profiles = nextData;
            state.selectedProfileId = nextData.activeProfileId || profileId;
          }
          state.workflowProfileSelections[taskType] = nextData.activeProfileId || profileId;
          state.taskModelConfigStatusByTask[taskType] = "";
        }
        var dsRefresh = typeof loadDirectServices === "function" ? loadDirectServices() : Promise.resolve();
        var wfRefresh = typeof loadWorkflowProfiles === "function" ? loadWorkflowProfiles(taskType) : (typeof loadProfiles === "function" ? loadProfiles() : Promise.resolve());
        return Promise.all([wfRefresh, dsRefresh]).then(function () {
          if (typeof setWorkflowProfileMutationBusy === "function") {
            setWorkflowProfileMutationBusy(false);
          } else {
            state.workflowProfileMutationBusy = false;
          }
          if (typeof renderWorkflowProfileStrip === "function") {
            renderWorkflowProfileStrip();
          } else if (typeof renderProfileStrip === "function") {
            renderProfileStrip();
          }
          if (typeof renderWorkflowTaskTabs === "function") {
            renderWorkflowTaskTabs();
          }
          if (typeof renderWorkflowProfileManager === "function") {
            renderWorkflowProfileManager();
          } else if (typeof renderProfileManager === "function") {
            renderProfileManager();
          }
          if (typeof renderTaskModelSelectionSection === "function") {
            renderTaskModelSelectionSection();
          }
          if (typeof renderModelInterfaceState === "function") {
            renderModelInterfaceState(state.modelInterfaceDetectable);
          }
          setStatus("已切换至：" + ((profile && profile.name) || "模型配置"));
        }).catch(function (refreshError) {
          if (typeof setWorkflowProfileMutationBusy === "function") {
            setWorkflowProfileMutationBusy(false);
          } else {
            state.workflowProfileMutationBusy = false;
          }
          if (typeof renderWorkflowProfileStrip === "function") {
            renderWorkflowProfileStrip();
          } else if (typeof renderProfileStrip === "function") {
            renderProfileStrip();
          }
          if (typeof renderWorkflowTaskTabs === "function") {
            renderWorkflowTaskTabs();
          }
          if (typeof renderWorkflowProfileManager === "function") {
            renderWorkflowProfileManager();
          } else if (typeof renderProfileManager === "function") {
            renderProfileManager();
          }
          if (typeof renderTaskModelSelectionSection === "function") {
            renderTaskModelSelectionSection();
          }
          var refreshErrMsg = typeof describeFetchError === "function"
            ? describeFetchError(refreshError)
            : (typeof describeSettingsError === "function"
              ? describeSettingsError(refreshError)
              : ((refreshError && refreshError.message) || String(refreshError || "未知错误")));
          setStatus("模型配置已激活，但刷新最新列表失败：" + refreshErrMsg);
        });
      })
      .catch(function (error) {
        var previousProfile = typeof getWorkflowProfileById === "function"
          ? getWorkflowProfileById(taskType, previousProfileId)
          : (typeof findWorkflowProfile === "function" ? findWorkflowProfile(previousProfileId, taskType) : null);
        var previousEntry = helpers.formatTaskModelConfigEntry
          ? helpers.formatTaskModelConfigEntry(previousProfile, { status: "error" })
          : { visibleText: typeof activeProfileName === "function" ? activeProfileName() : "尚未配置" };
        var rolled = helpers.rollbackTaskModelConfigSwitch
          ? helpers.rollbackTaskModelConfigSwitch({
            previousId: previousProfileId,
            previousLabel: previousEntry.visibleText
          })
          : {
            selectionId: previousProfileId,
            statusText: "切换失败",
            restoreFocus: true
          };
        var stillRelevant = state.currentView === "settings"
          ? getSettingsWorkflowTaskType() === taskType
          : getCurrentWorkflowTaskType() === taskType;
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        state.workflowProfileSelections[taskType] = rolled.selectionId;
        if (stillRelevant) {
          state.selectedProfileId = rolled.selectionId;
        }
        state.taskModelConfigStatusByTask[taskType] = "error";
        if (typeof renderWorkflowProfileStrip === "function") {
          renderWorkflowProfileStrip();
        } else if (typeof renderProfileStrip === "function") {
          renderProfileStrip();
        }
        if (typeof renderWorkflowTaskTabs === "function") {
          renderWorkflowTaskTabs();
        }
        if (typeof renderWorkflowProfileManager === "function") {
          renderWorkflowProfileManager();
        } else if (typeof renderProfileManager === "function") {
          renderProfileManager();
        }
        if (typeof renderTaskModelSelectionSection === "function") {
          renderTaskModelSelectionSection();
        }
        if (!stillRelevant) {
          return;
        }
        var errorMsg = typeof describeFetchError === "function"
          ? describeFetchError(error)
          : (typeof describeSettingsError === "function"
            ? describeSettingsError(error)
            : ((error && error.message) || String(error || "未知错误")));
        setStatus("切换模型配置失败：" + errorMsg);
        setNodeTextIfChanged(byId("workflow-switch-feedback"), rolled.statusText);
        if (rolled.restoreFocus && state.currentView !== "settings" && typeof focusTaskModelConfigTrigger === "function") {
          focusTaskModelConfigTrigger();
        }
      });
  }

  function cancelWorkflowProfileActivation() {
    if (state.workflowProfileActivationTimer !== null) {
      window.clearTimeout(state.workflowProfileActivationTimer);
      state.workflowProfileActivationTimer = null;
    }
  }

  function scheduleWorkflowProfileActivation(profileId, taskType, previousProfileId) {
    cancelWorkflowProfileActivation();
    state.workflowProfileActivationTimer = window.setTimeout(function () {
      state.workflowProfileActivationTimer = null;
      activateWorkflowProfile(profileId, taskType, previousProfileId);
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

  function describeFetchError(error) {
    if (typeof describeSettingsError === "function") {
      return describeSettingsError(error);
    }
    return (error && error.message) || String(error || "未知错误");
  }

  function escapeWorkflowText(value) {
    if (typeof escaped === "function") {
      return escaped(value);
    }
    return helpers.escapeHtml ? helpers.escapeHtml(String(value || "")) : String(value || "");
  }

  function loadWorkflowProfiles(taskType) {
    return typeof loadProfiles === "function" ? loadProfiles() : Promise.resolve({});
  }

  function renderWorkflowProfileStrip() {
    if (typeof renderProfileStrip === "function") {
      return renderProfileStrip();
    }
  }

  function renderWorkflowProfileManager() {
    if (typeof renderProfileManager === "function") {
      return renderProfileManager();
    }
  }

  function formatDirectServiceCatalogStatus(service) {
    var catalog = helpers.getDirectServiceCatalogState
      ? helpers.getDirectServiceCatalogState(service)
      : { status: "unavailable", models: [] };
    var count = catalog.models ? catalog.models.length : 0;
    var errorText = catalog.lastError && (catalog.lastError.message || catalog.lastError.code);
    if (catalog.status === "available" && catalog.cacheStatus === "valid") {
      if (catalog.fetchStatus === "error" && errorText) {
        return "目录刷新失败，继续使用 " + count + " 个缓存模型；" + errorText;
      }
      return "目录有效：" + count + " 个模型" + (catalog.fetchedAt ? "，获取于 " + catalog.fetchedAt : "");
    }
    if (catalog.status === "expired") {
      return "目录已过期；可使用高级手填" + (errorText ? "；最近错误：" + errorText : "");
    }
    if (catalog.status === "empty") {
      return "目录为空；可使用高级手填" + (errorText ? "；最近错误：" + errorText : "");
    }
    return "目录不可用；可使用高级手填" + (errorText ? "；最近错误：" + errorText : "");
  }

  function loadDirectServices(configRefreshRequestId, requestOptions, directServiceOperationId) {
    return Promise.all([
      request("/provider/direct-services", null, requestOptions),
      request("/provider/task-model-selections?host=ppt", null, requestOptions)
    ]).then(function (results) {
      var dsBody = results[0];
      var tmsBody = results[1];
      if (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId) {
        return { superseded: true };
      }
      if (directServiceOperationId && state.directServiceOperationId !== directServiceOperationId) {
        return { superseded: true };
      }
      state.directServices = (dsBody && dsBody.data && dsBody.data.directServices) || [];
      var selectionsMap = {};
      var rawSelections = (tmsBody && tmsBody.data && (tmsBody.data.taskModelSelections || tmsBody.data.selections)) || [];
      if (Array.isArray(rawSelections)) {
        rawSelections.forEach(function (sel) {
          if (sel && sel.taskType) {
            selectionsMap[sel.taskType] = sel;
          }
        });
      } else if (rawSelections && typeof rawSelections === "object") {
        selectionsMap = rawSelections;
      }
      state.taskModelSelections = selectionsMap;
      TASK_API_KEY_DEFS.forEach(function (definition) {
        var taskType = definition.taskType;
        var taskStatus = state.taskApiKeys && state.taskApiKeys[taskType];
        if (taskStatus && taskStatus.accessMethod === "direct_model" && taskStatus.activeProfileId) {
          state.workflowProfileSelections[taskType] = taskStatus.activeProfileId;
        }
      });
      renderDirectServicesList();
      renderTaskModelSelectionSection();
      if (typeof renderWorkflowProfileStrip === "function") {
        renderWorkflowProfileStrip();
      } else if (typeof renderProfileStrip === "function") {
        renderProfileStrip();
      }
      if (typeof renderWorkflowProfileManager === "function") {
        renderWorkflowProfileManager();
      } else if (typeof renderProfileManager === "function") {
        renderProfileManager();
      }
      return { success: true };
    }).catch(function (error) {
      if (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId) {
        return { superseded: true };
      }
      if (directServiceOperationId && state.directServiceOperationId !== directServiceOperationId) {
        return { superseded: true };
      }
      renderDirectServicesList();
      renderTaskModelSelectionSection();
      throw error;
    });
  }

  function renderDirectServicesList() {
    var list = byId("direct-services-list");
    var btnNew = byId("btn-new-direct-service");
    var rows = [];
    if (!list) {
      return;
    }
    if (btnNew) {
      btnNew.disabled = (state.directServices || []).length >= 5;
    }
    if (!state.directServices || state.directServices.length === 0) {
      list.innerHTML = '<p class="field-hint">尚未建立共享直连服务。</p>';
      return;
    }
    state.directServices.forEach(function (svc) {
      var id = escapeWorkflowText(svc.id);
      var modelText = svc.defaultModel ? (" · 默认模型：" + escapeWorkflowText(svc.defaultModel)) : "";
      var catalogText = typeof formatDirectServiceCatalogStatus === "function"
        ? formatDirectServiceCatalogStatus(svc)
        : (svc.modelList && svc.modelList.length ? ("目录已有 " + svc.modelList.length + " 个模型") : "目录未获取");
      rows.push('<div class="workflow-profile-list-row" data-direct-service-id="' + id + '">');
      rows.push('<div class="workflow-profile-copy">');
      rows.push('<div class="workflow-profile-title"><strong>' + escapeWorkflowText(svc.name) + '</strong>');
      rows.push('<span class="provider-badge">' + (svc.keyConfigured ? "已配Key" : "未配Key") + '</span></div>');
      rows.push('<p class="workflow-profile-note">' + escapeWorkflowText(svc.serviceBaseUrl || "未配置URL") + modelText + '</p>');
      rows.push('<p class="workflow-profile-note">' + escapeWorkflowText(catalogText) + '</p>');
      rows.push('</div>');
      rows.push('<div class="workflow-profile-actions">');
      rows.push('<button type="button" class="ghost-action mini-button" data-direct-action="edit" data-direct-id="' + id + '">编辑</button>');
      rows.push('<button type="button" class="ghost-action mini-button danger-action" data-direct-action="delete" data-direct-id="' + id + '">删除</button>');
      rows.push('</div></div>');
    });
    list.innerHTML = rows.join("");
  }

  function openDirectServiceEditor(mode, serviceId) {
    var isCreate = mode === "create";
    var svc = isCreate ? null : findDirectService(serviceId);
    var title = byId("direct-service-editor-title");
    var nameInput = byId("direct-service-name");
    var urlInput = byId("direct-service-url");
    var keyInput = byId("direct-service-key");
    var keyLabel = byId("direct-service-key-label");
    var keyStatus = byId("direct-service-key-status");
    var defaultModelInput = byId("direct-service-default-model");
    var modelsStatus = byId("direct-service-models-status");
    var btnRefresh = byId("btn-refresh-direct-service-models");
    var btnValidate = byId("btn-validate-direct-service");
    var validationStatus = byId("direct-service-validation-status");
    var errorBox = byId("direct-service-editor-error");

    if (isCreate && (state.directServices || []).length >= 5) {
      setStatus("最多只能保存 5 份共享直连服务。");
      return;
    }
    if (!isCreate && !svc) {
      setStatus("未找到指定的直连服务。");
      return;
    }

    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    state.directServiceEditor = {
      open: true,
      mode: mode,
      serviceId: isCreate ? "" : svc.id,
      revision: isCreate ? 1 : svc.revision,
      dirty: false
    };

    if (title) {
      title.textContent = isCreate ? "新建直连服务" : "编辑直连服务";
    }
    if (nameInput) {
      nameInput.value = isCreate ? "" : svc.name;
    }
    if (urlInput) {
      urlInput.value = isCreate ? "" : svc.serviceBaseUrl;
    }
    if (keyInput) {
      keyInput.value = "";
      keyInput.placeholder = isCreate ? "输入 API Key" : "留空保持原 API Key 不变";
    }
    if (keyLabel) {
      keyLabel.textContent = isCreate ? "API Key（仅需录入一次）" : "更换 API Key";
    }
    if (keyStatus) {
      keyStatus.textContent = isCreate ? "" : (svc.keyConfigured ? "已配置（留空保持不变）" : "未配置");
    }
    if (defaultModelInput) {
      defaultModelInput.value = isCreate ? "" : (svc.defaultModel || "");
    }
    if (modelsStatus) {
      modelsStatus.textContent = !isCreate && typeof formatDirectServiceCatalogStatus === "function"
        ? formatDirectServiceCatalogStatus(svc)
        : (!isCreate && svc.modelList && svc.modelList.length
          ? ("已获取 " + svc.modelList.length + " 个模型")
          : "目录未获取");
    }
    if (btnRefresh) {
      btnRefresh.disabled = isCreate;
    }
    if (btnValidate) {
      btnValidate.disabled = isCreate;
    }
    if (validationStatus) {
      validationStatus.textContent = "";
    }
    if (errorBox) {
      errorBox.textContent = "";
    }
    var urlImpactNode = byId("direct-service-url-impact");
    if (urlImpactNode) {
      urlImpactNode.hidden = true;
      urlImpactNode.textContent = "";
    }
    var btnClearKey = byId("btn-clear-direct-service-key");
    if (btnClearKey) {
      btnClearKey.hidden = isCreate || !svc.keyConfigured;
      btnClearKey.disabled = false;
    }

    var editorView = byId("direct-service-editor-view");
    if (editorView) {
      editorView.hidden = false;
    }
    var dsList = byId("direct-services-list");
    if (dsList) {
      dsList.hidden = true;
    }
    var btnNewDs = byId("btn-new-direct-service");
    if (btnNewDs) {
      btnNewDs.hidden = true;
    }
    if (nameInput && typeof nameInput.focus === "function") {
      nameInput.focus();
    }
  }

  function closeDirectServiceEditor() {
    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    if (state.directServiceEditor) {
      state.directServiceEditor.open = false;
    }
    var keyInput = byId("direct-service-key");
    if (keyInput) {
      keyInput.value = "";
    }
    if (state.workflowProfileMutationBusy) {
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
    }
    var editorView = byId("direct-service-editor-view");
    if (editorView) {
      editorView.hidden = true;
    }
    var dsList = byId("direct-services-list");
    if (dsList) {
      dsList.hidden = false;
    }
    var btnNewDs = byId("btn-new-direct-service");
    if (btnNewDs) {
      btnNewDs.hidden = false;
    }
    var errorBox = byId("direct-service-editor-error");
    if (errorBox) {
      errorBox.textContent = "";
    }
    var urlImpactNode = byId("direct-service-url-impact");
    if (urlImpactNode) {
      urlImpactNode.hidden = true;
      urlImpactNode.textContent = "";
    }
  }

  function updateDirectServiceUrlImpact() {
    var editor = state.directServiceEditor || {};
    if (editor.mode !== "edit" || !editor.serviceId) {
      var node = byId("direct-service-url-impact");
      if (node) {
        node.hidden = true;
        node.textContent = "";
      }
      return;
    }
    var svc = findDirectService(editor.serviceId);
    var urlInput = byId("direct-service-url");
    var urlImpactNode = byId("direct-service-url-impact");
    if (!svc || !urlInput || !urlImpactNode) {
      return;
    }
    var res = helpers.evaluateDirectServiceUrlImpact
      ? helpers.evaluateDirectServiceUrlImpact(svc, urlInput.value)
      : { isModified: false, warning: "" };
    if (res.isModified && res.warning) {
      urlImpactNode.textContent = res.warning;
      urlImpactNode.hidden = false;
    } else {
      urlImpactNode.hidden = true;
      urlImpactNode.textContent = "";
    }
  }

  function clearDirectServiceApiKey() {
    var editor = state.directServiceEditor || {};
    var serviceId = editor.serviceId;
    var revision = editor.revision;
    var keyInput = byId("direct-service-key");
    var keyStatus = byId("direct-service-key-status");
    var btnClear = byId("btn-clear-direct-service-key");
    var errorBox = byId("direct-service-editor-error");
    if (!serviceId || state.workflowProfileMutationBusy) {
      return;
    }
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    request("/provider/direct-services/" + encodeURIComponent(serviceId) + "/api-key?expectedRevision=" + encodeURIComponent(revision), null, {
      method: "DELETE"
    }).then(function (body) {
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      var svc = (body && body.data && body.data.directService) || {};
      var nextRev = svc.revision || (revision + 1);
      if (state.directServiceEditor && state.directServiceEditor.serviceId === serviceId) {
        state.directServiceEditor.revision = nextRev;
      }
      if (keyInput) {
        keyInput.value = "";
        keyInput.placeholder = "输入新 API Key";
      }
      if (keyStatus) {
        keyStatus.textContent = "未配置";
      }
      if (btnClear) {
        btnClear.hidden = true;
      }
      return loadDirectServices().then(function () {
        setStatus("API Key 已清除。");
      });
    }).catch(function (error) {
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      if (helpers.isDirectServiceRevisionConflict && helpers.isDirectServiceRevisionConflict(error)) {
        if (errorBox) {
          errorBox.textContent = "服务已被其他操作修改（版本冲突），已停止清除 Key。请刷新后重新编辑，本次修改未自动合并。";
        }
      } else if (errorBox) {
        errorBox.textContent = "清除 API Key 失败：" + describeFetchError(error);
      }
    });
  }

  function saveDirectServiceEditor() {
    if (state.workflowProfileMutationBusy) {
      return;
    }
    var editor = state.directServiceEditor || {};
    var isCreate = editor.mode === "create";
    var serviceId = editor.serviceId;
    var revision = editor.revision;
    var nameInput = byId("direct-service-name");
    var urlInput = byId("direct-service-url");
    var keyInput = byId("direct-service-key");
    var defaultModelInput = byId("direct-service-default-model");
    var errorBox = byId("direct-service-editor-error");

    var name = (nameInput && nameInput.value || "").trim();
    var url = (urlInput && urlInput.value || "").trim();
    var key = (keyInput && keyInput.value || "").trim();
    var defaultModel = (defaultModelInput && defaultModelInput.value || "").trim();

    var draft = {
      name: name,
      serviceBaseUrl: url,
      apiKey: key,
      key: key,
      isNew: isCreate,
      defaultModel: defaultModel
    };

    var checked = helpers.validateDirectServiceDraft
      ? helpers.validateDirectServiceDraft(draft, editor.mode)
      : { ok: Boolean(draft.name && draft.serviceBaseUrl && (!isCreate || draft.apiKey)) };

    if (!checked.ok) {
      if (errorBox) {
        errorBox.textContent = checked.message || checked.error || "请检查输入项。";
      }
      return;
    }

    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    var operationId = state.directServiceOperationId;
    var editorMode = editor.mode;
    function isCurrentOperation() {
      return state.directServiceOperationId === operationId &&
        state.directServiceEditor && state.directServiceEditor.open &&
        state.directServiceEditor.mode === editorMode &&
        state.directServiceEditor.serviceId === serviceId;
    }
    function completeSave(message) {
      return loadDirectServices(undefined, undefined, operationId).then(function () {
        if (!isCurrentOperation()) {
          return { superseded: true };
        }
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        closeDirectServiceEditor();
        setStatus(message);
        return { success: true };
      });
    }
    function failSave(error, prefix) {
      if (!isCurrentOperation()) {
        return { superseded: true };
      }
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      if (helpers.isDirectServiceRevisionConflict && helpers.isDirectServiceRevisionConflict(error)) {
        if (errorBox) {
          errorBox.textContent = "服务已被其他操作修改（版本冲突），已停止保存。请刷新后重新编辑，本次修改未自动合并。";
        }
      } else if (errorBox) {
        errorBox.textContent = prefix + describeFetchError(error);
      }
      return { failed: true, error: error };
    }
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }

    if (isCreate) {
      return request("/provider/direct-services", {
        name: draft.name,
        serviceBaseUrl: draft.serviceBaseUrl,
        defaultModel: draft.defaultModel,
        apiKey: draft.apiKey
      }).then(function (body) {
        if (!isCurrentOperation()) {
          return { superseded: true };
        }
        var created = (body && body.data && body.data.directService) || (body && body.data);
        var createdId = created ? created.id : "";
        var createdRev = (created && created.revision) || 1;
        var keyPromise = (created && created.keyConfigured)
          ? Promise.resolve()
          : request("/provider/direct-services/" + encodeURIComponent(createdId) + "/api-key", {
              apiKey: draft.apiKey,
              expectedRevision: createdRev
            }).catch(function (keyErr) {
              return request("/provider/direct-services/" + encodeURIComponent(createdId) + "?expectedRevision=" + encodeURIComponent(createdRev), null, {
                method: "DELETE"
              }).then(function () {
                throw keyErr;
              }, function () {
                throw keyErr;
              });
            });

        return keyPromise.then(function () {
          if (!isCurrentOperation()) {
            return { superseded: true };
          }
          return completeSave("共享直连服务已新建，模型目录已自动刷新。");
        });
      }).catch(function (error) {
        return failSave(error, "新建直连服务失败：");
      });
    }

    return request("/provider/direct-services/" + encodeURIComponent(serviceId), {
      name: draft.name,
      serviceBaseUrl: draft.serviceBaseUrl,
      defaultModel: draft.defaultModel,
      expectedRevision: revision
    }, { method: "PATCH" }).then(function (patchBody) {
      if (!isCurrentOperation()) {
        return { superseded: true };
      }
      var updated = (patchBody && patchBody.data && patchBody.data.directService) || (patchBody && patchBody.data) || {};
      var nextRev = updated.revision || (revision + 1);
      if (!draft.key) {
        return completeSave("共享直连服务已保存。");
      }
      return request("/provider/direct-services/" + encodeURIComponent(serviceId) + "/api-key", {
        apiKey: draft.key,
        expectedRevision: nextRev
      }).then(function () {
        if (!isCurrentOperation()) {
          return { superseded: true };
        }
        return completeSave("共享直连服务与 API Key 已保存。");
      });
    }).catch(function (error) {
      return failSave(error, "保存直连服务失败：");
    });
  }

  function refreshDirectServiceModelsInEditor() {
    var editor = state.directServiceEditor || {};
    var serviceId = editor.serviceId;
    var revision = editor.revision;
    var statusNode = byId("direct-service-models-status");
    if (!serviceId || state.workflowProfileMutationBusy) {
      return;
    }
    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    var operationId = state.directServiceOperationId;
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    if (statusNode) {
      statusNode.textContent = "正在刷新模型目录...";
    }
    return request("/provider/direct-services/" + encodeURIComponent(serviceId) + "/refresh-models", {
      expectedRevision: revision
    }).then(function (body) {
      if (state.directServiceOperationId !== operationId || !state.directServiceEditor.open || state.directServiceEditor.serviceId !== serviceId) {
        return { superseded: true };
      }
      var svc = (body && body.data && body.data.directService) || {};
      var models = svc.modelList || (body && body.data && body.data.models) || [];
      var nextRev = svc.revision || (body && body.data && body.data.revision) || (revision + 1);
      if (state.directServiceEditor && state.directServiceEditor.serviceId === serviceId) {
        state.directServiceEditor.revision = nextRev;
      }
      if (statusNode) {
        statusNode.textContent = typeof formatDirectServiceCatalogStatus === "function"
          ? formatDirectServiceCatalogStatus(svc)
          : ("已获取 " + models.length + " 个模型");
      }
      return loadDirectServices(undefined, undefined, operationId).then(function () {
        if (state.directServiceOperationId !== operationId || !state.directServiceEditor.open || state.directServiceEditor.serviceId !== serviceId) {
          return { superseded: true };
        }
        if (state.directServiceEditor && state.directServiceEditor.open && state.directServiceEditor.serviceId === serviceId) {
          var updatedSvc = findDirectService(serviceId);
          if (updatedSvc && updatedSvc.revision) {
            state.directServiceEditor.revision = updatedSvc.revision;
          }
          if (statusNode && updatedSvc && typeof formatDirectServiceCatalogStatus === "function") {
            statusNode.textContent = formatDirectServiceCatalogStatus(updatedSvc);
          }
        }
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        return { success: true };
      });
    }).catch(function (error) {
      if (state.directServiceOperationId !== operationId || !state.directServiceEditor.open || state.directServiceEditor.serviceId !== serviceId) {
        return { superseded: true };
      }
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      if (statusNode) {
        statusNode.textContent = "刷新失败：" + describeFetchError(error);
      }
      return { failed: true, error: error };
    });
  }

  function validateDirectService() {
    var editor = state.directServiceEditor || {};
    var serviceId = editor.serviceId;
    var revision = editor.revision;
    var statusNode = byId("direct-service-validation-status");
    var modelsStatus = byId("direct-service-models-status");
    if (!serviceId || state.workflowProfileMutationBusy) {
      if (statusNode) {
        statusNode.textContent = "请先保存直连服务。";
      }
      return;
    }
    if (statusNode) {
      statusNode.textContent = "正在验证服务连接、认证和模型目录（不执行任务调用）...";
    }
    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    var operationId = state.directServiceOperationId;
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    return request("/provider/direct-services/" + encodeURIComponent(serviceId) + "/validate", {
      expectedRevision: revision
    }).then(function (body) {
      if (state.directServiceOperationId !== operationId || !state.directServiceEditor.open || state.directServiceEditor.serviceId !== serviceId) {
        return { superseded: true };
      }
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      var data = (body && body.data) || {};
      var catalogAvailable = data.modelCatalogAvailable;
      if (catalogAvailable === undefined && data.directService) {
        catalogAvailable = helpers.getDirectServiceCatalogState
          ? helpers.getDirectServiceCatalogState(data.directService).usableForSelection
          : Boolean(data.directService.modelList && data.directService.modelList.length);
      }
      if (modelsStatus && data.directService && typeof formatDirectServiceCatalogStatus === "function") {
        modelsStatus.textContent = formatDirectServiceCatalogStatus(data.directService);
      }
      if (data.directService && data.directService.revision && state.directServiceEditor && state.directServiceEditor.serviceId === serviceId) {
        state.directServiceEditor.revision = data.directService.revision;
      }
      if (statusNode) {
        if (catalogAvailable) {
          statusNode.textContent = "服务验证成功；模型目录可用。";
        } else if (data.authenticationVerified === false) {
          statusNode.textContent = "服务可达，但认证未验证；未提供可用模型目录，可使用高级手填。";
        } else {
          statusNode.textContent = "服务可达且认证成功，但未提供可用模型目录；可使用高级手填。";
        }
      }
      if (typeof loadDirectServices === "function") {
        loadDirectServices(undefined, undefined, operationId).catch(function () {});
      }
    }).catch(function (error) {
      if (state.directServiceOperationId !== operationId || !state.directServiceEditor.open || state.directServiceEditor.serviceId !== serviceId) {
        return { superseded: true };
      }
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      if (statusNode) {
        statusNode.textContent = "服务验证失败：" + describeFetchError(error);
      }
      if (typeof loadDirectServices === "function") {
        loadDirectServices(undefined, undefined, operationId).then(function () {
          var currentSvc = findDirectService(serviceId);
          if (modelsStatus && currentSvc && typeof formatDirectServiceCatalogStatus === "function") {
            modelsStatus.textContent = formatDirectServiceCatalogStatus(currentSvc);
          }
        }).catch(function () {});
      }
    });
  }

  function openDirectServiceDeleteDialog(serviceId) {
    var svc = findDirectService(serviceId);
    var nameNode = byId("direct-service-delete-name");
    var warningNode = byId("direct-service-delete-warning");
    var confirmBtn = byId("btn-confirm-direct-service-delete");
    var dialog = byId("direct-service-delete-dialog");
    if (!svc) {
      return;
    }
    state.directServiceDeleteCandidate = { id: svc.id, name: svc.name, revision: svc.revision };
    if (nameNode) {
      nameNode.textContent = svc.name;
    }
    var evalRes = helpers.evaluateDirectServiceDelete ? helpers.evaluateDirectServiceDelete(svc) : { canDelete: true, message: "" };
    if (warningNode) {
      warningNode.textContent = evalRes.message || "";
    }
    if (confirmBtn) {
      confirmBtn.disabled = !evalRes.canDelete;
    }
    if (dialog) {
      dialog.hidden = false;
    }
  }

  function hideDirectServiceDeleteDialog() {
    state.directServiceDeleteCandidate = null;
    var dialog = byId("direct-service-delete-dialog");
    if (dialog) {
      dialog.hidden = true;
    }
    var confirmBtn = byId("btn-confirm-direct-service-delete");
    if (confirmBtn) {
      confirmBtn.disabled = false;
    }
  }

  function confirmDirectServiceDelete() {
    var candidate = state.directServiceDeleteCandidate;
    if (!candidate || state.workflowProfileMutationBusy) {
      return;
    }
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    request("/provider/direct-services/" + encodeURIComponent(candidate.id) + "?expectedRevision=" + encodeURIComponent(candidate.revision), null, {
      method: "DELETE"
    }).then(function () {
      hideDirectServiceDeleteDialog();
      return loadDirectServices().then(function () {
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        setStatus("直连服务“" + candidate.name + "”已删除。");
      });
    }).catch(function (error) {
      hideDirectServiceDeleteDialog();
      if (typeof setWorkflowProfileMutationBusy === "function") {
        setWorkflowProfileMutationBusy(false);
      } else {
        state.workflowProfileMutationBusy = false;
      }
      var errObj = error || {};
      var referenced = errObj.referencedTasks || (errObj.data && errObj.data.referencedTasks);
      if ((errObj.adapterCode || errObj.code) === "DIRECT_SERVICE_IN_USE" || (Array.isArray(referenced) && referenced.length)) {
        var tasksStr = helpers.formatReferencedTasks ? helpers.formatReferencedTasks(referenced) : "";
        setStatus("删除直连服务失败：该服务正被任务使用（" + (tasksStr || "已引用") + "），无法删除。");
      } else {
        setStatus("删除直连服务失败：" + describeFetchError(error));
      }
    });
  }

  function handleDirectServiceAction(event) {
    var action = event.target.getAttribute("data-direct-action");
    var serviceId = event.target.getAttribute("data-direct-id") || "";
    if (!action || state.workflowProfileMutationBusy) {
      return;
    }
    if (action === "edit") {
      openDirectServiceEditor("edit", serviceId);
    } else if (action === "delete") {
      openDirectServiceDeleteDialog(serviceId);
    }
  }

  function renderTaskModelSelectionSection() {
    var section = byId("ppt-task-direct-service-section");
    var title = byId("ppt-task-direct-service-title");
    var hint = byId("ppt-task-direct-service-hint");
    var select = byId("ppt-task-direct-service-select");
    var paramsDiv = byId("ppt-task-direct-params");
    var modelSelect = byId("ppt-task-model-select");
    var customCheck = byId("ppt-task-custom-model-check");
    var customRow = byId("ppt-task-custom-model-row");
    var customInput = byId("ppt-task-custom-model-input");
    var tempInput = byId("ppt-task-temperature");
    var maxOutInput = byId("ppt-task-max-output");
    var contextInput = byId("ppt-task-context");
    var costWarning = byId("ppt-task-model-cost-warning");
    var statusNode = byId("ppt-task-model-validation-status");

    if (!section || !select) {
      return;
    }

    var currentTask = getSettingsWorkflowTaskType();
    var isSupportedTask = (currentTask === "ppt.slide_assistant" || currentTask === "ppt.structure_review");
    section.hidden = !isSupportedTask;
    if (!isSupportedTask) {
      return;
    }

    if (title) {
      title.textContent = currentTask === "ppt.structure_review" ? "结构审查接入选择" : "智能总结接入选择";
    }
    if (hint) {
      hint.textContent = "使用工作流平台或绑定上方共享直连服务，独立调整任务参数。";
    }

    var directServices = state.directServices || [];
    var currentSelection = (state.taskModelSelections && state.taskModelSelections[currentTask]) || null;
    var profileData = (typeof getWorkflowProfileData === "function")
      ? getWorkflowProfileData(currentTask)
      : ((state.workflowProfiles && state.workflowProfiles[currentTask]) || (state.profilesByTask && state.profilesByTask[currentTask]) || {});
    var activeProfileId = (profileData && profileData.activeProfileId) || "";
    var chosenServiceId = (currentSelection && currentSelection.serviceId) || (String(activeProfileId).startsWith("direct_svc_") ? activeProfileId : "");

    var optionsHtml = ['<option value="">-- 使用工作流平台配置 --</option>'];
    directServices.forEach(function (svc) {
      var selectedAttr = svc.id === chosenServiceId ? " selected" : "";
      optionsHtml.push('<option value="' + escapeWorkflowText(svc.id) + '"' + selectedAttr + '>' + escapeWorkflowText(svc.name) + '</option>');
    });
    select.innerHTML = optionsHtml.join("");

    if (!chosenServiceId) {
      if (paramsDiv) {
        paramsDiv.hidden = true;
      }
      if (costWarning) {
        costWarning.hidden = true;
      }
      if (statusNode) {
        statusNode.textContent = "";
      }
      return;
    }

    if (paramsDiv) {
      paramsDiv.hidden = false;
    }

    var currentSvc = findDirectService(chosenServiceId);
    var catalog = helpers.getDirectServiceCatalogState
      ? helpers.getDirectServiceCatalogState(currentSvc || {})
      : {
        status: currentSvc && currentSvc.modelList && currentSvc.modelList.length ? "available" : "unavailable",
        cacheStatus: currentSvc && currentSvc.modelList && currentSvc.modelList.length ? "valid" : "empty",
        fetchStatus: "not_attempted",
        models: (currentSvc && currentSvc.modelList) || [],
        manualModelAllowed: true,
        usableForSelection: Boolean(currentSvc && currentSvc.modelList && currentSvc.modelList.length)
      };
    var modelList = catalog.usableForSelection ? catalog.models : [];
    var defaultModel = (currentSvc && currentSvc.defaultModel) || "";
    var currentModel = (currentSelection && currentSelection.modelName) || "";

    var modelOptionsHtml = ['<option value="">继承服务默认模型 (' + (escapeWorkflowText(defaultModel) || "未设置") + ')</option>'];
    var isModelInCatalog = false;
    modelList.forEach(function (m) {
      var sel = m === currentModel ? " selected" : "";
      if (sel) {
        isModelInCatalog = true;
      }
      modelOptionsHtml.push('<option value="' + escapeWorkflowText(m) + '"' + sel + '>' + escapeWorkflowText(m) + '</option>');
    });
    var isCustom = currentSelection && currentSelection.customModel !== undefined
      ? Boolean(currentSelection.customModel)
      : Boolean(currentModel && !isModelInCatalog);
    if (currentModel && !isCustom && !isModelInCatalog) {
      modelOptionsHtml.push('<option value="' + escapeWorkflowText(currentModel) + '" selected disabled>当前模型：' + escapeWorkflowText(currentModel) + '（目录不可用）</option>');
    }
    if (modelSelect) {
      modelSelect.innerHTML = modelOptionsHtml.join("");
    }
    if (customCheck) {
      customCheck.checked = isCustom;
      customCheck.disabled = Boolean(!catalog.manualModelAllowed && !isCustom);
      customCheck.title = catalog.usableForSelection
        ? "模型目录可用时不能使用高级手填模型。"
        : "模型目录不可用或已过期时，可手填并在真实调用验证后使用。";
    }
    if (customRow) {
      customRow.hidden = !isCustom;
    }
    if (customInput) {
      customInput.value = isCustom ? currentModel : "";
    }
    if (tempInput) {
      tempInput.value = currentSelection && currentSelection.temperature !== null && currentSelection.temperature !== undefined ? currentSelection.temperature : "";
    }
    if (maxOutInput) {
      maxOutInput.value = currentSelection && currentSelection.maxOutputTokens !== null && currentSelection.maxOutputTokens !== undefined ? currentSelection.maxOutputTokens : "";
    }
    if (contextInput) {
      contextInput.value = currentSelection && currentSelection.contextWindowTokens ? currentSelection.contextWindowTokens : "40000";
    }
    if (costWarning) {
      costWarning.hidden = false;
      costWarning.textContent = "验证调用会真实请求模型，可能产生费用并等待服务返回。";
    }
    if (statusNode) {
      var unavailableReason = currentSelection && currentSelection.modelUnavailableReason;
      if (currentSelection && currentSelection.modelAvailable === false && unavailableReason === "catalog_usable") {
        statusNode.textContent = "模型目录当前可用，不能使用高级手填模型；请从目录选择。";
      } else if (currentSelection && currentSelection.modelAvailable === false && unavailableReason === "cache_expired") {
        statusNode.textContent = "模型目录已过期，不能发起新任务；请先刷新目录。";
      } else if (currentSelection && currentSelection.modelAvailable === false && (unavailableReason === "catalog_unavailable" || unavailableReason === "catalog_empty")) {
        statusNode.textContent = "模型目录当前不可用；请刷新目录，或使用高级手填并验证真实任务调用。";
      } else if (currentSelection && currentSelection.modelAvailable === false) {
        statusNode.textContent = "当前模型已从最新目录移除，不能发起新任务；请重新选择模型。";
      } else if (catalog.fetchStatus === "error" && catalog.cacheStatus === "valid") {
        statusNode.textContent = "目录刷新失败，当前继续使用有效缓存；请留意最近一次错误。";
      } else {
        statusNode.textContent = "";
      }
    }
  }

  function handleTaskDirectServiceSelectChange() {
    var select = byId("ppt-task-direct-service-select");
    var serviceId = select ? select.value : "";
    var paramsDiv = byId("ppt-task-direct-params");
    var modelSelect = byId("ppt-task-model-select");
    var customCheck = byId("ppt-task-custom-model-check");
    var customRow = byId("ppt-task-custom-model-row");
    var customInput = byId("ppt-task-custom-model-input");
    var statusNode = byId("ppt-task-model-validation-status");
    state.lastValidatedCustomModel = null;

    if (!serviceId) {
      if (paramsDiv) {
        paramsDiv.hidden = true;
      }
      return;
    }
    if (paramsDiv) {
      paramsDiv.hidden = false;
    }
    var svc = findDirectService(serviceId);
    var catalog = helpers.getDirectServiceCatalogState
      ? helpers.getDirectServiceCatalogState(svc || {})
      : { usableForSelection: Boolean(svc && svc.modelList && svc.modelList.length), manualModelAllowed: true };
    var modelList = catalog.usableForSelection ? catalog.models : [];
    var defaultModel = (svc && svc.defaultModel) || "";
    var modelOptionsHtml = ['<option value="">继承服务默认模型 (' + (escapeWorkflowText(defaultModel) || "未设置") + ')</option>'];
    modelList.forEach(function (m) {
      modelOptionsHtml.push('<option value="' + escapeWorkflowText(m) + '">' + escapeWorkflowText(m) + '</option>');
    });
    if (modelSelect) {
      modelSelect.innerHTML = modelOptionsHtml.join("");
    }
    if (customCheck) {
      customCheck.checked = false;
      customCheck.disabled = Boolean(!catalog.manualModelAllowed);
      customCheck.title = catalog.usableForSelection
        ? "模型目录可用时不能使用高级手填模型。"
        : "模型目录不可用或已过期时，可手填并在真实调用验证后使用。";
    }
    if (customRow) {
      customRow.hidden = true;
    }
    if (customInput) {
      customInput.value = "";
    }
    if (statusNode) {
      statusNode.textContent = catalog.fetchStatus === "error" && catalog.cacheStatus === "valid"
        ? "目录刷新失败，当前继续使用有效缓存；请留意最近一次错误。"
        : "";
    }
  }

  function handleTaskCustomModelCheckChange() {
    var customCheck = byId("ppt-task-custom-model-check");
    var customRow = byId("ppt-task-custom-model-row");
    var customInput = byId("ppt-task-custom-model-input");
    var isChecked = Boolean(customCheck && customCheck.checked);
    if (customRow) {
      customRow.hidden = !isChecked;
    }
    if (isChecked && customInput && typeof customInput.focus === "function") {
      customInput.focus();
    }
  }

  function getTaskModelSelectionDraft() {
    var serviceId = (byId("ppt-task-direct-service-select") && byId("ppt-task-direct-service-select").value) || "";
    var isCustom = Boolean(byId("ppt-task-custom-model-check") && byId("ppt-task-custom-model-check").checked);
    var modelName = isCustom
      ? (byId("ppt-task-custom-model-input") ? byId("ppt-task-custom-model-input").value.trim() : "")
      : (byId("ppt-task-model-select") ? byId("ppt-task-model-select").value : "");
    var tempVal = byId("ppt-task-temperature") ? byId("ppt-task-temperature").value : "";
    var maxOutVal = byId("ppt-task-max-output") ? byId("ppt-task-max-output").value : "";
    var contextVal = byId("ppt-task-context") ? byId("ppt-task-context").value : "";

    return {
      serviceId: serviceId,
      modelName: modelName,
      customModel: isCustom,
      temperature: tempVal !== "" ? Number(tempVal) : null,
      maxOutputTokens: maxOutVal !== "" ? Number(maxOutVal) : null,
      contextWindowTokens: contextVal !== "" ? Number(contextVal) : 40000
    };
  }

  function validateTaskModelSelection() {
    var draft = getTaskModelSelectionDraft();
    var taskType = getSettingsWorkflowTaskType();
    var statusNode = byId("ppt-task-model-validation-status");
    var costWarning = byId("ppt-task-model-cost-warning");
    var currentSvc = findDirectService(draft.serviceId);
    if (!draft.serviceId || state.workflowProfileMutationBusy) {
      if (statusNode) {
        statusNode.textContent = "请先选择直连服务。";
      }
      return;
    }
    var checked = helpers.validateTaskModelSelectionDraft
      ? helpers.validateTaskModelSelectionDraft(draft, { service: currentSvc })
      : { ok: Boolean(draft.serviceId) };
    if (!checked.ok) {
      if (statusNode) {
        statusNode.textContent = checked.message || checked.error || "请检查参数设置。";
      }
      return;
    }
    if (statusNode) {
      statusNode.textContent = "正在验证调用（会真实请求模型，可能产生费用）...";
    }
    if (costWarning) {
      costWarning.hidden = false;
      costWarning.textContent = "验证调用会真实请求模型，可能产生费用并等待服务返回。";
    }
    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    var operationId = state.directServiceOperationId;
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    return request("/provider/task-model-selections/" + encodeURIComponent(taskType) + "/validate", draft)
      .then(function (body) {
        if (state.directServiceOperationId !== operationId || getSettingsWorkflowTaskType() !== taskType) {
          return { superseded: true };
        }
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        if (draft.customModel && draft.modelName) {
          state.lastValidatedCustomModel = {
            serviceId: draft.serviceId,
            modelName: draft.modelName
          };
        } else {
          state.lastValidatedCustomModel = null;
        }
        var result = body && body.data && body.data.validation ? body.data.validation : (body && body.data) || {};
        if (statusNode) {
          statusNode.textContent = (result.costWarning || result.mayIncurModelCost)
            ? "验证成功（真实调用，可能产生费用）。"
            : "验证成功！模型可正常调用。";
        }
        if (costWarning && result.costWarning) {
          costWarning.textContent = result.costWarning;
        }
      }).catch(function (error) {
        if (state.directServiceOperationId !== operationId || getSettingsWorkflowTaskType() !== taskType) {
          return { superseded: true };
        }
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        if (statusNode) {
          statusNode.textContent = "验证失败：" + describeFetchError(error);
        }
      });
  }

  function saveTaskModelSelection() {
    var draft = getTaskModelSelectionDraft();
    var taskType = getSettingsWorkflowTaskType();
    var statusNode = byId("ppt-task-model-validation-status");
    var currentSvc = findDirectService(draft.serviceId);
    if (!draft.serviceId || state.workflowProfileMutationBusy) {
      setStatus("请先选择直连服务。");
      return;
    }
    var checked = helpers.validateTaskModelSelectionDraft
      ? helpers.validateTaskModelSelectionDraft(draft, { service: currentSvc })
      : { ok: Boolean(draft.serviceId) };
    if (!checked.ok) {
      if (statusNode) {
        statusNode.textContent = checked.message || checked.error || "请检查参数设置。";
      }
      return;
    }
    if (draft.customModel) {
      var validatedCustom = state.lastValidatedCustomModel;
      var customValidated = typeof validatedCustom === "string"
        ? validatedCustom === draft.modelName
        : Boolean(validatedCustom && validatedCustom.serviceId === draft.serviceId && validatedCustom.modelName === draft.modelName);
      if (!customValidated) {
        if (statusNode) {
          statusNode.textContent = "请先验证调用；验证会真实请求模型并可能产生费用。";
        }
        return;
      }
      draft.customModelValidated = true;
    }
    state.directServiceOperationId = Number(state.directServiceOperationId || 0) + 1;
    var operationId = state.directServiceOperationId;
    var activationSaved = false;
    if (typeof setWorkflowProfileMutationBusy === "function") {
      setWorkflowProfileMutationBusy(true);
    } else {
      state.workflowProfileMutationBusy = true;
    }
    return request("/provider/direct-services/" + encodeURIComponent(draft.serviceId) + "/activate", {
      taskType: taskType,
      taskModelSelection: draft
    }).then(function (body) {
        if (state.directServiceOperationId !== operationId || getSettingsWorkflowTaskType() !== taskType) {
          return { superseded: true };
        }
        activationSaved = true;
        state.workflowProfileSelections[taskType] = draft.serviceId;
        if (body && body.data && body.data.taskModelSelection) {
          state.taskModelSelections[taskType] = body.data.taskModelSelection;
        }
        var wfPromise = typeof loadProfiles === "function" ? loadProfiles() : Promise.resolve();
        return Promise.all([
          wfPromise,
          loadDirectServices(undefined, undefined, operationId)
        ]).then(function () {
          if (state.directServiceOperationId !== operationId || getSettingsWorkflowTaskType() !== taskType) {
            return { superseded: true };
          }
          if (typeof setWorkflowProfileMutationBusy === "function") {
            setWorkflowProfileMutationBusy(false);
          } else {
            state.workflowProfileMutationBusy = false;
          }
          var taskLabel = taskType === "ppt.structure_review" ? "结构审查" : "智能总结";
          setStatus(taskLabel + "接入直连服务已保存并设为当前。");
          if (statusNode) {
            statusNode.textContent = "已保存并设为当前。";
          }
        });
      }).catch(function (error) {
        if (state.directServiceOperationId !== operationId || getSettingsWorkflowTaskType() !== taskType) {
          return { superseded: true };
        }
        if (typeof setWorkflowProfileMutationBusy === "function") {
          setWorkflowProfileMutationBusy(false);
        } else {
          state.workflowProfileMutationBusy = false;
        }
        if (statusNode) {
          statusNode.textContent = activationSaved
            ? "已保存，但刷新列表失败：" + describeFetchError(error)
            : "保存失败：" + describeFetchError(error);
        }
        if (activationSaved) {
          setStatus("任务接入已保存，但刷新最新列表失败：" + describeFetchError(error));
        }
      });
  }

  function validateActiveDirectTaskSelection(taskType) {
    var taskStatus = (state.taskApiKeys && state.taskApiKeys[taskType]) || {};
    var selection = (state.taskModelSelections && state.taskModelSelections[taskType]) || {};
    var activeProfileId = String(taskStatus.activeProfileId || "").trim();
    var serviceId = "";
    var service;

    if (taskStatus.accessMethod !== "direct_model") {
      return { valid: true, ok: true, applicable: false, error: "" };
    }
    if (activeProfileId) {
      serviceId = activeProfileId;
    } else if (selection.serviceId) {
      serviceId = String(selection.serviceId).trim();
    } else if (taskStatus.serviceId) {
      serviceId = String(taskStatus.serviceId).trim();
    } else {
      return { valid: true, ok: true, applicable: false, error: "" };
    }

    service = findDirectService(serviceId);
    if (helpers.validateDirectTaskSelectionReadiness) {
      return helpers.validateDirectTaskSelectionReadiness(
        Object.assign({}, selection, { serviceId: serviceId }),
        service,
        Object.assign({}, taskStatus, { accessMethod: "direct_model" })
      );
    }
    return { valid: true, ok: true };
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
        loadProfiles(requestId, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
        loadDirectServices(requestId, { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS })
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
    var pres = getActivePresentation();
    var currentDocSession = (helpers.getDocumentSessionId && pres) ? helpers.getDocumentSessionId(pres) : "";
    if (active.documentSessionId && currentDocSession && active.documentSessionId !== currentDocSession) {
      return;
    }
    if (!state.documentSessionId && currentDocSession) {
      state.documentSessionId = currentDocSession;
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
    if (active.documentSessionId && helpers.claimTaskSlot) {
      helpers.claimTaskSlot(state.activeTaskSlots, "wpp", PPT_WORKFLOW_TASK_TYPE, active.documentSessionId, active.jobId);
    }
    setInterruptedRetryVisible(false);
    setRunDisabled(true);
    setStatus("正在恢复未完成的智能总结任务...");
    showProgressText("任务编号已恢复，正在继续查询模型后台状态。");
    pollPptSlideJob(active.jobId);
  }

  function resumeStructureReviewJob() {
    if (state.jobId || state.currentView === "settings") {
      return;
    }
    var pres = typeof getActivePresentation === "function" ? getActivePresentation() : null;
    var currentDocSession = (helpers.getDocumentSessionId && pres) ? helpers.getDocumentSessionId(pres) : (state.documentSessionId || "");
    var active = loadStructureActiveJob(currentDocSession);
    if (!active || !active.jobId) {
      return;
    }
    if (active.documentSessionId && currentDocSession && active.documentSessionId !== currentDocSession) {
      return;
    }
    if (!state.documentSessionId && currentDocSession) {
      state.documentSessionId = currentDocSession;
    }

    return request("/ppt/structure-review/jobs/" + encodeURIComponent(active.jobId) + "?resume=1", null, {
      timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
        clearStructureActiveJob(active.jobId, currentDocSession);
        return;
      }
      if (job.status === "queued" || job.status === "running") {
        if (state.jobId) {
          return;
        }
        state.jobId = active.jobId;
        state.startedAt = active.startedAt || Date.now();
        state.pollErrors = 0;
        state.resumeExpected = true;
        if (active.documentSessionId && helpers.claimTaskSlot) {
          helpers.claimTaskSlot(state.activeTaskSlots, "wpp", PPT_STRUCTURE_WORKFLOW_TASK_TYPE, active.documentSessionId, active.jobId);
        }
        byId("btn-resubmit-structure-review").hidden = true;
        setRunDisabled(true);
        setStatus("正在恢复未完成的结构审查任务...");
        var progress = describeStructureProgress(job, active.jobId);
        byId("structure-result-output").textContent =
          "任务编号已恢复，正在继续查询模型后台状态。\n" + progress.detail;
        setStructureJobActionVisibility(job);
        setTimeout(function () { pollStructureReviewJob(active.jobId, currentDocSession); }, PPT_SLIDE_POLL_INTERVAL_MS);
      }
    }).catch(function (error) {
      if (error && (error.adapterCode === "LONG_TASK_NOT_FOUND" || error.adapterCode === "PPT_STRUCTURE_JOB_INTERRUPTED")) {
        clearStructureActiveJob(active.jobId, currentDocSession);
      }
    });
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

  function updateHistoryBadge() {
    var badges = [byId("history-unread-badge"), byId("structure-history-unread-badge")];
    var count = state.historyUnreadCount || 0;
    badges.forEach(function (badge) {
      if (!badge) {
        return;
      }
      if (count > 0) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.hidden = false;
      } else {
        badge.hidden = true;
        badge.textContent = "0";
      }
    });
  }

  function switchHistoryView(open) {
    state.historyOpen = Boolean(open);
    var isStructure = state.taskMode === "pptStructureReview";
    var summarySection = byId("summary-result-section");
    var structureSection = byId("structure-result-section");
    var historyView = byId("ppt-history-view");
    if (summarySection) {
      summarySection.hidden = state.historyOpen || isStructure;
    }
    if (structureSection) {
      structureSection.hidden = state.historyOpen || !isStructure;
    }
    if (historyView) {
      historyView.hidden = !state.historyOpen;
    }
    if (state.historyOpen) {
      state.historyUnreadCount = 0;
      updateHistoryBadge();
      loadAndRenderHistory();
    } else {
      if (isStructure) {
        if (state.structureResult) {
          renderStructureResult(state.structureResult);
        }
      } else {
        if (state.result) {
          renderResult(state.result);
        }
      }
    }
  }

  function loadAndRenderHistory() {
    var contentEl = byId("ppt-history-content");
    if (contentEl) {
      contentEl.innerHTML = '<div class="ppt-history-empty">正在加载历史记录...</div>';
    }
    var taskType = typeof homeWorkflowTaskType === "function"
      ? homeWorkflowTaskType()
      : (typeof PPT_WORKFLOW_TASK_TYPE !== "undefined" ? PPT_WORKFLOW_TASK_TYPE : "ppt.slide_assistant");
    request("/history?taskType=" + encodeURIComponent(taskType), null, {
      timeoutMs: 8000
    }).then(function (body) {
      var data = body && body.data;
      var items = (data && Array.isArray(data.items)) ? data.items : (Array.isArray(data) ? data : []);
      state.historyItems = items;
      if (contentEl) {
        contentEl.innerHTML = helpers.renderHistoryList(state.historyItems);
      }
    }).catch(function (error) {
      if (contentEl) {
        contentEl.innerHTML = '<div class="ppt-history-empty">读取历史记录失败：' + (helpers.escapeHtml ? helpers.escapeHtml(error.message) : error.message) + '</div>';
      }
    });
  }

  function handleClearHistory() {
    var taskType = typeof homeWorkflowTaskType === "function"
      ? homeWorkflowTaskType()
      : (typeof PPT_WORKFLOW_TASK_TYPE !== "undefined" ? PPT_WORKFLOW_TASK_TYPE : "ppt.slide_assistant");
    request("/history?taskType=" + encodeURIComponent(taskType), null, {
      method: "DELETE",
      timeoutMs: 8000
    }).then(function () {
      state.historyItems = [];
      var contentEl = byId("ppt-history-content");
      if (contentEl) {
        contentEl.innerHTML = helpers.renderHistoryList([]);
      }
      setStatus("历史记录已清空。");
    }).catch(function (error) {
      setStatus("清空历史记录失败：" + error.message);
    });
  }

  function handleHistoryContentClick(event) {
    var target = event.target;
    if (!target) {
      return;
    }
    var viewBtn = target.closest ? target.closest(".btn-history-view") : null;
    var copyBtn = target.closest ? target.closest(".btn-history-copy") : null;
    var deleteBtn = target.closest ? target.closest(".btn-history-delete") : null;

    if (viewBtn) {
      var id = viewBtn.getAttribute("data-history-id");
      handleHistoryViewItem(id, viewBtn);
      return;
    }
    if (copyBtn) {
      var copyId = copyBtn.getAttribute("data-history-id");
      handleHistoryCopyItem(copyId);
      return;
    }
    if (deleteBtn) {
      var deleteId = deleteBtn.getAttribute("data-history-id");
      handleHistoryDeleteItem(deleteId);
      return;
    }
  }

  function handleHistoryViewItem(id, btn) {
    var item = null;
    for (var i = 0; i < state.historyItems.length; i += 1) {
      if (state.historyItems[i].id === id) {
        item = state.historyItems[i];
        break;
      }
    }
    if (!item) {
      return;
    }
    var card = btn.closest ? btn.closest(".ppt-history-card") : null;
    if (!card) {
      return;
    }
    var existingDetail = card.querySelector(".ppt-history-card-detail");
    if (existingDetail) {
      if (existingDetail.hidden) {
        existingDetail.hidden = false;
        btn.textContent = "收起";
      } else {
        existingDetail.hidden = true;
        btn.textContent = "查看";
      }
      return;
    }
    var detailDiv = document.createElement("div");
    detailDiv.className = "ppt-history-card-detail";
    detailDiv.style.marginTop = "8px";
    detailDiv.style.paddingTop = "8px";
    detailDiv.style.borderTop = "1px dashed var(--hairline, #e2e8f0)";
    detailDiv.style.fontSize = "12px";
    detailDiv.style.lineHeight = "1.5";

    var result = item.result || {};
    var html = "";
    var actionsDiv = card.querySelector(".ppt-history-card-actions");
    if (result.resultType === "structure_review" || item.taskType === PPT_STRUCTURE_WORKFLOW_TASK_TYPE) {
      var summaryParts = [];
      if (result.reviewedRange) {
        var r = result.reviewedRange;
        summaryParts.push("审查范围：第 " + (r.startSlide || 1) + "–" + (r.endSlide || "-") + " 页");
      }
      if (result.overallStoryline) {
        summaryParts.push("整体主线：" + result.overallStoryline);
      }
      if (result.reviewConclusion) {
        summaryParts.push("审查结论：" + result.reviewConclusion);
      }
      var countParts = [];
      if (result.highPriorityIssueCount !== undefined) {
        countParts.push("高优先级问题：" + result.highPriorityIssueCount + " 项");
      }
      if (result.generalSuggestionCount !== undefined) {
        countParts.push("一般建议：" + result.generalSuggestionCount + " 项");
      }
      if (result.slideRecommendationCount !== undefined) {
        countParts.push("逐页建议：" + result.slideRecommendationCount + " 项");
      }
      if (countParts.length) {
        summaryParts.push("问题统计：" + countParts.join("，"));
      }

      var summaryText = summaryParts.join("\n\n") || result.plainText || result.reviewConclusion || "暂无摘要";
      var summaryHtml = '<pre style="white-space:pre-wrap;margin:0;font-family:inherit;">' + (helpers.escapeHtml ? helpers.escapeHtml(summaryText) : summaryText) + '</pre>';

      var reportId = result.reportId || result.jobId || item.jobId;
      var nowSeconds = Date.now() / 1000;
      var isExpired = Boolean(result.reportExpiresAt && nowSeconds >= result.reportExpiresAt);

      if (isExpired) {
        detailDiv.innerHTML = summaryHtml + '<div class="history-report-expired" style="color:var(--danger, #dc2626);margin-top:6px;">专用报告已过期。</div>';
        if (actionsDiv) {
          card.insertBefore(detailDiv, actionsDiv);
        } else {
          card.appendChild(detailDiv);
        }
        btn.textContent = "收起";
        return;
      }

      if (reportId) {
        detailDiv.innerHTML = summaryHtml + '<div class="history-detail-loading" style="color:var(--muted, #666);margin-top:6px;">正在读取完整审查报告...</div>';
        if (actionsDiv) {
          card.insertBefore(detailDiv, actionsDiv);
        } else {
          card.appendChild(detailDiv);
        }
        btn.textContent = "收起";
        return request("/ppt/structure-review/jobs/" + encodeURIComponent(reportId) + "?resume=1", null, {
          timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS
        }).then(function (body) {
          var job = body.data || {};
          if (job.status === "completed" && job.result) {
            var fullResult = job.result;
            var fullText = fullResult.plainText || fullResult.reviewConclusion || summaryText;
            detailDiv.innerHTML = '<pre style="white-space:pre-wrap;margin:0;font-family:inherit;">' + (helpers.escapeHtml ? helpers.escapeHtml(fullText) : fullText) + '</pre>';
          } else {
            detailDiv.innerHTML = summaryHtml + '<div class="history-report-expired" style="color:var(--danger, #dc2626);margin-top:6px;">专用报告已过期或不可用。</div>';
          }
        }).catch(function () {
          detailDiv.innerHTML = summaryHtml + '<div class="history-report-expired" style="color:var(--danger, #dc2626);margin-top:6px;">专用报告已过期或不可用。</div>';
        });
      }

      html = summaryHtml;
    } else if (result.resultType === "document" || result.slides) {
      var md = helpers.buildPptDocumentPlainText(result);
      html = '<pre style="white-space:pre-wrap;margin:0;font-family:inherit;">' + (helpers.escapeHtml ? helpers.escapeHtml(md) : md) + '</pre>';
    } else {
      var slideMd = helpers.buildPptSlideMarkdown(result);
      html = helpers.renderMarkdown ? helpers.renderMarkdown(slideMd) : (helpers.escapeHtml ? helpers.escapeHtml(slideMd) : slideMd);
    }
    detailDiv.innerHTML = html;
    if (actionsDiv) {
      card.insertBefore(detailDiv, actionsDiv);
    } else {
      card.appendChild(detailDiv);
    }
    btn.textContent = "收起";
  }

  function handleHistoryCopyItem(id) {
    var item = null;
    for (var i = 0; i < state.historyItems.length; i += 1) {
      if (state.historyItems[i].id === id) {
        item = state.historyItems[i];
        break;
      }
    }
    if (!item) {
      setStatus("未找到对应历史记录。");
      return;
    }
    var res = item.result || {};
    var text = "";
    if (res.resultType === "structure_review" || item.taskType === PPT_STRUCTURE_WORKFLOW_TASK_TYPE) {
      text = res.plainText || res.reviewConclusion || res.overallStoryline || (res.summary ? (res.summary.overview || "") : "");
    } else if (res.resultType === "document" || res.slides) {
      text = helpers.buildPptDocumentPlainText(res);
    } else {
      text = helpers.buildPptSlidePlainText(res);
    }
    if (!text) {
      text = res.rawAnswer || res.plainText || JSON.stringify(res, null, 2);
    }
    copyText(text, "历史结果已复制。");
  }

  function handleHistoryDeleteItem(id) {
    if (!id) {
      return;
    }
    request("/history/" + encodeURIComponent(id), null, {
      method: "DELETE",
      timeoutMs: 8000
    }).then(function () {
      state.historyItems = state.historyItems.filter(function (it) {
        return it.id !== id;
      });
      var container = byId("ppt-history-content");
      if (container) {
        container.innerHTML = helpers.renderHistoryList(state.historyItems);
      }
      setStatus("已删除该条历史记录。");
    }).catch(function (error) {
      setStatus("删除历史记录失败：" + error.message);
    });
  }

  function bindEvents() {
    var btnViewHistory = byId("btn-view-history");
    if (btnViewHistory) {
      btnViewHistory.addEventListener("click", function () {
        switchHistoryView(true);
      });
    }
    var btnViewStructureHistory = byId("btn-view-structure-history");
    if (btnViewStructureHistory) {
      btnViewStructureHistory.addEventListener("click", function () {
        switchHistoryView(true);
      });
    }
    var btnHistoryBack = byId("btn-history-back");
    if (btnHistoryBack) {
      btnHistoryBack.addEventListener("click", function () {
        switchHistoryView(false);
      });
    }
    var btnClearHistory = byId("btn-clear-history");
    if (btnClearHistory) {
      btnClearHistory.addEventListener("click", handleClearHistory);
    }
    var historyContent = byId("ppt-history-content");
    if (historyContent) {
      historyContent.addEventListener("click", handleHistoryContentClick);
    }
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
    byId("task-model-config-trigger").addEventListener("click", handleTaskModelConfigTriggerClick);
    byId("task-model-config-trigger").addEventListener("keydown", handleTaskModelConfigKeydown);
    byId("task-model-config-menu").addEventListener("click", handleTaskModelConfigMenuClick);
    byId("task-model-config-menu").addEventListener("keydown", handleTaskModelConfigKeydown);
    bindTaskModelConfigPress(byId("task-model-config-trigger"));
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
      var strip = byId("workflow-profile-strip");
      if (state.taskModelConfigMenu && state.taskModelConfigMenu.open && strip && !strip.contains(event.target)) {
        closeTaskModelConfigMenu(false);
      }
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
    if (helpers.bindDirectServiceEvents) {
      helpers.bindDirectServiceEvents({
        byId: byId,
        handlers: {
          openCreate: function () { openDirectServiceEditor("create", ""); },
          listAction: handleDirectServiceAction,
          closeEditor: closeDirectServiceEditor,
          saveEditor: saveDirectServiceEditor,
          refreshModels: refreshDirectServiceModelsInEditor,
          validateService: validateDirectService,
          cancelDelete: hideDirectServiceDeleteDialog,
          confirmDelete: confirmDirectServiceDelete,
          clearKey: clearDirectServiceApiKey,
          editorInput: function (id, event) {
            if (state.directServiceEditor) {
              state.directServiceEditor.dirty = true;
            }
            if (id === "direct-service-url") {
              updateDirectServiceUrlImpact();
            }
          },
          taskServiceChange: handleTaskDirectServiceSelectChange,
          customModelChange: handleTaskCustomModelCheckChange,
          validateTaskSelection: validateTaskModelSelection,
          saveTaskSelection: saveTaskModelSelection
        }
      });
    }
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
