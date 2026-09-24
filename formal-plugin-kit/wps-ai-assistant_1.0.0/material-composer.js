function createMaterialComposer(options) {
  var states = {};
  var schedule = options.schedule || function (fn, ms) { return setTimeout(fn, ms); };
  function formatCatalogLabel(summary) {
    if (!summary || !summary.totalDocuments) return '';
    var totalChars = typeof summary.totalCharacters === 'number' ? summary.totalCharacters.toLocaleString() : '0';
    return '已导入 ' + summary.totalDocuments + '/5 份资料，合计 ' + totalChars + '/100,000 字';
  }
  function stateFor(id) {
    if (!states[id]) {
      var saved = options.storage.getItem('word.material-composer:' + id);
      var data = saved ? JSON.parse(saved) : {};
      var catalogSummary = data.catalogSummary || null;
      states[id] = {
        documentSessionId: id,
        materialId: data.materialId || '',
        materialIds: data.materialIds || (data.materialId ? [data.materialId] : []),
        materials: data.materials || [],
        catalogSummary: catalogSummary,
        catalogLabel: formatCatalogLabel(catalogSummary),
        jobId: data.jobId || '',
        clientJobId: data.clientJobId || '',
        input: data.input || {},
        status: (data.jobId || data.clientJobId) ? 'running' : 'idle',
        phase: '',
        phaseLabel: '',
        result: null,
        error: '',
        busy: false,
        pending: false
      };
    }
    return states[id];
  }
  function current() { return stateFor(options.getSessionId()); }
  function persist(s) {
    options.storage.setItem('word.material-composer:' + s.documentSessionId, JSON.stringify({
      materialId: s.materialId,
      materialIds: s.materialIds,
      materials: s.materials,
      catalogSummary: s.catalogSummary,
      jobId: s.jobId,
      clientJobId: s.clientJobId,
      input: s.input
    }));
  }
  function show(s) {
    if (options.getSessionId() === s.documentSessionId) options.render(Object.assign({}, s));
  }
  function validResult(r, id) {
    return r && r.taskType === 'word.material_composer' && r.documentSessionId === id && typeof r.plainText === 'string' && r.plainText.trim() && Array.isArray(r.missingItems) && Array.isArray(r.paragraphs) && r.paragraphs.length > 0 && r.paragraphs.every(function (p) {
      return typeof p.text === 'string' && p.text.trim() && Array.isArray(p.missingItems) && Array.isArray(p.sources) && p.sources.every(function (source) {
        return ['fileName', 'section', 'quote', 'fragmentId'].every(function (key) { return typeof source[key] === 'string'; });
      });
    });
  }
  function active(s) { return s.status === 'queued' || s.status === 'running'; }
  function poll(s) {
    if (!active(s) || s.pending) return;
    s.pending = true;
    schedule(function () { s.pending = false; if (options.getSessionId() === s.documentSessionId && active(s)) return refresh(); }, 1500);
  }
  function accept(s, response) {
    var job = response && response.success === true && response.data;
    if (!job || !job.jobId || (job.documentSessionId && job.documentSessionId !== s.documentSessionId) || ['queued', 'running', 'succeeded', 'completed', 'failed', 'cancelled'].indexOf(job.status) < 0) throw new Error('任务返回格式不正确，请重试查询。');
    if (s.jobId && job.jobId !== s.jobId) throw new Error('任务编号不匹配，请重试查询。');
    s.jobId = job.jobId;
    s.status = job.status === 'completed' ? 'succeeded' : job.status;
    s.phase = job.phase || '';
    s.phaseLabel = job.phaseLabel || '';
    s.result = null;
    if (s.status === 'succeeded') {
      if (!validResult(job.result, s.documentSessionId)) { s.status = 'failed'; throw new Error('返回正文或出处格式不完整，不能复制。'); }
      s.result = job.result;
    }
    s.error = s.status === 'failed' ? (job.error && (job.error.message || job.error) || '任务失败，请检查后重新生成。') : '';
  }
  async function execute(s, url, body, method) {
    s.busy = true; s.error = ''; show(s);
    try { accept(s, await options.request(url, body, { method: method })); }
    catch (error) {
      s.error = error.message || '任务请求失败，请重试。';
      var httpStatus = error.httpStatus || error.status;
      if (method === 'GET' && httpStatus === 404) {
        // A missing known job has expired; an uncertain submission can retry its original key.
        if (s.jobId) s.clientJobId = '';
        s.jobId = ''; s.result = null; s.status = 'idle'; s.phase = ''; s.phaseLabel = '';
      }
      if (method === 'POST' && !s.jobId && httpStatus >= 400 && httpStatus < 500 && httpStatus !== 408 && httpStatus !== 409) {
        s.clientJobId = ''; s.result = null; s.status = 'idle'; s.phase = ''; s.phaseLabel = '';
      }
    }
    finally { s.busy = false; persist(s); show(s); if (!s.error) poll(s); }
  }
  async function refresh() {
    var s = current();
    if (!(s.jobId || s.clientJobId) || s.busy) { show(s); return; }
    await execute(s, '/word/material-composer/jobs/' + encodeURIComponent(s.jobId || s.clientJobId) + '?documentSessionId=' + encodeURIComponent(s.documentSessionId), undefined, 'GET');
  }
  return {
    setMaterial: function (reading) {
      var s = stateFor(reading.documentSessionId || options.getSessionId());
      if (s.busy || active(s)) return;
      s.materialId = reading.materialId || '';
      if (!s.materialIds) s.materialIds = [];
      if (s.materialId && s.materialIds.indexOf(s.materialId) === -1) {
        s.materialIds.push(s.materialId);
      }
      if (reading.catalogSummary) {
        s.catalogSummary = reading.catalogSummary;
        if (reading.catalogSummary.documents && reading.catalogSummary.documents.length) {
          s.materialIds = reading.catalogSummary.documents.map(function (d) { return d.materialId; }).filter(Boolean);
        }
      } else if (reading.materialId) {
        s.catalogSummary = {
          totalDocuments: s.materialIds.length,
          totalCharacters: (reading.limits && reading.limits.readableCharacterCount) || 0,
          documents: [{ materialId: reading.materialId, fileName: reading.fileName || '' }]
        };
      }
      s.catalogLabel = formatCatalogLabel(s.catalogSummary);
      s.jobId = '';
      s.clientJobId = '';
      s.result = null;
      s.status = 'idle';
      s.error = '';
      persist(s);
      show(s);
    },
    start: async function (input) {
      var s = current();
      if (s.busy || (s.jobId && active(s))) { show(s); return; }
      var retryingUncertain = Boolean(s.clientJobId && !s.jobId);
      var selectedInput = retryingUncertain ? s.input : input;
      var hasMaterial = Boolean(s.materialId || (s.materialIds && s.materialIds.length) || (s.catalogSummary && s.catalogSummary.totalDocuments));
      if (!hasMaterial || !s.documentSessionId || !selectedInput || typeof selectedInput.sectionTitle !== 'string' || typeof selectedInput.instruction !== 'string' || !selectedInput.sectionTitle.trim() || !selectedInput.instruction.trim()) { s.error = '请先导入资料，并填写章节标题和编写要求。'; show(s); return; }
      if (!retryingUncertain) s.input = { sectionTitle: selectedInput.sectionTitle, instruction: selectedInput.instruction };
      // Keep the idempotency key after an uncertain submission so a retry cannot create another job.
      if (s.jobId || !s.clientJobId) s.clientJobId = 'composer-' + Date.now() + '-' + Math.random().toString(36).slice(2);
      s.jobId = ''; s.result = null; s.status = 'queued'; persist(s);
      var mids = (s.materialIds && s.materialIds.length) ? s.materialIds : (s.materialId ? [s.materialId] : []);
      var body = {
        documentSessionId: s.documentSessionId,
        clientJobId: s.clientJobId,
        sectionTitle: s.input.sectionTitle,
        instruction: s.input.instruction
      };
      if (mids.length) {
        body.materialIds = mids;
        body.materialId = mids[0];
      } else if (s.materialId) {
        body.materialId = s.materialId;
      }
      await execute(s, '/word/material-composer/jobs', body, 'POST');
    },
    refresh: refresh,
    restore: async function () { var s = current(); show(s); if (s.jobId || s.clientJobId) await refresh(); },
    cancel: async function () { var s = current(); if (!s.jobId || s.busy || !active(s)) return; await execute(s, '/word/material-composer/jobs/' + encodeURIComponent(s.jobId) + '/cancel', { documentSessionId: s.documentSessionId }, 'POST'); },
    copy: async function () { var s = current(); if (s.status === 'succeeded' && validResult(s.result, s.documentSessionId)) await options.copyText(s.result.plainText); },
    apply: async function (target) {
      var s = current();
      if (target && target.documentSessionId && target.documentSessionId !== options.getSessionId()) {
        throw new Error('当前活动文档与草稿所属文档不一致，已阻止写入。');
      }
      if (options.getSessionId() !== s.documentSessionId) {
        throw new Error('当前活动文档与草稿所属文档不一致，已阻止写入。');
      }
      if (s.status !== 'succeeded' || !validResult(s.result, s.documentSessionId)) {
        throw new Error('当前没有可写入的章节草稿。');
      }
      var currentSection = (target && typeof target.sectionTitle === 'string') ? target.sectionTitle.trim() : '';
      var originalSection = (s.input && typeof s.input.sectionTitle === 'string') ? s.input.sectionTitle.trim() : '';
      if (currentSection && originalSection && currentSection !== originalSection) {
        s.error = '生成期间目标章节已变更，已暂停替换。请重新确认目标章节或重新生成。';
        show(s);
        throw new Error(s.error);
      }
      if (target && (target.isFullDocument || target.targetType === 'document')) {
        throw new Error('章节草稿仅支持替换选区或光标插入，禁止全篇替换。');
      }
      var mode = target && (target.hasSelection === true ||
        (target.hasSelection !== false && target.selectionText && target.selectionText.trim())) ? 'replace' : 'insert';
      if (typeof options.applyText !== 'function') {
        throw new Error('未配置文档写入处理器。');
      }
      try {
        var applied = await options.applyText(s.result.plainText, {
          mode: mode,
          selectionText: (target && target.selectionText) || '',
          documentSessionId: s.documentSessionId
        });
        if (!applied) {
          throw new Error('文档写入未完成，请点击「复制正文」后手动粘贴。');
        }
        s.error = '';
        s.phaseLabel = mode === 'replace' ? '章节草稿已替换至所选区域。' : '章节草稿已插入至光标位置。';
        show(s);
        return { ok: true, mode: mode };
      } catch (error) {
        s.error = (error && error.message) || '写入失败，请点击「复制正文」后手动粘贴。';
        show(s);
        throw error;
      }
    }
  };
}
function renderMaterialComposer(root, view) {
  var doc = root.ownerDocument;
  function append(parent, tag, text, className) {
    var node = doc.createElement(tag);
    node.className = className || '';
    node.textContent = text || '';
    parent.appendChild(node);
    return node;
  }
  var labels = { idle: '请导入资料并填写编写要求。', queued: '任务已排队。', running: '正在编写，可关闭窗格后继续查询。', succeeded: '编写完成，请核对出处及待补充项。', failed: '编写未完成。', cancelled: '任务已取消。' };
  root.textContent = '';
  if (view.catalogLabel || (view.catalogSummary && view.catalogSummary.totalDocuments)) {
    var catText = view.catalogLabel || ('已导入 ' + view.catalogSummary.totalDocuments + '/5 份资料，合计 ' + (view.catalogSummary.totalCharacters || 0).toLocaleString() + '/100,000 字');
    append(root, 'p', catText, 'material-composer-catalog');
  }
  append(root, 'p', labels[view.status] || '', 'material-composer-status');
  if (view.phaseLabel) append(root, 'p', view.phaseLabel, 'material-composer-phase');
  if (view.error) append(root, 'p', String(view.error), 'material-composer-error');
  if (!view.result) return;
  view.result.paragraphs.forEach(function (paragraph, index) {
    var row = append(root, 'section', '', 'material-composer-paragraph');
    append(row, 'p', paragraph.text, 'material-composer-body');
    var sources = append(row, 'aside', '', 'material-composer-sources');
    append(sources, 'h4', '第 ' + (index + 1) + ' 段出处');
    paragraph.sources.forEach(function (source) {
      append(sources, 'p', source.fileName + ' / ' + source.section + ' / ' + source.fragmentId);
      append(sources, 'blockquote', source.quote);
    });
    paragraph.missingItems.forEach(function (item) { append(sources, 'p', '待补充：' + item, 'material-composer-missing'); });
  });
  if (view.result.missingItems.length) {
    var missing = append(root, 'aside', '', 'material-composer-missing');
    append(missing, 'h4', '待补充项');
    view.result.missingItems.forEach(function (item) { append(missing, 'p', String(item)); });
  }
}
if (typeof window !== 'undefined') {
  window.createMaterialComposer = createMaterialComposer;
  window.renderMaterialComposer = renderMaterialComposer;
}
