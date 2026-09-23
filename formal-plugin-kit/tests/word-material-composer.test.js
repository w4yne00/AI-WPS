const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');
function harness(shared) {
  const context = { window: {}, Promise, Date, Math };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../wps-ai-assistant_1.0.0/material-composer.js'), 'utf8'), context);
  const saved = shared || new Map();
  const h = { session: 'doc-a', calls: [], views: [], copied: [], applied: [], scheduled: [], response: { success: true, data: { jobId: 'job-a', status: 'running', documentSessionId: 'doc-a' } } };
  h.api = context.window.createMaterialComposer({
    storage: { getItem: k => saved.get(k), setItem: (k,v) => saved.set(k,v) },
    getSessionId: () => h.session,
    request: async (url, body, method) => { h.calls.push({url,body,method:method.method}); if (h.error) throw Error('offline'); return h.respond ? h.respond() : h.response; },
    render: v => h.views.push(v), copyText: t => h.copied.push(t), schedule: fn => h.scheduled.push(fn),
    applyText: async (t, opts) => {
      h.applied.push({ text: t, options: opts });
      if (h.applyError) throw h.applyError;
      if (h.applyReturnFalse) return false;
      return true;
    }
  });
  h.saved = saved;
  h.last = () => h.views[h.views.length - 1];
  return h;
}
function result(session = 'doc-a') { return { taskType: 'word.material_composer', documentSessionId: session, plainText: '正文', paragraphs: [{text:'正文',sources:[{fileName:'资料.docx',section:'第一章',quote:'原句',fragmentId:'f1'}],missingItems:[]}],missingItems:[] }; }
test('submits material reference and input, persists no source text, prevents repeated submission while running', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1',text:'秘密原文'}); await h.api.start({sectionTitle:'范围',instruction:'编写'}); await h.api.start({sectionTitle:'范围',instruction:'编写'});
 assert.equal(h.calls.filter(x=>x.method==='POST').length,1); assert.equal(h.calls[0].body.materialId,'m1'); assert.equal(h.calls[0].body.documentSessionId,'doc-a'); assert.ok(h.calls[0].body.clientJobId); assert.equal(h.last().status,'running'); assert.ok(!JSON.stringify([...h.saved]).includes('秘密原文'));
});
test('reopening restores the same job; transient query failures keep it available for retry', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'编写'});
 const reopened=harness(h.saved); reopened.error=true; await reopened.api.restore(); assert.equal(reopened.last().jobId,'job-a'); assert.ok(reopened.last().error);
 reopened.error=false; await reopened.api.refresh(); assert.equal(reopened.last().status,'running'); assert.equal(reopened.calls.length,2); assert.ok(reopened.calls.every(x=>x.method==='GET' && x.url.includes('job-a')));
});
test('cancel requests the original job and renders cancellation', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'编写'}); h.response={success:true,data:{jobId:'job-a',status:'cancelled',documentSessionId:'doc-a'}}; await h.api.cancel(); assert.equal(h.last().status,'cancelled'); assert.equal(h.calls[1].url,'/word/material-composer/jobs/job-a/cancel'); assert.equal(h.calls[1].body.documentSessionId,'doc-a');
});
test('switching documents isolates material, job and late response', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'编写'}); h.session='doc-b'; await h.api.restore(); assert.equal(h.last().materialId,''); assert.equal(h.last().jobId,''); await h.scheduled[0](); assert.equal(h.calls.length,1); h.session='doc-a'; await h.api.restore(); assert.equal(h.last().jobId,'job-a');
});
test('only a validated result from the current document can be copied', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'编写'}); h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh(); await h.api.copy(); assert.deepEqual(h.copied,['正文']); h.session='doc-b'; await h.api.copy(); assert.equal(h.copied.length,1);
});
test('malformed successful responses and wrong-session results never claim success or copy', async () => {
 for(const bad of [{plainText:'未经核验'},result('doc-b'),{...result(),paragraphs:[]}]) { const h=harness(); h.api.setMaterial({materialId:'m1'}); h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:bad}}; await h.api.start({sectionTitle:'范围',instruction:'编写'}); await h.api.copy(); assert.notEqual(h.last().status,'succeeded'); assert.ok(h.last().error); assert.equal(h.copied.length,0); }
});

test('a late response from a different document never renders into the current document', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); let finish; h.respond=()=>new Promise(resolve=>{finish=resolve;}); const running=h.api.start({sectionTitle:'范围',instruction:'编写'}); h.session='doc-b'; await h.api.restore(); const before=h.views.length; finish(h.response); await running; assert.equal(h.views.length,before); assert.equal(h.last().documentSessionId,'doc-b');
});
test('uncertain submission retries with the original idempotency key', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.error=true; await h.api.start({sectionTitle:'范围',instruction:'编写'}); const first=h.calls[0].body.clientJobId; h.error=false; await h.api.start({sectionTitle:'范围',instruction:'编写'}); assert.equal(h.calls[1].body.clientJobId,first); assert.equal(h.last().jobId,'job-a');
});
test('completed backend state is validated and a failed task can explicitly start again', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.response={success:true,data:{jobId:'job-a',status:'failed',documentSessionId:'doc-a',error:{message:'模型失败'}}}; await h.api.start({sectionTitle:'范围',instruction:'编写'}); assert.equal(h.last().error,'模型失败'); const old=h.calls[0].body.clientJobId; h.response={success:true,data:{jobId:'job-b',status:'completed',documentSessionId:'doc-a',result:result()}}; await h.api.start({sectionTitle:'范围',instruction:'编写'}); assert.notEqual(h.calls[1].body.clientJobId,old); assert.equal(h.last().status,'succeeded'); await h.api.copy(); assert.deepEqual(h.copied,['正文']);
});
test('late material import stays bound to its originating document', async () => {
 const h=harness(); h.session='doc-b'; h.api.setMaterial({materialId:'m-a',documentSessionId:'doc-a'}); await h.api.restore(); assert.equal(h.last().materialId,''); h.session='doc-a'; await h.api.restore(); assert.equal(h.last().materialId,'m-a');
});
test('reopening uncertain submission queries client id without posting and retains server phase', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.error=true; await h.api.start({sectionTitle:'范围',instruction:'编写'}); const clientId=h.calls[0].body.clientJobId;
 const reopened=harness(h.saved); reopened.response={success:true,data:{jobId:clientId,status:'running',documentSessionId:'doc-a',phase:'checking',phaseLabel:'核对出处'}}; await reopened.api.restore(); assert.equal(reopened.calls.length,1); assert.equal(reopened.calls[0].method,'GET'); assert.ok(reopened.calls[0].url.includes(clientId)); assert.equal(reopened.last().phase,'checking'); assert.equal(reopened.last().phaseLabel,'核对出处');
});
test('missing uncertain job can be explicitly retried with its existing client id', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.error=true; await h.api.start({sectionTitle:'范围',instruction:'编写'}); const clientId=h.calls[0].body.clientJobId;
 const reopened=harness(h.saved); reopened.respond=()=>Promise.reject(Object.assign(Error('not found'),{status:404})); await reopened.api.restore(); assert.equal(reopened.calls.length,1); assert.equal(reopened.last().status,'idle'); reopened.respond=null; await reopened.api.start({sectionTitle:'范围',instruction:'编写'}); assert.equal(reopened.calls[1].body.clientJobId,clientId);
});
test('reopened uncertain job keeps its original input after a missing query and later edits', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.error=true; await h.api.start({sectionTitle:'原章节',instruction:'原要求'});
 const reopened=harness(h.saved); reopened.respond=()=>Promise.reject(Object.assign(Error('not found'),{status:404})); await reopened.api.restore(); reopened.respond=null;
 await reopened.api.start({sectionTitle:'新章节',instruction:'新要求'});
 assert.equal(reopened.calls[1].body.sectionTitle,'原章节'); assert.equal(reopened.calls[1].body.instruction,'原要求');
});
test('reopened uncertain job can retry its original input after restored fields are cleared', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.error=true; await h.api.start({sectionTitle:'原章节',instruction:'原要求'});
 const reopened=harness(h.saved); reopened.respond=()=>Promise.reject(Object.assign(Error('not found'),{status:404})); await reopened.api.restore(); reopened.respond=null;
 await reopened.api.start({sectionTitle:'',instruction:''});
 assert.equal(reopened.calls[1].body.sectionTitle,'原章节'); assert.equal(reopened.calls[1].body.instruction,'原要求');
});
test('render separates each paragraph from its source sidebar and safely displays markup as text', () => {
 const context={window:{}}; vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../wps-ai-assistant_1.0.0/material-composer.js'),'utf8'),context);
 const document={createElement(tag){return {tagName:tag,children:[],appendChild(child){this.children.push(child);},textContent:'',className:''};}};
 const root=document.createElement('div'); root.ownerDocument=document;
 const draft=result(); draft.paragraphs[0].text='<script>正文</script>'; draft.paragraphs[0].missingItems=['待核实日期'];
 context.window.renderMaterialComposer(root,{status:'succeeded',phaseLabel:'核对完成',result:draft});
 const row=root.children.find(x=>x.className==='material-composer-paragraph'); assert.ok(row); assert.equal(row.children[0].tagName,'p'); assert.equal(row.children[0].textContent,'<script>正文</script>'); assert.equal(row.children[1].tagName,'aside'); assert.ok(row.children[1].children.some(x=>x.textContent.includes('资料.docx'))); assert.ok(row.children[1].children.some(x=>x.textContent.includes('待核实日期'))); assert.ok(root.children.some(x=>x.textContent==='核对完成'));
});
test('expired known job releases the material and allows another import', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'编写'}); h.respond=()=>Promise.reject(Object.assign(Error('expired'),{httpStatus:404,adapterCode:'material_composer_job_not_found'})); await h.api.refresh(); assert.equal(h.last().status,'idle'); assert.equal(h.last().jobId,''); h.api.setMaterial({materialId:'m2'}); assert.equal(h.last().materialId,'m2');
});
test('explicit submission rejection releases input and idempotency key for corrected material', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.respond=()=>Promise.reject(Object.assign(Error('too large'),{httpStatus:413,adapterCode:'material_too_large'})); await h.api.start({sectionTitle:'范围',instruction:'编写'}); assert.equal(h.last().status,'idle'); assert.equal(h.last().clientJobId,''); h.api.setMaterial({materialId:'m2'}); assert.equal(h.last().materialId,'m2');
});
test('uncertain submission retains original input and never creates a second server job after edits', async () => {
 const h=harness(); const jobs=new Map(); let drop=true;
 h.respond=()=>{ const call=h.calls[h.calls.length-1]; if(call.method==='GET') return {success:true,data:jobs.get(call.url.split('/').pop().split('?')[0]).job}; const key=call.body.clientJobId; const fingerprint=JSON.stringify(call.body); if(jobs.has(key) && jobs.get(key).fingerprint!==fingerprint) throw Object.assign(Error('conflict'),{httpStatus:409}); const job={jobId:key,status:'running',documentSessionId:'doc-a'}; jobs.set(key,{fingerprint,job}); if(drop){drop=false; throw Error('response lost');} return {success:true,data:job}; };
 h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'范围',instruction:'原要求'}); await h.api.start({sectionTitle:'改范围',instruction:'新要求'}); assert.equal(h.calls[1].body.instruction,'原要求'); assert.equal(h.calls[1].body.sectionTitle,'范围'); assert.equal(h.last().status,'running'); await h.api.start({sectionTitle:'再次修改',instruction:'第三个要求'}); assert.equal(jobs.size,1);
});
test('conflicting uncertain submission keeps its key available for querying the original job', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); h.respond=()=>Promise.reject(Object.assign(Error('conflict'),{httpStatus:409})); await h.api.start({sectionTitle:'范围',instruction:'要求'}); const key=h.calls[0].body.clientJobId; assert.equal(h.last().clientJobId,key); h.respond=null; await h.api.refresh(); assert.ok(h.calls[1].url.includes(key)); assert.equal(h.calls[1].method,'GET');
});

test('explicit confirmation applies draft to selection or cursor, and rejects full document replacement', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh();
 await h.api.apply({sectionTitle:'第一章',selectionText:'旧内容'});
 assert.equal(h.applied.length,1); assert.equal(h.applied[0].text,'正文'); assert.equal(h.applied[0].options.mode,'replace'); assert.equal(h.applied[0].options.selectionText,'旧内容'); assert.ok(h.last().phaseLabel.includes('已替换'));
 await h.api.apply({sectionTitle:'第一章',selectionText:''});
 assert.equal(h.applied.length,2); assert.equal(h.applied[1].options.mode,'insert'); assert.ok(h.last().phaseLabel.includes('已插入'));
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章',isFullDocument:true}), /禁止全篇替换|仅支持替换选区或光标/);
 assert.equal(h.applied.length,2);
});

test('a noncollapsed whitespace selection is replacement rather than cursor insertion', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh();
 await h.api.apply({sectionTitle:'第一章',selectionText:'',hasSelection:true});
 assert.equal(h.applied[0].options.mode,'replace');
});

test('target chapter change pauses replacement and preserves draft', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh();
 await assert.rejects(() => h.api.apply({sectionTitle:'第二章 变更后'}), /目标章节已变更，已暂停替换/);
 assert.ok(h.last().result); assert.equal(h.applied.length,0); assert.ok(h.last().error.includes('目标章节已变更'));
 await h.api.apply({sectionTitle:'第一章',selectionText:'选区'});
 assert.equal(h.applied.length,1);
});

test('switching document session isolates apply and prevents writing to another document', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh();
 h.session='doc-b';
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章',documentSessionId:'doc-a'}), /文档不一致/);
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /没有可写入/);
 assert.equal(h.applied.length,0);
});

test('unconfirmed, running, cancelled or failed draft rejects apply', async () => {
 const h=harness();
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /没有可写入/);
 h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /没有可写入/);
 h.response={success:true,data:{jobId:'job-a',status:'cancelled',documentSessionId:'doc-a'}}; await h.api.cancel();
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /没有可写入/);
 h.response={success:true,data:{jobId:'job-a',status:'failed',documentSessionId:'doc-a',error:'失败'}}; await h.api.refresh();
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /没有可写入/);
 assert.equal(h.applied.length,0);
});

test('write failure reports clear error and preserves draft for manual copy', async () => {
 const h=harness(); h.api.setMaterial({materialId:'m1'}); await h.api.start({sectionTitle:'第一章',instruction:'编写'});
 h.response={success:true,data:{jobId:'job-a',status:'succeeded',documentSessionId:'doc-a',result:result()}}; await h.api.refresh();
 h.applyError=new Error('WPS COM error');
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /WPS COM error/);
 assert.ok(h.last().error.includes('WPS COM error') || h.last().error.includes('写入失败'));
 assert.ok(h.last().result);
 await h.api.copy(); assert.deepEqual(h.copied,['正文']);
 h.applyError=null; h.applyReturnFalse=true;
 await assert.rejects(() => h.api.apply({sectionTitle:'第一章'}), /未完成|写入失败/);
 assert.ok(h.last().result);
});
