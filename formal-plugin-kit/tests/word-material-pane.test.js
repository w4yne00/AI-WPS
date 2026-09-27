const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/taskpane.js'), 'utf8');
function load(name, context) {
  if (name === 'applyMaterialComposerResult') {
    context.isMaterialComposerFullDocumentSelection = load('isMaterialComposerFullDocumentSelection', {});
  }
  if (name === 'applyMaterialComposerResult' || name === 'renderMaterialComposerView') {
    context.materialComposerTargetHasChanged = load('materialComposerTargetHasChanged', {});
    if (!('materialComposerWriteAttempted' in context)) context.materialComposerWriteAttempted = false;
    if (!('materialComposerAppliedMessage' in context)) context.materialComposerAppliedMessage = '';
    if (!('lastMaterialComposerView' in context)) context.lastMaterialComposerView = null;
    if (!('materialComposerTargetSnapshot' in context)) context.materialComposerTargetSnapshot = null;
  }
  const start = source.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'missing function ' + name);
  const end = source.indexOf('\n  function ', start + 1);
  return vm.runInNewContext('(' + source.slice(start, end) + ')', context);
}

function materialMutationHarness() {
  const saved = new Map();
  const nodes = new Map();
  const h = { session: 'doc-a', copied: [], applied: [], views: [] };
  const context = {
    window: { confirm: () => true },
    byId: id => {
      if (!nodes.has(id)) nodes.set(id, { textContent: '', value: '', disabled: false });
      return nodes.get(id);
    },
    getMaterialComposerSessionId: () => h.session,
    materialImportRequestSequences: {},
    request: (...args) => h.request(...args),
    document: {
      body: { appendChild(input) { input.parentNode = { removeChild() {} }; } },
      createElement() {
        return { style: {}, addEventListener(name, callback) { h.chooseFile = callback; }, click() {} };
      }
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/material-composer.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/material-import.js'), 'utf8'), context);
  h.composer = context.window.createMaterialComposer({
    getSessionId: () => h.session,
    storage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    request: (...args) => h.request(...args),
    render: view => h.views.push(view),
    copyText: text => h.copied.push(text),
    applyText: text => { h.applied.push(text); return true; },
    schedule() {}
  });
  context.ensureMaterialComposer = () => h.composer;
  context.window.readMaterialFile = async () => 'base64';
  h.context = context;
  h.saved = saved;
  h.node = context.byId;
  h.last = () => h.views[h.views.length - 1];
  h.flush = () => new Promise(resolve => setImmediate(resolve));
  return h;
}

test('the real delete response invalidates a generated draft while preserving copy', async () => {
  const h = materialMutationHarness();
  h.composer.setMaterial({ materialId: 'm1', catalogSummary: {
    totalDocuments: 1, totalCharacters: 2, documents: [{ materialId: 'm1', updatedAt: '2026-09-27T01:00:00' }], toc: []
  } });
  h.request = async () => ({ success: true, data: {
    jobId: 'job-a', status: 'succeeded', documentSessionId: 'doc-a', result: {
      taskType: 'word.material_composer', documentSessionId: 'doc-a', plainText: '正文',
      paragraphs: [{ text: '正文', sources: [], missingItems: [] }], missingItems: [],
      basisMaterials: [{ materialId: 'm1', updatedAt: '2026-09-27T01:00:00' }]
    }
  } });
  await h.composer.start({ sectionTitle: '第一章', instruction: '按资料编写' });
  assert.equal(h.last().status, 'succeeded');
  h.request = async () => ({ success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } });
  load('handleMaterialDelete', h.context)('m1');
  await h.flush();
  assert.equal(h.last().basisStatus, 'removed');
  await assert.rejects(h.composer.apply({ documentSessionId: 'doc-a', sectionTitle: '第一章' }), /已被移除/);
  assert.equal(h.applied.length, 0);
  await h.composer.copy();
  assert.deepEqual(h.copied, ['正文']);
});

test('late update and delete responses cannot replace another document catalog or notice', async () => {
  for (const operation of ['update', 'delete']) {
    for (const outcome of ['success', 'failure']) {
      const h = materialMutationHarness();
      let resolveRequest, rejectRequest;
      h.request = () => new Promise((resolve, reject) => { resolveRequest = resolve; rejectRequest = reject; });
      load(operation === 'update' ? 'handleMaterialUpdate' : 'handleMaterialDelete', h.context)('m1');
      if (operation === 'update') h.chooseFile({ target: { files: [{ name: '更新.docx' }] } });
      await h.flush();
      h.session = 'doc-b';
      h.composer.setMaterial({ materialId: 'b1', catalogSummary: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'b1' }], toc: [] } });
      h.node('material-composer-status').textContent = 'B 文档提示';
      const catalog = { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] };
      if (outcome === 'success') resolveRequest({ success: true, data: operation === 'update' ? { fileName: '更新.docx', catalogSummary: catalog } : catalog });
      else rejectRequest(Error('A 旧请求失败'));
      await h.flush();
      assert.deepEqual(Array.from(h.last().materialIds), ['b1'], operation + outcome);
      assert.equal(h.node('material-composer-status').textContent, 'B 文档提示', operation + outcome);
    }
  }
});

test('a later deletion wins over an earlier update response in the same document', async () => {
  const h = materialMutationHarness();
  const pending = {};
  h.request = (url, body, options) => new Promise(resolve => { pending[options.method] = resolve; });
  load('handleMaterialUpdate', h.context)('m1');
  h.chooseFile({ target: { files: [{ name: '更新.docx' }] } });
  await h.flush();
  load('handleMaterialDelete', h.context)('m1');
  pending.DELETE({ success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } });
  await h.flush();
  const deletionNotice = h.node('material-composer-status').textContent;
  pending.PUT({ success: true, data: { fileName: '更新.docx', catalogSummary: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } } });
  await h.flush();
  assert.equal(h.last().catalogSummary.totalDocuments, 0);
  assert.equal(h.node('material-composer-status').textContent, deletionNotice);
});

test('a newer import wins over an earlier deletion response and old import failures stay in their document', async () => {
  const h = materialMutationHarness();
  let resolveDelete, rejectImport;
  h.request = (url, body, options = {}) => {
    if (options.method === 'DELETE') return new Promise(resolve => { resolveDelete = resolve; });
    if (h.session === 'doc-b') return new Promise((resolve, reject) => { rejectImport = reject; });
    return Promise.resolve({ success: true, data: { materialId: 'm2', documentSessionId: 'doc-a', catalogSummary: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm2' }], toc: [] } } });
  };
  h.context.window.renderMaterialReading = () => {};
  load('handleMaterialDelete', h.context)('m1');
  const importFile = load('handleMaterialImportFileChange', h.context);
  importFile({ target: { files: [{ name: '新资料.docx' }] } });
  await h.flush();
  resolveDelete({ success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } });
  await h.flush();
  assert.deepEqual(Array.from(h.last().materialIds), ['m2']);
  h.session = 'doc-b';
  importFile({ target: { files: [{ name: 'B资料.docx' }] } });
  await h.flush();
  h.session = 'doc-a';
  h.node('material-import-status').textContent = 'A 文档提示';
  rejectImport(Error('B 导入失败'));
  await h.flush();
  assert.equal(h.node('material-import-status').textContent, 'A 文档提示');
});

for (const catalogOutcome of ['success', 'failure']) {
  test('a delayed committed update followed by a failed update stays unwritable until catalog ' + catalogOutcome, async () => {
    const h = materialMutationHarness();
    const original = { totalDocuments: 1, totalCharacters: 2, documents: [{ materialId: 'm1', updatedAt: '2026-09-27T01:00:00' }], toc: [] };
    const updated = { totalDocuments: 1, totalCharacters: 2, documents: [{ materialId: 'm1', updatedAt: '2026-09-27T02:00:00' }], toc: [] };
    h.composer.setMaterial({ materialId: 'm1', catalogSummary: original });
    h.request = async () => ({ success: true, data: {
      jobId: 'job-a', status: 'succeeded', documentSessionId: 'doc-a', result: {
        taskType: 'word.material_composer', documentSessionId: 'doc-a', plainText: '正文',
        paragraphs: [{ text: '正文', sources: [], missingItems: [] }], missingItems: [],
        basisMaterials: [{ materialId: 'm1', updatedAt: '2026-09-27T01:00:00' }]
      }
    } });
    await h.composer.start({ sectionTitle: '第一章', instruction: '按资料编写' });
    let resolveFirst, resolveCatalog, rejectCatalog;
    let catalogGets = 0;
    h.request = (url, body) => {
      if (url.includes('/catalog')) {
        catalogGets += 1;
        return new Promise((resolve, reject) => { resolveCatalog = resolve; rejectCatalog = reject; });
      }
      if (body.fileName === '更新1.docx') return new Promise(resolve => { resolveFirst = resolve; });
      return Promise.reject(Object.assign(Error('更新2不是有效DOCX'), { httpStatus: 422 }));
    };
    const update = load('handleMaterialUpdate', h.context);
    update('m1');
    h.chooseFile({ target: { files: [{ name: '更新1.docx' }] } });
    await h.flush();
    assert.equal(h.last().basisStatus, 'checking');
    await assert.rejects(h.composer.apply({ documentSessionId: 'doc-a', sectionTitle: '第一章' }));
    update('m1');
    h.chooseFile({ target: { files: [{ name: '更新2.docx' }] } });
    await h.flush();
    assert.equal(catalogGets, 0, 'the final catalog must wait for every submitted mutation');
    resolveFirst({ success: true, data: { fileName: '更新1.docx', catalogSummary: updated } });
    await h.flush();
    assert.equal(catalogGets, 1);
    assert.equal(h.last().basisStatus, 'checking');
    await assert.rejects(h.composer.apply({ documentSessionId: 'doc-a', sectionTitle: '第一章' }));
    if (catalogOutcome === 'success') resolveCatalog({ success: true, data: updated });
    else rejectCatalog(Error('目录查询失败'));
    await h.flush();
    assert.equal(h.last().basisStatus, catalogOutcome === 'success' ? 'updated' : 'checking');
    if (catalogOutcome === 'success') assert.match(h.last().error, /更新2不是有效DOCX/);
    await assert.rejects(h.composer.apply({ documentSessionId: 'doc-a', sectionTitle: '第一章' }));
    assert.equal(h.applied.length, 0);
    await h.composer.copy();
    assert.deepEqual(h.copied, ['正文']);
    assert.match(h.node('material-composer-status').textContent, /更新2不是有效DOCX/);
  });
}

test('chapter generation sends only explicit chapter and requirements, never document body', async () => {
  const nodes = {
    'material-section-title': {value: '实施安排'},
    'material-instruction': {value: '按阶段说明'},
    'material-composer-status': {textContent: ''}
  };
  let input;
  const doc = {Selection: {Range: {Start: 0, End: 0, Text: ''}}};
  Object.defineProperty(doc, 'Content', {get: () => { throw new Error('must not read current body'); }});
  const run = load('startMaterialComposer', {
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({start(value) { input = value; return Promise.resolve(); }}),
    validateActiveDirectTaskSelection: () => ({valid:true}),
    getActiveDocument: () => doc,
    getWritableSelection: selected => selected.Selection,
    getMaterialComposerSessionId: () => 'doc-a',
    lastMaterialComposerView: null
  });
  await run();
  assert.deepEqual(JSON.parse(JSON.stringify(input)), {sectionTitle:'实施安排', instruction:'按阶段说明'});
});

test('selecting a chapter reads only explicit selection and never modifies the document', () => {
  const doc = {};
  const nodes = {'material-section-title':{value:''}, 'material-composer-status':{textContent:''}};
  const select = load('useMaterialComposerSelection', {
    byId: id => nodes[id],
    getActiveDocument: () => doc,
    getSelectionText: selected => { assert.equal(selected,doc); return '第二章 实施安排'; },
    handleMaterialComposerInputChange() {}
  });
  select();
  assert.equal(nodes['material-section-title'].value, '第二章 实施安排');
});

test('a completed result for another document cannot change the visible pane', () => {
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-b',
    byId: () => { throw new Error('other document touched UI'); }
  });
  view({documentSessionId:'doc-a',status:'completed',result:{plainText:'A'}});
});

test('an uncertain restored request repopulates its locked chapter and instruction', () => {
  const nodes = {
    'material-composer-status': {textContent:''},
    'material-import-file': {disabled:false},
    'material-section-title': {value:'',disabled:false},
    'material-instruction': {value:'',disabled:false},
    'btn-material-selection': {disabled:false},
    'btn-material-generate': {disabled:false},
    'btn-material-cancel': {disabled:false},
    'btn-material-copy': {disabled:false},
    'material-composer-result': {}
  };
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-a',
    byId: id => nodes[id],
    window: {renderMaterialComposer() {}}
  });
  view({documentSessionId:'doc-a',clientJobId:'composer-1',jobId:'',status:'idle',busy:false,result:null,input:{sectionTitle:'原章节',instruction:'原要求'}});
  assert.equal(nodes['material-section-title'].value,'原章节');
  assert.equal(nodes['material-instruction'].value,'原要求');
});

test('the latest material selection wins when reads finish out of order in one document', async () => {
  const nodes = {
    'material-import-status': {textContent:''},
    'material-import-result': {}
  };
  const pending = {};
  const accepted = [];
  const context = {
    byId: id => nodes[id],
    getMaterialComposerSessionId: () => 'doc-a',
    materialImportRequestSequences: {},
    ensureMaterialComposer: () => ({
      setMaterial(reading) { accepted.push(reading.materialId); },
      beginMaterialMutation() {}, endMaterialMutation() {}
    }),
    request() {},
    window: {
      readMaterialFile(file) { return new Promise(resolve => { pending[file.name] = resolve; }); },
      submitMaterialImport(input) { return Promise.resolve({materialId:input.fileName,documentSessionId:input.documentSessionId}); },
      renderMaterialReading() {}
    }
  };
  const importFile = load('handleMaterialImportFileChange', context);
  importFile({target:{files:[{name:'A.docx',type:'',size:1}]}});
  importFile({target:{files:[{name:'B.docx',type:'',size:1}]}});
  pending['B.docx']('B');
  await new Promise(resolve => setImmediate(resolve));
  pending['A.docx']('A');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(accepted,['B.docx']);
});

test('real pane generates and restores a read-only chapter with source sidebar in a narrow viewport', t => {
  const {execFileSync} = require('node:child_process');
  const os = require('node:os');
  try { execFileSync('agent-browser', ['--version'], {stdio:'ignore'}); }
  catch (_) { t.skip('agent-browser unavailable'); return; }
  const root = path.join(__dirname, '../wps-ai-assistant_1.0.0');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'material-pane-'));
  const run = (...args) => execFileSync('agent-browser', ['--session','material-pane', ...args], {encoding:'utf8', env:{...process.env, AGENT_BROWSER_SOCKET_DIR:temp}});
  const mock = `
window.paneErrors=[];window.addEventListener('error',e=>paneErrors.push(e.message));
window.confirm=function(){return true;};
window.requests=[];
window.mockBody='前缀|实施安排|后缀';
var mockStart=mockBody.indexOf('实施安排'),mockEnd=mockStart+'实施安排'.length;
var mockRange={get Start(){return mockStart;},get End(){return mockEnd;},get Text(){return mockBody.slice(mockStart,mockEnd);},set Text(value){mockBody=mockBody.slice(0,mockStart)+value+mockBody.slice(mockEnd);mockEnd=mockStart+value.length;}};
var mockSelection={Range:mockRange,get Text(){return mockRange.Text;}};
var mockDocument={Name:'章节.docx',FullName:'/test/章节.docx',Selection:mockSelection,get Content(){return {Start:0,End:mockBody.length,Text:mockBody};}};
window.Application={ActiveDocument:mockDocument};
window.fetch=async function(url,options){
  var p=new URL(url).pathname, body=options&&options.body?JSON.parse(options.body):null;
  requests.push({path:p,body:body});
  var data={};
  if(p==='/health')data={status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true};
  if(p==='/word/materials'){
    var catalog={totalDocuments:1,totalCharacters:24,documents:[{materialId:'mat-browser',fileName:'资料.docx'}],toc:[{materialId:'mat-browser',headingLevel:1,sectionTitle:'实施安排'}]};
    localStorage.setItem('test-material-catalog',JSON.stringify(catalog));
    data={materialId:'mat-browser',documentSessionId:body.documentSessionId,blocks:[],fragments:[],fileName:'资料.docx',catalogSummary:catalog};
  }
  if(p==='/word/materials/catalog')data=JSON.parse(localStorage.getItem('test-material-catalog')||'{"totalDocuments":0,"totalCharacters":0,"documents":[],"toc":[]}');
  if(p==='/word/material-composer/conflicts')data={conflicts:[{conflictId:'conflict-1',topic:'项目预算',difference:'150万元与50万元存在差异',options:[{optionId:'opt-1',sourceId:'mat-browser',sourceName:'资料.docx',sourceType:'material',value:'150万元',text:'预算为150万元'},{optionId:'opt-2',sourceId:'user',sourceName:'用户补充事实',sourceType:'user',value:'50万元',text:'预算调整为50万元'}]}]};
  if(p==='/word/material-composer/jobs'){
    localStorage.setItem('test-job',JSON.stringify(body));
    if(!window.lostJobResponse){window.lostJobResponse=true;throw new Error('response lost');}
    data={jobId:body.clientJobId,status:'queued',documentSessionId:body.documentSessionId};
  }else if(p.indexOf('/word/material-composer/jobs/')===0){
    var saved=JSON.parse(localStorage.getItem('test-job'));
    data={jobId:saved.clientJobId,status:'completed',documentSessionId:saved.documentSessionId,result:{taskType:'word.material_composer',documentSessionId:saved.documentSessionId,plainText:'信息化处负责。〔待补充：完成时间〕',missingItems:['完成时间'],paragraphs:[{text:'信息化处负责。〔待补充：完成时间〕',missingItems:['完成时间'],sources:[{fileName:'资料.docx',section:'责任安排',quote:'信息化处负责。',fragmentId:'f1'}]}]}};
  }
  return {ok:true,status:200,json:async()=>({success:true,data:data})};
};`;
  let html = fs.readFileSync(path.join(root,'taskpane.html'),'utf8');
  html = html.replace('</head>', '<script>'+mock+'</script></head>');
  html = html.replace(/<script src="\.\/([^"?]+)[^"]*"><\/script>/g, (_,name)=>'<script>'+fs.readFileSync(path.join(root,name),'utf8')+'</script>');
  html = html.replace(/<link rel="stylesheet"[^>]+>/, '<style>'+fs.readFileSync(path.join(root,'taskpane.css'),'utf8')+'</style>');
  const page=path.join(temp,'pane.html'); fs.writeFileSync(page,html);
  try {
    run('open',require('node:url').pathToFileURL(page).href+'?mode=materialImport');
    run('set','viewport','320','900');
    const errors = run('eval','JSON.stringify(window.paneErrors)');
    assert.ok(errors.includes('[]'),errors);
    run('eval',`(async()=>{var input=document.getElementById('material-import-file');var dt=new DataTransfer();dt.items.add(new File(['docx'],'资料.docx'));input.files=dt.files;input.dispatchEvent(new Event('change'));})();`);
    run('wait','--text','资料目录');
    run('scrollintoview','.material-composer-toc summary');
    run('click','.material-composer-toc summary');
    run('scrollintoview','.material-composer-toc-chapter');
    run('click','.material-composer-toc-chapter');
    assert.equal(run('eval',`document.getElementById('material-section-title').value`).trim(), '"实施安排"');
    run('fill','#material-instruction','简要说明责任和工期');
    run('fill','#material-user-facts','预算调整为50万元');
    run('scrollintoview','#btn-material-check-conflicts');
    run('click','#btn-material-check-conflicts');
    run('wait','--text','150万元与50万元存在差异');
    run('scrollintoview','.material-composer-conflict-choice:last-child');
    run('click','.material-composer-conflict-choice:last-child');
    assert.equal(run('eval',`document.querySelectorAll('.material-composer-conflict-choice.active').length`).trim(),'1');
    run('scrollintoview','#btn-material-generate');
    run('click','#btn-material-generate');
    run('wait','--text','response lost');
    run('fill','#material-user-facts','预算调整为500万元');
    assert.equal(run('eval',`document.querySelectorAll('.material-composer-conflict-choice').length`).trim(),'0');
    run('scrollintoview','#btn-material-generate');
    run('click','#btn-material-generate');
    run('wait','--text','信息化处负责。');
    const posts=JSON.parse(JSON.parse(run('eval',`JSON.stringify(requests.filter(r=>r.path==='/word/material-composer/jobs').map(r=>r.body))`)));
    assert.equal(posts.length,2); assert.deepEqual(posts[1],posts[0]);
    assert.equal(posts[1].userFacts,'预算调整为50万元');
    assert.equal(posts[1].conflictResolutions[0].chosenCandidateId,'opt-2');
    assert.equal(posts[1].conflictResolutions[0].chosenSource,'用户补充事实');
    assert.equal(posts[1].conflictResolutions[0].topic,'项目预算');
    assert.ok(run('get','text','#material-composer-result').includes('资料.docx'));
    assert.equal(run('eval',`String(document.querySelectorAll('#material-composer-result .material-composer-sources').length)`).trim(),'"1"');
    assert.equal(run('eval',`document.documentElement.scrollWidth <= innerWidth && getComputedStyle(document.getElementById('word-result-section')).display === "none"`).trim(), 'true');
    assert.equal(run('eval',`document.getElementById('btn-material-apply').disabled`).trim(), 'false');
    assert.equal(run('get','text','#btn-material-apply').trim(), '替换所选内容');
    run('fill','#material-section-title','已修改的新目标');
    assert.equal(run('eval',`document.getElementById('btn-material-apply').disabled`).trim(), 'true');
    assert.ok(run('get','text','#material-composer-status').includes('目标章节或选区已变更，写入已暂停'));
    run('fill','#material-section-title','实施安排');
    assert.equal(run('eval',`document.getElementById('btn-material-apply').disabled`).trim(), 'false');
    run('click','#btn-material-apply');
    assert.ok(run('get','text','#material-composer-status').includes('章节草稿已替换至所选区域'));
    assert.equal(run('eval',`window.Application.ActiveDocument.Selection.Text`).trim(), '"信息化处负责。〔待补充：完成时间〕"');
    assert.equal(run('eval',`window.mockBody`).trim(), '"前缀|信息化处负责。〔待补充：完成时间〕|后缀"');
    assert.equal(run('eval',`document.getElementById('btn-material-apply').disabled`).trim(), 'true');
    run('reload');
    run('wait','--text','信息化处负责。');
    const after=run('eval',`JSON.stringify(requests.filter(r=>r.path==='/word/material-composer/jobs'))`);
    assert.ok(after.includes('[]'),after);
  } finally { try {run('close');} finally {fs.rmSync(temp,{recursive:true,force:true});} }
});

test('renderMaterialComposerView dynamically adapts btn-material-apply text and enables it only for succeeded result', () => {
  const nodes = {
    'material-composer-status': {textContent:''},
    'material-import-file': {disabled:false},
    'material-section-title': {value:'第一章',disabled:false},
    'material-instruction': {value:'要求',disabled:false},
    'btn-material-selection': {disabled:false},
    'btn-material-generate': {disabled:false},
    'btn-material-cancel': {disabled:false},
    'btn-material-copy': {disabled:false},
    'btn-material-apply': {textContent:'',disabled:true},
    'material-composer-result': {}
  };
  let selection = '已有选区内容';
  const range = {Start: 2, End: 8, Text: selection};
  const snapshot = {documentSessionId:'doc-a',sectionTitle:'第一章',start:2,end:8,selectedText:selection};
  const doc = {Selection: {Range: range}};
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-a',
    getActiveDocument: () => doc,
    getWritableSelection: selected => selected.Selection,
    getSelectionText: () => selection,
    materialComposerTargetSnapshot: snapshot,
    byId: id => nodes[id],
    window: {renderMaterialComposer() {}}
  });

  view({documentSessionId:'doc-a',status:'running',busy:true,result:null,input:{sectionTitle:'第一章'}});
  assert.equal(nodes['btn-material-apply'].disabled, true);

  view({documentSessionId:'doc-a',status:'succeeded',busy:false,result:{plainText:'正文'},input:{sectionTitle:'第一章'}});
  assert.equal(nodes['btn-material-apply'].disabled, false);
  assert.equal(nodes['btn-material-apply'].textContent, '替换所选内容');

  selection = '';
  range.Text = '';
  range.End = range.Start;
  snapshot.selectedText = '';
  snapshot.end = snapshot.start;
  view({documentSessionId:'doc-a',status:'succeeded',busy:false,result:{plainText:'正文'},input:{sectionTitle:'第一章'}});
  assert.equal(nodes['btn-material-apply'].disabled, false);
  assert.equal(nodes['btn-material-apply'].textContent, '在光标处插入');
});

test('renderMaterialComposerView pauses replacement when section title in textarea differs from generation input', () => {
  const nodes = {
    'material-composer-status': {textContent:''},
    'material-import-file': {disabled:false},
    'material-section-title': {value:'被修改的章节',disabled:false},
    'material-instruction': {value:'要求',disabled:false},
    'btn-material-selection': {disabled:false},
    'btn-material-generate': {disabled:false},
    'btn-material-cancel': {disabled:false},
    'btn-material-copy': {disabled:false},
    'btn-material-apply': {textContent:'',disabled:false},
    'material-composer-result': {}
  };
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-a',
    getActiveDocument: () => ({}),
    getWritableSelection: () => null,
    getSelectionText: () => '选区内容',
    byId: id => nodes[id],
    window: {renderMaterialComposer() {}}
  });

  view({documentSessionId:'doc-a',status:'succeeded',busy:false,result:{plainText:'正文'},input:{sectionTitle:'原章节'}});
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.ok(nodes['material-composer-status'].textContent.includes('目标章节或选区已变更'));
});

test('clearing a completed draft title pauses write instead of restoring the old title', () => {
  const nodes = {
    'material-composer-status': {textContent:''}, 'material-import-file': {disabled:false},
    'material-section-title': {value:'',disabled:false}, 'material-instruction': {value:'要求',disabled:false},
    'btn-material-selection': {disabled:false}, 'btn-material-generate': {disabled:false},
    'btn-material-cancel': {disabled:false}, 'btn-material-copy': {disabled:false},
    'btn-material-apply': {textContent:'',disabled:false}, 'material-composer-result': {}
  };
  const range = {Start:2, End:5, Text:'旧章节'};
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-a',
    getActiveDocument: () => ({Selection:{Range:range}}),
    getWritableSelection: doc => doc.Selection,
    getSelectionText: () => '旧章节',
    materialComposerTargetSnapshot: {documentSessionId:'doc-a',sectionTitle:'第一章',start:2,end:5,selectedText:'旧章节'},
    lastMaterialComposerView: {documentSessionId:'doc-a',status:'succeeded'},
    byId: id => nodes[id], window: {renderMaterialComposer() {}}
  });

  view({documentSessionId:'doc-a',jobId:'job-a',status:'succeeded',result:{plainText:'正文'},input:{sectionTitle:'第一章'}});
  assert.equal(nodes['material-section-title'].value, '');
  assert.equal(nodes['btn-material-apply'].disabled, true);
});

test('editing the selected chapter during generation invalidates its write target', () => {
  const changed = load('materialComposerTargetHasChanged', {});
  const snapshot = {documentSessionId: 'doc-a', sectionTitle: '第一章', start: 2, end: 5, selectedText: '旧章节'};
  const selection = {Range: {Start: 2, End: 5, Text: '新章节'}};
  assert.equal(changed(snapshot, selection, '第一章', 'doc-a'), true);
  selection.Range.Text = '旧章节';
  assert.equal(changed(snapshot, selection, '第一章', 'doc-a'), false);
  selection.Range.Start = 8;
  assert.equal(changed(snapshot, selection, '第一章', 'doc-a'), true);
});

test('verified selection replacement preserves prefix and suffix in the shared document body', () => {
  let body = '前缀|旧章节|后缀';
  const start = body.indexOf('旧章节');
  const range = {Start: start, End: start + '旧章节'.length};
  Object.defineProperty(range, 'Text', {
    get: () => body.slice(range.Start, range.End),
    set: value => { body = body.slice(0, range.Start) + value + body.slice(range.End); range.End = range.Start + value.length; }
  });
  const doc = {Selection: {Range: range}};
  Object.defineProperty(doc, 'Content', {get: () => ({Start: 0, End: body.length, Text: body})});
  const write = load('writeMaterialComposerText', {});

  assert.equal(write(doc, doc.Selection, '新草稿'), true);
  assert.equal(body, '前缀|新草稿|后缀');
});

test('verified cursor insertion preserves text on both sides of the cursor', () => {
  let body = '左|右';
  const range = {Start: 2, End: 2};
  Object.defineProperty(range, 'Text', {
    get: () => body.slice(range.Start, range.End),
    set: value => { body = body.slice(0, range.Start) + value + body.slice(range.End); range.End = range.Start + value.length; }
  });
  const doc = {Selection: {Range: range}};
  Object.defineProperty(doc, 'Content', {get: () => ({Start: 0, End: body.length, Text: body})});

  assert.equal(load('writeMaterialComposerText', {})(doc, doc.Selection, '新草稿'), true);
  assert.equal(body, '左|新草稿右');
});

test('applyMaterialComposerResult inserts at cursor when selection is collapsed', async () => {
  const doc = {
    Selection: { Range: {Start: 2, End: 2, Text: ''} },
    Content: { Text: '整篇未授权内容' }
  };
  const nodes = {
    'material-section-title': { value: '第一章' },
    'material-composer-status': { textContent: '' },
    'btn-material-apply': {disabled: false}
  };
  let appliedArgs = null;
  const applyFn = load('applyMaterialComposerResult', {
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: d => d.Selection,
    getSelectionText: () => '',
    materialComposerTargetSnapshot: {documentSessionId:'doc-a',sectionTitle:'第一章',start:2,end:2,selectedText:''},
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({
      apply: async args => {
        appliedArgs = args;
        doc.Selection.Range.Text = '插入的光标正文';
        return { ok: true, mode: 'insert' };
      }
    })
  });

  await applyFn();
  assert.equal(doc.Selection.Range.Text, '插入的光标正文');
  assert.equal(appliedArgs.selectionText, '');
  assert.ok(nodes['material-composer-status'].textContent.includes('已插入至光标位置'));
});

test('a confirmed cursor write cannot be repeated by clicking the same draft again', async () => {
  const doc = {Selection: {Range: {Start: 2, End: 2, Text: ''}}};
  const nodes = {
    'material-section-title': {value: '第一章'},
    'material-composer-status': {textContent: ''},
    'btn-material-apply': {disabled: false}
  };
  let writes = 0;
  const apply = load('applyMaterialComposerResult', {
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: selected => selected.Selection,
    getSelectionText: () => '',
    materialComposerTargetSnapshot: {documentSessionId:'doc-a',sectionTitle:'第一章',start:2,end:2,selectedText:''},
    materialComposerWriteAttempted: false,
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({apply: async () => { writes += 1; return {ok:true,mode:'insert'}; }})
  });

  await apply();
  await apply();
  assert.equal(writes, 1);
  assert.equal(nodes['btn-material-apply'].disabled, true);
});

test('confirming a whole-document selection never writes the chapter draft', async () => {
  let body = '第一章\r原有正文\r';
  const range = {Start: 0, End: body.length};
  Object.defineProperty(range, 'Text', {
    get: () => body,
    set: value => { body = value; }
  });
  const doc = {Selection: {Range: range}};
  Object.defineProperty(doc, 'Content', {
    get: () => ({Start: 0, End: body.length, Text: body})
  });
  const context = {window: {}, Promise, Date, Math};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/material-composer.js'), 'utf8'), context);
  const composer = context.window.createMaterialComposer({
    storage: {getItem: () => null, setItem() {}},
    getSessionId: () => 'doc-a',
    request: async () => ({success: true, data: {jobId: 'job-a', status: 'succeeded', documentSessionId: 'doc-a', result: {
      taskType: 'word.material_composer', documentSessionId: 'doc-a', plainText: '新草稿', missingItems: [],
      paragraphs: [{text: '新草稿', missingItems: [], sources: []}]
    }}}),
    render() {}, copyText() {}, applyText: text => { range.Text = text; return true; }
  });
  composer.setMaterial({materialId: 'm1'});
  await composer.start({sectionTitle: '第一章', instruction: '编写'});
  const nodes = {'material-section-title': {value: '第一章'}, 'material-composer-status': {textContent: ''}, 'btn-material-apply': {disabled: false}};
  const apply = load('applyMaterialComposerResult', {
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: selected => selected.Selection,
    getSelectionText: selected => selected.Selection.Range.Text,
    materialComposerTargetSnapshot: {documentSessionId:'doc-a',sectionTitle:'第一章',start:0,end:body.length,selectedText:body},
    byId: id => nodes[id],
    ensureMaterialComposer: () => composer
  });

  await apply();
  assert.equal(body, '第一章\r原有正文\r');
  assert.match(nodes['material-composer-status'].textContent, /禁止全篇替换/);
});

test('whole-document text is rejected when the host omits the final paragraph mark from the selection range', () => {
  const full = load('isMaterialComposerFullDocumentSelection', {});
  const doc = {Content: {Start:0, End:4, Text:'甲\r乙\r'}};
  const selection = {Range: {Start:0, End:3, Text:'甲\r乙'}};
  assert.equal(full(doc, selection, '甲乙'), true);
});

test('a whole-document whitespace selection is still rejected', () => {
  const full = load('isMaterialComposerFullDocumentSelection', {});
  assert.equal(full({Content:{Start:0,End:1,Text:'\r'}}, {Range:{Start:0,End:1,Text:'\r'}}, ''), true);
});

test('a partial host write is reported as uncertain and keeps surrounding text visible', () => {
  let body = '前缀旧章节后缀';
  const range = {Start: 2, End: 5};
  Object.defineProperty(range, 'Text', {
    get: () => body.slice(range.Start, range.End),
    set: () => { body = '前缀新后缀'; throw new Error('host stopped halfway'); }
  });
  const doc = {Selection: {Range: range}};
  Object.defineProperty(doc, 'Content', {get: () => ({Start: 0, End: body.length, Text: body})});
  const write = load('writeMaterialComposerText', {});

  assert.throws(() => write(doc, doc.Selection, '新章节'), /部分写入|核实/);
  assert.equal(body, '前缀新后缀');
});

test('a host setter that silently makes no change is not reported as success', () => {
  const body = '前缀旧章节后缀';
  const range = {Start: 2, End: 5};
  Object.defineProperty(range, 'Text', {get: () => body.slice(2, 5), set: () => {}});
  const doc = {Selection: {Range: range}, Content: {Start: 0, End: body.length, Text: body}};

  assert.throws(() => load('writeMaterialComposerText', {})(doc, doc.Selection, '新章节'), /未写入/);
});

test('a selection whose range text disagrees with document offsets is never written', () => {
  let body = '前缀旧章节后缀';
  const range = {Start: 2, End: 5};
  Object.defineProperty(range, 'Text', {
    get: () => '别处文本',
    set: value => { body = value; }
  });
  const doc = {Selection: {Range: range}, Content: {Start: 0, End: body.length, Text: body}};

  assert.throws(() => load('writeMaterialComposerText', {})(doc, doc.Selection, '新章节'), /核实文档写入范围/);
  assert.equal(body, '前缀旧章节后缀');
});

test('applyMaterialComposerResult reports failure and guides to manual copy when write fails', async () => {
  const doc = {
    Selection: { Range: {Start: 2, End: 5, Text: '旧内容'} },
    Content: {Start: 0, End: 7, Text: '前缀旧内容后缀'}
  };
  const nodes = {
    'material-section-title': { value: '第一章' },
    'material-composer-status': { textContent: '' },
    'btn-material-apply': {disabled: false}
  };
  const applyFn = load('applyMaterialComposerResult', {
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: d => d.Selection,
    getSelectionText: d => d.Selection.Range.Text,
    materialComposerTargetSnapshot: {documentSessionId:'doc-a',sectionTitle:'第一章',start:2,end:5,selectedText:'旧内容'},
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({
      apply: async () => {
        throw new Error('写入失败：文档受保护');
      }
    })
  });

  await applyFn();
  assert.ok(nodes['material-composer-status'].textContent.includes('写入失败'));
  assert.ok(nodes['material-composer-status'].textContent.includes('文档受保护'));
});

test('editing composer facts updates draft inputs without mutating the submitted view', () => {
  const frozen={input:{sectionTitle:'预算',instruction:'编写',userFacts:'50万元'},conflictResolutions:[{chosenValue:'50万元'}]};
  let edited;
  const nodes={'material-section-title':{value:'预算'},'material-instruction':{value:'编写'},'material-user-facts':{value:'500万元'}};
  const change=load('handleMaterialComposerInputChange',{byId:id=>nodes[id],lastMaterialComposerView:frozen,ensureMaterialComposer:()=>({updateInput:input=>{edited=input;}})});
  change();
  assert.equal(frozen.input.userFacts,'50万元'); assert.equal(edited.userFacts,'500万元');
});

test('late conflict failure cannot replace a new document or edited input notice in the pane', async () => {
  for(const change of ['document','input']) {
    const context={window:{}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../wps-ai-assistant_1.0.0/material-composer.js'),'utf8'),context);
    let session='doc-a', reject;
    const saved=new Map();
    const nodes={'material-section-title':{value:'预算'},'material-instruction':{value:'编写'},'material-user-facts':{value:'50万元'},'material-composer-status':{textContent:''}};
    const composer=context.window.createMaterialComposer({
      getSessionId:()=>session,
      storage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)},
      render(){},
      request:()=>new Promise((resolve,fail)=>{reject=fail;})
    });
    composer.setMaterial({materialId:'m1'});
    const check=load('checkMaterialComposerConflicts',{byId:id=>nodes[id],ensureMaterialComposer:()=>composer});
    const pending=check();
    if(change==='document') session='doc-b';
    else composer.updateInput({sectionTitle:'预算',instruction:'编写',userFacts:'60万元'});
    nodes['material-composer-status'].textContent='当前提示，请保留';
    reject(Error('旧请求失败'));
    await pending;
    assert.equal(nodes['material-composer-status'].textContent,'当前提示，请保留');
  }
});

test('renderMaterialComposerView disables apply and preserves copy while basis is checking, updated or removed', () => {
  const nodes = {
    'material-composer-status': { textContent: '' },
    'material-import-file': { disabled: false },
    'material-section-title': { value: '第一章', disabled: false },
    'material-instruction': { value: '要求', disabled: false },
    'btn-material-selection': { disabled: false },
    'btn-material-generate': { disabled: false },
    'btn-material-cancel': { disabled: false },
    'btn-material-copy': { disabled: false },
    'btn-material-apply': { textContent: '', disabled: false },
    'material-composer-result': {}
  };
  const range = { Start: 2, End: 8, Text: '选区内容' };
  const snapshot = { documentSessionId: 'doc-a', sectionTitle: '第一章', start: 2, end: 8, selectedText: '选区内容' };
  const doc = { Selection: { Range: range } };
  const view = load('renderMaterialComposerView', {
    getMaterialComposerSessionId: () => 'doc-a',
    getActiveDocument: () => doc,
    getWritableSelection: () => doc.Selection,
    getSelectionText: () => '选区内容',
    materialComposerTargetSnapshot: snapshot,
    byId: id => nodes[id],
    window: { renderMaterialComposer() {} }
  });

  view({
    documentSessionId: 'doc-a',
    status: 'succeeded',
    busy: false,
    result: { plainText: '正文' },
    input: { sectionTitle: '第一章' },
    basisStatus: 'updated',
    error: '更新2不是有效DOCX'
  });
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.ok(nodes['material-composer-status'].textContent.includes('参考资料已更新'));
  assert.match(nodes['material-composer-status'].textContent, /更新2不是有效DOCX/);

  view({
    documentSessionId: 'doc-a',
    status: 'succeeded',
    busy: false,
    result: { plainText: '正文' },
    input: { sectionTitle: '第一章' },
    basisStatus: 'removed'
  });
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.ok(nodes['material-composer-status'].textContent.includes('已被移除'));
  view({ documentSessionId: 'doc-a', status: 'succeeded', busy: false, result: { plainText: '正文' }, input: { sectionTitle: '第一章' }, basisStatus: 'checking' });
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.equal(nodes['btn-material-copy'].disabled, false);
  assert.match(nodes['material-composer-status'].textContent, /核查|核对|确认/);
});

test('applyMaterialComposerResult pauses write-back when basis is updated or removed', async () => {
  const doc = {
    Selection: { Range: { Start: 2, End: 5, Text: '旧内容' } },
    Content: { Start: 0, End: 7, Text: '前缀旧内容后缀' }
  };
  const nodes = {
    'material-section-title': { value: '第一章' },
    'material-composer-status': { textContent: '' },
    'btn-material-apply': { disabled: false }
  };
  let applied = false;
  const applyFn = load('applyMaterialComposerResult', {
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: d => d.Selection,
    getSelectionText: d => d.Selection.Range.Text,
    materialComposerTargetSnapshot: { documentSessionId: 'doc-a', sectionTitle: '第一章', start: 2, end: 5, selectedText: '旧内容' },
    lastMaterialComposerView: { documentSessionId: 'doc-a', status: 'succeeded', basisStatus: 'updated', result: { plainText: '正文' } },
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({
      apply: async () => {
        applied = true;
        return { ok: true, mode: 'replace' };
      }
    })
  });

  await applyFn();
  assert.equal(applied, false);
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.ok(nodes['material-composer-status'].textContent.includes('参考资料已更新'));
});

test('checking the catalog pauses pane write without consuming the draft write attempt', async () => {
  const doc = { Selection: { Range: { Start: 2, End: 5, Text: '旧内容' } }, Content: { Start: 0, End: 7, Text: '前缀旧内容后缀' } };
  const nodes = { 'material-section-title': { value: '第一章' }, 'material-composer-status': { textContent: '' }, 'btn-material-apply': { disabled: false } };
  let applied = false;
  const context = {
    getActiveDocument: () => doc, getMaterialComposerSessionId: () => 'doc-a',
    getWritableSelection: d => d.Selection, getSelectionText: d => d.Selection.Range.Text,
    materialComposerTargetSnapshot: { documentSessionId: 'doc-a', sectionTitle: '第一章', start: 2, end: 5, selectedText: '旧内容' },
    lastMaterialComposerView: { documentSessionId: 'doc-a', status: 'succeeded', basisStatus: 'checking', result: { plainText: '正文' } },
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({ apply: async () => { applied = true; return { ok: true, mode: 'replace' }; } })
  };
  await load('applyMaterialComposerResult', context)();
  assert.equal(applied, false);
  assert.equal(context.materialComposerWriteAttempted, false);
  assert.equal(nodes['btn-material-apply'].disabled, true);
  assert.match(nodes['material-composer-status'].textContent, /核查|核对|确认/);
});

test('syncMaterialComposerSession migrates material session only after binding succeeds', async () => {
  const doc = { FullName: '未命名1.docx' };
  let currentDocSession = 'unsaved-session-1';
  const nodes = {
    'material-import-result': { textContent: '' },
    'material-import-file': { value: '' },
    'material-section-title': { value: '' },
    'material-instruction': { value: '' },
    'material-user-facts': { value: '' },
    'btn-material-apply': { disabled: false },
    'material-import-status': { textContent: '' }
  };
  const requests = [];
  const storage = new Map();
  storage.set('word.material-composer:unsaved-session-1', JSON.stringify({
    materialIds: ['m1'],
    documentSessionId: 'unsaved-session-1',
    catalogSummary: { totalDocuments: 1, documents: [{ materialId: 'm1', fileName: '资料1.docx' }] }
  }));

  let restored = 0;
  const context = {
    state: { currentMode: 'materialImport' },
    getActiveDocument: () => doc,
    getMaterialComposerSessionId: () => currentDocSession,
    lastBoundDocumentObject: doc,
    lastBoundDocumentSessionId: 'unsaved-session-1',
    materialComposerSession: 'unsaved-session-1',
    materialComposerBindings: [],
    request: (url, body) => {
      requests.push({ url, body });
      return Promise.resolve({ success: true, data: { totalDocuments: 1 } });
    },
    ensureMaterialComposer: () => ({
      restore: () => { restored += 1; }
    }),
    byId: id => nodes[id],
    window: {
      localStorage: {
        getItem: k => storage.get(k),
        setItem: (k, v) => storage.set(k, v)
      }
    }
  };

  const sync = load('syncMaterialComposerSession', context);

  // Document now saved as real path
  currentDocSession = 'saved-session-2';
  doc.FullName = '/path/to/saved.docx';

  sync();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/word/materials/bind-document');
  assert.equal(requests[0].body.oldDocumentSessionId, 'unsaved-session-1');
  assert.equal(requests[0].body.newDocumentSessionId, 'saved-session-2');

  assert.equal(storage.has('word.material-composer:saved-session-2'), false);
  await new Promise(resolve => setImmediate(resolve));
  // Verify storage was migrated after the server accepted the binding.
  assert.ok(storage.has('word.material-composer:saved-session-2'));
  const migrated = JSON.parse(storage.get('word.material-composer:saved-session-2'));
  assert.equal(migrated.documentSessionId, 'saved-session-2');
  assert.deepEqual(migrated.materialIds, ['m1']);
});

function materialBindingHarness() {
  const h = materialMutationHarness();
  h.doc = { FullName: '/path/to/saved.docx' };
  h.now = 1000;
  h.context.Date = { now: () => h.now };
  h.context.state = { currentMode: 'materialImport' };
  h.context.getActiveDocument = () => h.doc;
  h.context.lastBoundDocumentObject = h.doc;
  h.context.lastBoundDocumentSessionId = 'doc-a';
  h.context.materialComposerSession = 'doc-a';
  h.context.materialComposerBindings = [];
  h.context.window.localStorage = {
    getItem: key => h.saved.get(key), setItem: (key, value) => h.saved.set(key, value)
  };
  h.saved.set('word.material-composer:doc-a', JSON.stringify({
    documentSessionId: 'doc-a', materialId: 'm1', materialIds: ['m1'],
    catalogSummary: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] },
    jobId: 'old-job', clientJobId: 'old-client', submittedRequest: { documentSessionId: 'doc-a', clientJobId: 'old-client' },
    input: { sectionTitle: '第一章', instruction: '编写' }
  }));
  h.session = 'saved-a';
  h.sync = load('syncMaterialComposerSession', h.context);
  return h;
}

test('busy binding preserves pending migration and retries after the task can finish', async () => {
  const h = materialBindingHarness();
  let attempts = 0;
  h.request = async url => {
    if (url.includes('bind-document')) {
      attempts += 1;
      if (attempts === 1) throw Object.assign(Error('生成中'), { httpStatus: 409, adapterCode: 'MATERIAL_COMPOSER_BUSY' });
    }
    return { success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } };
  };
  h.sync();
  await h.flush();
  assert.equal(h.saved.has('word.material-composer:saved-a'), false);
  assert.match(h.node('material-import-status').textContent, /生成|任务/);
  h.sync();
  await h.flush();
  assert.equal(attempts, 1);
  h.now += 2000;
  h.sync();
  await h.flush();
  assert.equal(attempts, 2);
  assert.equal(h.last().catalogSummary.totalDocuments, 1);
  const migrated = JSON.parse(h.saved.get('word.material-composer:saved-a'));
  assert.deepEqual(migrated.materialIds, ['m1']);
  assert.ok(!migrated.jobId && !migrated.clientJobId && !migrated.submittedRequest);
});

test('binding an existing completed job never queries that job under the new document session', async () => {
  const h = materialBindingHarness();
  const urls = [];
  h.request = async url => {
    urls.push(url);
    return { success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } };
  };
  h.sync();
  await h.flush();
  assert.equal(urls.some(url => url.includes('/jobs/')), false);
  assert.equal(h.last().documentSessionId, 'saved-a');
  assert.equal(h.last().jobId, '');
  assert.deepEqual(JSON.parse(h.saved.get('word.material-composer:doc-a')).jobId, 'old-job');
});

test('a binding identity conflict is visible and never commits or repeatedly retries the migration', async () => {
  const h = materialBindingHarness();
  let attempts = 0;
  h.request = async () => {
    attempts += 1;
    throw Object.assign(Error('目标文档已有资料'), { httpStatus: 409, adapterCode: 'MATERIAL_BIND_TARGET_CONFLICT' });
  };
  h.sync();
  await h.flush();
  assert.match(h.node('material-import-status').textContent, /目标文档已有资料/);
  assert.equal(h.saved.has('word.material-composer:saved-a'), false);
  h.now += 10000;
  h.sync();
  await h.flush();
  assert.equal(attempts, 1);
});

test('saving to a different identity lets a pending conflict bind to the corrected target', async () => {
  const h = materialBindingHarness();
  const targets = [];
  h.request = async (url, body) => {
    if (url.includes('bind-document')) {
      targets.push(body.newDocumentSessionId);
      if (body.newDocumentSessionId === 'saved-a') throw Object.assign(Error('目标文档已有资料'), { httpStatus: 409, adapterCode: 'MATERIAL_BIND_TARGET_CONFLICT' });
    }
    return { success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } };
  };
  h.sync();
  await h.flush();
  h.session = 'saved-corrected-a';
  h.sync();
  await h.flush();
  assert.deepEqual(targets, ['saved-a', 'saved-corrected-a']);
  assert.equal(h.last().documentSessionId, 'saved-corrected-a');
  assert.deepEqual(Array.from(h.last().materialIds), ['m1']);
});

test('late binding success or failure cannot change another document pane', async () => {
  for (const outcome of ['success', 'failure']) {
    const h = materialBindingHarness();
    let resolveBind, rejectBind;
    h.request = url => {
      if (url.includes('bind-document')) return new Promise((resolve, reject) => { resolveBind = resolve; rejectBind = reject; });
      return Promise.resolve({ success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'b1' }], toc: [] } });
    };
    h.sync();
    h.doc = { FullName: '/path/to/b.docx' };
    h.session = 'doc-b';
    h.sync();
    await h.flush();
    h.node('material-import-status').textContent = 'B 文档提示';
    if (outcome === 'success') resolveBind({ success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } });
    else rejectBind(Object.assign(Error('A 生成中'), { httpStatus: 409, adapterCode: 'MATERIAL_COMPOSER_BUSY' }));
    await h.flush();
    assert.equal(h.last().documentSessionId, 'doc-b');
    assert.deepEqual(Array.from(h.last().materialIds), ['b1']);
    assert.equal(h.node('material-import-status').textContent, 'B 文档提示');
  }
});

test('two documents can retain independent pending save bindings', async () => {
  const h = materialBindingHarness();
  const pending = new Map();
  h.request = (url, body) => {
    if (url.includes('bind-document')) return new Promise(resolve => { pending.set(body.newDocumentSessionId, resolve); });
    if (url.includes('saved-a')) return Promise.resolve({ success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } });
    return Promise.resolve({ success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } });
  };
  h.sync();
  const a = h.doc;
  h.doc = { FullName: '未命名2.docx' };
  h.session = 'doc-b';
  h.sync();
  await h.flush();
  h.doc.FullName = '/path/to/b.docx';
  h.session = 'saved-b';
  h.sync();
  assert.equal(pending.size, 2);
  pending.get('saved-b')({ success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } });
  await h.flush();
  h.doc = a;
  h.session = 'saved-a';
  h.sync();
  pending.get('saved-a')({ success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } });
  await h.flush();
  assert.equal(h.last().documentSessionId, 'saved-a');
  assert.deepEqual(Array.from(h.last().materialIds), ['m1']);
});

test('a save completing while another document is active retains the next save migration', async () => {
  const h = materialBindingHarness();
  const a = h.doc;
  const binds = [];
  let resolveFirst;
  h.request = (url, body) => {
    const catalog = { success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } };
    if (url.includes('bind-document')) {
      binds.push([body.oldDocumentSessionId, body.newDocumentSessionId]);
      if (binds.length === 1) return new Promise(resolve => { resolveFirst = resolve; });
    }
    return Promise.resolve(catalog);
  };
  h.sync();
  h.doc = { FullName: '/path/to/b.docx' };
  h.session = 'doc-b';
  h.sync();
  resolveFirst({ success: true, data: { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm1' }], toc: [] } });
  await h.flush();
  h.doc = a;
  h.session = 'saved-a-again';
  h.sync();
  await h.flush();
  assert.deepEqual(binds, [['doc-a', 'saved-a'], ['saved-a', 'saved-a-again']]);
  assert.equal(h.last().documentSessionId, 'saved-a-again');
  assert.deepEqual(Array.from(h.last().materialIds), ['m1']);
});

test('saving before the first import still binds imported materials on the next save', async () => {
  const h = materialBindingHarness();
  h.saved.delete('word.material-composer:doc-a');
  const catalogs = new Map();
  const binds = [];
  const empty = { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] };
  h.request = async (url, body) => {
    if (url.includes('bind-document')) {
      binds.push([body.oldDocumentSessionId, body.newDocumentSessionId]);
      const source = catalogs.get(body.oldDocumentSessionId);
      if (!source) throw Object.assign(Error('原会话不存在资料集，无法迁移。'), { httpStatus: 404, adapterCode: 'MATERIAL_NOT_FOUND' });
      catalogs.set(body.newDocumentSessionId, source);
      catalogs.delete(body.oldDocumentSessionId);
      return { success: true, data: source };
    }
    if (url === '/word/materials') {
      const summary = { totalDocuments: 1, totalCharacters: 20, documents: [{ materialId: 'm-new', fileName: body.fileName }], toc: [] };
      catalogs.set(body.documentSessionId, summary);
      return { success: true, data: { materialId: 'm-new', documentSessionId: body.documentSessionId, catalogSummary: summary } };
    }
    return { success: true, data: catalogs.get(decodeURIComponent(url.split('documentSessionId=')[1])) || empty };
  };
  h.sync();
  await h.flush();
  load('handleMaterialImportFileChange', h.context)({ target: { files: [{ name: '首次资料.docx' }] } });
  await h.flush();
  h.session = 'saved-a-again';
  h.sync();
  await h.flush();
  assert.deepEqual(binds, [['doc-a', 'saved-a'], ['saved-a', 'saved-a-again']]);
  assert.equal(h.last().documentSessionId, 'saved-a-again');
  assert.deepEqual(Array.from(h.last().materialIds), ['m-new']);
  assert.equal(h.saved.has('word.material-composer:doc-a'), false);
});

test('an explicitly missing server source preserves the old local job and reports unavailable materials', async () => {
  const h = materialBindingHarness();
  const oldCache = h.saved.get('word.material-composer:doc-a');
  let binds = 0;
  h.request = async url => {
    if (url.includes('bind-document')) {
      binds += 1;
      throw Object.assign(Error('原会话不存在资料集，无法迁移。'), { httpStatus: 404, adapterCode: 'MATERIAL_NOT_FOUND' });
    }
    return { success: true, data: { totalDocuments: 0, totalCharacters: 0, documents: [], toc: [] } };
  };
  h.sync();
  await h.flush();
  assert.equal(h.saved.get('word.material-composer:doc-a'), oldCache);
  assert.match(h.node('material-import-status').textContent, /不可用|不存在/);
  assert.ok(h.last(), 'the current document catalog must be restored after a missing source');
  assert.equal(h.last().documentSessionId, 'saved-a');
  assert.deepEqual(Array.from(h.last().materialIds), []);
  assert.equal(h.last().jobId, '');
  h.now += 10000;
  h.sync();
  await h.flush();
  assert.equal(binds, 1);
});

test('an unrelated 404 remains an explicit binding failure and does not advance the source session', async () => {
  const h = materialBindingHarness();
  const binds = [];
  h.request = async (url, body) => {
    binds.push(body.oldDocumentSessionId);
    throw Object.assign(Error('接口不可用'), { httpStatus: 404, adapterCode: 'ROUTE_NOT_FOUND' });
  };
  h.sync();
  await h.flush();
  assert.equal(h.saved.has('word.material-composer:saved-a'), false);
  assert.match(h.node('material-import-status').textContent, /接口不可用/);
  h.session = 'saved-a-again';
  h.sync();
  await h.flush();
  assert.deepEqual(binds, ['doc-a', 'doc-a']);
});
