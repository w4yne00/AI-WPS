const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const pptJs = fs.readFileSync(
  path.join(ROOT, "wps-ai-assistant-wpp_1.0.0", "taskpane.js"),
  "utf8"
);
const context = { window: {} };
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(ROOT, "wps-ai-assistant-wpp_1.0.0", "taskpane-helpers.js"), "utf8"),
  context
);
const helpers = context.window.WpsAiPptHelpers;

function present(result) {
  assert.strictEqual(typeof helpers.presentPptStructureReviewResultView, "function");
  return helpers.presentPptStructureReviewResultView({ result: result });
}

function functionSource(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = source.indexOf("\n  function ", start + 1);
  return source.slice(start, end < 0 ? source.length : end);
}

function sampleResult(overrides) {
  return Object.assign({
    reviewedRange: { startSlide: 1, endSlide: 4, totalSlides: 4, isFullDeck: true },
    reviewConclusion: "本次审查第 1–4 页（演示文稿共 4 页）。",
    overallStoryline: "先封面后目录，再进入方案。",
    pageRoles: [
      { slideNumber: 1, role: "封面页", reason: "整套文稿第 1 页，未识别为目录或过渡。" },
      { slideNumber: 2, role: "目录页", reason: "标题命中目录。" },
      { slideNumber: 3, role: "未确认页角色", reason: "证据不足，按正文页执行规则。" },
      { slideNumber: 4, role: "结束页", reason: "整套文稿末页命中结束语。" }
    ],
    slideRecommendations: [
      { slideNumber: 1, suggestion: "封面主标题再缩短。", role: "章节概述" },
      { slideNumber: 3, suggestion: "补充本页主标题。", role: "内容页" }
    ],
    slides: [
      { index: 1, role: "开场白", title: "汇报标题" }
    ],
    rawAnswer: null
  }, overrides || {});
}

function testListShowsPageRoleReasonSeparately() {
  // Break: structure review HTML still has no dedicated 页角色清单.
  const view = present(sampleResult());
  const html = view.html;

  assert.ok(html.includes("页角色清单"));
  assert.ok(html.indexOf("页角色清单") < html.indexOf("逐页调整意见"));
  assert.ok(html.includes("第 1 页｜封面页：整套文稿第 1 页，未识别为目录或过渡。"));
  assert.ok(html.includes("第 2 页｜目录页：标题命中目录。"));
}

function testRecommendationsUseReturnedPageRolesNotFreeRoles() {
  // Break: labels come from slideRecommendations.role / slides.role (智能总结自由角色).
  const view = present(sampleResult());
  const html = view.html;

  assert.ok(html.includes("第 1 页（封面页）：封面主标题再缩短。"));
  assert.ok(html.includes("第 3 页（未确认页角色）：补充本页主标题。"));
  assert.ok(!html.includes("章节概述"));
  assert.ok(!html.includes("内容页"));
  assert.ok(!html.includes("开场白"));
}

function testUnconfirmedRoleStaysVisibleAndIsNotBody() {
  // Break: missing/unconfirmed role is blanked or rewritten as 正文页.
  const view = present(sampleResult({
    pageRoles: [
      { slideNumber: 8, role: "未确认页角色", reason: "证据不足，按正文页执行规则。" },
      { slideNumber: 9, role: "", reason: "证据不足，按正文页执行规则。" }
    ],
    slideRecommendations: [
      { slideNumber: 8, suggestion: "补标题。", role: "正文" },
      { slideNumber: 9, suggestion: "核对要点。" }
    ]
  }));

  const html = view.html;
  assert.ok(html.includes("第 8 页｜未确认页角色：证据不足，按正文页执行规则。"));
  assert.ok(html.includes("第 9 页｜未确认页角色：证据不足，按正文页执行规则。"));
  assert.ok(html.includes("第 8 页（未确认页角色）：补标题。"));
  assert.ok(html.includes("第 9 页（未确认页角色）：核对要点。"));
  assert.ok(!html.includes("第 8 页（正文页）"));
  assert.ok(!html.includes("第 9 页（正文页）"));
  assert.ok(!html.includes("第 8 页：补标题。"));
}

function testCopyConclusionKeepsPageRoles() {
  // Break: 复制审查结论 only has the storyline, no page roles.
  const view = present(sampleResult());
  const copy = view.copyConclusionText;

  assert.ok(copy.includes("本次审查第 1–4 页"));
  assert.ok(copy.includes("页角色清单"));
  assert.ok(copy.includes("第 3 页｜未确认页角色：证据不足，按正文页执行规则。"));
  assert.ok(!copy.includes("章节概述"));
  assert.ok(!copy.includes("开场白"));
}

function testRawAnswerFallbackStillShowsPageRoles() {
  // Break: rawAnswer path dumps model text and drops the page-role list.
  const view = present(sampleResult({
    rawAnswer: "模型自由发挥：这一页像开场白。"
  }));

  assert.ok(view.html.includes("页角色清单"));
  assert.ok(view.html.includes("封面页"));
  assert.ok(view.html.includes("未确认页角色"));
  assert.ok(view.copyConclusionText.includes("未确认页角色"));
}

function testRenderUsesPresenterAndDoesNotReadSummaryRoles() {
  // Break: renderStructureResult still formats recommendations in place
  // and never calls the presenter.
  const render = functionSource(pptJs, "renderStructureResult");
  const copyHandler = pptJs.slice(
    pptJs.indexOf('byId("btn-copy-review-conclusion").addEventListener'),
    pptJs.indexOf('byId("btn-copy-recommended-outline").addEventListener')
  );

  assert.ok(render.includes("presentPptStructureReviewResultView"));
  assert.ok(!render.includes("item.role"));
  assert.ok(!render.includes("slides["));
  assert.ok(copyHandler.includes("copyConclusionText"));
}

testListShowsPageRoleReasonSeparately();
testRecommendationsUseReturnedPageRolesNotFreeRoles();
testUnconfirmedRoleStaysVisibleAndIsNotBody();
testCopyConclusionKeepsPageRoles();
testRawAnswerFallbackStillShowsPageRoles();
testRenderUsesPresenterAndDoesNotReadSummaryRoles();

console.log("ppt structure page role tests passed");
