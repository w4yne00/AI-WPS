const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const { etRoot } = require('./support/plugin-roots');
const helpers = require(path.join(etRoot, 'taskpane-helpers.js'));
const ledgerFactory = require(path.join(etRoot, 'material-ledger.js')).createMaterialLedger;
const flush = () => new Promise(resolve => setImmediate(resolve));

function pane(kind = 'Analysis') {
  const modes = { Analysis: 'excelAnalysis', Formula: 'excelFormulaAssistant', SmartFill: 'excelSmartFill' };
  const types = { Analysis: 'excel.analysis', Formula: 'excel.formula_assistant', SmartFill: 'excel.smart_fill' };
  const elements = new Map(), storage = new Map(), timers = [], calls = [];
  let booting = true;
  function node(id) {
    if (!elements.has(id)) elements.set(id, { id, textContent: '', innerHTML: '', value: '', hidden: /^btn-(cancel|resubmit|stop)/.test(id), disabled: false,
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      setAttribute() {}, getAttribute() { return ''; }, querySelector() { return null; }, querySelectorAll() { return []; },
      addEventListener(event, callback) { this['on' + event] = callback; }, click() { if (this.onclick) this.onclick(); }, focus() {} });
    return elements.get(id);
  }
  const workbook = { Name: '测试.xlsx', __ai_wps_doc_session__: 'doc-A' };
  const context = {
    window: { WpsAiAssistantHelpers: { ...helpers, getDocumentSessionId: value => value.__ai_wps_doc_session__ }, Application: { ActiveWorkbook: workbook }, location: { search: '' },
      localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) } },
    document: { getElementById: id => booting ? null : node(id), querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
      body: { setAttribute() {} }, visibilityState: 'visible' },
    navigator: {}, AbortController, console,
    setTimeout: (fn, ms) => { const timer = { fn, ms }; timers.push(timer); return timer; },
    clearTimeout: timer => { const index = timers.indexOf(timer); if (index >= 0) timers.splice(index, 1); },
    fetch: (url, options = {}) => new Promise((resolve, reject) => {
      calls.push({ url, options, resolve: data => resolve({ ok: true, json: async () => ({ data }) }),
        reject, fail: (status, code) => resolve({ ok: false, status, json: async () => ({ errors: [{ code, message: '任务不存在' }] }) }) });
    })
  };
  const names = ['getExcelTaskSession', 'getCurrentExcelDocumentSession', 'syncActiveTaskBusyUi', 'syncActiveSessionView', 'bindEvents',
    'runExcelAnalysisAction', 'runExcelFormulaAction', 'runExcelSmartFillAction',
    'cancelQueuedExcelAnalysisJob', 'cancelQueuedExcelFormulaJob', 'cancelExcelSmartFillJob',
    'pollExcelAnalysisJob', 'pollExcelFormulaJob', 'pollExcelSmartFillJob',
    'resumeExcelAnalysisActiveJob', 'resumeExcelFormulaActiveJob', 'resumeExcelSmartFillActiveJob',
    'renderExcelAnalysisJobProgress', 'renderExcelFormulaJobProgress', 'renderExcelSmartFillJobProgress'];
  let source = fs.readFileSync(path.join(etRoot, 'taskpane.js'), 'utf8');
  source = source.replace('  if (!isTaskpanePage()) {', `
    window.lifecycle = { state: state, ${names.map(name => name + ':' + name).join(',')} };
    extractExcelRange = function () { return {table:{headers:['事项'],rows:[['A']]},scope:{sheetName:'Sheet1',address:'A1:A2'}}; };
    extractExcelFormulaRange = function () { return {selection:{address:'A1',sheetName:'Sheet1'},options:{mode:'generate',requirement:'求和'}}; };
    buildExcelSmartFillRequest = function (id) { return {clientJobId:id,source:{},userInstruction:'生成',documentSessionId:getCurrentExcelDocumentSession()}; };
    refreshDiagnostics = function () { return Promise.resolve(); };
    if (!isTaskpanePage()) {`);
  vm.runInNewContext(source, context);
  booting = false;
  const api = context.window.lifecycle;
  api.state.currentMode = modes[kind];
  api.state.documentSessionId = 'doc-A';
  api.state.smartFillLiveSource = { ok: true };
  node('excel-formula-requirement').value = '求和';
  node('excel-smart-fill-instruction').value = '生成';
  return { ...api, node, timers, calls, workbook, storage, type: types[kind], kind,
    run: () => api['runExcel' + kind + 'Action'](),
    cancel: () => api[kind === 'SmartFill' ? 'cancelExcelSmartFillJob' : 'cancelQueuedExcel' + kind + 'Job'](),
    tick: async () => { const timer = timers.find(timer => timer.ms === 0); if (timer) { timers.splice(timers.indexOf(timer), 1); timer.fn(); } await flush(); }
  };
}

for (const kind of ['Analysis', 'Formula', 'SmartFill']) {
  test(`${kind} keeps cancellation available while a running model is silent`, () => {
    const h = pane(kind);
    h['renderExcel' + kind + 'JobProgress']({ status: 'running', canCancel: true, phase: 'provider_processing' }, 'job-running');
    const suffix = { Analysis: 'analysis', Formula: 'formula', SmartFill: 'smart-fill' }[kind];
    assert.equal(h.node('btn-cancel-excel-' + suffix + '-job').hidden, false);
  });

  test(`${kind} can cancel while the submission response is pending`, async () => {
    const h = pane(kind);
    h.run();
    await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    assert.ok(post);
    const suffix = { Analysis: 'analysis', Formula: 'formula', SmartFill: 'smart-fill' }[kind];
    assert.equal(h.node('btn-cancel-excel-' + suffix + '-job').hidden, false);
    h.cancel();
    const cancel = h.calls.find(call => call.options.method === 'DELETE');
    assert.ok(cancel);
    cancel.fail(404, 'EXCEL_JOB_NOT_FOUND');
    await flush();
    assert.equal(helpers.isTaskSlotBusy(h.state.activeTaskSlots, 'et', h.type, 'doc-A'), true);
    post.resolve({ jobId: JSON.parse(post.options.body).clientJobId, status: 'running', canCancel: true });
    await flush();
    assert.equal(h.calls.filter(call => call.options.method === 'DELETE').length, 2, 'retry only cancellation after submission confirmation');
  });

  test(`${kind} stops automatic queries after bounded errors and continues the same task`, async () => {
    const h = pane(kind);
    h.run(); await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    const jobId = JSON.parse(post.options.body).clientJobId;
    post.resolve({ jobId, status: 'running', canCancel: true });
    await flush();
    for (let i = 0; i < 4; i++) {
      h.calls[h.calls.length - 1].reject(new Error('Failed to fetch'));
      await flush();
      if (i < 3) {
        const timer = h.timers.find(timer => timer.ms === 15000);
        assert.ok(timer);
        h.timers.splice(h.timers.indexOf(timer), 1); timer.fn(); await flush();
      }
    }
    assert.equal(h.getExcelTaskSession(h.type).paused, true);
    assert.equal(helpers.isTaskSlotBusy(h.state.activeTaskSlots, 'et', h.type, 'doc-A'), true);
    const suffix = { Analysis: '', Formula: '-formula', SmartFill: '-smart-fill' }[kind];
    const retry = h.node('btn-resubmit-interrupted' + suffix + '-job');
    assert.equal(retry.hidden, false);
    assert.equal(retry.textContent, '继续查询');
    h.bindEvents(); retry.click(); await flush();
    assert.equal(h.calls.filter(call => call.options.method === 'POST').length, 1);
    assert.ok(h.calls[h.calls.length - 1].url.includes(jobId));
  });

  test(`${kind} can pause before POST confirms and a late acknowledgement does not resume polling`, async () => {
    const h = pane(kind);
    h.run(); await h.tick();
    assert.equal(h.node('btn-stop-excel-task-wait').hidden, false);
    h.bindEvents(); h.node('btn-stop-excel-task-wait').click();
    assert.equal(h.getExcelTaskSession(h.type).paused, true);
    const post = h.calls.find(call => call.options.method === 'POST');
    post.resolve({ jobId: JSON.parse(post.options.body).clientJobId, status: 'running', canCancel: true });
    await flush();
    assert.equal(h.calls.filter(call => call.options.method === 'GET').length, 0);
    assert.match(h.node('status-line').textContent, /停止自动等待/);
  });

  test(`${kind} returning to the original workbook keeps cancel available and recovers a missing task`, async () => {
    const h = pane(kind);
    h.run(); await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    const jobId = JSON.parse(post.options.body).clientJobId;
    h.workbook.__ai_wps_doc_session__ = 'doc-B';
    h.syncActiveSessionView('doc-B');
    post.resolve({ jobId, status: 'running', canCancel: true });
    await flush();
    h.workbook.__ai_wps_doc_session__ = 'doc-A';
    h.syncActiveSessionView('doc-A');
    const suffix = { Analysis: 'analysis', Formula: 'formula', SmartFill: 'smart-fill' }[kind];
    assert.equal(h.node('btn-cancel-excel-' + suffix + '-job').hidden, false);
    h.calls[h.calls.length - 1].fail(404, 'EXCEL_JOB_NOT_FOUND');
    await flush();
    assert.equal(h.getExcelTaskSession(h.type, 'doc-A').jobId, '');
    h.run(); await h.tick();
    assert.equal(h.calls.filter(call => call.options.method === 'POST').length, 2);
  });

  test(`${kind} confirmed cancellation removes old waiting feedback timers`, async () => {
    const h = pane(kind);
    h.run(); await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    post.resolve({ jobId: JSON.parse(post.options.body).clientJobId, status: 'running', canCancel: true });
    await flush();
    h.cancel();
    h.calls[h.calls.length - 1].resolve({ status: 'cancelled' });
    await flush();
    assert.equal(h.timers.some(timer => timer.ms === 8000 || timer.ms === 30000), false);
    assert.match(h.node('status-line').textContent, /已取消/);
    assert.equal(helpers.isTaskSlotBusy(h.state.activeTaskSlots, 'et', h.type, 'doc-A'), false);
  });

  for (const missing of ['NOT_FOUND', 'INTERRUPTED']) test(`${kind} ${missing} restores a working fresh submission`, async () => {
    const h = pane(kind);
    const session = h.getExcelTaskSession(h.type);
    session.jobId = 'missing-job';
    session.pollStartedAt = Date.now();
    session.resumeExpected = true;
    helpers.claimTaskSlot(h.state.activeTaskSlots, 'et', h.type, 'doc-A', 'missing-job');
    h['pollExcel' + kind + 'Job']('missing-job', () => {}, 'doc-A');
    h.calls[0].fail(missing === 'NOT_FOUND' ? 404 : 410, 'EXCEL_' + (kind === 'SmartFill' ? 'SMART_FILL' : kind.toUpperCase()) + '_JOB_' + missing);
    await flush();
    assert.equal(session.jobId, '');
    assert.equal(helpers.isTaskSlotBusy(h.state.activeTaskSlots, 'et', h.type, 'doc-A'), false);
    const suffix = { Analysis: '', Formula: '-formula', SmartFill: '-smart-fill' }[kind];
    assert.equal(h.node('btn-resubmit-interrupted' + suffix + '-job').hidden, false);
    h.bindEvents();
    h.node('btn-resubmit-interrupted' + suffix + '-job').click();
    await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    assert.ok(post, 'retry must send a new task');
    assert.notEqual(JSON.parse(post.options.body).clientJobId, 'missing-job');
  });
}

for (const kind of ['Analysis', 'Formula']) test(`${kind} local preparation can be cancelled before any POST`, async () => {
  const h = pane(kind);
  h.run(); h.cancel(); await h.tick();
  assert.equal(h.calls.some(call => call.options.method === 'POST'), false);
  assert.equal(h.getExcelTaskSession(h.type).jobId, '');
  assert.equal(helpers.isTaskSlotBusy(h.state.activeTaskSlots, 'et', h.type, 'doc-A'), false);
});

for (const kind of ['Analysis', 'Formula']) {
  test(`${kind} resume timeout schedules recovery instead of leaving a permanently busy slot`, async () => {
    const h = pane(kind);
    // Save via the production submission path so the storage format remains real.
    h.run(); await h.tick();
    const post = h.calls.find(call => call.options.method === 'POST');
    const jobId = JSON.parse(post.options.body).clientJobId;
    const session = h.getExcelTaskSession(h.type);
    session.recoveryPending = true;
    const resumed = h['resumeExcel' + kind + 'ActiveJob']();
    assert.ok(resumed, 'production storage should be recoverable');
    h.calls[h.calls.length - 1].reject(new Error('Failed to fetch'));
    await resumed;
    assert.equal(session.jobId, jobId);
    assert.ok(h.timers.some(timer => timer.ms === 15000), 'resume failure must schedule another status query');
  });
}

test('ledger submission and status queries have bounded HTTP waits', async () => {
  const calls = [], scheduled = [];
  const ledger = ledgerFactory({ getSessionId: () => 'ledger-A', schedule: fn => scheduled.push(fn),
    request: async (url, body, options) => {
      calls.push({ url, body, options });
      if (url.includes('/conflicts')) return { data: { conflicts: [] } };
      return { data: { jobId: body ? body.clientJobId : 'ledger-job', status: 'running' } };
    }
  });
  await ledger.generate();
  await scheduled.shift()();
  assert.ok(calls.every(call => call.options.timeoutMs > 0));
});

test('ledger can cancel during conflict preparation without a later model submission', async () => {
  let finishPreparation;
  const calls = [];
  const ledger = ledgerFactory({ getSessionId: () => 'ledger-A', request: (url, body) => {
    calls.push(url);
    if (url.includes('/conflicts')) return new Promise(resolve => { finishPreparation = resolve; });
    return Promise.resolve({ data: { jobId: body.clientJobId, status: 'running' } });
  } });
  const pending = ledger.generate();
  await ledger.cancel();
  assert.equal(ledger.getState().busy, false);
  assert.equal(ledger.getState().status, 'cancelled');
  finishPreparation({ data: { conflicts: [] } });
  await pending;
  assert.equal(calls.some(url => url === '/excel/material-ledger/jobs'), false);
});

test('ledger retains cancellation intent when cancel races with submission registration', async () => {
  let finishPost;
  const calls = [];
  const ledger = ledgerFactory({ getSessionId: () => 'ledger-A', schedule() {}, request: (url, body) => {
    calls.push({ url, body });
    if (url.includes('/conflicts')) return Promise.resolve({ data: { conflicts: [] } });
    if (url.endsWith('/cancel')) {
      if (calls.filter(call => call.url.endsWith('/cancel')).length === 1) return Promise.reject(Object.assign(new Error('not found'), { status: 404 }));
      return Promise.resolve({ data: { status: 'cancelled' } });
    }
    return new Promise(resolve => { finishPost = () => resolve({ data: { jobId: body.clientJobId, status: 'running' } }); });
  } });
  const pending = ledger.generate();
  await flush();
  await ledger.cancel();
  assert.equal(ledger.getState().busy, true);
  finishPost();
  await pending;
  assert.equal(calls.filter(call => call.url.endsWith('/cancel')).length, 2);
  assert.equal(ledger.getState().status, 'cancelled');
});

test('ledger pauses unreachable status polling and continues the same job without another POST', async () => {
  const scheduled = [], calls = [];
  const ledger = ledgerFactory({ getSessionId: () => 'ledger-A', schedule: fn => scheduled.push(fn), request: (url, body) => {
    calls.push({ url, body });
    if (url.includes('/conflicts')) return Promise.resolve({ data: { conflicts: [] } });
    if (url.endsWith('/jobs')) return Promise.resolve({ data: { jobId: body.clientJobId, status: 'running' } });
    return Promise.reject(new Error('Failed to fetch'));
  } });
  await ledger.generate();
  const id = ledger.getState().jobId;
  for (let i = 0; i < 4; i++) await scheduled.shift()();
  assert.equal(ledger.getState().paused, true);
  assert.equal(scheduled.length, 0);
  await ledger.generate();
  assert.equal(ledger.getState().jobId, id);
  assert.equal(calls.filter(call => call.url.endsWith('/jobs')).length, 1);
  assert.equal(scheduled.length, 1);
});

test('ledger submission timeout recovers by status query and keeps cancellation available', async () => {
  const scheduled = [], calls = [];
  const ledger = ledgerFactory({ getSessionId: () => 'ledger-A', schedule: fn => scheduled.push(fn), request: (url, body) => {
    calls.push({ url, body });
    if (url.includes('/conflicts')) return Promise.resolve({ data: { conflicts: [] } });
    if (url.endsWith('/jobs')) return Promise.reject(new Error('Failed to fetch'));
    return Promise.resolve({ data: { status: 'running', canCancel: true } });
  } });
  await ledger.generate();
  assert.equal(ledger.getState().busy, true);
  assert.equal(ledger.getState().status, 'running');
  assert.equal(scheduled.length, 1);
  await scheduled.shift()();
  assert.equal(calls.filter(call => call.url.endsWith('/jobs')).length, 1);
  assert.equal(ledger.getState().pendingRequest, null);
});
