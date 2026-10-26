const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pptRoot } = require("./support/plugin-roots");
const { createTemplateDeck } = require(path.join(pptRoot, "template-deck.js"));
const { createTemplateBodyPage } = require(path.join(pptRoot, "template-body-page.js"));
const { createMaterialOutline } = require(path.join(pptRoot, "material-outline.js"));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(create) {
  const requests = [], pending = [], scheduled = [], storage = new Map();
  const options = {
    getSessionId: () => "doc-a", hasConfirmedOutline: () => true,
    getConfirmedOutline: () => ({ confirmed: true, slides: [{ pageIndex: 1, pageRole: "content", title: "正文", keyPoints: ["要点"] }, { pageIndex: 2, pageRole: "content", title: "正文二", keyPoints: ["要点二"] }] }),
    storage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    schedule: fn => scheduled.push(fn),
    request: (url, payload, config) => { const d = deferred(); requests.push({ url, payload, config }); pending.push(d); return d.promise; }
  };
  return { ctrl: create(options), options, requests, pending, scheduled };
}
test("整套模板在提交未确认时可停止，迟到结果不继续生成后续页面", async () => {
  const h = harness(createTemplateDeck);
  const generation = h.ctrl.startGenerate();
  await flush();
  assert.equal(typeof h.ctrl.cancelJob, "function");
  const cancellation = h.ctrl.cancelJob();
  h.pending[1].resolve({ success: true, data: { status: "cancelled" } });
  await cancellation;
  h.pending[0].resolve({ success: true, data: { jobId: h.requests[0].payload.clientJobId, status: "running" } });
  await flush();
  while (h.scheduled.length) h.scheduled.shift()();
  await generation;
  assert.equal(h.ctrl.getState().status, "cancelled");
  assert.equal(h.requests.filter(item => item.url === "/ppt/template-page/jobs").length, 1);
});
for (const [create, type] of [[createMaterialOutline, "outline"], [createTemplateBodyPage, "page"]]) {
  test(type + " retries cancel after a pending POST is finally accepted", async () => {
    const h = harness(create);
    const submission = type === "outline" ? h.ctrl.submit() : h.ctrl.startGenerate({ pageIndex: 1 });
    await flush();
    const cancellation = type === "outline" ? h.ctrl.cancel() : h.ctrl.cancelJob();
    h.pending[1].reject(Object.assign(new Error("任务尚未登记"), { status: 404 }));
    await Promise.resolve(cancellation).catch(() => {});
    h.pending[0].resolve({ success: true, data: { jobId: h.requests[0].payload.clientJobId, status: "running" } });
    await flush();
    assert.equal(h.requests.filter(item => /\/cancel$/.test(item.url)).length, 2);
    h.pending[2].resolve({ success: true, data: { status: "cancelled" } });
    await flush();
    while (h.scheduled.length) h.scheduled.shift()();
    await submission;
    assert.equal(type === "outline" ? h.ctrl.current().status : h.ctrl.getState().status, "cancelled");
  });
}

test("模板单页重开后继续查询原任务，不再次提交模型", async () => {
  const h = harness(createTemplateBodyPage);
  h.ctrl.startGenerate({ pageIndex: 1 });
  await flush();
  const reopened = createTemplateBodyPage(h.options);
  assert.equal(reopened.getState().status, "running");
  assert.equal(reopened.getState().pollPaused, true);
  reopened.startGenerate({ pageIndex: 1 });
  await flush();
  h.scheduled.shift()();
  await flush();
  assert.equal(h.requests.filter(item => item.url === "/ppt/template-page/jobs").length, 1);
  assert.match(h.requests[1].url, /\/ppt\/template-page\/jobs\//);
});

test("资料大纲提交超时保留任务号，仅查询已提交任务", async () => {
  const h = harness(createMaterialOutline);
  const submission = h.ctrl.submit();
  h.pending[0].reject(Object.assign(new Error("请求超时"), { name: "AbortError" }));
  await submission;
  assert.equal(h.ctrl.current().busy, true);
  assert.equal(h.scheduled.length, 1);
  h.scheduled.shift()();
  await flush();
  assert.equal(h.requests.filter(item => item.url === "/ppt/material-outline/jobs").length, 1);
  assert.match(h.requests[1].url, /\/ppt\/material-outline\/jobs\//);
});

test("整套模板停止未确认后，迟到查询不得继续提交下一页", async () => {
  const h = harness(createTemplateDeck);
  const generation = h.ctrl.startGenerate();
  await flush();
  h.pending[0].resolve({ success: true, data: { jobId: "job-a", status: "running" } });
  await flush();
  h.scheduled.shift()();
  await flush();
  const cancellation = h.ctrl.cancelJob().catch(() => {});
  h.pending[2].reject(Object.assign(new Error("停止超时"), { name: "AbortError" }));
  await cancellation;
  h.pending[1].resolve({ success: true, data: { status: "completed", result: { pageIndex: 1, keyPoints: ["要点"] } } });
  await flush();
  assert.equal(h.requests.filter(item => item.url === "/ppt/template-page/jobs").length, 1);
  assert.equal((await generation).status, "PAUSED");
  assert.equal(h.ctrl.getState().status, "paused");
});

test("整套模板暂停后立即继续，旧查询不得推进新的生成轮次", async () => {
  const h = harness(createTemplateDeck);
  const generation = h.ctrl.startGenerate();
  await flush();
  h.pending[0].resolve({ success: true, data: { jobId: "job-a", status: "running" } });
  await flush();
  h.scheduled.shift()();
  await flush();
  const cancellation = h.ctrl.cancelJob().catch(() => {});
  h.pending[2].reject(Object.assign(new Error("停止超时"), { name: "AbortError" }));
  await cancellation;
  h.ctrl.startGenerate();
  await flush();
  h.scheduled.shift()();
  await flush();
  assert.match(h.requests[3].url, /\/jobs\/job-a\?documentSessionId=/);
  h.pending[1].resolve({ success: true, data: { status: "completed", result: { pageIndex: 1, keyPoints: ["旧结果"] } } });
  await flush();
  assert.equal((await generation).status, "PAUSED");
  assert.equal(h.ctrl.getState().pages.length, 0);
  assert.equal(h.ctrl.getState().status, "running");
  assert.equal(h.requests.filter(item => item.url === "/ppt/template-page/jobs").length, 1);
});

for (const [create, type] of [[createMaterialOutline, "outline"], [createTemplateBodyPage, "page"]]) {
  test(type + " 取消遇到任务不存在后，继续查询释放旧任务并可重新提交", async () => {
    const h = harness(create);
    const start = () => type === "outline" ? h.ctrl.submit() : h.ctrl.startGenerate({ pageIndex: 1 });
    const submission = start();
    await flush();
    h.pending[0].resolve({ success: true, data: { jobId: "job-a", status: "running" } });
    await flush();
    const cancellation = type === "outline" ? h.ctrl.cancel() : h.ctrl.cancelJob();
    h.pending[1].reject(Object.assign(new Error("任务不存在"), { status: 404 }));
    await cancellation.catch(() => {});
    const resumed = start().catch(() => {});
    if (type === "page") h.scheduled.pop()();
    await flush();
    assert.match(h.requests[2].url, /\/jobs\/job-a\?documentSessionId=/);
    h.pending[2].reject(Object.assign(new Error("任务不存在"), { status: 404 }));
    await resumed;
    const state = type === "outline" ? h.ctrl.current() : h.ctrl.getState();
    assert.notEqual(state.status, "running");
    start();
    await flush();
    assert.equal(h.requests.filter(item => /\/jobs$/.test(item.url)).length, 2);
    if (type === "page") { while (h.scheduled.length) h.scheduled.shift()(); await submission; }
  });
}
