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

  function readSlideTitleInfo(slide) {
    var shapes = getSlideShapes(slide);
    var titleShape = getExplicitTitleShape(shapes);
    var titleText = readShapeText(titleShape);
    var count;
    var index;
    var candidate;
    var candidateText;
    if (titleText) {
      return { text: titleText, shape: titleShape };
    }
    count = getCollectionCount(shapes);
    for (index = 1; index <= count; index += 1) {
      candidate = getCollectionItem(shapes, index);
      candidateText = readShapeText(candidate);
      if (candidateText && candidateText.length <= 200) {
        return { text: candidateText, shape: candidate };
      }
    }
    return { text: "", shape: null };
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

  function collectBodyText(slide, titleShape, limits) {
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
      if (shape === titleShape) {
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
    body = collectBodyText(slide, titleInfo.shape, limits);
    previous = readAdjacentTitle(slides, slideIndex, -1, limits.maxAdjacentTitleLength);
    next = readAdjacentTitle(slides, slideIndex, 1, limits.maxAdjacentTitleLength);
    truncated = body.truncated || title.length < titleInfo.text.length || previous.truncated || next.truncated;
    return {
      presentationId: safeText(safeRead(presentation, "Name") || safeRead(presentation, "name"), "active-presentation") || "active-presentation",
      scene: "ppt",
      slide: {
        index: slideIndex,
        title: title,
        textBlocks: body.blocks,
        previousTitle: previous.text,
        nextTitle: next.text,
        bodyCharacterCount: body.bodyCharacterCount,
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

  global.WpsAiPptHelpers = {
    extractPresentationSlide: extractPresentationSlide,
    truncateText: truncateText,
    renderMarkdown: renderMarkdown,
    escapeHtml: escapeHtml,
    normalizeWorkflowProfiles: normalizeWorkflowProfiles
  };
}(window));
