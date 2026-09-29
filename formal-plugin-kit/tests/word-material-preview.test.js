const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {wordRoot} = require('./support/plugin-roots');

test('preview gives prose full width and drills into sources with reading position preserved', t => {
  try {execFileSync('agent-browser', ['--version'], {stdio:'ignore'});} catch (_) {t.skip('agent-browser unavailable'); return;}
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'cite-'));
  const run = (...args) => execFileSync('agent-browser', ['--session', 'cp-' + path.basename(temp).slice(-6), ...args], {encoding:'utf8',env:{...process.env,AGENT_BROWSER_SOCKET_DIR:temp}}).trim();
  const draft = {plainText:'完整正文', missingItems:['完成时间'], unverifiedItems:['预算待核对'], paragraphs:Array.from({length:12}, (_,i)=>({text:'第'+(i+1)+'段正文。'+'需要完整阅读的文字。'.repeat(25),sources:[{fileName:'资料.docx',section:'建设内容',fragmentId:'frag-'+i,quote:'<img src=x onerror=alert(1)>原始引文'+i}],missingItems:[],unverifiedItems:[]}))};
  const html = '<!doctype html><meta charset="utf-8"><style>'+fs.readFileSync(path.join(wordRoot,'taskpane.css'),'utf8')+'</style><div id="context"></div><div id="preview" class="material-composer-preview"></div><script>'+fs.readFileSync(path.join(wordRoot,'material-composer.js'),'utf8')+'</script><script>window.view={documentSessionId:"doc-a",jobId:"job-a",status:"succeeded",result:'+JSON.stringify(draft)+'};window.refresh=()=>renderMaterialComposer(document.getElementById("context"),view,null,null,null,null,document.getElementById("preview"));refresh();</script>';
  const page = path.join(temp,'preview.html');fs.writeFileSync(page,html);
  try {
    run('open',require('node:url').pathToFileURL(page).href);
    for (const width of [420,320]) {
      run('set','viewport',String(width),'900');
      assert.equal(run('eval','(()=>{const p=document.querySelector(".material-composer-body"),r=p.closest(".material-composer-paragraph");return p.getBoundingClientRect().width/r.getBoundingClientRect().width>=.98})()'),'true');
    }
    assert.equal(run('eval','document.querySelectorAll("#preview blockquote").length'),'0');
    assert.equal(run('eval','document.querySelectorAll(".material-composer-source-link").length'),'12');
    assert.equal(run('eval','document.querySelector(".material-composer-issues-link").textContent.includes("2")'),'true');
    run('eval','document.getElementById("preview").scrollTop=240;window.savedScroll=document.getElementById("preview").scrollTop;document.querySelectorAll(".material-composer-source-link")[1].click()');
    assert.ok(run('get','text','#preview').includes('原始引文1'));
    assert.equal(run('eval','document.querySelectorAll("#preview img").length'),'0');
    assert.equal(run('eval','document.querySelectorAll("#preview .material-composer-body").length'),'0');
    run('eval','view=JSON.parse(JSON.stringify(view));refresh()');
    assert.ok(run('get','text','#preview').includes('原始引文1'));
    run('click','.material-composer-back');
    assert.equal(run('eval','document.getElementById("preview").scrollTop===savedScroll'),'true');
    assert.equal(run('eval','document.activeElement===document.querySelectorAll(".material-composer-source-link")[1]'),'true');
    run('eval','document.querySelector(".material-composer-issues-link").click()');
    assert.ok(run('get','text','#preview').includes('完成时间'));
    run('eval','view.basisStatus="removed";refresh()');
    assert.ok(run('get','text','#context').includes('已失效'));
    run('eval','view.documentSessionId="doc-b";view.jobId="job-b";refresh()');
    assert.equal(run('eval','document.querySelectorAll("#preview blockquote").length'),'0');
    assert.equal(run('eval','document.querySelectorAll("#preview .material-composer-body").length'),'12');
  } finally {try {run('close');} finally {fs.rmSync(temp,{recursive:true,force:true});}}
});
