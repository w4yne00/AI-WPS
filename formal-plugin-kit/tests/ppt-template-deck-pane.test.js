const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { pptRoot } = require('./support/plugin-roots');

function pane() {
  const nodes = new Map(), storage = new Map(), requests = [], jobs = new Map();
  const node = id => {
    if (!nodes.has(id)) {
      const listeners = {};
      nodes.set(id, {
        value: '', textContent: '', innerHTML: '', hidden: true, disabled: false, style: {}, dataset: {},
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        setAttribute() {}, removeAttribute() {}, focus() {}, contains() { return false; },
        querySelectorAll() { return []; },
        addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
        click() { if (!this.disabled) for (const handler of listeners.click || []) handler({ target: this }); }
      });
    }
    return nodes.get(id);
  };
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const presentation = { Name: 'A.pptx', FullName: '/test/A.pptx', Slides: { Count: 3 } };
  const context = {
    window: {
      Application: { ActivePresentation: presentation },
      WpsAiPptHelpers: require(path.join(pptRoot, 'taskpane-helpers.js')),
      localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
      location: { search: '?mode=pptMaterialOutline' }, addEventListener() {}, confirm: () => true
    },
    document: { readyState: 'loading', hidden: false, body: node('body'), getElementById: node,
      querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {} },
    console, Promise, Date, Math, Array, Object, URLSearchParams, setTimeout, clearTimeout,
    fetch: async (url, options) => {
      const route = new URL(url).pathname;
      const body = options.body && JSON.parse(options.body);
      requests.push({ route, body });
      if (route === '/ppt/template-page/jobs') {
        jobs.set(body.clientJobId, body);
        if (requests.length === 1) await pending;
        return { ok: true, json: async () => ({ success: true, data: { jobId: body.clientJobId, status: 'running' } }) };
      }
      const job = jobs.get(decodeURIComponent(route.split('/').pop()));
      const data = h.failure ? { status: 'failed', error: { message: '模型服务暂不可用' } } : {
        status: 'completed', result: { pageIndex: job.pageIndex, pageRole: job.pageRole,
          title: job.outlineTitle, keyPoints: job.outlineKeyPoints, sources: [], missingItems: [], speakerNotes: '讲稿' }
      };
      return { ok: true, json: async () => ({ success: true, data }) };
    }
  };
  for (const file of ['material-outline.js', 'template-body-page.js', 'template-deck.js']) {
    vm.runInNewContext(fs.readFileSync(path.join(pptRoot, file), 'utf8'), context);
  }
  const source = fs.readFileSync(path.join(pptRoot, 'taskpane.js'), 'utf8');
  vm.runInNewContext(source.replace('  if (document.readyState === "loading") {',
    '  window.testApi = { state, bindEvents, ensureMaterialOutline, ensureTemplateDeck };\n  if (document.readyState === "loading") {'), context);
  const h = { node, requests, finish, ...context.window.testApi };
  h.state.taskMode = 'pptMaterialOutline';
  h.bindEvents();
  h.ensureMaterialOutline().current().result = {
    slides: [
      { pageIndex: 1, pageRole: 'cover', title: '架构汇报', keyPoints: ['方案介绍'] },
      { pageIndex: 2, pageRole: 'content', title: '分层架构', keyPoints: ['分层解耦'] }
    ], basisMaterials: []
  };
  node('btn-confirm-outline').click();
  return h;
}

async function waitForTerminal(h) {
  for (let i = 0; i < 100; i++) {
    if (['preview', 'failed'].includes(h.ensureTemplateDeck().getState().status)) {
      await new Promise(resolve => setImmediate(resolve));
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error('整套生成未到终态');
}

test('确认大纲后点击整套生成立即显示运行状态，完成后展示预览并恢复按钮', async () => {
  const h = pane();
  assert.equal(h.node('ppt-template-deck-card').hidden, false);
  h.node('btn-ppt-generate-template-deck').click();
  const running = {
    statusVisible: !h.node('ppt-template-deck-status').hidden,
    status: h.node('ppt-template-deck-status').textContent,
    disabled: h.node('btn-ppt-generate-template-deck').disabled,
    label: h.node('btn-ppt-generate-template-deck').textContent
  };
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, 1, '点击已实际提交首个页面任务');
  assert.equal(h.requests[0].body.pageRole, 'cover');
  h.finish();
  await waitForTerminal(h);
  assert.equal(running.statusVisible, true);
  assert.match(running.status, /正在生成整套/);
  assert.equal(running.disabled, true);
  assert.match(running.label, /正在生成/);
  assert.equal(h.node('ppt-template-deck-preview').hidden, false);
  assert.match(h.node('ppt-template-deck-preview').innerHTML, /分层架构/);
  assert.equal(h.node('btn-ppt-generate-template-deck').disabled, false);
  assert.equal(h.node('ppt-template-deck-status').hidden, true);
  assert.equal(h.node('btn-ppt-confirm-template-deck').hidden, false);
});

test('整套生成失败显示原因并恢复按钮，重试时清除失败状态', async () => {
  const h = pane();
  h.failure = true;
  h.node('btn-ppt-generate-template-deck').click();
  h.finish();
  await waitForTerminal(h);
  assert.equal(h.node('ppt-template-deck-status').hidden, false);
  assert.match(h.node('ppt-template-deck-status').textContent, /模型服务暂不可用/);
  assert.equal(h.node('btn-ppt-generate-template-deck').disabled, false);
  h.failure = false;
  h.node('btn-ppt-generate-template-deck').click();
  const retryStatus = h.node('ppt-template-deck-status').textContent;
  await waitForTerminal(h);
  assert.match(retryStatus, /正在生成整套/);
  assert.equal(h.node('ppt-template-deck-preview').hidden, false);
});

test('已确认的旧整套预览不遮挡重新生成的反馈或保留追加入口', async () => {
  const h = pane();
  h.node('btn-ppt-generate-template-deck').click();
  h.finish();
  await waitForTerminal(h);
  h.node('btn-ppt-confirm-template-deck').click();
  assert.equal(h.node('btn-ppt-append-template-deck').hidden, false);
  h.node('btn-ppt-generate-template-deck').click();
  const next = {
    cardVisible: !h.node('ppt-template-deck-card').hidden,
    statusVisible: !h.node('ppt-template-deck-status').hidden,
    previewHidden: h.node('ppt-template-deck-preview').hidden,
    appendHidden: h.node('btn-ppt-append-template-deck').hidden
  };
  await waitForTerminal(h);
  assert.deepEqual(next, { cardVisible: true, statusVisible: true, previewHidden: true, appendHidden: true });
});
