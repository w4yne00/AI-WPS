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

  function makeTextHash(value) {
    var text = String(value || "");
    var hash = 2166136261;
    var index;
    for (index = 0; index < text.length; index += 1) {
      hash = Math.imul(hash ^ text.charCodeAt(index), 16777619) >>> 0;
    }
    return ("00000000" + hash.toString(16)).slice(-8);
  }

  function countUnicodeCodePoints(text) {
    return Array.from(String(text == null ? "" : text)).length;
  }

  function validateExcelSmartFillInstruction(value) {
    var text = String(value == null ? "" : value);
    if (countUnicodeCodePoints(text) > 4000) {
      throw new Error("智能填写说明最多 4000 个字符。");
    }
    return text;
  }

  function requireExcelSmartFillInstruction(value) {
    var text = validateExcelSmartFillInstruction(value);
    if (!String(text || "").trim()) {
      throw new Error("请填写需要生成什么。");
    }
    return text;
  }

  function createExcelSmartFillItemId() {
    var randomSource = (typeof globalThis !== "undefined" && globalThis.crypto) ||
      (typeof crypto !== "undefined" ? crypto : null);
    var bytes = [];
    var index;
    var hex = "";
    var buffer;
    if (!randomSource || typeof randomSource.getRandomValues !== "function") {
      throw new Error("当前环境缺少安全随机源，无法生成智能填写项标识。");
    }
    buffer = new Uint8Array(16);
    randomSource.getRandomValues(buffer);
    for (index = 0; index < 16; index += 1) {
      bytes.push(buffer[index]);
    }
    for (index = 0; index < bytes.length; index += 1) {
      hex += ("0" + bytes[index].toString(16)).slice(-2);
    }
    return "sf_" + hex;
  }

  function parseExcelA1Cell(address) {
    var match = String(address || "").replace(/^.*!/, "").match(/\$?([A-Za-z]+)\$?([0-9]+)/);
    var letters;
    var column = 0;
    var index;
    if (!match) {
      return null;
    }
    letters = match[1].toUpperCase();
    for (index = 0; index < letters.length; index += 1) {
      column = column * 26 + (letters.charCodeAt(index) - 64);
    }
    return { row: Number(match[2]), column: column };
  }

  function sanitizeExcelSmartFillSource(source, target) {
    var address = String(source && source.address || "").trim();
    var origin;
    var blocked = {};
    var items = target && Array.isArray(target.items) ? target.items : [];
    if (!source) {
      return source;
    }
    if (!address) {
      origin = { row: 1, column: 1 };
    } else {
      origin = parseExcelA1Cell(address.split(":")[0]);
      if (!origin) {
        throw new Error("智能填写来源必须是可解析的连续区域，不能使用整列或无法定位的地址。");
      }
    }
    items.forEach(function (item) {
      blocked[Number(item.row) + "," + Number(item.column)] = true;
    });
    function blankAt(sheetRow, sheetColumn, value) {
      return blocked[sheetRow + "," + sheetColumn] ? "" : value;
    }
    source.headers = (source.headers || []).map(function (value, columnIndex) {
      return blankAt(origin.row, origin.column + columnIndex, value);
    });
    source.rows = (source.rows || []).map(function (row, rowIndex) {
      return (row || []).map(function (value, columnIndex) {
        return blankAt(origin.row + 1 + rowIndex, origin.column + columnIndex, value);
      });
    });
    source.truncated = false;
    source.snapshotHash = makeTextHash(JSON.stringify({
      sheetName: source.sheetName,
      address: source.address,
      headers: source.headers,
      rows: source.rows
    }));
    return source;
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

    text = text.replace(/(!?)\[([^\]]+)\]\(([^)\s]+)\)/g, function (match, _imagePrefix, label) {
      return storeToken(escapeHtml(label || match));
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
      html.push('<div class="markdown-table-wrap">');
      bodyRows.forEach(function (row) {
        var cells = splitTableRow(row);
        html.push('<div class="markdown-table-block">');
        headers.forEach(function (header, index) {
          html.push(
            '<div class="markdown-table-field"><span class="markdown-table-label">' +
            renderInlineMarkdown(header) +
            '</span><span class="markdown-table-value">' +
            renderInlineMarkdown(cells[index] || "") +
            "</span></div>"
          );
        });
        html.push("</div>");
      });
      html.push("</div>");
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
    "technical-document-template-rules": "技术文档模板规则"
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
      template_id: options.templateId || "technical-document-template-rules",
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
    var profiles = Array.isArray(source.configurations) ? source.configurations :
      (Array.isArray(source.profiles) ? source.profiles : []);
    var normalized = profiles.filter(function (profile) {
      return profile && profile.taskType === taskType && profile.id;
    }).map(function (profile) {
      return {
        id: String(profile.id),
        taskType: taskType,
        name: String(profile.name || "未命名配置"),
        note: String(profile.note || ""),
        keyConfigured: Boolean(profile.keyConfigured),
        complete: typeof profile.complete === "boolean" ? profile.complete : Boolean(profile.keyConfigured),
        accessMethod: String(profile.accessMethod || "workflow_platform"),
        serviceBaseUrl: String(profile.serviceBaseUrl || ""),
        callPath: String(profile.callPath || ""),
        modelName: String(profile.modelName || ""),
        temperature: profile.temperature,
        maxOutputTokens: profile.maxOutputTokens,
        contextWindowTokens: Number(profile.contextWindowTokens || 40000),
        missingFields: Array.isArray(profile.missingFields) ? profile.missingFields : [],
        configVersion: Number(profile.configVersion || 1),
        lastValidation: profile.lastValidation || null,
        createdAt: String(profile.createdAt || ""),
        updatedAt: String(profile.updatedAt || "")
      };
    });
    var activeId = String(source.activeConfigurationId || source.activeProfileId || "");
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
      status = "recovery";
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
      : (typeof setInterval === "function" ? setInterval : function () { return 0; });
    var clearIntervalFn = typeof settings.clearIntervalFn === "function"
      ? settings.clearIntervalFn
      : (typeof clearInterval === "function" ? clearInterval : function () {});
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

  function extractExcelFormulaSelection(range, options) {
    var settings = options || {};
    var maxRows = Number(settings.maxRows || 30);
    var maxColumns = Number(settings.maxColumns || 20);
    var maxCellTextLength = Number(settings.maxCellTextLength || 120);
    var maxFormulaLength = Number(settings.maxFormulaLength || 1000);
    var maxTotalTextLength = Number(settings.maxTotalTextLength || 20000);
    function readOwned(owner, keys) {
      var index;
      var value;
      if (!owner) {
        return undefined;
      }
      for (index = 0; index < keys.length; index += 1) {
        value = safeRead(owner, keys[index]);
        if (typeof value === "function") {
          value = safeCall(value, owner);
        }
        if (typeof value !== "undefined" && value !== null) {
          return value;
        }
      }
      return undefined;
    }

    var rows = readOwned(range, ["Rows", "rows"]);
    var columns = readOwned(range, ["Columns", "columns"]);
    var rowCount = readCollectionCount(rows);
    var columnCount = readCollectionCount(columns);
    var cellsCollection = readOwned(range, ["Cells", "cells"]) || range;
    var capturedRows = Math.min(rowCount, maxRows);
    var capturedColumns = Math.min(columnCount, maxColumns);
    var totalLength = 0;
    var truncated = rowCount > maxRows || columnCount > maxColumns;
    var matrix = [];
    var headers = [];
    var rowIndex;
    var columnIndex;

    function getCell(row, column) {
      var item = safeRead(cellsCollection, "Item") || safeRead(cellsCollection, "item");
      if (typeof item === "function") {
        try {
          return item.call(cellsCollection, row, column);
        } catch (error) {
          return null;
        }
      }
      return safeRead(cellsCollection, row + "," + column) || null;
    }

    function bounded(value, limit) {
      var text = toSafeString(value, "").replace(/\r/g, "").trim();
      var remaining;
      if (text.length > limit) {
        text = text.slice(0, limit);
        truncated = true;
      }
      remaining = Math.max(maxTotalTextLength - totalLength, 0);
      if (text.length > remaining) {
        text = text.slice(0, remaining);
        truncated = true;
      }
      totalLength += text.length;
      return text;
    }

    function readFormula(cell) {
      var hasFormulaValue = resolveScalarValue(readOwned(
        cell,
        ["HasFormula", "hasFormula"]
      ));
      var hasFormulaText;
      var formulaKeys = [
        "Formula",
        "formula",
        "FormulaLocal",
        "formulaLocal",
        "FormulaR1C1",
        "formulaR1C1"
      ];
      var index;
      var formula;

      if (typeof hasFormulaValue === "boolean" && !hasFormulaValue) {
        return "";
      }
      if (typeof hasFormulaValue === "number" && hasFormulaValue === 0) {
        return "";
      }
      if (typeof hasFormulaValue === "string") {
        hasFormulaText = hasFormulaValue.trim().toLowerCase();
        if (hasFormulaText === "false" || hasFormulaText === "0" || hasFormulaText === "no") {
          return "";
        }
      }

      for (index = 0; index < formulaKeys.length; index += 1) {
        formula = toSafeString(readOwned(cell, [formulaKeys[index]]), "")
          .replace(/\r/g, "")
          .trim();
        if (formula.charAt(0) === "=") {
          return bounded(formula, maxFormulaLength);
        }
      }
      return "";
    }

    function readRawValue(cell) {
      return resolveScalarValue(readOwned(
        cell,
        ["Value2", "value2", "Value", "value"]
      ));
    }

    function classifyCell(text, formula, rawValue) {
      if (formula) {
        return "formula";
      }
      if (!text && (typeof rawValue === "undefined" || rawValue === null || rawValue === "")) {
        return "blank";
      }
      if (typeof rawValue === "boolean") {
        return "boolean";
      }
      if (typeof rawValue === "number") {
        return "number";
      }
      if (/^#(?:N\/A|VALUE!|REF!|DIV\/0!|NAME\?|NUM!|NULL!)/i.test(text)) {
        return "error";
      }
      return text ? "text" : "unknown";
    }

    if (!range || !rowCount || !columnCount) {
      throw new Error("未读取到明确选区，请先框选相关表格范围。");
    }

    for (rowIndex = 1; rowIndex <= capturedRows; rowIndex += 1) {
      var row = [];
      for (columnIndex = 1; columnIndex <= capturedColumns; columnIndex += 1) {
        var cell = getCell(rowIndex, columnIndex) || {};
        var rawValue = readRawValue(cell);
        var text = bounded(firstDefined(
          readOwned(cell, ["Text", "text"]),
          rawValue,
          ""
        ), maxCellTextLength);
        var formula = readFormula(cell);
        var address = toSafeString(firstDefined(
          readOwned(cell, ["Address", "address"]),
          ""
        ), "").trim();
        row.push({
          address: address,
          text: text,
          valueType: classifyCell(text, formula, rawValue),
          formula: formula
        });
        if (rowIndex === 1) {
          headers.push(text || "列" + columnIndex);
        }
      }
      matrix.push(row);
    }

    return {
      sheetName: String(settings.sheetName || "").trim(),
      address: toSafeString(firstDefined(
        readOwned(range, ["Address", "address"]),
        ""
      ), "").trim(),
      headers: headers,
      cells: matrix,
      rowCount: rowCount,
      columnCount: columnCount,
      truncated: truncated
    };
  }

  function extractExcelSmartFillPayload(targetRange, sourceRange, options) {
    var settings = options || {};
    var maxItems = Number(settings.maxItems || 500);
    var maxSourceRows = Number(settings.maxSourceRows || 500);
    var maxSourceColumns = Number(settings.maxSourceColumns || 50);
    var maxCellTextLength = Number(settings.maxCellTextLength || 2000);
    var maxTotalTextLength = Number(settings.maxTotalTextLength || 200000);
    var targetOnly = Boolean(settings.targetOnly);
    var sourceOnly = Boolean(settings.sourceOnly);
    var totalLength = 0;

    function readOwned(owner, keys) {
      var index;
      var value;
      if (!owner) {
        return undefined;
      }
      for (index = 0; index < keys.length; index += 1) {
        value = safeRead(owner, keys[index]);
        if (typeof value === "function") {
          value = safeCall(value, owner);
        }
        if (typeof value !== "undefined" && value !== null) {
          return value;
        }
      }
      return undefined;
    }

    function readRangeDimensions(range) {
      var rows = readOwned(range, ["Rows", "rows"]);
      var columns = readOwned(range, ["Columns", "columns"]);
      var areas = readOwned(range, ["Areas", "areas"]);
      var areaCount = readCollectionCount(areas);
      if (areaCount > 1) {
        throw new Error("智能填写目标或来源必须是连续区域，不支持非连续选区。");
      }
      return {
        rows: readCollectionCount(rows),
        columns: readCollectionCount(columns),
        areas: areaCount
      };
    }

    function getCell(range, row, column) {
      var cells = readOwned(range, ["Cells", "cells"]) || range;
      var item = safeRead(cells, "Item") || safeRead(cells, "item");
      if (typeof item === "function") {
        try {
          return item.call(cells, row, column);
        } catch (error) {
          return null;
        }
      }
      return safeRead(cells, row + "," + column) || null;
    }

    function readPropertyState(owner, keys, preserveObject) {
      var keyIndex;
      var rawValue;
      var value;
      if (!owner) {
        return { known: true, present: false, value: undefined };
      }
      for (keyIndex = 0; keyIndex < keys.length; keyIndex += 1) {
        try {
          rawValue = owner[keys[keyIndex]];
          if (typeof rawValue === "function") {
            rawValue = rawValue.call(owner);
          }
        } catch (error) {
          return { known: false, present: true, value: undefined };
        }
        if (typeof rawValue === "undefined" || rawValue === null) {
          continue;
        }
        if (preserveObject) {
          return { known: true, present: true, value: rawValue };
        }
        value = resolveScalarValue(rawValue);
        if (typeof value === "undefined" || value === null) {
          return { known: false, present: true, value: undefined };
        }
        return { known: true, present: true, value: value };
      }
      return { known: true, present: false, value: undefined };
    }

    function readRawValue(cell) {
      var state = readPropertyState(cell, ["Value2", "value2", "Value", "value"], false);
      return state.known && state.present ? state.value : undefined;
    }

    function readFormula(cell) {
      var hasFormula = readBooleanState(cell, ["HasFormula", "hasFormula"]);
      var formulaState = readPropertyState(cell, [
        "Formula", "formula", "FormulaLocal", "formulaLocal", "FormulaR1C1", "formulaR1C1"
      ], false);
      var formula = formulaState.present
        ? toSafeString(formulaState.value, "").replace(/\r/g, "").trim()
        : "";
      if (!hasFormula.known || !formulaState.known) {
        return null;
      }
      return formula.charAt(0) === "=" ? formula : "";
    }

    function readBooleanState(owner, keys) {
      var state = readPropertyState(owner, keys, false);
      var value;
      if (!state.known || !state.present) {
        return { known: state.known, value: null };
      }
      value = state.value;
      if (typeof value === "boolean") {
        return { known: true, value: value };
      }
      if (typeof value === "number" && isFinite(value)) {
        return { known: true, value: value !== 0 };
      }
      if (typeof value === "string") {
        if (/^(true|yes|1|是)$/i.test(value.trim())) {
          return { known: true, value: true };
        }
        if (/^(false|no|0|否)$/i.test(value.trim())) {
          return { known: true, value: false };
        }
      }
      return { known: false, value: null };
    }

    function readSafetyBoolean(owner, keys) {
      var state;
      if (!owner) {
        return false;
      }
      state = readBooleanState(owner, keys);
      return !state.known || state.value === null ? true : state.value;
    }

    function readSafetyObjectBoolean(ownerState, keys) {
      if (!ownerState.known) {
        return true;
      }
      return readSafetyBoolean(ownerState.present ? ownerState.value : null, keys);
    }

    function readProtected(cell) {
      var worksheetState = readPropertyState(cell, ["Worksheet", "worksheet"], true);
      var explicitlyProtected = readBooleanState(cell, ["Protected", "protected"]);
      var locked = readBooleanState(cell, ["Locked", "locked"]);
      var sheetProtected;
      if (!worksheetState.known || !explicitlyProtected.known || !locked.known) {
        return true;
      }
      if (explicitlyProtected.value === true) {
        return true;
      }
      if (locked.value !== true) {
        return false;
      }
      if (!worksheetState.present || !worksheetState.value) {
        return true;
      }
      sheetProtected = readBooleanState(worksheetState.value, [
        "ProtectContents", "protectContents", "ProtectionMode", "protectionMode",
        "Protected", "protected"
      ]);
      return !sheetProtected.known || sheetProtected.value !== false;
    }

    function readCellText(cell, rawValue) {
      return toSafeString(firstDefined(
        readOwned(cell, ["Text", "text"]),
        rawValue,
        ""
      ), "").replace(/\r/g, "");
    }

    function readDisplayedSourceText(cell) {
      var text = readOwned(cell, ["Text", "text"]);
      if (typeof text === "undefined" || text === null) {
        return "";
      }
      return toSafeString(text, "").replace(/\r/g, "");
    }

    function bounded(value) {
      var text = String(value || "");
      var length = countUnicodeCodePoints(text);
      if (length > maxCellTextLength) {
        throw new Error("智能填写单元格文本最多 " + maxCellTextLength + " 个字符，不能静默截断。");
      }
      if (totalLength + length > maxTotalTextLength) {
        throw new Error("智能填写上下文文本总量超过 " + maxTotalTextLength + " 个字符，不能静默截断。");
      }
      totalLength += length;
      return text;
    }

    function classifyCell(text, formula, rawValue, cell) {
      if (formula) {
        return "formula";
      }
      if (!text && (typeof rawValue === "undefined" || rawValue === null || rawValue === "")) {
        return "blank";
      }
      if (typeof rawValue === "boolean") {
        return "boolean";
      }
      if (isDateCell(cell, rawValue)) {
        return "date";
      }
      if (typeof rawValue === "number") {
        return "number";
      }
      if (/^#(?:N\/A|VALUE!|REF!|DIV\/0!|NAME\?|NUM!|NULL!)/i.test(text)) {
        return "error";
      }
      return text ? "text" : "unknown";
    }

    function makeSnapshotHash(item) {
      var source = [
        item.address,
        item.originalValue,
        item.originalValueType,
        item.originalFormula,
        item.isFormula,
        item.isMerged,
        item.isProtected,
        item.isHidden
      ].join("\u0001");
      var hash = 2166136261;
      var index;
      for (index = 0; index < source.length; index += 1) {
        hash = Math.imul(hash ^ source.charCodeAt(index), 16777619) >>> 0;
      }
      return ("00000000" + hash.toString(16)).slice(-8);
    }

    function readSheetName(range, fallback) {
      var worksheet = readOwned(range, ["Worksheet", "worksheet", "Parent", "parent"]);
      return toSafeString(firstDefined(
        settings[fallback + "SheetName"],
        readOwned(worksheet, ["Name", "name"]),
        ""
      ), "").trim();
    }

    var targetDimensions = readRangeDimensions(targetRange);
    var sourceDimensions = readRangeDimensions(sourceRange);
    var targetAddress = toSafeString(readOwned(targetRange, ["Address", "address"]), "").trim();
    var sourceAddress = toSafeString(readOwned(sourceRange, ["Address", "address"]), "").trim();
    var targetItems = [];
    var sourceHeaders = [];
    var sourceRows = [];
    var targetRow;
    var targetColumn;
    var sourceRow;
    var sourceColumn;

    if (!sourceOnly && (!targetRange || !targetDimensions.rows || !targetDimensions.columns)) {
      throw new Error("未读取到明确目标区域，请先选中需要填写的单元格。");
    }
    if (!targetOnly && (!sourceRange || !sourceDimensions.rows || !sourceDimensions.columns)) {
      throw new Error("未读取到明确来源区域，请先选中来源数据。");
    }
    if (!sourceOnly && targetDimensions.rows * targetDimensions.columns > maxItems) {
      throw new Error("智能填写目标最多支持 " + maxItems + " 个单元格。");
    }

    for (targetRow = 1; !sourceOnly && targetRow <= targetDimensions.rows; targetRow += 1) {
      for (targetColumn = 1; targetColumn <= targetDimensions.columns; targetColumn += 1) {
        var targetCell = getCell(targetRange, targetRow, targetColumn) || {};
        var targetRawValue = readRawValue(targetCell);
        var targetRowState = readPropertyState(targetCell, ["EntireRow", "entireRow"], true);
        var targetColumnState = readPropertyState(targetCell, ["EntireColumn", "entireColumn"], true);
        var targetHidden = readSafetyBoolean(targetCell, ["Hidden", "hidden"]) ||
          readSafetyObjectBoolean(targetRowState, ["Hidden", "hidden"]) ||
          readSafetyObjectBoolean(targetColumnState, ["Hidden", "hidden"]);
        var targetFormulaRaw = readFormula(targetCell);
        var targetFormula = bounded(targetFormulaRaw);
        var targetText = bounded(readCellText(targetCell, targetRawValue));
        var targetItem = {
          itemId: "target-" + (targetItems.length + 1),
          address: toSafeString(readOwned(targetCell, ["Address", "address"]), "").trim() ||
            (targetAddress + "#" + targetRow + "," + targetColumn),
          row: normalizeInteger(firstDefined(readOwned(targetCell, ["Row", "row"]), targetRow)) || targetRow,
          column: normalizeInteger(firstDefined(readOwned(targetCell, ["Column", "column"]), targetColumn)) || targetColumn,
          originalValue: targetText,
          originalValueType: classifyCell(targetText, targetFormula, targetRawValue, targetCell),
          originalFormula: targetFormula,
          isFormula: readSafetyBoolean(targetCell, ["HasFormula", "hasFormula"]) || targetFormulaRaw === null || Boolean(targetFormula),
          isMerged: readSafetyBoolean(targetCell, ["MergeCells", "mergeCells", "Merged", "merged"]),
          isProtected: readProtected(targetCell),
          isHidden: targetHidden
        };
        targetItem.snapshotHash = makeSnapshotHash(targetItem);
        targetItems.push(targetItem);
      }
    }

    if (!targetOnly && sourceDimensions.rows > maxSourceRows) {
      throw new Error("智能填写来源最多支持 " + maxSourceRows + " 行，不能静默截断。");
    }
    if (!targetOnly && sourceDimensions.columns > maxSourceColumns) {
      throw new Error("智能填写来源最多支持 " + maxSourceColumns + " 列，不能静默截断。");
    }
    var capturedSourceRows = sourceDimensions.rows;
    var capturedSourceColumns = sourceDimensions.columns;
    for (sourceRow = 1; !targetOnly && sourceRow <= capturedSourceRows; sourceRow += 1) {
      var sourceRowValues = [];
      for (sourceColumn = 1; sourceColumn <= capturedSourceColumns; sourceColumn += 1) {
        var sourceCell = getCell(sourceRange, sourceRow, sourceColumn) || {};
        var sourceRawValue = readRawValue(sourceCell);
        var sourceFormula = readFormula(sourceCell);
        var sourceRowState = readPropertyState(sourceCell, ["EntireRow", "entireRow"], true);
        var sourceColumnState = readPropertyState(sourceCell, ["EntireColumn", "entireColumn"], true);
        var sourceHidden = readSafetyBoolean(sourceCell, ["Hidden", "hidden"]) ||
          readSafetyObjectBoolean(sourceRowState, ["Hidden", "hidden"]) ||
          readSafetyObjectBoolean(sourceColumnState, ["Hidden", "hidden"]);
        var sourceHasFormula = readSafetyBoolean(sourceCell, ["HasFormula", "hasFormula"]);
        sourceRowValues.push(sourceHidden || sourceHasFormula || sourceFormula === null || sourceFormula
          ? ""
          : bounded(readDisplayedSourceText(sourceCell)));
      }
      if (sourceRow === 1) {
        sourceHeaders = sourceRowValues;
      } else {
        sourceRows.push(sourceRowValues);
      }
    }

    var result = {
      workbookId: toSafeString(settings.workbookId, "active-workbook") || "active-workbook",
      scene: "excel",
      userInstruction: ""
    };
    if (!sourceOnly) {
      result.target = {
        sheetName: readSheetName(targetRange, "target"),
        address: targetAddress || "target",
        columnHeader: bounded(toSafeString(settings.targetColumnHeader, "")),
        rowContext: Array.isArray(settings.targetRowContext)
          ? settings.targetRowContext.map(function (value) {
            return bounded(String(value || ""));
          })
          : [],
        items: targetItems
      };
    }
    if (!targetOnly) {
      result.source = {
        sheetName: readSheetName(sourceRange, "source"),
        address: sourceAddress,
        headers: sourceHeaders,
        rows: sourceRows,
        rowCount: sourceRows.length,
        columnCount: capturedSourceColumns,
        truncated: false
      };
      if (result.target) {
        sanitizeExcelSmartFillSource(result.source, result.target);
      }
      result.source.snapshotHash = makeTextHash(JSON.stringify({
        sheetName: result.source.sheetName,
        address: result.source.address,
        headers: result.source.headers,
        rows: result.source.rows
      }));
    }
    return result;
  }

  function displayExcelSmartFillSourceAddress(address) {
    var text = String(address || "").trim();
    if (text.indexOf("!") >= 0) {
      text = text.split("!").pop();
    }
    return text.replace(/\$/g, "");
  }

  function formatExcelSmartFillSourceSummary(sheetName, address, headerCount, dataRowCount) {
    if (!sheetName && !address) {
      return "数据范围：未检测到当前选区";
    }
    return "数据范围：" + sheetName + "!" + address + " · " + headerCount + " 行表头 · " + dataRowCount + " 行数据";
  }

  function isExcelSmartFillSafetyStateReady(state) {
    return Boolean(state && state.known === true && state.present === true);
  }

  function readExcelSmartFillBoundCount(owner, keys) {
    var objectState = readSmartFillPropertyState(owner, keys, true);
    var countState;
    var count;
    if (!isExcelSmartFillSafetyStateReady(objectState) || !objectState.value) {
      return { known: false, value: 0 };
    }
    countState = readSmartFillPropertyState(objectState.value, ["Count", "count"], false);
    if (!isExcelSmartFillSafetyStateReady(countState)) {
      return { known: false, value: 0 };
    }
    count = Number(countState.value);
    if (!isFinite(count) || count <= 0) {
      return { known: false, value: 0 };
    }
    return { known: true, value: count };
  }

  function readExcelSmartFillRangeAddress(range) {
    var state = readSmartFillPropertyState(range, ["Address", "address"], false);
    var text;
    if (!isExcelSmartFillSafetyStateReady(state)) {
      return { known: false, value: "" };
    }
    text = String(state.value == null ? "" : state.value).trim();
    if (!text || /^function\b/.test(text)) {
      return { known: false, value: "" };
    }
    return { known: true, value: text };
  }

  function readExcelSmartFillRangeSheetName(range) {
    var worksheetState = readSmartFillPropertyState(range, ["Worksheet", "worksheet"], true);
    var nameState;
    var name;
    if (!isExcelSmartFillSafetyStateReady(worksheetState) || !worksheetState.value) {
      return { known: false, value: "" };
    }
    nameState = readSmartFillPropertyState(worksheetState.value, ["Name", "name"], false);
    if (!isExcelSmartFillSafetyStateReady(nameState)) {
      return { known: false, value: "" };
    }
    name = String(nameState.value == null ? "" : nameState.value).trim();
    if (!name) {
      return { known: false, value: "" };
    }
    return { known: true, value: name };
  }

  function canRetryExcelSmartFillFromFrozenSource(source, items) {
    return Boolean(
      source &&
      Array.isArray(source.rows) &&
      source.rows.length > 0 &&
      Array.isArray(items) &&
      items.length > 0
    );
  }

  function readExcelSmartFillSourceMetadata(range, options) {
    var settings = options || {};
    var maxDataRows = Number(settings.maxSourceRows || 500);
    var maxSourceColumns = Number(settings.maxSourceColumns || 50);
    var addressState = range ? readExcelSmartFillRangeAddress(range) : { known: false, value: "" };
    var sheetState = range ? readExcelSmartFillRangeSheetName(range) : { known: false, value: "" };
    var expectedSheet = String(settings.sourceSheetName || settings.sheetName || "").trim();
    var rowsState = range ? readExcelSmartFillBoundCount(range, ["Rows", "rows"]) : { known: false, value: 0 };
    var columnsState = range ? readExcelSmartFillBoundCount(range, ["Columns", "columns"]) : { known: false, value: 0 };
    var areasState = range ? readExcelSmartFillBoundCount(range, ["Areas", "areas"]) : { known: true, value: 1 };
    var rawAddress = addressState.known ? addressState.value : "";
    var address = displayExcelSmartFillSourceAddress(rawAddress);
    var sheetName = sheetState.known ? sheetState.value : "";
    var rows = rowsState.known ? rowsState.value : 0;
    var columns = columnsState.known ? columnsState.value : 0;
    var areas = areasState.known ? areasState.value : 0;
    var headerCount = 0;
    var dataRowCount = 0;
    var summary;
    function fail(error, extra) {
      extra = extra || {};
      return {
        ok: false,
        error: error,
        summary: extra.summary || summary || "数据范围：未检测到当前选区",
        sheetName: extra.sheetName != null ? extra.sheetName : sheetName,
        address: extra.address != null ? extra.address : address,
        headerCount: extra.headerCount != null ? extra.headerCount : headerCount,
        dataRowCount: extra.dataRowCount != null ? extra.dataRowCount : dataRowCount,
        rawAddress: rawAddress,
        rowCount: rows,
        columnCount: columns
      };
    }

    if (!range || !rowsState.known || !columnsState.known || !rows || !columns) {
      return fail("未读取到明确来源区域，请先选中来源数据。", {
        summary: "数据范围：未检测到当前选区",
        headerCount: 0,
        dataRowCount: 0
      });
    }

    headerCount = 1;
    dataRowCount = Math.max(rows - 1, 0);
    summary = formatExcelSmartFillSourceSummary(
      sheetName || "当前工作表",
      address || "未识别地址",
      headerCount,
      dataRowCount
    );

    if (!addressState.known || !parseExcelA1Cell(address || rawAddress)) {
      return fail("无法读取来源地址，请重新选择来源范围。");
    }

    if (!areasState.known || areas > 1) {
      return fail("来源必须是同一工作表中的连续矩形区域。");
    }

    if (!sheetState.known || !sheetName) {
      return fail("无法证明来源属于同一工作表。");
    }
    if (expectedSheet && expectedSheet !== sheetName) {
      return fail("无法证明来源属于同一工作表。");
    }

    if (dataRowCount < 1) {
      return fail("来源必须包含一行表头和至少一行数据。", { dataRowCount: 0 });
    }

    if (columns > maxSourceColumns) {
      return fail("智能填写来源最多支持 " + maxSourceColumns + " 列，不能静默截断。");
    }

    if (dataRowCount > maxDataRows) {
      return fail("来源数据行最多 " + maxDataRows + " 行。");
    }

    return {
      ok: true,
      error: "",
      summary: summary,
      sheetName: sheetName,
      address: address,
      headerCount: headerCount,
      dataRowCount: dataRowCount,
      rawAddress: rawAddress,
      rowCount: rows,
      columnCount: columns
    };
  }

  function analyzeExcelSmartFillSourceRange(range, options) {
    var settings = options || {};
    var metadata = readExcelSmartFillSourceMetadata(range, settings);
    var maxCellTextLength = Number(settings.maxCellTextLength || 2000);
    var maxTotalTextLength = Number(settings.maxTotalTextLength || 200000);
    var sheetName = metadata.sheetName;
    var rawAddress = metadata.rawAddress;
    var address = metadata.address;
    var rows = metadata.rowCount;
    var columns = metadata.columnCount;
    var headerCount = 0;
    var dataRowCount = 0;
    var headers = [];
    var sourceRows = [];
    var dataSheetRows = [];
    var rowIndex;
    var columnIndex;
    var cell;
    var hidden;
    var merged;
    var hasHidden = false;
    var hasMerged = false;
    var hasUnreadSafety = false;
    var displayed;
    var hiddenState;
    var rowState;
    var columnState;
    var rowHidden;
    var columnHidden;
    var mergedState;
    var formulaState;
    var textState;
    var totalLength = 0;
    var summary;

    function getCell(row, column) {
      var cells = range && range.Cells;
      if (!cells || typeof cells.Item !== "function") {
        return null;
      }
      return cells.Item(row, column);
    }

    function bounded(text) {
      var value = String(text || "");
      var length = countUnicodeCodePoints(value);
      if (length > maxCellTextLength) {
        throw new Error("智能填写单元格文本最多 " + maxCellTextLength + " 个字符，不能静默截断。");
      }
      if (totalLength + length > maxTotalTextLength) {
        throw new Error("智能填写上下文文本总量超过 " + maxTotalTextLength + " 个字符，不能静默截断。");
      }
      totalLength += length;
      return value;
    }

    if (!metadata.ok) {
      return {
        ok: false,
        error: metadata.error,
        summary: metadata.summary,
        sheetName: sheetName,
        address: address,
        headerCount: metadata.headerCount,
        dataRowCount: metadata.dataRowCount,
        rawAddress: rawAddress,
        headers: [],
        rows: [],
        dataSheetRows: [],
        columnCount: columns
      };
    }

    headerCount = metadata.headerCount;
    dataRowCount = metadata.dataRowCount;
    summary = metadata.summary;

    for (rowIndex = 1; rowIndex <= rows; rowIndex += 1) {
      var rowValues = [];
      for (columnIndex = 1; columnIndex <= columns; columnIndex += 1) {
        cell = getCell(rowIndex, columnIndex);
        if (!cell) {
          hasUnreadSafety = true;
          rowValues.push("");
          continue;
        }
        hiddenState = readSmartFillBooleanState(cell, ["Hidden", "hidden"]);
        rowState = readSmartFillPropertyState(cell, ["EntireRow", "entireRow"], true);
        columnState = readSmartFillPropertyState(cell, ["EntireColumn", "entireColumn"], true);
        rowHidden = isExcelSmartFillSafetyStateReady(rowState)
          ? readSmartFillBooleanState(rowState.value, ["Hidden", "hidden"])
          : { known: false, present: false, value: null };
        columnHidden = isExcelSmartFillSafetyStateReady(columnState)
          ? readSmartFillBooleanState(columnState.value, ["Hidden", "hidden"])
          : { known: false, present: false, value: null };
        mergedState = readSmartFillBooleanState(cell, ["MergeCells", "mergeCells"]);
        formulaState = readSmartFillFormulaState(cell);
        textState = readSmartFillPropertyState(cell, ["Text", "text"], false);
        if (!isExcelSmartFillSafetyStateReady(hiddenState) ||
            !isExcelSmartFillSafetyStateReady(rowHidden) ||
            !isExcelSmartFillSafetyStateReady(columnHidden) ||
            !isExcelSmartFillSafetyStateReady(mergedState) ||
            !formulaState.known ||
            !isExcelSmartFillSafetyStateReady(textState)) {
          hasUnreadSafety = true;
        }
        hidden = hiddenState.value === true || rowHidden.value === true || columnHidden.value === true;
        merged = mergedState.value === true;
        if (hidden) {
          hasHidden = true;
        }
        if (merged) {
          hasMerged = true;
        }
        if (formulaState.isFormula) {
          displayed = "";
        } else if (!textState.present || textState.value == null) {
          displayed = "";
        } else {
          displayed = bounded(String(textState.value).replace(/\r/g, ""));
        }
        rowValues.push(displayed);
      }
      if (rowIndex === 1) {
        headers = rowValues;
      } else {
        sourceRows.push(rowValues);
        dataSheetRows.push(Number(cell && cell.Row) || rowIndex);
      }
    }

    if (hasUnreadSafety) {
      return {
        ok: false,
        error: "无法安全读取来源单元格状态，请取消隐藏或公式单元格后重试。",
        summary: summary,
        sheetName: sheetName,
        address: address,
        headerCount: headerCount,
        dataRowCount: dataRowCount,
        rawAddress: rawAddress,
        headers: headers,
        rows: sourceRows,
        dataSheetRows: dataSheetRows
      };
    }
    if (hasMerged) {
      return {
        ok: false,
        error: "来源不能包含合并单元格。",
        summary: summary,
        sheetName: sheetName,
        address: address,
        headerCount: headerCount,
        dataRowCount: dataRowCount,
        rawAddress: rawAddress,
        headers: headers,
        rows: sourceRows,
        dataSheetRows: dataSheetRows
      };
    }
    if (hasHidden) {
      return {
        ok: false,
        error: "来源不能包含隐藏行、列或单元格。",
        summary: summary,
        sheetName: sheetName,
        address: address,
        headerCount: headerCount,
        dataRowCount: dataRowCount,
        rawAddress: rawAddress,
        headers: headers,
        rows: sourceRows,
        dataSheetRows: dataSheetRows
      };
    }

    return {
      ok: true,
      error: "",
      summary: summary,
      sheetName: sheetName,
      address: address,
      headerCount: headerCount,
      dataRowCount: dataRowCount,
      rawAddress: rawAddress,
      headers: headers,
      rows: sourceRows,
      dataSheetRows: dataSheetRows,
      columnCount: columns
    };
  }

  function inspectExcelSmartFillSourceSelection(range, options) {
    var analysis = readExcelSmartFillSourceMetadata(range, options);
    return {
      ok: analysis.ok,
      error: analysis.error,
      summary: analysis.summary,
      sheetName: analysis.sheetName,
      address: analysis.address,
      headerCount: analysis.headerCount,
      dataRowCount: analysis.dataRowCount
    };
  }

  function extractExcelSmartFillSourcePayload(range, options) {
    var settings = options || {};
    var analysis = analyzeExcelSmartFillSourceRange(range, settings);
    var createItemId = typeof settings.createItemId === "function"
      ? settings.createItemId
      : createExcelSmartFillItemId;
    var source;
    if (!analysis.ok) {
      throw new Error(analysis.error);
    }
    source = {
      sheetName: analysis.sheetName,
      address: analysis.rawAddress,
      headers: analysis.headers,
      rows: analysis.rows,
      rowCount: analysis.rows.length,
      columnCount: analysis.columnCount,
      truncated: false
    };
    source.snapshotHash = makeTextHash(JSON.stringify({
      sheetName: source.sheetName,
      address: source.address,
      headers: source.headers,
      rows: source.rows
    }));
    return {
      workbookId: String(settings.workbookId || "active-workbook"),
      scene: "excel",
      source: source,
      items: analysis.rows.map(function (_row, index) {
        var sheetRow = analysis.dataSheetRows[index] || (index + 2);
        return {
          itemId: createItemId(),
          sourceRowIndex: index + 1,
          sourceRowLabel: "第 " + sheetRow + " 行"
        };
      })
    };
  }

  function sliceExcelSmartFillSourceForRetry(source, item) {
    var index = Number(item && item.sourceRowIndex) - 1;
    var rows = source && Array.isArray(source.rows) ? source.rows : [];
    var row;
    if (!source || index < 0 || index >= rows.length || !Array.isArray(rows[index])) {
      throw new Error("未找到需要重试的智能填写项。");
    }
    row = rows[index].slice();
    return {
      sheetName: source.sheetName,
      address: source.address,
      snapshotHash: source.snapshotHash || "",
      headers: Array.isArray(source.headers) ? source.headers.slice() : [],
      rows: [row],
      rowCount: 1,
      columnCount: Number(source.columnCount) || row.length,
      truncated: false
    };
  }

  function readExcelSmartFillDisplayCell(cell) {
    var text;
    if (!cell) {
      return "";
    }
    if (cell.hidden || cell.hasFormula || String(cell.formula || "").charAt(0) === "=") {
      return "";
    }
    text = String(cell.text == null ? "" : cell.text);
    if (countUnicodeCodePoints(text) > 2000) {
      throw new Error("智能填写单元格文本最多 2000 个字符，不能静默截断。");
    }
    return text;
  }

  function buildExcelSmartFillDefaultSource(target, readCell) {
    var items = target && Array.isArray(target.items) ? target.items : [];
    var first = items[0];
    var columnCount;
    var column;
    var headers = [];
    var rowValues = [];
    var source;
    if (!first) {
      return {
        sheetName: target && target.sheetName || "",
        address: "",
        headers: [],
        rows: [],
        rowCount: 0,
        columnCount: 0,
        truncated: false
      };
    }
    columnCount = 1;
    items.forEach(function (item) {
      var itemColumn = Number(item.column) || 1;
      if (itemColumn > columnCount) {
        columnCount = itemColumn;
      }
    });
    for (column = 1; column <= columnCount; column += 1) {
      headers.push(readExcelSmartFillDisplayCell(
        typeof readCell === "function" ? readCell(1, column) : null
      ));
    }
    items.forEach(function (item) {
      var itemRow = Number(item.row) || 1;
      var itemColumn = Number(item.column);
      var currentRow = [];
      for (column = 1; column <= columnCount; column += 1) {
        currentRow.push(column === itemColumn
          ? ""
          : readExcelSmartFillDisplayCell(
            typeof readCell === "function" ? readCell(itemRow, column) : null
          ));
      }
      rowValues.push(currentRow);
    });
    if (target) {
      target.columnHeader = headers[Number(first.column) - 1] || "";
      target.rowContext = (rowValues[0] || []).slice();
    }
    source = {
      sheetName: target.sheetName || "",
      address: "",
      headers: headers,
      rows: rowValues,
      rowCount: rowValues.length,
      columnCount: columnCount,
      truncated: false
    };
    source.snapshotHash = makeTextHash(JSON.stringify({
      sheetName: source.sheetName,
      address: source.address,
      headers: source.headers,
      rows: source.rows
    }));
    return source;
  }

  function buildExcelSmartFillReadonlyPreview(data, targets) {
    var items = data && Array.isArray(data.items) ? data.items : [];
    var targetList = Array.isArray(targets) ? targets : [];
    var html = [
      '<div class="smart-fill-preview-head">',
      "<strong>智能填写预览</strong>",
      '<span class="field-hint">写入前请核对生成结果；本页为只读预览。</span>',
      "</div>"
    ];
    function targetAddress(itemId) {
      var index;
      for (index = 0; index < targetList.length; index += 1) {
        if (targetList[index] && targetList[index].itemId === itemId) {
          return targetList[index].address || itemId;
        }
      }
      return itemId;
    }
    if (!items.length) {
      html.push('<p class="field-hint">未返回可展示的目标结果。</p>');
      return html.join("");
    }
    html.push('<div class="smart-fill-result-list">');
    items.forEach(function (item) {
      var completed = item && item.status === "completed";
      var failed = item && item.status === "failed";
      var unprocessed = item && item.status === "unprocessed";
      var value = completed ? String(item.value == null ? "" : item.value) : "";
      var statusLabel = completed ? "可写入" : (failed ? "失败" : (unprocessed ? "未处理" : "信息不足"));
      var statusClass = completed
        ? "is-complete"
        : (failed ? "is-failed" : (unprocessed ? "is-unprocessed" : "is-insufficient"));
      html.push(
        '<article class="smart-fill-result-item">',
        '<div class="smart-fill-result-meta">',
        "<span>" + escapeHtml(targetAddress(item.itemId)) + "</span>",
        '<span class="smart-fill-result-status ' + statusClass + '">' +
          statusLabel + "</span>",
        "</div>",
        '<p class="smart-fill-result-value">' + escapeHtml(completed ? value : statusLabel) + "</p>",
        "</article>"
      );
    });
    html.push("</div>");
    return html.join("");
  }

  function createExcelSmartFillPreview(result) {
    return {
      result: result || null,
      consumed: false
    };
  }

  function consumeExcelSmartFillPreview(preview) {
    if (!preview || preview.consumed || !preview.result) {
      throw new Error("同一预览不能重复提交写入。");
    }
    preview.consumed = true;
    preview.result = null;
    return preview;
  }

  function describeExcelSmartFillHostCell(displayedText, flags) {
    var options = flags || {};
    return {
      text: displayedText == null ? "" : String(displayedText),
      hidden: options.hidden === true,
      hasFormula: options.hasFormula === true,
      formula: String(options.formula || ""),
      comment: ""
    };
  }

  function finalizeExcelSmartFillWriteSuccess(preview) {
    try {
      consumeExcelSmartFillPreview(preview);
    } catch (error) {
      if (preview) {
        preview.consumed = true;
        preview.result = null;
      }
    }
    return preview;
  }

  function validateExcelSmartFillTarget(target) {
    var items = target && Array.isArray(target.items) ? target.items : [];
    var firstRow;
    var firstColumn;
    if (!items.length) {
      throw new Error("未读取到明确目标区域，请先选中需要填写的单元格。");
    }
    firstRow = Number(items[0].row);
    firstColumn = Number(items[0].column);
    if (!isFinite(firstRow) || !isFinite(firstColumn)) {
      throw new Error("智能填写目标缺少有效的行列坐标。");
    }
    items.forEach(function (item, index) {
      if (Number(item.column) !== firstColumn) {
        throw new Error("智能填写目标必须是连续的单列区域。");
      }
      if (Number(item.row) !== firstRow + index) {
        throw new Error("智能填写目标必须是连续的单列区域。");
      }
      if (item.isFormula || item.isMerged || item.isProtected || item.isHidden ||
          ["blank", "text", "number", "boolean", "date"].indexOf(item.originalValueType || "blank") === -1) {
        throw new Error("目标区域包含公式、合并、受保护或隐藏单元格，无法执行智能填写。");
      }
    });
    return true;
  }

  function scalarText(value) {
    return toSafeString(value, "").replace(/\r/g, "");
  }

  function readSmartFillPropertyState(owner, keys, preserveObject) {
    var keyIndex;
    var rawValue;
    var value;
    if (!owner) {
      return { known: true, present: false, value: undefined };
    }
    for (keyIndex = 0; keyIndex < keys.length; keyIndex += 1) {
      try {
        rawValue = owner[keys[keyIndex]];
        if (typeof rawValue === "function") {
          rawValue = rawValue.call(owner);
        }
      } catch (error) {
        return { known: false, present: true, value: undefined };
      }
      if (typeof rawValue === "undefined" || rawValue === null) {
        continue;
      }
      if (preserveObject) {
        return { known: true, present: true, value: rawValue };
      }
      value = resolveScalarValue(rawValue);
      if (typeof value === "undefined" || value === null) {
        return { known: false, present: true, value: undefined };
      }
      return { known: true, present: true, value: value };
    }
    return { known: true, present: false, value: undefined };
  }

  function isDateNumberFormat(fmt) {
    var cleaned;
    if (typeof fmt !== "string") {
      return false;
    }
    cleaned = fmt.replace(/"[^"]*"/g, "");
    return /[yYmMdDhHsS]/.test(cleaned) && !/^\s*0(?:\.0+)?%?\s*$/.test(cleaned);
  }

  function isDateCell(cell, rawValue) {
    var formatState;
    if (rawValue instanceof Date) {
      return true;
    }
    if (typeof rawValue === "number" && cell) {
      formatState = readSmartFillPropertyState(cell, [
        "NumberFormat", "numberFormat", "NumberFormatLocal", "numberFormatLocal"
      ], false);
      if (formatState && formatState.present && isDateNumberFormat(formatState.value)) {
        return true;
      }
    }
    return false;
  }

  function readSmartFillBooleanState(owner, keys) {
    var state = readSmartFillPropertyState(owner, keys, false);
    var value;
    if (!state.known || !state.present) {
      return { known: state.known, present: state.present, value: null };
    }
    value = state.value;
    if (typeof value === "boolean") {
      return { known: true, present: true, value: value };
    }
    if (typeof value === "number" && isFinite(value)) {
      return { known: true, present: true, value: value !== 0 };
    }
    if (typeof value === "string") {
      if (/^(true|yes|1|是)$/i.test(value.trim())) {
        return { known: true, present: true, value: true };
      }
      if (/^(false|no|0|否)$/i.test(value.trim())) {
        return { known: true, present: true, value: false };
      }
    }
    return { known: false, present: true, value: null };
  }

  function readSmartFillFormulaState(cell) {
    var hasFormula = readSmartFillBooleanState(cell, ["HasFormula", "hasFormula"]);
    var formulaState = readSmartFillPropertyState(cell, [
      "Formula", "formula", "FormulaLocal", "formulaLocal", "FormulaR1C1", "formulaR1C1"
    ], false);
    var formula = formulaState.present ? scalarText(formulaState.value).trim() : "";
    if (!hasFormula.known || !formulaState.known) {
      return { known: false, value: "", isFormula: false };
    }
    return {
      known: true,
      value: formula.charAt(0) === "=" ? formula : "",
      isFormula: hasFormula.value === true || formula.charAt(0) === "="
    };
  }

  function readSmartFillProtectedState(cell) {
    var worksheetState = readSmartFillPropertyState(cell, ["Worksheet", "worksheet"], true);
    var explicitlyProtected = readSmartFillBooleanState(cell, ["Protected", "protected"]);
    var locked = readSmartFillBooleanState(cell, ["Locked", "locked"]);
    var sheetProtected;
    if (!worksheetState.known || !explicitlyProtected.known || !locked.known) {
      return { known: false, value: false };
    }
    if (explicitlyProtected.value === true) {
      return { known: true, value: true };
    }
    if (locked.value !== true) {
      return { known: true, value: false };
    }
    if (!worksheetState.present || !worksheetState.value) {
      return { known: true, value: true };
    }
    sheetProtected = readSmartFillBooleanState(worksheetState.value, [
      "ProtectContents", "protectContents", "ProtectionMode", "protectionMode",
      "Protected", "protected"
    ]);
    if (!sheetProtected.known) {
      return { known: true, value: true };
    }
    return { known: true, value: sheetProtected.value !== false };
  }

  function readSmartFillHiddenState(cell) {
    var direct = readSmartFillBooleanState(cell, ["Hidden", "hidden"]);
    var rowOwner = readSmartFillPropertyState(cell, ["EntireRow", "entireRow"], true);
    var columnOwner = readSmartFillPropertyState(cell, ["EntireColumn", "entireColumn"], true);
    var rowHidden;
    var columnHidden;
    if (!direct.known || !rowOwner.known || !columnOwner.known) {
      return { known: false, value: false };
    }
    rowHidden = readSmartFillBooleanState(rowOwner.present ? rowOwner.value : null, ["Hidden", "hidden"]);
    columnHidden = readSmartFillBooleanState(columnOwner.present ? columnOwner.value : null, ["Hidden", "hidden"]);
    if (!rowHidden.known || !columnHidden.known) {
      return { known: false, value: false };
    }
    return {
      known: true,
      value: direct.value === true || rowHidden.value === true || columnHidden.value === true
    };
  }

  function classifySmartFillSnapshotValue(text, formula, rawValue, cell) {
    if (formula) {
      return "formula";
    }
    if (!text && (typeof rawValue === "undefined" || rawValue === null || rawValue === "")) {
      return "blank";
    }
    if (typeof rawValue === "boolean") {
      return "boolean";
    }
    if (isDateCell(cell, rawValue)) {
      return "date";
    }
    if (typeof rawValue === "number") {
      return "number";
    }
    if (/^#(?:N\/A|VALUE!|REF!|DIV\/0!|NAME\?|NUM!|NULL!)/i.test(text)) {
      return "error";
    }
    return text ? "text" : "unknown";
  }

  function readSmartFillCellSnapshot(cell) {
    var rawState = readSmartFillPropertyState(cell, ["Value2", "value2", "Value", "value"], false);
    var textState = readSmartFillPropertyState(cell, ["Text", "text"], false);
    var formulaState = readSmartFillFormulaState(cell);
    var mergedState = readSmartFillBooleanState(cell, ["MergeCells", "mergeCells", "Merged", "merged"]);
    var protectedState = readSmartFillProtectedState(cell);
    var hiddenState = readSmartFillHiddenState(cell);
    var rawValue;
    var text;
    if (!rawState.known || !textState.known ||
        !formulaState.known || !mergedState.known || !protectedState.known ||
        !hiddenState.known) {
      return { readable: false };
    }
    if (!rawState.present) {
      text = scalarText(textState.present ? textState.value : "");
      if (text !== "") {
        return { readable: false };
      }
      rawValue = undefined;
    } else {
      rawValue = rawState.value;
      text = scalarText(textState.present ? textState.value : rawValue);
    }
    return {
      readable: true,
      text: text,
      formula: formulaState.value,
      isFormula: formulaState.isFormula,
      isMerged: mergedState.value === true,
      isProtected: protectedState.value === true,
      isHidden: hiddenState.value === true,
      rawValue: rawValue,
      valueType: classifySmartFillSnapshotValue(text, formulaState.value, rawValue, cell)
    };
  }

  function sameSmartFillSnapshot(item, current) {
    return String(item.originalValue || "") === current.text &&
      String(item.originalFormula || "") === current.formula &&
      Boolean(item.isFormula) === current.isFormula &&
      Boolean(item.isMerged) === current.isMerged &&
      Boolean(item.isProtected) === current.isProtected &&
      Boolean(item.isHidden) === current.isHidden &&
      (!item.originalValueType || item.originalValueType === current.valueType);
  }

  function sameSmartFillSnapshotState(expected, current) {
    var rawValuesEqual = Boolean(
      expected && current && (
        expected.rawValue === current.rawValue ||
        (expected.valueType === "blank" && current.valueType === "blank")
      )
    );
    if (expected && current && !rawValuesEqual &&
        typeof expected.rawValue === "number" && typeof current.rawValue === "number" &&
        isNaN(expected.rawValue) && isNaN(current.rawValue)) {
      rawValuesEqual = true;
    }
    if (expected && current && !rawValuesEqual &&
        expected.rawValue instanceof Date && current.rawValue instanceof Date &&
        expected.rawValue.getTime() === current.rawValue.getTime()) {
      rawValuesEqual = true;
    }
    return Boolean(expected && current && current.readable && rawValuesEqual &&
      expected.text === current.text &&
      expected.formula === current.formula &&
      expected.isFormula === current.isFormula &&
      expected.isMerged === current.isMerged &&
      expected.isProtected === current.isProtected &&
      expected.isHidden === current.isHidden &&
      expected.valueType === current.valueType);
  }

  function smartFillWriteValueMatches(current, value, valueType) {
    if (!current || !current.readable || current.isFormula || current.formula) {
      return false;
    }
    if (valueType === "number") {
      if (current.valueType !== "number" || typeof current.rawValue !== "number") {
        return false;
      }
      if (isNaN(value)) {
        return isNaN(current.rawValue);
      }
      return current.rawValue === value || Math.abs(current.rawValue - value) < 1e-9;
    }
    if (valueType === "text") {
      if (current.valueType !== "text" && current.valueType !== "unknown") {
        return false;
      }
      var expectedStr = String(value);
      var textMatches = current.text === expectedStr || current.text === "'" + expectedStr;
      var rawMatches = typeof current.rawValue === "string" &&
        (current.rawValue === expectedStr || current.rawValue === "'" + expectedStr);
      return textMatches && rawMatches;
    }
    return false;
  }

  function detectExcelSmartFillConflicts(targetItems, getCell, candidateItemIds) {
    var items = Array.isArray(targetItems) ? targetItems : [];
    var conflicts = [];
    var filterActive = Array.isArray(candidateItemIds);
    var candidateIdMap = {};
    if (typeof getCell !== "function") {
      return { hasConflict: false, conflicts: [] };
    }
    if (filterActive) {
      candidateItemIds.forEach(function (id) {
        if (id) {
          candidateIdMap[id] = true;
        }
      });
    }
    items.forEach(function (item) {
      if (filterActive && !candidateIdMap[item.itemId]) {
        return;
      }
      var cell = getCell(item);
      var current;
      if (!cell) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "cell_unavailable" });
        return;
      }
      current = readSmartFillCellSnapshot(cell);
      if (!current.readable) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "unreadable" });
        return;
      }
      if (current.isFormula || current.formula) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "formula_detected" });
        return;
      }
      if (current.isMerged) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "merged" });
        return;
      }
      if (current.isProtected) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "protected" });
        return;
      }
      if (current.isHidden) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "hidden" });
        return;
      }
      if (!sameSmartFillSnapshot(item, current)) {
        conflicts.push({ itemId: item.itemId, address: item.address, reason: "content_changed" });
      }
    });
    return {
      hasConflict: conflicts.length > 0,
      conflicts: conflicts
    };
  }

  function buildExcelSmartFillEditorPreview(data, targets, drafts, options) {
    var items = data && Array.isArray(data.items) ? data.items : [];
    var targetList = Array.isArray(targets) ? targets : [];
    var draftList = Array.isArray(drafts) ? drafts : [];
    var settings = options || {};
    var retryEnabled = settings.retryEnabled !== false;
    var draftById = {};
    var targetById = {};
    var itemById = {};
    var ordered = [];
    var html = [
      '<div class="smart-fill-preview-head">',
      "<strong>智能填写预览</strong>",
      '<span class="field-hint">可编辑、取消勾选或逐项重试；未勾选项不会写入。</span>',
      "</div>"
    ];

    draftList.forEach(function (draft) {
      if (draft && draft.itemId) {
        draftById[draft.itemId] = draft;
      }
    });

    targetList.forEach(function (target) {
      if (target && target.itemId) {
        targetById[target.itemId] = target;
      }
    });

    items.forEach(function (item) {
      if (item && item.itemId) {
        itemById[item.itemId] = item;
      }
    });

    if (targetList.length) {
      targetList.forEach(function (target) {
        if (target && target.itemId) {
          ordered.push(itemById[target.itemId] || target);
        }
      });
    } else {
      ordered = items.slice();
    }

    if (!ordered.length) {
      html.push('<p class="field-hint">未返回可展示的目标结果。</p>');
      return html.join("");
    }

    html.push('<div class="smart-fill-result-list">');
    ordered.forEach(function (item) {
      var itemId = item ? item.itemId : "";
      var target = targetById[itemId] || {};
      var draft = draftById[itemId] || {};
      var address = target.sourceRowLabel || (item && item.sourceRowLabel) || target.address || itemId;
      var status = draft.status || (item ? item.status : "unprocessed");
      var completed = status === "completed";
      var insufficient = status === "insufficient_information";
      var failed = status === "failed";
      var unprocessed = status === "unprocessed";
      var conflict = status === "write_conflict";

      var statusLabel = completed
        ? "可写入"
        : (conflict
          ? "写入冲突"
          : (failed
            ? "失败"
            : (unprocessed ? "未处理" : "信息不足")));

      var statusClass = completed
        ? "is-complete"
        : (conflict
          ? "is-conflict"
          : (failed
            ? "is-failed"
            : (unprocessed ? "is-unprocessed" : "is-insufficient")));

      var value = typeof draft.value !== "undefined"
        ? String(draft.value == null ? "" : draft.value)
        : (completed ? String(item.value == null ? "" : item.value) : "");

      var valueType = draft.valueType || (item && item.valueType) || "text";
      var inputType = valueType === "number" ? "number" : "text";

      var checked = typeof draft.selected !== "undefined"
        ? Boolean(draft.selected)
        : (completed && !conflict);

      html.push(
        '<article class="smart-fill-result-item" data-smart-fill-item-id="' + escapeHtml(itemId) + '">',
        '<div class="smart-fill-result-meta">',
        '<label class="smart-fill-result-select">',
        '<input type="checkbox" data-smart-fill-select="' + escapeHtml(itemId) + '"' +
          (checked ? " checked" : "") + ' aria-label="选择 ' + escapeHtml(address) + '">',
        "<span>" + escapeHtml(address) + "</span>",
        "</label>",
        '<span class="smart-fill-result-status ' + statusClass + '">' + statusLabel + "</span>",
        "</div>",
        '<div class="smart-fill-result-edit">',
        '<input class="smart-fill-result-value" type="' + inputType + '" data-smart-fill-value-input="' +
          escapeHtml(itemId) + '" value="' + escapeHtml(value) + '"' +
          (inputType === "number" ? ' step="any"' : "") +
          ' aria-label="编辑 ' + escapeHtml(address) + '">',
        retryEnabled
          ? ('<button type="button" class="ghost-action mini-button" data-smart-fill-retry="' +
            escapeHtml(itemId) + '">重新生成此项</button>')
          : "",
        "</div>",
        "</article>"
      );
    });
    html.push("</div>");
    return html.join("");
  }

  function validateExcelSmartFillDraft(draft) {
    var value;
    var valueType;
    var codePoints;
    if (!draft || !draft.selected) {
      return { isWriteable: false, valid: true, value: "" };
    }
    value = String(draft.value == null ? "" : draft.value);
    if (!value.trim()) {
      return { isWriteable: false, valid: false, error: "填写内容不能为空" };
    }
    valueType = draft.valueType === "number" ? "number" : "text";
    if (valueType === "number") {
      if (!isFinite(Number(value))) {
        return { isWriteable: false, valid: false, error: "数字格式无效" };
      }
    }
    codePoints = Array.from ? Array.from(value).length : value.length;
    if (codePoints > 2000) {
      return { isWriteable: false, valid: false, error: "单单元格文本超出 2000 字符限制" };
    }
    return {
      isWriteable: true,
      valid: true,
      value: valueType === "number" ? Number(value) : value,
      valueType: valueType,
      codePoints: codePoints
    };
  }

  function calculateExcelSmartFillDraftsSummary(drafts, targetItems) {
    var draftList = Array.isArray(drafts) ? drafts : [];
    var targetList = Array.isArray(targetItems) ? targetItems : [];
    var targetById = {};
    var writableCount = 0;
    var overwriteCount = 0;
    var totalCodePoints = 0;

    targetList.forEach(function (target) {
      if (target && target.itemId) {
        targetById[target.itemId] = target;
      }
    });

    draftList.forEach(function (draft) {
      var validation;
      var target;
      if (!draft || !draft.selected) {
        return;
      }
      validation = validateExcelSmartFillDraft(draft);
      if (validation.isWriteable) {
        writableCount += 1;
        totalCodePoints += validation.codePoints || 0;
        target = targetById[draft.itemId];
        if (target && ["text", "number", "boolean", "date"].indexOf(target.originalValueType) >= 0 &&
            String(target.originalValue || "").trim()) {
          overwriteCount += 1;
        }
      }
    });

    return {
      writableCount: writableCount,
      overwriteCount: overwriteCount,
      totalCodePoints: totalCodePoints,
      canWrite: writableCount > 0 && totalCodePoints <= 200000,
      summaryText: writableCount > 0
        ? "将写入 " + writableCount + " 个单元格；未勾选或信息不足项不会写入。"
        : "尚无可写入的智能填写预览。"
    };
  }

  function writeExcelSmartFillCells(targetItems, results, getCell) {
    var items = Array.isArray(targetItems) ? targetItems : [];
    var output = Array.isArray(results) ? results : [];
    var resultById = {};
    var plans = [];
    var written = [];
    var totalPlanCodePoints = 0;
    var index;

    if (items.length !== output.length || typeof getCell !== "function") {
      throw new Error("智能填写结果与目标单元格数量不一致。");
    }
    output.forEach(function (result) {
      if (!result || !result.itemId || resultById[result.itemId]) {
        throw new Error("智能填写结果包含重复或无效的目标标识。");
      }
      resultById[result.itemId] = result;
    });

    for (index = 0; index < items.length; index += 1) {
      var item = items[index];
      var result = resultById[item.itemId];
      var cell;
      var current;
      var strVal;
      var codePoints;
      if (!result) {
        throw new Error("智能填写结果缺少目标单元格。");
      }
      if (result.status === "insufficient_information") {
        plans.push({ item: item, cell: null, result: result, current: null, skip: true });
        continue;
      }
      cell = getCell(item);
      if (!cell) {
        throw new Error("目标单元格不可用，已停止写回。");
      }
      current = readSmartFillCellSnapshot(cell);
      if (!current.readable) {
        throw new Error("目标单元格状态无法安全读取，已停止写回。");
      }
      if (item.isFormula || item.isMerged || item.isProtected || item.isHidden ||
          current.isFormula || current.isMerged || current.isProtected || current.isHidden ||
          current.formula) {
        throw new Error("目标区域包含公式、合并、受保护或隐藏单元格，已停止写回。");
      }
      if (!sameSmartFillSnapshot(item, current)) {
        throw new Error("目标单元格内容已变化，请重新生成预览后再写入。");
      }
      if (result.status !== "completed" || (result.valueType !== "text" && result.valueType !== "number")) {
        throw new Error("智能填写结果不完整，已停止写回。");
      }
      if (result.valueType === "number" &&
          (typeof result.value !== "number" || !isFinite(result.value))) {
        throw new Error("智能填写数字结果无效，已停止写回。");
      }
      if (result.valueType === "text") {
        strVal = String(result.value || "");
        if (!strVal.trim()) {
          throw new Error("智能填写文本结果为空，已停止写回。");
        }
        codePoints = Array.from ? Array.from(strVal).length : strVal.length;
        if (codePoints > 2000) {
          throw new Error("智能填写文本超出 2000 字符限制，已停止写回。");
        }
        totalPlanCodePoints += codePoints;
      }
      plans.push({ item: item, cell: cell, result: result, current: current, skip: false });
    }

    if (totalPlanCodePoints > 200000) {
      throw new Error("智能填写总文本超出 200000 字符限制，已停止写回。");
    }

    try {
      plans.forEach(function (plan) {
        var value;
        var storedValue;
        var afterWrite;
        var entry;
        if (plan.skip) {
          return;
        }
        value = plan.result.valueType === "number" ? plan.result.value : String(plan.result.value);
        storedValue = plan.result.valueType === "text" && /^[=+\-@]/.test(value)
          ? "'" + value
          : value;
        entry = {
          address: plan.item.address || plan.item.itemId || "未知地址",
          cell: plan.cell,
          previousValue: plan.current.rawValue,
          previousSnapshot: plan.current
        };
        written.push(entry);
        plan.cell.Value2 = storedValue;
        afterWrite = readSmartFillCellSnapshot(plan.cell);
        if (!afterWrite.readable || !smartFillWriteValueMatches(afterWrite, value, plan.result.valueType)) {
          throw new Error("写回后未能核对目标地址 " + plan.item.address + "。");
        }
      });
    } catch (error) {
      var rollbackFailures = [];
      written.slice().reverse().forEach(function (entry) {
        try {
          var restoreValue = entry.previousValue;
          if (typeof restoreValue === "undefined" || restoreValue === null) {
            restoreValue = "";
          }
          entry.cell.Value2 = restoreValue;
          if (!sameSmartFillSnapshotState(entry.previousSnapshot, readSmartFillCellSnapshot(entry.cell))) {
            rollbackFailures.push(entry.address || "未知地址");
          }
        } catch (rollbackError) {
          rollbackFailures.push(entry.address || "未知地址");
        }
      });
      var compErr;
      if (rollbackFailures.length) {
        compErr = new Error(
          "智能填写写回失败，已尝试恢复已写入单元格；以下地址需要人工核对：" +
          rollbackFailures.join("、")
        );
        compErr.code = "COMPENSATION_FAILED";
        compErr.rollbackFailures = rollbackFailures;
        compErr.manualReviewAddresses = rollbackFailures;
        compErr.cause = error;
        throw compErr;
      }
      compErr = new Error("智能填写写回失败，已尝试恢复已写入单元格。" +
        (error && error.message ? " " + error.message : ""));
      compErr.code = "COMPENSATION_SUCCEEDED";
      compErr.rollbackFailures = [];
      compErr.cause = error;
      throw compErr;
    }
    return {
      writtenCount: written.length,
      skippedCount: plans.filter(function (plan) { return plan.skip; }).length
    };
  }

  function createExcelSelectionWatcher(options) {
    var settings = options || {};
    var refresh = typeof settings.refresh === "function" ? settings.refresh : function () {};
    var getEventSources = typeof settings.getEventSources === "function"
      ? settings.getEventSources
      : function () { return []; };
    var setTimeoutFn = typeof settings.setTimeoutFn === "function"
      ? settings.setTimeoutFn
      : (typeof setTimeout === "function" ? setTimeout : function () { return 0; });
    var clearTimeoutFn = typeof settings.clearTimeoutFn === "function"
      ? settings.clearTimeoutFn
      : (typeof clearTimeout === "function" ? clearTimeout : function () {});
    var intervalMs = typeof settings.intervalMs === "number" ? settings.intervalMs : 2000;
    var eventName = settings.eventName || "SheetSelectionChange";
    var timerId = null;
    var running = false;
    var eventSource = null;
    var eventRegistered = false;

    function safeRefresh() {
      try {
        refresh();
      } catch (error) {
        // Transient ET object failures are retried by the next host event or fallback poll.
      }
    }

    function clearFallback() {
      if (timerId !== null) {
        clearTimeoutFn(timerId);
        timerId = null;
      }
    }

    function scheduleFallback() {
      clearFallback();
      if (!running) {
        return;
      }
      timerId = setTimeoutFn(function () {
        timerId = null;
        if (!running) {
          return;
        }
        safeRefresh();
        scheduleFallback();
      }, intervalMs);
    }

    function handleSelectionChange() {
      if (!running) {
        return;
      }
      safeRefresh();
      scheduleFallback();
    }

    function registerEvent() {
      var sources;
      var index;
      var candidate;
      var result;
      try {
        sources = getEventSources();
      } catch (error) {
        sources = [];
      }
      if (!Array.isArray(sources)) {
        sources = sources ? [sources] : [];
      }
      for (index = 0; index < sources.length; index += 1) {
        candidate = sources[index];
        if (!candidate || typeof candidate.AddApiEventListener !== "function") {
          continue;
        }
        try {
          result = candidate.AddApiEventListener(eventName, handleSelectionChange);
          if (result === false) {
            continue;
          }
          eventSource = candidate;
          eventRegistered = true;
          return true;
        } catch (error) {
          // Try the next compatible WPS ET event entrypoint before falling back to polling.
        }
      }
      eventSource = null;
      eventRegistered = false;
      return false;
    }

    return {
      start: function () {
        if (running) {
          return;
        }
        running = true;
        safeRefresh();
        registerEvent();
        scheduleFallback();
      },
      stop: function () {
        if (!running) {
          return;
        }
        running = false;
        clearFallback();
        if (eventRegistered && eventSource && typeof eventSource.RemoveApiEventListener === "function") {
          try {
            eventSource.RemoveApiEventListener(eventName);
          } catch (error) {
            // Event cleanup differs across WPS ET builds; stopped polling still prevents reads.
          }
        }
        eventSource = null;
        eventRegistered = false;
      },
      isRunning: function () {
        return running;
      },
      isEventRegistered: function () {
        return eventRegistered;
      }
    };
  }

  function canDeleteWorkflowProfile(profile, activeProfileId) {
    return Boolean(profile && profile.id && profile.id !== activeProfileId);
  }

  function workflowProfileStatusText(profile, activeProfileId) {
    if (!profile || !profile.complete) {
      return "配置不完整";
    }
    return profile.id === activeProfileId ? "当前使用" : "可切换";
  }

  function workflowProfileOptionState(profile, activeProfileId) {
    var item = profile || {};
    var active = Boolean(item.id && item.id === activeProfileId);
    var configured = Boolean(item.complete);
    var name = String(item.name || "未命名配置");
    var method = item.accessMethod === "direct_model" ? "模型直连" : "工作流平台";
    return {
      id: String(item.id || ""),
      label: name + " · " + method,
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

  function normalizeExcelReportList(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) {
        return String(item || "").trim();
      }).filter(Boolean);
    }
    if (typeof value === "string" && value.trim()) {
      return [value.trim()];
    }
    return [];
  }

  function buildExcelAnalysisMarkdown(data) {
    var report = (data && data.structuredReport) || {};
    var findings = normalizeExcelReportList(report.findings);
    var risks = normalizeExcelReportList(report.risks);
    var actions = normalizeExcelReportList(report.actions);
    return [
      "## 数据概览",
      report.overview || "未返回数据概览。",
      "",
      "## 关键发现",
      findings.length ? findings.map(function (item) { return "- " + item; }).join("\n") : "- 未返回关键发现。",
      "",
      "## 风险异常",
      risks.length ? risks.map(function (item) { return "- " + item; }).join("\n") : "- 未返回风险异常。",
      "",
      "## 建议动作",
      actions.length ? actions.map(function (item) { return "- " + item; }).join("\n") : "- 未返回建议动作。"
    ].join("\n");
  }

  function presentExcelAnalysisResultView(input) {
    var source = input || {};
    var result = source.result || {};
    var view = source.view === "plain" ? "plain" : "preview";
    var reportMarkdown = buildExcelAnalysisMarkdown(result);
    var plainText = result.plainText || "";
    if (view === "plain") {
      return {
        presentation: "source",
        displayMarkdown: plainText,
        html: "",
        sourceText: plainText,
        copyText: plainText,
        viewLabels: { preview: "分析报告", plain: "汇报段落" }
      };
    }
    return {
      presentation: "rendered",
      displayMarkdown: reportMarkdown,
      html: renderMarkdown(reportMarkdown),
      sourceText: "",
      copyText: reportMarkdown,
      viewLabels: { preview: "分析报告", plain: "汇报段落" }
    };
  }

  function shouldShowExcelResultViewSwitch(mode) {
    return mode === "excelAnalysis";
  }

  return {
    normalizeText: normalizeText,
    escapeHtml: escapeHtml,
    renderMarkdown: renderMarkdown,
    buildExcelAnalysisMarkdown: buildExcelAnalysisMarkdown,
    presentExcelAnalysisResultView: presentExcelAnalysisResultView,
    shouldShowExcelResultViewSwitch: shouldShowExcelResultViewSwitch,
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
    deriveModelInterfaceState: deriveModelInterfaceState,
    normalizeAdapterHealth: normalizeAdapterHealth,
    createSettingsRefreshController: createSettingsRefreshController,
    extractExcelFormulaSelection: extractExcelFormulaSelection,
    extractExcelSmartFillPayload: extractExcelSmartFillPayload,
    inspectExcelSmartFillSourceSelection: inspectExcelSmartFillSourceSelection,
    extractExcelSmartFillSourcePayload: extractExcelSmartFillSourcePayload,
    sliceExcelSmartFillSourceForRetry: sliceExcelSmartFillSourceForRetry,
    canRetryExcelSmartFillFromFrozenSource: canRetryExcelSmartFillFromFrozenSource,
    displayExcelSmartFillSourceAddress: displayExcelSmartFillSourceAddress,
    createExcelSmartFillItemId: createExcelSmartFillItemId,
    requireExcelSmartFillInstruction: requireExcelSmartFillInstruction,
    validateExcelSmartFillInstruction: validateExcelSmartFillInstruction,
    sanitizeExcelSmartFillSource: sanitizeExcelSmartFillSource,
    buildExcelSmartFillDefaultSource: buildExcelSmartFillDefaultSource,
    buildExcelSmartFillReadonlyPreview: buildExcelSmartFillReadonlyPreview,
    buildExcelSmartFillEditorPreview: buildExcelSmartFillEditorPreview,
    validateExcelSmartFillDraft: validateExcelSmartFillDraft,
    calculateExcelSmartFillDraftsSummary: calculateExcelSmartFillDraftsSummary,
    detectExcelSmartFillConflicts: detectExcelSmartFillConflicts,
    createExcelSmartFillPreview: createExcelSmartFillPreview,
    consumeExcelSmartFillPreview: consumeExcelSmartFillPreview,
    describeExcelSmartFillHostCell: describeExcelSmartFillHostCell,
    finalizeExcelSmartFillWriteSuccess: finalizeExcelSmartFillWriteSuccess,
    validateExcelSmartFillTarget: validateExcelSmartFillTarget,
    writeExcelSmartFillCells: writeExcelSmartFillCells,
    createExcelSelectionWatcher: createExcelSelectionWatcher,
    canDeleteWorkflowProfile: canDeleteWorkflowProfile,
    workflowProfileStatusText: workflowProfileStatusText,
    workflowProfileOptionState: workflowProfileOptionState,
    validateWorkflowProfileDraft: validateWorkflowProfileDraft,
    shouldActivateNewWorkflowProfile: shouldActivateNewWorkflowProfile
  };
});
