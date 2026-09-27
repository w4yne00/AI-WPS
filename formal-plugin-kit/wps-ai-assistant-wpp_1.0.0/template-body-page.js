(function (root, factory) {
  var exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  if (typeof window !== "undefined") {
    window.createTemplateBodyPage = exports.createTemplateBodyPage;
    window.evaluateSlideTextCapacity = exports.evaluateSlideTextCapacity;
    window.MAX_POINTS = exports.MAX_POINTS;
    window.MAX_CHARACTERS = exports.MAX_CHARACTERS;
    window.MAX_ESTIMATED_LINES = exports.MAX_ESTIMATED_LINES;
    window.CHARS_PER_LINE = exports.CHARS_PER_LINE;
    window.TEMPLATE_LAYOUT_NAME = exports.TEMPLATE_LAYOUT_NAME;
  }
  if (root) {
    root.createTemplateBodyPage = exports.createTemplateBodyPage;
    root.evaluateSlideTextCapacity = exports.evaluateSlideTextCapacity;
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
      var lines = len === 0 ? 0 : Math.max(1, Math.ceil(len / CHARS_PER_LINE));
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
      status: "idle", // idle, running, completed, failed, cancelled, OVERFLOW_REJECTED
      phase: "",
      jobId: "",
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
        render(Object.assign({}, currentState));
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

    function startGenerate(params) {
      var p = params || {};
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

      currentState.status = "running";
      currentState.phase = "preparing";
      currentState.jobId = clientJobId;
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
        instruction: p.instruction || "",
        userFacts: p.userFacts || ""
      };

      return request("/ppt/template-page/jobs", payload, { method: "POST" })
        .then(function (startResp) {
          if (!startResp || !startResp.success) {
            var msg = (startResp && startResp.message) || "发起任务失败";
            throw new Error(msg);
          }
          var jobId = (startResp.data && startResp.data.jobId) || clientJobId;
          currentState.jobId = jobId;
          return _pollJob(jobId, sessionId);
        });
    }

    function _pollJob(jobId, sessionId) {
      return new Promise(function (resolve, reject) {
        function check() {
          if (currentState.status === "cancelled") {
            resolve({ status: "CANCELLED" });
            return;
          }

          var url = "/ppt/template-page/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(sessionId);
          request(url, null, { method: "GET" })
            .then(function (resp) {
              if (!resp || !resp.success) {
                throw new Error((resp && resp.message) || "查询任务失败");
              }
              var data = resp.data || {};
              currentState.phase = data.phase || currentState.phase;

              if (data.status === "completed") {
                var res = data.result || {};
                var capacity = evaluateSlideTextCapacity(res.keyPoints || []);

                if (capacity.isOverflow) {
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
      if (currentState.status !== "running") {
        return Promise.resolve();
      }
      var jobId = currentState.jobId;
      var sessionId = getSessionId();
      currentState.status = "cancelled";
      currentState.phase = "cancelling";
      notify();

      if (!jobId) {
        return Promise.resolve();
      }

      return request("/ppt/template-page/jobs/" + encodeURIComponent(jobId) + "/cancel", {
        documentSessionId: sessionId
      }, { method: "POST" }).catch(function () {
        // swallow cancel network error
      });
    }

    function getState() {
      return Object.assign({}, currentState);
    }

    return {
      getCandidatePage: getCandidatePage,
      startGenerate: startGenerate,
      cancelJob: cancelJob,
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
    createTemplateBodyPage: createTemplateBodyPage
  };
});
