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
        catalogRequestVersion: 0,
        catalogLabel: formatCatalogLabel(catalogSummary),
        jobId: data.jobId || '',
        clientJobId: data.clientJobId || '',
        input: data.input || {},
        conflicts: data.conflicts || [],
        conflictResolutions: data.conflictResolutions || [],
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
      input: s.input,
      conflicts: s.conflicts,
      conflictResolutions: s.conflictResolutions
    }));
  }
  function show(s) {
    if (options.getSessionId() === s.documentSessionId) options.render(Object.assign({}, s));
  }
  function validResult(r, id) {
    return r && r.taskType === 'word.material_composer' && r.documentSessionId === id && typeof r.plainText === 'string' && r.plainText.trim() && Array.isArray(r.missingItems) && (!r.unverifiedItems || Array.isArray(r.unverifiedItems)) && Array.isArray(r.paragraphs) && r.paragraphs.length > 0 && r.paragraphs.every(function (p) {
      return typeof p.text === 'string' && p.text.trim() && Array.isArray(p.missingItems) && (!p.unverifiedItems || Array.isArray(p.unverifiedItems)) && Array.isArray(p.sources) && p.sources.every(function (source) {
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
    var phaseLabels = {
      preparing: '正在校验任务与资料...',
      extracting: '正在检索资料原文...',
      provider_processing: '正在依据原文编写章节草稿...',
      parsing: '正在核对草稿出处与待补充项...'
    };
    s.phaseLabel = job.phaseLabel || phaseLabels[s.phase] || '';
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
  async function restoreCatalog(s) {
    var version = ++s.catalogRequestVersion;
    var response = await options.request('/word/materials/catalog?documentSessionId=' + encodeURIComponent(s.documentSessionId), undefined, { method: 'GET' });
    if (version !== s.catalogRequestVersion) return;
    var catalog = response && response.success === true && response.data;
    if (!catalog || !Array.isArray(catalog.documents) || !Array.isArray(catalog.toc) || typeof catalog.totalDocuments !== 'number' || typeof catalog.totalCharacters !== 'number') {
      throw new Error('资料目录返回格式不正确，请重试查询。');
    }
    s.catalogSummary = catalog;
    s.catalogLabel = formatCatalogLabel(catalog);
    s.materialIds = catalog.documents.map(function (item) { return item.materialId; }).filter(Boolean);
    s.materialId = s.materialIds[s.materialIds.length - 1] || '';
    persist(s);
    show(s);
  }
  return {
    setMaterial: function (reading) {
      var s = stateFor(reading.documentSessionId || options.getSessionId());
      if (s.busy || active(s)) return;
      s.catalogRequestVersion += 1;
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
      s.conflicts = [];
      s.conflictResolutions = [];
      s.jobId = '';
      s.clientJobId = '';
      s.result = null;
      s.status = 'idle';
      s.error = '';
      persist(s);
      show(s);
    },
    checkConflicts: async function (input) {
      var s = current();
      var sectionTitle = (input && input.sectionTitle) || (s.input && s.input.sectionTitle) || '';
      var instruction = (input && input.instruction) || (s.input && s.input.instruction) || '';
      var userFacts = (input && typeof input.userFacts === 'string') ? input.userFacts : ((s.input && s.input.userFacts) || '');
      var mids = (s.materialIds && s.materialIds.length) ? s.materialIds : (s.materialId ? [s.materialId] : []);
      var body = {
        documentSessionId: s.documentSessionId,
        sectionTitle: sectionTitle,
        instruction: instruction,
        userFacts: userFacts
      };
      if (mids.length) {
        body.materialIds = mids;
        body.materialId = mids[0];
      } else if (s.materialId) {
        body.materialId = s.materialId;
      }
      var res = await options.request('/word/material-composer/conflicts', body, { method: 'POST' });
      var data = (res && res.data) || res || {};
      s.conflicts = data.conflicts || [];
      persist(s);
      show(s);
      return s.conflicts;
    },
    resolveConflict: function (conflictId, candidateId, chosenValue) {
      var s = current();
      if (!s.conflictResolutions) s.conflictResolutions = [];
      s.conflictResolutions = s.conflictResolutions.filter(function (r) { return r.conflictId !== conflictId; });
      s.conflictResolutions.push({
        conflictId: conflictId,
        chosenCandidateId: candidateId,
        chosenValue: chosenValue,
        resolution: 'use_candidate'
      });
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
      if (!retryingUncertain) {
        s.input = {
          sectionTitle: selectedInput.sectionTitle,
          instruction: selectedInput.instruction
        };
        var uFacts = typeof selectedInput.userFacts === 'string' ? selectedInput.userFacts : ((s.input && s.input.userFacts) || '');
        if (uFacts) {
          s.input.userFacts = uFacts;
        }
        if (selectedInput.conflictResolutions && Array.isArray(selectedInput.conflictResolutions)) {
          s.conflictResolutions = selectedInput.conflictResolutions;
        }
      }
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
      if (s.input.userFacts) {
        body.userFacts = s.input.userFacts;
      }
      if (s.conflictResolutions && s.conflictResolutions.length) {
        body.conflictResolutions = s.conflictResolutions;
      }
      if (mids.length) {
        body.materialIds = mids;
        body.materialId = mids[0];
      } else if (s.materialId) {
        body.materialId = s.materialId;
      }
      await execute(s, '/word/material-composer/jobs', body, 'POST');
    },
    refresh: refresh,
    restore: async function () {
      var s = current();
      show(s);
      try { await restoreCatalog(s); }
      catch (error) { s.error = error.message || '资料目录查询失败，请重试。'; show(s); }
      if (s.jobId || s.clientJobId) await refresh();
    },
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
      var hasMissing = (s.result.missingItems && s.result.missingItems.length > 0) ||
        (s.result.paragraphs && s.result.paragraphs.some(function (p) { return p.missingItems && p.missingItems.length > 0; }));
      if (hasMissing && target && target.confirmedMissingItems === false) {
        throw new Error('草稿中包含待补充项，已取消写入。请补充或确认直接使用草稿。');
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
function renderMaterialComposer(root, view, onSelectChapter, onResolveConflict) {
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
  var catalog = view.catalogSummary;
  if (catalog && Array.isArray(catalog.documents) && catalog.documents.length) {
    var directory = append(root, 'details', '', 'material-composer-toc');
    append(directory, 'summary', '资料目录（' + catalog.documents.length + ' 份）');
    catalog.documents.forEach(function (material) {
      var file = append(directory, 'section', '', 'material-composer-toc-file');
      append(file, 'strong', material.fileName || '未命名资料');
      (catalog.toc || []).filter(function (entry) { return entry.materialId === material.materialId; }).forEach(function (entry) {
        var level = Math.max(1, Math.min(6, Number(entry.headingLevel) || 1));
        var chapter = append(file, 'button', entry.sectionTitle, 'ghost-action material-composer-toc-chapter material-composer-toc-level-' + level);
        chapter.type = 'button';
        chapter.disabled = view.busy || view.status === 'queued' || view.status === 'running' || typeof onSelectChapter !== 'function';
        if (!chapter.disabled) chapter.addEventListener('click', function () { onSelectChapter(entry.sectionTitle); });
      });
    });
  }

  if (view.conflicts && view.conflicts.length) {
    var conflictSec = append(root, 'section', '', 'material-composer-conflicts');
    append(conflictSec, 'h4', '资料与补充事实冲突（需手动选择采纳依据）：');
    append(conflictSec, 'small', '资料之间及补充事实之间的差异由您手动选择，系统不按文件时间自动决定。');
    view.conflicts.forEach(function (conflict) {
      var card = append(conflictSec, 'div', '', 'material-composer-conflict-card');
      append(card, 'strong', conflict.description || conflict.factType);
      (conflict.candidates || []).forEach(function (cand) {
        var isChosen = (view.conflictResolutions || []).some(function (cr) {
          return cr.conflictId === conflict.id && cr.chosenCandidateId === cand.candidateId;
        });
        var label = '[' + (cand.sourceType === 'user' ? '用户补充事实' : cand.sourceName) + '] ' + cand.value;
        var btn = append(card, 'button', label, 'ghost-action material-composer-conflict-choice' + (isChosen ? ' active' : ''));
        btn.type = 'button';
        if (typeof onResolveConflict === 'function') {
          btn.addEventListener('click', function () {
            onResolveConflict(conflict.id, cand.candidateId, cand.value);
          });
        }
      });
    });
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
      var srcText = (source.sourceType === 'user' ? '[用户补充事实] ' : '') + source.fileName + ' / ' + source.section + ' / ' + source.fragmentId;
      append(sources, 'p', srcText);
      append(sources, 'blockquote', source.quote);
    });
    paragraph.missingItems.forEach(function (item) { append(sources, 'p', '待补充：' + item, 'material-composer-missing'); });
    if (paragraph.unverifiedItems && paragraph.unverifiedItems.length) {
      paragraph.unverifiedItems.forEach(function (item) {
        append(sources, 'p', '待核对（无依据）：' + item, 'material-composer-unverified');
      });
    }
  });

  if (view.result.unverifiedItems && view.result.unverifiedItems.length) {
    var unverified = append(root, 'aside', '', 'material-composer-unverified');
    append(unverified, 'h4', '待核对关键事实（数字/日期/名称/责任/承诺）');
    append(unverified, 'small', '已标出无原文依据内容；AI 核对不伪造出处，亦不宣称发现全部冲突，请逐项核对。');
    view.result.unverifiedItems.forEach(function (item) { append(unverified, 'p', '待核对：' + String(item)); });
  }

  if (view.result.missingItems.length) {
    var missing = append(root, 'aside', '', 'material-composer-missing');
    append(missing, 'h4', '待补充项');
    append(missing, 'small', '正文中已显示“〔待补充：具体信息〕”，可确认直接使用草稿或补充信息后写入。');
    view.result.missingItems.forEach(function (item) { append(missing, 'p', '待补充：' + String(item)); });
  }
}
if (typeof window !== 'undefined') {
  window.createMaterialComposer = createMaterialComposer;
  window.renderMaterialComposer = renderMaterialComposer;
}
