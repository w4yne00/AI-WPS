const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const { etRoot: root } = require('./support/plugin-roots');
const ribbonXml = fs.readFileSync(path.join(root, 'ribbon.xml'), 'utf8');
const ribbonJs = fs.readFileSync(path.join(root, 'ribbon.js'), 'utf8');
const helpers = require(path.join(root, 'taskpane-helpers.js'));

function createTestHarness(sharedStorage) {
  const context = {
    window: {},
    console,
    Promise,
    Date,
    Math,
    Array,
    Object,
    setTimeout,
    clearTimeout,
    btoa: value => Buffer.from(value, "binary").toString("base64"),
  };
  const scriptContent = fs.readFileSync(path.join(root, 'material-ledger.js'), 'utf8');
  vm.runInNewContext(scriptContent, context);

  const storage = sharedStorage || new Map();
  const h = {
    session: 'sess-excel-doc-1',
    calls: [],
    views: [],
    copied: [],
    writeSpyCalls: [],
    scheduled: [],
    response: {
      success: true,
      data: {
        jobId: 'job-ledger-1',
        status: 'running',
        documentSessionId: 'sess-excel-doc-1',
      },
    },
  };

  // Mock WPS App with read-only selection and write-tracking spies
  const mockCells = {
    1: { 1: { Text: '事项名称', Value2: '事项名称' }, 2: { Text: '主责部门', Value2: '主责部门' }, 3: { Text: '截止时间', Value2: '截止时间' } },
  };

  h.mockApp = {
    Selection: {
      Address: '$A$1:$C$1',
      Rows: { Count: 1 },
      Columns: { Count: 3 },
      Cells: {
        Item(row, col) {
          const cellObj = (mockCells[row] && mockCells[row][col]) || { Text: '', Value2: '' };
          // Define write trap on Value, Value2, Formula
          return Object.defineProperties({}, {
            Text: { get: () => cellObj.Text },
            Value: {
              get: () => cellObj.Value2,
              set: (v) => { h.writeSpyCalls.push({ prop: 'Value', val: v }); },
            },
            Value2: {
              get: () => cellObj.Value2,
              set: (v) => { h.writeSpyCalls.push({ prop: 'Value2', val: v }); },
            },
            Formula: {
              get: () => '',
              set: (v) => { h.writeSpyCalls.push({ prop: 'Formula', val: v }); },
            },
          });
        },
      },
    },
  };

  h.api = context.window.createMaterialLedger({
    storage: {
      getItem: (k) => storage.get(k),
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    getSessionId: () => h.session,
    render: (v) => h.views.push(v),
    copyText: (t) => h.copied.push(t),
    schedule: fn => h.scheduled.push(fn),
    request: async (url, body, opts) => {
      h.calls.push({ url, body, method: opts && opts.method });
      if (h.requestHandler) {
        return h.requestHandler(url, body, opts);
      }
      if (url.startsWith('/excel/materials/catalog')) {
        return h.catalogResponse || {
          success: true,
          data: { totalDocuments: 0, totalCharacters: 0, documents: [] },
        };
      }
      if (url.startsWith('/materials/reusable-sources')) {
        return h.reusableSourcesResponse || {
          success: true,
          data: { sources: [] },
        };
      }
      if (url.startsWith('/excel/material-ledger/conflicts')) {
        return h.conflictsResponse || {
          success: true,
          data: { conflicts: [] },
        };
      }
      return h.response;
    },
  });

  h.context = context;
  h.storage = storage;
  h.last = () => h.views[h.views.length - 1];
  return h;
}

test('1. Ribbon XML and JS register btnAiExcelLedger mapping to excelLedger mode', () => {
  assert.ok(ribbonXml.includes('id="btnAiExcelLedger"'), 'ribbon.xml should have btnAiExcelLedger');
  assert.ok(ribbonXml.includes('label="任务台账"'), 'ribbon.xml should label button 任务台账');

  const context = { window: { Application: {} }, location: { href: 'http://test/' } };
  vm.runInNewContext(ribbonJs, context);
  const resolveMode = context.resolveMode;
  assert.equal(typeof resolveMode, 'function');
  assert.equal(resolveMode('btnAiExcelLedger'), 'excelLedger');
});

test('2. readSelectionHeaders extracts headers from selection range', () => {
  assert.equal(typeof helpers.readSelectionHeaders, 'function');

  const mockRange = {
    Columns: { Count: 4 },
    Rows: { Count: 1 },
    Cells: {
      Item(row, col) {
        const val = ['工作事项', ' 责任部门 ', '', '交付物验收'][col - 1];
        return { Text: val, Value2: val };
      },
    },
  };

  const headers = helpers.readSelectionHeaders({ Selection: mockRange });
  assert.deepEqual(headers, ['工作事项', '责任部门', '交付物验收']);

  // Empty selection returns []
  assert.deepEqual(helpers.readSelectionHeaders(null), []);
});

test('3. Controller headers management: default tags, add, remove, and read from selection', () => {
  const h = createTestHarness();
  const state = h.last();
  assert.deepEqual(Array.from(state.headers), ['工作事项', '责任部门', '完成时间', '交付物验收']);

  h.api.addHeader('风险等级');
  assert.ok(h.last().headers.includes('风险等级'));

  h.api.removeHeader(1); // Remove 责任部门
  assert.ok(!h.last().headers.includes('责任部门'));

  // Read headers from selection
  h.api.readSelectionHeaders(h.mockApp);
  assert.deepEqual(Array.from(h.last().headers), ['事项名称', '主责部门', '截止时间']);

  // Assert strictly 0 write calls made to worksheet
  assert.equal(h.writeSpyCalls.length, 0);
});

test('4. Materials management: import, list reusable sources, and clone', async () => {
  const h = createTestHarness();

  // Test list reusable sources
  h.reusableSourcesResponse = {
    success: true,
    data: {
      sources: [
        {
          sourceSessionId: 'sess-word-prev',
          displayName: '方案.docx',
          totalDocuments: 1,
          totalCharacters: 5000,
        },
      ],
    },
  };

  const sources = await h.api.listReusableSources();
  assert.equal(sources.length, 1);
  assert.equal(sources[0].displayName, '方案.docx');

  // Test clone
  h.requestHandler = async (url, body, opts) => {
    if (url === '/excel/materials/clone-from-source') {
      return {
        success: true,
        data: {
          totalDocuments: 1,
          totalCharacters: 5000,
          catalogSummary: {
            totalDocuments: 1,
            totalCharacters: 5000,
            documents: [{ materialId: 'cloned-m1', fileName: '方案.docx' }],
          },
        },
      };
    }
  };

  await h.api.cloneFromSource('sess-word-prev');
  const lastState = h.last();
  assert.equal(lastState.catalogSummary.totalDocuments, 1);
  assert.equal(lastState.catalogSummary.documents[0].fileName, '方案.docx');
});

test('5. Ledger generation lifecycle: submit, phase progression, and cancel', async () => {
  const h = createTestHarness();

  h.response = {
    success: true,
    data: {
      jobId: 'job-123',
      status: 'queued',
      documentSessionId: 'sess-excel-doc-1',
    },
  };

  await h.api.generate();
  assert.equal(h.last().status, 'queued');
  assert.ok(h.calls.some((c) => c.url === '/excel/material-ledger/jobs'));

  // Simulate cancel
  h.requestHandler = async (url, body, opts) => {
    if (url.includes('/cancel')) {
      return { success: true, data: { jobId: 'job-123', status: 'cancelled' } };
    }
  };

  await h.api.cancel();
  assert.equal(h.last().status, 'cancelled');
});

test('6. Result rendering and TSV formatting: missing fields, duplicates, citations', () => {
  const h = createTestHarness();

  const sampleResult = {
    schemaVersion: 'excel.material_ledger.v1',
    headers: ['工作事项', '责任部门', '完成时间', '交付物验收'],
    rows: [
      {
        rowIndex: 0,
        values: {
          '工作事项': '网络改造',
          '责任部门': '信息化部',
          '完成时间': '2026-10',
          '交付物验收': '验收报告',
        },
        missingFields: [],
        isDuplicate: false,
        duplicateOfIndex: null,
        duplicateReason: '',
        sources: [{ fileName: '建设任务.docx', chapter: '第一章', text: '原句' }],
      },
      {
        rowIndex: 1,
        values: {
          '工作事项': '安全审计整改',
          '责任部门': '安全组',
          '完成时间': '',
          '交付物验收': '整改台账',
        },
        missingFields: ['完成时间'],
        isDuplicate: true,
        duplicateOfIndex: 0,
        duplicateReason: '与网络改造同属配套安全',
        sources: [{ fileName: '建设任务.docx', chapter: '第一章', text: '原句2' }],
      },
    ],
    basisMaterials: [{ materialId: 'm1', fileName: '建设任务.docx', updatedAt: '2026-09-27' }],
  };

  h.api.setResult(sampleResult);
  const state = h.last();
  assert.ok(state.result);
  assert.equal(state.result.rows.length, 2);

  // Missing field check
  const row2 = state.result.rows[1];
  assert.deepEqual(Array.from(row2.missingFields), ['完成时间']);
  assert.equal(row2.isDuplicate, true);
  assert.equal(row2.duplicateOfIndex, 0);

  // TSV Export formatting
  const tsv = h.api.formatTsv(state.result);
  const lines = tsv.split('\n');
  assert.equal(lines[0], '工作事项\t责任部门\t完成时间\t交付物验收');
  assert.equal(lines[1], '网络改造\t信息化部\t2026-10\t验收报告');
  assert.equal(lines[2], '安全审计整改\t安全组\t\t整改台账');

  // Copy TSV
  h.api.copyTsv();
  assert.equal(h.copied.length, 1);
  assert.equal(h.copied[0], tsv);

  // Pure preview invariant: 0 writes to WPS cells throughout
  assert.equal(h.writeSpyCalls.length, 0);
});

test('7. Document isolation: switching document sessions preserves independent state', async () => {
  const h = createTestHarness();
  h.session = 'doc-1';
  h.api.addHeader('Doc1特有字段');
  assert.ok(h.last().headers.includes('Doc1特有字段'));

  // Switch to doc-2
  h.session = 'doc-2';
  await h.api.restore();
  assert.ok(!h.last().headers.includes('Doc1特有字段'));
  assert.deepEqual(Array.from(h.last().headers), ['工作事项', '责任部门', '完成时间', '交付物验收']);
});

test('file chooser uploads the actual filename and DOCX bytes', async () => {
  const h = createTestHarness();
  await h.api.importMaterial({ name: '方案.docx', arrayBuffer: async () => Uint8Array.from([1, 2, 3]).buffer });
  const call = h.calls.find(c => c.url === '/excel/materials/import');
  assert.equal(call.body.fileName, '方案.docx');
  assert.equal(call.body.contentBase64, 'AQID');
});

test('restore discovers reusable sources and excludes the current workbook', async () => {
  const h = createTestHarness();
  h.reusableSourcesResponse = { data: { sources: [
    { sourceSessionId: h.session, displayName: '当前工作簿' },
    { sourceSessionId: 'word-source', displayName: '方案.docx' }
  ] } };
  await h.api.restore();
  assert.deepEqual(Array.from(h.last().reusableSources, x => x.sourceSessionId), ['word-source']);
});

test('completion after switching workbooks stays with the submitted workbook', async () => {
  const h = createTestHarness();
  const result = { headers: ['工作事项'], rows: [{ values: { '工作事项': 'A任务' }, sources: [] }] };
  h.requestHandler = async url => url.endsWith('/jobs')
    ? { data: { jobId: 'job-A', status: 'running' } }
    : { data: { status: 'completed', result } };
  h.session = 'A';
  await h.api.generate();
  h.session = 'B';
  await h.scheduled.shift()();
  assert.equal(h.api.getState().result, null);
  h.session = 'A';
  assert.equal(h.api.getState().result.rows[0].values['工作事项'], 'A任务');
});

test('a missing recovered task stops polling and allows resubmission', async () => {
  const saved = new Map([['excel.material-ledger:sess-excel-doc-1', JSON.stringify({ jobId: 'lost' })]]);
  const h = createTestHarness(saved);
  h.requestHandler = async url => {
    if (url.includes('/jobs/')) throw Object.assign(new Error('任务不存在'), { status: 404, adapterCode: 'MATERIAL_LEDGER_JOB_NOT_FOUND' });
    return { data: { totalDocuments: 0, documents: [] } };
  };
  await h.api.restore();
  await h.scheduled.shift()();
  assert.equal(h.api.getState().status, 'interrupted');
  assert.equal(h.api.getState().jobId, '');
  assert.equal(h.scheduled.length, 0);
  assert.ok(h.api.getState().error);
});

test('an uncertain submission retries the original job and request', async () => {
  const h = createTestHarness();
  const submitted = [];
  h.requestHandler = async (url, body) => {
    if (url.endsWith('/jobs')) {
      submitted.push(JSON.parse(JSON.stringify(body)));
      throw new Error('Failed to fetch');
    }
    return { data: { conflicts: [] } };
  };
  await h.api.generate();
  h.api.setInstruction('编辑后的要求');
  await h.api.generate();
  assert.equal(submitted.length, 2);
  assert.deepEqual(submitted[1], submitted[0]);
});

function ledgerPaneHarness() {
  const source = fs.readFileSync(path.join(root, 'taskpane.js'), 'utf8');
  function node() { return { hidden: true, disabled: false, value: '', textContent: '', innerHTML: '', children: [],
    appendChild(child) { this.children.push(child); }, addEventListener() {} }; }
  const nodes = new Map();
  const byId = id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); };
  const head = node(), body = node();
  byId('ledger-preview-table').querySelector = selector => selector === 'thead' ? head : body;
  const context = { state: { currentMode: 'excelLedger' }, byId, helpers, document: { createElement: node }, setStatus() {}, ensureMaterialLedger() {} };
  const start = source.indexOf('function renderMaterialLedgerView(');
  const end = source.indexOf('\n  function ', start + 1);
  const render = vm.runInNewContext('(' + source.slice(start, end) + ')', context);
  return { render, byId, head, body };
}

test('the actual pane displays backend values and source quotes using result headers', () => {
  const pane = ledgerPaneHarness();
  pane.render({ headers: ['后续编辑的新列'], reusableSources: [], activeDrawerRowIndex: 0,
    result: { headers: ['工作事项'], rows: [{ values: { '工作事项': '网络改造' }, missingFields: [],
      sources: [{ fileName: '方案.docx', chapter: '第一章', text: '原文网络改造' }] }] } });
  assert.match(pane.head.innerHTML, /工作事项/);
  assert.match(pane.body.children[0].innerHTML, /网络改造/);
  assert.match(pane.body.children[0].innerHTML, /查看出处/);
  assert.match(pane.byId('drawer-content').children[0].innerHTML, /第一章/);
  assert.match(pane.byId('drawer-content').children[0].innerHTML, /原文网络改造/);
});

test('the actual pane exposes update, remove and conflict choices', () => {
  const pane = ledgerPaneHarness();
  pane.render({ headers: ['工作事项'], catalogSummary: { documents: [{ materialId: 'm1', fileName: '方案.docx' }] },
    reusableSources: [], conflicts: [{ conflictId: 'c1', topic: '预算', difference: '预算存在差异',
      options: [{ optionId: 'o1', value: '100万元', sourceName: '方案.docx' }] }], conflictResolutions: [] });
  const materials = pane.byId('ledger-material-list').innerHTML;
  assert.match(materials, /方案.docx/);
  assert.match(materials, /更新/);
  assert.match(materials, /移除/);
  assert.match(pane.byId('ledger-conflicts').innerHTML, /100万元/);
});

test('a selected conflict survives rechecking unchanged candidates and enables generation', async () => {
  const h = createTestHarness();
  h.conflictsResponse = { data: { conflicts: [{ conflictId: 'c1', topic: '预算',
    options: [{ optionId: 'o1', sourceName: '方案.docx', value: '100万元' }] }] } };
  await h.api.generate();
  assert.equal(h.calls.filter(c => c.url.endsWith('/jobs')).length, 0);
  h.api.setConflictResolutions([{ conflictId: 'c1', chosenCandidateId: 'o1', chosenValue: '100万元' }]);
  await h.api.generate();
  assert.equal(h.calls.filter(c => c.url.endsWith('/jobs')).length, 1);
});

test('a failed cancellation does not claim the running task was cancelled', async () => {
  const h = createTestHarness();
  await h.api.generate();
  h.requestHandler = async () => { throw new Error('connection lost'); };
  await h.api.cancel();
  assert.equal(h.api.getState().status, 'running');
  assert.equal(h.api.getState().busy, true);
  assert.match(h.api.getState().error, /取消失败/);
});

test('a delayed file read keeps its original workbook for upload and catalog reload', async () => {
  const h = createTestHarness();
  let finishRead;
  h.session = 'A';
  const upload = h.api.importMaterial({ name: 'A.docx', arrayBuffer: () => new Promise(resolve => { finishRead = resolve; }) });
  h.session = 'B';
  finishRead(Uint8Array.from([1]).buffer);
  await upload;
  const call = h.calls.find(c => c.url === '/excel/materials/import');
  assert.equal(call.body.documentSessionId, 'A');
  assert.ok(h.calls.some(c => c.url === '/excel/materials/catalog?documentSessionId=A'));
  assert.equal(h.api.getState().catalogSummary.totalDocuments, 0);
});

test('real ledger pane uploads files, previews backend rows and manages independent materials without cell writes', t => {
  const { execFileSync } = require('node:child_process');
  const os = require('node:os');
  try { execFileSync('agent-browser', ['--version'], { stdio: 'ignore' }); }
  catch (_) { t.skip('agent-browser unavailable'); return; }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'excel-ledger-pane-'));
  const run = (...args) => execFileSync('agent-browser', ['--session', 'excel-ledger-pane', ...args], {
    encoding: 'utf8', env: { ...process.env, AGENT_BROWSER_SOCKET_DIR: temp }
  });
  const mock = `
window.paneErrors=[];window.addEventListener('error',e=>paneErrors.push(e.message));
window.confirm=()=>true;window.requests=[];window.cellWrites=0;
var cell={Text:'工作事项'};['Value','Value2','Formula'].forEach(key=>Object.defineProperty(cell,key,{get:()=>'',set:()=>window.cellWrites++}));
var sheet={Name:'Sheet1',Range:()=>cell,Cells:{Item:()=>cell}};
window.Application={Selection:{Rows:{Count:1},Columns:{Count:1},Cells:{Item:()=>cell}},ActiveSheet:sheet,
ActiveWorkbook:{Name:'台账.xlsx',FullName:'/test/excel-ledger-browser.xlsx',ActiveSheet:sheet,Worksheets:{Item:()=>sheet}}};
window.catalog={totalDocuments:0,totalCharacters:0,documents:[]};
window.fetch=async function(url,options){
  var p=new URL(url).pathname, method=(options&&options.method)||'GET', body=options&&options.body?JSON.parse(options.body):null;
  requests.push({path:p,method:method,body:body});var data={};
  if(p==='/health')data={status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true};
  if(p==='/materials/reusable-sources')data={sources:[{sourceSessionId:'word-source',displayName:'原方案.docx',totalDocuments:1}]};
  if(p==='/excel/materials/catalog')data=catalog;
  if(p==='/excel/materials/import'||(p==='/excel/materials/m1'&&method==='PUT')){
    catalog={totalDocuments:1,totalCharacters:3,documents:[{materialId:'m1',fileName:body.fileName,updatedAt:'v1'}]};
    data={materialId:'m1',fileName:body.fileName};
  }
  if(p==='/excel/materials/m1'&&method==='DELETE'){catalog={totalDocuments:0,totalCharacters:0,documents:[]};data={catalogSummary:catalog};}
  if(p==='/excel/material-ledger/conflicts')data={conflicts:[]};
  if(p==='/excel/material-ledger/jobs')data={jobId:body.clientJobId,status:'completed',result:{
    headers:['工作事项','责任部门'],basisMaterials:[{materialId:'m1',updatedAt:'v1'}],rows:[
      {values:{'工作事项':'网络改造','责任部门':''},missingFields:['责任部门'],isDuplicate:true,duplicateOfIndex:0,duplicateReason:'重复提及',
       sources:[{fileName:'方案.docx',chapter:'第一章',text:'开展网络改造'}]}
    ]}};
  return {ok:true,status:200,json:async()=>({success:true,data:data})};
};`;
  let html = fs.readFileSync(path.join(root, 'taskpane.html'), 'utf8');
  html = html.replace('</head>', '<script>' + mock + '</script></head>');
  html = html.replace(/<script src="\.\/([^"?]+)[^"]*"><\/script>/g,
    (_, name) => '<script>' + fs.readFileSync(path.join(root, name), 'utf8') + '</script>');
  html = html.replace(/<link rel="stylesheet"[^>]+>/, '<style>' + fs.readFileSync(path.join(root, 'taskpane.css'), 'utf8') + '</style>');
  const page = path.join(temp, 'pane.html');
  fs.writeFileSync(page, html);
  const upload = name => run('eval', `(function(){var input=document.getElementById('excel-ledger-file-input'),dt=new DataTransfer();dt.items.add(new File([new Uint8Array([1,2,3])],${JSON.stringify(name)}));input.files=dt.files;input.dispatchEvent(new Event('change'));})()`);
  try {
    run('open', require('node:url').pathToFileURL(page).href + '?mode=excelLedger');
    run('set', 'viewport', '320', '900');
    run('wait', '--fn', "document.querySelector('#ledger-reusable-select').options.length===2");
    upload('方案.docx');
    run('wait', '--text', '方案.docx');
    assert.match(run('eval', "JSON.stringify(requests.find(r=>r.path==='/excel/materials/import').body)"), /AQID/);
    run('scrollintoview', '#btn-run-primary');
    run('click', '#btn-run-primary');
    run('wait', '--text', '网络改造');
    assert.match(run('get', 'text', '#ledger-preview-table'), /〔缺项〕/);
    assert.match(run('get', 'text', '#ledger-preview-table'), /疑似重复/);
    run('scrollintoview', '.btn-view-citation');
    run('click', '.btn-view-citation');
    run('wait', '--text', '开展网络改造');
    assert.match(run('get', 'text', '#drawer-content'), /第一章/);
    run('click', '#btn-close-drawer');
    run('eval', "document.querySelector('[data-ledger-update]').click()");
    upload('更新版.docx');
    run('wait', '--text', '更新版.docx');
    assert.equal(run('eval', "requests.filter(r=>r.method==='PUT').length").trim(), '1');
    run('eval', "document.querySelector('[data-ledger-remove]').click()");
    run('wait', '--fn', "document.querySelector('#ledger-material-list').textContent===''");
    assert.equal(run('eval', "requests.filter(r=>r.method==='DELETE').length").trim(), '1');
    assert.equal(run('eval', 'window.cellWrites').trim(), '0');
    assert.equal(run('eval', 'JSON.stringify(window.paneErrors)').trim(), '"[]"');
  } finally {
    try { run('close'); } catch (_) {}
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test('a late poll response cannot restore a cancelled job result', async () => {
  const h = createTestHarness();
  let finishPoll;
  h.requestHandler = async url => {
    if (url.endsWith('/jobs')) return { data: { jobId: 'late-job', status: 'running' } };
    if (url.endsWith('/cancel')) return { data: { jobId: 'late-job', status: 'cancelled' } };
    return new Promise(resolve => { finishPoll = resolve; });
  };
  // No conflicts in this fixture; keep the actual controller request pipeline.
  const handler = h.requestHandler;
  h.requestHandler = (url, ...args) => url.includes('/conflicts') ? { data: { conflicts: [] } } : handler(url, ...args);
  await h.api.generate();
  const poll = h.scheduled.shift()();
  await h.api.cancel();
  finishPoll({ data: { status: 'completed', result: { rows: [{ values: { '工作事项': '过期任务' } }] } } });
  await poll;
  assert.equal(h.api.getState().status, 'cancelled');
  assert.equal(h.api.getState().result, null);
});
