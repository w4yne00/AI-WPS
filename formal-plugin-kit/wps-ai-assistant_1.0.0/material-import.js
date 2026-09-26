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
    var reading = response && response.data ? response.data : response;
    if (settings.root) {
      renderMaterialReading(settings.root, reading || {});
    }
    return reading;
  });
}

function renderMaterialReading(root, reading) {
  var data = reading || {};
  var lines = [];
  var blocks = data.blocks || [];
  var index;
  lines.push("读取结果不宣称理解全部内容。");
  lines.push(data.disclosure || "图片文字和嵌入附件未读取，不宣称理解全部内容。");
  lines.push("本阶段字数统计和文件字节上限是实施参数，不是已确认的产品数值。");
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

if (typeof window !== "undefined") {
  window.submitMaterialImport = submitMaterialImport;
  window.renderMaterialReading = renderMaterialReading;
  window.readMaterialFile = readMaterialFile;
}
