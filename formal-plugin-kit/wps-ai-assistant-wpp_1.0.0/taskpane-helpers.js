(function (global) {
  "use strict";

  function safeCall(fn, thisArg, args) {
    if (typeof fn !== "function") {
      return undefined;
    }
    try {
      return fn.apply(thisArg, args || []);
    } catch (error) {
      return undefined;
    }
  }

  function safeRead(object, key) {
    if (!object) {
      return undefined;
    }
    try {
      return object[key];
    } catch (error) {
      return undefined;
    }
  }

  function resolveValue(value, thisArg) {
    return typeof value === "function" ? safeCall(value, thisArg) : value;
  }

  function resolveScalarValue(value, depth) {
    var resolved = typeof value === "function" ? safeCall(value, null) : value;
    var keys;
    var index;
    var nested;
    var primitive;
    depth = depth || 0;
    if (typeof resolved === "undefined" || resolved === null) {
      return resolved;
    }
    if (typeof resolved === "string" || typeof resolved === "number" || typeof resolved === "boolean") {
      return resolved;
    }
    if (depth >= 3 || Array.isArray(resolved) || typeof resolved !== "object") {
      return undefined;
    }
    keys = ["value", "Value", "text", "Text"];
    for (index = 0; index < keys.length; index += 1) {
      nested = safeRead(resolved, keys[index]);
      if (typeof nested !== "undefined" && nested !== null) {
        return resolveScalarValue(nested, depth + 1);
      }
    }
    if (typeof resolved.valueOf === "function" && resolved.valueOf !== Object.prototype.valueOf) {
      primitive = safeCall(resolved.valueOf, resolved);
      if (primitive !== resolved) {
        return resolveScalarValue(primitive, depth + 1);
      }
    }
    if (typeof resolved.toString === "function" && resolved.toString !== Object.prototype.toString) {
      primitive = safeCall(resolved.toString, resolved);
      if (primitive && primitive !== "[object Object]") {
        return primitive;
      }
    }
    return undefined;
  }

  function safeText(value, fallback) {
    var resolved = resolveScalarValue(value);
    if (typeof resolved === "undefined" || resolved === null) {
      return fallback || "";
    }
    return String(resolved).replace(/\r/g, "").trim();
  }

  function readNumber(value) {
    var resolved = resolveScalarValue(value);
    var numeric = Number(resolved);
    return isNaN(numeric) || numeric < 0 ? 0 : Math.floor(numeric);
  }

  function truncateText(text, maxLength) {
    var value = String(text || "");
    if (maxLength && value.length > maxLength) {
      return value.slice(0, maxLength);
    }
    return value;
  }

  function getCollectionCount(collection) {
    var count;
    if (!collection) {
      return 0;
    }
    count = resolveValue(safeRead(collection, "Count"), collection);
    if (typeof count === "undefined" || count === null || count === "") {
      count = resolveValue(safeRead(collection, "count"), collection);
    }
    if (typeof count === "undefined" || count === null || count === "") {
      count = safeRead(collection, "length");
    }
    return readNumber(count);
  }

  function getCollectionItem(collection, index) {
    var item;
    if (!collection || index < 1) {
      return null;
    }
    item = safeRead(collection, "Item") || safeRead(collection, "item");
    if (typeof item === "function") {
      return safeCall(item, collection, [index]) || null;
    }
    if (Array.isArray(collection)) {
      return collection[index - 1] || null;
    }
    return safeRead(collection, index) || safeRead(collection, index - 1) || null;
  }

  function getPresentation(app) {
    return resolveValue(safeRead(app, "ActivePresentation"), app) ||
      resolveValue(safeRead(app, "activePresentation"), app) ||
      null;
  }

  function getActiveSlide(app) {
    var activeWindow = resolveValue(safeRead(app, "ActiveWindow"), app) ||
      resolveValue(safeRead(app, "activeWindow"), app) || {};
    var view = resolveValue(safeRead(activeWindow, "View"), activeWindow) ||
      resolveValue(safeRead(activeWindow, "view"), activeWindow) || {};
    var slide = resolveValue(safeRead(view, "Slide"), view) ||
      resolveValue(safeRead(view, "slide"), view);
    var selection;
    var slideRange;
    if (slide) {
      return slide;
    }
    selection = resolveValue(safeRead(activeWindow, "Selection"), activeWindow) ||
      resolveValue(safeRead(activeWindow, "selection"), activeWindow) || {};
    slideRange = resolveValue(safeRead(selection, "SlideRange"), selection) ||
      resolveValue(safeRead(selection, "slideRange"), selection);
    return getCollectionItem(slideRange, 1);
  }

  function readTextRange(frame) {
    var textRange = frame && (
      resolveValue(safeRead(frame, "TextRange"), frame) ||
      resolveValue(safeRead(frame, "textRange"), frame)
    );
    return safeText(textRange && (safeRead(textRange, "Text") || safeRead(textRange, "text")));
  }

  function readShapeText(shape) {
    var frame = resolveValue(safeRead(shape, "TextFrame"), shape) ||
      resolveValue(safeRead(shape, "textFrame"), shape);
    var text = readTextRange(frame);
    if (text) {
      return text;
    }
    frame = resolveValue(safeRead(shape, "TextFrame2"), shape) ||
      resolveValue(safeRead(shape, "textFrame2"), shape);
    return readTextRange(frame);
  }

  function getSlideShapes(slide) {
    return resolveValue(safeRead(slide, "Shapes"), slide) ||
      resolveValue(safeRead(slide, "shapes"), slide) ||
      null;
  }

  function getExplicitTitleShape(shapes) {
    return resolveValue(safeRead(shapes, "Title"), shapes) ||
      resolveValue(safeRead(shapes, "title"), shapes) ||
      null;
  }

  function getShapeId(shape) {
    return safeText(safeRead(shape, "Id") || safeRead(shape, "ID") || safeRead(shape, "id"));
  }

  function getShapeName(shape) {
    return safeText(safeRead(shape, "Name") || safeRead(shape, "name"));
  }

  function getShapeMetric(shape, key) {
    var value = resolveScalarValue(safeRead(shape, key) || safeRead(shape, key.toLowerCase()));
    var numeric = Number(value);
    return isNaN(numeric) || numeric < 0 ? null : numeric;
  }

  function getPlaceholderType(shape) {
    var format = resolveValue(safeRead(shape, "PlaceholderFormat"), shape) ||
      resolveValue(safeRead(shape, "placeholderFormat"), shape);
    return readNumber(format && (safeRead(format, "Type") || safeRead(format, "type")));
  }

  function shapesMatch(left, right) {
    var leftId;
    var rightId;
    var leftName;
    var rightName;
    if (!left || !right) {
      return false;
    }
    if (left === right) {
      return true;
    }
    leftId = getShapeId(left);
    rightId = getShapeId(right);
    if (leftId && rightId && leftId === rightId) {
      return true;
    }
    leftName = getShapeName(left);
    rightName = getShapeName(right);
    return Boolean(leftName && rightName && leftName === rightName);
  }

  function readSlideTitleInfo(slide) {
    var shapes = getSlideShapes(slide);
    var titleShape = getExplicitTitleShape(shapes);
    var titleText = readShapeText(titleShape);
    var count;
    var index;
    var candidate;
    var candidateText;
    if (titleText) {
      count = getCollectionCount(shapes);
      for (index = 1; index <= count; index += 1) {
        candidate = getCollectionItem(shapes, index);
        if (shapesMatch(candidate, titleShape)) {
          return { text: titleText, shape: candidate, index: index };
        }
      }
      for (index = 1; index <= count; index += 1) {
        candidate = getCollectionItem(shapes, index);
        if (readShapeText(candidate) === titleText) {
          return { text: titleText, shape: candidate, index: index };
        }
      }
      return { text: titleText, shape: titleShape, index: 0 };
    }
    count = getCollectionCount(shapes);
    for (index = 1; index <= count; index += 1) {
      candidate = getCollectionItem(shapes, index);
      candidateText = readShapeText(candidate);
      if (candidateText && candidateText.length <= 200) {
        return { text: candidateText, shape: candidate, index: index };
      }
    }
    return { text: "", shape: null, index: 0 };
  }

  function buildSubtitleInfo(shape, index, maxLength) {
    var rawText = readShapeText(shape);
    return {
      text: truncateText(rawText, maxLength),
      shape: shape,
      index: index,
      truncated: Boolean(maxLength && rawText.length > maxLength)
    };
  }

  function readSlideSubtitleInfo(slide, titleInfo, maxLength) {
    var shapes = getSlideShapes(slide);
    var count = getCollectionCount(shapes);
    var candidates = [];
    var index;
    var shape;
    var text;
    var name;
    var titleTop = getShapeMetric(titleInfo.shape, "Top");
    var titleHeight = getShapeMetric(titleInfo.shape, "Height");
    var titleBottom;
    var maxGap;
    var maxHeight;
    var geometryCandidates;
    for (index = 1; index <= count; index += 1) {
      if (index === titleInfo.index) {
        continue;
      }
      shape = getCollectionItem(shapes, index);
      text = readShapeText(shape);
      if (!text) {
        continue;
      }
      candidates.push({
        shape: shape,
        index: index,
        text: text,
        name: getShapeName(shape),
        placeholderType: getPlaceholderType(shape),
        top: getShapeMetric(shape, "Top"),
        height: getShapeMetric(shape, "Height")
      });
    }
    for (index = 0; index < candidates.length; index += 1) {
      if (candidates[index].placeholderType === 4) {
        return buildSubtitleInfo(candidates[index].shape, candidates[index].index, maxLength);
      }
    }
    for (index = 0; index < candidates.length; index += 1) {
      name = candidates[index].name;
      if (name && /(副标题|副標題|subtitle)/i.test(name)) {
        return buildSubtitleInfo(candidates[index].shape, candidates[index].index, maxLength);
      }
    }
    if (titleTop === null || titleHeight === null) {
      return { text: "", shape: null, index: 0, truncated: false };
    }
    titleBottom = titleTop + titleHeight;
    maxGap = Math.max(titleHeight * 3, 120);
    maxHeight = Math.max(titleHeight * 2.5, 100);
    geometryCandidates = candidates.filter(function (candidate) {
      return candidate.text.length <= maxLength &&
        candidate.top !== null &&
        candidate.height !== null &&
        candidate.top >= titleBottom - 4 &&
        candidate.top - titleBottom <= maxGap &&
        candidate.height <= maxHeight;
    });
    geometryCandidates.sort(function (left, right) {
      var topDifference = left.top - right.top;
      return topDifference || left.index - right.index;
    });
    if (geometryCandidates.length) {
      return buildSubtitleInfo(
        geometryCandidates[0].shape,
        geometryCandidates[0].index,
        maxLength
      );
    }
    return { text: "", shape: null, index: 0, truncated: false };
  }

  function getSlideIndex(slide, slides) {
    var index = readNumber(safeRead(slide, "SlideIndex") || safeRead(slide, "slideIndex") || safeRead(slide, "Index"));
    var count;
    var candidateIndex;
    if (index) {
      return index;
    }
    count = getCollectionCount(slides);
    for (candidateIndex = 1; candidateIndex <= count; candidateIndex += 1) {
      if (getCollectionItem(slides, candidateIndex) === slide) {
        return candidateIndex;
      }
    }
    return 0;
  }

  function readAdjacentTitle(slides, slideIndex, offset, maxLength) {
    var targetIndex = slideIndex + offset;
    var count = getCollectionCount(slides);
    var info;
    if (targetIndex < 1 || targetIndex > count) {
      return { text: "", truncated: false };
    }
    info = readSlideTitleInfo(getCollectionItem(slides, targetIndex));
    return {
      text: truncateText(info.text, maxLength),
      truncated: Boolean(maxLength && info.text.length > maxLength)
    };
  }

  function collectBodyText(slide, excludedIndexes, limits) {
    var shapes = getSlideShapes(slide);
    var count = getCollectionCount(shapes);
    var blocks = [];
    var bodyLength = 0;
    var truncated = false;
    var index;
    var shape;
    var text;
    var block;
    var remaining;
    for (index = 1; index <= count; index += 1) {
      shape = getCollectionItem(shapes, index);
      if (excludedIndexes[index]) {
        continue;
      }
      text = readShapeText(shape);
      if (!text) {
        continue;
      }
      block = truncateText(text, limits.maxBlockLength);
      if (block.length < text.length) {
        truncated = true;
      }
      remaining = limits.maxBodyLength - bodyLength;
      if (remaining <= 0) {
        truncated = true;
        break;
      }
      if (block.length > remaining) {
        block = block.slice(0, remaining);
        truncated = true;
      }
      if (block) {
        blocks.push(block);
        bodyLength += block.length;
      }
      if (bodyLength >= limits.maxBodyLength && index < count) {
        truncated = true;
        break;
      }
    }
    return {
      blocks: blocks,
      bodyCharacterCount: bodyLength,
      truncated: truncated
    };
  }

  function extractPresentationSlide(app, options) {
    var limits = {
      maxTitleLength: readNumber(options && options.maxTitleLength) || 200,
      maxSubtitleLength: readNumber(options && options.maxSubtitleLength) || 300,
      maxBlockLength: readNumber(options && options.maxBlockLength) || 1000,
      maxBodyLength: readNumber(options && options.maxBodyLength) || 3000,
      maxAdjacentTitleLength: readNumber(options && options.maxAdjacentTitleLength) || 200
    };
    var presentation = getPresentation(app);
    var slide = getActiveSlide(app);
    var slides;
    var slideIndex;
    var titleInfo;
    var title;
    var subtitleInfo;
    var subtitle;
    var excludedIndexes;
    var body;
    var previous;
    var next;
    var truncated;
    if (!presentation) {
      throw new Error("请先打开演示文稿。");
    }
    if (!slide) {
      throw new Error("未能读取当前幻灯片。");
    }
    slides = resolveValue(safeRead(presentation, "Slides"), presentation) ||
      resolveValue(safeRead(presentation, "slides"), presentation) || null;
    slideIndex = getSlideIndex(slide, slides);
    if (!slideIndex) {
      throw new Error("未能识别当前幻灯片序号。");
    }
    titleInfo = readSlideTitleInfo(slide);
    title = truncateText(titleInfo.text, limits.maxTitleLength);
    subtitleInfo = readSlideSubtitleInfo(slide, titleInfo, limits.maxSubtitleLength);
    subtitle = subtitleInfo.text;
    excludedIndexes = {};
    if (titleInfo.index) {
      excludedIndexes[titleInfo.index] = true;
    }
    if (subtitleInfo.index) {
      excludedIndexes[subtitleInfo.index] = true;
    }
    body = collectBodyText(slide, excludedIndexes, {
      maxBlockLength: limits.maxBlockLength,
      maxBodyLength: Math.max(limits.maxBodyLength - subtitle.length, 0)
    });
    previous = readAdjacentTitle(slides, slideIndex, -1, limits.maxAdjacentTitleLength);
    next = readAdjacentTitle(slides, slideIndex, 1, limits.maxAdjacentTitleLength);
    truncated = body.truncated ||
      subtitleInfo.truncated ||
      title.length < titleInfo.text.length ||
      previous.truncated ||
      next.truncated;
    return {
      presentationId: safeText(safeRead(presentation, "Name") || safeRead(presentation, "name"), "active-presentation") || "active-presentation",
      scene: "ppt",
      slide: {
        index: slideIndex,
        title: title,
        subtitle: subtitle,
        textBlocks: body.blocks,
        previousTitle: previous.text,
        nextTitle: next.text,
        subtitleCharacterCount: subtitle.length,
        bodyCharacterCount: body.bodyCharacterCount,
        contentCharacterCount: subtitle.length + body.bodyCharacterCount,
        truncated: truncated
      }
    };
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderMarkdown(markdown) {
    return String(markdown || "")
      .split(/\n{2,}/)
      .map(function (block) {
        var escaped = escapeHtml(block).replace(/\n/g, "<br>");
        if (/^##\s+/.test(block)) {
          return "<h3>" + escaped.replace(/^##\s+/, "") + "</h3>";
        }
        return "<p>" + escaped + "</p>";
      })
      .join("");
  }

  function normalizeWorkflowProfiles(value) {
    var data = value && value.data ? value.data : value || {};
    var profiles = Array.isArray(data.profiles) ? data.profiles : [];
    return {
      taskType: safeText(data.taskType),
      activeProfileId: safeText(data.activeProfileId),
      profileCount: profiles.length,
      profiles: profiles.map(function (profile) {
        return {
          id: safeText(profile && profile.id),
          taskType: safeText(profile && profile.taskType),
          name: safeText(profile && profile.name),
          note: safeText(profile && profile.note),
          apiKeyRef: safeText(profile && profile.apiKeyRef),
          keyConfigured: Boolean(profile && profile.keyConfigured)
        };
      })
    };
  }

  function workflowProfileOptionState(profile, activeProfileId) {
    var item = profile || {};
    var active = Boolean(item.id && item.id === activeProfileId);
    var configured = Boolean(item.keyConfigured);
    var name = String(item.name || "未命名工作流");
    return {
      id: String(item.id || ""),
      label: (active ? "✓ " : "") + name + (configured ? "" : "（Key 未配置）"),
      active: active,
      disabled: !configured
    };
  }

  function validateWorkflowProfileDraft(draft, mode) {
    var value = draft || {};
    var name = String(value.name || "").trim();
    var note = String(value.note || "").trim();
    var apiKey = String(value.apiKey || "").trim();
    if (!name) {
      return { ok: false, field: "name", message: "请输入工作流名称。" };
    }
    if (name.length > 40) {
      return { ok: false, field: "name", message: "工作流名称不能超过 40 个字。" };
    }
    if (note.length > 200) {
      return { ok: false, field: "note", message: "工作流备注不能超过 200 个字。" };
    }
    if (mode === "create" && !apiKey) {
      return { ok: false, field: "apiKey", message: "请输入工作流 API Key。" };
    }
    return { ok: true, name: name, note: note, apiKey: apiKey };
  }

  function shouldActivateNewWorkflowProfile(profileCount, requested) {
    return Number(profileCount || 0) === 0 || Boolean(requested);
  }

  function buildPptSlidePlainText(result) {
    var data = result || {};
    var sections = [];
    var bullets = Array.isArray(data.bullets) ? data.bullets : [];
    if (safeText(data.suggestedTitle)) {
      sections.push(safeText(data.suggestedTitle));
    }
    if (bullets.length) {
      sections.push(bullets.map(function (item, index) {
        return (index + 1) + ". " + safeText(item);
      }).join("\n"));
    }
    if (safeText(data.conclusion)) {
      sections.push(safeText(data.conclusion));
    }
    return sections.join("\n\n");
  }

  function buildPptSlideMarkdown(result) {
    var data = result || {};
    var bullets = Array.isArray(data.bullets) ? data.bullets : [];
    return [
      "## 建议标题",
      safeText(data.suggestedTitle) || "未返回建议标题",
      "",
      "## 核心要点",
      bullets.length ? bullets.map(function (item) {
        return "- " + safeText(item);
      }).join("\n") : "未返回核心要点",
      "",
      "## 本页结论",
      safeText(data.conclusion) || "未返回本页结论"
    ].join("\n");
  }

  function validatePptDocumentFile(file) {
    var name = safeText(file && file.name);
    var size = Number(file && file.size) || 0;
    var match = name.toLowerCase().match(/\.([^.]+)$/);
    var extension = match ? match[1] : "";
    if (extension !== "md" && extension !== "docx") {
      return {
        valid: false,
        code: "PPT_DOCUMENT_TYPE_UNSUPPORTED",
        message: "仅支持 Markdown（.md）和 Word（.docx）文档。"
      };
    }
    if (size < 1 || size > 10 * 1024 * 1024) {
      return {
        valid: false,
        code: "PPT_DOCUMENT_TOO_LARGE",
        message: "文件大小必须在 1 字节至 10 MB 之间。"
      };
    }
    return {
      valid: true,
      extension: extension,
      mimeType: extension === "md"
        ? "text/markdown"
        : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    };
  }

  function normalizePptDocumentSlide(value, fallbackIndex) {
    var slide = value || {};
    var index = Number(slide.index);
    var bullets = Array.isArray(slide.bullets) ? slide.bullets : [];
    if (!isFinite(index) || index < 1) {
      index = fallbackIndex || 1;
    }
    return {
      index: Math.floor(index),
      role: safeText(slide.role),
      title: safeText(slide.title),
      subtitle: safeText(slide.subtitle),
      bullets: bullets.map(function (item) { return safeText(item); }).filter(Boolean),
      conclusion: safeText(slide.conclusion),
      layoutSuggestion: safeText(slide.layoutSuggestion),
      visualSuggestion: safeText(slide.visualSuggestion)
    };
  }

  function normalizePptDocumentResult(value) {
    var data = value || {};
    var slides = Array.isArray(data.slides) ? data.slides : [];
    var requestedCount = Number(data.recommendedSlideCount);
    return {
      resultType: "document",
      deckTitle: safeText(data.deckTitle),
      documentSummary: safeText(data.documentSummary),
      globalStyleAdvice: safeText(data.globalStyleAdvice),
      recommendedSlideCount: isFinite(requestedCount) && requestedCount > 0
        ? Math.floor(requestedCount)
        : null,
      slides: slides.map(function (slide, index) {
        return normalizePptDocumentSlide(slide, index + 1);
      }).sort(function (left, right) {
        return left.index - right.index;
      }),
      plainText: safeText(data.plainText),
      rawAnswer: safeText(data.rawAnswer),
      parseFallbackReason: safeText(data.parseFallbackReason),
      provider: safeText(data.provider)
    };
  }

  function hasStructuredPptDocumentResult(result) {
    return Boolean(
      !result.parseFallbackReason &&
      (result.deckTitle ||
        result.documentSummary ||
        result.globalStyleAdvice ||
        result.slides.length)
    );
  }

  function buildPptDocumentSlidePlainText(value) {
    var slide = normalizePptDocumentSlide(value, 1);
    var lines = [];
    var heading = "第 " + slide.index + " 页";
    if (slide.role) {
      heading += "（" + slide.role + "）";
    }
    lines.push(heading);
    if (slide.title) {
      lines.push("标题：" + slide.title);
    }
    if (slide.subtitle) {
      lines.push("副标题：" + slide.subtitle);
    }
    if (slide.bullets.length) {
      lines.push("正文：\n" + slide.bullets.map(function (item, index) {
        return (index + 1) + ". " + item;
      }).join("\n"));
    }
    if (slide.conclusion) {
      lines.push("结论：" + slide.conclusion);
    }
    if (slide.layoutSuggestion) {
      lines.push("版式建议：" + slide.layoutSuggestion);
    }
    if (slide.visualSuggestion) {
      lines.push("视觉建议：" + slide.visualSuggestion);
    }
    return lines.join("\n");
  }

  function buildPptDocumentOutline(value) {
    var result = normalizePptDocumentResult(value);
    var lines;
    if (!hasStructuredPptDocumentResult(result)) {
      return result.plainText || result.rawAnswer;
    }
    lines = result.slides.map(function (slide) {
      var line = slide.index + ". " + (slide.title || "未命名页面");
      if (slide.role) {
        line += "（" + slide.role + "）";
      }
      if (slide.subtitle) {
        line += " - " + slide.subtitle;
      }
      return line;
    });
    if (result.deckTitle) {
      lines.unshift(result.deckTitle);
    }
    return lines.join("\n");
  }

  function buildPptDocumentPlainText(value) {
    var result = normalizePptDocumentResult(value);
    var sections = [];
    if (!hasStructuredPptDocumentResult(result)) {
      return result.plainText || result.rawAnswer;
    }
    if (result.deckTitle) {
      sections.push("演示文稿标题：" + result.deckTitle);
    }
    if (result.documentSummary) {
      sections.push("文档摘要：" + result.documentSummary);
    }
    if (result.globalStyleAdvice) {
      sections.push("全局风格建议：" + result.globalStyleAdvice);
    }
    if (result.slides.length) {
      sections.push(result.slides.map(buildPptDocumentSlidePlainText).join("\n\n"));
    }
    return sections.join("\n\n");
  }

  global.WpsAiPptHelpers = {
    extractPresentationSlide: extractPresentationSlide,
    truncateText: truncateText,
    renderMarkdown: renderMarkdown,
    escapeHtml: escapeHtml,
    normalizeWorkflowProfiles: normalizeWorkflowProfiles,
    workflowProfileOptionState: workflowProfileOptionState,
    validateWorkflowProfileDraft: validateWorkflowProfileDraft,
    shouldActivateNewWorkflowProfile: shouldActivateNewWorkflowProfile,
    buildPptSlideMarkdown: buildPptSlideMarkdown,
    buildPptSlidePlainText: buildPptSlidePlainText,
    validatePptDocumentFile: validatePptDocumentFile,
    normalizePptDocumentResult: normalizePptDocumentResult,
    buildPptDocumentPlainText: buildPptDocumentPlainText,
    buildPptDocumentOutline: buildPptDocumentOutline,
    buildPptDocumentSlidePlainText: buildPptDocumentSlidePlainText
  };
}(window));
