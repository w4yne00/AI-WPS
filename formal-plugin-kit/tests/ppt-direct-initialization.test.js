const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { pptRoot } = require('./support/plugin-roots');
const source = fs.readFileSync(path.join(pptRoot, 'taskpane.js'), 'utf8');
const helpers = require(path.join(pptRoot, 'taskpane-helpers.js'));
const tasks = ['ppt.slide_assistant', 'ppt.structure_review'];
function pane(failConfig = false, mode = '') {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: '', innerHTML: '', textContent: '', dataset: {}, style: {}, hidden: false,
      classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
      setAttribute() {}, removeAttribute() {}, addEventListener() {}, focus() {}, contains() { return false; }, querySelectorAll() { return []; } });
    return nodes.get(id);
  };
  const calls = [];
  const taskApiKeys = Object.fromEntries(tasks.map(taskType => [taskType, { accessMethod: 'direct_model', activeProfileId: 'direct_svc_old' }]));
  const selections = Object.fromEntries(tasks.map(taskType => [taskType, { taskType, serviceId: 'direct_svc_old', modelName: 'custom', customModel: true, customModelValidated: true }]));
  const context = {
    window: { setTimeout(fn, delay) { if (!delay) Promise.resolve().then(fn); return 1; }, clearTimeout() {}, WpsAiPptHelpers: helpers, location: { search: mode ? '?mode=' + mode : '' }, addEventListener() {}, localStorage: { getItem() { return null; } } },
    document: { readyState: 'loading', hidden: false, body: node('body'), getElementById: node, querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {} },
    console, URLSearchParams, setTimeout() { return 1; }, clearTimeout() {}, setInterval() { return 1; }, clearInterval() {},
    fetch: async url => {
      const route = url.replace('http://127.0.0.1:18100', ''); calls.push(route);
      if (route === '/config' && failConfig) throw new Error('offline');
      if (route.endsWith('/direct_svc_new/activate')) throw new Error('activation failed');
      if (route === '/conflict') return { ok: false, status: 409, json: async () => ({ success: false, errors: [{ code: 'DIRECT_SERVICE_REFERENCED', message: 'referenced', referencedTasks: tasks }] }) };
      let data = {};
      if (route === '/config') data = { taskApiKeys };
      if (route === '/health') data = { status: 'ok' };
      if (route.startsWith('/provider/model-configurations?')) data = { taskType: decodeURIComponent(route.split('=')[1]), activeProfileId: '', profiles: [] };
      if (route === '/provider/direct-services') data = { directServices: [{ id: 'direct_svc_old', name: '共享服务', keyConfigured: false }] };
      if (route.startsWith('/provider/task-model-selections?')) data = { taskModelSelections: selections };
      return { ok: true, status: 200, json: async () => ({ success: true, data: JSON.parse(JSON.stringify(data)) }) };
    }
  };
  const exported = source.replace('  if (document.readyState === "loading") {', '  window.testApi = { state, initialize, refreshSettings, request, getWorkflowProfileData, validateActiveDirectTaskSelection, applyTaskModelConfigMenuItem, saveTaskModelSelection, finishWorkflowEditorSave, submitPptSlideJob, submitStructureReviewJob };\n  if (document.readyState === "loading") {');
  vm.runInNewContext(exported, context);
  return { ...context.window.testApi, node, calls, setTaskStatus(task, status) { taskApiKeys[task] = status; } };
}
async function settle(p) { for (let i = 0; i < 30; i++) await Promise.resolve(); if (p.state.configRefreshPromise) await p.state.configRefreshPromise; }
test('real home initialization restores authoritative direct selections and blocks missing keys', async () => {
  const p = pane(); p.initialize(); await settle(p);
  assert.ok(p.calls.includes('/config'));
  for (const task of tasks) {
    assert.equal(p.getWorkflowProfileData(task).activeProfileId, 'direct_svc_old');
    assert.equal(p.state.workflowProfileSelections[task], 'direct_svc_old');
    assert.equal(p.validateActiveDirectTaskSelection(task).valid, false);
  }
  p.submitPptSlideJob({});
  p.submitStructureReviewJob({});
  assert.equal(p.calls.some(route => route.startsWith('/ppt/')), false);
});
test('unknown or failed authoritative configuration blocks submission', async () => {
  const p = pane(true);
  assert.equal(p.validateActiveDirectTaskSelection(tasks[0]).valid, false);
  p.initialize(); await settle(p);
  assert.equal(p.validateActiveDirectTaskSelection(tasks[1]).valid, false);
});
test('request preserves real HTTP 409 referencing task details', async () => {
  const p = pane();
  await assert.rejects(p.request('/conflict'), error => error.status === 409 && JSON.stringify(error.referencedTasks) === JSON.stringify(tasks));
});
test('reopened custom selection reuses persisted validation only for the same service and model', async () => {
  const p = pane(); p.initialize(); await settle(p);
  p.node('ppt-task-direct-service-select').value = 'direct_svc_old';
  p.node('ppt-task-custom-model-check').checked = true;
  p.node('ppt-task-custom-model-input').value = 'changed';
  await p.saveTaskModelSelection();
  assert.equal(p.calls.some(route => route.endsWith('/activate')), false);
  p.node('ppt-task-custom-model-input').value = 'custom';
  await p.saveTaskModelSelection();
  assert.ok(p.calls.includes('/provider/direct-services/direct_svc_old/activate'));
});

test('actual compact menu activation failure restores the active shared service for both PPT tasks', async () => {
  for (const task of tasks) {
    const p = pane(); p.initialize(); await settle(p);
    p.state.taskMode = task === tasks[0] ? 'pptSlideAssistant' : 'pptStructureReview';
    p.state.workflowTaskType = task;
    p.state.directServices.push({ id: 'direct_svc_new', name: '新服务', serviceBaseUrl: 'https://example.com/v1', keyConfigured: true });
    p.applyTaskModelConfigMenuItem({ action: 'select', id: 'direct_svc_new' }, false);
    await settle(p);
    assert.ok(p.calls.includes('/provider/direct-services/direct_svc_new/activate'));
    assert.equal(p.state.workflowProfileSelections[task], 'direct_svc_old');
    assert.equal(p.state.selectedProfileId, 'direct_svc_old');
  }
});

test('settings entry loads the same authoritative task state as home', async () => {
  const p = pane(false, 'settings'); p.initialize(); await settle(p);
  p.state.settingsRefreshController.stop();
  assert.ok(p.calls.includes('/config'));
  for (const task of tasks) assert.equal(p.getWorkflowProfileData(task).activeProfileId, 'direct_svc_old');
});

test('workflow editor completion reloads the newly activated workflow from config', async () => {
  const p = pane(); p.initialize(); await settle(p);
  p.setTaskStatus(tasks[0], { accessMethod: 'workflow_platform', activeProfileId: 'flow-new' });
  await p.finishWorkflowEditorSave('已保存');
  assert.equal(p.getWorkflowProfileData(tasks[0]).activeProfileId, 'flow-new');
  assert.equal(p.validateActiveDirectTaskSelection(tasks[0]).applicable, false);
});
test('direct mode without any selected service fails closed', async () => {
  const p = pane(); p.initialize(); await settle(p);
  p.state.taskApiKeys[tasks[0]] = { accessMethod: 'direct_model' };
  p.state.taskModelSelections[tasks[0]] = {};
  assert.equal(p.validateActiveDirectTaskSelection(tasks[0]).valid, false);
});

test('incomplete task status is unavailable, while explicit unconfigured status remains supported', async () => {
  const p = pane();
  p.setTaskStatus(tasks[0], {}); p.initialize(); await settle(p);
  assert.equal(p.validateActiveDirectTaskSelection(tasks[0]).valid, false);
  p.setTaskStatus(tasks[0], { configured: false, accessMethod: '', activeProfileId: '' });
  await p.refreshSettings({ silent: true });
  assert.equal(p.state.taskConfigurationReady, true);
});
