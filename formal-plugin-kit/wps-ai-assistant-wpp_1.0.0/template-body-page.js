(function (root, factory) {
  var exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  if (typeof window !== "undefined") {
    window.createTemplateBodyPage = exports.createTemplateBodyPage;
    window.evaluateSlideTextCapacity = exports.evaluateSlideTextCapacity;
    window.appendTemplateBodySlide = exports.appendTemplateBodySlide;
    window.MAX_POINTS = exports.MAX_POINTS;
    window.MAX_CHARACTERS = exports.MAX_CHARACTERS;
    window.MAX_ESTIMATED_LINES = exports.MAX_ESTIMATED_LINES;
    window.CHARS_PER_LINE = exports.CHARS_PER_LINE;
    window.TEMPLATE_LAYOUT_NAME = exports.TEMPLATE_LAYOUT_NAME;
  }
  if (root) {
    root.createTemplateBodyPage = exports.createTemplateBodyPage;
    root.evaluateSlideTextCapacity = exports.evaluateSlideTextCapacity;
    root.appendTemplateBodySlide = exports.appendTemplateBodySlide;
    root.MAX_POINTS = exports.MAX_POINTS;
    root.MAX_CHARACTERS = exports.MAX_CHARACTERS;
    root.MAX_ESTIMATED_LINES = exports.MAX_ESTIMATED_LINES;
    root.CHARS_PER_LINE = exports.CHARS_PER_LINE;
    root.TEMPLATE_LAYOUT_NAME = exports.TEMPLATE_LAYOUT_NAME;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var MAX_POINTS = 4;
  var MAX_CHARACTERS = 260;
  var MAX_ESTIMATED_LINES = 8;
  var CHARS_PER_LINE = 32;
  var TEMPLATE_LAYOUT_NAME = "标题和内容";

  /**
   * Evaluate whether key points exceed the layout capacity.
   * Fail-Closed defense: strictly enforce limits, no silent truncation.
   */
  function evaluateSlideTextCapacity(points) {
    var pts = Array.isArray(points) ? points : (points ? [points] : []);
    var totalPoints = pts.length;
    var totalCharacters = 0;
    var estimatedLines = 0;
    var reasons = [];

    for (var i = 0; i < pts.length; i++) {
      var text = String(pts[i] || "").trim();
      var len = text.length;
      totalCharacters += len;
      var lines = len === 0 ? 0 : text.split(/\r\n|\r|\n/).reduce(function (sum, line) {
        return sum + Math.max(1, Math.ceil(line.length / CHARS_PER_LINE));
      }, 0);
      estimatedLines += lines;
    }

    if (totalPoints > MAX_POINTS) {
      reasons.push("要点数超过4条（当前 " + totalPoints + " 条）");
    }
    if (totalCharacters > MAX_CHARACTERS) {
      reasons.push("总字符数超过260字（当前 " + totalCharacters + " 字）");
    }
    if (estimatedLines > MAX_ESTIMATED_LINES) {
      reasons.push("估计行数超过8行（当前 " + estimatedLines + " 行）");
    }

    return {
      totalPoints: totalPoints,
      totalCharacters: totalCharacters,
      estimatedLines: estimatedLines,
      isOverflow: reasons.length > 0,
      reasons: reasons
    };
  }

  function findCustomLayout(pres, layoutName) {
    if (!pres) return null;
    var targetName = layoutName || TEMPLATE_LAYOUT_NAME;

    // 1. Check pres.SlideMaster.CustomLayouts
    try {
      if (pres.SlideMaster && pres.SlideMaster.CustomLayouts) {
        var count = pres.SlideMaster.CustomLayouts.Count || 0;
        for (var i = 1; i <= count; i++) {
          var layout = pres.SlideMaster.CustomLayouts.Item(i);
          if (layout && layout.Name === targetName) {
            return layout;
          }
        }
      }
    } catch (e) {}

    // 2. Check pres.Designs
    try {
      if (pres.Designs) {
        var designCount = pres.Designs.Count || 1;
        for (var d = 1; d <= designCount; d++) {
          var design = pres.Designs.Item(d);
          if (design && design.SlideMaster && design.SlideMaster.CustomLayouts) {
            var lCount = design.SlideMaster.CustomLayouts.Count || 0;
            for (var j = 1; j <= lCount; j++) {
              var l = design.SlideMaster.CustomLayouts.Item(j);
              if (l && l.Name === targetName) {
                return l;
              }
            }
          }
        }
      }
    } catch (e2) {}

    return null;
  }

  /**
   * Append a new slide at Count + 1 using template layout, fill placeholders,
   * and execute reverse rollback compensation if any error occurs midway.
   */
  function appendTemplateBodySlide(app, result, options) {
    var opts = options || {};
    if (!app || !app.ActivePresentation) {
      throw new Error("未找到当前打开的演示文稿。");
    }

    if (opts.expectedSessionId && opts.sessionId && opts.expectedSessionId !== opts.sessionId) {
      throw new Error("文档会话已变更，禁止跨文档写入。");
    }

    if (!result) {
      throw new Error("缺少要写入的正文页数据。");
    }

    if (result.isOverflow || evaluateSlideTextCapacity(result.keyPoints).isOverflow) {
      throw new Error("排版容量超限，禁止写入幻灯片。");
    }

    var pres = app.ActivePresentation;
    if (!pres.Slides) {
      throw new Error("演示文稿缺少幻灯片集合。");
    }

    var initialCount = pres.Slides.Count || 0;
    var insertIndex = initialCount + 1; // Strictly append to the end!
    var createdSlide = null;

    try {
      var layout = findCustomLayout(pres, opts.layoutName || TEMPLATE_LAYOUT_NAME);
      if (layout && typeof pres.Slides.AddSlide === "function") {
        createdSlide = pres.Slides.AddSlide(insertIndex, layout);
      } else {
        throw new Error(layout ? "当前环境不支持使用固定模板添加幻灯片。" : "未找到固定模板版式：" + TEMPLATE_LAYOUT_NAME);
      }

      var titleText = String(result.title || "").trim();
      var keyPoints = Array.isArray(result.keyPoints) ? result.keyPoints : [];
      var bodyText = keyPoints.join("\r\n");

      function findPlaceholder(shapes, types, names) {
        if (!shapes) return null;
        var collections = shapes.Placeholders ? [shapes.Placeholders, shapes] : [shapes];
        for (var c = 0; c < collections.length; c++) {
          var collection = collections[c];
          for (var i = 1; i <= (collection.Count || 0); i++) {
            var shape = collection.Item(i);
            if (!shape) continue;
            var type = shape.PlaceholderFormat ? shape.PlaceholderFormat.Type : 0;
            if (types.indexOf(type) !== -1 || names.indexOf(shape.Name) !== -1) return shape;
          }
        }
        return null;
      }
      function writeText(shape, text, label) {
        if (!shape || !shape.TextFrame || !shape.TextFrame.TextRange) throw new Error("未找到" + label + "占位符。");
        var range = shape.TextFrame.TextRange;
        range.Text = text;
        function normalize(value) { return String(value || "").replace(/\r\n|\r/g, "\n"); }
        if (normalize(range.Text) !== normalize(text)) throw new Error(label + "写入后核验失败。");
      }
      var shapes = createdSlide.Shapes;
      writeText(findPlaceholder(shapes, [1, 3], ["标题 1", "Title 1"]), titleText, "标题");
      writeText(findPlaceholder(shapes, [2, 7], ["内容占位符 2", "Content Placeholder 2"]), bodyText, "正文");
      var notesShapes = createdSlide.NotesPage && createdSlide.NotesPage.Shapes;
      writeText(findPlaceholder(notesShapes, [2], []), String(result.speakerNotes || "").trim(), "讲稿");
      if (pres.Slides.Count !== initialCount + 1) throw new Error("追加后页数核验失败。");

      return {
        success: true,
        status: "APPENDED",
        slideIndex: insertIndex,
        initialCount: initialCount,
        newCount: pres.Slides.Count || (initialCount + 1)
      };
    } catch (writeErr) {
      var rollbackError = "";
      if (createdSlide) {
        try {
          if (typeof createdSlide.Delete !== "function") throw new Error("当前环境不支持删除新增页。");
          createdSlide.Delete();
        } catch (delErr) { rollbackError = delErr.message || String(delErr); }
      }
      var currentCount;
      try { currentCount = pres.Slides.Count; } catch (countErr) { rollbackError = countErr.message || String(countErr); }
      var recovered = !rollbackError && currentCount === initialCount;
      return {
        success: false,
        status: recovered ? "ROLLBACK_COMPENSATED" : "ROLLBACK_FAILED",
        error: (writeErr.message || String(writeErr)) + (recovered ? " 已恢复原页数。" : " 恢复失败，请人工核查并清理第 " + insertIndex + " 页后再试。"),
        rollbackError: rollbackError,
        slideIndex: insertIndex,
        initialCount: initialCount,
        currentCount: currentCount
      };
    }
  }

  function createTemplateBodyPage(options) {
    var opts = options || {};
    var request = opts.request || function () { return Promise.reject(new Error("no request function")); };
    var storage = opts.storage || { getItem: function () {}, setItem: function () {}, removeItem: function () {} };
    var getSessionId = opts.getSessionId || function () { return "default"; };
    var getConfirmedOutline = opts.getConfirmedOutline || function () { return null; };
    var hasConfirmedOutline = opts.hasConfirmedOutline || function () { return false; };
    var render = opts.render || function () {};
    var schedule = opts.schedule || function (fn, ms) { return setTimeout(fn, ms || 0); };
    var pollIntervalMs = typeof opts.pollIntervalMs === "number" ? opts.pollIntervalMs : 500;
    var wpsApp = opts.wpsApp || (typeof wps !== "undefined" ? wps.WppApplication() : null);

    var currentState = {
      documentSessionId: "",
      outlineSnapshot: "",
      recoveryRequired: false,
      status: "idle", // idle, running, completed, failed, cancelled, OVERFLOW_REJECTED
      phase: "",
      jobId: "",
      clientJobId: "",
      currentCandidate: null,
      result: null,
      error: null,
      isOverflow: false,
      overflowReasons: [],
      writtenToSlide: false,
      newSlideIndex: null
    };

    function notify() {
      try {
        render(getState());
      } catch (e) {
        if (typeof console !== "undefined" && console.error) {
          console.error("render error:", e);
        }
      }
    }

    function getCandidatePage(preferredPageIndex) {
      if (!hasConfirmedOutline()) {
        throw new Error("请先确认逐页大纲后再生成正文页。");
      }
      var outline = getConfirmedOutline();
      if (!outline || !Array.isArray(outline.slides)) {
        throw new Error("未找到有效的大纲页面列表。");
      }

      var slides = outline.slides;
      if (typeof preferredPageIndex === "number") {
        var found = null;
        for (var i = 0; i < slides.length; i++) {
          if (slides[i].pageIndex === preferredPageIndex) {
            found = slides[i];
            break;
          }
        }
        if (!found) {
          throw new Error("页面在大纲中不存在 (页码: " + preferredPageIndex + ")");
        }
        if (found.pageRole !== "content") {
          throw new Error("仅支持生成正文页 (页码: " + preferredPageIndex + ", 角色: " + found.pageRole + ")");
        }
        return found;
      }

      // Default: find first content slide
      for (var j = 0; j < slides.length; j++) {
        if (slides[j].pageRole === "content") {
          return slides[j];
        }
      }
      return null;
    }

    function recoveryKey(sessionId) { return "ppt.template-page-write:" + sessionId; }
    function recoveryFor(sessionId) {
      var raw = storage.getItem(recoveryKey(sessionId));
      var saved = raw ? JSON.parse(raw) : null;
      return saved && saved.status !== "written" ? saved : null;
    }
    function assertNoRecovery() {
      if (recoveryFor(getSessionId()) || (currentState.documentSessionId === getSessionId() && currentState.recoveryRequired)) {
        throw new Error("请先人工核查并恢复残留页，禁止继续追加。");
      }
    }
    function verifyRecovery(appToUse) {
      var sessionId = getSessionId();
      var saved = recoveryFor(sessionId);
      if (!saved) return;
      var app = appToUse || wpsApp;
      if (!app || !app.ActivePresentation || app.ActivePresentation.Slides.Count !== saved.initialCount) {
        throw new Error("请先核查并清理新增页，恢复原页数后再核查。");
      }
      storage.removeItem(recoveryKey(sessionId));
      if (currentState.documentSessionId === sessionId) {
        currentState.recoveryRequired = false;
        currentState.error = null;
      }
      notify();
    }

    function startGenerate(params) {
      var p = params || {};
      try { assertNoRecovery(); } catch (recoveryErr) { return Promise.reject(recoveryErr); }
      if (currentState.status === "running") return Promise.reject(new Error("正文页任务正在运行。"));
      if (!hasConfirmedOutline()) {
        return Promise.reject(new Error("请先确认逐页大纲后再生成正文页。"));
      }

      var candidate;
      try {
        candidate = getCandidatePage(p.pageIndex);
      } catch (err) {
        return Promise.reject(err);
      }

      if (!candidate) {
        return Promise.reject(new Error("大纲中未找到可生成的正文页。"));
      }

      var sessionId = getSessionId();
      var clientJobId = "cjob_tp_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);

      currentState.documentSessionId = sessionId;
      currentState.outlineSnapshot = JSON.stringify(getConfirmedOutline());
      currentState.recoveryRequired = false;
      currentState.status = "running";
      currentState.phase = "preparing";
      currentState.jobId = clientJobId;
      currentState.clientJobId = clientJobId;
      currentState.currentCandidate = candidate;
      currentState.result = null;
      currentState.error = null;
      currentState.isOverflow = false;
      currentState.overflowReasons = [];
      currentState.writtenToSlide = false;
      currentState.newSlideIndex = null;
      notify();

      var payload = {
        documentSessionId: sessionId,
        clientJobId: clientJobId,
        pageIndex: candidate.pageIndex,
        pageRole: "content",
        outlineTitle: candidate.title || ("第 " + candidate.pageIndex + " 页"),
        outlineKeyPoints: Array.isArray(candidate.keyPoints) ? candidate.keyPoints : [],
        outlineFragmentIds: Array.isArray(candidate.fragmentIds) ? candidate.fragmentIds : [],
        instruction: p.instruction || (getConfirmedOutline() || {}).instruction || "",
        userFacts: p.userFacts || (getConfirmedOutline() || {}).userFacts || ""
      };

      return request("/ppt/template-page/jobs", payload, { method: "POST" })
        .then(function (startResp) {
          if (currentState.documentSessionId !== sessionId || currentState.clientJobId !== clientJobId) return { status: "STALE" };
          if (!startResp || !startResp.success) {
            var msg = (startResp && startResp.message) || "发起任务失败";
            throw new Error(msg);
          }
          var jobId = (startResp.data && startResp.data.jobId) || clientJobId;
          currentState.jobId = jobId;
          return _pollJob(jobId, sessionId);
        }).catch(function (err) {
          if (currentState.documentSessionId !== sessionId || currentState.clientJobId !== clientJobId) throw err;
          if (currentState.status === "cancelled") return { status: "CANCELLED" };
          currentState.status = "failed";
          currentState.phase = "failed";
          currentState.error = { message: err.message || String(err) };
          notify();
          throw err;
        });
    }

    function _pollJob(jobId, sessionId) {
      return new Promise(function (resolve, reject) {
        function check() {
          if (currentState.documentSessionId !== sessionId || currentState.jobId !== jobId) { resolve({ status: "STALE" }); return; }
          if (currentState.status === "cancelled") {
            resolve({ status: "CANCELLED" });
            return;
          }

          var url = "/ppt/template-page/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(sessionId);
          request(url, null, { method: "GET" })
            .then(function (resp) {
              if (currentState.documentSessionId !== sessionId || currentState.jobId !== jobId) { resolve({ status: "STALE" }); return; }
              if (currentState.status === "cancelled") { resolve({ status: "CANCELLED" }); return; }
              if (!resp || !resp.success) {
                throw new Error((resp && resp.message) || "查询任务失败");
              }
              var data = resp.data || {};
              currentState.phase = data.phase || currentState.phase;

              if (data.status === "completed") {
                var res = data.result || {};
                var capacity = evaluateSlideTextCapacity(res.keyPoints || []);

                if (capacity.isOverflow || res.isOverflow) {
                  currentState.status = "OVERFLOW_REJECTED";
                  currentState.phase = "overflow_rejected";
                  currentState.isOverflow = true;
                  currentState.overflowReasons = capacity.reasons;
                  currentState.result = res;
                  notify();
                  resolve({
                    status: "OVERFLOW_REJECTED",
                    isOverflow: true,
                    overflowReasons: capacity.reasons,
                    writtenToSlide: false,
                    result: res
                  });
                  return;
                }

                currentState.status = "completed";
                currentState.result = res;
                notify();
                resolve({
                  status: "COMPLETED",
                  isOverflow: false,
                  writtenToSlide: false,
                  result: res
                });
                return;
              }

              if (data.status === "failed") {
                currentState.status = "failed";
                currentState.phase = "failed";
                currentState.error = data.error || { message: "任务生成失败" };
                notify();
                resolve({
                  status: "FAILED",
                  error: currentState.error
                });
                return;
              }

              if (data.status === "cancelled") {
                currentState.status = "cancelled";
                currentState.phase = "cancelled";
                notify();
                resolve({ status: "CANCELLED" });
                return;
              }

              // Still queued / running
              notify();
              schedule(check, pollIntervalMs);
            })
            .catch(function (err) {
              if (currentState.documentSessionId !== sessionId || currentState.jobId !== jobId) { resolve({ status: "STALE" }); return; }
              if (currentState.status === "cancelled") { resolve({ status: "CANCELLED" }); return; }
              currentState.status = "failed";
              currentState.phase = "failed";
              currentState.error = { message: err.message || String(err) };
              notify();
              reject(err);
            });
        }

        schedule(check, 10);
      });
    }

    function cancelJob() {
      if (currentState.status !== "running") return Promise.resolve();
      var jobId = currentState.jobId;
      var clientJobId = currentState.clientJobId;
      var sessionId = currentState.documentSessionId;
      currentState.phase = "stopping";
      notify();
      return request("/ppt/template-page/jobs/" + encodeURIComponent(jobId) + "/cancel", {
        documentSessionId: sessionId
      }, { method: "POST" }).then(function (resp) {
        if (!resp || !resp.success) throw new Error((resp && resp.message) || "取消未获服务器确认，请重试。");
        if (currentState.documentSessionId !== sessionId || currentState.clientJobId !== clientJobId) return;
        if (resp.data && resp.data.status === "cancelled") {
          currentState.status = "cancelled";
          currentState.phase = "cancelled";
          currentState.result = null;
        }
        notify();
      }).catch(function (err) {
        if (currentState.documentSessionId === sessionId && currentState.clientJobId === clientJobId) {
          currentState.error = { message: "取消未确认：" + (err.message || String(err)) };
          notify();
        }
        throw err;
      });
    }

    function appendSlide(appToUse, resultToUse) {
      assertNoRecovery();
      if (currentState.writtenToSlide) {
        throw new Error("本页内容已追加写入，请勿重复写入。");
      }
      if (currentState.documentSessionId !== getSessionId()) throw new Error("文档会话已变更，请回到生成内容所属演示文稿。");
      if (!hasConfirmedOutline() || JSON.stringify(getConfirmedOutline()) !== currentState.outlineSnapshot) {
        throw new Error("大纲或依据已变化，请重新确认并生成正文页。");
      }
      if (currentState.status !== "completed") throw new Error("正文页尚未完成或不可写入。");
      var res = resultToUse || currentState.result;
      if (!res) {
        throw new Error("尚未生成正文页数据。");
      }
      var app = appToUse || wpsApp;
      var sessionId = getSessionId();

      var pres = app && app.ActivePresentation;
      if (!pres || !pres.Slides) throw new Error("未找到当前演示文稿。");
      if (res.isOverflow || evaluateSlideTextCapacity(res.keyPoints).isOverflow) throw new Error("排版容量超限，禁止写入。");
      var initialCount = pres.Slides.Count;
      storage.setItem(recoveryKey(sessionId), JSON.stringify({
        status: "writing", initialCount: initialCount, slideIndex: initialCount + 1, jobId: currentState.jobId
      }));
      var writeRes = appendTemplateBodySlide(app, res, {
        expectedSessionId: currentState.documentSessionId,
        sessionId: sessionId
      });

      if (writeRes.status === "ROLLBACK_COMPENSATED") storage.removeItem(recoveryKey(sessionId));
      if (writeRes.status === "ROLLBACK_FAILED") {
        currentState.recoveryRequired = true;
        currentState.error = { message: writeRes.error };
        notify();
      }
      if (writeRes.success) {
        currentState.writtenToSlide = true;
        currentState.newSlideIndex = writeRes.slideIndex;
        try {
          storage.setItem(recoveryKey(sessionId), JSON.stringify({ status: "written", jobId: currentState.jobId, slideIndex: writeRes.slideIndex }));
        } catch (saveErr) {
          currentState.recoveryRequired = true;
          currentState.error = { message: "已追加，但写入记录保存失败，请人工核查，禁止重复追加。" };
          writeRes.warning = currentState.error.message;
        }
        notify();
      }

      return writeRes;
    }

    function getState() {
      var sessionId = getSessionId();
      var saved = recoveryFor(sessionId);
      var view = currentState.documentSessionId && currentState.documentSessionId !== sessionId ?
        { status: "idle", result: null, documentSessionId: sessionId, error: null } : Object.assign({}, currentState);
      view.recoveryRequired = Boolean(saved || view.recoveryRequired);
      view.canAppend = view.status === "completed" && !view.writtenToSlide && !view.recoveryRequired &&
        hasConfirmedOutline() && JSON.stringify(getConfirmedOutline()) === currentState.outlineSnapshot;
      if (saved) view.recoveryInfo = saved;
      return view;
    }

    return {
      verifyRecovery: verifyRecovery,
      hasConfirmedOutline: hasConfirmedOutline,
      getConfirmedOutline: getConfirmedOutline,
      getCandidatePage: getCandidatePage,
      startGenerate: startGenerate,
      cancelJob: cancelJob,
      appendSlide: appendSlide,
      getState: getState,
      evaluateSlideTextCapacity: evaluateSlideTextCapacity
    };
  }

  return {
    MAX_POINTS: MAX_POINTS,
    MAX_CHARACTERS: MAX_CHARACTERS,
    MAX_ESTIMATED_LINES: MAX_ESTIMATED_LINES,
    CHARS_PER_LINE: CHARS_PER_LINE,
    TEMPLATE_LAYOUT_NAME: TEMPLATE_LAYOUT_NAME,
    evaluateSlideTextCapacity: evaluateSlideTextCapacity,
    appendTemplateBodySlide: appendTemplateBodySlide,
    findCustomLayout: findCustomLayout,
    createTemplateBodyPage: createTemplateBodyPage
  };
});
