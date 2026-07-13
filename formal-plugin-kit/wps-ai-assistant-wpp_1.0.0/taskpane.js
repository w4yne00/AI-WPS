(function () {
  "use strict";

  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";
  var TASK_API_KEY_DEFS = [
    { taskType: "ppt.slide_assistant", label: "PPT 单页助手" }
  ];
  var PPT_SLIDE_POLL_INTERVAL_MS = 3000;
  var PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS = 10000;
  var PPT_SLIDE_POLL_MAX_ERRORS = 240;
  var PPT_SLIDE_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY = "ai-wps-ppt-slide-assistant-active-job-v1";
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
    jobId: "",
    startedAt: 0,
    pollErrors: 0,
    profiles: { activeProfileId: "", profiles: [] },
    selectedProfileId: "",
    diagnosticsText: ""
  };

  function byId(id) { return document.getElementById(id); }
  function safeText(value) { return String(value === null || typeof value === "undefined" ? "" : value).replace(/\r/g, "").trim(); }
  function setStatus(message) { if (byId("status-line")) { byId("status-line").textContent = message || ""; } }
  function getWppApplication() { return window.Application || window.wps || {}; }
  function queryMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    return match ? decodeURIComponent(match[1]) : "pptSlideAssistant";
  }

  function request(path, payload, options) {
    var settings = options || {};
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) { controller.abort(); } }, settings.timeoutMs || 15000);
    var fetchOptions = {
      method: settings.method || (payload === null || typeof payload === "undefined" ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" }
    };
    if (controller) { fetchOptions.signal = controller.signal; }
    if (payload !== null && typeof payload !== "undefined") { fetchOptions.body = JSON.stringify(payload); }
    return fetch(ADAPTER_BASE_URL + path, fetchOptions).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        var error;
        if (!response.ok || body.success === false) {
          error = new Error((body.errors && body.errors[0] && body.errors[0].message) || body.message || ("HTTP " + response.status));
          error.adapterCode = body.errors && body.errors[0] && body.errors[0].code;
          throw error;
        }
        return body;
      });
    }).finally(function () { clearTimeout(timer); });
  }

  function buildPptSlideClientJobId() {
    return ["client-ppt-slide", Date.now().toString(36), Math.random().toString(36).slice(2, 10)].join("-");
  }

  function loadActiveJob() {
    try {
      var raw = window.localStorage && window.localStorage.getItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) { return null; }
  }

  function saveActiveJob(job) {
    try {
      if (window.localStorage && job && job.jobId) {
        window.localStorage.setItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY, JSON.stringify(job));
      }
    } catch (error) { /* In-memory polling remains available. */ }
  }

  function clearActiveJob(jobId) {
    try {
      var active = loadActiveJob();
      if (!jobId || !active || !active.jobId || active.jobId === jobId) {
        window.localStorage.removeItem(PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY);
      }
    } catch (error) { /* Cleanup must not block rendering. */ }
  }

  function setSummary(payload) {
    var slide = payload && payload.slide ? payload.slide : {};
    var adjacent = [slide.previousTitle ? "前一页" : "", slide.nextTitle ? "后一页" : ""].filter(Boolean).join("、") || "无";
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
    output.textContent = text || "";
  }

  function updateCopyButtons(rawOnly) {
    ["btn-copy-title", "btn-copy-bullets", "btn-copy-conclusion"].forEach(function (id) {
      byId(id).disabled = !state.result || rawOnly;
    });
    byId("btn-copy-result").disabled = !state.result;
  }

  function renderResult(result) {
    var raw = safeText(result && result.rawAnswer);
    state.result = result || {};
    state.resultMode = "preview";
    byId("result-view-switch").hidden = false;
    if (raw) {
      setPlainResult(raw);
      updateCopyButtons(true);
    } else {
      byId("result-output").innerHTML = helpers.renderMarkdown(helpers.buildPptSlideMarkdown(state.result));
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
    if (!state.result) { return; }
    state.resultMode = mode === "plain" ? "plain" : "preview";
    raw = safeText(state.result.rawAnswer);
    if (state.resultMode === "plain" || raw) {
      setPlainResult(raw || state.result.plainText || helpers.buildPptSlidePlainText(state.result));
    } else {
      byId("result-output").innerHTML = helpers.renderMarkdown(helpers.buildPptSlideMarkdown(state.result));
    }
    updateViewButtons();
  }

  function isFatalPollError(error) {
    return error && (error.adapterCode === "PPT_SLIDE_JOB_NOT_FOUND" || error.adapterCode === "REQUEST_VALIDATION_FAILED");
  }

  function schedulePoll(jobId, delay) { setTimeout(function () { pollPptSlideJob(jobId); }, delay); }

  function pollPptSlideJob(jobId) {
    if (!jobId || state.jobId !== jobId) { return; }
    request("/ppt/slide-assistant/jobs/" + encodeURIComponent(jobId), null, { timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS })
      .then(function (body) {
        var job = body.data || {};
        if (state.jobId !== jobId) { return; }
        state.pollErrors = 0;
        saveActiveJob({ jobId: jobId, traceId: body.traceId || job.traceId || "", startedAt: state.startedAt });
        if (job.status === "completed") {
          clearActiveJob(jobId); state.jobId = ""; byId("btn-run-primary").disabled = false;
          renderResult(job.result || {}); setStatus("PPT 本页内容已生成。"); return;
        }
        if (job.status === "failed") {
          clearActiveJob(jobId); state.jobId = ""; byId("btn-run-primary").disabled = false;
          setStatus("生成失败"); setPlainResult((job.error && job.error.message) || "后台任务执行失败。"); return;
        }
        setStatus("模型后台正在处理 PPT 本页内容...");
        setPlainResult([job.runningMessage || "模型后台正在处理。", "已等待：" + (job.elapsedSeconds || 0) + " 秒", "任务编号：" + jobId].join("\n"));
        schedulePoll(jobId, PPT_SLIDE_POLL_INTERVAL_MS);
      })
      .catch(function (error) {
        var elapsed = Date.now() - (state.startedAt || Date.now());
        var within;
        if (state.jobId !== jobId) { return; }
        state.pollErrors += 1;
        if (isFatalPollError(error)) {
          clearActiveJob(jobId); state.jobId = ""; byId("btn-run-primary").disabled = false;
          setStatus("状态查询失败"); setPlainResult(error.message); return;
        }
        within = state.pollErrors <= PPT_SLIDE_POLL_MAX_ERRORS && elapsed <= PPT_SLIDE_POLL_MAX_WAIT_MS;
        saveActiveJob({ jobId: jobId, startedAt: state.startedAt });
        setStatus(within ? "状态查询暂时失败，继续等待模型后台..." : "连接中断，正在低频恢复查询...");
        setPlainResult("任务编号已保留，不会重复提交。\n最近错误：" + error.message);
        schedulePoll(jobId, within ? PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS : PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS);
      });
  }

  function submitPptSlideJob(payload) {
    var clientJobId = payload.clientJobId;
    state.jobId = clientJobId; state.startedAt = Date.now(); state.pollErrors = 0;
    saveActiveJob({ jobId: clientJobId, startedAt: state.startedAt });
    setStatus("正在提交 PPT 单页任务...");
    request("/ppt/slide-assistant/jobs", payload, { timeoutMs: PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS })
      .then(function (body) {
        var job = body.data || {};
        var jobId = job.jobId || clientJobId;
        if (state.jobId !== clientJobId) { return; }
        state.jobId = jobId;
        saveActiveJob({ jobId: jobId, traceId: body.traceId || "", startedAt: state.startedAt });
        if (job.status === "completed") {
          clearActiveJob(jobId); state.jobId = ""; byId("btn-run-primary").disabled = false; renderResult(job.result || {}); return;
        }
        setStatus("任务已提交，模型后台处理中..."); pollPptSlideJob(jobId);
      })
      .catch(function (error) {
        if (isFatalPollError(error)) {
          clearActiveJob(clientJobId); state.jobId = ""; byId("btn-run-primary").disabled = false; setStatus("提交失败"); setPlainResult(error.message); return;
        }
        setStatus("提交响应未确认，正在按任务编号恢复查询..."); pollPptSlideJob(clientJobId);
      });
  }

  function runPptSlideAssistant() {
    var button = byId("btn-run-primary");
    button.disabled = true;
    state.result = null; byId("result-view-switch").hidden = true; updateCopyButtons(false);
    setStatus("正在读取当前幻灯片..."); setPlainResult("正在读取当前幻灯片，请稍候。");
    setTimeout(function () {
      var payload;
      var instruction;
      var bodyCount;
      try {
        payload = helpers.extractPresentationSlide(getWppApplication(), PPT_EXTRACTION_LIMITS);
        instruction = safeText(byId("ppt-slide-instruction").value).slice(0, 1000);
        bodyCount = (payload.slide.textBlocks || []).join("").replace(/\s/g, "").length;
        setSummary(payload);
        if (bodyCount < 20 && !instruction) {
          button.disabled = false; setStatus("请填写本页主题或生成要求。"); setPlainResult("当前页正文内容不足，请填写本页主题或生成要求。"); return;
        }
        payload.userInstruction = instruction;
        payload.clientJobId = buildPptSlideClientJobId();
        submitPptSlideJob(payload);
      } catch (error) {
        button.disabled = false; setStatus("读取失败"); setPlainResult("读取当前幻灯片失败：" + error.message);
      }
    }, 0);
  }

  function copyText(text, successMessage) {
    var value = safeText(text);
    var area;
    if (!value) { setStatus("暂无可复制的内容。"); return; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () { setStatus(successMessage); }).catch(function () { copyTextFallback(value, successMessage); });
      return;
    }
    area = copyTextFallback(value, successMessage);
    return area;
  }

  function copyTextFallback(value, message) {
    var area = document.createElement("textarea");
    area.value = value; area.setAttribute("readonly", "readonly"); area.style.position = "fixed"; area.style.left = "-9999px";
    document.body.appendChild(area); area.select();
    try { document.execCommand("copy"); setStatus(message); } catch (error) { setStatus("复制失败，请手动选择结果文本。"); }
    document.body.removeChild(area);
  }

  function activeProfileName() {
    var found = (state.profiles.profiles || []).filter(function (item) { return item.id === state.profiles.activeProfileId; })[0];
    return found ? found.name : "尚未配置";
  }

  function renderProfileStrip() {
    var select = byId("workflow-profile-select");
    if (!select) { return; }
    select.innerHTML = "";
    if (!state.profiles.profiles.length) {
      select.innerHTML = '<option value="">尚未配置工作流</option>';
    } else {
      state.profiles.profiles.forEach(function (profile) {
        var option = document.createElement("option"); option.value = profile.id;
        option.textContent = profile.name + (profile.keyConfigured ? "" : "（密钥未配置）");
        option.selected = profile.id === (state.selectedProfileId || state.profiles.activeProfileId); select.appendChild(option);
      });
    }
    byId("workflow-profile-current").textContent = "当前：" + activeProfileName();
    byId("btn-activate-workflow-profile").disabled = !state.selectedProfileId || state.selectedProfileId === state.profiles.activeProfileId;
  }

  function renderProfileManager() {
    var manager = byId("workflow-profile-manager");
    var html = ['<div class="profile-create"><input id="profile-create-name" maxlength="40" placeholder="工作流名称" />',
      '<input id="profile-create-key" type="password" placeholder="API Key" />',
      '<input id="profile-create-note" maxlength="200" placeholder="备注（选填）" />',
      '<button data-profile-action="create" type="button">保存工作流</button></div>'];
    if (!manager) { return; }
    state.profiles.profiles.forEach(function (profile) {
      var id = helpers.escapeHtml(profile.id); var active = profile.id === state.profiles.activeProfileId;
      html.push('<div class="profile-row" data-profile-id="' + id + '"><strong>' + helpers.escapeHtml(profile.name) + (active ? "（当前）" : "") + '</strong>');
      html.push('<input data-name="' + id + '" maxlength="40" value="' + helpers.escapeHtml(profile.name) + '" />');
      html.push('<input data-note="' + id + '" maxlength="200" value="' + helpers.escapeHtml(profile.note) + '" placeholder="备注" />');
      html.push('<input data-key="' + id + '" type="password" placeholder="输入新 API Key" />');
      html.push('<div class="profile-actions">' + (!active ? '<button data-profile-action="activate" data-profile-id="' + id + '">设为当前</button>' : "") +
        '<button data-profile-action="update" data-profile-id="' + id + '">保存名称</button><button data-profile-action="key" data-profile-id="' + id + '">更换密钥</button>' +
        (!active ? '<button data-profile-action="delete" data-profile-id="' + id + '">删除</button>' : "") + '</div></div>');
    });
    manager.innerHTML = html.join("");
  }

  function loadProfiles() {
    return request("/provider/workflow-profiles?taskType=" + encodeURIComponent(PPT_WORKFLOW_TASK_TYPE)).then(function (body) {
      state.profiles = helpers.normalizeWorkflowProfiles(body.data || {}); state.selectedProfileId = state.profiles.activeProfileId;
      renderProfileStrip(); renderProfileManager();
    }).catch(function () { state.profiles = { activeProfileId: "", profiles: [] }; renderProfileStrip(); renderProfileManager(); });
  }

  function profileField(kind, id) { return document.querySelector('[data-' + kind + '="' + id + '"]'); }
  function profileAction(event) {
    var action = event.target.getAttribute("data-profile-action"); var id = event.target.getAttribute("data-profile-id") || ""; var path; var payload; var method = "POST";
    if (!action) { return; }
    if (action === "create") {
      payload = { taskType: PPT_WORKFLOW_TASK_TYPE, name: safeText(byId("profile-create-name").value), apiKey: safeText(byId("profile-create-key").value), note: safeText(byId("profile-create-note").value), activate: !state.profiles.profiles.length };
      if (!payload.name || !payload.apiKey) { setStatus("请填写工作流名称和 API Key。"); return; }
      path = "/provider/workflow-profiles";
    } else if (action === "activate") { path = "/provider/workflow-profiles/" + encodeURIComponent(id) + "/activate"; payload = {}; }
    else if (action === "update") { path = "/provider/workflow-profiles/" + encodeURIComponent(id); payload = { name: safeText(profileField("name", id).value), note: safeText(profileField("note", id).value) }; method = "PATCH"; }
    else if (action === "key") { path = "/provider/workflow-profiles/" + encodeURIComponent(id) + "/api-key"; payload = { apiKey: safeText(profileField("key", id).value) }; }
    else if (action === "delete") { path = "/provider/workflow-profiles/" + encodeURIComponent(id); payload = null; method = "DELETE"; }
    request(path, payload, { method: method }).then(function () { setStatus("工作流配置已更新。"); loadProfiles(); }).catch(function (error) { setStatus("工作流配置失败：" + error.message); });
  }

  function refreshDiagnostics() {
    return Promise.all([request("/provider/debug-last"), request("/provider/status"), request("/provider/route-diagnostics"), request("/provider/task-api-keys")]).then(function (items) {
      state.diagnosticsText = JSON.stringify({ lastTask: items[0].data || {}, provider: items[1].data || {}, routes: items[2].data || {}, taskApiKeys: items[3].data || {} }, null, 2);
      byId("diagnostics-output").textContent = state.diagnosticsText;
    }).catch(function (error) { byId("diagnostics-output").textContent = "诊断读取失败：" + error.message; });
  }

  function bindEvents() {
    byId("btn-run-primary").addEventListener("click", runPptSlideAssistant);
    byId("btn-result-preview").addEventListener("click", function () { setResultMode("preview"); });
    byId("btn-result-plain").addEventListener("click", function () { setResultMode("plain"); });
    byId("btn-copy-title").addEventListener("click", function () { copyText(state.result && state.result.suggestedTitle, "标题已复制。"); });
    byId("btn-copy-bullets").addEventListener("click", function () { copyText(state.result && (state.result.bullets || []).map(function (item, index) { return (index + 1) + ". " + item; }).join("\n"), "要点已复制。"); });
    byId("btn-copy-conclusion").addEventListener("click", function () { copyText(state.result && state.result.conclusion, "结论已复制。"); });
    byId("btn-copy-result").addEventListener("click", function () { copyText(state.result && (state.result.rawAnswer || state.result.plainText || helpers.buildPptSlidePlainText(state.result)), "完整结果已复制。"); });
    byId("workflow-profile-select").addEventListener("change", function (event) { state.selectedProfileId = event.target.value; renderProfileStrip(); });
    byId("btn-activate-workflow-profile").addEventListener("click", function () { request("/provider/workflow-profiles/" + encodeURIComponent(state.selectedProfileId) + "/activate", {}).then(loadProfiles); });
    byId("workflow-profile-manager").addEventListener("click", profileAction);
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", function () { copyText(state.diagnosticsText, "诊断信息已复制。"); });
    byId("btn-save-provider-url").addEventListener("click", function () { request("/provider/base-url", { baseUrl: safeText(byId("provider-base-url").value), providerName: "企业大模型接口" }).then(function () { setStatus("模型接口地址已保存。"); }); });
    byId("btn-save-api-key").addEventListener("click", function () { request("/provider/api-key", { apiKey: safeText(byId("provider-api-key").value) }).then(function () { byId("provider-api-key").value = ""; setStatus("统一密钥已保存。"); }); });
    byId("btn-clear-api-key").addEventListener("click", function () { request("/provider/api-key", null, { method: "DELETE" }).then(function () { setStatus("统一密钥已清除。"); }); });
  }

  function resumeJob() {
    var active = loadActiveJob();
    if (!active || !active.jobId || queryMode() === "settings") { return; }
    state.jobId = active.jobId; state.startedAt = active.startedAt || Date.now(); state.pollErrors = 0;
    byId("btn-run-primary").disabled = true; setStatus("正在恢复未完成的 PPT 单页任务..."); pollPptSlideJob(active.jobId);
  }

  function initialize() {
    var settingsMode = queryMode() === "settings";
    byId("home-view").hidden = settingsMode; byId("settings-view").hidden = !settingsMode;
    bindEvents(); loadProfiles();
    if (settingsMode) {
      request("/config").then(function (body) { byId("provider-base-url").value = safeText(body.data && body.data.providerBaseUrl); });
      refreshDiagnostics();
    } else { resumeJob(); }
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", initialize); } else { initialize(); }
}());
