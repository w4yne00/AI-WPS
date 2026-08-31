const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { wordRoot: root } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

[
  'WRITING_ACTIVE_JOB_STORAGE_KEY = "ai-wps-writing-active-job-v1"',
  '"/word/smart-write/jobs"',
  '"/word/smart-imitation/jobs"',
  "saveWritingActiveJob",
  "resumeWritingActiveJob",
  "pollWritingJob",
  "cancelQueuedWritingJob",
  "clientJobId",
  "?resume=1"
].forEach((marker) => assert.ok(source.includes(marker), `missing ${marker}`));

assert.ok(!source.includes('request("/word/smart-write", state.latestDocumentPayload)'));
assert.ok(!source.includes('request("/word/smart-imitation", state.latestDocumentPayload)'));
assert.ok(source.includes('startWritingJob(state.latestDocumentPayload, "word.smart_write", "smartWrite")'));
assert.ok(source.includes('startWritingJob(state.latestDocumentPayload, "word.smart_imitation", "smartImitation")'));
assert.ok(source.includes("本次恢复结果仅供预览和复制"));

console.log("Word writing background job contracts passed");
