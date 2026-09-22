const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/taskpane.js'), 'utf8');
function load(name, context) {
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
  const run = load('startMaterialComposer', {
    byId: id => nodes[id],
    ensureMaterialComposer: () => ({start(value) { input = value; return Promise.resolve(); }}),
    validateActiveDirectTaskSelection: () => ({valid:true}),
    getActiveDocument: () => { throw new Error('must not read current body'); }
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
window.requests=[];
window.Application={ActiveDocument:{Name:'章节.docx',FullName:'/test/章节.docx',Selection:{Text:'实施安排'}}};
window.fetch=async function(url,options){
  var p=new URL(url).pathname, body=options&&options.body?JSON.parse(options.body):null;
  requests.push({path:p,body:body});
  var data={};
  if(p==='/health')data={status:'ok',modelTasksAllowed:true,configurationMutationsAllowed:true};
  if(p==='/word/materials')data={materialId:'mat-browser',documentSessionId:body.documentSessionId,blocks:[],fragments:[],fileName:'资料.docx'};
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
    run('fill','#material-section-title','实施安排');
    run('fill','#material-instruction','简要说明责任和工期');
    run('click','#btn-material-generate');
    run('wait','--text','信息化处负责。');
    assert.ok(run('get','text','#material-composer-result').includes('资料.docx'));
    assert.equal(run('eval',`String(document.querySelectorAll('#material-composer-result .material-composer-sources').length)`).trim(),'"1"');
    assert.equal(run('eval',`document.documentElement.scrollWidth <= innerWidth && getComputedStyle(document.getElementById('word-result-section')).display === "none"`).trim(), 'true');
    run('reload');
    run('wait','--text','信息化处负责。');
    const after=run('eval',`JSON.stringify(requests.filter(r=>r.path==='/word/material-composer/jobs'))`);
    assert.ok(after.includes('[]'),after);
  } finally { try {run('close');} finally {fs.rmSync(temp,{recursive:true,force:true});} }
});
