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
    schedule: (fn, ms) => setTimeout(fn, ms || 0),
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
