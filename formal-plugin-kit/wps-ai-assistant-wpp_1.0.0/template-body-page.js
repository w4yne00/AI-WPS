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

    if (result.isOverflow) {
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
      } else if (typeof pres.Slides.Add === "function") {
        // Fallback: 2 = ppLayoutText / ppLayoutTitleAndContent
        createdSlide = pres.Slides.Add(insertIndex, 2);
      } else {
        throw new Error("当前环境不支持添加幻灯片。");
      }

      var titleText = String(result.title || "").trim();
      var keyPoints = Array.isArray(result.keyPoints) ? result.keyPoints : [];
      var bodyText = keyPoints.join("\r\n");

      var shapes = createdSlide.Shapes;
      var shapeCount = (shapes && shapes.Count) || 0;
      var titleFilled = false;
      var bodyFilled = false;

      // 1. Try Placeholders collection if available
      var placeholders = shapes && shapes.Placeholders;
      var phCount = (placeholders && placeholders.Count) || 0;

      for (var p = 1; p <= phCount; p++) {
        try {
          var ph = placeholders.Item(p);
          if (!ph) continue;
          var pType = ph.PlaceholderFormat ? ph.PlaceholderFormat.Type : 0;
          if ((pType === 1 || pType === 3) && !titleFilled) {
            if (ph.TextFrame && ph.TextFrame.TextRange) {
              ph.TextFrame.TextRange.Text = titleText;
              titleFilled = true;
            }
          } else if ((pType === 2 || pType === 7) && !bodyFilled) {
            if (ph.TextFrame && ph.TextFrame.TextRange) {
              ph.TextFrame.TextRange.Text = bodyText;
              bodyFilled = true;
            }
          }
        } catch (ePh) {}
      }

      // 2. Fallback to general shapes
      if (!titleFilled || !bodyFilled) {
        for (var s = 1; s <= shapeCount; s++) {
          var sh = shapes.Item(s);
          if (!sh) continue;
          var sName = sh.Name || "";
          var sType = sh.PlaceholderFormat ? sh.PlaceholderFormat.Type : 0;
          if (!titleFilled && (sType === 1 || sType === 3 || sName.indexOf("标题") !== -1 || sName.indexOf("Title") !== -1)) {
            if (sh.TextFrame && sh.TextFrame.TextRange) {
              sh.TextFrame.TextRange.Text = titleText;
              titleFilled = true;
            }
          } else if (!bodyFilled && (sType === 2 || sType === 7 || sName.indexOf("内容") !== -1 || sName.indexOf("Body") !== -1 || sName.indexOf("Content") !== -1)) {
            if (sh.TextFrame && sh.TextFrame.TextRange) {
              sh.TextFrame.TextRange.Text = bodyText;
              bodyFilled = true;
            }
          }
        }
      }

      if (!titleFilled && !bodyFilled) {
        throw new Error("未能在新建幻灯片中定位并填充有效占位符。");
      }

      // 3. Notes page
      if (result.speakerNotes && createdSlide.NotesPage && createdSlide.NotesPage.Shapes) {
        try {
          var nShapes = createdSlide.NotesPage.Shapes;
          var nPhs = nShapes.Placeholders;
          var nPhCount = (nPhs && nPhs.Count) || 0;
          var notesFilled = false;
          for (var np = 1; np <= nPhCount; np++) {
            var nph = nPhs.Item(np);
            if (nph && nph.PlaceholderFormat && nph.PlaceholderFormat.Type === 2) {
              if (nph.TextFrame && nph.TextFrame.TextRange) {
                nph.TextFrame.TextRange.Text = String(result.speakerNotes).trim();
                notesFilled = true;
                break;
              }
            }
          }
          if (!notesFilled && nShapes.Item) {
            for (var ns = 1; ns <= (nShapes.Count || 0); ns++) {
              var nsh = nShapes.Item(ns);
              if (nsh && nsh.PlaceholderFormat && nsh.PlaceholderFormat.Type === 2) {
                if (nsh.TextFrame && nsh.TextFrame.TextRange) {
                  nsh.TextFrame.TextRange.Text = String(result.speakerNotes).trim();
                  break;
                }
              }
            }
          }
        } catch (eNotes) {}
      }

      return {
        success: true,
        status: "APPENDED",
        slideIndex: insertIndex,
        initialCount: initialCount,
        newCount: pres.Slides.Count || (initialCount + 1)
      };
    } catch (writeErr) {
      // Reverse Rollback Compensation: delete the created slide and restore count
      if (createdSlide && typeof createdSlide.Delete === "function") {
        try {
          createdSlide.Delete();
        } catch (delErr) {
          if (typeof console !== "undefined" && console.error) {
            console.error("Rollback deletion failed:", delErr);
          }
        }
      }

      return {
        success: false,
        status: "ROLLBACK_COMPENSATED",
        error: writeErr.message || String(writeErr),
        initialCount: initialCount,
        currentCount: pres.Slides.Count || initialCount
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

    function appendSlide(appToUse, resultToUse) {
      if (currentState.writtenToSlide) {
        throw new Error("本页内容已追加写入，请勿重复写入。");
      }
      var res = resultToUse || currentState.result;
      if (!res) {
        throw new Error("尚未生成正文页数据。");
      }
      var app = appToUse || wpsApp;
      var sessionId = getSessionId();

      var writeRes = appendTemplateBodySlide(app, res, {
        expectedSessionId: sessionId,
        sessionId: sessionId
      });

      if (writeRes.success) {
        currentState.writtenToSlide = true;
        currentState.newSlideIndex = writeRes.slideIndex;
        notify();
      }

      return writeRes;
    }

    function getState() {
      return Object.assign({}, currentState);
    }

    return {
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
