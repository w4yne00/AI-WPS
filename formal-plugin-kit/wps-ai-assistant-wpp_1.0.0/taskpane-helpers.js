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

  function readStructureTitleInfo(slide) {
    var shapes = getSlideShapes(slide);
    var explicitTitle = getExplicitTitleShape(shapes);
    var explicitTitleText;
    var count;
    var index;
    var candidate;
    var name;
    var placeholderType;
    if (explicitTitle) {
      explicitTitleText = readShapeText(explicitTitle);
      count = getCollectionCount(shapes);
      for (index = 1; index <= count; index += 1) {
        candidate = getCollectionItem(shapes, index);
        if (shapesMatch(candidate, explicitTitle)) {
          return { text: explicitTitleText, shape: candidate, index: index };
        }
      }
      return { text: explicitTitleText, shape: explicitTitle, index: 0 };
    }
    count = getCollectionCount(shapes);
    for (index = 1; index <= count; index += 1) {
      candidate = getCollectionItem(shapes, index);
      placeholderType = getPlaceholderType(candidate);
      name = getShapeName(candidate);
      if (placeholderType === 1 || placeholderType === 3 ||
          (name && /(主标题|主標題|title)/i.test(name) && !/(副标题|副標題|subtitle)/i.test(name))) {
        return {
          text: readShapeText(candidate),
          shape: candidate,
          index: index
        };
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

  function readExplicitSubtitleInfo(shapes, titleIndex, maxLength) {
    var count = getCollectionCount(shapes);
    var index;
    var shape;
    var info;
    var name;
    for (index = 1; index <= count; index += 1) {
      if (index === titleIndex) {
        continue;
      }
      shape = getCollectionItem(shapes, index);
      if (getPlaceholderType(shape) === 4) {
        info = buildSubtitleInfo(shape, index, maxLength);
        if (info.text) {
          return info;
        }
      }
    }
    for (index = 1; index <= count; index += 1) {
      if (index === titleIndex) {
        continue;
      }
      shape = getCollectionItem(shapes, index);
      name = getShapeName(shape);
      if (name && /(副标题|副標題|subtitle)/i.test(name)) {
        info = buildSubtitleInfo(shape, index, maxLength);
        if (info.text) {
          return info;
        }
      }
    }
    return null;
  }

  function readSlideSubtitleInfo(slide, titleInfo, maxLength) {
    var shapes = getSlideShapes(slide);
    var count = getCollectionCount(shapes);
    var candidates = [];
    var explicitInfo = readExplicitSubtitleInfo(shapes, titleInfo.index, maxLength);
    var index;
    var shape;
    var text;
    var titleTop = getShapeMetric(titleInfo.shape, "Top");
    var titleHeight = getShapeMetric(titleInfo.shape, "Height");
    var titleBottom;
    var maxGap;
    var maxHeight;
    var geometryCandidates;
    if (explicitInfo) {
      return explicitInfo;
    }
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
        top: getShapeMetric(shape, "Top"),
        height: getShapeMetric(shape, "Height")
      });
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

  function readStructureSubtitleInfo(slide, titleInfo, maxLength) {
    var shapes = getSlideShapes(slide);
    return readExplicitSubtitleInfo(shapes, titleInfo.index, maxLength) ||
      { text: "", shape: null, index: 0, truncated: false };
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

  function structureExtractionError(code, message) {
    var error = new Error(message);
    error.code = code;
    return error;
  }

  function readStructurePageNumber(value, label) {
    var resolved = resolveScalarValue(value);
    var numeric;
    if (typeof resolved === "undefined" || resolved === null || resolved === "") {
      return 0;
    }
    numeric = Number(resolved);
    if (!isFinite(numeric) || Math.floor(numeric) !== numeric || numeric < 1) {
      throw structureExtractionError(
        "PPT_STRUCTURE_PAGE_INVALID",
        label + "必须为正整数。"
      );
    }
    return numeric;
  }

  function extractPresentationStructure(app, startSlide, endSlide, options) {
    var limits = {
      maxSlides: readNumber(options && options.maxSlides) || 60,
      maxTitleLength: readNumber(options && options.maxTitleLength) || 200,
      maxSubtitleLength: readNumber(options && options.maxSubtitleLength) || 300,
      maxFallbackLength: readNumber(options && options.maxFallbackLength) || 120,
      maxFallbackSlides: readNumber(options && options.maxFallbackSlides) || 10
    };
    var presentation = getPresentation(app);
    var slides;
    var totalSlides;
    var explicitStart = readStructurePageNumber(startSlide, "起始页");
    var explicitEnd = readStructurePageNumber(endSlide, "结束页");
    var start = explicitStart;
    var end = explicitEnd;
    var fallbackCount = 0;
    var extracted = [];
    var index;
    var currentSlide;
    var titleInfo;
    var subtitleInfo;
    var excludedIndexes;
    var body;
    var bodyFallbackOmitted;
    if (!presentation) {
      throw structureExtractionError("PPT_STRUCTURE_PRESENTATION_REQUIRED", "请先打开演示文稿。");
    }
    slides = resolveValue(safeRead(presentation, "Slides"), presentation) ||
      resolveValue(safeRead(presentation, "slides"), presentation) || null;
    totalSlides = getCollectionCount(slides);
    if (!totalSlides) {
      throw structureExtractionError("PPT_STRUCTURE_SLIDES_REQUIRED", "当前演示文稿没有可审查的幻灯片。");
    }
    if (totalSlides > limits.maxSlides && (!explicitStart || !explicitEnd)) {
      throw structureExtractionError(
        "PPT_STRUCTURE_EXPLICIT_RANGE_REQUIRED",
        "演示文稿超过 60 页，请明确填写起始页和结束页后再审查。"
      );
    }
    if (!start) {
      start = 1;
    }
    if (!end) {
      end = totalSlides;
    }
    if (end < start) {
      throw structureExtractionError(
        "PPT_STRUCTURE_RANGE_REVERSED",
        "结束页不能小于起始页。"
      );
    }
    if (start > totalSlides || end > totalSlides) {
      throw structureExtractionError(
        "PPT_STRUCTURE_PAGE_OUT_OF_RANGE",
        "起止页必须在 1 至 " + totalSlides + " 页之间。"
      );
    }
    if (end - start + 1 > limits.maxSlides) {
      throw structureExtractionError(
        "PPT_STRUCTURE_RANGE_TOO_LARGE",
        "单次结构审查最多支持 60 页，请明确选择不超过 60 页的起止范围。"
      );
    }

    for (index = start; index <= end; index += 1) {
      currentSlide = getCollectionItem(slides, index);
      if (!currentSlide) {
        throw structureExtractionError(
          "PPT_STRUCTURE_SLIDE_UNREADABLE",
          "无法读取第 " + index + " 页幻灯片，请确认演示文稿状态后重试。"
        );
      }
      titleInfo = readStructureTitleInfo(currentSlide);
      subtitleInfo = readStructureSubtitleInfo(
        currentSlide,
        titleInfo,
        limits.maxSubtitleLength
      );
      body = "";
      bodyFallbackOmitted = false;
      if (!titleInfo.text) {
        if (fallbackCount >= limits.maxFallbackSlides) {
          bodyFallbackOmitted = true;
        } else {
          fallbackCount += 1;
          excludedIndexes = {};
          if (titleInfo.index) {
            excludedIndexes[titleInfo.index] = true;
          }
          if (subtitleInfo.index) {
            excludedIndexes[subtitleInfo.index] = true;
          }
          body = collectBodyText(currentSlide, excludedIndexes, {
            maxBlockLength: limits.maxFallbackLength,
            maxBodyLength: limits.maxFallbackLength
          }).blocks.join("\n").slice(0, limits.maxFallbackLength);
        }
      }
      extracted.push({
        index: index,
        title: truncateText(titleInfo.text, limits.maxTitleLength),
        subtitle: subtitleInfo.text,
        bodyFallback: body,
        bodyFallbackOmitted: bodyFallbackOmitted
      });
    }
    return {
      presentationId: safeText(
        safeRead(presentation, "Name") || safeRead(presentation, "name"),
        "active-presentation"
      ) || "active-presentation",
      scene: "ppt",
      scope: {
        totalSlides: totalSlides,
        startSlide: start,
        endSlide: end
      },
      slides: extracted
    };
  }

  function formatPptStructureRange(value) {
    var range = value || {};
    return "本次审查第 " + readNumber(range.startSlide) + "–" +
      readNumber(range.endSlide) + " 页（演示文稿共 " +
      readNumber(range.totalSlides) + " 页）｜" +
      (range.isFullDeck ? "整套审查" : "指定页段");
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
    var profiles = Array.isArray(data.configurations) ? data.configurations :
      (Array.isArray(data.profiles) ? data.profiles : []);
    return {
      taskType: safeText(data.taskType),
      activeProfileId: safeText(data.activeConfigurationId || data.activeProfileId),
      profileCount: profiles.length,
      profiles: profiles.map(function (profile) {
        return {
          id: safeText(profile && profile.id),
          taskType: safeText(profile && profile.taskType),
          name: safeText(profile && profile.name),
          note: safeText(profile && profile.note),
          apiKeyRef: safeText(profile && profile.apiKeyRef),
          keyConfigured: Boolean(profile && profile.keyConfigured),
          complete: profile && typeof profile.complete === "boolean" ? profile.complete : Boolean(profile && profile.keyConfigured),
          accessMethod: safeText(profile && profile.accessMethod) || "workflow_platform",
          serviceBaseUrl: safeText(profile && profile.serviceBaseUrl),
          callPath: safeText(profile && profile.callPath),
          modelName: safeText(profile && profile.modelName),
          temperature: profile && profile.temperature,
          maxOutputTokens: profile && profile.maxOutputTokens,
          contextWindowTokens: Number(profile && profile.contextWindowTokens || 40000),
          missingFields: profile && Array.isArray(profile.missingFields) ? profile.missingFields : [],
          configVersion: Number(profile && profile.configVersion || 1),
          lastValidation: profile && profile.lastValidation || null
        };
      })
    };
  }

  function workflowProfileOptionState(profile, activeProfileId) {
    var item = profile || {};
    var active = Boolean(item.id && item.id === activeProfileId);
    var configured = Boolean(item.complete);
    var name = String(item.name || "未命名配置");
    var method = item.accessMethod === "direct_model" ? "模型直连" : "工作流平台";
    var model = item.accessMethod === "direct_model" && item.modelName ? " · " + item.modelName : "";
    return {
      id: String(item.id || ""),
      label: (active ? "✓ " : "") + name + " · " + method + model +
        (configured ? "" : "（配置不完整）"),
      active: active,
      disabled: !configured
    };
  }

  function deriveModelInterfaceState(input) {
    var source = input || {};
    var taskTypes = Array.isArray(source.taskTypes) ? source.taskTypes : [];
    var profilesByTask = source.profilesByTask || {};
    var readyCount = 0;
    var totalCount = taskTypes.length;
    var taskIndex;
    var profileIndex;
    var data;
    var profiles;

    if (source.detectable === false) {
      return { code: "unavailable", label: "无法检测", readyCount: 0, totalCount: totalCount };
    }

    for (taskIndex = 0; taskIndex < taskTypes.length; taskIndex += 1) {
      data = profilesByTask[taskTypes[taskIndex]] || {};
      profiles = Array.isArray(data.profiles) ? data.profiles : [];
      for (profileIndex = 0; profileIndex < profiles.length; profileIndex += 1) {
        if (profiles[profileIndex]
          && profiles[profileIndex].id === data.activeProfileId
          && profiles[profileIndex].complete) {
          readyCount += 1;
          break;
        }
      }
    }

    if (totalCount === 0 || readyCount === 0) {
      return { code: "unconfigured", label: "未配置", readyCount: readyCount, totalCount: totalCount };
    }
    if (readyCount === totalCount) {
      return { code: "ready", label: "已就绪", readyCount: readyCount, totalCount: totalCount };
    }
    return {
      code: "partial",
      label: "部分就绪 · " + readyCount + "/" + totalCount,
      readyCount: readyCount,
      totalCount: totalCount
    };
  }

  function normalizeAdapterHealth(value, connected) {
    var source = value && typeof value === "object" ? value : {};
    var policy = source.operationPolicy && typeof source.operationPolicy === "object"
      ? source.operationPolicy
      : {};
    var status = String(source.status || "").toLowerCase();
    if (connected === false) {
      status = "unavailable";
    } else if (status === "ok") {
      status = "ready";
    } else if (["ready", "degraded", "recovery"].indexOf(status) < 0) {
      status = "ready";
    }
    var recovery = status === "recovery";
    var degraded = status === "degraded";
    return {
      status: status,
      connected: status !== "unavailable",
      badgeClass: status === "ready" ? "badge-ok" : (degraded ? "badge-warn" : "badge-error"),
      badgeLabel: status === "ready" ? "已连接" : (
        degraded ? "增强降级" : (recovery ? "恢复模式" : "未连接")
      ),
      summary: degraded
        ? "Adapter 已连接，写作规范增强能力降级，核心功能可继续使用。"
        : (recovery
          ? "Adapter 已连接但处于恢复模式，配置变更和模型任务已被阻止。"
          : (status === "unavailable" ? "无法连接本地 Adapter。" : "Adapter 已连接。")),
      configurationMutationsAllowed: !recovery && policy.configurationMutationsAllowed !== false,
      modelTasksAllowed: !recovery && policy.modelTasksAllowed !== false,
      writingPolicyMutationsAllowed: !recovery && !degraded && policy.writingPolicyMutationsAllowed !== false
    };
  }

  function createSettingsRefreshController(options) {
    var settings = options || {};
    var refresh = typeof settings.refresh === "function" ? settings.refresh : function () {};
    var setIntervalFn = typeof settings.setIntervalFn === "function"
      ? settings.setIntervalFn
      : (typeof global.setInterval === "function" ? global.setInterval : function () { return 0; });
    var clearIntervalFn = typeof settings.clearIntervalFn === "function"
      ? settings.clearIntervalFn
      : (typeof global.clearInterval === "function" ? global.clearInterval : function () {});
    var intervalMs = typeof settings.intervalMs === "number" ? settings.intervalMs : 30000;
    var timerId = null;

    return {
      start: function () {
        if (timerId !== null) {
          return;
        }
        refresh();
        timerId = setIntervalFn(refresh, intervalMs);
      },
      stop: function () {
        if (timerId === null) {
          return;
        }
        clearIntervalFn(timerId);
        timerId = null;
      },
      isRunning: function () {
        return timerId !== null;
      }
    };
  }

  function validateWorkflowProfileDraft(draft, mode) {
    var value = draft || {};
    var name = String(value.name || "").trim();
    var note = String(value.note || "").trim();
    var apiKey = String(value.apiKey || "").trim();
    if (!name) {
      return { ok: false, field: "name", message: "请输入模型配置名称。" };
    }
    if (name.length > 40) {
      return { ok: false, field: "name", message: "模型配置名称不能超过 40 个字。" };
    }
    if (note.length > 200) {
      return { ok: false, field: "note", message: "模型配置备注不能超过 200 个字。" };
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

  function describePptJobProgress(job, sourceMode, jobId) {
    var data = job || {};
    var phase = safeText(data.phase) || (data.status === "queued" ? "queued" : "provider_processing");
    var isDocument = sourceMode === "document" || data.sourceMode === "document";
    var status;
    var detail;
    if (phase === "queued") {
      status = "智能总结任务正在排队...";
      detail = data.queuePosition
        ? "队列位置：第 " + data.queuePosition + " 位"
        : "任务正在等待执行槽位。";
    } else if (phase === "preparing") {
      status = "正在准备智能总结任务...";
      detail = "正在准备任务资源。";
    } else if (phase === "uploading") {
      status = "正在上传文档到模型后台...";
      detail = "正在上传文档到模型后台。";
    } else if (phase === "parsing") {
      status = "正在整理智能总结结果...";
      detail = "正在解析并整理返回结果。";
    } else {
      status = isDocument
        ? "模型后台正在生成文档总结方案..."
        : "模型后台正在生成当前页总结...";
      detail = isDocument
        ? "模型后台正在处理文档总结。"
        : "模型后台正在处理当前页总结。";
    }
    return {
      status: status,
      detail: [
        detail,
        "已等待：" + (Number(data.elapsedSeconds) || 0) + " 秒",
        "任务编号：" + safeText(jobId || data.jobId)
      ].join("\n")
    };
  }

  global.WpsAiPptHelpers = {
    extractPresentationSlide: extractPresentationSlide,
    extractPresentationStructure: extractPresentationStructure,
    formatPptStructureRange: formatPptStructureRange,
    truncateText: truncateText,
    renderMarkdown: renderMarkdown,
    escapeHtml: escapeHtml,
    normalizeWorkflowProfiles: normalizeWorkflowProfiles,
    workflowProfileOptionState: workflowProfileOptionState,
    deriveModelInterfaceState: deriveModelInterfaceState,
    normalizeAdapterHealth: normalizeAdapterHealth,
    createSettingsRefreshController: createSettingsRefreshController,
    validateWorkflowProfileDraft: validateWorkflowProfileDraft,
    shouldActivateNewWorkflowProfile: shouldActivateNewWorkflowProfile,
    buildPptSlideMarkdown: buildPptSlideMarkdown,
    buildPptSlidePlainText: buildPptSlidePlainText,
    validatePptDocumentFile: validatePptDocumentFile,
    normalizePptDocumentResult: normalizePptDocumentResult,
    buildPptDocumentPlainText: buildPptDocumentPlainText,
    buildPptDocumentOutline: buildPptDocumentOutline,
    buildPptDocumentSlidePlainText: buildPptDocumentSlidePlainText,
    describePptJobProgress: describePptJobProgress
  };
}(window));
