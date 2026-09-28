const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const { pptRoot: root } = require("./support/plugin-roots");

function shape(spec) {
  const font = {};
  Object.defineProperty(font, "Size", {
    set() {
      throw new Error("禁止缩小字号");
    },
    get() {
      return 20;
    },
  });
  return {
    Name: spec.name,
    Left: spec.left,
    Top: spec.top,
    PlaceholderFormat: { Type: spec.type || 0 },
    TextFrame: {
      TextRange: {
        Font: font,
        get Text() {
          return spec.text;
        },
        set Text(value) {
          if (spec.onWrite) spec.onWrite(value);
          spec.text = value;
        },
      },
    },
    spec,
  };
}

function collection(items) {
  return {
    get Count() {
      return items.length;
    },
    Item(index) {
      return items[index - 1];
    },
  };
}

function createHost() {
  const slides = [];
  const calls = { addSlide: 0, duplicate: 0 };
  function reindex() {
    slides.forEach((slide, index) => {
      slide.index = index + 1;
    });
  }
  function makeSlide(layoutName, shapes, notes) {
    const slide = {
      CustomLayout: { Name: layoutName },
      get Shapes() {
        return collection(slide.shapes);
      },
      NotesPage: { Shapes: collection(notes) },
      shapes,
      Delete() {
        const index = slides.indexOf(slide);
        if (index >= 0) slides.splice(index, 1);
        reindex();
      },
      Duplicate() {
        calls.duplicate += 1;
        const copy = makeSlide(
          layoutName,
          slide.shapes.map((item) => shape({ ...item.spec, text: item.spec.text, onWrite: item.spec.onWrite })),
          notes.map((item) => shape({ ...item.spec, text: item.spec.text, onWrite: item.spec.onWrite }))
        );
        slides.splice(slides.indexOf(slide) + 1, 0, copy);
        reindex();
        return copy;
      },
      MoveTo(index) {
        const from = slides.indexOf(slide);
        slides.splice(from, 1);
        slides.splice(index - 1, 0, slide);
        reindex();
      },
    };
    return slide;
  }
  const layouts = [
    { Name: "标题幻灯片" },
    { Name: "节标题" },
    { Name: "两栏内容" },
    { Name: "标题和内容" },
  ];
  slides.push(makeSlide("标题幻灯片", [
    shape({ name: "标题 1", type: 3, text: "原封面", left: 1, top: 1 }),
    shape({ name: "副标题 2", type: 4, text: "原副标题", left: 1, top: 3 }),
  ], [shape({ name: "备注", type: 2, text: "原封面备注", left: 0, top: 0 })]));
  slides.push(makeSlide("节标题", [
    shape({ name: "矩形 19", type: 0, text: "一", left: 3.5, top: 1.8 }),
    shape({ name: "矩形 20", type: 0, text: "原目录一", left: 4.6, top: 1.8 }),
    shape({ name: "矩形 15", type: 0, text: "二", left: 3.5, top: 2.9 }),
    shape({ name: "矩形 12", type: 0, text: "原目录二", left: 4.7, top: 2.9 }),
    shape({ name: "矩形 4", type: 0, text: "三", left: 3.5, top: 4.1 }),
    shape({ name: "矩形 5", type: 0, text: "原目录三", left: 4.6, top: 4.0 }),
  ], [shape({ name: "备注", type: 2, text: "原目录备注", left: 0, top: 0 })]));
  slides.push(makeSlide("两栏内容", [
    shape({ name: "标题 3", type: 1, text: "原章节", left: 1, top: 2 }),
    shape({ name: "标题 1", type: 0, text: "原章节副标题", left: 1, top: 4 }),
  ], [shape({ name: "备注", type: 2, text: "原章节备注", left: 0, top: 0 })]));
  slides.push(makeSlide("两栏内容", [
    shape({ name: "标题 3", type: 1, text: "原章节二", left: 1, top: 2 }),
    shape({ name: "标题 1", type: 0, text: "原章节副标题二", left: 1, top: 4 }),
  ], [shape({ name: "备注", type: 2, text: "", left: 0, top: 0 })]));
  slides.push(makeSlide("空白", [
    shape({ name: "文本框 1", type: 0, text: "原封底", left: 1, top: 1 }),
  ], [shape({ name: "备注", type: 2, text: "", left: 0, top: 0 })]));
  reindex();
  const originalSlides = slides.slice();
  const pres = {
    SlideMaster: { CustomLayouts: collection(layouts) },
    Designs: { Count: 1, Item: () => ({ SlideMaster: { CustomLayouts: collection(layouts) } }) },
    Slides: {
      get Count() {
        return slides.length;
      },
      Item: (index) => slides[index - 1],
      AddSlide(index, layout) {
        calls.addSlide += 1;
        if (index !== slides.length + 1) throw new Error("只能追加到末尾");
        let created;
        if (layout.Name === "标题幻灯片") {
          created = makeSlide(layout.Name, [
            shape({ name: "标题 1", type: 3, text: "", left: 1, top: 1 }),
            shape({ name: "副标题 2", type: 4, text: "", left: 1, top: 3 }),
          ], [shape({ name: "备注", type: 2, text: "", left: 0, top: 0 })]);
        } else if (layout.Name === "标题和内容") {
          created = makeSlide(layout.Name, [
            shape({ name: "标题 1", type: 1, text: "", left: 1, top: 1 }),
            shape({ name: "内容占位符 2", type: 2, text: "", left: 1, top: 3 }),
          ], [shape({ name: "备注", type: 2, text: "", left: 0, top: 0 })]);
        } else {
          throw new Error("未适配版式：" + layout.Name);
        }
        slides.push(created);
        reindex();
        return created;
      },
    },
  };
  return {
    app: { ActivePresentation: pres },
    calls,
    originalTexts() {
      return originalSlides.map((slide) => slide.shapes.map((item) => item.spec.text).join("|"));
    },
    notesText(index) {
      return slides[index - 1].NotesPage.Shapes.Item(1).TextFrame.TextRange.Text;
    },
    bodyText(index) {
      return slides[index - 1].shapes.map((item) => item.spec.text).join("|");
    },
  };
}

function outline() {
  return {
    confirmed: true,
    confirmedAt: "2026-09-28T00:00:00Z",
    instruction: "面向评审",
    userFacts: "",
    slides: [
      { pageIndex: 1, pageRole: "cover", title: "封面", keyPoints: ["副标题"] },
      { pageIndex: 2, pageRole: "agenda", title: "目录", keyPoints: ["架构", "路径", "保障"] },
      { pageIndex: 3, pageRole: "transition", title: "一、架构", keyPoints: ["总体架构"] },
      { pageIndex: 4, pageRole: "content", title: "分层设计", keyPoints: ["分层解耦", "安全可控"] },
      { pageIndex: 5, pageRole: "summary", title: "总结", keyPoints: ["不在四类页内"] },
    ],
  };
}

function loadController(h) {
  const context = { window: {}, console, Promise, Date, Math, Array, Object, setTimeout, clearTimeout };
  const scriptPath = path.join(root, "template-deck.js");
  vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), context);
  if (!context.window.createTemplateDeck) throw new Error("createTemplateDeck is not defined");
  h.jobs = new Map();
  h.confirmations = [];
  const ctrl = context.window.createTemplateDeck({
    request(url, body, opts) {
      const method = (opts && opts.method) || "GET";
      h.calls.push({ url, body, method });
      if (url === "/ppt/template-page/jobs" && method === "POST") {
        h.jobs.set(body.clientJobId, body);
        return Promise.resolve({ success: true, data: { jobId: body.clientJobId, status: "running" } });
      }
      const jobId = decodeURIComponent(String(url).split("/ppt/template-page/jobs/")[1] || "").split("?")[0];
      const submitted = h.jobs.get(jobId) || {};
      if (h.pollStatuses && h.pollStatuses.length) {
        return Promise.resolve({ success: true, data: { status: h.pollStatuses.shift() } });
      }
      const points = submitted.pageRole === "content" && h.overflowContent
        ? ["要点一", "要点二", "要点三", "要点四", "要点五"]
        : submitted.outlineKeyPoints || [];
      return Promise.resolve({
        success: true,
        data: {
          status: "completed",
          elapsedMs: 15,
          result: {
            schemaVersion: "ppt.template_page.v1",
            pageIndex: submitted.pageIndex,
            pageRole: submitted.pageRole,
            title: submitted.outlineTitle,
            keyPoints: points,
            speakerNotes: submitted.pageRole + "讲稿",
            sources: [],
            missingItems: [],
            isOverflow: points.length > (submitted.pageRole === "agenda" ? 3 : 4),
          },
        },
      });
    },
    storage: { getItem() {}, setItem() {}, removeItem() {} },
    getSessionId: () => h.session,
    getConfirmedOutline: () => h.outline,
    hasConfirmedOutline: () => !!(h.outline && h.outline.confirmed),
    render: (view) => h.views.push(view),
    schedule: (fn) => {
      fn();
      return 0;
    },
    confirm: (message) => {
      h.confirmations.push(message);
      return h.allowConfirm !== false;
    },
    wpsApp: h.host && h.host.app,
  });
  return ctrl;
}

function harness(extra) {
  const h = {
    session: "sess-deck",
    outline: outline(),
    calls: [],
    views: [],
    host: createHost(),
    allowConfirm: true,
    ...extra,
  };
  h.ctrl = loadController(h);
  return h;
}

test("未确认大纲时不能生成整套内容", async () => {
  const h = harness({ outline: null });
  await assert.rejects(() => h.ctrl.startGenerate(), /确认逐页大纲/);
  assert.equal(h.calls.length, 0);
});

test("按已确认大纲生成封面目录章节和正文，并保留讲稿", async () => {
  const h = harness();
  const result = await h.ctrl.startGenerate();
  assert.equal(result.status, "PREVIEW");
  const roles = h.calls.filter((call) => call.method === "POST").map((call) => call.body.pageRole);
  assert.equal(roles.join(","), "cover,agenda,transition,content");
  const state = h.ctrl.getState();
  assert.equal(state.pages.map((page) => page.pageRole).join(","), "cover,agenda,transition,content");
  assert.ok(state.pages.every((page) => page.speakerNotes.endsWith("讲稿")));
  assert.match(state.excludedNotice, /总结/);
  assert.equal(state.contentConfirmed, false);
  assert.equal(state.elapsedMs, 60);
  assert.match(state.unverified.join(" "), /真实 WPS/);
});

test("排队和运行中的任务持续查询，直到整套内容生成", async () => {
  const h = harness({ pollStatuses: ["queued", "running"] });
  const result = await h.ctrl.startGenerate();
  assert.equal(result.status, "PREVIEW");
  assert.equal(h.calls.filter((call) => call.method === "GET").length, 6);
  assert.equal(h.ctrl.getState().pages.length, 4);
});

test("先确认内容并最终确认后才追加，原页面文字不变", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  const before = h.host.originalTexts();
  assert.throws(() => h.ctrl.append(h.host.app), /确认整套内容/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
  h.ctrl.confirmContent();
  h.allowConfirm = false;
  const declined = h.ctrl.append(h.host.app);
  assert.equal(declined.status, "CONFIRM_DECLINED");
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
  h.allowConfirm = true;
  const written = h.ctrl.append(h.host.app);
  assert.equal(written.success, true);
  assert.equal(written.completed, true);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 9);
  assert.deepEqual(h.host.originalTexts(), before);
  assert.match(h.host.bodyText(6), /封面/);
  assert.match(h.host.bodyText(6), /副标题/);
  assert.match(h.host.notesText(6), /cover讲稿/);
  const agendaTitles = h.host.app.ActivePresentation.Slides.Item(7).shapes
    .filter((item) => item.Left >= 4.5)
    .sort((a, b) => a.Top - b.Top)
    .map((item) => item.spec.text);
  assert.equal(agendaTitles.join(","), "架构,路径,保障");
  assert.equal(
    h.host.app.ActivePresentation.Slides.Item(7).shapes.filter((item) => item.Left < 4).map((item) => item.spec.text).join(","),
    "一,二,三"
  );
  assert.match(h.host.bodyText(8), /一、架构/);
  assert.match(h.host.bodyText(8), /总体架构/);
  assert.match(h.host.notesText(8), /transition讲稿/);
  assert.match(h.host.bodyText(9), /分层设计/);
  assert.match(h.host.bodyText(9), /分层解耦/);
  assert.match(h.host.notesText(9), /content讲稿/);
  assert.match(h.confirmations[0], /末尾/);
  assert.match(h.confirmations[0], /保持不变/);
});

test("溢出可拆页并明示页数变化，未再确认前不写入", async () => {
  const h = harness({ overflowContent: true });
  await h.ctrl.startGenerate();
  const state = h.ctrl.getState();
  const content = state.pages.find((page) => page.pageRole === "content");
  assert.equal(content.isOverflow, true);
  assert.equal(content.keyPoints.length, 5);
  const split = h.ctrl.splitPage(content.pageId);
  assert.equal(split.pageCountBefore, 4);
  assert.equal(split.pageCountAfter, 5);
  assert.match(split.message, /页数由 4 变为 5/);
  const points = h.ctrl.getState().pages.filter((page) => page.pageRole === "content").flatMap((page) => page.keyPoints);
  assert.equal(points.join(","), "要点一,要点二,要点三,要点四,要点五");
  assert.equal(h.ctrl.getState().contentConfirmed, false);
  assert.throws(() => h.ctrl.append(h.host.app), /确认整套内容/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
});

test("目录拆页后清空复制页未使用的旧条目和编号", async () => {
  const h = harness();
  h.outline.slides[1].keyPoints = ["架构", "路径", "保障", "运维"];
  await h.ctrl.startGenerate();
  const agenda = h.ctrl.getState().pages.find((page) => page.pageRole === "agenda");
  h.ctrl.splitPage(agenda.pageId);
  h.ctrl.confirmContent();
  assert.equal(h.ctrl.append(h.host.app).completed, true);
  for (const index of [7, 8]) {
    const slots = h.host.app.ActivePresentation.Slides.Item(index).shapes;
    assert.equal(slots[4].spec.text, "");
    assert.equal(slots[5].spec.text, "");
  }
  assert.match(h.host.bodyText(7), /架构.*路径/s);
  assert.match(h.host.bodyText(8), /保障.*运维/s);
});

test("拆页后仍按字符和行数拦截过长正文", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  const content = h.ctrl.getState().pages.find((page) => page.pageRole === "content");
  content.keyPoints = ["长".repeat(300), "短"];
  content.isOverflow = true;
  h.ctrl.splitPage(content.pageId);
  const splitContents = h.ctrl.getState().pages.filter((page) => page.pageRole === "content");
  assert.equal(splitContents[0].isOverflow, true);
  assert.throws(() => h.ctrl.confirmContent(), /超出容量/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
});

test("追加边界独立拒绝未标记的正文超限", () => {
  const host = createHost();
  const { appendTemplateDeck } = require(path.join(root, "template-deck.js"));
  const written = appendTemplateDeck(host.app, { pages: [{
    pageRole: "content", title: "长文", keyPoints: ["长".repeat(300)], speakerNotes: "讲稿", isOverflow: false,
  }] });
  assert.equal(written.completed, false);
  assert.equal(host.app.ActivePresentation.Slides.Count, 5);
});

test("精简后必须重新预览确认，且不直接改演示文稿", async () => {
  const h = harness({ overflowContent: true });
  await h.ctrl.startGenerate();
  h.overflowContent = false;
  const content = h.ctrl.getState().pages.find((page) => page.pageRole === "content");
  const simplified = await h.ctrl.simplifyPage(content.pageId);
  assert.equal(simplified.keyPoints.length <= 4, true);
  assert.equal(h.ctrl.getState().contentConfirmed, false);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
  const posted = h.calls.filter((call) => call.method === "POST" && call.body && call.body.pageRole === "content");
  assert.match(posted[posted.length - 1].body.instruction, /精简/);
});

test("目标文稿或已确认内容变化时拒绝写入旧预览", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.ctrl.confirmContent();
  h.session = "other-deck";
  assert.throws(() => h.ctrl.append(h.host.app), /演示文稿已变化/);
  h.session = "sess-deck";
  h.ctrl.getState().pages[0].title = "被改过的封面";
  assert.throws(() => h.ctrl.append(h.host.app), /已确认内容已变化/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
});

test("生成后切换文稿不能把旧内容重新确认为新文稿", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.session = "other-deck";
  h.outline = { ...outline(), instruction: "另一文稿" };
  assert.throws(() => h.ctrl.confirmContent(), /目标演示文稿|大纲已变化/);
  assert.equal(h.ctrl.getState().contentConfirmed, false);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 5);
});

test("部分失败展示已追加范围，重试不重复追加也不伪报完成", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.ctrl.confirmContent();
  let notesWrites = 0;
  h.host.app.ActivePresentation.Slides.Item(3).NotesPage.Shapes.Item(1).spec.onWrite = () => {
    notesWrites += 1;
    if (notesWrites === 1) throw new Error("宿主写入中断");
  };
  const failed = h.ctrl.append(h.host.app);
  assert.equal(failed.success, false);
  assert.equal(failed.completed, false);
  assert.notEqual(failed.status, "APPENDED");
  assert.equal([].concat(failed.appendedRange).join(","), "6,7");
  assert.match(failed.recoveryChoices.join(" "), /继续追加/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 7);
  assert.match(h.host.bodyText(1), /原封面/);
  const retried = h.ctrl.append(h.host.app);
  assert.equal(retried.success, true);
  assert.equal(retried.completed, true);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 9);
  assert.equal(h.host.calls.duplicate, 3);
});

test("失败页删除失败后必须先核查残页，才能继续追加", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.ctrl.confirmContent();
  const prototype = h.host.app.ActivePresentation.Slides.Item(3);
  const duplicate = prototype.Duplicate.bind(prototype);
  let cleanup;
  prototype.Duplicate = () => {
    const slide = duplicate();
    cleanup = slide.Delete.bind(slide);
    slide.Delete = () => { throw new Error("删除失败"); };
    return slide;
  };
  let failedOnce = false;
  prototype.NotesPage.Shapes.Item(1).spec.onWrite = () => {
    if (!failedOnce) { failedOnce = true; throw new Error("备注写入失败"); }
  };
  const failed = h.ctrl.append(h.host.app);
  assert.equal(failed.status, "ROLLBACK_FAILED");
  assert.equal(failed.residualSlideIndex, 8);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 8);
  assert.equal(h.ctrl.getState().recoveryRequired, true);
  assert.equal([].concat(h.ctrl.getState().appendedRange).join(","), "6,7");
  assert.match(h.ctrl.getState().recoveryChoices.join(" "), /核查/);
  assert.throws(() => h.ctrl.append(h.host.app), /核查恢复/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 8);
  assert.throws(() => h.ctrl.verifyRecovery(h.host.app), /残页/);
  cleanup();
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 7);
  h.ctrl.verifyRecovery(h.host.app);
  const retried = h.ctrl.append(h.host.app);
  assert.equal(retried.completed, true);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 9);
});

test("删除接口静默未删除残页时同样阻止重试", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.ctrl.confirmContent();
  const prototype = h.host.app.ActivePresentation.Slides.Item(3);
  const duplicate = prototype.Duplicate.bind(prototype);
  prototype.Duplicate = () => {
    const slide = duplicate();
    slide.Delete = () => {};
    return slide;
  };
  prototype.NotesPage.Shapes.Item(1).spec.onWrite = () => { throw new Error("备注写入失败"); };
  const failed = h.ctrl.append(h.host.app);
  assert.equal(failed.status, "ROLLBACK_FAILED");
  assert.equal(h.ctrl.getState().recoveryRequired, true);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 8);
});

test("部分追加后重新点击生成不会清空恢复进度", async () => {
  const h = harness();
  await h.ctrl.startGenerate();
  h.ctrl.confirmContent();
  h.host.app.ActivePresentation.Slides.Item(3).NotesPage.Shapes.Item(1).spec.onWrite = () => {
    throw new Error("备注写入失败");
  };
  assert.equal(h.ctrl.append(h.host.app).status, "PARTIAL");
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 7);
  await assert.rejects(h.ctrl.startGenerate(), /已有追加进度/);
  assert.equal(h.host.app.ActivePresentation.Slides.Count, 7);
});

test("任务窗格提供整套填充入口", () => {
  const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
  const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  assert.match(html, /template-deck\.js/);
  assert.match(html, /id="ppt-template-deck-card"/);
  assert.match(html, /id="btn-ppt-generate-template-deck"/);
  assert.match(html, /id="btn-ppt-confirm-template-deck"/);
  assert.match(html, /id="btn-ppt-append-template-deck"/);
  assert.match(js, /createTemplateDeck/);
});
