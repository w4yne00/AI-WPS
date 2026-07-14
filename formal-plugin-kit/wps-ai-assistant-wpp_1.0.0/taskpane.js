(function () {
  "use strict";

  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.18.0-alpha";
  var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";
  var TASK_API_KEY_DEFS = [
    { taskType: "ppt.slide_assistant", label: "智能总结" }
  ];
  var PPT_SLIDE_POLL_INTERVAL_MS = 3000;
  var PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS = 10000;
  var PPT_SLIDE_POLL_MAX_ERRORS = 240;
  var PPT_SLIDE_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY = "ai-wps-ppt-slide-assistant-active-job-v1";
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
    resultMode: "preview",
    sourceMode: "slide",
    selectedDocument: null,
    jobId: "",
    jobSourceMode: "",
    busy: false,
    startedAt: 0,
    pollErrors: 0,
    currentView: "home",
    profiles: { activeProfileId: "", profiles: [] },
    selectedProfileId: "",
    diagnosticsText: ""
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function safeText(value) {
    return String(value === null || typeof value === "undefined" ? "" : value)
      .replace(/\r/g, "")
      .trim();
  }

  function setStatus(message) {
    if (byId("status-line")) {
      byId("status-line").textContent = message || "";
    }
  }

  function setHealthBadge(className, text) {
    var node = byId("health-indicator");
    if (!node) {
      return;
    }
    node.className = "badge " + className;
    node.textContent = text;
  }

  function getWppApplication() {
    return window.Application || window.wps || {};
  }

  function queryMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    return match ? decodeURIComponent(match[1]) : "pptSlideAssistant";
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
      "btn-open-settings"
    ].forEach(function (id) {
      if (byId(id)) {
        byId(id).disabled = isDisabled;
      }
    });
    if (byId("btn-activate-workflow-profile")) {
      byId("btn-activate-workflow-profile").disabled = isDisabled ||
        !state.selectedProfileId || state.selectedProfileId === state.profiles.activeProfileId;
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
    output.innerHTML = "";
    output.textContent = text || "";
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
      setPlainResult(result.plainText || result.rawAnswer || "模型后台未返回可显示的文档总结结果。");
      return;
    }
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
    var raw;
    if (result && result.resultType === "document") {
      state.result = helpers.normalizePptDocumentResult(result);
    } else {
      state.result = result || {};
    }
    state.resultMode = "preview";
    byId("result-view-switch").hidden = false;
    raw = safeText(state.result.rawAnswer);
    if (state.result.resultType === "document") {
      renderDocumentPreview();
      updateCopyButtons(false);
    } else if (raw) {
      setPlainResult(raw);
      updateCopyButtons(true);
    } else {
      byId("result-output").innerHTML = helpers.renderMarkdown(
        helpers.buildPptSlideMarkdown(state.result)
      );
      updateCopyButtons(false);
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
    var raw;
    if (!state.result) {
      return;
    }
    state.resultMode = mode === "plain" ? "plain" : "preview";
    raw = safeText(state.result.rawAnswer);
    if (state.result.resultType === "document") {
      if (state.resultMode === "plain") {
        setPlainResult(helpers.buildPptDocumentPlainText(state.result));
      } else {
        renderDocumentPreview();
      }
    } else if (state.resultMode === "plain" || raw) {
      setPlainResult(raw || state.result.plainText || helpers.buildPptSlidePlainText(state.result));
    } else {
      byId("result-output").innerHTML = helpers.renderMarkdown(
        helpers.buildPptSlideMarkdown(state.result)
      );
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
      error.adapterCode === "REQUEST_VALIDATION_FAILED" ||
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
    setRunDisabled(false);
    renderResult(result || {});
    setStatus(result && result.resultType === "document" ? "文档总结已完成。" : "当前页总结已完成。");
  }

  function failJob(jobId, message, statusMessage) {
    var failureMessage = safeText(message) || "后台任务执行失败。";
    clearActiveJob(jobId);
    state.jobId = "";
    state.jobSourceMode = "";
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
      "/ppt/slide-assistant/jobs/" + encodeURIComponent(jobId),
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
      setStatus((state.jobSourceMode || state.sourceMode) === "document"
        ? "模型后台正在生成文档总结方案..."
        : "模型后台正在生成当前页总结...");
      showProgressText([
        job.runningMessage || "模型后台正在处理。",
        "已等待：" + (job.elapsedSeconds || 0) + " 秒",
        "任务编号：" + jobId
      ].join("\n"));
      schedulePoll(jobId, PPT_SLIDE_POLL_INTERVAL_MS);
    }).catch(function (error) {
      var elapsed = Date.now() - (state.startedAt || Date.now());
      var within;
      if (state.jobId !== jobId) {
        return;
      }
      state.pollErrors += 1;
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
      setStatus("任务已提交，模型后台处理中...");
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

  function copyText(text, successMessage) {
    var value = safeText(text);
    if (!value) {
      setStatus("暂无可复制的内容。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () {
        setStatus(successMessage);
      }).catch(function () {
        copyTextFallback(value, successMessage);
      });
      return;
    }
    copyTextFallback(value, successMessage);
  }

  function copyTextFallback(value, message) {
    var area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "readonly");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      setStatus(message);
    } catch (error) {
      setStatus("复制失败，请手动选择结果文本。");
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

  function renderProfileStrip() {
    var select = byId("workflow-profile-select");
    if (!select) {
      return;
    }
    select.innerHTML = "";
    if (!state.profiles.profiles.length) {
      select.innerHTML = '<option value="">尚未配置工作流</option>';
    } else {
      state.profiles.profiles.forEach(function (profile) {
        var option = document.createElement("option");
        option.value = profile.id;
        option.textContent = profile.name + (profile.keyConfigured ? "" : "（密钥未配置）");
        option.selected = profile.id === (state.selectedProfileId || state.profiles.activeProfileId);
        select.appendChild(option);
      });
    }
    byId("workflow-profile-current").textContent = "当前：" + activeProfileName();
    byId("btn-activate-workflow-profile").disabled =
      state.busy || !state.selectedProfileId || state.selectedProfileId === state.profiles.activeProfileId;
  }

  function renderProfileManager() {
    var manager = byId("workflow-profile-manager");
    var html = [
      '<div class="profile-create"><input id="profile-create-name" maxlength="40" placeholder="工作流名称" />',
      '<input id="profile-create-key" type="password" placeholder="API Key" />',
      '<input id="profile-create-note" maxlength="200" placeholder="备注（选填）" />',
      '<button data-profile-action="create" type="button">保存工作流</button></div>'
    ];
    if (!manager) {
      return;
    }
    state.profiles.profiles.forEach(function (profile) {
      var id = helpers.escapeHtml(profile.id);
      var active = profile.id === state.profiles.activeProfileId;
      html.push('<div class="profile-row" data-profile-id="' + id + '"><strong>' +
        helpers.escapeHtml(profile.name) + (active ? "（当前）" : "") + '</strong>');
      html.push('<input data-name="' + id + '" maxlength="40" value="' +
        helpers.escapeHtml(profile.name) + '" />');
      html.push('<input data-note="' + id + '" maxlength="200" value="' +
        helpers.escapeHtml(profile.note) + '" placeholder="备注" />');
      html.push('<input data-key="' + id + '" type="password" placeholder="输入新 API Key" />');
      html.push('<div class="profile-actions">' +
        (!active ? '<button data-profile-action="activate" data-profile-id="' + id + '">设为当前</button>' : "") +
        '<button data-profile-action="update" data-profile-id="' + id + '">保存名称</button>' +
        '<button data-profile-action="key" data-profile-id="' + id + '">更换密钥</button>' +
        (!active ? '<button data-profile-action="delete" data-profile-id="' + id + '">删除</button>' : "") +
        '</div></div>');
    });
    manager.innerHTML = html.join("");
  }

  function loadProfiles() {
    return request(
      "/provider/workflow-profiles?taskType=" + encodeURIComponent(PPT_WORKFLOW_TASK_TYPE)
    ).then(function (body) {
      state.profiles = helpers.normalizeWorkflowProfiles(body.data || {});
      state.selectedProfileId = state.profiles.activeProfileId;
      renderProfileStrip();
      renderProfileManager();
    }).catch(function () {
      state.profiles = { activeProfileId: "", profiles: [] };
      renderProfileStrip();
      renderProfileManager();
    });
  }

  function profileField(kind, id) {
    return document.querySelector('[data-' + kind + '="' + id + '"]');
  }

  function profileAction(event) {
    var action = event.target.getAttribute("data-profile-action");
    var id = event.target.getAttribute("data-profile-id") || "";
    var path;
    var payload;
    var method = "POST";
    if (!action) {
      return;
    }
    if (action === "create") {
      payload = {
        taskType: PPT_WORKFLOW_TASK_TYPE,
        name: safeText(byId("profile-create-name").value),
        apiKey: safeText(byId("profile-create-key").value),
        note: safeText(byId("profile-create-note").value),
        activate: !state.profiles.profiles.length
      };
      if (!payload.name || !payload.apiKey) {
        setStatus("请填写工作流名称和 API Key。");
        return;
      }
      path = "/provider/workflow-profiles";
    } else if (action === "activate") {
      path = "/provider/workflow-profiles/" + encodeURIComponent(id) + "/activate";
      payload = {};
    } else if (action === "update") {
      path = "/provider/workflow-profiles/" + encodeURIComponent(id);
      payload = {
        name: safeText(profileField("name", id).value),
        note: safeText(profileField("note", id).value)
      };
      method = "PATCH";
    } else if (action === "key") {
      path = "/provider/workflow-profiles/" + encodeURIComponent(id) + "/api-key";
      payload = { apiKey: safeText(profileField("key", id).value) };
    } else if (action === "delete") {
      path = "/provider/workflow-profiles/" + encodeURIComponent(id);
      payload = null;
      method = "DELETE";
    }
    request(path, payload, { method: method }).then(function () {
      setStatus("工作流配置已更新。");
      loadProfiles();
    }).catch(function (error) {
      setStatus("工作流配置失败：" + error.message);
    });
  }

  function refreshDiagnostics() {
    return Promise.all([
      request("/provider/debug-last"),
      request("/provider/status"),
      request("/provider/route-diagnostics"),
      request("/provider/task-api-keys")
    ]).then(function (items) {
      state.diagnosticsText = JSON.stringify({
        frontendBuild: FRONTEND_BUILD_VERSION,
        taskDefinitions: TASK_API_KEY_DEFS,
        lastTask: items[0].data || {},
        provider: items[1].data || {},
        routes: items[2].data || {},
        taskApiKeys: items[3].data || {}
      }, null, 2);
      byId("diagnostics-output").textContent = state.diagnosticsText;
    }).catch(function (error) {
      byId("diagnostics-output").textContent = "诊断读取失败：" + error.message;
    });
  }

  function refreshSettings() {
    request("/config").then(function (body) {
      byId("provider-base-url").value = safeText(body.data && body.data.providerBaseUrl);
    }).catch(function () {
      byId("provider-base-url").value = "";
    });
    refreshDiagnostics();
  }

  function checkHealth() {
    setHealthBadge("badge-warn", "检测中");
    return request("/health", null, { timeoutMs: 5000 }).then(function () {
      setHealthBadge("badge-ok", "已连接");
    }).catch(function () {
      setHealthBadge("badge-error", "未连接");
    });
  }

  function resumeJob() {
    var active;
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
    setRunDisabled(true);
    setStatus("正在恢复未完成的智能总结任务...");
    showProgressText("任务编号已恢复，正在继续查询模型后台状态。");
    pollPptSlideJob(active.jobId);
  }

  function switchView(viewName) {
    var settingsMode = viewName === "settings";
    state.currentView = settingsMode ? "settings" : "home";
    byId("home-view").classList.toggle("active", !settingsMode);
    byId("settings-view").classList.toggle("active", settingsMode);
    document.body.setAttribute("data-task-mode", settingsMode ? "settings" : "pptSlideAssistant");
    byId("task-title").textContent = settingsMode ? "设置" : "智能总结";
    byId("btn-open-settings").classList.toggle("is-back", settingsMode);
    byId("btn-open-settings").setAttribute("title", settingsMode ? "返回智能总结" : "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回智能总结" : "打开设置");
    if (settingsMode) {
      refreshSettings();
    } else {
      resumeJob();
    }
  }

  function bindEvents() {
    byId("btn-open-settings").addEventListener("click", function () {
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
    byId("result-output").addEventListener("click", handleDocumentResultCopy);
    byId("workflow-profile-select").addEventListener("change", function (event) {
      state.selectedProfileId = event.target.value;
      renderProfileStrip();
    });
    byId("btn-activate-workflow-profile").addEventListener("click", function () {
      request(
        "/provider/workflow-profiles/" + encodeURIComponent(state.selectedProfileId) + "/activate",
        {}
      ).then(loadProfiles).catch(function (error) {
        setStatus("切换工作流失败：" + error.message);
      });
    });
    byId("workflow-profile-manager").addEventListener("click", profileAction);
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", function () {
      copyText(state.diagnosticsText, "诊断信息已复制。");
    });
    byId("btn-save-provider-url").addEventListener("click", function () {
      request("/provider/base-url", {
        baseUrl: safeText(byId("provider-base-url").value),
        providerName: "企业大模型接口"
      }).then(function () {
        setStatus("模型接口地址已保存。");
        checkHealth();
      }).catch(function (error) {
        setStatus("模型接口地址保存失败：" + error.message);
      });
    });
    byId("btn-save-api-key").addEventListener("click", function () {
      request("/provider/api-key", {
        apiKey: safeText(byId("provider-api-key").value)
      }).then(function () {
        byId("provider-api-key").value = "";
        setStatus("统一密钥已保存。");
      }).catch(function (error) {
        setStatus("统一密钥保存失败：" + error.message);
      });
    });
    byId("btn-clear-api-key").addEventListener("click", function () {
      request("/provider/api-key", null, { method: "DELETE" }).then(function () {
        setStatus("统一密钥已清除。");
      }).catch(function (error) {
        setStatus("统一密钥清除失败：" + error.message);
      });
    });
  }

  function initialize() {
    bindEvents();
    setSourceMode("slide");
    loadProfiles();
    checkHealth();
    switchView(queryMode() === "settings" ? "settings" : "home");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
}());
