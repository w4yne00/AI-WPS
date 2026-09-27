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

function createMockGridApp(config) {
  const opts = config || {};
  const activeSheetName = opts.sheetName || 'Sheet1';
  const docSessionId = opts.documentSessionId || 'sess-excel-doc-1';
  const grid = opts.cells || {};
  const sheetProtected = Boolean(opts.sheetProtected);
  const cellStore = {};

  function cellKey(r, c) {
    return `${r},${c}`;
  }

  function getCell(r, c) {
    const k = cellKey(r, c);
    if (!cellStore[k]) {
      const cellData = grid[k] || {};
      let val = cellData.Value2 !== undefined ? cellData.Value2 : (cellData.Value !== undefined ? cellData.Value : null);
      cellStore[k] = {
        Row: r,
        Column: c,
        get Value2() {
          if (typeof cellData.onRead === 'function') cellData.onRead();
          return val;
        },
        set Value2(newVal) {
          if (typeof cellData.onWrite === 'function') {
            cellData.onWrite(newVal);
          }
          val = newVal;
        },
        get Value() { return val; },
        set Value(newVal) { val = newVal; },
        HasFormula: Boolean(cellData.HasFormula || cellData.Formula || cellData.formula),
        Formula: cellData.Formula || cellData.formula || '',
        MergeCells: Boolean(cellData.MergeCells || cellData.mergeCells),
        EntireRow: { Hidden: Boolean(cellData.rowHidden) },
        EntireColumn: { Hidden: Boolean(cellData.colHidden) },
        Locked: cellData.Locked !== undefined ? Boolean(cellData.Locked) : true
      };
    }
    return cellStore[k];
  }

  const selectionRow = opts.selectionRow || 2;
  const selectionCol = opts.selectionCol || 1;
  const selectionRowCount = opts.selectionRowCount || 1;
  const selectionColCount = opts.selectionColCount || 1;

  const app = {
    ActiveWorkbook: {
      Name: opts.workbookName || '测试台账.xlsx',
      FullName: opts.workbookPath || '/test/测试台账.xlsx',
      wps_doc_session_id: docSessionId
    },
    ActiveSheet: {
      Name: activeSheetName,
      ProtectContents: sheetProtected,
      Cells: {
        Item: (r, c) => getCell(r, c)
      },
      Range: (r1, c1, r2, c2) => {
        return {
          Item: (r, c) => getCell(r, c)
        };
      }
    },
    Selection: {
      Row: selectionRow,
      Column: selectionCol,
      Rows: { Count: selectionRowCount },
      Columns: { Count: selectionColCount },
      Cells: {
        Item: (r, c) => getCell(r, c)
      }
    },
    getCellValue(r, c) {
      return getCell(r, c).Value2;
    }
  };
  return app;
}

test('resolveExcelLedgerTargetRange calculates bounding box for single-cell selection', () => {
  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const rangeInfo = helpers.resolveExcelLedgerTargetRange(app, 5, 4);
  assert.strictEqual(rangeInfo.startRow, 2);
  assert.strictEqual(rangeInfo.startCol, 1);
  assert.strictEqual(rangeInfo.endRow, 6);
  assert.strictEqual(rangeInfo.endCol, 4);
  assert.strictEqual(rangeInfo.rowCount, 5);
  assert.strictEqual(rangeInfo.colCount, 4);
  assert.strictEqual(rangeInfo.targetAddress, 'A2:D6');
  assert.strictEqual(rangeInfo.sheetName, 'Sheet1');
});

test('resolveExcelLedgerTargetRange accepts multi-cell selection with sufficient capacity', () => {
  const app = createMockGridApp({ selectionRow: 3, selectionCol: 2, selectionRowCount: 10, selectionColCount: 5 });
  const rangeInfo = helpers.resolveExcelLedgerTargetRange(app, 5, 4);
  assert.strictEqual(rangeInfo.startRow, 3);
  assert.strictEqual(rangeInfo.startCol, 2);
  assert.strictEqual(rangeInfo.endRow, 7);
  assert.strictEqual(rangeInfo.endCol, 5);
  assert.strictEqual(rangeInfo.targetAddress, 'B3:E7');
});

test('resolveExcelLedgerTargetRange rejects multi-cell selection with insufficient capacity', () => {
  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 3, selectionColCount: 2 });
  assert.throws(() => {
    helpers.resolveExcelLedgerTargetRange(app, 5, 4);
  }, /选区尺寸不足以容纳/);
});

test('validateExcelLedgerTargetBlank succeeds on completely blank range', () => {
  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const rangeInfo = helpers.resolveExcelLedgerTargetRange(app, 3, 2);
  const result = helpers.validateExcelLedgerTargetBlank(app, rangeInfo, { documentSessionId: 'sess-excel-doc-1' });
  assert.strictEqual(result.valid, true);
  assert.strictEqual(result.cells.length, 6);
});

test('validateExcelLedgerTargetBlank rejects cells with existing values, formulas, merged, or hidden', () => {
  // Existing text
  const appWithText = createMockGridApp({
    cells: { '3,2': { Value2: '已有内容' } }
  });
  const range1 = { startRow: 2, startCol: 1, endRow: 4, endCol: 3, targetAddress: 'A2:C4', sheetName: 'Sheet1', rowCount: 3, colCount: 3 };
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(appWithText, range1, { documentSessionId: 'sess-excel-doc-1' });
  }, /目标区域包含已有数据/);

  // Existing formula
  const appWithFormula = createMockGridApp({
    cells: { '2,2': { Formula: '=SUM(A1)' } }
  });
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(appWithFormula, range1, { documentSessionId: 'sess-excel-doc-1' });
  }, /包含公式/);

  // Merged cell
  const appWithMerged = createMockGridApp({
    cells: { '2,1': { MergeCells: true } }
  });
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(appWithMerged, range1, { documentSessionId: 'sess-excel-doc-1' });
  }, /合并单元格/);

  // Hidden row
  const appWithHidden = createMockGridApp({
    cells: { '2,1': { rowHidden: true } }
  });
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(appWithHidden, range1, { documentSessionId: 'sess-excel-doc-1' });
  }, /隐藏/);

  // Document session mismatch
  const normalApp = createMockGridApp();
  assert.throws(() => {
    helpers.validateExcelLedgerTargetBlank(normalApp, range1, { documentSessionId: 'sess-different-workbook' });
  }, /工作簿/);
});

test('sanitizeExcelLedgerCellValue escapes formulas and keeps missing fields blank', () => {
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue('=SUM(A1)'), "'=SUM(A1)");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue('+123'), "'+123");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue('-cmd'), "'-cmd");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue('@macro'), "'@macro");
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(''), '');
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(null), '');
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(undefined), '');
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue('正常文本'), '正常文本');
  assert.strictEqual(helpers.sanitizeExcelLedgerCellValue(42), 42);
});

test('writeExcelMaterialLedger successfully writes headers and rows to blank area', () => {
  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const result = {
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] },
      { values: { '工作事项': '任务2', '责任部门': null }, missingFields: ['责任部门'] }
    ]
  };

  const report = helpers.writeExcelMaterialLedger(app, result, {
    includeHeaders: true,
    documentSessionId: 'sess-excel-doc-1'
  });

  assert.strictEqual(report.success, true);
  assert.strictEqual(report.writtenCount, 6);
  assert.strictEqual(report.targetAddress, 'A2:B4');
  assert.strictEqual(report.sheetName, 'Sheet1');
  assert.strictEqual(report.includeHeaders, true);

  // Row 2: Headers
  assert.strictEqual(app.getCellValue(2, 1), '工作事项');
  assert.strictEqual(app.getCellValue(2, 2), '责任部门');
  // Row 3: Data row 1
  assert.strictEqual(app.getCellValue(3, 1), '任务1');
  assert.strictEqual(app.getCellValue(3, 2), '技术部');
  // Row 4: Data row 2 (missing field must be blank '')
  assert.strictEqual(app.getCellValue(4, 1), '任务2');
  assert.strictEqual(app.getCellValue(4, 2), '');
});

test('writeExcelMaterialLedger supports includeHeaders: false and formula injection defense', () => {
  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const result = {
    headers: ['工作事项', '金额'],
    rows: [
      { values: { '工作事项': '=SUM(A1:A10)', '金额': '+5000' }, missingFields: [] }
    ]
  };

  const report = helpers.writeExcelMaterialLedger(app, result, {
    includeHeaders: false,
    documentSessionId: 'sess-excel-doc-1'
  });

  assert.strictEqual(report.success, true);
  assert.strictEqual(report.writtenCount, 2);
  assert.strictEqual(report.targetAddress, 'A2:B2');
  assert.strictEqual(report.includeHeaders, false);

  // Formulas escaped with leading single quote
  assert.strictEqual(app.getCellValue(2, 1), "'=SUM(A1:A10)");
  assert.strictEqual(app.getCellValue(2, 2), "'+5000");
});

test('writeExcelMaterialLedger rolls back on mid-write failure (COMPENSATION_SUCCEEDED)', () => {
  const app = createMockGridApp({
    selectionRow: 2,
    selectionCol: 1,
    cells: {
      '3,2': {
        onWrite: () => {
          throw new Error('COM write error at cell 3,2');
        }
      }
    }
  });

  const result = {
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }
    ]
  };

  assert.throws(() => {
    helpers.writeExcelMaterialLedger(app, result, {
      includeHeaders: true,
      documentSessionId: 'sess-excel-doc-1'
    });
  }, (err) => {
    assert.strictEqual(err.code, 'COMPENSATION_SUCCEEDED');
    assert.ok(err.message.includes('台账写入失败，已成功将已写入单元格恢复为空白'));
    return true;
  });

  // Verify previously written cells (A2, B2, A3) have been restored to ''
  assert.strictEqual(app.getCellValue(2, 1), '');
  assert.strictEqual(app.getCellValue(2, 2), '');
  assert.strictEqual(app.getCellValue(3, 1), '');
});

test('writeExcelMaterialLedger reports COMPENSATION_FAILED if rollback fails', () => {
  let failRollback = false;
  const app = createMockGridApp({
    selectionRow: 2,
    selectionCol: 1,
    cells: {
      '2,1': {
        onWrite: (val) => {
          if (failRollback && val === '') {
            throw new Error('Rollback failed at 2,1');
          }
        }
      },
      '2,2': {
        onWrite: () => {
          failRollback = true;
          throw new Error('Write failed at 2,2');
        }
      }
    }
  });

  const result = {
    headers: ['工作事项', '责任部门'],
    rows: [{ values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }]
  };

  assert.throws(() => {
    helpers.writeExcelMaterialLedger(app, result, {
      includeHeaders: true,
      documentSessionId: 'sess-excel-doc-1'
    });
  }, (err) => {
    assert.strictEqual(err.code, 'COMPENSATION_FAILED');
    assert.ok(Array.isArray(err.rollbackFailures));
    assert.ok(err.rollbackFailures.includes('A2'));
    return true;
  });
});

test('ledger controller inspectTargetRange updates state with target address and valid status', () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }
    ]
  });

  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const inspection = h.api.inspectTargetRange(app);
  assert.strictEqual(inspection.valid, true);
  assert.strictEqual(h.api.getState().includeHeaders, true);
  assert.strictEqual(h.api.getState().writeStatus, 'ready');
  assert.strictEqual(h.api.getState().targetRangeInfo.targetAddress, 'A2:B3');
  assert.strictEqual(h.api.getState().targetRangeInfo.rowCount, 2);
});

test('ledger controller setIncludeHeaders toggles header inclusion and recalculates range', () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }
    ]
  });

  h.api.setIncludeHeaders(false);
  assert.strictEqual(h.api.getState().includeHeaders, false);

  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  const inspection = h.api.inspectTargetRange(app);
  assert.strictEqual(inspection.valid, true);
  assert.strictEqual(h.api.getState().targetRangeInfo.targetAddress, 'A2:B2');
  assert.strictEqual(h.api.getState().targetRangeInfo.rowCount, 1);
});

test('ledger controller writeToSheet writes to sheet and updates writeStatus to success', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }
    ]
  });

  const app = createMockGridApp({ selectionRow: 2, selectionCol: 1, selectionRowCount: 1, selectionColCount: 1 });
  h.api.inspectTargetRange(app);
  const report = await h.api.writeToSheet(app);
  assert.strictEqual(report.success, true);
  assert.strictEqual(h.api.getState().writeStatus, 'success');
  assert.strictEqual(app.getCellValue(2, 1), '工作事项');
  assert.strictEqual(app.getCellValue(3, 1), '任务1');
});

test('ledger controller writeToSheet updates writeStatus to error on write failure', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({
    headers: ['工作事项', '责任部门'],
    rows: [
      { values: { '工作事项': '任务1', '责任部门': '技术部' }, missingFields: [] }
    ]
  });

  const app = createMockGridApp({
    selectionRow: 2,
    selectionCol: 1,
    cells: {
      '2,1': {
        onWrite: () => {
          throw new Error('Write failed at 2,1');
        }
      }
    }
  });

  h.api.inspectTargetRange(app);
  await assert.rejects(async () => {
    await h.api.writeToSheet(app);
  }, /写入失败/);

  assert.strictEqual(h.api.getState().writeStatus, 'error');
  assert.ok(h.api.getState().writeError.includes('写入失败'));
});

test('ledger review rejects selection, sheet and workbook changes after target confirmation', async () => {
  for (const change of [
    app => { app.Selection.Row = 10; },
    app => { app.ActiveSheet.Name = 'Sheet2'; },
    app => { app.Selection.Rows.Count = 3; },
    app => { app.ActiveWorkbook.FullName = '/test/another.xlsx'; }
  ]) {
    const h = createTestHarness();
    h.context.window.WpsAiAssistantHelpers = helpers;
    h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
    const app = createMockGridApp();
    assert.equal(h.api.inspectTargetRange(app).valid, true);
    change(app);
    await assert.rejects(h.api.writeToSheet(app), /目标.*变化|工作簿.*不一致/);
    assert.equal(app.getCellValue(2, 1), null);
    assert.equal(app.getCellValue(10, 1), null);
  }
});

test('ledger review requires inspecting a target before writing', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  await assert.rejects(h.api.writeToSheet(app), /检测.*目标/);
  assert.equal(app.getCellValue(2, 1), null);
});

test('ledger review rechecks blank cells after target confirmation', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  assert.equal(h.api.inspectTargetRange(app).valid, true);
  app.ActiveSheet.Cells.Item(3, 1).Value2 = '已有数据';
  await assert.rejects(h.api.writeToSheet(app), /已有数据/);
  assert.equal(app.getCellValue(2, 1), null);
  assert.equal(app.getCellValue(3, 1), '已有数据');
});

test('ledger review restores a cell whose setter changes its value before throwing', () => {
  const app = createMockGridApp();
  const cell = app.ActiveSheet.Cells.Item(3, 1);
  const original = Object.getOwnPropertyDescriptor(cell, 'Value2');
  Object.defineProperty(cell, 'Value2', {
    get: original.get,
    set(value) {
      original.set.call(cell, value);
      if (value !== '') throw new Error('host changed value before failure');
    }
  });
  assert.throws(() => helpers.writeExcelMaterialLedger(app, {
    headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }]
  }), err => err.code === 'COMPENSATION_SUCCEEDED');
  assert.equal(app.getCellValue(2, 1), '');
  assert.equal(app.getCellValue(3, 1), '');
});

test('ledger review reports the failed write cell when it cannot restore the changed value', () => {
  const app = createMockGridApp();
  const cell = app.ActiveSheet.Cells.Item(3, 1);
  const original = Object.getOwnPropertyDescriptor(cell, 'Value2');
  Object.defineProperty(cell, 'Value2', {
    get: original.get,
    set(value) {
      if (value !== '') original.set.call(cell, value);
      throw new Error('host cannot restore cell');
    }
  });
  assert.throws(() => helpers.writeExcelMaterialLedger(app, {
    headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }]
  }), err => {
    assert.equal(err.code, 'COMPENSATION_FAILED');
    assert.deepEqual(err.rollbackFailures, ['A3']);
    return true;
  });
  assert.equal(app.getCellValue(2, 1), '');
  assert.equal(app.getCellValue(3, 1), '任务1');
});

for (const mode of ['ignored', 'converted', 'formula', 'unreadable']) {
  test(`ledger review rejects ${mode} host writes and restores the target`, () => {
    const app = createMockGridApp();
    const cell = app.ActiveSheet.Cells.Item(3, 1);
    const original = Object.getOwnPropertyDescriptor(cell, 'Value2');
    let unreadable = false;
    Object.defineProperty(cell, 'Value2', {
      get() {
        if (unreadable) throw new Error('host read failed');
        return original.get.call(cell);
      },
      set(value) {
        unreadable = mode === 'unreadable' && value !== '';
        cell.HasFormula = mode === 'formula' && value !== '';
        if (mode !== 'ignored') original.set.call(cell, mode === 'converted' && value !== '' ? 123 : value);
      }
    });
    assert.throws(() => helpers.writeExcelMaterialLedger(app, {
      headers: ['编号'], rows: [{ values: { '编号': '00123' } }]
    }), err => {
      assert.equal(err.code, 'COMPENSATION_SUCCEEDED');
      assert.match(err.cause.message, /核对.*A3/);
      return true;
    });
    assert.equal(app.getCellValue(2, 1), '');
    assert.ok(app.getCellValue(3, 1) === '' || app.getCellValue(3, 1) === null);
    assert.equal(cell.HasFormula, false);
  });
}

test('ledger review accepts a host removing the text escape quote without creating a formula', () => {
  const app = createMockGridApp();
  const cell = app.ActiveSheet.Cells.Item(3, 1);
  const original = Object.getOwnPropertyDescriptor(cell, 'Value2');
  Object.defineProperty(cell, 'Value2', {
    get: original.get,
    set(value) {
      const stored = value.startsWith("'") ? value.slice(1) : value;
      original.set.call(cell, stored);
      cell.Formula = stored;
    }
  });
  const report = helpers.writeExcelMaterialLedger(app, {
    headers: ['工作事项'], rows: [{ values: { '工作事项': '=SUM(A1:A10)' } }]
  });
  assert.equal(report.success, true);
  assert.equal(app.getCellValue(3, 1), '=SUM(A1:A10)');
  assert.equal(cell.HasFormula, false);
});

test('ledger review cannot reopen a completed result by inspecting another target or toggling headers', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  h.api.inspectTargetRange(app);
  await h.api.writeToSheet(app);
  app.Selection.Row = 10;
  h.api.setIncludeHeaders(false);
  h.api.inspectTargetRange(app);
  assert.equal(h.api.getState().writeStatus, 'success');
  const report = await h.api.writeToSheet(app);
  assert.equal(report.targetAddress, 'A2:A3');
  assert.equal(app.getCellValue(10, 1), null);
});

test('ledger review preserves completed write state after reopening the pane', async () => {
  const storage = new Map();
  const h = createTestHarness(storage);
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  h.api.inspectTargetRange(app);
  await h.api.writeToSheet(app);
  const restored = createTestHarness(storage);
  restored.context.window.WpsAiAssistantHelpers = helpers;
  app.Selection.Row = 10;
  restored.api.inspectTargetRange(app);
  assert.equal(restored.api.getState().writeStatus, 'success');
  const report = await restored.api.writeToSheet(app);
  assert.equal(report.targetAddress, 'A2:A3');
  assert.equal(app.getCellValue(10, 1), null);
});

test('ledger review opens writing again for a newly generated result with a newly inspected target', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  h.api.inspectTargetRange(app);
  await h.api.writeToSheet(app);
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务2' } }] });
  assert.equal(h.api.getState().targetRangeInfo, null);
  assert.equal(h.api.getState().writeReport, null);
  app.Selection.Row = 10;
  await assert.rejects(h.api.writeToSheet(app), /检测.*目标/);
  assert.equal(h.api.inspectTargetRange(app).valid, true);
  await h.api.writeToSheet(app);
  assert.equal(app.getCellValue(11, 1), '任务2');
  assert.equal(app.getCellValue(3, 1), '任务1');
});

test('ledger review blocks writing when the pending write state cannot be saved', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  h.api.inspectTargetRange(app);
  h.storage.set = () => { throw new Error('QuotaExceededError'); };
  await assert.rejects(h.api.writeToSheet(app), /保存.*未.*写入/);
  assert.equal(app.getCellValue(2, 1), null);
});

test('ledger review pauses restored writing when the completion report could not be saved', async () => {
  const storage = new Map();
  const h = createTestHarness(storage);
  h.context.window.WpsAiAssistantHelpers = helpers;
  h.api.setResult({ headers: ['工作事项'], rows: [{ values: { '工作事项': '任务1' } }] });
  const app = createMockGridApp();
  h.api.inspectTargetRange(app);
  const save = storage.set.bind(storage);
  storage.set = (key, value) => {
    if (JSON.parse(value).writeReport?.success) throw new Error('QuotaExceededError');
    return save(key, value);
  };
  const report = await h.api.writeToSheet(app);
  assert.equal(report.success, true);
  assert.match(report.persistenceWarning, /完成状态.*保存/);
  const restored = createTestHarness(storage);
  restored.context.window.WpsAiAssistantHelpers = helpers;
  app.Selection.Row = 10;
  assert.equal(restored.api.inspectTargetRange(app).valid, false);
  await assert.rejects(restored.api.writeToSheet(app), /上次.*核对/);
  assert.equal(app.getCellValue(10, 1), null);
  await restored.api.restore();
  const reopened = createTestHarness(storage);
  reopened.context.window.WpsAiAssistantHelpers = helpers;
  assert.equal(reopened.api.inspectTargetRange(app).valid, false);
  await assert.rejects(reopened.api.writeToSheet(app), /上次.*核对/);
  assert.equal(app.getCellValue(10, 1), null);
});

test('ledger controller writeToSheet rejects when result is not completed', async () => {
  const h = createTestHarness();
  h.context.window.WpsAiAssistantHelpers = helpers;
  // State is idle by default without completed result
  const app = createMockGridApp();
  await assert.rejects(async () => {
    await h.api.writeToSheet(app);
  }, /没有可写入的已完成台账/);
});

test('taskpane HTML contains ledger write section and target controls', () => {
  const html = fs.readFileSync(path.join(root, 'taskpane.html'), 'utf8');
  assert.ok(html.includes('id="ledger-write-section"'), 'taskpane.html should contain #ledger-write-section');
  assert.ok(html.includes('id="ledger-target-summary"'), 'taskpane.html should contain #ledger-target-summary');
  assert.ok(html.includes('id="ledger-target-validation"'), 'taskpane.html should contain #ledger-target-validation');
  assert.ok(html.includes('id="btn-refresh-ledger-target"'), 'taskpane.html should contain #btn-refresh-ledger-target');
  assert.ok(html.includes('id="ledger-include-headers-toggle"'), 'taskpane.html should contain #ledger-include-headers-toggle');
  assert.ok(html.includes('id="btn-write-ledger"'), 'taskpane.html should contain #btn-write-ledger');
  assert.ok(html.includes('id="ledger-write-status"'), 'taskpane.html should contain #ledger-write-status');
});

test('renderMaterialLedgerView renders write section and target controls on completed result', () => {
  const pane = ledgerPaneHarness();
  pane.render({
    headers: ['工作事项', '责任部门'],
    result: {
      headers: ['工作事项', '责任部门'],
      rows: [{ values: { '工作事项': '任务1' }, missingFields: [] }]
    },
    targetRangeInfo: {
      sheetName: 'Sheet1',
      targetAddress: 'A2:B3',
      rowCount: 2,
      colCount: 2
    },
    includeHeaders: true,
    writeStatus: 'ready',
    writeError: ''
  });

  const writeSection = pane.byId('ledger-write-section');
  assert.strictEqual(writeSection.hidden, false);
  const summary = pane.byId('ledger-target-summary');
  assert.ok(summary.textContent.includes('A2:B3'));
  const btnWrite = pane.byId('btn-write-ledger');
  assert.strictEqual(btnWrite.disabled, false);
  const validation = pane.byId('ledger-target-validation');
  assert.ok(validation.textContent.includes('可安全写入'));
});

test('renderMaterialLedgerView hides write section when result is not present', () => {
  const pane = ledgerPaneHarness();
  pane.render({
    headers: ['工作事项'],
    result: null
  });
  const writeSection = pane.byId('ledger-write-section');
  assert.strictEqual(writeSection.hidden, true);
});

test('renderMaterialLedgerView disables write button when basis warning is active', () => {
  const pane = ledgerPaneHarness();
  pane.render({
    headers: ['工作事项'],
    result: {
      headers: ['工作事项'],
      basisMaterials: [{ materialId: 'm1', updatedAt: 'v1' }],
      rows: [{ values: { '工作事项': '任务1' }, missingFields: [] }]
    },
    catalogSummary: {
      documents: [{ materialId: 'm1', updatedAt: 'v2' }]
    },
    targetRangeInfo: {
      sheetName: 'Sheet1',
      targetAddress: 'A2:A3',
      rowCount: 2,
      colCount: 1
    },
    writeStatus: 'ready'
  });

  const basisWarning = pane.byId('ledger-basis-warning');
  assert.strictEqual(basisWarning.hidden, false);
  const btnWrite = pane.byId('btn-write-ledger');
  assert.strictEqual(btnWrite.disabled, true);
});

test('renderMaterialLedgerView shows error state when writeStatus is error', () => {
  const pane = ledgerPaneHarness();
  pane.render({
    headers: ['工作事项'],
    result: {
      headers: ['工作事项'],
      rows: [{ values: { '工作事项': '任务1' }, missingFields: [] }]
    },
    writeStatus: 'error',
    writeError: '目标区域包含已有数据 (A2)'
  });

  const validation = pane.byId('ledger-target-validation');
  assert.ok(validation.textContent.includes('包含已有数据'));
  const btnWrite = pane.byId('btn-write-ledger');
  assert.strictEqual(btnWrite.disabled, true);
});

test('real ledger pane writes ledger to worksheet cells upon confirmation and prevents write on cancel', t => {
  const { execFileSync } = require('node:child_process');
  const os = require('node:os');
  try { execFileSync('agent-browser', ['--version'], { stdio: 'ignore' }); }
  catch (_) { t.skip('agent-browser unavailable'); return; }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'excel-ledger-write-'));
  const run = (...args) => execFileSync('agent-browser', ['--session', 'excel-ledger-write', ...args], {
    encoding: 'utf8', env: { ...process.env, AGENT_BROWSER_SOCKET_DIR: temp }
  });
  const mock = `
window.paneErrors=[];window.addEventListener('error',e=>paneErrors.push(e.message));
window.confirmResult = false;
window.confirmCalls = 0;
window.confirmMessages = [];
window.confirm = function(msg) { window.confirmCalls++; window.confirmMessages.push(msg); return window.confirmResult; };
window.requests=[];window.cellWrites=0;
var cellStore = {};
function getCell(r, c) {
  var k = r + ',' + c;
  if (!cellStore[k]) {
    var val = '';
    cellStore[k] = {
      Row: r, Column: c,
      get Value2() { return val; },
      set Value2(v) { window.cellWrites++; val = v; },
      get Value() { return val; },
      set Value(v) { val = v; },
      HasFormula: false, Formula: '', MergeCells: false,
      EntireRow: { Hidden: false }, EntireColumn: { Hidden: false }, Locked: false
    };
  }
  return cellStore[k];
}
var sheet = {
  Name: 'Sheet1',
  ProtectContents: false,
  Cells: { Item: getCell },
  Range: function() { return { Item: getCell }; }
};
window.Application = {
  Selection: { Row: 2, Column: 1, Rows: { Count: 1 }, Columns: { Count: 1 }, Cells: { Item: getCell } },
  ActiveSheet: sheet,
  ActiveWorkbook: {
    Name: '台账测试.xlsx',
    FullName: '/test/台账测试.xlsx',
    ActiveSheet: sheet,
    Worksheets: { Item: () => sheet }
  }
};
window.catalog={totalDocuments:1,totalCharacters:50,documents:[{materialId:'m1',fileName:'台账依据.docx',updatedAt:'v1'}]};
window.fetch=async function(url,options){
  var p=new URL(url).pathname;
  if(p==='/health') return {ok:true,status:200,json:async()=>({success:true,data:{status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true}})};
  if(p==='/materials/reusable-sources') return {ok:true,status:200,json:async()=>({success:true,data:{sources:[]}})};
  if(p==='/excel/materials/catalog') return {ok:true,status:200,json:async()=>({success:true,data:catalog})};
  if(p==='/excel/material-ledger/conflicts') return {ok:true,status:200,json:async()=>({success:true,data:{conflicts:[]}})};
  if(p==='/excel/material-ledger/jobs') return {ok:true,status:200,json:async()=>({
    success:true,data:{jobId:'job-write-1',status:'completed',result:{
      headers:['工作事项','责任部门'],basisMaterials:[{materialId:'m1',updatedAt:'v1'}],
      rows:[{values:{'工作事项':'设备采购','责任部门':'采办部'},missingFields:[]}]
    }}
  })};
  return {ok:true,status:200,json:async()=>({success:true,data:{}})};
};`;
  let html = fs.readFileSync(path.join(root, 'taskpane.html'), 'utf8');
  html = html.replace('</head>', '<script>' + mock + '</script></head>');
  html = html.replace(/<script src="\.\/([^"?]+)[^"]*"><\/script>/g,
    (_, name) => '<script>' + fs.readFileSync(path.join(root, name), 'utf8') + '</script>');
  html = html.replace(/<link rel="stylesheet"[^>]+>/, '<style>' + fs.readFileSync(path.join(root, 'taskpane.css'), 'utf8') + '</style>');
  const page = path.join(temp, 'pane.html');
  fs.writeFileSync(page, html);
  try {
    run('open', require('node:url').pathToFileURL(page).href + '?mode=excelLedger');
    run('set', 'viewport', '320', '900');
    run('wait', '--text', '台账依据.docx');
    run('scrollintoview', '#btn-run-primary');
    run('click', '#btn-run-primary');
    run('wait', '--text', '设备采购');
    run('wait', '--text', '写入工作表');
    run('scrollintoview', '#btn-write-ledger');
    run('click', '#btn-refresh-ledger-target');
    run('wait', '--text', '可安全写入');
    run('click', '#btn-write-ledger');
    assert.equal(run('eval', 'window.confirmCalls').trim(), '1');
    assert.equal(run('eval', 'window.cellWrites').trim(), '0');
    run('eval', 'window.confirmResult = true');
    run('eval', "Application.Selection.Row = 10; Application.ActiveSheet.Name = 'Sheet2'");
    run('click', '#btn-write-ledger');
    run('wait', '--text', '目标工作簿、工作表或选区已变化');
    assert.equal(run('eval', 'window.cellWrites').trim(), '0');
    assert.equal(run('eval', "window.confirmMessages[1].includes('Sheet1') && window.confirmMessages[1].includes('A2:B3')").trim(), 'true');
    run('click', '#btn-refresh-ledger-target');
    run('wait', '--text', '可安全写入');
    run('click', '#btn-write-ledger');
    run('wait', '--text', '成功写入');
    assert.equal(run('eval', 'window.confirmCalls').trim(), '3');
    assert.equal(run('eval', 'window.cellWrites').trim(), '4');
    assert.equal(run('eval', "getCell(2, 1).Value2 === '' && getCell(10, 1).Value2 === '工作事项' && getCell(11, 1).Value2 === '设备采购'").trim(), 'true');
    run('eval', 'Application.Selection.Row = 20');
    run('click', '#btn-refresh-ledger-target');
    assert.equal(run('eval', "document.getElementById('btn-write-ledger').disabled").trim(), 'true');
    assert.equal(run('eval', 'window.cellWrites').trim(), '4');
    assert.equal(run('eval', 'JSON.stringify(window.paneErrors)').trim(), '"[]"');
  } finally {
    try { run('close'); } catch (_) {}
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
