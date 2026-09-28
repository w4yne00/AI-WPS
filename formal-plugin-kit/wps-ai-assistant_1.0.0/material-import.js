function submitMaterialImport(options) {
  var settings = options || {};
  var request = settings.request;
  if (typeof request !== "function") {
    return Promise.reject(new Error("资料导入请求入口不可用。"));
  }
  return Promise.resolve(request("/word/materials", {
    fileName: settings.fileName || "",
    mimeType: settings.mimeType || "",
    sizeBytes: settings.sizeBytes || 0,
    contentBase64: settings.contentBase64 || "",
    documentSessionId: settings.documentSessionId || ""
  })).then(function (response) {
    return finishNativeMaterialConversion(settings, response);
  }).then(function (response) {
    var reading = response && response.data ? response.data : response;
    if (settings.root) {
      renderMaterialReading(settings.root, reading || {});
    }
    return reading;
  });
}

async function finishNativeMaterialConversion(settings, response) {
  var stage = response && response.data ? response.data : response;
  if (!stage || !stage.conversionRequired) return response;
  var request = settings.request;
  try {
    var app = settings.application;
    if (!app || !app.Documents || typeof app.Documents.Open !== "function") {
      throw new Error("当前宿主无法调用 WPS 的 DOC 转换接口，请在 WPS 中另存为 DOCX 后上传。");
    }
    var active = app.ActiveDocument;
    var security = app.AutomationSecurity;
    var alerts = app.DisplayAlerts;
    var hostOptions = app.Options;
    if ([1, 2, 3].indexOf(security) < 0 || !hostOptions || typeof hostOptions.UpdateLinksAtOpen !== "boolean") {
      throw new Error("当前 WPS 无法核验宏与外链保护，已停止 DOC 转换。请手动另存为 DOCX 后上传。");
    }
    var updateLinks = hostOptions.UpdateLinksAtOpen;
    var temporary = null;
    window.materialConversionActive = true;
    try {
      app.AutomationSecurity = 3;
      if (app.AutomationSecurity !== 3) throw new Error("无法禁止 DOC 宏执行，已停止转换。");
      hostOptions.UpdateLinksAtOpen = false;
      if (hostOptions.UpdateLinksAtOpen !== false) throw new Error("无法禁止 DOC 外链更新，已停止转换。");
      app.DisplayAlerts = 0;
      temporary = app.Documents.Open(stage.sourcePath, false, true, false, "", "", false, "", "", undefined, undefined, false);
      if (!temporary || typeof temporary.SaveAs2 !== "function") throw new Error("WPS 未提供 DOC 转换能力。");
      temporary.SaveAs2(stage.targetPath, 12, false, "", false);
    } finally {
      try {
        if (temporary) temporary.Close(0);
      } finally {
        try {
          app.AutomationSecurity = security;
          hostOptions.UpdateLinksAtOpen = updateLinks;
          app.DisplayAlerts = alerts;
          if (active && typeof active.Activate === "function") active.Activate();
        } finally {
          window.materialConversionActive = false;
        }
      }
    }
    return await request("/word/materials", {conversionId:stage.conversionId, documentSessionId:settings.documentSessionId});
  } catch (error) {
    try {
      await request("/word/materials", {conversionId:stage.conversionId, documentSessionId:settings.documentSessionId, cancelConversion:true});
    } catch (cleanupError) {
      throw new Error((error.message || "DOC 转换失败") + "；临时副本清理未确认，请重试。");
    }
    throw error;
  }
}

function renderMaterialReading(root, reading) {
  var data = reading || {};
  var lines = [];
  var blocks = data.blocks || [];
  var index;
  if (data.fullReading) {
    lines.push("原图 " + (data.fullReading.imageCount || 0) + " 张；" + (data.fullReading.complete ? "全部支持内容已读取" : "存在未读取对象，暂不能生成"));
    var unreadLabels = {vector_drawing:"原生图形或连线", drawing:"绘图对象", oMath:"公式", image:"缺失的图片", unsupported_image:"不支持的图片格式", embedded_attachment:"嵌入附件", object:"嵌入对象", AlternateContent:"无法完整读取的复合内容", missing_note:"缺失的脚注或尾注", del:"尚未确认的修订", ins:"尚未确认的修订", chart:"原生图表", altChunk:"外部嵌入内容"};
    (data.fullReading.unreadObjects || []).forEach(function (item) { lines.push("未读取：" + (unreadLabels[item.kind] || "未识别对象")); });
  }
  if (data.catalogSummary && data.catalogSummary.totalDocuments) {
    var totalChars = typeof data.catalogSummary.totalCharacters === 'number' ? data.catalogSummary.totalCharacters.toLocaleString() : '0';
    lines.push("已导入 " + data.catalogSummary.totalDocuments + "/5 份资料，合计 " + totalChars + "/100,000 字。");
  }
  for (index = 0; index < blocks.length; index += 1) {
    lines.push(blockLine(blocks[index]));
  }
  (data.fragments || []).forEach(function (fragment) {
    var source = fragment.source || {};
    if (source.part) {
      lines.push("出处 " + source.part + " #" + source.blockIndex + " " + (fragment.text || ""));
    }
  });
  (data.unreadRegions || []).forEach(function (region) {
    if (data.fullReading && region.kind === "image") return;
    lines.push((region.message || "未读取") + " " + (region.count || 0));
  });
  root.textContent = lines.join("\n");
}

function blockLine(block) {
  var source = block.source || {};
  var locator = source.part ? " [" + source.part + "#" + source.blockIndex + "]" : "";
  if (block.kind === "heading") {
    return "标题" + (block.level || "") + " " + block.text + locator;
  }
  if (block.kind === "list_item") {
    return "列表 " + block.text + locator;
  }
  if (block.kind === "table") {
    return "表格 " + (block.rows || []).map(function (row) {
      return row.join(" | ");
    }).join(" / ") + locator;
  }
  return (block.text || "") + locator;
}

function readMaterialFile(file) {
  return new Promise(function (resolve, reject) {
    var reader = new FileReader();
    reader.onload = function () {
      var value = String(reader.result || "");
      var marker = value.indexOf(",");
      resolve(marker >= 0 ? value.slice(marker + 1) : value);
    };
    reader.onerror = function () {
      reject(new Error("资料文件读取失败。"));
    };
    reader.readAsDataURL(file);
  });
}

function submitMaterialUpdate(options) {
  var settings = options || {};
  var request = settings.request;
  if (typeof request !== "function") {
    return Promise.reject(new Error("资料更新请求入口不可用。"));
  }
  var materialId = settings.materialId;
  if (!materialId) {
    return Promise.reject(new Error("缺少资料编号。"));
  }
  return Promise.resolve(request("/word/materials/" + encodeURIComponent(materialId), {
    fileName: settings.fileName || "",
    mimeType: settings.mimeType || "",
    sizeBytes: settings.sizeBytes || 0,
    contentBase64: settings.contentBase64 || "",
    documentSessionId: settings.documentSessionId || ""
  }, { method: "PUT" })).then(function (response) {
    return finishNativeMaterialConversion(settings, response);
  }).then(function (response) {
    return response && response.data ? response.data : response;
  });
}

function submitMaterialDelete(options) {
  var settings = options || {};
  var request = settings.request;
  if (typeof request !== "function") {
    return Promise.reject(new Error("资料移除请求入口不可用。"));
  }
  var materialId = settings.materialId;
  if (!materialId) {
    return Promise.reject(new Error("缺少资料编号。"));
  }
  var query = "?documentSessionId=" + encodeURIComponent(settings.documentSessionId || "");
  return Promise.resolve(request("/word/materials/" + encodeURIComponent(materialId) + query, null, { method: "DELETE" })).then(function (response) {
    return response && response.data ? response.data : response;
  });
}

if (typeof window !== "undefined") {
  window.submitMaterialImport = submitMaterialImport;
  window.submitMaterialUpdate = submitMaterialUpdate;
  window.submitMaterialDelete = submitMaterialDelete;
  window.renderMaterialReading = renderMaterialReading;
  window.readMaterialFile = readMaterialFile;
}
