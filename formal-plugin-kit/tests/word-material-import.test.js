const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const test = require("node:test");

const pluginRoot = path.join(__dirname, "../wps-ai-assistant_1.0.0");

function loadMaterialImport() {
  const source = fs.readFileSync(path.join(pluginRoot, "material-import.js"), "utf8");
  const context = { window: {}, console };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(source, context);
  return context;
}

test("importing one DOCX shows located reading and does not change the document", async () => {
  const api = loadMaterialImport();
  const writes = [];
  const sourceSaves = [];
  const root = createRoot();
  const reading = {
    materialId: "mat_test",
    sourceFileUnchanged: true,
    targetDocumentUnchanged: true,
    understandsAllContent: false,
    disclosure: "图片文字和嵌入附件未读取，不宣称理解全部内容。",
    limits: {
      productConfirmed: false,
      characterCountMethod: "unicode_codepoints_of_extracted_readable_text",
      fileByteLimit: 10485760,
      readableCharacterCount: 24
    },
    unreadRegions: [
      { kind: "image", count: 1, message: "图片中的文字未读取。" },
      { kind: "embedded_attachment", count: 1, message: "嵌入附件未读取。" }
    ],
    blocks: [
      { kind: "heading", level: 1, text: "第一章 范围", source: { part: "word/document.xml", blockIndex: 0 } },
      { kind: "list_item", text: "保留原文事实", source: { part: "word/document.xml", blockIndex: 1 } },
      {
        kind: "table",
        rows: [["责任部门", "完成时间"], ["信息化处", ""]],
        source: { part: "word/document.xml", blockIndex: 2 }
      }
    ],
    fragments: [
      { text: "第一章 范围", source: { part: "word/document.xml", blockIndex: 0 } }
    ]
  };
  const requests = [];
  await api.submitMaterialImport({
    fileName: "资料.docx",
    contentBase64: "ZG9jeA==",
    documentSessionId: "doc-session-1",
    root,
    documentApi: {
      insertText(value) { writes.push(value); },
      save() { writes.push("save"); }
    },
    sourceFile: {
      name: "资料.docx",
      save() { sourceSaves.push("save"); }
    },
    request(url, body) {
      requests.push({ url, body });
      return Promise.resolve({ success: true, data: reading });
    }
  });

  const visible = root.textContent;
  assert.strictEqual(requests[0].url, "/word/materials");
  assert.strictEqual(requests[0].body.fileName, "资料.docx");
  assert.strictEqual(requests[0].body.documentSessionId, "doc-session-1");
  assert.ok(visible.includes("第一章 范围"));
  assert.ok(visible.includes("保留原文事实"));
  assert.ok(visible.includes("责任部门"));
  assert.ok(visible.includes("完成时间"));
  assert.ok(visible.includes("信息化处"));
  assert.ok(visible.includes("word/document.xml"));
  assert.ok(visible.includes("未读取"));
  assert.ok(!visible.includes("已理解全部"));
  assert.ok(visible.includes("实施参数"));
  assert.deepStrictEqual(writes, []);
  assert.deepStrictEqual(sourceSaves, []);
});

test("ribbon opens the material import pane without a document action", () => {
  const source = fs.readFileSync(path.join(pluginRoot, "ribbon.js"), "utf8");
  const created = [];
  const context = {
    window: {
      Application: {
        CreateTaskPane(url) {
          created.push(url);
          return { Visible: false };
        },
        confirm() {}
      }
    },
    location: { href: "file:///addon/ribbon.xml" }
  };
  context.window.window = context.window;
  vm.createContext(context);
  vm.runInContext(source, context);
  context.OnAction({ Id: "btnAiMaterialImport" });
  assert.strictEqual(created.length, 1);
  assert.ok(created[0].includes("mode=materialImport"));
  assert.strictEqual(context.window.Application.WpsAiAssistantTaskPane.Visible, true);
});

function createRoot() {
  return {
    textContent: "",
    appendChild(node) {
      this.textContent += node.textContent || "";
    }
  };
}
