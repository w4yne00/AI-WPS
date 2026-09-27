(function (root, factory) {
  var exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  var host = root || (typeof globalThis !== "undefined" ? globalThis : this);
  if (typeof window !== "undefined") {
    window.createTemplateDeck = exports.createTemplateDeck;
    window.appendTemplateDeck = exports.appendTemplateDeck;
  }
  host.createTemplateDeck = exports.createTemplateDeck;
  host.appendTemplateDeck = exports.appendTemplateDeck;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var ROLE_LABELS = { cover: "封面", agenda: "目录", transition: "章节页", content: "正文页" };
  var EXCLUDED_LABELS = { summary: "总结", backcover: "封底" };
  var LAYOUTS = { cover: "标题幻灯片", content: "标题和内容", agenda: "节标题", transition: "两栏内容" };

  function slotLimit(role) {
    if (role === "agenda") return 3;
    if (role === "cover" || role === "transition") return 1;
    return 4;
  }

  function isOverflow(role, points) {
    return (points || []).length > slotLimit(role);
  }

  function fingerprint(pages) {
    return JSON.stringify((pages || []).map(function (page) {
      return {
        pageId: page.pageId,
        pageRole: page.pageRole,
        title: page.title,
        keyPoints: page.keyPoints,
        speakerNotes: page.speakerNotes
      };
    }));
  }

  function shapesOf(slide) {
    var shapes = [];
    var collection = slide && slide.Shapes;
    var count = collection ? (collection.Count || 0) : 0;
    for (var i = 1; i <= count; i++) shapes.push(collection.Item(i));
    return shapes;
  }

  function findLayout(pres, name) {
    var masters = [];
    if (pres.SlideMaster && pres.SlideMaster.CustomLayouts) masters.push(pres.SlideMaster.CustomLayouts);
    if (pres.Designs) {
      var designCount = pres.Designs.Count || 0;
      for (var i = 1; i <= designCount; i++) {
        var design = pres.Designs.Item(i);
        if (design && design.SlideMaster && design.SlideMaster.CustomLayouts) masters.push(design.SlideMaster.CustomLayouts);
      }
    }
    for (var m = 0; m < masters.length; m++) {
      var layouts = masters[m];
      for (var j = 1; j <= (layouts.Count || 0); j++) {
        var layout = layouts.Item(j);
        if (layout && layout.Name === name) return layout;
      }
    }
    return null;
  }

  function findShape(shapes, types, names) {
    for (var i = 0; i < shapes.length; i++) {
      var shape = shapes[i];
      var type = shape.PlaceholderFormat ? shape.PlaceholderFormat.Type : 0;
      if (types.indexOf(type) !== -1 || names.indexOf(shape.Name) !== -1) return shape;
    }
    return null;
  }

  function writeText(shape, text, label) {
    if (!shape || !shape.TextFrame || !shape.TextFrame.TextRange) throw new Error("未找到" + label + "。");
    var range = shape.TextFrame.TextRange;
    range.Text = text;
    var normalize = function (value) { return String(value || "").replace(/\r\n|\r/g, "\n"); };
    if (normalize(range.Text) !== normalize(text)) throw new Error(label + "写入后核验失败。");
  }

  function writeNotes(slide, text) {
    var notes = slide.NotesPage && slide.NotesPage.Shapes;
    var found = null;
    if (notes) {
      for (var i = 1; i <= (notes.Count || 0); i++) {
        var shape = notes.Item(i);
        var type = shape.PlaceholderFormat ? shape.PlaceholderFormat.Type : 0;
        if (type === 2 || shape.Name === "备注") {
          found = shape;
          break;
        }
      }
    }
    writeText(found, String(text || ""), "讲稿");
  }

  function agendaSlots(slide) {
    var shapes = shapesOf(slide).filter(function (shape) {
      var type = shape.PlaceholderFormat ? shape.PlaceholderFormat.Type : 0;
      return !type && shape.TextFrame;
    });
    var lefts = shapes.map(function (shape) { return shape.Left; }).sort(function (a, b) { return a - b; });
    var median = lefts.length ? lefts[Math.floor(lefts.length / 2)] : 0;
    return shapes.filter(function (shape) { return shape.Left >= median - 0.1; })
      .sort(function (a, b) { return a.Top - b.Top; });
  }

  function fillPage(slide, page) {
    var shapes = shapesOf(slide);
    if (page.pageRole === "cover") {
      writeText(findShape(shapes, [1, 3], ["标题 1"]), page.title, "标题");
      writeText(findShape(shapes, [4], ["副标题 2"]), (page.keyPoints || [])[0] || "", "副标题");
    } else if (page.pageRole === "agenda") {
      var slots = agendaSlots(slide);
      if ((page.keyPoints || []).length > slots.length) throw new Error("目录超出模板槽位，已阻止截断。");
      (page.keyPoints || []).forEach(function (point, index) { writeText(slots[index], point, "目录项"); });
    } else if (page.pageRole === "transition") {
      writeText(findShape(shapes, [1, 3], ["标题 3"]), page.title, "标题");
      var subtitle = null;
      for (var i = 0; i < shapes.length; i++) {
        var type = shapes[i].PlaceholderFormat ? shapes[i].PlaceholderFormat.Type : 0;
        if (!type && shapes[i].TextFrame) { subtitle = shapes[i]; break; }
      }
      if ((page.keyPoints || []).length > 1) throw new Error("章节页超出一个副标题，已阻止截断。");
      writeText(subtitle, (page.keyPoints || [])[0] || "", "副标题");
    } else {
      writeText(findShape(shapes, [1, 3], ["标题 1"]), page.title, "标题");
      writeText(findShape(shapes, [2, 7], ["内容占位符 2"]), (page.keyPoints || []).join("\r\n"), "正文");
    }
    writeNotes(slide, page.speakerNotes);
  }

  function createSlide(pres, page, prototypeLimit) {
    if (page.pageRole === "cover" || page.pageRole === "content") {
      var layoutName = LAYOUTS[page.pageRole];
      var layout = findLayout(pres, layoutName);
      if (!layout || typeof pres.Slides.AddSlide !== "function") throw new Error("未找到固定模板版式：" + layoutName);
      var slide = pres.Slides.AddSlide(pres.Slides.Count + 1, layout);
      return { slide: slide, index: pres.Slides.Count };
    }
    var proto = null;
    for (var i = 1; i <= prototypeLimit; i++) {
      var candidate = pres.Slides.Item(i);
      if (candidate && candidate.CustomLayout && candidate.CustomLayout.Name === LAYOUTS[page.pageRole]) {
        proto = candidate;
        break;
      }
    }
    if (!proto || typeof proto.Duplicate !== "function") throw new Error("未找到可复制的固定模板页：" + LAYOUTS[page.pageRole]);
    var duplicated = proto.Duplicate();
    var created = duplicated && typeof duplicated.Item === "function" ? duplicated.Item(1) : duplicated;
    if (!created || typeof created.MoveTo !== "function") {
      if (created && typeof created.Delete === "function") created.Delete();
      throw new Error("复制模板页后无法移到末尾。");
    }
    try {
      created.MoveTo(pres.Slides.Count);
    } catch (moveErr) {
      if (typeof created.Delete === "function") created.Delete();
      throw moveErr;
    }
    var index = pres.Slides.Count;
    if (index <= prototypeLimit) throw new Error("新增页未能移到已有页之后。");
    return { slide: created, index: index };
  }

  function appendTemplateDeck(app, deck) {
    if (!app || !app.ActivePresentation || !app.ActivePresentation.Slides) throw new Error("未找到当前打开的演示文稿。");
    var pres = app.ActivePresentation;
    if (!deck.baselineSlideCount) deck.baselineSlideCount = pres.Slides.Count;
    var prototypeLimit = deck.baselineSlideCount;
    var appended = [];
    for (var i = 0; i < deck.pages.length; i++) {
      var page = deck.pages[i];
      if (page.writtenSlideIndex) {
        appended.push(page.writtenSlideIndex);
        continue;
      }
      var created = null;
      try {
        created = createSlide(pres, page, prototypeLimit);
        if (!created || created.index <= prototypeLimit) throw new Error("禁止修改已有页。");
        fillPage(created.slide, page);
        page.writtenSlideIndex = created.index;
        appended.push(created.index);
      } catch (err) {
        var rollbackError = "";
        if (created && created.slide && typeof created.slide.Delete === "function") {
          try { created.slide.Delete(); } catch (delErr) { rollbackError = delErr.message || String(delErr); }
        }
        return {
          success: false,
          completed: false,
          status: rollbackError ? "ROLLBACK_FAILED" : "PARTIAL",
          error: err.message || String(err),
          appendedRange: appended.length ? [appended[0], appended[appended.length - 1]] : [],
          recoveryChoices: rollbackError
            ? ["继续追加剩余页", "核查并清理未恢复的新增页"]
            : ["继续追加剩余页", "已恢复失败页，可继续追加"]
        };
      }
    }
    return {
      success: true,
      completed: true,
      status: "APPENDED",
      appendedRange: appended.length ? [appended[0], appended[appended.length - 1]] : [],
      recoveryChoices: []
    };
  }

  function createTemplateDeck(options) {
    var opts = options || {};
    var request = opts.request || function () { return Promise.reject(new Error("no request function")); };
    var getSessionId = opts.getSessionId || function () { return ""; };
    var getConfirmedOutline = opts.getConfirmedOutline || function () { return null; };
    var hasConfirmedOutline = opts.hasConfirmedOutline || function () { return false; };
    var render = opts.render || function () {};
    var schedule = opts.schedule || function (fn) { return setTimeout(fn, 0); };
    var confirmWrite = opts.confirm || function () { return true; };
    var state = {
      status: "idle",
      pages: [],
      contentConfirmed: false,
      confirmedFingerprint: "",
      confirmedSessionId: "",
      confirmedOutlineSnapshot: "",
      baselineSlideCount: 0,
      elapsedMs: 0,
      excludedNotice: "",
      unverified: ["真实模型质量", "真实 WPS 固定模板排版与可编辑性"],
      pageCountMessage: "",
      error: null
    };

    function notify() {
      try { render(getState()); } catch (err) {}
    }

    function getState() { return state; }

    function pollJob(jobId, sessionId) {
      return new Promise(function (resolve, reject) {
        schedule(function () {
          request("/ppt/template-page/jobs/" + encodeURIComponent(jobId) + "?documentSessionId=" + encodeURIComponent(sessionId), null, { method: "GET" })
            .then(function (resp) {
              if (!resp || !resp.success) throw new Error((resp && resp.message) || "查询任务失败");
              var data = resp.data || {};
              if (data.status === "completed") { resolve(data); return; }
              if (data.status === "failed") throw new Error((data.error && data.error.message) || "任务生成失败");
              throw new Error("整套生成尚未完成");
            })
            .catch(reject);
        }, 10);
      });
    }

    function submitPage(slide, instruction) {
      var sessionId = getSessionId();
      var clientJobId = "cjob_deck_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
      var payload = {
        documentSessionId: sessionId,
        clientJobId: clientJobId,
        pageIndex: slide.pageIndex,
        pageRole: slide.pageRole,
        outlineTitle: slide.title || slide.outlineTitle || "",
        outlineKeyPoints: slide.sourceKeyPoints || slide.keyPoints || [],
        outlineFragmentIds: slide.fragmentIds || [],
        instruction: instruction || "",
        userFacts: (getConfirmedOutline() || {}).userFacts || ""
      };
      return request("/ppt/template-page/jobs", payload, { method: "POST" }).then(function (start) {
        if (!start || !start.success) throw new Error((start && start.message) || "发起任务失败");
        return pollJob((start.data && start.data.jobId) || clientJobId, sessionId);
      });
    }

    function startGenerate() {
      if (!hasConfirmedOutline()) return Promise.reject(new Error("请先确认逐页大纲后再生成整套内容。"));
      var outline = getConfirmedOutline() || {};
      var selected = (outline.slides || []).filter(function (slide) { return ROLE_LABELS[slide.pageRole]; });
      var excluded = (outline.slides || []).filter(function (slide) { return !ROLE_LABELS[slide.pageRole]; });
      if (!selected.length) return Promise.reject(new Error("已确认大纲中没有封面、目录、章节页或正文页。"));
      state.pages = [];
      state.contentConfirmed = false;
      state.elapsedMs = 0;
      state.baselineSlideCount = 0;
      state.status = "running";
      state.error = null;
      notify();
      return selected.reduce(function (chain, slide) {
        return chain.then(function () {
          return submitPage(slide, outline.instruction || "").then(function (data) {
            var result = data.result || {};
            var role = result.pageRole || slide.pageRole;
            var points = result.keyPoints || [];
            state.elapsedMs += Number(data.elapsedMs) || 0;
            state.pages.push({
              pageId: role + "-" + (result.pageIndex || slide.pageIndex) + "-" + state.pages.length,
              pageIndex: result.pageIndex || slide.pageIndex,
              pageRole: role,
              title: result.title || slide.title || "",
              keyPoints: points,
              sourceKeyPoints: slide.keyPoints || [],
              speakerNotes: result.speakerNotes || "",
              isOverflow: !!(result.isOverflow || isOverflow(role, points)),
              writtenSlideIndex: null
            });
          });
        });
      }, Promise.resolve()).then(function () {
        state.status = "preview";
        state.excludedNotice = excluded.length
          ? "以下大纲页不属于本模板四类页面，本次不写入：" + excluded.map(function (slide) {
            return EXCLUDED_LABELS[slide.pageRole] || slide.pageRole;
          }).join("、")
          : "";
        state.unverified = ["真实模型质量", "真实 WPS 固定模板排版与可编辑性"];
        notify();
        return { status: "PREVIEW", pages: state.pages };
      });
    }

    function confirmContent() {
      if (!state.pages.length) throw new Error("请先生成整套内容。");
      if (state.pages.some(function (page) { return page.isOverflow; })) throw new Error("仍有超出容量的页面，请先精简或拆页。");
      state.contentConfirmed = true;
      state.confirmedFingerprint = fingerprint(state.pages);
      state.confirmedSessionId = getSessionId();
      state.confirmedOutlineSnapshot = JSON.stringify(getConfirmedOutline() || {});
      notify();
      return state;
    }

    function splitPage(pageId) {
      var index = -1;
      for (var i = 0; i < state.pages.length; i++) if (state.pages[i].pageId === pageId) index = i;
      if (index < 0) throw new Error("未找到要拆分的页面。");
      var page = state.pages[index];
      if (!page.keyPoints || page.keyPoints.length < 2) throw new Error("该页无法拆页，请精简。");
      var before = state.pages.length;
      var mid = Math.ceil(page.keyPoints.length / 2);
      var leftPoints = page.keyPoints.slice(0, mid);
      var rightPoints = page.keyPoints.slice(mid);
      var left = Object.assign({}, page, {
        pageId: page.pageId + "-a",
        keyPoints: leftPoints,
        isOverflow: isOverflow(page.pageRole, leftPoints),
        writtenSlideIndex: null
      });
      var right = Object.assign({}, page, {
        pageId: page.pageId + "-b",
        keyPoints: rightPoints,
        isOverflow: isOverflow(page.pageRole, rightPoints),
        writtenSlideIndex: null
      });
      state.pages.splice(index, 1, left, right);
      state.contentConfirmed = false;
      state.pageCountMessage = "页数由 " + before + " 变为 " + state.pages.length;
      notify();
      return { pageCountBefore: before, pageCountAfter: state.pages.length, message: state.pageCountMessage };
    }

    function simplifyPage(pageId) {
      var page = null;
      for (var i = 0; i < state.pages.length; i++) if (state.pages[i].pageId === pageId) page = state.pages[i];
      if (!page) return Promise.reject(new Error("未找到要精简的页面。"));
      return submitPage({
        pageIndex: page.pageIndex,
        pageRole: page.pageRole,
        title: page.title,
        sourceKeyPoints: page.sourceKeyPoints || page.keyPoints,
        keyPoints: page.keyPoints
      }, "请精简到模板容量内，不要截断或丢弃已确认事实。").then(function (data) {
        var result = data.result || {};
        page.title = result.title || page.title;
        page.keyPoints = result.keyPoints || page.keyPoints;
        page.speakerNotes = result.speakerNotes || page.speakerNotes;
        page.isOverflow = !!(result.isOverflow || isOverflow(page.pageRole, page.keyPoints));
        state.contentConfirmed = false;
        state.elapsedMs += Number(data.elapsedMs) || 0;
        notify();
        return page;
      });
    }

    function append(app) {
      if (!state.contentConfirmed) throw new Error("请先确认整套内容。");
      if (getSessionId() !== state.confirmedSessionId) throw new Error("目标演示文稿已变化，已阻止写入旧预览。");
      if (fingerprint(state.pages) !== state.confirmedFingerprint) throw new Error("已确认内容已变化，请重新确认后再写入。");
      if (JSON.stringify(getConfirmedOutline() || {}) !== state.confirmedOutlineSnapshot) throw new Error("已确认大纲已变化，请重新确认后再写入。");
      var count = app && app.ActivePresentation && app.ActivePresentation.Slides ? app.ActivePresentation.Slides.Count : 0;
      var message = "即将向当前演示文稿末尾追加整套页面。现有第 1 至 " + count + " 页完全保持不变。确认追加？";
      if (!confirmWrite(message)) return { success: false, status: "CONFIRM_DECLINED", completed: false };
      var written = appendTemplateDeck(app, state);
      state.status = written.completed ? "completed" : "partial";
      state.error = written.success ? null : { message: written.error || "" };
      notify();
      return written;
    }

    return {
      startGenerate: startGenerate,
      confirmContent: confirmContent,
      splitPage: splitPage,
      simplifyPage: simplifyPage,
      append: append,
      getState: getState,
      hasConfirmedOutline: hasConfirmedOutline
    };
  }

  return { createTemplateDeck: createTemplateDeck, appendTemplateDeck: appendTemplateDeck };
});
