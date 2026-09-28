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
  assert.ok(!visible.includes("实施参数"));
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

test("on-demand writing has its own ribbon name and icon", () => {
  const xml = fs.readFileSync(path.join(pluginRoot, "ribbon.xml"), "utf8");
  const ribbon = fs.readFileSync(path.join(pluginRoot, "ribbon.js"), "utf8");
  const iconPath = path.join(pluginRoot, "assets/icon-on-demand-write.png");
  assert.match(xml, /id="btnAiMaterialImport" label="按需编写"/);
  assert.match(ribbon, /btnAiMaterialImport: "assets\/icon-on-demand-write\.png"/);
  assert.ok(fs.existsSync(iconPath));
  const icon = fs.readFileSync(iconPath);
  assert.equal(icon.readUInt32BE(16), 32);
  assert.equal(icon.readUInt32BE(20), 32);
});

function createRoot() {
  return {
    textContent: "",
    appendChild(node) {
      this.textContent += node.textContent || "";
    }
  };
}


test("material reading renders into a real browser DOM", (t) => {
  const { execFileSync } = require("child_process");
  const os = require("os");
  try { execFileSync("agent-browser", ["--version"], { stdio: "ignore" }); }
  catch (_) { t.skip("agent-browser unavailable"); return; }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "material-dom-"));
  const run = (...args) => execFileSync("agent-browser", ["--session", "mi-" + path.basename(temp).slice(-6), ...args], {
    encoding: "utf8", env: { ...process.env, AGENT_BROWSER_SOCKET_DIR: temp }
  });
  const source = fs.readFileSync(path.join(pluginRoot, "material-import.js"), "utf8");
  const page = path.join(temp, "reading.html");
  fs.writeFileSync(page, '<meta charset="utf-8"><pre id="result"></pre><script>' + source +
    ';submitMaterialImport({root:document.getElementById("result"),request:function(){return {data:{blocks:[{kind:"paragraph",text:"正文甲\\n正文乙"}]}};}}).catch(function(e){document.body.textContent=e.toString();});</script>');
  try {
    run("open", require("url").pathToFileURL(page).href);
    assert.ok(run("get", "text", "body").includes("正文甲\n正文乙"));
  } finally {
    try { run("close"); } finally { fs.rmSync(temp, { recursive: true, force: true }); }
  }
});

test('DOC conversion disables macros, converts a temporary copy and restores the active document', async () => {
  const api = loadMaterialImport();
  const events = [];
  const active = {Activate(){ events.push('restore'); }};
  const converted = {SaveAs2(file, format){ events.push(['save', file, format]); }, Close(save){ events.push(['close', save]); }};
  const app = {AutomationSecurity:1, DisplayAlerts:1, Options:{UpdateLinksAtOpen:true}, ActiveDocument:active,
    Documents:{Open(...args){ assert.equal(app.AutomationSecurity,3); assert.equal(app.Options.UpdateLinksAtOpen,false); assert.equal(args[2],true); assert.equal(args[11],false); events.push(['open',args[0]]); return converted; }}};
  const calls = [];
  const reading = await api.submitMaterialImport({fileName:'参考.doc', documentSessionId:'doc-a', application:app,
    request:async (url, body) => {
      calls.push(body);
      return calls.length === 1 ? {success:true,data:{conversionRequired:true, conversionId:'token', sourcePath:'/tmp/source.doc', targetPath:'/tmp/converted.docx'}} : {success:true,data:{fileName:'参考.doc',blocks:[]}};
    }});
  assert.equal(reading.fileName,'参考.doc');
  assert.equal(calls[1].conversionId,'token');
  assert.equal(app.AutomationSecurity,1);
  assert.equal(app.Options.UpdateLinksAtOpen,true);
  assert.deepEqual(events, [['open','/tmp/source.doc'],['save','/tmp/converted.docx',12],['close',0],'restore']);
});
