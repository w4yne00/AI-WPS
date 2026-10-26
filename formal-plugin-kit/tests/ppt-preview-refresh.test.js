const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pptRoot } = require("./support/plugin-roots");

function pane() {
  const nodes = new Map(), storage = new Map();
  function element() {
    let html = "", text = "";
    return {
      children: [], style: {}, value: "", hidden: false,
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute() {}, contains() { return false; },
      appendChild(child) { this.children.push(child); return child; },
      get innerHTML() { return html; },
      set innerHTML(value) { html = value; text = ""; this.children = []; },
      get textContent() {
        return text + html.replace(/<[^>]*>/g, "") + this.children.map(child => child.textContent).join("");
      },
      set textContent(value) { text = value; html = ""; this.children = []; }
    };
  }
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  const document = {
    readyState: "loading", activeElement: null, addEventListener() {},
    getElementById: node, createElement: element, createTextNode: text => ({ textContent: text })
  };
  const context = {
    window: {
      WpsAiPptHelpers: require(path.join(pptRoot, "taskpane-helpers.js")),
      Application: { ActivePresentation: { Name: "A.pptx", FullName: "/test/A.pptx" } },
      localStorage: {
        getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
        removeItem: key => storage.delete(key)
      }
    },
    document, console, setTimeout, clearTimeout
  };
  vm.createContext(context);
  for (const file of ["material-outline.js", "template-body-page.js", "template-deck.js"]) {
    vm.runInContext(fs.readFileSync(path.join(pptRoot, file), "utf8"), context);
  }
  const source = fs.readFileSync(path.join(pptRoot, "taskpane.js"), "utf8");
  vm.runInContext(source.replace('  if (document.readyState === "loading") {',
    '  window.testApi = { state, renderResult, renderStructureResult, renderMaterialOutlineView, renderTemplateBodyPageView, renderTemplateDeckView, ensureMaterialOutline };\n  if (document.readyState === "loading") {'), context);
  const api = context.window.testApi;
  api.state.taskMode = "pptMaterialOutline";
  const outline = api.ensureMaterialOutline().current();
  outline.confirmationStatus = "confirmed";
  outline.confirmedOutline = { slides: [{ pageIndex: 1, pageRole: "content", title: "依据", keyPoints: [] }] };
  return { ...api, node, document };
}

const summaryCases = {
  "当前页总结": text => ({ suggestedTitle: text, bullets: [text + "正文"] }),
  "文档结构化总结": text => ({ resultType: "document", deckTitle: text, slides: [{ index: 1, title: text }] }),
  "文档 Markdown 总结": text => ({ resultType: "document", rawAnswer: "# " + text + "\n\n" + text + "正文" })
};
for (const [name, result] of Object.entries(summaryCases)) {
  test(name + "连续结果无需切换标签即可刷新", () => {
    const h = pane();
    h.renderResult(result("旧任务"));
    assert.match(h.node("result-output").textContent, /旧任务/);
    h.renderResult(result("新任务"));
    assert.match(h.node("result-output").textContent, /新任务/);
    assert.doesNotMatch(h.node("result-output").textContent, /旧任务/);
    assert.equal(h.state.resultMode, "preview");
  });
}

test("结构审查连续结果立即替换旧内容", () => {
  const h = pane();
  h.renderStructureResult({ overallStoryline: "旧任务" });
  assert.match(h.node("structure-result-output").textContent, /旧任务/);
  h.renderStructureResult({ overallStoryline: "新任务" });
  assert.match(h.node("structure-result-output").textContent, /新任务/);
  assert.doesNotMatch(h.node("structure-result-output").textContent, /旧任务/);
});

test("大纲新结果不被旧标题输入焦点阻止刷新", () => {
  const h = pane();
  const view = text => ({ documentSessionId: "A", result: { slides: [{ pageIndex: 1, title: text }] } });
  h.renderMaterialOutlineView(view("旧任务"));
  assert.match(h.node("outline-slide-list").innerHTML, /旧任务/);
  const input = { getAttribute: name => name === "data-title-page" ? "1" : null };
  h.document.activeElement = input;
  h.node("outline-slide-list").contains = target => target === input;
  h.renderMaterialOutlineView(view("新任务"));
  assert.match(h.node("outline-slide-list").innerHTML, /新任务/);
  assert.doesNotMatch(h.node("outline-slide-list").innerHTML, /旧任务/);
});

for (const [name, render, output, view] of [
  ["正文页", "renderTemplateBodyPageView", "ppt-template-page-preview-content",
    text => ({ status: "completed", result: { title: text, keyPoints: [text + "正文"] } })],
  ["整套内容", "renderTemplateDeckView", "ppt-template-deck-preview",
    text => ({ status: "preview", pages: [{ pageRole: "content", title: text, keyPoints: [text + "正文"] }] })]
]) {
  test(name + "连续结果立即替换旧预览", () => {
    const h = pane();
    h[render](view("旧任务"));
    assert.match(h.node(output).innerHTML, /旧任务/);
    h[render](view("新任务"));
    assert.match(h.node(output).innerHTML, /新任务/);
    assert.doesNotMatch(h.node(output).innerHTML, /旧任务/);
  });
}
