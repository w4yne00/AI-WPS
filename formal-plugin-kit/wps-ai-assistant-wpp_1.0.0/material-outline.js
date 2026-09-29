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
    preparing: "正在完整读取资料...",
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

    async function refreshCatalog(sessionId) {
      var s = sessionId ? stateFor(sessionId) : current();
      try {
        var res = await request("/ppt/materials/catalog?documentSessionId=" + encodeURIComponent(s.documentSessionId));
        if (res && res.success && res.data) {
          s.catalogSummary = {
            totalDocuments: res.data.totalDocuments || 0,
            totalCharacters: res.data.totalCharacters || 0,
            documents: res.data.documents || []
          };
          s.catalogLabel = formatCatalogLabel(s.catalogSummary);
          onMaterialsChanged(s.catalogSummary.documents, s.documentSessionId);
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
        await refreshCatalog(s.documentSessionId);
        await detectConflicts(s.documentSessionId);
      }
      return res;
    }

    async function finishDocConversion(stage, sessionId, materialId) {
      var url = materialId ? "/ppt/materials/" + encodeURIComponent(materialId) : "/ppt/materials/import";
      var method = { method: materialId ? "PUT" : "POST" };
      try {
        var app = typeof opts.getWordApp === "function" ? opts.getWordApp() : null;
        if (!app || !app.Documents || typeof app.Documents.Open !== "function") {
          throw new Error("当前 PPT 无法调用 WPS DOC 转换，请另存为 DOCX 后上传。");
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

    async function importMaterial(upload, base64OrMaterialId, docIdentity, sessionId) {
      var s = sessionId ? stateFor(sessionId) : current();
      var fileName = "";
      var contentBase64 = "";
      var materialId = "";
      if (typeof upload === "string") {
        fileName = upload;
        contentBase64 = base64OrMaterialId;
      } else if (upload && typeof upload === "object") {
        fileName = upload.fileName || upload.name;
        contentBase64 = upload.contentBase64;
        materialId = typeof base64OrMaterialId === "string" ? base64OrMaterialId : "";
        if (!contentBase64) {
          if (typeof upload.arrayBuffer === "function") {
            var bytes = new Uint8Array(await upload.arrayBuffer());
            var binary = "";
            for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
            contentBase64 = btoa(binary);
          } else if (typeof FileReader !== "undefined") {
            contentBase64 = await new Promise(function (resolve, reject) {
              var reader = new FileReader();
              reader.onload = function () { resolve(String(reader.result || "").split(",").pop()); };
              reader.onerror = function () { reject(new Error("读取资料文件失败")); };
              reader.readAsDataURL(upload);
            });
          }
        }
      }
      var url = materialId ? ("/ppt/materials/" + encodeURIComponent(materialId)) : "/ppt/materials/import";
      var res = await request(url, {
        documentSessionId: s.documentSessionId,
        documentIdentity: docIdentity || "",
        fileName: fileName,
        contentBase64: contentBase64
      }, { method: materialId ? "PUT" : "POST" });
      if (res && res.data && res.data.conversionRequired) res = await finishDocConversion(res.data, s.documentSessionId, materialId);
      if (res && res.success) {
        await refreshCatalog(s.documentSessionId);
        await detectConflicts(s.documentSessionId);
      }
      return res;
    }

    async function deleteMaterial(materialId) {
      var s = current();
      var res = await request("/ppt/materials/" + encodeURIComponent(materialId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId), null, { method: "DELETE" });
      if (res && res.success) {
        await refreshCatalog(s.documentSessionId);
        await detectConflicts(s.documentSessionId);
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
      if (res && res.data && res.data.conversionRequired) res = await finishDocConversion(res.data, s.documentSessionId, materialId);
      if (res && res.success) {
        await refreshCatalog(s.documentSessionId);
        await detectConflicts(s.documentSessionId);
      }
      return res;
    }

    async function bindDocument(oldSessionId, newIdentity, newSessionId) {
      var old = stateFor(oldSessionId);
      var res;
      try {
        res = await request("/ppt/materials/bind-document", {
          oldDocumentSessionId: oldSessionId,
          newDocumentIdentity: newIdentity || "",
          newDocumentSessionId: newSessionId
        }, { method: "POST" });
        if (!res || !res.success) throw new Error((res && res.message) || "资料绑定失败");
      } catch (error) {
        if (!(error && error.status === 404 && error.adapterCode === "MATERIAL_NOT_FOUND" &&
            !old.result && !old.busy && !old.catalogSummary.totalDocuments)) throw error;
        // No server materials exist yet; first save only migrates the local draft.
        var target = stateFor(newSessionId);
        if (target.result || target.jobId || target.catalogSummary.totalDocuments ||
            target.audience !== DEFAULT_AUDIENCE || target.slideCount !== DEFAULT_SLIDE_COUNT ||
            target.instruction || target.userFacts || target.conflictResolutions.length) return;
      }
      var migrated = clone(old);
      migrated.documentSessionId = newSessionId;
      // The outline belongs to the saved presentation; an old job keeps its original identity.
      migrated.jobId = "";
      migrated.clientJobId = "";
      migrated.pendingRequest = null;
      migrated.busy = false;
      migrated.pollScheduled = false;
      if (res && res.data && Array.isArray(res.data.documents)) {
        migrated.catalogSummary = res.data;
        migrated.catalogLabel = formatCatalogLabel(res.data);
      }
      states[newSessionId] = migrated;
      persist(migrated);
      return res;
    }

    async function detectConflicts(sessionId) {
      var s = sessionId ? stateFor(sessionId) : current();
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

    function onMaterialsChanged(currentDocs, sessionId) {
      var s = sessionId ? stateFor(sessionId) : current();
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
      s.activeDrawerPageIndex = null;
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
        if (s.jobId !== clientJobId || !s.busy) return;
        if (res && res.success && res.data) {
          s.jobId = res.data.jobId || clientJobId;
          s.status = res.data.status || "running";
          s.phase = res.data.phase || "provider_processing";
          s.phaseLabel = OUTLINE_PHASE_TEXT[s.phase] || OUTLINE_PHASE_TEXT.provider_processing;
          persist(s);
          render();
          schedulePoll(s, s.jobId);
        } else {
          throw new Error((res && res.message) || "任务提交失败");
        }
      } catch (err) {
        if (s.jobId !== clientJobId || !s.busy) return;
        s.busy = false;
        s.status = "failed";
        s.phase = "failed";
        s.phaseLabel = OUTLINE_PHASE_TEXT.failed;
        s.error = err.message || "任务提交异常";
        persist(s);
        render();
      }
    }

    async function poll(sessionId, expectedJobId) {
      var s = sessionId ? stateFor(sessionId) : current();
      var jobId = expectedJobId || s.jobId;
      if (!jobId || s.jobId !== jobId || !s.busy) return;
      try {
        var res = await request("/ppt/material-outline/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(s.documentSessionId));
        if (s.jobId !== jobId || !s.busy) return;
        if (!res || !res.success || !res.data) throw new Error("任务状态响应无效");
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
            schedulePoll(s, jobId);
          }
        }
      } catch (err) {
        if (s.jobId !== jobId || !s.busy) return;
        if (err && (err.status === 404 || err.adapterCode === "LONG_TASK_NOT_FOUND")) {
          s.busy = false;
          s.jobId = "";
          s.pendingRequest = null;
          s.status = "interrupted";
          s.phase = "";
          s.phaseLabel = "";
          s.error = "原任务不存在，可能因 Adapter 重启而中断，请重新提交。";
          persist(s);
          render();
        } else {
          s.error = (err && err.message) || "状态查询暂时失败，正在重试。";
          persist(s);
          render();
          schedulePoll(s, jobId);
        }
      }
    }

    function schedulePoll(s, jobId) {
      if (s.pollScheduled === jobId || !s.busy || s.jobId !== jobId) return;
      s.pollScheduled = jobId;
      schedule(function () {
        if (s.pollScheduled === jobId) s.pollScheduled = false;
        return poll(s.documentSessionId, jobId);
      }, 1000);
    }

    async function cancel() {
      var s = current();
      if (!s.jobId || !s.busy) return;
      var jobId = s.jobId;
      try {
        var res = await request("/ppt/material-outline/jobs/" + encodeURIComponent(jobId) + "/cancel", {
          documentSessionId: s.documentSessionId
        }, { method: "POST" });
        if (s.jobId !== jobId) return;
        if (!res || !res.success || !res.data || res.data.status !== "cancelled") {
          throw new Error("服务端尚未确认取消，继续查询任务状态。");
        }
        s.busy = false;
        s.status = "cancelled";
        s.phase = "cancelled";
        s.phaseLabel = OUTLINE_PHASE_TEXT.cancelled;
        s.error = "";
        persist(s);
        render();
        return res;
      } catch (err) {
        if (s.jobId !== jobId) return;
        s.error = "取消失败：" + ((err && err.message) || "请稍后重试");
        persist(s);
        render();
        schedulePoll(s, jobId);
      }
    }

    // Confirmation Gate
    async function openSources(pageIndex) {
      var s = current(), result = s.result;
      s.activeDrawerPageIndex = pageIndex;
      s.sourceImages = {};
      s.sourceImageError = "";
      render();
      var slide = result && (result.slides || []).find(function (p) { return p.pageIndex === pageIndex; });
      if (!slide) return;
      try {
        for (var i = 0; i < (slide.sources || []).length; i++) {
          var src = slide.sources[i];
          if (!src.imageId) continue;
          var basis = (result.basisMaterials || []).find(function (b) { return b.materialId === src.materialId; });
          var response = await request("/ppt/materials/image?documentSessionId=" + encodeURIComponent(s.documentSessionId) +
            "&materialId=" + encodeURIComponent(src.materialId) + "&imageId=" + encodeURIComponent(src.imageId) +
            "&updatedAt=" + encodeURIComponent(basis ? basis.updatedAt : ""), null, { method: "GET" });
          if (current() !== s || s.result !== result || s.activeDrawerPageIndex !== pageIndex) return;
          s.sourceImages[src.imageId] = response.data.imageDataUri;
          render();
        }
      } catch (error) {
        if (current() !== s || s.result !== result || s.activeDrawerPageIndex !== pageIndex) return;
        s.sourceImageError = error.message || "出处图片读取失败";
        render();
      }
    }

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
        if (slide.coreMessage) lines.push("核心观点：" + slide.coreMessage);
        if (slide.presentationAdvice) lines.push("表达建议：" + slide.presentationAdvice);
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
      s.activeDrawerPageIndex = null;
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
      openSources: openSources,
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
