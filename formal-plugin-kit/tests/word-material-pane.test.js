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
  }
  const start = source.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'missing function ' + name);
  const end = source.indexOf('\n  function ', start + 1);
  return vm.runInNewContext('(' + source.slice(start, end) + ')', context);
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
    getSelectionText: selected => { assert.equal(selected,doc); return '第二章 实施安排'; }
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
    ensureMaterialComposer: () => ({setMaterial(reading) { accepted.push(reading.materialId); }}),
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
  if(p==='/word/material-composer/jobs'){
    localStorage.setItem('test-job',JSON.stringify(body));
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
    run('click','.material-composer-toc summary');
    run('click','.material-composer-toc-chapter');
    assert.equal(run('eval',`document.getElementById('material-section-title').value`).trim(), '"实施安排"');
    run('fill','#material-instruction','简要说明责任和工期');
    run('click','#btn-material-generate');
    run('wait','--text','信息化处负责。');
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
