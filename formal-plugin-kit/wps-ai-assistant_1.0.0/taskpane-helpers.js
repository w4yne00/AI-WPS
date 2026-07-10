(function (root, factory) {
  var exports = factory();
  root.WpsAiAssistantHelpers = exports;
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function normalizeText(text) {
    return String(text || "").replace(/\r/g, "").trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function sanitizeMarkdownUrl(value) {
    var url = String(value || "").trim();
    if (/^(https?:\/\/|mailto:)/i.test(url)) {
      return url;
    }
    return "";
  }

  function renderInlineMarkdown(value) {
    var tokens = [];
    var text = String(value || "");

    function storeToken(html) {
      var token = "\u0000MDTOKEN" + tokens.length + "\u0000";
      tokens.push({ token: token, html: html });
      return token;
    }

    text = text.replace(/`([^`]+)`/g, function (_match, code) {
      return storeToken("<code>" + escapeHtml(code) + "</code>");
    });

    text = text.replace(/(!?)\[([^\]]+)\]\(([^)\s]+)\)/g, function (match, imagePrefix, label, url) {
      var safeUrl = imagePrefix ? "" : sanitizeMarkdownUrl(url);
      if (!safeUrl) {
        return escapeHtml(label || match);
      }
      return storeToken(
        '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' +
        escapeHtml(label) +
        "</a>"
      );
    });

    text = escapeHtml(text)
      .replace(/==([^=\n]+)==/g, '<mark class="smart-diff-highlight">$1</mark>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");

    tokens.forEach(function (entry) {
      text = text.split(escapeHtml(entry.token)).join(entry.html);
    });
    return text;
  }

  function renderMarkdown(markdown) {
    var lines = String(markdown || "").replace(/\r/g, "").split("\n");
    var html = [];
    var paragraph = [];
    var listType = "";
    var inCode = false;
    var codeLang = "";
    var codeLines = [];
    var tableRows = [];

    function closeList() {
      if (listType) {
        html.push("</" + listType + ">");
        listType = "";
      }
    }

    function flushParagraph() {
      if (paragraph.length) {
        closeList();
        html.push("<p>" + paragraph.map(renderInlineMarkdown).join("<br>") + "</p>");
        paragraph = [];
      }
    }

    function splitTableRow(line) {
      var value = String(line || "").trim();
      if (value.charAt(0) === "|") {
        value = value.slice(1);
      }
      if (value.charAt(value.length - 1) === "|") {
        value = value.slice(0, -1);
      }
      return value.split("|").map(function (cell) {
        return cell.trim();
      });
    }

    function isTableSeparator(line) {
      var cells = splitTableRow(line);
      return cells.length > 0 && cells.every(function (cell) {
        return /^:?-{3,}:?$/.test(cell);
      });
    }

    function isTableLine(line) {
      return /\|/.test(line || "");
    }

    function flushTable() {
      if (tableRows.length < 2 || !isTableSeparator(tableRows[1])) {
        tableRows.forEach(function (row) {
          paragraph.push(row.trim());
        });
        tableRows = [];
        return;
      }

      flushParagraph();
      closeList();
      var headers = splitTableRow(tableRows[0]);
      var bodyRows = tableRows.slice(2);
      html.push('<div class="markdown-table-wrap"><table><thead><tr>');
      headers.forEach(function (cell) {
        html.push("<th>" + renderInlineMarkdown(cell) + "</th>");
      });
      html.push("</tr></thead><tbody>");
      bodyRows.forEach(function (row) {
        html.push("<tr>");
        splitTableRow(row).forEach(function (cell) {
          html.push("<td>" + renderInlineMarkdown(cell) + "</td>");
        });
        html.push("</tr>");
      });
      html.push("</tbody></table></div>");
      tableRows = [];
    }

    function openList(nextType) {
      flushParagraph();
      if (listType !== nextType) {
        closeList();
        html.push("<" + nextType + ">");
        listType = nextType;
      }
    }

    lines.forEach(function (line) {
      var codeFence = line.match(/^```([A-Za-z0-9_-]*)\s*$/);
      var heading = line.match(/^(#{1,6})\s+(.+)$/);
      var unordered = line.match(/^\s*[-*+]\s+(.+)$/);
      var ordered = line.match(/^\s*\d+\.\s+(.+)$/);
      var quote = line.match(/^>\s?(.+)$/);
      var divider = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line);

      if (inCode) {
        if (codeFence) {
          html.push(
            '<pre><code' +
            (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : "") +
            ">" +
            escapeHtml(codeLines.join("\n")) +
            "</code></pre>"
          );
          inCode = false;
          codeLang = "";
          codeLines = [];
          return;
        }
        codeLines.push(line);
        return;
      }

      if (tableRows.length && !isTableLine(line)) {
        flushTable();
      }

      if (codeFence) {
        flushTable();
        flushParagraph();
        closeList();
        inCode = true;
        codeLang = codeFence[1] || "";
        codeLines = [];
        return;
      }

      if (!line.trim()) {
        flushTable();
        flushParagraph();
        closeList();
        return;
      }

      if (isTableLine(line)) {
        tableRows.push(line);
        return;
      }

      if (heading) {
        flushTable();
        flushParagraph();
        closeList();
        html.push(
          "<h" + heading[1].length + ">" +
          renderInlineMarkdown(heading[2]) +
          "</h" + heading[1].length + ">"
        );
        return;
      }

      if (divider) {
        flushTable();
        flushParagraph();
        closeList();
        html.push("<hr>");
        return;
      }

      if (unordered) {
        flushTable();
        openList("ul");
        html.push("<li>" + renderInlineMarkdown(unordered[1]) + "</li>");
        return;
      }

      if (ordered) {
        flushTable();
        openList("ol");
        html.push("<li>" + renderInlineMarkdown(ordered[1]) + "</li>");
        return;
      }

      if (quote) {
        flushTable();
        flushParagraph();
        closeList();
        html.push("<blockquote>" + renderInlineMarkdown(quote[1]) + "</blockquote>");
        return;
      }

      paragraph.push(line.trim());
    });

    if (inCode) {
      html.push(
        '<pre><code' +
        (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : "") +
        ">" +
        escapeHtml(codeLines.join("\n")) +
        "</code></pre>"
      );
    }
    flushTable();
    flushParagraph();
    closeList();

    return html.join("\n");
  }

  function stripInlineMarkdownForWriteback(value) {
    return String(value || "")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .replace(/\*{1,3}/g, "");
  }

  function buildInlineWritebackRuns(value) {
    var runs = [];
    var source = String(value || "");
    var pattern = /\*\*([^*]+)\*\*/g;
    var lastIndex = 0;
    var match;

    while ((match = pattern.exec(source)) !== null) {
      if (match.index > lastIndex) {
        runs.push({
          text: stripInlineMarkdownForWriteback(source.slice(lastIndex, match.index)),
          bold: false
        });
      }
      runs.push({
        text: stripInlineMarkdownForWriteback(match[1]),
        bold: true
      });
      lastIndex = pattern.lastIndex;
    }

    if (lastIndex < source.length) {
      runs.push({
        text: stripInlineMarkdownForWriteback(source.slice(lastIndex)),
        bold: false
      });
    }

    return runs.filter(function (run) {
      return Boolean(run.text);
    });
  }

  function buildMarkdownWritebackBlocks(markdown) {
    var lines = String(markdown || "").replace(/\r/g, "").split("\n");
    var blocks = [];
    var paragraph = [];
    var inCode = false;
    var codeLines = [];

    function pushBlock(type, text, extras) {
      var cleanText = stripInlineMarkdownForWriteback(text);
      var block;
      var key;
      if (!cleanText) {
        return;
      }
      block = {
        type: type,
        text: cleanText,
        runs: buildInlineWritebackRuns(text)
      };
      extras = extras || {};
      for (key in extras) {
        if (Object.prototype.hasOwnProperty.call(extras, key)) {
          block[key] = extras[key];
        }
      }
      blocks.push(block);
    }

    function flushParagraph() {
      if (!paragraph.length) {
        return;
      }
      pushBlock("paragraph", paragraph.join("\n"));
      paragraph = [];
    }

    lines.forEach(function (line) {
      var codeFence = line.match(/^```([A-Za-z0-9_-]*)\s*$/);
      var heading = line.match(/^(#{1,6})\s+(.+)$/);
      var unordered = line.match(/^\s*[-*+]\s+(.+)$/);
      var ordered = line.match(/^\s*(\d+)\.\s+(.+)$/);
      var divider = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line);

      if (inCode) {
        if (codeFence) {
          pushBlock("paragraph", codeLines.join("\n"));
          inCode = false;
          codeLines = [];
          return;
        }
        codeLines.push(line);
        return;
      }

      if (codeFence) {
        flushParagraph();
        inCode = true;
        codeLines = [];
        return;
      }

      if (!line.trim()) {
        flushParagraph();
        return;
      }

      if (divider) {
        flushParagraph();
        return;
      }

      if (heading) {
        flushParagraph();
        pushBlock("heading", heading[2], { level: heading[1].length });
        return;
      }

      if (unordered) {
        flushParagraph();
        pushBlock("unorderedListItem", unordered[1]);
        return;
      }

      if (ordered) {
        flushParagraph();
        pushBlock("orderedListItem", ordered[2], { ordinal: Number(ordered[1]) });
        return;
      }

      paragraph.push(line.trim());
    });

    if (inCode) {
      pushBlock("paragraph", codeLines.join("\n"));
    }
    flushParagraph();
    return blocks;
  }

  function hasStructuredSmartWriteContent(value) {
    var text = String(value || "").replace(/\r/g, "\n");
    var lines = text.split("\n");
    var nonEmpty = lines.filter(function (line) {
      return Boolean(line.trim());
    });

    if (!text.trim()) {
      return false;
    }
    if (/(^|\n)\s{0,3}#{1,6}\s+\S/.test(text)) {
      return true;
    }
    if (/(^|\n)\s*[-*+•·]\s+\S/.test(text)) {
      return true;
    }
    if (/(^|\n)\s*\d+[.)．、]\s+\S/.test(text)) {
      return true;
    }
    if (/(^|\n)\s*[一二三四五六七八九十]+[、.．]\s*\S/.test(text)) {
      return true;
    }
    if (/(^|\n)\s*[（(][一二三四五六七八九十\d]+[）)]\s*\S/.test(text)) {
      return true;
    }
    if (/(^|\n)\s*第[一二三四五六七八九十\d]+[章节条]\s*\S/.test(text)) {
      return true;
    }
    if (/\*\*[^*\n]+\*\*/.test(text)) {
      return true;
    }
    if (/\|.+\|/.test(text) && /(^|\n)\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*(\n|$)/.test(text)) {
      return true;
    }
    if (nonEmpty.length >= 2 && nonEmpty.some(function (line) {
      return line.split("\t").length >= 2;
    })) {
      return true;
    }
    return false;
  }

  function shouldUseStructuredSmartWriteResult(originalText, rewrittenText) {
    return hasStructuredSmartWriteContent(originalText) || hasStructuredSmartWriteContent(rewrittenText);
  }

  function getSmartWriteParagraphs(value) {
    return String(value || "")
      .replace(/\r/g, "\n")
      .split(/\n+/)
      .map(function (line) {
        return line.trim();
      })
      .filter(Boolean);
  }

  function normalizeSmartWriteLineBreaks(value) {
    return String(value || "")
      .replace(/\r/g, "\n")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function breakInlineSmartWriteStructure(value) {
    var text = normalizeSmartWriteLineBreaks(value);
    var boundary = "([。！？；;!?””）\\)])";
    var patterns = [
      new RegExp(boundary + "\\s*(#{1,6}\\s+\\S)", "g"),
      new RegExp(boundary + "\\s*([一二三四五六七八九十]+[、.．]\\s*\\S)", "g"),
      new RegExp(boundary + "\\s*([（(][一二三四五六七八九十\\d]+[）)]\\s*\\S)", "g"),
      new RegExp(boundary + "\\s*(第[一二三四五六七八九十\\d]+[章节条]\\s*\\S)", "g"),
      new RegExp(boundary + "\\s*(\\d+[.)．、]\\s+\\S)", "g"),
      new RegExp(boundary + "\\s*([-*+•·]\\s+\\S)", "g")
    ];
    patterns.forEach(function (pattern) {
      text = text.replace(pattern, "$1\n\n$2");
    });
    return normalizeSmartWriteLineBreaks(text);
  }

  function splitSmartWriteSentences(value) {
    var text = normalizeSmartWriteLineBreaks(value);
    var matches = text.match(/[^。！？；!?;]+[。！？；!?;]*/g);
    if (!matches || !matches.length) {
      return text ? [text] : [];
    }
    return matches.map(function (sentence) {
      return sentence.trim();
    }).filter(Boolean);
  }

  function distributeSmartWriteSentences(sentences, targetCount) {
    var paragraphs = [];
    var totalLength = 0;
    var consumedLength = 0;
    var sentenceIndex = 0;
    var lengthIndex;

    for (lengthIndex = 0; lengthIndex < sentences.length; lengthIndex += 1) {
      totalLength += sentences[lengthIndex].length;
    }

    for (var paragraphIndex = 0; paragraphIndex < targetCount; paragraphIndex += 1) {
      var remainingParagraphs = targetCount - paragraphIndex;
      var paragraphSentences = [];
      var targetLength = totalLength * (paragraphIndex + 1) / targetCount;

      if (remainingParagraphs === 1) {
        paragraphSentences = sentences.slice(sentenceIndex);
        sentenceIndex = sentences.length;
      } else {
        while (sentenceIndex < sentences.length - (remainingParagraphs - 1)) {
          paragraphSentences.push(sentences[sentenceIndex]);
          consumedLength += sentences[sentenceIndex].length;
          sentenceIndex += 1;
          if (consumedLength >= targetLength) {
            break;
          }
        }
      }

      if (paragraphSentences.length) {
        paragraphs.push(paragraphSentences.join(""));
      }
    }

    return paragraphs.filter(Boolean);
  }

  function formatSmartWriteResult(originalText, rewrittenText) {
    var normalized = normalizeSmartWriteLineBreaks(rewrittenText);
    var originalParagraphs;
    var targetCount;
    var structuredText;
    var sentences;
    var distributed;

    if (!normalized) {
      return "";
    }
    if (getSmartWriteParagraphs(normalized).length >= 2) {
      return normalized;
    }

    structuredText = breakInlineSmartWriteStructure(normalized);
    if (getSmartWriteParagraphs(structuredText).length >= 2) {
      return structuredText;
    }

    originalParagraphs = getSmartWriteParagraphs(originalText);
    if (originalParagraphs.length < 2) {
      return normalized;
    }

    targetCount = Math.min(originalParagraphs.length, 6);
    sentences = splitSmartWriteSentences(normalized);
    if (sentences.length < targetCount) {
      return normalized;
    }

    distributed = distributeSmartWriteSentences(sentences, targetCount);
    return distributed.length >= 2 ? distributed.join("\n\n") : normalized;
  }

  function normalizeSmartWriteComparisonLine(value) {
    return String(value || "").replace(/\s+/g, "").trim();
  }

  function sanitizeSmartWriteHighlightText(value) {
    return String(value || "").replace(/==/g, "＝");
  }

  function getSmartWriteCommonPrefixLength(left, right) {
    var index = 0;
    var maxLength = Math.min(left.length, right.length);
    while (index < maxLength && left.charAt(index) === right.charAt(index)) {
      index += 1;
    }
    return index;
  }

  function getSmartWriteCommonSuffixLength(left, right, prefixLength) {
    var suffixLength = 0;
    var maxLength = Math.min(left.length, right.length) - prefixLength;
    while (
      suffixLength < maxLength &&
      left.charAt(left.length - 1 - suffixLength) === right.charAt(right.length - 1 - suffixLength)
    ) {
      suffixLength += 1;
    }
    return suffixLength;
  }

  function markSmartWriteInsertedSegment(value) {
    return value ? "==" + sanitizeSmartWriteHighlightText(value) + "==" : "";
  }

  function markSmartWriteDiffSegments(originalText, rewrittenText) {
    var original = String(originalText || "");
    var rewritten = String(rewrittenText || "");
    var originalLength = original.length;
    var rewrittenLength = rewritten.length;
    var matrixSize = originalLength * rewrittenLength;
    var dp;
    var i;
    var j;
    var pieces = [];
    var pending = "";

    if (!rewrittenLength) {
      return "";
    }
    if (!originalLength) {
      return markSmartWriteInsertedSegment(rewritten);
    }
    if (matrixSize > 40000) {
      return markSmartWriteInsertedSegment(rewritten);
    }

    dp = new Array(originalLength + 1);
    for (i = 0; i <= originalLength; i += 1) {
      dp[i] = new Array(rewrittenLength + 1).fill(0);
    }

    for (i = originalLength - 1; i >= 0; i -= 1) {
      for (j = rewrittenLength - 1; j >= 0; j -= 1) {
        if (original.charAt(i) === rewritten.charAt(j)) {
          dp[i][j] = dp[i + 1][j + 1] + 1;
        } else {
          dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
    }

    function flushPending() {
      if (pending) {
        pieces.push(markSmartWriteInsertedSegment(pending));
        pending = "";
      }
    }

    i = 0;
    j = 0;
    while (j < rewrittenLength) {
      if (i < originalLength && original.charAt(i) === rewritten.charAt(j)) {
        flushPending();
        pieces.push(rewritten.charAt(j));
        i += 1;
        j += 1;
      } else if (i < originalLength && (j >= rewrittenLength || dp[i + 1][j] >= dp[i][j + 1])) {
        i += 1;
      } else {
        pending += rewritten.charAt(j);
        j += 1;
      }
    }
    flushPending();

    return pieces.join("");
  }

  function markSmartWriteChangedText(originalValue, rewrittenValue) {
    var rewritten = String(rewrittenValue || "");
    var original = String(originalValue || "");
    var edgeMatch = rewritten.match(/^(\s*)([\s\S]*?)(\s*)$/);
    var leading = edgeMatch ? edgeMatch[1] : "";
    var body = edgeMatch ? edgeMatch[2] : rewritten;
    var trailing = edgeMatch ? edgeMatch[3] : "";
    var originalBody = original.trim();
    var prefixLength;
    var suffixLength;
    var changedStart;
    var changedEnd;
    var changedText;
    var originalChangedText;

    if (!body || normalizeSmartWriteComparisonLine(original) === normalizeSmartWriteComparisonLine(rewritten)) {
      return rewritten;
    }

    prefixLength = getSmartWriteCommonPrefixLength(originalBody, body);
    suffixLength = getSmartWriteCommonSuffixLength(originalBody, body, prefixLength);
    changedStart = prefixLength;
    changedEnd = body.length - suffixLength;
    changedText = body.slice(changedStart, changedEnd);
    originalChangedText = originalBody.slice(prefixLength, originalBody.length - suffixLength);

    if (!changedText) {
      return rewritten;
    }

    return leading +
      body.slice(0, changedStart) +
      markSmartWriteDiffSegments(originalChangedText, changedText) +
      body.slice(changedEnd) +
      trailing;
  }

  function getSmartWriteComparableLineText(line) {
    var text = String(line || "");
    var match = text.match(/^(\s*#{1,6}\s+)(.+)$/) ||
      text.match(/^(\s*[-*+]\s+)(.+)$/) ||
      text.match(/^(\s*\d+\.\s+)(.+)$/) ||
      text.match(/^(>\s?)(.+)$/);
    return match ? match[2] : text;
  }

  function markSmartWriteTableLine(originalLine, line) {
    var originalCells = String(originalLine || "").split("|");
    return String(line || "").split("|").map(function (cell, index) {
      var trimmed = cell.trim();
      if (!trimmed || /^:?-{3,}:?$/.test(trimmed)) {
        return cell;
      }
      return markSmartWriteChangedText(originalCells[index] || "", cell);
    }).join("|");
  }

  function markSmartWriteComparisonLine(originalLine, line) {
    var text = String(line || "");
    var originalText = String(originalLine || "");
    var tableSeparator = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(text);
    var match;
    if (!text.trim()) {
      return text;
    }
    if (tableSeparator) {
      return text;
    }
    if (text.indexOf("|") >= 0) {
      return markSmartWriteTableLine(originalText, text);
    }
    match = text.match(/^(\s*#{1,6}\s+)(.+)$/);
    if (match) {
      return match[1] + markSmartWriteChangedText(getSmartWriteComparableLineText(originalText), match[2]);
    }
    match = text.match(/^(\s*[-*+]\s+)(.+)$/);
    if (match) {
      return match[1] + markSmartWriteChangedText(getSmartWriteComparableLineText(originalText), match[2]);
    }
    match = text.match(/^(\s*\d+\.\s+)(.+)$/);
    if (match) {
      return match[1] + markSmartWriteChangedText(getSmartWriteComparableLineText(originalText), match[2]);
    }
    match = text.match(/^(>\s?)(.+)$/);
    if (match) {
      return match[1] + markSmartWriteChangedText(getSmartWriteComparableLineText(originalText), match[2]);
    }
    return markSmartWriteChangedText(originalText, text);
  }

  function buildHighlightedSmartWriteResult(originalText, rewrittenText) {
    var originalLines = normalizeSmartWriteLineBreaks(originalText)
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .filter(Boolean);
    var rewrittenLines = normalizeSmartWriteLineBreaks(rewrittenText).split("\n");
    var originalIndex = 0;
    return rewrittenLines.map(function (line) {
      var cleanLine = line.trim();
      var originalLine;
      var changed;
      if (!cleanLine) {
        return line;
      }
      originalLine = originalLines[originalIndex] || "";
      changed = normalizeSmartWriteComparisonLine(cleanLine) !== normalizeSmartWriteComparisonLine(originalLine);
      originalIndex += 1;
      return changed ? markSmartWriteComparisonLine(originalLine, line) : line;
    }).join("\n");
  }

  function buildSmartWritePreviewModel(result) {
    var source = result || {};
    var originalText = normalizeSmartWriteLineBreaks(source.originalText || "");
    var rewrittenText = formatSmartWriteResult(originalText, source.rewrittenText || "");
    var hasOriginal = Boolean(originalText);
    var highlightedText = hasOriginal ? buildHighlightedSmartWriteResult(originalText, rewrittenText) : rewrittenText;
    var comparisonMarkdown = "";

    if (hasOriginal && rewrittenText) {
      comparisonMarkdown = [
        "### 原文",
        "",
        originalText,
        "",
        "### 智能编写结果",
        "",
        highlightedText
      ].join("\n");
    } else {
      comparisonMarkdown = rewrittenText;
    }

    return {
      previewMarkdown: rewrittenText,
      plainText: rewrittenText,
      comparisonMarkdown: comparisonMarkdown,
      hasOriginal: hasOriginal,
      hasStructuredResult: shouldUseStructuredSmartWriteResult(originalText, rewrittenText)
    };
  }

  var FORMAT_REVIEW_GROUP_ORDER = [
    "page_setup",
    "heading",
    "body_text",
    "paragraph",
    "caption_note",
    "other"
  ];
  var FORMAT_REVIEW_GROUP_TEXT = {
    page_setup: "页面设置",
    heading: "标题层级",
    body_text: "正文格式",
    paragraph: "段落格式",
    caption_note: "图表题/注释",
    other: "其他格式项"
  };
  var FORMAT_REVIEW_ROLE_TEXT = {
    document_title: "文档标题",
    heading1: "一级标题",
    heading2: "二级标题",
    heading3: "三级标题",
    heading4: "四级标题",
    caption: "图表题",
    note: "无编号注",
    numbered_note: "有编号注",
    list1_numbered: "一级编号列项",
    list1_plain: "一级无编号列项",
    list2_numbered: "二级编号列项",
    list2_plain: "二级无编号列项",
    appendix_title: "附录标题",
    appendix_heading1: "附录一级标题",
    appendix_heading2: "附录二级标题",
    appendix_heading3: "附录三级标题",
    table_body: "表正文",
    body: "正文",
    page_setup: "页面设置"
  };
  var FORMAT_REVIEW_RULE_TEXT = {
    page_setup: "页面设置",
    style_name: "段落样式",
    font_name: "字体",
    font_size: "字号",
    line_spacing: "行距",
    alignment: "对齐方式",
    first_line_indent: "首行缩进"
  };
  var FORMAT_REVIEW_TEMPLATE_TEXT = {
    "technical-file-format-requirements": "技术文件格式及书写要求",
    "general-office": "通用办公文档格式"
  };
  var FORMAT_REVIEW_STYLE_TEXT = {
    Normal: "正文样式（Normal）",
    Body: "正文样式（Body）",
    body: "正文样式",
    "heading 1": "一级标题样式（heading 1）",
    "heading 2": "二级标题样式（heading 2）",
    "heading 3": "三级标题样式（heading 3）",
    "heading 4": "四级标题样式（heading 4）",
    Caption: "图表题样式（Caption）",
    caption: "图表题样式（caption）"
  };
  var FORMAT_REVIEW_ALIGNMENT_TEXT = {
    left: "左对齐",
    center: "居中",
    right: "右对齐",
    justify: "两端对齐",
    justified: "两端对齐",
    distribute: "分散对齐",
    distributed: "分散对齐",
    "0": "左对齐",
    "1": "居中",
    "2": "右对齐",
    "3": "两端对齐",
    "4": "分散对齐"
  };
  var FORMAT_REVIEW_FONT_TEXT = {
    simsun: "宋体",
    "songti sc": "宋体",
    "songti": "宋体",
    "宋体": "宋体",
    simhei: "黑体",
    "黑体": "黑体",
    kaiti: "楷体",
    "楷体": "楷体",
    fangsong: "仿宋",
    "仿宋": "仿宋"
  };
  var FORMAT_REVIEW_SIZE_TEXT = {
    "22": "二号",
    "18": "小二",
    "16": "三号",
    "15": "小三",
    "14": "四号",
    "12": "小四",
    "10.5": "五号",
    "9": "小五"
  };

  function formatReviewGroupItems(items, getKey) {
    var grouped = {};
    (items || []).forEach(function (item) {
      var key = getKey(item) || "other";
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    });
    return grouped;
  }

  function getFormatReviewGroup(issue) {
    var ruleId = String((issue && issue.ruleId) || "");
    var role = String((issue && issue.role) || "");
    if (ruleId === "page_setup") {
      return "page_setup";
    }
    if (role.indexOf("heading") >= 0 || role.indexOf("title") >= 0) {
      return "heading";
    }
    if (ruleId === "style_name" || ruleId === "font_name" || ruleId === "font_size") {
      return "body_text";
    }
    if (ruleId === "line_spacing" || ruleId === "alignment" || ruleId === "first_line_indent") {
      return "paragraph";
    }
    if (role.indexOf("caption") >= 0 || role.indexOf("note") >= 0 || ruleId.indexOf("caption") >= 0 || ruleId.indexOf("note") >= 0) {
      return "caption_note";
    }
    return "other";
  }

  function formatAiFallbackReason(reason) {
    var reasonText = {
      no_paragraphs: "未读取到正文段落，未调用模型后台；请确认当前文档对象能暴露正文段落或全文文本。",
      provider_not_configured: "统一 API URL 或格式审查任务 API Key 未形成可用配置，已使用本地模板规则。",
      dify_response_not_role_json: "模型后台未返回段落角色 JSON，已使用本地模板规则。",
      provider_request_failed: "模型后台请求失败，已使用本地模板规则。",
      dify_response_no_valid_roles: "模型后台返回的角色无效，已使用本地模板规则。",
      dify_returned_no_roles: "模型后台未返回有效段落角色，已使用本地模板规则。",
      ai_budget_limited: "文档段落较多，AI 角色识别仅处理前 40 段；其余段落已使用本地模板规则。"
    };
    return reasonText[reason] || (reason ? "未记录的 AI 兜底原因，已使用本地模板规则。" : "");
  }

  function formatReviewRole(role) {
    return FORMAT_REVIEW_ROLE_TEXT[String(role || "")] || "未识别角色";
  }

  function formatReviewRule(ruleId) {
    return FORMAT_REVIEW_RULE_TEXT[String(ruleId || "")] || "其他格式项";
  }

  function formatReviewTemplate(templateId) {
    return FORMAT_REVIEW_TEMPLATE_TEXT[String(templateId || "")] || "当前格式模板";
  }

  function parseFormatReviewNumber(value) {
    var match = String(value || "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function formatReviewFontName(value) {
    var raw = String(value || "").trim();
    var normalized = raw.toLowerCase();
    return FORMAT_REVIEW_FONT_TEXT[normalized] || FORMAT_REVIEW_FONT_TEXT[raw] || raw || "未读取";
  }

  function formatReviewFontSize(value) {
    var numeric = parseFormatReviewNumber(value);
    var key;
    var label;
    if (numeric === null || isNaN(numeric)) {
      return String(value || "").trim() || "未读取";
    }
    key = String(Math.round(numeric * 10) / 10).replace(/\.0$/, "");
    label = FORMAT_REVIEW_SIZE_TEXT[key];
    return label ? label + "（" + key + "pt）" : key + "pt";
  }

  function formatReviewStyleName(value) {
    var raw = String(value || "").trim();
    return FORMAT_REVIEW_STYLE_TEXT[raw] || raw || "未读取";
  }

  function formatReviewAlignment(value) {
    var raw = String(value || "").trim();
    var key = raw.toLowerCase();
    return FORMAT_REVIEW_ALIGNMENT_TEXT[key] || FORMAT_REVIEW_ALIGNMENT_TEXT[raw] || raw || "未读取";
  }

  function formatReviewLineSpacing(value) {
    var numeric = parseFormatReviewNumber(value);
    if (numeric === null || isNaN(numeric)) {
      return String(value || "").trim() || "未读取";
    }
    if (Math.abs(numeric - 1) < 0.01) {
      return "单倍行距（1倍）";
    }
    if (Math.abs(numeric - 1.5) < 0.01) {
      return "1.5 倍行距";
    }
    return numeric + " 倍行距";
  }

  function formatReviewIndent(value) {
    var numeric = parseFormatReviewNumber(value);
    if (numeric === null || isNaN(numeric)) {
      return String(value || "").trim() || "未读取";
    }
    if (Math.abs(numeric) < 0.01) {
      return "无首行缩进";
    }
    if (Math.abs(numeric - 480) <= 20 || Math.abs(numeric - 640) <= 20) {
      return "首行缩进 2 字符（约 " + numeric + " twips）";
    }
    return "首行缩进约 " + numeric + " twips";
  }

  function formatReviewPageSetup(value) {
    var raw = String(value || "").trim();
    if (!raw || raw === "{}") {
      return "未读取";
    }
    if (raw.charAt(0) !== "{") {
      return raw;
    }
    try {
      var data = JSON.parse(raw);
      var parts = [];
      if (data.paperSize || data.PaperSize) {
        parts.push("纸张：" + (data.paperSize || data.PaperSize));
      }
      if (data.marginTop || data.marginBottom || data.marginLeft || data.marginRight) {
        parts.push(
          "页边距：上 " + (data.marginTop || "未读") +
          "、下 " + (data.marginBottom || "未读") +
          "、左 " + (data.marginLeft || "未读") +
          "、右 " + (data.marginRight || "未读")
        );
      }
      return parts.length ? parts.join("；") : raw;
    } catch (error) {
      return raw;
    }
  }

  function formatReviewValue(ruleId, value, isExpected) {
    var rule = String(ruleId || "");
    if (rule === "font_name") {
      return isExpected ? "宋体" : formatReviewFontName(value);
    }
    if (rule === "font_size") {
      return isExpected ? "小四（12pt）" : formatReviewFontSize(value);
    }
    if (rule === "style_name") {
      return formatReviewStyleName(value);
    }
    if (rule === "alignment") {
      return formatReviewAlignment(value);
    }
    if (rule === "line_spacing") {
      return formatReviewLineSpacing(value);
    }
    if (rule === "first_line_indent") {
      return formatReviewIndent(value);
    }
    if (rule === "page_setup") {
      return isExpected ? "A4 页面及模板页边距" : formatReviewPageSetup(value);
    }
    return String(value || "").trim() || (isExpected ? "按模板要求" : "未读取");
  }

  function normalizeFormatReviewSuggestion(issue) {
    var rule = String((issue && issue.ruleId) || "");
    var suggestion = String((issue && issue.suggestion) || "").trim();
    if (rule === "font_size") {
      return "字号调整为小四。";
    }
    if (rule === "font_name") {
      return "字体调整为宋体。";
    }
    if (rule === "alignment") {
      var expected = formatReviewAlignment(issue && issue.expectedValue);
      return "对齐方式调整为" + expected + "。";
    }
    if (rule === "style_name") {
      return "按" + formatReviewRole(issue && issue.role) + "套用模板样式。";
    }
    if (rule === "line_spacing") {
      var lineSpacing = parseFormatReviewNumber(issue && issue.expectedValue);
      if (lineSpacing !== null && !isNaN(lineSpacing)) {
        if (Math.abs(lineSpacing - 1) < 0.01) {
          return "行距调整为单倍行距。";
        }
        return "行距调整为 " + lineSpacing + " 倍。";
      }
      return "按模板要求调整行距。";
    }
    if (rule === "first_line_indent") {
      return "按模板要求调整首行缩进。";
    }
    if (rule === "page_setup") {
      return suggestion.replace(/^建议/, "") || "按模板设置页面和页边距。";
    }
    return suggestion || "按模板要求调整。";
  }

  function formatReviewParagraphLabel(issue) {
    if (!issue || issue.ruleId === "page_setup" || issue.paragraphIndex === 0) {
      return "页面";
    }
    return "P" + (issue.paragraphIndex || 0);
  }

  function formatReviewIssueTitle(issue) {
    return formatReviewParagraphLabel(issue) + " " +
      formatReviewRole(issue.role) + " - " +
      (issue.message || (formatReviewRule(issue.ruleId) + "不符合模板要求。")).replace(/。$/, "");
  }

  function describeFormatReviewProvider(value) {
    var provider = String(value || "local");
    if (provider === "local") {
      return "本地规则";
    }
    if (provider === "mock") {
      return "模拟服务";
    }
    if (provider.indexOf("enterprise-dify-chat") === 0) {
      return "AI 辅助 + 本地规则";
    }
    return "外部服务";
  }

  function summarizeFormatReviewDistribution(grouped) {
    var parts = [];
    FORMAT_REVIEW_GROUP_ORDER.forEach(function (group) {
      var count = grouped[group] ? grouped[group].length : 0;
      if (count) {
        parts.push(FORMAT_REVIEW_GROUP_TEXT[group] + " " + count);
      }
    });
    return parts.length ? parts.join("、") : "无";
  }

  function renderReadableFormatReview(data) {
    var summary = data && data.summary ? data.summary : {};
    var issues = data && data.issues ? data.issues : [];
    var grouped = formatReviewGroupItems(issues, getFormatReviewGroup);
    var lines = [
      "格式审查结果",
      "",
      "## 审查概览",
      "",
      "- 检查范围：" + (summary.scope === "selection" ? "选中内容" : "全文"),
      "- 问题总数：" + (summary.issueCount || issues.length || 0),
      "- 扫描段落：" + (typeof summary.paragraphCount !== "undefined" ? summary.paragraphCount : "未统计"),
      "- 问题分布：" + summarizeFormatReviewDistribution(grouped),
      "- 识别来源：" + describeFormatReviewProvider(summary.provider),
      "",
      "以下仅显示需要调整的格式项，正文内容不会在检查中改写。",
      ""
    ];

    if (!issues.length) {
      lines.push("当前范围未发现明显格式问题。");
      lines.push("");
      lines.push("## 诊断信息");
      lines.push("");
      lines.push("- 模板：" + formatReviewTemplate(summary.templateId));
      lines.push("- 识别来源：" + describeFormatReviewProvider(summary.provider));
      return lines.join("\n").trim();
    }

    lines.push("## 优先处理清单");
    lines.push("");
    lines.push("| 段落 | 问题类型 | 当前值 | 模板要求 | 建议 |");
    lines.push("| --- | --- | --- | --- | --- |");
    issues.slice(0, 12).forEach(function (issue) {
      lines.push(
        "| " + formatReviewParagraphLabel(issue) +
        " | " + formatReviewRule(issue.ruleId) +
        " | " + formatReviewValue(issue.ruleId, issue.currentValue, false) +
        " | " + formatReviewValue(issue.ruleId, issue.expectedValue, true) +
        " | " + normalizeFormatReviewSuggestion(issue) +
        " |"
      );
    });
    if (issues.length > 12) {
      lines.push("");
      lines.push("优先处理清单仅展示前 12 项；完整问题见下方详细分组。");
    }
    lines.push("");
    lines.push("## 详细问题");
    lines.push("");
    FORMAT_REVIEW_GROUP_ORDER.forEach(function (group) {
      var groupIssues = grouped[group] || [];
      if (!groupIssues.length) {
        return;
      }
      lines.push("### " + FORMAT_REVIEW_GROUP_TEXT[group] + "（" + groupIssues.length + "）");
      lines.push("");
      groupIssues.forEach(function (issue) {
        lines.push("#### " + formatReviewIssueTitle(issue));
        lines.push("- 现状：" + formatReviewValue(issue.ruleId, issue.currentValue, false));
        lines.push("- 要求：" + formatReviewValue(issue.ruleId, issue.expectedValue, true));
        lines.push("- 建议：" + normalizeFormatReviewSuggestion(issue));
        lines.push("");
      });
    });

    lines.push("## 诊断信息");
    lines.push("");
    lines.push("- 模板：" + formatReviewTemplate(summary.templateId));
    lines.push("- 识别来源：" + describeFormatReviewProvider(summary.provider));
    if (typeof summary.aiClassifiedParagraphCount !== "undefined") {
      lines.push(
        "- AI 识别段落：" + (summary.aiClassifiedParagraphCount || 0) +
        "；本地兜底段落：" + (summary.localFallbackParagraphCount || 0)
      );
    }
    if (summary.aiInvalidRoleCount || summary.aiOutOfBatchCount) {
      lines.push(
        "- AI 无效角色：" + (summary.aiInvalidRoleCount || 0) +
        "；越界段落：" + (summary.aiOutOfBatchCount || 0)
      );
    }
    var aiFallbackText = formatAiFallbackReason(summary.aiFallbackReason);
    if (aiFallbackText) {
      lines.push("- AI 兜底原因：" + aiFallbackText);
    }
    return lines.join("\n").trim();
  }

  var DOCUMENT_REVIEW_CATEGORY_TEXT = {
    typo: "错别字",
    expression: "语言表达",
    logic: "逻辑表达",
    fluency: "通畅性",
    professional: "专业性"
  };
  var DOCUMENT_REVIEW_STATUS_TEXT = {
    pending: "待处理",
    done: "已处理",
    ignored: "已忽略"
  };

  function buildDocumentReviewRecord(data, statusByIndex) {
    var source = data || {};
    var issues = source.issues || [];
    var statuses = statusByIndex || {};
    var counts = {
      pending: 0,
      done: 0,
      ignored: 0
    };
    var lines = [
      "文档审查处理记录",
      "",
      "## 处理概览",
      "",
      "- 审查摘要：" + (source.summary || "未提供"),
      "- 问题总数：" + issues.length
    ];

    issues.forEach(function (_, index) {
      var status = statuses[String(index)] || "pending";
      if (!Object.prototype.hasOwnProperty.call(counts, status)) {
        status = "pending";
      }
      counts[status] += 1;
    });

    lines.push("- 待处理：" + counts.pending);
    lines.push("- 已处理：" + counts.done);
    lines.push("- 已忽略：" + counts.ignored);
    lines.push("");

    if (!issues.length) {
      lines.push("未发现需要处理的问题。");
      return lines.join("\n").trim();
    }

    lines.push("## 问题清单");
    lines.push("");
    issues.forEach(function (issue, index) {
      var status = statuses[String(index)] || "pending";
      if (!DOCUMENT_REVIEW_STATUS_TEXT[status]) {
        status = "pending";
      }
      lines.push(
        "### " + (index + 1) + ". " +
        (DOCUMENT_REVIEW_CATEGORY_TEXT[issue.category] || "其他问题") +
        "（" + DOCUMENT_REVIEW_STATUS_TEXT[status] + "）"
      );
      lines.push("- 位置：" + (issue.location || "未标注"));
      lines.push("- 原文：" + (issue.originalText || issue.original_text || "未提供"));
      lines.push("- 问题：" + (issue.problem || "未提供"));
      lines.push("- 建议：" + (issue.suggestion || "未提供"));
      if (issue.suggestedRewrite || issue.suggested_rewrite) {
        lines.push("- 建议改写：" + (issue.suggestedRewrite || issue.suggested_rewrite));
      }
      lines.push("");
    });

    return lines.join("\n").trim();
  }

  function getEffectiveSelectionText(selectionOrSources) {
    if (!selectionOrSources) {
      return "";
    }
    if (Array.isArray(selectionOrSources)) {
      for (var i = 0; i < selectionOrSources.length; i += 1) {
        var value = getEffectiveSelectionText(selectionOrSources[i]);
        if (value) {
          return value;
        }
      }
      return "";
    }
    return normalizeText(
      selectionOrSources.Text ||
      (selectionOrSources.Range && selectionOrSources.Range.Text) ||
      (selectionOrSources.TextRange && selectionOrSources.TextRange.Text) ||
      ""
    );
  }

  function getWritableSelection(sources) {
    for (var i = 0; i < sources.length; i += 1) {
      var selection = sources[i];
      if (!selection) {
        continue;
      }
      if (typeof selection.Text !== "undefined") {
        return selection;
      }
      if (selection.Range && typeof selection.Range.Text !== "undefined") {
        return selection;
      }
    }
    return null;
  }

  function resolveRewriteScope(options) {
    var selectionText = normalizeText(options.selectionText);
    if (options.requireSelection && !selectionText) {
      return {
        ok: false,
        selectionMode: "selection",
        scopeLabel: "当前范围：全文",
        message: "请先用鼠标选中一段文字，再执行改写或续写。"
      };
    }

    if (selectionText) {
      return {
        ok: true,
        selectionMode: "selection",
        scopeLabel: "当前范围：选中文本",
        selectedText: selectionText
      };
    }

    return {
      ok: true,
      selectionMode: "document",
      scopeLabel: "当前范围：全文"
    };
  }

  function canApplyRewriteToSelection(originalText, currentSelectionText) {
    if (!normalizeText(currentSelectionText)) {
      return {
        ok: false,
        message: "当前未检测到有效选区，无法安全写回改写结果。"
      };
    }

    if (normalizeText(originalText) !== normalizeText(currentSelectionText)) {
      return {
        ok: false,
        message: "选区已变化，请重新选中原文后再应用改写结果。"
      };
    }

    return { ok: true };
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

  function normalizeNumber(value) {
    var resolved = resolveScalarValue(value);
    if (resolved === null || typeof resolved === "undefined" || resolved === "") {
      return null;
    }
    var numeric = Number(resolved);
    return isNaN(numeric) ? null : numeric;
  }

  function normalizeFontSize(value) {
    var numeric = normalizeNumber(value);
    return numeric && numeric > 0 ? numeric : null;
  }

  function normalizeAlignmentValue(value, fallback) {
    var resolved = resolveScalarValue(value);
    var text;
    var map = {
      "0": "left",
      "1": "center",
      "2": "right",
      "3": "justify",
      "4": "distribute",
      left: "left",
      center: "center",
      centered: "center",
      centre: "center",
      right: "right",
      justify: "justify",
      justified: "justify",
      distributed: "distribute",
      distribute: "distribute",
      "左对齐": "left",
      "居中": "center",
      "居中对齐": "center",
      "右对齐": "right",
      "两端对齐": "justify",
      "分散对齐": "distribute",
      wdalignparagraphleft: "left",
      wdalignparagraphcenter: "center",
      wdalignparagraphright: "right",
      wdalignparagraphjustify: "justify",
      wdalignparagraphdistribute: "distribute"
    };
    if (typeof resolved === "undefined" || resolved === null || resolved === "") {
      return fallback || "";
    }
    text = String(resolved).trim();
    return map[text.toLowerCase()] || map[text] || text;
  }

  function firstDefined() {
    for (var i = 0; i < arguments.length; i += 1) {
      if (typeof arguments[i] !== "undefined" && arguments[i] !== null) {
        return arguments[i];
      }
    }
    return null;
  }

  function normalizePositiveInteger(value) {
    var numeric = Number(value);
    if (isNaN(numeric) || numeric <= 0) {
      return null;
    }
    return Math.floor(numeric);
  }

  function normalizeCollectOptions(options) {
    var source = typeof options === "number" ? { maxParagraphs: options } : (options || {});
    return {
      maxParagraphs: normalizePositiveInteger(source.maxParagraphs),
      maxParagraphTextLength: normalizePositiveInteger(source.maxParagraphTextLength),
      avoidFallbackTextRead: Boolean(source.avoidFallbackTextRead)
    };
  }

  function limitTextLength(value, maxLength) {
    var text = String(value || "");
    if (maxLength && text.length > maxLength) {
      return text.slice(0, maxLength);
    }
    return text;
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

  function safeCall(fn, thisArg) {
    if (typeof fn !== "function") {
      return undefined;
    }
    try {
      return fn.call(thisArg);
    } catch (error) {
      return undefined;
    }
  }

  function resolveRange(object) {
    var range = firstDefined(safeRead(object, "Range"), safeRead(object, "range"));
    return typeof range === "function" ? safeCall(range, object) : range;
  }

  function normalizeParagraphText(text) {
    return String(text || "")
      .replace(/\u0007/g, "")
      .replace(/\r/g, "\n")
      .replace(/\n+$/g, "");
  }

  function toSafeString(value, fallback) {
    var resolved = resolveScalarValue(value);
    if (typeof resolved === "undefined" || resolved === null) {
      return fallback || "";
    }
    if (typeof resolved === "string") {
      return resolved;
    }
    if (typeof resolved === "number" || typeof resolved === "boolean") {
      return String(resolved);
    }
    return fallback || "";
  }

  function normalizeInteger(value) {
    var numeric = normalizeNumber(typeof value === "function" ? safeCall(value, null) : value);
    if (numeric === null) {
      return null;
    }
    return Math.round(numeric);
  }

  function readText(object) {
    var range = resolveRange(object);
    return normalizeParagraphText(toSafeString(firstDefined(
      safeRead(object, "Text"),
      safeRead(object, "text"),
      safeRead(range, "Text"),
      safeRead(range, "text"),
      safeRead(safeRead(object, "TextRange"), "Text"),
      safeRead(safeRead(range, "TextRange"), "Text")
    )));
  }

  function readDocumentText(document) {
    var content = safeRead(document, "Content") || safeRead(document, "content");
    var range = resolveRange(document);
    return normalizeParagraphText(toSafeString(firstDefined(
      safeRead(document, "Text"),
      safeRead(document, "text"),
      safeRead(content, "Text"),
      safeRead(content, "text"),
      safeRead(range, "Text"),
      safeRead(range, "text")
    )));
  }

  function readStyleName(paragraph) {
    var range = resolveRange(paragraph);
    var style = firstDefined(
      safeRead(paragraph, "Style"),
      safeRead(paragraph, "style"),
      safeRead(range, "Style"),
      safeRead(range, "style")
    );
    if (typeof style === "string") {
      return style;
    }
    return toSafeString(firstDefined(
      safeRead(paragraph, "StyleNameLocal"),
      safeRead(paragraph, "styleName"),
      safeRead(paragraph, "StyleName"),
      safeRead(range, "StyleNameLocal"),
      safeRead(range, "StyleName"),
      safeRead(style, "NameLocal"),
      safeRead(style, "Name"),
      "Body"
    ), "Body");
  }

  function readFont(paragraph) {
    var range = resolveRange(paragraph);
    return firstDefined(
      safeRead(paragraph, "Font"),
      safeRead(range, "Font"),
      {}
    );
  }

  function readParagraphFormat(paragraph) {
    var range = resolveRange(paragraph);
    return firstDefined(
      safeRead(paragraph, "ParagraphFormat"),
      safeRead(range, "ParagraphFormat"),
      {}
    );
  }

  function readCollectionCount(collection) {
    if (!collection) {
      return 0;
    }
    var count = typeof collection.length === "number" ? collection.length : null;
    if (count === null) {
      count = typeof collection.Count === "function" ? safeCall(collection.Count, collection) : safeRead(collection, "Count");
    }
    if (typeof count === "undefined" || count === null) {
      count = typeof collection.count === "function" ? safeCall(collection.count, collection) : safeRead(collection, "count");
    }
    count = Number(count);
    return isNaN(count) || count < 0 ? 0 : count;
  }

  function getCollectionItem(collection, oneBasedIndex) {
    if (!collection || oneBasedIndex < 1) {
      return null;
    }
    var zeroBasedIndex = oneBasedIndex - 1;
    if (typeof collection.length === "number" && collection[zeroBasedIndex]) {
      return collection[zeroBasedIndex];
    }
    if (typeof collection.Item === "function") {
      return safeCall(function () { return collection.Item(oneBasedIndex); }, collection);
    }
    if (typeof collection.item === "function") {
      return safeCall(function () { return collection.item(oneBasedIndex); }, collection);
    }
    return collection[oneBasedIndex] || collection[zeroBasedIndex] || null;
  }

  function getParagraphCollection(document) {
    var content = safeRead(document, "Content") || safeRead(document, "content");
    var range = resolveRange(document);
    return firstDefined(
      safeRead(document, "Paragraphs"),
      safeRead(document, "paragraphs"),
      safeRead(content, "Paragraphs"),
      safeRead(content, "paragraphs"),
      safeRead(range, "Paragraphs"),
      safeRead(range, "paragraphs"),
      []
    );
  }

  function collectParagraphsFromText(text, options) {
    var collectOptions = normalizeCollectOptions(options);
    var normalized = String(text || "").replace(/\r/g, "\n");
    if (!normalized.trim()) {
      return [];
    }
    var lines = normalized.split(/\n+/).map(function (line) {
      return line.trim();
    }).filter(Boolean);
    if (collectOptions.maxParagraphs) {
      lines = lines.slice(0, collectOptions.maxParagraphs);
    }
    return lines.map(function (line, index) {
      return {
        index: index + 1,
        text: limitTextLength(line, collectOptions.maxParagraphTextLength),
        styleName: "Normal",
        fontName: "",
        fontSize: null,
        bold: false,
        italic: false,
        underline: null,
        alignment: "",
        outlineLevel: 0,
        lineSpacing: null,
        firstLineIndent: null,
        spaceBefore: null,
        spaceAfter: null,
        leftIndent: null,
        rightIndent: null
      };
    });
  }

  function collectParagraphs(document, options) {
    var collectOptions = normalizeCollectOptions(options);
    var collection = getParagraphCollection(document);
    var count = readCollectionCount(collection);
    if (collectOptions.maxParagraphs) {
      count = Math.min(count, collectOptions.maxParagraphs);
    }
    var items = [];
    for (var i = 1; i <= count; i += 1) {
      var paragraph = getCollectionItem(collection, i);
      if (!paragraph) {
        continue;
      }
      var font = readFont(paragraph);
      var paragraphFormat = readParagraphFormat(paragraph);
      items.push({
        index: i,
        text: limitTextLength(readText(paragraph), collectOptions.maxParagraphTextLength),
        styleName: readStyleName(paragraph),
        fontName: toSafeString(firstDefined(safeRead(font, "NameFarEast"), safeRead(font, "Name")), ""),
        fontSize: normalizeFontSize(safeRead(font, "Size")),
        bold: Boolean(safeRead(font, "Bold")),
        italic: Boolean(safeRead(font, "Italic")),
        underline: normalizeInteger(firstDefined(safeRead(font, "Underline"), null)),
        alignment: normalizeAlignmentValue(safeRead(paragraphFormat, "Alignment"), ""),
        outlineLevel: normalizeInteger(firstDefined(safeRead(paragraphFormat, "OutlineLevel"), 0)),
        lineSpacing: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LineSpacing"), safeRead(paragraphFormat, "lineSpacing"), null)),
        firstLineIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "FirstLineIndent"), safeRead(paragraphFormat, "firstLineIndent"), null)),
        spaceBefore: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceBefore"), safeRead(paragraphFormat, "spaceBefore"), null)),
        spaceAfter: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceAfter"), safeRead(paragraphFormat, "spaceAfter"), null)),
        leftIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LeftIndent"), safeRead(paragraphFormat, "leftIndent"), null)),
        rightIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "RightIndent"), safeRead(paragraphFormat, "rightIndent"), null))
      });
    }
    if (items.length) {
      return items;
    }
    if (collectOptions.avoidFallbackTextRead) {
      return [];
    }
    return collectParagraphsFromText(readDocumentText(document), collectOptions);
  }

  function collectParagraphsFromSelectionSources(selectionSources, selectedText, options) {
    var sources = Array.isArray(selectionSources) ? selectionSources : [selectionSources];
    var collectOptions = normalizeCollectOptions(options);
    var paragraphs;
    var index;
    for (index = 0; index < sources.length; index += 1) {
      if (!sources[index]) {
        continue;
      }
      paragraphs = collectParagraphs(sources[index], {
        maxParagraphs: collectOptions.maxParagraphs,
        maxParagraphTextLength: collectOptions.maxParagraphTextLength,
        avoidFallbackTextRead: true
      });
      if (paragraphs.length) {
        return paragraphs;
      }
    }
    return collectParagraphsFromText(selectedText, options);
  }

  function buildDocumentStructure(options) {
    var paragraphs = options.paragraphs || [];
    var headings = options.headings || [];
    return {
      doc_name: options.documentId || "unnamed.docx",
      template_id: options.templateId || "general-office",
      selection_mode: options.selectionMode || "document",
      page_setup: options.pageSetup || {},
      paragraphs: paragraphs.map(function (paragraph) {
        return {
          index: paragraph.index,
          text: paragraph.text || "",
          style_name: paragraph.styleName || paragraph.style_name || "",
          font_family: paragraph.fontName || paragraph.font_family || "",
          font_size_pt: normalizeFontSize(firstDefined(paragraph.fontSize, paragraph.font_size_pt)),
          bold: Boolean(paragraph.bold),
          italic: Boolean(paragraph.italic),
          underline: paragraph.underline || null,
          alignment: normalizeAlignmentValue(paragraph.alignment, ""),
          outline_level: normalizeNumber(firstDefined(paragraph.outlineLevel, paragraph.outline_level)),
          line_spacing: normalizeNumber(firstDefined(paragraph.lineSpacing, paragraph.line_spacing)),
          first_line_indent: normalizeNumber(firstDefined(paragraph.firstLineIndent, paragraph.first_line_indent)),
          space_before: normalizeNumber(firstDefined(paragraph.spaceBefore, paragraph.space_before)),
          space_after: normalizeNumber(firstDefined(paragraph.spaceAfter, paragraph.space_after)),
          left_indent: normalizeNumber(firstDefined(paragraph.leftIndent, paragraph.left_indent)),
          right_indent: normalizeNumber(firstDefined(paragraph.rightIndent, paragraph.right_indent))
        };
      }),
      headings: headings.map(function (heading) {
        return {
          level: heading.level || heading.outlineLevel || 0,
          text: heading.text || "",
          paragraph_index: heading.paragraphIndex || heading.index || null
        };
      }),
      tables: options.tables || [],
      captions: options.captions || [],
      capabilities: {
        page_setup_extracted: Boolean(options.pageSetup && Object.keys(options.pageSetup).length),
        paragraph_style_extracted: paragraphs.length > 0,
        table_extracted: Boolean(options.tables && options.tables.length),
        header_footer_extracted: false
      }
    };
  }

  function normalizeWorkflowProfileData(data, taskType) {
    var source = data && typeof data === "object" ? data : {};
    var profiles = Array.isArray(source.profiles) ? source.profiles : [];
    var normalized = profiles.filter(function (profile) {
      return profile && profile.taskType === taskType && profile.id;
    }).map(function (profile) {
      return {
        id: String(profile.id),
        taskType: taskType,
        name: String(profile.name || "未命名工作流"),
        note: String(profile.note || ""),
        keyConfigured: Boolean(profile.keyConfigured),
        createdAt: String(profile.createdAt || ""),
        updatedAt: String(profile.updatedAt || "")
      };
    });
    var activeId = String(source.activeProfileId || "");
    var activeExists = normalized.some(function (profile) {
      return profile.id === activeId;
    });
    return {
      taskType: taskType,
      activeProfileId: activeExists ? activeId : "",
      profileCount: normalized.length,
      profiles: normalized
    };
  }

  function getActiveWorkflowProfileName(data) {
    var profiles = data && Array.isArray(data.profiles) ? data.profiles : [];
    var activeId = data ? data.activeProfileId : "";
    var index;
    for (index = 0; index < profiles.length; index += 1) {
      if (profiles[index].id === activeId) {
        return profiles[index].name;
      }
    }
    return "尚未配置";
  }

  function canDeleteWorkflowProfile(profile, activeProfileId) {
    return Boolean(profile && profile.id && profile.id !== activeProfileId);
  }

  function workflowProfileStatusText(profile, activeProfileId) {
    if (!profile || !profile.keyConfigured) {
      return "密钥未配置";
    }
    return profile.id === activeProfileId ? "当前使用" : "可切换";
  }

  return {
    normalizeText: normalizeText,
    escapeHtml: escapeHtml,
    renderMarkdown: renderMarkdown,
    buildInlineWritebackRuns: buildInlineWritebackRuns,
    buildMarkdownWritebackBlocks: buildMarkdownWritebackBlocks,
    hasStructuredSmartWriteContent: hasStructuredSmartWriteContent,
    shouldUseStructuredSmartWriteResult: shouldUseStructuredSmartWriteResult,
    formatSmartWriteResult: formatSmartWriteResult,
    buildSmartWritePreviewModel: buildSmartWritePreviewModel,
    renderReadableFormatReview: renderReadableFormatReview,
    buildDocumentReviewRecord: buildDocumentReviewRecord,
    getEffectiveSelectionText: getEffectiveSelectionText,
    getWritableSelection: getWritableSelection,
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection,
    readCollectionCount: readCollectionCount,
    getCollectionItem: getCollectionItem,
    getParagraphCollection: getParagraphCollection,
    collectParagraphs: collectParagraphs,
    collectParagraphsFromSelectionSources: collectParagraphsFromSelectionSources,
    collectParagraphsFromText: collectParagraphsFromText,
    readDocumentText: readDocumentText,
    toSafeString: toSafeString,
    buildDocumentStructure: buildDocumentStructure,
    normalizeWorkflowProfileData: normalizeWorkflowProfileData,
    getActiveWorkflowProfileName: getActiveWorkflowProfileName,
    canDeleteWorkflowProfile: canDeleteWorkflowProfile,
    workflowProfileStatusText: workflowProfileStatusText
  };
});
