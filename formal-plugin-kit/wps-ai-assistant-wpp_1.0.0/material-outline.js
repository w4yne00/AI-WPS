(function (root, factory) {
  var exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  if (typeof window !== "undefined") {
    window.createMaterialOutline = exports.createMaterialOutline;
    window.DEFAULT_AUDIENCE = exports.DEFAULT_AUDIENCE;
    window.DEFAULT_SLIDE_COUNT = exports.DEFAULT_SLIDE_COUNT;
    window.MIN_SLIDE_COUNT = exports.MIN_SLIDE_COUNT;
    window.MAX_SLIDE_COUNT = exports.MAX_SLIDE_COUNT;
    window.OUTLINE_PHASE_TEXT = exports.OUTLINE_PHASE_TEXT;
    window.PAGE_ROLE_NAMES = exports.PAGE_ROLE_NAMES;
  }
  if (root) {
    root.createMaterialOutline = exports.createMaterialOutline;
    root.DEFAULT_AUDIENCE = exports.DEFAULT_AUDIENCE;
    root.DEFAULT_SLIDE_COUNT = exports.DEFAULT_SLIDE_COUNT;
    root.MIN_SLIDE_COUNT = exports.MIN_SLIDE_COUNT;
    root.MAX_SLIDE_COUNT = exports.MAX_SLIDE_COUNT;
    root.OUTLINE_PHASE_TEXT = exports.OUTLINE_PHASE_TEXT;
    root.PAGE_ROLE_NAMES = exports.PAGE_ROLE_NAMES;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var DEFAULT_AUDIENCE = "公司高管与业务领导";
  var DEFAULT_SLIDE_COUNT = 8;
  var MIN_SLIDE_COUNT = 3;
  var MAX_SLIDE_COUNT = 30;

  var OUTLINE_PHASE_TEXT = {
    queued: "正在排队...",
    preparing: "正在分析资料并建立索引...",
    provider_processing: "正在生成逐页大纲...",
    parsing: "正在校验页数与出处...",
    completed: "逐页大纲生成完成",
    failed: "大纲生成失败",
    cancelled: "任务已取消"
  };

  var PAGE_ROLE_NAMES = {
    cover: "封面页",
    agenda: "目录页",
    transition: "过渡页",
    content: "内容页",
    summary: "总结页",
    backcover: "封底页"
  };

  function createMaterialOutline(options) {
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
        var raw = storage.getItem("ppt.material-outline:" + sessionId);
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
          audience: (saved && saved.audience) || DEFAULT_AUDIENCE,
          slideCount: (saved && typeof saved.slideCount === "number") ? saved.slideCount : DEFAULT_SLIDE_COUNT,
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
          phaseLabel: (saved && saved.phase) ? (OUTLINE_PHASE_TEXT[saved.phase] || saved.phase) : "",
          result: (saved && saved.result) || null,
          error: (saved && saved.error) || "",
          pendingRequest: (saved && saved.pendingRequest) || null,
          busy: Boolean(saved && saved.jobId && (!saved.status || saved.status === "running" || saved.status === "queued")),
          pollScheduled: false,
          activeDrawerPageIndex: null,
          // Confirmation Gate State
          confirmationStatus: (saved && saved.confirmationStatus) || "unconfirmed",
          confirmedOutline: (saved && saved.confirmedOutline) || null,
          confirmedAt: (saved && saved.confirmedAt) || null,
          basisWarning: Boolean(saved && saved.basisWarning)
        };
      }
      return states[sessionId];
    }

    function current() {
      return stateFor(getSessionId());
    }

    function persist(s) {
      try {
        storage.setItem("ppt.material-outline:" + s.documentSessionId, JSON.stringify({
          audience: s.audience,
          slideCount: s.slideCount,
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
          confirmationStatus: s.confirmationStatus,
          confirmedOutline: s.confirmedOutline,
          confirmedAt: s.confirmedAt,
          basisWarning: s.basisWarning
        }));
      } catch (e) {
        // ignore storage errors
      }
    }

    function setAudience(newAudience) {
      var s = current();
      var val = String(newAudience || "").trim();
      if (!val) val = DEFAULT_AUDIENCE;
      if (s.audience !== val) {
        s.audience = val;
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    function setSlideCount(newCount) {
      var s = current();
      var count = parseInt(newCount, 10);
      if (isNaN(count) || count < MIN_SLIDE_COUNT || count > MAX_SLIDE_COUNT) {
        count = DEFAULT_SLIDE_COUNT;
      }
      if (s.slideCount !== count) {
        s.slideCount = count;
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    function setInstruction(newInst) {
      var s = current();
      var val = String(newInst || "").trim();
      if (s.instruction !== val) {
        s.instruction = val;
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    function setUserFacts(newFacts) {
      var s = current();
      var val = String(newFacts || "").trim();
      if (s.userFacts !== val) {
        s.userFacts = val;
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    async function refreshCatalog() {
      var s = current();
      try {
        var res = await request("/ppt/materials/catalog?documentSessionId=" + encodeURIComponent(s.documentSessionId));
        if (res && res.success && res.data) {
          s.catalogSummary = {
            totalDocuments: res.data.totalDocuments || 0,
            totalCharacters: res.data.totalCharacters || 0,
            documents: res.data.documents || []
          };
          s.catalogLabel = formatCatalogLabel(s.catalogSummary);
          onMaterialsChanged(s.catalogSummary.documents);
          persist(s);
          render();
        }
      } catch (e) {
        // Keep current catalog if fetch fails
      }
    }

    async function refreshReusableSources() {
      var s = current();
      try {
        var res = await request("/materials/reusable-sources");
        if (res && res.success && res.data && Array.isArray(res.data.sources)) {
          s.reusableSources = res.data.sources.filter(function (src) {
            return src.documentSessionId !== s.documentSessionId;
          });
          render();
        }
      } catch (e) {
        s.reusableSources = [];
      }
    }

    async function cloneFromSource(sourceSessionId, targetIdentity) {
      var s = current();
      var res = await request("/ppt/materials/clone-from-source", {
        sourceSessionId: sourceSessionId,
        targetDocumentSessionId: s.documentSessionId,
        targetDocumentIdentity: targetIdentity || ""
      }, { method: "POST" });
      if (res && res.success) {
        await refreshCatalog();
      }
      return res;
    }

    async function importMaterial(fileName, base64Content, docIdentity) {
      var s = current();
      var res = await request("/ppt/materials/import", {
        documentSessionId: s.documentSessionId,
        documentIdentity: docIdentity || "",
        fileName: fileName,
        contentBase64: base64Content
      }, { method: "POST" });
      if (res && res.success) {
        await refreshCatalog();
      }
      return res;
    }

    async function deleteMaterial(materialId) {
      var s = current();
      var res = await request("/ppt/materials/" + encodeURIComponent(materialId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "DELETE" });
      if (res && res.success) {
        await refreshCatalog();
      }
      return res;
    }

    async function updateMaterial(materialId, fileName, base64Content) {
      var s = current();
      var res = await request("/ppt/materials/" + encodeURIComponent(materialId), {
        documentSessionId: s.documentSessionId,
        fileName: fileName,
        contentBase64: base64Content
      }, { method: "PUT" });
      if (res && res.success) {
        await refreshCatalog();
      }
      return res;
    }

    async function bindDocument(oldSessionId, newIdentity, newSessionId) {
      var res = await request("/ppt/materials/bind-document", {
        oldDocumentSessionId: oldSessionId,
        newDocumentIdentity: newIdentity || "",
        newDocumentSessionId: newSessionId
      }, { method: "POST" });
      return res;
    }

    async function detectConflicts() {
      var s = current();
      try {
        var res = await request("/ppt/material-outline/conflicts", {
          documentSessionId: s.documentSessionId,
          userFacts: s.userFacts
        }, { method: "POST" });
        if (res && res.success && res.data && Array.isArray(res.data.conflicts)) {
          s.conflicts = res.data.conflicts;
          render();
        }
      } catch (e) {
        s.conflicts = [];
      }
    }

    function setConflictResolution(conflictId, optionId, value) {
      var s = current();
      var existing = s.conflictResolutions.filter(function (c) {
        return c.conflictId !== conflictId;
      });
      existing.push({
        conflictId: conflictId,
        chosenCandidateId: optionId,
        chosenValue: value
      });
      s.conflictResolutions = existing;
      if (s.confirmationStatus === "confirmed") {
        s.confirmationStatus = "needs_reconfirmation";
      }
      persist(s);
      render();
    }

    function onMaterialsChanged(currentDocs) {
      var s = current();
      if (!s.result || !s.result.basisMaterials || !s.result.basisMaterials.length) {
        s.basisWarning = false;
        return;
      }
      var docMap = {};
      (currentDocs || []).forEach(function (d) {
        docMap[d.materialId] = d;
      });

      var changed = false;
      for (var i = 0; i < s.result.basisMaterials.length; i++) {
        var basis = s.result.basisMaterials[i];
        var cur = docMap[basis.materialId];
        if (!cur || cur.updatedAt !== basis.updatedAt) {
          changed = true;
          break;
        }
      }
      if (changed) {
        s.basisWarning = true;
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
      } else {
        s.basisWarning = false;
      }
    }

    async function submit() {
      var s = current();
      if (s.busy) return;
      s.error = "";
      s.busy = true;
      s.status = "running";
      s.phase = "preparing";
      s.phaseLabel = OUTLINE_PHASE_TEXT.preparing;

      var clientJobId = "job_outline_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8);
      s.clientJobId = clientJobId;
      s.jobId = clientJobId;

      var reqPayload = {
        documentSessionId: s.documentSessionId,
        clientJobId: clientJobId,
        audience: s.audience,
        slideCount: s.slideCount,
        instruction: s.instruction,
        userFacts: s.userFacts,
        conflictResolutions: s.conflictResolutions
      };
      s.pendingRequest = clone(reqPayload);
      persist(s);
      render();

      try {
        var res = await request("/ppt/material-outline/jobs", reqPayload, { method: "POST" });
        if (res && res.success && res.data) {
          s.jobId = res.data.jobId || clientJobId;
          s.status = res.data.status || "running";
          s.phase = res.data.phase || "provider_processing";
          s.phaseLabel = OUTLINE_PHASE_TEXT[s.phase] || OUTLINE_PHASE_TEXT.provider_processing;
          persist(s);
          render();
          schedulePoll();
        } else {
          throw new Error((res && res.message) || "任务提交失败");
        }
      } catch (err) {
        s.busy = false;
        s.status = "failed";
        s.phase = "failed";
        s.phaseLabel = OUTLINE_PHASE_TEXT.failed;
        s.error = err.message || "任务提交异常";
        persist(s);
        render();
      }
    }

    async function poll() {
      var s = current();
      if (!s.jobId) return;
      try {
        var res = await request("/ppt/material-outline/jobs/" + encodeURIComponent(s.jobId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId));
        if (res && res.success && res.data) {
          var job = res.data;
          s.status = job.status || s.status;
          s.phase = job.phase || s.phase;
          s.phaseLabel = OUTLINE_PHASE_TEXT[s.phase] || job.phase;

          if (job.status === "completed") {
            s.busy = false;
            s.result = job.result;
            s.confirmationStatus = "unconfirmed";
            s.confirmedOutline = null;
            s.confirmedAt = null;
            s.basisWarning = false;
            persist(s);
            render();
          } else if (job.status === "failed") {
            s.busy = false;
            s.error = (job.error && job.error.message) || "逐页大纲生成失败";
            persist(s);
            render();
          } else if (job.status === "cancelled") {
            s.busy = false;
            s.phaseLabel = OUTLINE_PHASE_TEXT.cancelled;
            persist(s);
            render();
          } else {
            // Still running or queued
            persist(s);
            render();
            schedulePoll();
          }
        }
      } catch (err) {
        // retry on transient network errors
        schedulePoll();
      }
    }

    function schedulePoll() {
      var s = current();
      if (s.pollScheduled || !s.busy) return;
      s.pollScheduled = true;
      schedule(function () {
        s.pollScheduled = false;
        poll();
      }, 1000);
    }

    async function cancel() {
      var s = current();
      if (!s.jobId || !s.busy) return;
      try {
        var res = await request("/ppt/material-outline/jobs/" + encodeURIComponent(s.jobId) + "/cancel", {
          documentSessionId: s.documentSessionId
        }, { method: "POST" });
        s.busy = false;
        s.status = "cancelled";
        s.phase = "cancelled";
        s.phaseLabel = OUTLINE_PHASE_TEXT.cancelled;
        persist(s);
        render();
        return res;
      } catch (err) {
        s.busy = false;
        s.status = "cancelled";
        persist(s);
        render();
      }
    }

    // Confirmation Gate
    function confirmOutline() {
      var s = current();
      if (!s.result || !s.result.slides || !s.result.slides.length) {
        return null;
      }
      s.confirmedOutline = clone(s.result);
      s.confirmationStatus = "confirmed";
      s.confirmedAt = new Date().toISOString();
      persist(s);
      render();
      return s.confirmedOutline;
    }

    function hasConfirmedOutline() {
      var s = current();
      return s.confirmationStatus === "confirmed" && Boolean(s.confirmedOutline);
    }

    function getConfirmedOutline() {
      var s = current();
      return s.confirmedOutline;
    }

    function updateSlideTitle(pageIndex, newTitle) {
      var s = current();
      if (!s.result || !s.result.slides) return;
      var slide = s.result.slides.find(function (item) { return item.pageIndex === pageIndex; });
      if (slide) {
        slide.title = String(newTitle || "").trim();
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    function updateSlideKeyPoints(pageIndex, keyPoints) {
      var s = current();
      if (!s.result || !s.result.slides) return;
      var slide = s.result.slides.find(function (item) { return item.pageIndex === pageIndex; });
      if (slide) {
        slide.keyPoints = Array.isArray(keyPoints) ? keyPoints.slice() : [String(keyPoints || "").trim()];
        if (s.confirmationStatus === "confirmed") {
          s.confirmationStatus = "needs_reconfirmation";
        }
        persist(s);
        render();
      }
    }

    function formatOutlineMarkdown(outline) {
      if (!outline || !outline.slides) return "";
      var lines = [];
      lines.push("# PPT 逐页演示大纲");
      lines.push("- 汇报对象：" + (outline.audience || DEFAULT_AUDIENCE));
      lines.push("- 幻灯片数：" + (outline.slideCount || outline.slides.length) + " 页");
      if (outline.instruction) {
        lines.push("- 重点要求：" + outline.instruction);
      }
      lines.push("");

      outline.slides.forEach(function (slide) {
        var roleLabel = PAGE_ROLE_NAMES[slide.pageRole] || slide.pageRole || "内容页";
        lines.push("## 第 " + slide.pageIndex + " 页（" + roleLabel + "）：" + (slide.title || ""));
        if (slide.keyPoints && slide.keyPoints.length) {
          slide.keyPoints.forEach(function (point) {
            lines.push("- " + point);
          });
        }
        if (slide.missingItems && slide.missingItems.length) {
          slide.missingItems.forEach(function (missing) {
            lines.push("- 〔待补充：" + missing + "〕");
          });
        }
        lines.push("");
      });
      return lines.join("\n").trim();
    }

    function copyOutlineMarkdown() {
      var s = current();
      if (!s.result) return;
      var text = formatOutlineMarkdown(s.result);
      copyText(text);
      return text;
    }

    function clearResult() {
      var s = current();
      s.result = null;
      s.confirmedOutline = null;
      s.confirmationStatus = "unconfirmed";
      s.confirmedAt = null;
      s.status = "idle";
      s.phase = "";
      s.phaseLabel = "";
      s.error = "";
      persist(s);
      render();
    }

    return {
      stateFor: stateFor,
      current: current,
      setAudience: setAudience,
      setSlideCount: setSlideCount,
      setInstruction: setInstruction,
      setUserFacts: setUserFacts,
      refreshCatalog: refreshCatalog,
      refreshReusableSources: refreshReusableSources,
      cloneFromSource: cloneFromSource,
      importMaterial: importMaterial,
      deleteMaterial: deleteMaterial,
      updateMaterial: updateMaterial,
      bindDocument: bindDocument,
      detectConflicts: detectConflicts,
      setConflictResolution: setConflictResolution,
      onMaterialsChanged: onMaterialsChanged,
      submit: submit,
      poll: poll,
      cancel: cancel,
      confirmOutline: confirmOutline,
      hasConfirmedOutline: hasConfirmedOutline,
      getConfirmedOutline: getConfirmedOutline,
      updateSlideTitle: updateSlideTitle,
      updateSlideKeyPoints: updateSlideKeyPoints,
      formatOutlineMarkdown: formatOutlineMarkdown,
      copyOutlineMarkdown: copyOutlineMarkdown,
      clearResult: clearResult
    };
  }

  return {
    createMaterialOutline: createMaterialOutline,
    DEFAULT_AUDIENCE: DEFAULT_AUDIENCE,
    DEFAULT_SLIDE_COUNT: DEFAULT_SLIDE_COUNT,
    MIN_SLIDE_COUNT: MIN_SLIDE_COUNT,
    MAX_SLIDE_COUNT: MAX_SLIDE_COUNT,
    OUTLINE_PHASE_TEXT: OUTLINE_PHASE_TEXT,
    PAGE_ROLE_NAMES: PAGE_ROLE_NAMES
  };
});
