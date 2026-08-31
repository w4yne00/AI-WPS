const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function functionSource(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = source.indexOf("\n  function ", start + 1);
  return source.slice(start, next >= 0 ? next : source.length);
}

function taskDiagnostics() {
  return {
    maxRunning: 2,
    maxQueued: 8,
    runningCount: 2,
    queuedCount: 3,
    terminalCount: 4,
    maxTerminalJobs: 50,
    terminalTtlSeconds: 7200,
    cancelledCount: 5,
    rejectedCount: 6,
    timedOutCount: 7,
    recentTerminalJobs: [{
      taskType: "ppt.slide_assistant",
      status: "failed",
      elapsedSeconds: 42,
      errorCode: "PROVIDER_TIMEOUT",
      apiKey: "recent-terminal-secret",
      fileName: "完整上传文件名-近期终态.docx"
    }]
  };
}

function diagnosticResults() {
  return [
    {
      data: {
        taskType: "ppt.slide_assistant",
        traceId: "trace-safe",
        url: "https://model.example/v1/chat-messages",
        request: {
          bodyKeys: ["inputs", "query"],
          inputsKeys: ["query"],
          queryLength: 300,
          queryPreview: "不应显示的文档正文",
          plainText: "不应显示的用户全文",
          formula: "=SUM(A1:A99)",
          fileName: "完整上传文件名-机密项目.docx",
          apiKey: "request-secret"
        },
        error: {
          type: "ProviderTimeoutError",
          status: 504,
          message: "不应显示的异常正文"
        }
      }
    },
    { data: { configured: true, providerType: "enterprise-dify-chat" } },
    {
      data: {
        providerBaseUrlConfigured: true,
        url: "https://model.example/v1/chat-messages",
        longTaskCoordinator: taskDiagnostics()
      }
    },
    { data: { "ppt.slide_assistant": { configured: true, authSource: "task-file" } } }
  ];
}

function assertSanitized(text) {
  [
    "运行中：2/2",
    "排队中：3/8",
    "取消数：5",
    "拒绝数：6",
    "超时数：7",
    "耗时 42 秒",
    "PROVIDER_TIMEOUT"
  ].forEach((token) => assert.ok(text.includes(token), `missing ${token}`));
  [
    "request-secret",
    "recent-terminal-secret",
    "不应显示的文档正文",
    "不应显示的用户全文",
    "不应显示的异常正文",
    "=SUM(A1:A99)",
    "完整上传文件名-机密项目.docx",
    "完整上传文件名-近期终态.docx"
  ].forEach((token) => assert.ok(!text.includes(token), `leaked ${token}`));
}

const commonContext = {
  yesNo(value) {
    return value ? "是" : "否";
  },
  describeAuthSource(value) {
    return value || "未检测";
  },
  firstErrorMessage() {
    return "";
  }
};

const { wordRoot, etRoot, pptRoot } = require("./support/plugin-roots");

[
  path.join(wordRoot, "taskpane.js"),
  path.join(etRoot, "taskpane.js")
].forEach((filePath) => {
  const source = fs.readFileSync(filePath, "utf8");
  const render = vm.runInNewContext(
    `(${functionSource(source, "renderProviderDiagnostics")})`,
    commonContext
  );
  assertSanitized(render(...diagnosticResults()));
});

const pptSource = fs.readFileSync(
  path.join(pptRoot, "taskpane.js"),
  "utf8"
);
const renderPpt = vm.runInNewContext(
  `(${functionSource(pptSource, "renderProviderDiagnostics")})`,
  { FRONTEND_BUILD_VERSION: "test-build" }
);
assertSanitized(renderPpt(diagnosticResults()));

console.log("long task diagnostics tests passed");
