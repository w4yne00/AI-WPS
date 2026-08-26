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

  function sha256Text(value) {
    var text = unescape(encodeURIComponent(String(value || "")));
    var maxWord = Math.pow(2, 32);
    var words = [];
    var hash = [];
    var constants = [];
    var primeCounter = 0;
    var candidate = 2;
    var bitLength = text.length * 8;
    var index;
    var isPrime;
    var divisor;

    function rightRotate(number, amount) {
      return (number >>> amount) | (number << (32 - amount));
    }

    while (primeCounter < 64) {
      isPrime = true;
      for (divisor = 2; divisor * divisor <= candidate; divisor += 1) {
        if (candidate % divisor === 0) {
          isPrime = false;
          break;
        }
      }
      if (isPrime) {
        if (primeCounter < 8) {
          hash[primeCounter] = (Math.pow(candidate, 0.5) * maxWord) | 0;
        }
        constants[primeCounter] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
        primeCounter += 1;
      }
      candidate += 1;
    }
    text += "\x80";
    while (text.length % 64 !== 56) {
      text += "\x00";
    }
    for (index = 0; index < text.length; index += 1) {
      words[index >> 2] = words[index >> 2] || 0;
      words[index >> 2] |= text.charCodeAt(index) << ((3 - index) % 4) * 8;
    }
    words.push(Math.floor(bitLength / maxWord));
    words.push(bitLength);

    for (index = 0; index < words.length; index += 16) {
      var working = hash.slice(0);
      var schedule = words.slice(index, index + 16);
      var round;
      for (round = 0; round < 64; round += 1) {
        var word = schedule[round];
        var a = working[0];
        var e = working[4];
        if (round >= 16) {
          var w15 = schedule[round - 15];
          var w2 = schedule[round - 2];
          word = schedule[round] = (
            schedule[round - 16] +
            (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3)) +
            schedule[round - 7] +
            (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10))
          ) | 0;
        }
        var temp1 = (
          working[7] +
          (rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25)) +
          ((e & working[5]) ^ ((~e) & working[6])) +
          constants[round] +
          word
        ) | 0;
        var temp2 = (
          (rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22)) +
          ((a & working[1]) ^ (a & working[2]) ^ (working[1] & working[2]))
        ) | 0;
        working = [
          (temp1 + temp2) | 0,
          working[0],
          working[1],
          working[2],
          (working[3] + temp1) | 0,
          working[4],
          working[5],
          working[6]
        ];
      }
      for (round = 0; round < 8; round += 1) {
        hash[round] = (hash[round] + working[round]) | 0;
      }
    }
    return hash.map(function (word) {
      var hex = (word >>> 0).toString(16);
      return "00000000".slice(hex.length) + hex;
    }).join("");
  }

  function getFullDocumentReviewCapacity(reviewCharacterCount) {
    var count = Number(reviewCharacterCount);
    var tier;
    var initialChunkCount;
    if (!isFinite(count) || count <= 0 || Math.floor(count) !== count) {
      throw new Error("全篇审查字符数必须是正整数。");
    }
    if (count > 120000) {
      throw new Error("全篇审查最多支持 120,000 审查字符，请缩小正文或表格范围。");
    }
    if (count <= 20000) {
      return {
        tier: "single_chunk",
        requiresConfirmation: false,
        initialChunkCount: 1,
        estimatedCallCount: 1,
        callLimit: 8
      };
    }
    tier = count <= 60000 ? "standard" : "large";
    initialChunkCount = Math.ceil(count / 18000);
    return {
      tier: tier,
      requiresConfirmation: tier === "large",
      initialChunkCount: initialChunkCount,
      estimatedCallCount: initialChunkCount + 1,
      callLimit: tier === "large" ? 24 : 16
    };
  }

  function getDeterministicFormatReviewCapacity(reviewCharacterCount) {
    var count = Number(reviewCharacterCount);
    if (!isFinite(count) || count < 0 || Math.floor(count) !== count || count > 120000) {
      return { tier: "rejected", accepted: false, requiresConfirmation: false };
    }
    return {
      tier: count <= 60000 ? "standard" : "large",
      accepted: true,
      requiresConfirmation: false
    };
  }

  function reviewBlockTextValues(block) {
    var values = [];
    if (!block || block.blockType !== "table") {
      return block && block.text ? [block.text] : [];
    }
    (block.rows || []).forEach(function (row) {
      (row.cells || []).forEach(function (cell) {
        if (cell.text) {
          values.push(cell.text);
        }
      });
    });
    (block.nestedTables || []).forEach(function (table) {
      var nested = reviewBlockTextValues({
        blockType: "table",
        rows: table.rows,
        nestedTables: table.nestedTables
      });
      values = values.concat(nested);
    });
    return values;
  }

  function reviewStructureProjection(block) {
    var projection = {
      blockId: block.blockId,
      blockType: block.blockType,
      paragraphIndex: Number(block.paragraphIndex || 0),
      headingLevel: Number(block.headingLevel || 0),
      listLabel: String(block.listLabel || "")
    };
    if (block.blockType !== "table") {
      return projection;
    }
    function projectTable(table) {
      return {
        tableId: String(table.tableId || ""),
        tableIndex: Number(table.tableIndex || 0),
        tablePath: Array.isArray(table.tablePath) ? table.tablePath.map(function (item) {
          return {
            tableIndex: Number(item.tableIndex || 0),
            rowIndex: Number(item.rowIndex || 0),
            columnIndex: Number(item.columnIndex || 0)
          };
        }) : [],
        rows: (table.rows || []).map(function (row) {
          return {
            rowIndex: Number(row.rowIndex || 0),
            cells: (row.cells || []).map(function (cell) {
              return {
                cellId: String(cell.cellId || ""),
                rowIndex: Number(cell.rowIndex || 0),
                columnIndex: Number(cell.columnIndex || 0),
                rowSpan: Number(cell.rowSpan || 1),
                columnSpan: Number(cell.columnSpan || 1),
                mergeId: String(cell.mergeId || ""),
                nestedTableIds: Array.isArray(cell.nestedTableIds) ? cell.nestedTableIds.slice() : []
              };
            })
          };
        }),
        nestedTables: (table.nestedTables || []).map(projectTable)
      };
    }
    projection.table = projectTable(block);
    return projection;
  }

  function reviewStructureSha256(blocks) {
    return sha256Text(JSON.stringify((Array.isArray(blocks) ? blocks : []).map(reviewStructureProjection)));
  }

  function buildFullDocumentReviewBody(paragraphsOrContent, maxReviewCharacters) {
    var content = Array.isArray(paragraphsOrContent)
      ? { paragraphs: paragraphsOrContent, tables: [] }
      : (paragraphsOrContent || {});
    var limit = Math.max(1, Number(maxReviewCharacters) || 20000);
    var blocks = [];
    var pendingBlocks = [];
    var sourceValues = [];
    var seenIds = {};
    var characterCount = 0;
    var tableCount = 0;
    var cellCount = 0;

    function appendBlock(block) {
      var values;
      if (!block || !block.blockId || seenIds[block.blockId]) {
        return;
      }
      values = reviewBlockTextValues(block);
      if (!values.length) {
        return;
      }
      seenIds[block.blockId] = true;
      blocks.push(block);
      values.forEach(function (value) {
        characterCount += value.length;
        sourceValues.push(value);
      });
      if (block.blockType === "table") {
        function countNestedTables(table) {
          return 1 + (table.nestedTables || []).reduce(function (total, nested) {
            return total + countNestedTables(nested);
          }, 0);
        }
        function countNestedCells(table) {
          return (table.rows || []).reduce(function (total, row) {
            return total + (row.cells || []).length;
          }, 0) + (table.nestedTables || []).reduce(function (total, nested) {
            return total + countNestedCells(nested);
          }, 0);
        }
        tableCount += countNestedTables(block);
        cellCount += countNestedCells(block);
      }
    }

    (Array.isArray(content.paragraphs) ? content.paragraphs : []).forEach(function (paragraph) {
      var text = String(paragraph && paragraph.text || "")
        .replace(/[\r\u0007]+$/g, "")
        .trim();
      var hasOutlineFact = Boolean(paragraph && (
        (Object.prototype.hasOwnProperty.call(paragraph, "outlineLevel") &&
          typeof paragraph.outlineLevel !== "undefined") ||
        (Object.prototype.hasOwnProperty.call(paragraph, "outline_level") &&
          typeof paragraph.outline_level !== "undefined")
      ));
      var outlineLevel = hasOutlineFact
        ? normalizeWpsOutlineLevel(paragraph.outlineLevel !== undefined
          ? paragraph.outlineLevel : paragraph.outline_level) : null;
      var paragraphIndex = Number(paragraph && (paragraph.index || paragraph.paragraphIndex)) || pendingBlocks.length + 1;
      if (!text) {
        return;
      }
      pendingBlocks.push({
        blockId: "paragraph-" + paragraphIndex,
        blockType: !hasOutlineFact ? (paragraph.listLabel ? "listItem" : "paragraph") :
          (outlineLevel === null ? (paragraph.listLabel ? "listItem" : "unknown") :
            (outlineLevel > 0 ? "heading" : (paragraph.listLabel ? "listItem" : "paragraph"))),
        paragraphIndex: paragraphIndex,
        listLabel: paragraph.listLabel ? String(paragraph.listLabel) : undefined,
        text: text
      });
      if (hasOutlineFact) {
        pendingBlocks[pendingBlocks.length - 1].outlineLevel = outlineLevel;
        if (outlineLevel > 0) {
          pendingBlocks[pendingBlocks.length - 1].headingLevel = outlineLevel;
        }
      }
    });
    (Array.isArray(content.tables) ? content.tables : []).forEach(function (table, index) {
      var tableId = String(table && (table.tableId || table.id) || "table-" + (index + 1));
      pendingBlocks.push({
        blockId: tableId,
        blockType: "table",
        paragraphIndex: Number(table && table.paragraphIndex) || pendingBlocks.length + 1,
        tableId: tableId,
        tableIndex: Number(table && table.tableIndex) || index + 1,
        rows: Array.isArray(table && table.rows) ? table.rows : [],
        nestedTables: Array.isArray(table && table.nestedTables) ? table.nestedTables : []
      });
    });
    pendingBlocks.sort(function (left, right) {
      return Number(left.paragraphIndex || 0) - Number(right.paragraphIndex || 0);
    });
    pendingBlocks.forEach(appendBlock);
    if (!blocks.length) {
      throw new Error("未读取到可审查的正文或结构化正文表格。");
    }
    if (characterCount > limit) {
      throw new Error("当前全篇审查范围超过本次抽取设定的字符上限（20,000 审查字符）。");
    }
    return {
      blocks: blocks,
      sourceText: sourceValues.join("\n"),
      reviewCharacterCount: characterCount,
      contentSha256: sha256Text(sourceValues.join("\n")),
      structureSha256: reviewStructureSha256(blocks),
      tableCount: tableCount,
      cellCount: cellCount,
      capacity: getFullDocumentReviewCapacity(characterCount)
    };
  }

  function buildFullDocumentReviewBatches(body, targetCharacters) {
    var target = Math.max(1, Number(targetCharacters) || 3500);
    var batches = [];
    var current = [];
    var currentCount = 0;
    var blocks = body && Array.isArray(body.blocks) ? body.blocks : [];

    function flush() {
      var values = [];
      var count = 0;
      if (!current.length) {
        return;
      }
      current.forEach(function (block) {
        var blockValues = reviewBlockTextValues(block);
        values = values.concat(blockValues);
        blockValues.forEach(function (value) { count += value.length; });
      });
      batches.push({
        sequence: batches.length,
        batchId: "batch-" + batches.length,
        blocks: current,
        characterCount: count,
        contentSha256: sha256Text(values.join("\n")),
        structureSha256: reviewStructureSha256(current),
        range: {
          start: current[0].blockId,
          end: current[current.length - 1].blockId
        }
      });
      current = [];
      currentCount = 0;
    }

    blocks.forEach(function (block) {
      var blockCount = reviewBlockTextValues(block).reduce(function (total, value) {
        return total + value.length;
      }, 0);
      if (current.length && currentCount + blockCount > target) {
        flush();
      }
      current.push(block);
      currentCount += blockCount;
    });
    flush();
    return batches;
  }

  function formatReviewBlockTextValues(block) {
    if (!block) {
      return [];
    }
    if (block.blockType === "table" || Array.isArray(block.rows) || Array.isArray(block.nestedTables)) {
      var tableValues = [];
      (block.rows || []).forEach(function (row) {
        (row.cells || []).forEach(function (cell) {
          if (cell.text) {
            tableValues.push(String(cell.text));
          }
        });
      });
      (block.nestedTables || []).forEach(function (table) {
        tableValues = tableValues.concat(formatReviewBlockTextValues(table));
      });
      return tableValues.length ? [tableValues.join("\n")] : [];
    }
    if (block.text) {
      return [String(block.text)];
    }
    return [];
  }

  function normalizeDeterministicNumber(value) {
    if (!isFinite(value)) {
      throw new Error("格式审查数值表示无效。");
    }
    if (value === 0) {
      return 0;
    }
    if (String(value).toLowerCase().indexOf("e") >= 0 ||
        Math.abs(value) < 0.0001 || Math.abs(value) >= 1000000000000000) {
      throw new Error("格式审查数值表示不受支持。");
    }
    return value;
  }

  function normalizeDeterministicJsonValue(value) {
    if (typeof value === "number") {
      return normalizeDeterministicNumber(value);
    }
    if (Array.isArray(value)) {
      return value.map(normalizeDeterministicJsonValue);
    }
    if (value && typeof value === "object") {
      var normalized = {};
      Object.keys(value).forEach(function (key) {
        normalized[key] = normalizeDeterministicJsonValue(value[key]);
      });
      return normalized;
    }
    return value;
  }

  function normalizeDeterministicIndex(value, fallback) {
    return normalizeDeterministicNumber(Number(value || fallback));
  }

  function normalizeDeterministicRangeNumber(value) {
    return normalizeDeterministicNumber(Number(value));
  }

  function normalizeDeterministicFormatFacts(value) {
    var source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    var normalized = {};
    var allowed = [
      "styleName", "fontName", "fontSize", "bold", "italic", "underline",
      "strikeThrough", "superscript", "subscript", "allCaps", "smallCaps",
      "color", "highlight", "characterSpacing", "characterScale", "alignment",
      "lineSpacing", "firstLineIndent", "spaceBefore", "spaceAfter", "leftIndent",
      "rightIndent", "outlineLevel", "segments", "dataStatus", "facts", "formatFacts",
      "lineSpacingMode"
    ];
    allowed.forEach(function (key) {
      if (typeof source[key] !== "undefined") {
        normalized[key] = normalizeDeterministicJsonValue(source[key]);
      }
    });
    if (Object.prototype.hasOwnProperty.call(normalized, "dataStatus") &&
        ["verified", "mixed", "unknown", "read_failed", "unsupported", "context_only", "insufficient"]
          .indexOf(normalized.dataStatus) < 0) {
      normalized.dataStatus = "insufficient";
    }
    if (Array.isArray(normalized.segments)) {
      normalized.segments = normalized.segments.map(function (segment) {
        var item = segment && typeof segment === "object" ? segment : {};
        return {
          start: normalizeDeterministicIndex(item.start, 0),
          end: normalizeDeterministicIndex(item.end, 0),
          format: normalizeDeterministicFormatFacts(item.format || {})
        };
      });
    }
    if ((!normalized.facts || !Object.keys(normalized.facts).length) &&
        (!normalized.formatFacts || !Object.keys(normalized.formatFacts).length)) {
      var derived = buildWpsFormatFacts(source);
      if (Object.keys(derived).length) {
        normalized.facts = derived;
      }
    }
    var facts = normalized.facts || normalized.formatFacts || {};
    ["fontSize", "lineSpacing", "firstLineIndent", "spaceBefore", "spaceAfter", "leftIndent", "rightIndent"]
      .forEach(function (key) {
        var fact = facts && facts[key];
        if (fact && fact.dataStatus === "verified") {
          normalized[key] = fact.normalizedValue;
        } else if (fact && Object.prototype.hasOwnProperty.call(source, key)) {
          normalized[key] = null;
        }
      });
    if (facts && facts.lineSpacing && facts.lineSpacing.mode) {
      normalized.lineSpacingMode = facts.lineSpacing.mode;
    }
    if (normalized.dataStatus === "insufficient" && source.insufficientReason) {
      normalized.insufficientReason = String(source.insufficientReason).slice(0, 120);
    } else {
      delete normalized.insufficientReason;
    }
    return normalizeDeterministicJsonValue(normalized);
  }

  function normalizeDeterministicImageFacts(value) {
    return (Array.isArray(value) ? value : []).filter(function (image) {
      return image && image.imageId;
    }).map(function (image) {
      return {
        imageId: String(image.imageId),
        groupId: String(image.groupId || image.imageGroupId || image.imageId).slice(0, 160),
        fingerprint: String(image.fingerprint || image.objectFingerprint || "").slice(0, 256),
        captionStatus: String(image.captionStatus || image.figureCaptionStatus || "unknown").slice(0, 32),
        associationStatus: String(image.associationStatus || "missing").slice(0, 32),
        supported: image.supported !== false && image.supportedType !== false,
        altText: String(image.altText || image.alternativeText || "").slice(0, 2000),
        nearbyText: String(image.nearbyText || image.contextText || image.adjacentText || "").slice(0, 4000)
      };
    });
  }

  function normalizeDeterministicRange(value) {
    var source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    var allowed = ["start", "end", "area", "paragraphIndex", "tableId", "cellId",
      "pageNumber", "pageStart", "pageEnd", "sectionIndex"];
    var numeric = ["start", "end", "paragraphIndex", "pageNumber", "pageStart", "pageEnd", "sectionIndex"];
    var normalized = {};
    Object.keys(source).forEach(function (key) {
      if (allowed.indexOf(key) < 0 || source[key] === null || typeof source[key] === "undefined") {
        if (allowed.indexOf(key) < 0) {
          throw new Error("格式审查原文范围格式无效。");
        }
        return;
      }
      if (numeric.indexOf(key) >= 0) {
        var valueNumber = normalizeDeterministicRangeNumber(source[key]);
        if (!isFinite(valueNumber) || Math.floor(valueNumber) !== valueNumber || valueNumber < 0) {
          throw new Error("格式审查原文范围索引无效。");
        }
        normalized[key] = valueNumber;
      } else {
        if (typeof source[key] !== "string" || source[key].length > 160) {
          throw new Error("格式审查原文范围标识无效。");
        }
        normalized[key] = source[key];
      }
    });
    if (Object.prototype.hasOwnProperty.call(normalized, "start") &&
        Object.prototype.hasOwnProperty.call(normalized, "end") && normalized.end < normalized.start) {
      throw new Error("格式审查原文范围顺序无效。");
    }
    if (Object.prototype.hasOwnProperty.call(normalized, "pageStart") &&
        Object.prototype.hasOwnProperty.call(normalized, "pageEnd") && normalized.pageEnd < normalized.pageStart) {
      throw new Error("格式审查页码范围顺序无效。");
    }
    return normalized;
  }

  function normalizeDeterministicTable(table, index, parentId) {
    var source = table && typeof table === "object" ? table : {};
    var tableId = String(source.tableId || source.id ||
      (parentId ? parentId + "-nested-" + (index + 1) : "format-table-" + (index + 1)));
    var rows = Array.isArray(source.rows) ? source.rows.map(function (row, rowPosition) {
      var rowSource = row && typeof row === "object" ? row : {};
      var rowIndex = normalizeDeterministicIndex(rowSource.rowIndex, rowPosition + 1);
      var cells = Array.isArray(rowSource.cells) ? rowSource.cells.map(function (cell, columnPosition) {
        var cellSource = cell && typeof cell === "object" ? cell : {};
        return {
          cellId: String(cellSource.cellId || "cell-" + rowIndex + "-" + (columnPosition + 1)),
          rowIndex: normalizeDeterministicIndex(cellSource.rowIndex, rowIndex),
          columnIndex: normalizeDeterministicIndex(cellSource.columnIndex, columnPosition + 1),
          rowSpan: normalizeDeterministicIndex(cellSource.rowSpan, 1),
          columnSpan: normalizeDeterministicIndex(cellSource.columnSpan, 1),
          text: String(cellSource.text || ""),
          format: normalizeDeterministicFormatFacts(cellSource.format || {})
        };
      }) : [];
      cells.sort(function (left, right) { return left.columnIndex - right.columnIndex; });
      return { rowIndex: rowIndex, cells: cells };
    }) : [];
    rows.sort(function (left, right) { return left.rowIndex - right.rowIndex; });
    return {
      tableId: tableId,
      tableIndex: normalizeDeterministicIndex(source.tableIndex, index + 1),
      rows: rows,
      nestedTables: (Array.isArray(source.nestedTables) ? source.nestedTables : [])
        .map(function (nested, nestedIndex) {
          return normalizeDeterministicTable(nested, nestedIndex, tableId);
        }),
      format: normalizeDeterministicFormatFacts(source.format || {})
    };
  }

  function formatReviewFormatProjection(block) {
    function tableProjection(table) {
      return {
        tableId: String(table && table.tableId || ""),
        format: table && table.format || {},
        rows: (table && table.rows || []).map(function (row) {
          return {
            rowIndex: normalizeDeterministicIndex(row && row.rowIndex, 0),
            cells: (row && row.cells || []).map(function (cell) {
              return {
                cellId: String(cell && cell.cellId || ""),
                format: cell && cell.format || {}
              };
            })
          };
        }),
        nestedTables: (table && table.nestedTables || []).map(tableProjection)
      };
    }
    return {
      blockId: String(block && block.blockId || ""),
      scope: String(block && block.scope || "in_scope"),
      format: block && block.format || {},
      segments: block && block.format && Array.isArray(block.format.segments)
        ? block.format.segments : [],
      table: block && block.blockType === "table" ? tableProjection(block) : null
    };
  }

  function formatFactValueType(value) {
    if (typeof value === "boolean") {
      return "boolean";
    }
    if (value !== null && typeof value !== "undefined" && value !== "" && !isNaN(Number(value))) {
      return "number";
    }
    if (typeof value === "string") {
      return "string";
    }
    return "unknown";
  }

  function isMixedWpsFactValue(value) {
    var resolved = resolveScalarValue(value);
    var text = String(resolved === null || typeof resolved === "undefined" ? "" : resolved).toLowerCase();
    return resolved === 9999999 || resolved === -9999999 ||
      text === "mixed" || text === "undefined" || text === "wdundefined";
  }

  function buildWpsFact(source, rawValue, rawUnit, normalizedValue, normalizedUnit, valueType, dataStatus, extra) {
    var result = {
      source: source,
      rawValue: typeof rawValue === "undefined" ? null : rawValue,
      rawUnit: rawUnit || "unknown",
      normalizedValue: typeof normalizedValue === "undefined" ? null : normalizedValue,
      normalizedUnit: normalizedUnit || "unknown",
      valueType: valueType || formatFactValueType(rawValue),
      dataStatus: dataStatus || "verified"
    };
    Object.keys(extra || {}).forEach(function (key) {
      if (typeof extra[key] !== "undefined" && extra[key] !== null) {
        result[key] = extra[key];
      }
    });
    return result;
  }

  function normalizeWpsLineSpacingMode(value) {
    var resolved = resolveScalarValue(value);
    var text = String(resolved === null || typeof resolved === "undefined" ? "" : resolved)
      .trim().toLowerCase().replace(/-/g, "_");
    var modes = {
      "0": "single", single: "single", wdlinespacesingle: "single",
      "1": "one_point_five", "1.5": "one_point_five", one_point_five: "one_point_five", wdlinespace1pt5: "one_point_five",
      "2": "double", double: "double", wdlinespacedouble: "double",
      "3": "minimum", minimum: "minimum", at_least: "minimum", wdlinespaceatleast: "minimum",
      "4": "fixed", fixed: "fixed", exactly: "fixed", wdlinespaceexactly: "fixed",
      "5": "multiple", multiple: "multiple", wdlinespacemultiple: "multiple"
    };
    return modes[text] || "unknown";
  }

  function factInputParts(value, defaultUnit) {
    var source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    var rawValue = Object.prototype.hasOwnProperty.call(source, "rawValue")
      ? source.rawValue : (Object.prototype.hasOwnProperty.call(source, "value") ? source.value : value);
    var dataStatus = source.dataStatus || (isMixedWpsFactValue(rawValue) ? "mixed" :
      (rawValue === null || typeof rawValue === "undefined" || rawValue === "" ? "unknown" : "verified"));
    return {
      rawValue: resolveScalarValue(rawValue),
      rawUnit: String(source.rawUnit || defaultUnit || "unknown"),
      dataStatus: dataStatus,
      valueType: source.valueType || formatFactValueType(rawValue)
    };
  }

  function normalizeWpsNumericFact(value, source, rawUnit, normalizedUnit) {
    var parts = factInputParts(value, rawUnit);
    var numeric = Number(parts.rawValue);
    var normalized = null;
    var status = parts.dataStatus;
    if (status === "verified" && !isNaN(numeric) && isFinite(numeric)) {
      if (parts.rawUnit === "pt" && normalizedUnit === "twip") {
        normalized = Math.round(numeric * 20);
      } else if ((parts.rawUnit === "twip" || parts.rawUnit === "twips") && normalizedUnit === "twip") {
        normalized = Math.round(numeric);
      } else if (parts.rawUnit === "pt" && normalizedUnit === "pt") {
        normalized = Math.round(numeric * 10000) / 10000;
      } else if (parts.rawUnit === normalizedUnit) {
        normalized = Math.round(numeric * 10000) / 10000;
      } else {
        status = "unknown";
      }
    } else if (status === "verified") {
      status = "unknown";
    }
    return buildWpsFact(source, parts.rawValue, parts.rawUnit, normalized, normalized === null ? "unknown" : normalizedUnit,
      parts.valueType, status, {});
  }

  function normalizeWpsPaperSizeFact(value) {
    var parts = factInputParts(value, "enum");
    var key = String(parts.rawValue === null || typeof parts.rawValue === "undefined" ? "" : parts.rawValue)
      .trim().toLowerCase();
    var normalized = (key === "7" || key === "a4" || key === "wdpapersizea4" || key === "paper_a4") ? "A4" : null;
    return buildWpsFact("wps.word.page_setup.paper_size", parts.rawValue, parts.rawUnit, normalized,
      normalized ? "paper" : "unknown", normalized ? "enum" : parts.valueType, normalized ? parts.dataStatus : "unknown", {});
  }

  function normalizeWpsLineSpacingFact(value, mode) {
    var parts = factInputParts(value, normalizeWpsLineSpacingMode(mode) === "multiple" ? "multiple" : "pt");
    var selectedMode = normalizeWpsLineSpacingMode(
      value && typeof value === "object" && value.mode !== undefined ? value.mode : mode
    );
    var numeric = Number(parts.rawValue);
    var normalized = null;
    var normalizedUnit = "unknown";
    var status = parts.dataStatus;
    if (status === "verified" && !isNaN(numeric) && isFinite(numeric)) {
      if (selectedMode === "multiple" && ["multiple", "factor", "倍"].indexOf(parts.rawUnit) >= 0) {
        normalized = Math.round(numeric * 10000) / 10000;
        normalizedUnit = "multiple";
      } else if (["fixed", "minimum"].indexOf(selectedMode) >= 0 && parts.rawUnit === "pt") {
        normalized = Math.round(numeric * 20);
        normalizedUnit = "twip";
      } else if (["single", "one_point_five", "double"].indexOf(selectedMode) >= 0) {
        normalized = { single: 1, one_point_five: 1.5, double: 2 }[selectedMode];
        normalizedUnit = "multiple";
      } else {
        status = "unknown";
      }
    } else if (status === "verified") {
      status = "unknown";
    }
    return buildWpsFact("wps.word.paragraph_format.line_spacing", parts.rawValue, parts.rawUnit, normalized,
      normalizedUnit, parts.valueType, status, { mode: selectedMode });
  }

  function buildWpsPageSetupFacts(pageSetup) {
    var source = pageSetup || {};
    return {
      paperSize: normalizeWpsPaperSizeFact(source.paperSize !== undefined ? source.paperSize : source.PaperSize),
      marginTop: normalizeWpsNumericFact(source.marginTop !== undefined ? source.marginTop : source.TopMargin,
        "wps.word.page_setup.marginTop", "pt", "twip"),
      marginBottom: normalizeWpsNumericFact(source.marginBottom !== undefined ? source.marginBottom : source.BottomMargin,
        "wps.word.page_setup.marginBottom", "pt", "twip"),
      marginLeft: normalizeWpsNumericFact(source.marginLeft !== undefined ? source.marginLeft : source.LeftMargin,
        "wps.word.page_setup.marginLeft", "pt", "twip"),
      marginRight: normalizeWpsNumericFact(source.marginRight !== undefined ? source.marginRight : source.RightMargin,
        "wps.word.page_setup.marginRight", "pt", "twip")
    };
  }

  function buildWpsFormatFacts(paragraph) {
    var source = paragraph || {};
    var facts = {};
    if (source.fontSize !== undefined || source.font_size_pt !== undefined) {
      facts.fontSize = normalizeWpsNumericFact(
        source.fontSize !== undefined ? source.fontSize : source.font_size_pt,
        "wps.word.font.size", "pt", "pt"
      );
    }
    if (source.lineSpacing !== undefined || source.line_spacing !== undefined || source.lineSpacingMode !== undefined) {
      facts.lineSpacing = normalizeWpsLineSpacingFact(
        source.lineSpacing !== undefined ? source.lineSpacing : source.line_spacing,
        source.lineSpacingMode
      );
    }
    ["firstLineIndent", "spaceBefore", "spaceAfter", "leftIndent", "rightIndent"].forEach(function (key) {
      var snake = key.replace(/[A-Z]/g, function (letter) { return "_" + letter.toLowerCase(); });
      if (source[key] !== undefined || source[snake] !== undefined) {
        facts[key] = normalizeWpsNumericFact(
          source[key] !== undefined ? source[key] : source[snake],
          "wps.word.paragraph_format." + key, "pt", "twip"
        );
      }
    });
    return facts;
  }

  function stableFormatReviewJson(value) {
    if (Array.isArray(value)) {
      return "[" + value.map(stableFormatReviewJson).join(",") + "]";
    }
    if (value && typeof value === "object") {
      return "{" + Object.keys(value).filter(function (key) {
        return typeof value[key] !== "undefined" && typeof value[key] !== "function";
      }).sort().map(function (key) {
        return JSON.stringify(key) + ":" + stableFormatReviewJson(value[key]);
      }).join(",") + "}";
    }
    if (typeof value === "number") {
      return JSON.stringify(normalizeDeterministicNumber(value));
    }
    return typeof value === "undefined" ? "null" : JSON.stringify(value);
  }

  function formatReviewTableStructureProjection(table) {
    return {
      tableId: String(table && table.tableId || ""),
      tableIndex: Number(table && table.tableIndex || 0),
      rows: (table && table.rows || []).map(function (row) {
        return {
          rowIndex: Number(row && row.rowIndex || 0),
          cells: (row && row.cells || []).map(function (cell) {
            return {
              cellId: String(cell && cell.cellId || ""),
              rowIndex: Number(cell && cell.rowIndex || 0),
              columnIndex: Number(cell && cell.columnIndex || 0),
              rowSpan: Number(cell && cell.rowSpan || 1),
              columnSpan: Number(cell && cell.columnSpan || 1)
            };
          })
        };
      }),
      nestedTables: (table && table.nestedTables || []).map(formatReviewTableStructureProjection)
    };
  }

  function formatReviewStructureProjection(block) {
    return {
      blockId: block.blockId,
      blockType: block.blockType,
      scope: block.scope,
      paragraphIndex: Number(block.paragraphIndex || 0),
      range: block.range || {},
      tableId: block.tableId || "",
      tableIndex: Number(block.tableIndex || 0),
      headingLevel: Number(block.headingLevel || 0),
      listLabel: block.listLabel || "",
      captionFor: block.captionFor || "",
      sectionId: block.sectionId || "",
      storyId: block.storyId || "",
      rows: (block.rows || []).map(function (row) {
        return {
          rowIndex: Number(row && row.rowIndex || 0),
          cells: (row && row.cells || []).map(function (cell) {
            return {
              cellId: String(cell && cell.cellId || ""),
              rowIndex: Number(cell && cell.rowIndex || 0),
              columnIndex: Number(cell && cell.columnIndex || 0),
              rowSpan: Number(cell && cell.rowSpan || 1),
              columnSpan: Number(cell && cell.columnSpan || 1)
            };
          })
        };
      }),
      nestedTables: (block.nestedTables || []).map(formatReviewTableStructureProjection),
      images: (block.images || []).map(function (image) {
        return {
          imageId: String(image && image.imageId || ""),
          groupId: String(image && image.groupId || ""),
          fingerprint: String(image && image.fingerprint || ""),
          captionStatus: String(image && image.captionStatus || "unknown"),
          associationStatus: String(image && image.associationStatus || "missing"),
          supported: image && image.supported !== false,
          altText: String(image && image.altText || ""),
          nearbyText: String(image && image.nearbyText || "")
        };
      })
    };
  }

  function applyFormatBlockStoryIdentity(block) {
    if (!block || typeof block !== "object") {
      return block;
    }
    var range = block.range && typeof block.range === "object" ? block.range : {};
    var sectionId = String(block.sectionId || block.section || "").trim();
    if (!sectionId && Number(range.sectionIndex) > 0) {
      sectionId = "section-" + Number(range.sectionIndex);
    }
    var storyId = String(block.storyId || block.story || "").trim();
    if (!storyId && block.scope !== "context") {
      storyId = "body";
    }
    if (sectionId) {
      block.sectionId = sectionId;
    }
    if (storyId) {
      block.storyId = storyId;
    }
    return block;
  }

  function fillFormatBlocksStoryIdentity(blocks) {
    var lastSectionId = "";
    var lastStoryId = "";
    (Array.isArray(blocks) ? blocks : []).forEach(function (block) {
      if (!block || typeof block !== "object") {
        return;
      }
      applyFormatBlockStoryIdentity(block);
      if (block.scope === "context") {
        return;
      }
      if (block.sectionId) {
        lastSectionId = String(block.sectionId);
      } else if (lastSectionId) {
        block.sectionId = lastSectionId;
      }
      if (block.storyId) {
        lastStoryId = String(block.storyId);
      } else if (lastStoryId) {
        block.storyId = lastStoryId;
      }
    });
  }

  function normalizeDeterministicFormatReviewBlock(block) {
    if (!block || !block.blockId) {
      return null;
    }
    block.scope = block.scope === "context" ? "context" : "in_scope";
    block.text = String(block.text || "");
    block.range = normalizeDeterministicRange(block.range);
    block.format = normalizeDeterministicFormatFacts(block.format || {});
    block.images = normalizeDeterministicImageFacts(block.images);
    if (block.blockType === "image" && block.images.length) {
      ["imageId", "groupId", "fingerprint", "captionStatus", "associationStatus",
        "supported", "altText", "nearbyText"].forEach(function (key) {
        block[key] = block.images[0][key];
      });
    }
    var hasTopLevelOutline = Object.prototype.hasOwnProperty.call(block, "outlineLevel") &&
      typeof block.outlineLevel !== "undefined";
    var hasFormatOutline = Object.prototype.hasOwnProperty.call(block.format, "outlineLevel") &&
      typeof block.format.outlineLevel !== "undefined";
    var hasHeadingLevel = Object.prototype.hasOwnProperty.call(block, "headingLevel") &&
      typeof block.headingLevel !== "undefined";
    var hasOutlineFact = hasTopLevelOutline || hasFormatOutline || hasHeadingLevel;
    if (hasOutlineFact) {
      var rawOutlineLevel = hasTopLevelOutline ? block.outlineLevel :
        (hasFormatOutline ? block.format.outlineLevel : block.headingLevel);
      block.outlineLevel = normalizeWpsOutlineLevel(rawOutlineLevel);
      block.format.outlineLevel = block.outlineLevel;
      block.format = normalizeDeterministicFormatFacts(block.format);
      if (block.blockType === "heading") {
        if (block.outlineLevel === 0) {
          block.blockType = "paragraph";
          delete block.headingLevel;
        } else if (block.outlineLevel === null) {
          block.blockType = "unknown";
          delete block.headingLevel;
        } else {
          block.headingLevel = block.outlineLevel;
        }
      }
    }
    if (block.blockType === "table") {
      var normalizedTable = normalizeDeterministicTable(block, Number(block.tableIndex || 1) - 1);
      block.tableId = normalizedTable.tableId;
      block.tableIndex = normalizedTable.tableIndex;
      block.rows = normalizedTable.rows;
      block.nestedTables = normalizedTable.nestedTables;
      block.format = normalizedTable.format;
      block.text = formatReviewBlockTextValues(block).join("\n");
    }
    applyFormatBlockStoryIdentity(block);
    return JSON.parse(stableFormatReviewJson(block));
  }

  function normalizeFormatReviewCoverageUnsupportedObjects(value) {
    if (!Array.isArray(value)) {
      return [];
    }
    return value.map(function (item) {
      var source = item && typeof item === "object" ? item : {};
      var count = Math.max(0, Math.floor(Number(source.count) || 0));
      var normalized = {
        type: String(source.type || "unknown").slice(0, 64),
        count: count,
        status: String(source.status || "not_supported").slice(0, 32)
      };
      if (source.reason) {
        normalized.reason = String(source.reason).slice(0, 120);
      }
      return normalized;
    });
  }

  function collectFormatReviewImageFacts(blocks) {
    var images = [];
    var seen = {};

    function add(image) {
      if (!image || typeof image !== "object") {
        return;
      }
      var normalized = normalizeDeterministicImageFacts([image])[0];
      if (!normalized || !normalized.imageId || seen[normalized.imageId]) {
        return;
      }
      seen[normalized.imageId] = true;
      images.push(normalized);
    }

    (Array.isArray(blocks) ? blocks : []).forEach(function (block) {
      if (!block || typeof block !== "object") {
        return;
      }
      if (block.blockType === "image" || block.isImage === true) {
        add(block);
      }
      (Array.isArray(block.images) ? block.images : []).forEach(add);
    });
    return images;
  }

  function buildDeterministicFormatReviewCoverage(blocks, suppliedCoverage) {
    var sourceCoverage = suppliedCoverage && typeof suppliedCoverage === "object"
      ? suppliedCoverage : {};
    var inScope = (Array.isArray(blocks) ? blocks : []).filter(function (block) {
      return block && block.scope === "in_scope";
    });
    var formatFactStatusCounts = {};
    var formatSegmentCount = 0;
    var tableCellCount = 0;
    var insufficientBlockCount = 0;
    var unsupportedObjects = [];

    function countFactStatuses(facts) {
      if (!facts || typeof facts !== "object" || Array.isArray(facts)) {
        return;
      }
      if (facts.dataStatus) {
        var status = String(facts.dataStatus);
        formatFactStatusCounts[status] = (formatFactStatusCounts[status] || 0) + 1;
      }
      if (facts.facts && typeof facts.facts === "object" && !Array.isArray(facts.facts)) {
        Object.keys(facts.facts).forEach(function (key) {
          var fact = facts.facts[key];
          if (fact && typeof fact === "object" && fact.dataStatus) {
            var nestedStatus = String(fact.dataStatus);
            formatFactStatusCounts[nestedStatus] = (formatFactStatusCounts[nestedStatus] || 0) + 1;
          }
        });
      }
    }

    function countTable(table, countStatuses) {
      if (!table || typeof table !== "object") {
        return;
      }
      (Array.isArray(table.rows) ? table.rows : []).forEach(function (row) {
        (Array.isArray(row && row.cells) ? row.cells : []).forEach(function (cell) {
          tableCellCount += 1;
          var cellFormat = cell && cell.format && typeof cell.format === "object" ? cell.format : {};
          if (countStatuses) {
            countFactStatuses(cellFormat);
          }
          formatSegmentCount += Array.isArray(cellFormat.segments) ? cellFormat.segments.length : 0;
          if (cellFormat.dataStatus === "insufficient") {
            insufficientBlockCount += 1;
          }
        });
      });
      (Array.isArray(table.nestedTables) ? table.nestedTables : []).forEach(function (nested) {
        countTable(nested, countStatuses);
      });
    }

    (Array.isArray(blocks) ? blocks : []).forEach(function (block) {
      if (!block || typeof block !== "object") {
        return;
      }
      var format = block.format && typeof block.format === "object" ? block.format : {};
      if (block.scope === "in_scope") {
        countFactStatuses(format);
      }
      formatSegmentCount += Array.isArray(format.segments) ? format.segments.length : 0;
      if (format.dataStatus === "insufficient") {
        insufficientBlockCount += 1;
      }
      if (block.blockType === "table") {
        countTable(block, block.scope === "in_scope");
      }
      if (Array.isArray(block.unsupportedObjects)) {
        unsupportedObjects = unsupportedObjects.concat(
          normalizeFormatReviewCoverageUnsupportedObjects(block.unsupportedObjects)
        );
      }
    });
    unsupportedObjects = unsupportedObjects.concat(
      normalizeFormatReviewCoverageUnsupportedObjects(sourceCoverage.unsupportedObjects)
    );

    var unsupportedObjectCount = unsupportedObjects.reduce(function (total, item) {
      return total + item.count;
    }, 0);
    var unsupportedObjectsByType = {};
    unsupportedObjects.forEach(function (item) {
      unsupportedObjectsByType[item.type] = (unsupportedObjectsByType[item.type] || 0) + item.count;
    });
    var imageFacts = collectFormatReviewImageFacts(blocks);
    var missingCaption = imageFacts.filter(function (image) {
      return ["missing", "absent", "none"].indexOf(String(image.captionStatus || "").toLowerCase()) >= 0;
    });
    var textEvidenceOnlyCount = missingCaption.filter(function (image) {
      return Boolean(String(image.altText || "").trim() || String(image.nearbyText || "").trim());
    }).length;
    var notAssessableCount = missingCaption.length - textEvidenceOnlyCount;
    var coverage = {
      inScopeBlockCount: inScope.length,
      contextBlockCount: (Array.isArray(blocks) ? blocks.length : 0) - inScope.length,
      paragraphCount: inScope.filter(function (block) {
        return ["paragraph", "heading", "listItem"].indexOf(block.blockType) >= 0;
      }).length,
      tableCount: inScope.filter(function (block) { return block.blockType === "table"; }).length,
      captionCount: inScope.filter(function (block) { return block.blockType === "caption"; }).length,
      tableCellCount: tableCellCount,
      formatSegmentCount: formatSegmentCount,
      formatDataStatus: insufficientBlockCount ? "insufficient" :
        (Object.keys(formatFactStatusCounts).some(function (status) {
          return status !== "verified";
        }) ? "partial" : "verified"),
      formatDataInsufficientBlockCount: insufficientBlockCount,
      formatFactStatusCounts: formatFactStatusCounts,
      unsupportedObjectCount: unsupportedObjectCount,
      unsupportedObjectsByType: unsupportedObjectsByType,
      imageCount: imageFacts.length,
      supportedImageCount: imageFacts.filter(function (image) { return image.supported !== false; }).length,
      missingFigureCaptionCount: missingCaption.length,
      textEvidenceOnlyCount: textEvidenceOnlyCount,
      imageNotAssessableCount: notAssessableCount,
      notAssessableCount: notAssessableCount,
      pixelExportCount: 0,
      pixelUploadCount: 0,
      pixelInspectedCount: 0,
      imageSemanticStatus: "disabled",
      imageSemanticReason: "image_semantics_disabled"
    };
    if (Object.prototype.hasOwnProperty.call(sourceCoverage, "headerFooter") &&
        sourceCoverage.headerFooter && typeof sourceCoverage.headerFooter === "object") {
      coverage.headerFooter = sourceCoverage.headerFooter;
    }
    if (unsupportedObjects.length) {
      coverage.unsupportedObjects = unsupportedObjects;
    }
    return JSON.parse(stableFormatReviewJson(coverage));
  }

  function buildDeterministicFormatReviewBody(payload, options) {
    var source = payload || {};
    var content = source.content || {};
    var structure = content.documentStructure || {};
    var paragraphs = Array.isArray(content.paragraphs) ? content.paragraphs : [];
    var tables = Array.isArray(structure.tables) ? structure.tables : [];
    var contextBlocks = Array.isArray((options || {}).contextBlocks)
      ? (options || {}).contextBlocks : [];
    var blocks = [];
    var seen = {};

    function pushBlock(block) {
      if (!block || !block.blockId || seen[block.blockId]) {
        return;
      }
      var normalizedBlock = normalizeDeterministicFormatReviewBlock(block);
      if (!normalizedBlock) {
        return;
      }
      seen[normalizedBlock.blockId] = true;
      blocks.push(normalizedBlock);
    }

    function isCaptionParagraph(paragraph) {
      var styleName = String(paragraph && (paragraph.styleName || paragraph.style_name) || "");
      var text = String(paragraph && paragraph.text || "").trim();
      return /caption|题注/i.test(styleName) || /^(图|表)\s*[0-9０-９一二三四五六七八九十]+[：:.、\s]/.test(text);
    }

    paragraphs.forEach(function (paragraph) {
      var index = Number(paragraph && (paragraph.index || paragraph.paragraphIndex)) || blocks.length + 1;
      var text = String(paragraph && paragraph.text || "").replace(/[\r\u0007]+$/g, "").trim();
      var hasOutlineFact = Boolean(paragraph && (
        (Object.prototype.hasOwnProperty.call(paragraph, "outlineLevel") &&
          typeof paragraph.outlineLevel !== "undefined") ||
        (Object.prototype.hasOwnProperty.call(paragraph, "outline_level") &&
          typeof paragraph.outline_level !== "undefined")
      ));
      var outlineLevel = hasOutlineFact
        ? normalizeWpsOutlineLevel(paragraph.outlineLevel !== undefined
          ? paragraph.outlineLevel : paragraph.outline_level)
        : null;
      var blockType = isCaptionParagraph(paragraph) ? "caption" :
        (!hasOutlineFact ? (paragraph.listLabel ? "listItem" : "paragraph") :
          (outlineLevel === null ? (paragraph.listLabel ? "listItem" : "unknown") :
            (outlineLevel > 0 ? "heading" : (paragraph.listLabel ? "listItem" : "paragraph"))));
      var format;
      if (!text) {
        return;
      }
      format = {
        styleName: paragraph.styleName || paragraph.style_name || "",
        fontName: paragraph.fontName || paragraph.font_name || "",
        fontSize: paragraph.fontSize,
        bold: Boolean(paragraph.bold),
        italic: Boolean(paragraph.italic),
        underline: paragraph.underline,
        alignment: paragraph.alignment || "",
        lineSpacing: paragraph.lineSpacing,
        firstLineIndent: paragraph.firstLineIndent,
        spaceBefore: paragraph.spaceBefore,
        spaceAfter: paragraph.spaceAfter,
        leftIndent: paragraph.leftIndent,
        rightIndent: paragraph.rightIndent,
        segments: Array.isArray(paragraph.formatSegments) ? paragraph.formatSegments : [],
        dataStatus: paragraph.formatDataStatus || paragraph.dataStatus || "verified",
        facts: paragraph.formatFacts || paragraph.format_facts || buildWpsFormatFacts(paragraph),
        insufficientReason: paragraph.formatInsufficientReason || ""
      };
      var paragraphBlock = {
        blockId: "format-paragraph-" + index,
        blockType: blockType,
        paragraphIndex: index,
        listLabel: paragraph.listLabel ? String(paragraph.listLabel) : undefined,
        captionFor: paragraph.captionFor ? String(paragraph.captionFor) : undefined,
        text: text,
        format: format,
        range: paragraph.range || {}
      };
      if (hasOutlineFact) {
        paragraphBlock.outlineLevel = outlineLevel;
        if (outlineLevel > 0) {
          paragraphBlock.headingLevel = outlineLevel;
        }
      }
      pushBlock(paragraphBlock);
    });

    tables.forEach(function (table, index) {
      var tableId = String(table && (table.tableId || table.id) || "format-table-" + (index + 1));
      var values = formatReviewBlockTextValues(table);
      pushBlock({
        blockId: "format-table-" + tableId,
        blockType: "table",
        tableId: tableId,
        tableIndex: Number(table && table.tableIndex) || index + 1,
        paragraphIndex: Number(table && table.paragraphIndex) || paragraphs.length + index + 1,
        rows: Array.isArray(table && table.rows) ? table.rows : [],
        nestedTables: Array.isArray(table && table.nestedTables) ? table.nestedTables : [],
        text: values.join("\n"),
        format: table && table.format || {},
        range: table && table.range || {}
      });
    });
    (Array.isArray((options || {}).imageFacts) ? (options || {}).imageFacts : []).forEach(function (image, index) {
      if (!image || !image.imageId) {
        return;
      }
      pushBlock({
        blockId: "format-image-" + String(image.imageId),
        blockType: "image",
        paragraphIndex: Number(image.paragraphIndex || paragraphs.length + tables.length + index + 1),
        text: "",
        images: [{
          imageId: String(image.imageId),
          groupId: String(image.groupId || image.imageId),
          fingerprint: String(image.fingerprint || ""),
          captionStatus: String(image.captionStatus || "unknown"),
          associationStatus: String(image.associationStatus || "missing"),
          supported: image.supported !== false,
          altText: String(image.altText || ""),
          nearbyText: String(image.nearbyText || "")
        }],
        format: { dataStatus: "verified" },
        range: image.range || {}
      });
    });
    contextBlocks.forEach(function (block) {
      pushBlock({
        blockId: String(block.blockId || "format-context-" + blocks.length),
        blockType: "context",
        paragraphIndex: Number(block.paragraphIndex || 0),
        text: String(block.text || ""),
        format: block.format || {},
        range: block.range || {},
        scope: "context"
      });
    });
    blocks.sort(function (left, right) {
      return Number(left.paragraphIndex || 0) - Number(right.paragraphIndex || 0);
    });
    fillFormatBlocksStoryIdentity(blocks);
    if (!blocks.some(function (block) { return block.scope === "in_scope"; })) {
      throw new Error("未读取到可审查的格式语义单元。");
    }

    var inScope = blocks.filter(function (block) { return block.scope === "in_scope"; });
    var sourceValues = [];
    inScope.forEach(function (block) {
      sourceValues = sourceValues.concat(formatReviewBlockTextValues(block));
    });
    var reviewCharacterCount = sourceValues.reduce(function (total, value) {
      return total + value.length;
    }, 0);
    var capacity = getDeterministicFormatReviewCapacity(reviewCharacterCount);
    if (!capacity.accepted) {
      throw new Error("格式审查超过 120,000 个审查字符，请缩小正文或表格范围。");
    }
    var structureProjection = blocks.map(formatReviewStructureProjection);
    var formatProjection = blocks.map(formatReviewFormatProjection);
    var suppliedCoverage = (options || {}).coverage || {};
    return {
      documentId: source.documentId || "unnamed.docx",
      selectionMode: source.selectionMode || "document",
      documentIdentity: (options || {}).documentIdentity || {},
      editSequence: (options || {}).editSequence,
      scope: (options || {}).scope || {
        mode: source.selectionMode || "document",
        expandedToSemanticUnits: source.selectionMode === "selection",
        contextOnly: contextBlocks.map(function (block) { return block.blockId; })
      },
      templateId: source.options && source.options.templateId || "technical-document-template-rules",
      blocks: blocks,
      reviewCharacterCount: reviewCharacterCount,
      contentSha256: sha256Text(sourceValues.join("\n")),
      structureSha256: sha256Text(stableFormatReviewJson(structureProjection)),
      formatSha256: sha256Text(stableFormatReviewJson(formatProjection)),
      coverage: buildDeterministicFormatReviewCoverage(blocks, suppliedCoverage),
      pageSetup: structure.page_setup || structure.pageSetup || {},
      pageSetupFacts: structure.page_setup_facts || structure.pageSetupFacts ||
        buildWpsPageSetupFacts(structure.page_setup || structure.pageSetup || {}),
      formatSnapshotSchemaVersion: "word.format_review.snapshot.v2",
      formatFactSchemaVersion: "format_snapshot.v2",
      capacityTier: capacity.tier
    };
  }

  function buildDeterministicFormatReviewBatches(body, targetCharacters) {
    var target = Math.max(1, Number(targetCharacters) || 3500);
    var batches = [];
    var current = [];
    var currentCount = 0;
    var blocks = body && Array.isArray(body.blocks) ? body.blocks : [];

    function flush() {
      var values = [];
      if (!current.length) {
        return;
      }
      current.forEach(function (block) {
        values = values.concat(formatReviewBlockTextValues(block));
      });
      batches.push({
        sequence: batches.length,
        batchId: "format-batch-" + batches.length,
        blocks: current,
        characterCount: current.filter(function (block) { return block.scope === "in_scope"; })
          .reduce(function (total, block) {
            return total + formatReviewBlockTextValues(block).reduce(function (count, value) {
              return count + value.length;
            }, 0);
          }, 0),
        contentSha256: sha256Text(current.filter(function (block) { return block.scope === "in_scope"; })
          .reduce(function (list, block) { return list.concat(formatReviewBlockTextValues(block)); }, []).join("\n")),
        structureSha256: sha256Text(stableFormatReviewJson(current.map(formatReviewStructureProjection))),
        formatSha256: sha256Text(stableFormatReviewJson(current.map(formatReviewFormatProjection)))
      });
      current = [];
      currentCount = 0;
    }

    blocks.forEach(function (block) {
      var blockCount = formatReviewBlockTextValues(block).reduce(function (total, value) {
        return total + value.length;
      }, 0);
      if (current.length && currentCount + blockCount > target) {
        flush();
      }
      current.push(block);
      currentCount += blockCount;
    });
    flush();
    return batches;
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
      originalText: originalText,
      previewMarkdown: rewrittenText,
      plainText: rewrittenText,
      comparisonMarkdown: comparisonMarkdown,
      hasOriginal: hasOriginal,
      hasStructuredResult: shouldUseStructuredSmartWriteResult(originalText, rewrittenText)
    };
  }

  function presentWordResultView(input) {
    var source = input || {};
    var rewriteMode = source.rewriteMode === "imitate" ? "imitate" : "rewrite";
    var model = buildSmartWritePreviewModel({
      originalText: source.originalText || "",
      rewrittenText: source.rewrittenText || "",
      rewriteMode: rewriteMode
    });
    var view = source.view || "preview";
    var resultText = model.plainText || "";
    var compareAvailable = rewriteMode !== "imitate";
    var presentation = "source";
    var displayMarkdown = resultText;

    if (!compareAvailable && view === "compare") {
      view = "preview";
    }
    if (view === "plain") {
      presentation = "source";
      displayMarkdown = model.plainText || "";
    } else if (view === "compare") {
      presentation = "rendered";
      displayMarkdown = model.comparisonMarkdown || model.previewMarkdown || "";
    } else {
      presentation = "rendered";
      displayMarkdown = model.previewMarkdown || "";
    }

    return {
      presentation: presentation,
      displayMarkdown: displayMarkdown,
      html: presentation === "rendered" ? renderMarkdown(displayMarkdown) : "",
      sourceText: presentation === "source" ? displayMarkdown : "",
      copyText: resultText,
      writebackText: resultText,
      compareAvailable: compareAvailable,
      viewLabels: {
        preview: "预览",
        compare: "对照",
        plain: "纯文本"
      }
    };
  }

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
    heading: "标题",
    page_setup: "页面设置"
  };
  var FORMAT_REVIEW_RULE_TEXT = {
    page_setup: "页面设置",
    style_name: "段落样式",
    font_name: "字体",
    font_size: "字号",
    line_spacing: "行距",
    alignment: "对齐方式",
    first_line_indent: "首行缩进",
    "structure.heading_hierarchy": "标题层级",
    "structure.caption_association": "题注关联",
    "structure.caption_placement": "题注位置"
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
    "4": "分散对齐",
    "左对齐": "左对齐",
    "居中": "居中",
    "右对齐": "右对齐",
    "两端对齐": "两端对齐",
    "分散对齐": "分散对齐"
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

  function formatFormatFactDiagnostic(fact) {
    if (!fact || typeof fact !== "object") {
      return "未读取";
    }
    var rawValue = typeof fact.rawValue === "undefined" || fact.rawValue === null
      ? "未读取"
      : String(fact.rawValue);
    var normalizedValue = typeof fact.normalizedValue === "undefined" || fact.normalizedValue === null
      ? "未归一化"
      : String(fact.normalizedValue);
    var rawUnit = fact.rawUnit ? " " + fact.rawUnit : "";
    var normalizedUnit = fact.normalizedUnit ? " " + fact.normalizedUnit : "";
    return rawValue + rawUnit + " → " + normalizedValue + normalizedUnit +
      "（" + (fact.dataStatus || "unknown") + "）";
  }

  function appendFormatFactDiagnostics(lines, diagnostics) {
    if (!diagnostics || typeof diagnostics !== "object") {
      return;
    }
    lines.push("- 事实契约：" + (diagnostics.schemaVersion || "format_snapshot.v2"));
    var pageSetup = diagnostics.pageSetup || {};
    var pageLabels = {
      paperSize: "纸张",
      marginTop: "上边距",
      marginRight: "右边距",
      marginBottom: "下边距",
      marginLeft: "左边距"
    };
    Object.keys(pageLabels).forEach(function (key) {
      if (pageSetup[key]) {
        lines.push("- 规范页面事实·" + pageLabels[key] + "：" + formatFormatFactDiagnostic(pageSetup[key]));
      }
    });
    var statusCounts = diagnostics.statusCounts || {};
    var statusParts = Object.keys(statusCounts).map(function (status) {
      return status + " " + Number(statusCounts[status] || 0);
    });
    if (statusParts.length) {
      lines.push("- 事实状态统计：" + statusParts.join("、"));
    }
    var blocks = Array.isArray(diagnostics.blocks) ? diagnostics.blocks : [];
    var examples = [];
    blocks.some(function (block) {
      var facts = block && block.facts ? block.facts : {};
      if (facts.lineSpacing) {
        examples.push("P" + Number(block.paragraphIndex || 0) + " 行距 " + formatFormatFactDiagnostic(facts.lineSpacing));
      }
      return examples.length >= 3;
    });
    if (examples.length) {
      lines.push("- 行距事实示例：" + examples.join("；"));
    }
  }

  function formatReviewRole(role) {
    return FORMAT_REVIEW_ROLE_TEXT[String(role || "")] || "未识别角色";
  }

  function formatReviewRule(ruleId) {
    return FORMAT_REVIEW_RULE_TEXT[String(ruleId || "")] || "其他格式项";
  }

  var DETERMINISTIC_FORMAT_REVIEW_STATUS_TEXT = {
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消",
    queued: "排队中",
    running: "执行中",
    passed: "未发现格式问题",
    violations_found: "发现格式问题",
    not_assessable: "无法判定",
    complete: "已完成",
    partial: "数据不足",
    insufficient: "数据不足",
    not_available: "不可用",
    not_needed: "无需语义增强",
    degraded: "部分生效",
    not_ready: "未就绪"
  };
  var DETERMINISTIC_FORMAT_REVIEW_DATA_STATUS_TEXT = {
    verified: "已验证",
    mixed: "格式不一致",
    unsupported: "当前 WPS 不支持",
    unknown: "无法识别",
    read_failed: "无法识别",
    insufficient: "数据不足",
    not_assessable: "无法判定"
  };
  var DETERMINISTIC_FORMAT_REVIEW_STYLE_TEXT = {
    Normal: "正文样式",
    Body: "正文样式",
    body: "正文样式",
    "heading 1": "一级标题样式",
    "heading 2": "二级标题样式",
    "heading 3": "三级标题样式",
    "heading 4": "四级标题样式",
    Caption: "图表题样式",
    caption: "图表题样式"
  };

  function parseFormatReviewNumber(value) {
    var match = String(value || "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function formatReviewFontName(value) {
    var raw = String(value || "").trim();
    var normalized = raw.toLowerCase();
    return FORMAT_REVIEW_FONT_TEXT[normalized] || FORMAT_REVIEW_FONT_TEXT[raw] || raw || "未读取";
  }

  function formatReviewAlignment(value) {
    var raw = String(value || "").trim();
    var key = raw.toLowerCase();
    return FORMAT_REVIEW_ALIGNMENT_TEXT[key] || FORMAT_REVIEW_ALIGNMENT_TEXT[raw] || raw || "未读取";
  }

  function formatDeterministicFormatReviewStatus(value, fallback) {
    return DETERMINISTIC_FORMAT_REVIEW_STATUS_TEXT[String(value || "")] || fallback || "无法判定";
  }

  function formatDeterministicFormatReviewTemplate(value) {
    if (value === "technical-document-template-rules") {
      return "技术文档模板规则";
    }
    return "无法识别";
  }

  function deterministicFormatReviewFact(diagnostics, issue) {
    var keyByRule = {
      font_name: "fontName",
      font_size: "fontSize",
      line_spacing: "lineSpacing",
      first_line_indent: "firstLineIndent",
      space_before: "spaceBefore",
      space_after: "spaceAfter",
      left_indent: "leftIndent",
      right_indent: "rightIndent"
    };
    var paragraphIndex = Number(issue && issue.paragraphIndex);
    var key = keyByRule[String(issue && issue.ruleId || "")];
    var blocks = diagnostics && Array.isArray(diagnostics.blocks) ? diagnostics.blocks : [];
    var block;
    if (!key || !isFinite(paragraphIndex)) {
      return null;
    }
    block = blocks.filter(function (candidate) {
      return candidate && Number(candidate.paragraphIndex) === paragraphIndex;
    })[0];
    return block && block.facts && block.facts[key] ? block.facts[key] : null;
  }

  function formatDeterministicFormatReviewFact(fact, ruleId) {
    var status;
    var normalized;
    var unit;
    var mode;
    var numeric;
    var pt;
    if (!fact || typeof fact !== "object") {
      return "";
    }
    status = DETERMINISTIC_FORMAT_REVIEW_DATA_STATUS_TEXT[String(fact.dataStatus || "unknown")];
    if (status && fact.dataStatus !== "verified") {
      return status;
    }
    normalized = fact.normalizedValue;
    if (normalized === null || typeof normalized === "undefined") {
      return status || "无法识别";
    }
    unit = String(fact.normalizedUnit || "");
    if (ruleId === "line_spacing") {
      mode = String(fact.mode || "");
      numeric = Number(normalized);
      if (!isFinite(numeric)) {
        return "无法识别";
      }
      if (mode === "multiple" || mode === "single" || mode === "one_point_five" || mode === "double") {
        return String(Math.round(numeric * 100) / 100).replace(/\.0$/, "") + " 倍行距";
      }
      if (mode === "fixed" || mode === "minimum") {
        pt = unit === "twip" ? Math.round(numeric / 20 * 100) / 100 : numeric;
        return (mode === "fixed" ? "固定值 " : "最小值 ") +
          String(pt).replace(/\.0$/, "") + " 磅";
      }
      return "无法识别";
    }
    if (ruleId === "font_size" && unit === "pt") {
      return formatDeterministicFontSize(normalized);
    }
    if (ruleId === "first_line_indent" && unit === "twip") {
      numeric = Number(normalized);
      if (numeric === 0) {
        return "无首行缩进";
      }
      if (Math.abs(numeric - 480) <= 20 || Math.abs(numeric - 640) <= 20) {
        return "首行缩进 2 字符";
      }
      return "无法识别";
    }
    if (ruleId === "font_name" || ruleId === "alignment" || ruleId === "style_name") {
      return formatDeterministicReadableFormatValue(ruleId, normalized, false);
    }
    return "无法识别";
  }

  function formatDeterministicFontSize(value) {
    var numeric = parseFormatReviewNumber(value);
    var key;
    if (numeric === null || isNaN(numeric)) {
      return "无法识别";
    }
    key = String(Math.round(numeric * 10) / 10).replace(/\.0$/, "");
    return FORMAT_REVIEW_SIZE_TEXT[key]
      ? FORMAT_REVIEW_SIZE_TEXT[key] + "（" + key + "pt）"
      : "无法识别";
  }

  function formatDeterministicPageSetupFacts(diagnostics) {
    var pageSetup = diagnostics && diagnostics.pageSetup;
    var parts = [];
    var statusLabels = DETERMINISTIC_FORMAT_REVIEW_DATA_STATUS_TEXT;
    var fact;
    var numeric;
    if (!pageSetup || typeof pageSetup !== "object") {
      return "";
    }
    ["paperSize", "marginTop", "marginBottom", "marginLeft", "marginRight"].some(function (key) {
      fact = pageSetup[key];
      if (!fact || typeof fact !== "object") {
        return false;
      }
      if (fact.dataStatus && fact.dataStatus !== "verified") {
        parts = [statusLabels[String(fact.dataStatus)] || "无法判定"];
        return true;
      }
      return false;
    });
    if (parts.length) {
      return parts[0];
    }
    fact = pageSetup.paperSize;
    if (fact && fact.normalizedValue !== null && typeof fact.normalizedValue !== "undefined") {
      parts.push("纸张：" + (String(fact.normalizedValue) === "A4" ? "A4" : "无法识别"));
    }
    [["marginTop", "上"], ["marginBottom", "下"], ["marginLeft", "左"], ["marginRight", "右"]]
      .forEach(function (item) {
        fact = pageSetup[item[0]];
        if (!fact || fact.normalizedValue === null || typeof fact.normalizedValue === "undefined") {
          return;
        }
        numeric = Number(fact.normalizedValue);
        if (!isFinite(numeric)) {
          parts.push(item[1] + "边距：无法识别");
          return;
        }
        if (String(fact.normalizedUnit || "") === "twip") {
          numeric = Math.round(numeric / 20 * 100) / 100;
        }
        parts.push(item[1] + "边距 " + String(numeric).replace(/\.0$/, "") + " 磅");
      });
    return parts.length ? parts.join("；") : Object.keys(pageSetup).length ? "无法识别" : "";
  }

  function formatDeterministicPageSetupValue(value, isExpected, diagnostics) {
    var source = value && typeof value === "object" && !Array.isArray(value) ? value : null;
    var raw = source ? "" : String(value === null || typeof value === "undefined" ? "" : value).trim();
    var data = source;
    var paper;
    var parts = [];
    var factText;
    var labels = {
      "7": "A4",
      a4: "A4",
      wdpapersizea4: "A4",
      paper_a4: "A4"
    };
    if (isExpected) {
      return /A4/.test(raw) && /边距/.test(raw) ? "A4 纸张及模板页边距" : "无法识别";
    }
    factText = formatDeterministicPageSetupFacts(diagnostics);
    if (factText) {
      return factText;
    }
    if (!data && raw.charAt(0) === "{") {
      try {
        data = JSON.parse(raw);
      } catch (error) {
        data = null;
      }
    }
    if (!data || typeof data !== "object") {
      return "无法识别";
    }
    paper = data.paperSize || data.PaperSize;
    if (paper !== null && typeof paper !== "undefined") {
      paper = labels[String(paper).trim().toLowerCase()];
      parts.push(paper ? "纸张：" + paper : "纸张：无法识别");
    }
    [
      ["marginTop", "上"], ["marginBottom", "下"],
      ["marginLeft", "左"], ["marginRight", "右"]
    ].forEach(function (item) {
      var numeric = Number(data[item[0]]);
      if (isFinite(numeric)) {
        parts.push(item[1] + "边距 " + String(Math.round(numeric / 20 * 100) / 100).replace(/\.0$/, "") + " 磅");
      }
    });
    return parts.length ? parts.join("；") : "无法识别";
  }

  function formatDeterministicFormatReviewIssueLocation(issue) {
    var source = issue && issue.sourceAnchor && typeof issue.sourceAnchor === "object"
      ? issue.sourceAnchor : {};
    var parts = [];
    var chapterPath = Array.isArray(source.chapterPath) ? source.chapterPath : [];
    var paragraphIndex = Number(issue && issue.paragraphIndex);
    var snippet = String(source.textSnippet || source.text || "").replace(/[\r\n]+/g, " ").trim();
    var scope = String(source.locationScope || issue && issue.locationScope || "").trim().toLowerCase();
    var sectionIndex;
    var sectionName;
    var pageStart;
    var pageEnd;

    function positiveInteger(value) {
      var numeric = Number(value);
      return isFinite(numeric) && numeric > 0 && Math.floor(numeric) === numeric ? numeric : 0;
    }

    function appendPageRange() {
      var pageRange = source.pageRange && typeof source.pageRange === "object"
        ? source.pageRange : {};
      pageStart = positiveInteger(pageRange.start || source.pageStart);
      pageEnd = positiveInteger(pageRange.end || source.pageEnd);
      if (!pageStart || !pageEnd) {
        pageStart = positiveInteger(source.pageNumber);
        pageEnd = pageStart;
      }
      if (pageStart && pageEnd && pageEnd >= pageStart) {
        parts.push(pageStart === pageEnd
          ? "第 " + pageStart + " 页"
          : "第 " + pageStart + " 至第 " + pageEnd + " 页");
      }
    }

    if (issue && issue.ruleId === "page_setup") {
      return "页面设置（全文）";
    }
    if (!scope) {
      scope = issue && (issue.role === "section" || issue.role === "chapter")
        ? "section" : (paragraphIndex > 0 ? "paragraph" : "document");
    }
    if (scope === "document") {
      return "全文";
    }
    if (chapterPath.length) {
      parts.push("章节：" + chapterPath.map(function (item) { return String(item); }).join(" > "));
    }
    if (scope === "section") {
      sectionIndex = positiveInteger(source.sectionIndex || (issue && issue.sectionIndex));
      sectionName = String(source.sectionName || (issue && issue.sectionName) || "")
        .replace(/[\r\n]+/g, " ").trim();
      if (sectionIndex && sectionName) {
        parts.push("第 " + sectionIndex + " 节：" + sectionName.slice(0, 120));
      } else if (sectionName) {
        parts.push("节：" + sectionName.slice(0, 120));
      } else if (sectionIndex) {
        parts.push("第 " + sectionIndex + " 节");
      }
      appendPageRange();
      return parts.length ? parts.join("；") : "无法验证位置";
    }
    if (paragraphIndex > 0 && issue.anchorVerification === "verified") {
      parts.push("第 " + paragraphIndex + " 段");
    }
    if (snippet) {
      parts.push("原文：“" + snippet.slice(0, 80) + "”");
    }
    appendPageRange();
    return parts.length ? parts.join("；") : "无法验证位置";
  }

  function formatDeterministicReadableFormatValue(ruleId, value, isExpected, diagnostics, issue) {
    var rule = String(ruleId || "");
    var raw = value === null || typeof value === "undefined" ? "" : String(value).trim();
    var numeric;
    var readable;
    var fact;
    if (rule === "page_setup") {
      return formatDeterministicPageSetupValue(value, isExpected, diagnostics);
    }
    if (!isExpected) {
      fact = deterministicFormatReviewFact(diagnostics, issue);
      readable = formatDeterministicFormatReviewFact(fact, rule);
      if (readable) {
        return readable;
      }
    }
    if (!raw) {
      return "无法识别";
    }
    if (rule === "font_name") {
      readable = formatReviewFontName(raw);
      return readable && readable !== "未读取" &&
        Object.prototype.hasOwnProperty.call(FORMAT_REVIEW_FONT_TEXT, raw.toLowerCase())
        ? readable : "无法识别";
    }
    if (rule === "font_size") {
      return formatDeterministicFontSize(raw);
    }
    if (rule === "style_name") {
      readable = DETERMINISTIC_FORMAT_REVIEW_STYLE_TEXT[raw];
      return readable && readable !== "未读取" &&
        Object.prototype.hasOwnProperty.call(DETERMINISTIC_FORMAT_REVIEW_STYLE_TEXT, raw)
        ? readable : "无法识别";
    }
    if (rule === "alignment") {
      readable = formatReviewAlignment(raw);
      return readable && readable !== "未读取" &&
        Object.prototype.hasOwnProperty.call(FORMAT_REVIEW_ALIGNMENT_TEXT, raw.toLowerCase())
        ? readable : "无法识别";
    }
    if (rule === "line_spacing") {
      if (/倍/.test(raw)) {
        numeric = parseFormatReviewNumber(raw);
        return numeric === null || isNaN(numeric) ? "无法识别" :
          String(Math.round(numeric * 100) / 100).replace(/\.0$/, "") + " 倍行距";
      }
      if (/pt|磅/i.test(raw)) {
        numeric = parseFormatReviewNumber(raw);
        return numeric === null || isNaN(numeric) ? "无法识别" :
          String(Math.round(numeric * 100) / 100).replace(/\.0$/, "") + " 磅";
      }
      return "无法识别";
    }
    if (rule === "first_line_indent") {
      if (/twip|字符|磅/.test(raw)) {
        numeric = parseFormatReviewNumber(raw);
        if (numeric === null || isNaN(numeric)) {
          return "无法识别";
        }
        if (Math.abs(numeric) < 0.01) {
          return "无首行缩进";
        }
        if (Math.abs(numeric - 480) <= 20 || Math.abs(numeric - 640) <= 20) {
          return "首行缩进 2 字符";
        }
        return "无法识别";
      }
      return "无法识别";
    }
    if (rule === "structure.heading_hierarchy") {
      numeric = Number(raw);
      return isFinite(numeric) && numeric > 0 ? "第 " + numeric + " 级标题" : "无法识别";
    }
    if (rule === "structure.caption_association") {
      return ({
        associated: "已关联",
        orphaned: "孤立",
        missing: "缺失",
        ambiguous: "歧义"
      })[raw] || "无法判定";
    }
    if (rule === "structure.caption_placement") {
      return ({
        before: "对象前",
        after: "对象后"
      })[raw] || "无法判定";
    }
    return "无法识别";
  }

  function formatDeterministicFormatReviewIssueMessage(issue) {
    var messages = {
      page_setup: "页面设置不符合模板要求。",
      style_name: "段落样式不符合模板要求。",
      font_name: "字体不符合模板要求。",
      font_size: "字号不符合模板要求。",
      line_spacing: "行距不符合模板要求。",
      alignment: "对齐方式不符合模板要求。",
      first_line_indent: "首行缩进不符合模板要求。",
      "structure.heading_hierarchy": "标题层级关系不符合模板要求。",
      "structure.table_semantics": "表格结构无法满足模板要求。",
      "structure.caption_association": "题注关联不符合模板要求。",
      "structure.caption_placement": "题注位置不符合模板要求。",
      "structure.role_confirmation": "段落结构角色无法可靠确认。"
    };
    return messages[String(issue && issue.ruleId || "")] || "格式问题，请按模板要求核对。";
  }

  function formatDeterministicFormatReviewSuggestion(issue) {
    var suggestions = {
      page_setup: "请按模板要求调整页面设置。",
      style_name: "请按模板要求调整段落样式。",
      font_name: "请按模板要求调整字体。",
      font_size: "请按模板要求调整字号。",
      line_spacing: "请按模板要求调整行距。",
      alignment: "请按模板要求调整对齐方式。",
      first_line_indent: "请按模板要求调整首行缩进。",
      "structure.heading_hierarchy": "请按模板要求核对标题层级关系。",
      "structure.table_semantics": "请核对表格结构证据。",
      "structure.caption_association": "请核对题注与对象的关联。",
      "structure.caption_placement": "请按模板要求调整题注位置。",
      "structure.role_confirmation": "请核对段落结构角色证据。"
    };
    return suggestions[String(issue && issue.ruleId || "")] || "请按模板要求核对格式问题。";
  }

  function renderReadableDeterministicFormatReview(data) {
    var source = data || {};
    var summary = source.summary || {};
    var issues = Array.isArray(source.issues) ? source.issues : [];
    var diagnostics = summary.formatFactDiagnostics;
    var total = Number(source.total || source.issueCount || issues.length);
    var lines = [
      "# 格式审查报告",
      "",
      "审查状态：" + formatDeterministicFormatReviewStatus(summary.executionStatus, "未记录"),
      "合规状态：" + formatDeterministicFormatReviewStatus(summary.complianceStatus, "无法判定"),
      "覆盖状态：" + formatDeterministicFormatReviewStatus(summary.coverageStatus, "无法判定"),
      "语义增强：" + formatDeterministicFormatReviewStatus(summary.semanticStatus, "未记录"),
      "审查依据：" + formatDeterministicFormatReviewTemplate(summary.templateId),
      "规则版本：" + String(summary.rulePackVersion || "未记录"),
      "来源版本：" + String(summary.rulePackSourceVersion || "未记录"),
      "问题数量：" + total,
      "",
      "以下内容仅展示可由当前格式事实确认的问题，不修改 Word 文档。",
      ""
    ];
    if (!issues.length) {
      lines.push("当前筛选范围未发现需要调整的格式问题。若覆盖状态不是“已完成”，零问题不代表文档完全合规。" );
      return lines.join("\n");
    }
    lines.push("## 问题清单");
    lines.push("");
    lines.push("| 位置 | 问题类型 | 当前值 | 模板要求 | 建议 |");
    lines.push("| --- | --- | --- | --- | --- |");
    issues.forEach(function (issue) {
      lines.push(
        "| " + formatDeterministicFormatReviewIssueLocation(issue) +
        " | " + formatReviewRule(issue.ruleId) +
        " | " + formatDeterministicReadableFormatValue(issue.ruleId, issue.currentValue, false, diagnostics, issue) +
        " | " + formatDeterministicReadableFormatValue(issue.ruleId, issue.expectedValue, true, diagnostics, issue) +
        " | " + formatDeterministicFormatReviewSuggestion(issue) + " |"
      );
    });
    lines.push("");
    lines.push("## 详细说明");
    lines.push("");
    issues.forEach(function (issue) {
      lines.push("### " + formatReviewRule(issue.ruleId) + " · " +
        formatDeterministicFormatReviewIssueLocation(issue));
      lines.push("- 角色：" + (formatReviewRole(issue.role) === "未识别角色" ? "无法识别" : formatReviewRole(issue.role)));
      lines.push("- 当前值：" + formatDeterministicReadableFormatValue(issue.ruleId, issue.currentValue, false, diagnostics, issue));
      lines.push("- 模板要求：" + formatDeterministicReadableFormatValue(issue.ruleId, issue.expectedValue, true, diagnostics, issue));
      lines.push("- 问题说明：" + formatDeterministicFormatReviewIssueMessage(issue));
      lines.push("- 建议：" + formatDeterministicFormatReviewSuggestion(issue));
      lines.push("");
    });
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
    return isNaN(numeric) || !isFinite(numeric) ? null : numeric;
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
    if (isNaN(numeric) || !isFinite(numeric) || numeric <= 0) {
      return null;
    }
    return Math.floor(numeric);
  }

  function normalizeWpsOutlineLevel(value) {
    var resolved = resolveScalarValue(value);
    var numeric;
    if (resolved === null || typeof resolved === "undefined" ||
        (typeof resolved === "string" && !resolved.trim()) ||
        typeof resolved === "boolean") {
      return null;
    }
    numeric = Number(resolved);
    if (!isFinite(numeric) || Math.floor(numeric) !== numeric) {
      return null;
    }
    if (numeric === 0 || numeric === 10) {
      return 0;
    }
    return numeric >= 1 && numeric <= 9 ? numeric : null;
  }

  function collectHeadingsFromParagraphs(paragraphs) {
    return (Array.isArray(paragraphs) ? paragraphs : []).map(function (paragraph) {
      var level = normalizeWpsOutlineLevel(paragraph && paragraph.outlineLevel);
      if (level === null || level === 0) {
        return null;
      }
      return {
        level: level,
        text: paragraph && paragraph.text || "",
        paragraphIndex: paragraph && (paragraph.index || paragraph.paragraphIndex) || null
      };
    }).filter(Boolean);
  }

  function normalizeCollectOptions(options) {
    var source = typeof options === "number" ? { maxParagraphs: options } : (options || {});
    return {
      maxParagraphs: normalizePositiveInteger(source.maxParagraphs),
      maxParagraphTextLength: normalizePositiveInteger(source.maxParagraphTextLength),
      avoidFallbackTextRead: Boolean(source.avoidFallbackTextRead),
      excludeTableParagraphs: Boolean(source.excludeTableParagraphs),
      includeCharacterFormatSegments: Boolean(source.includeCharacterFormatSegments),
      maxFormatSegments: normalizePositiveInteger(source.maxFormatSegments) || 2048
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

  function safeCallWithArgs(fn, thisArg, args) {
    if (typeof fn !== "function") {
      return undefined;
    }
    try {
      return fn.apply(thisArg, Array.isArray(args) ? args : []);
    } catch (error) {
      return undefined;
    }
  }

  function resolveRange(object) {
    var range = firstDefined(safeRead(object, "Range"), safeRead(object, "range"));
    return typeof range === "function" ? safeCall(range, object) : range;
  }

  function readParagraphRange(paragraph, paragraphIndex) {
    var range = resolveRange(paragraph);
    var result = { paragraphIndex: paragraphIndex };
    var start = normalizeInteger(firstDefined(safeRead(range, "Start"), safeRead(range, "start")));
    var end = normalizeInteger(firstDefined(safeRead(range, "End"), safeRead(range, "end")));
    var information = safeRead(range, "Information") || safeRead(range, "information");
    var pageNumber = typeof information === "function"
      ? normalizePositiveInteger(safeCallWithArgs(information, range, [3])) : null;
    var sectionIndex = typeof information === "function"
      ? normalizePositiveInteger(safeCallWithArgs(information, range, [2])) : null;
    pageNumber = pageNumber || normalizePositiveInteger(firstDefined(
      safeRead(range, "PageNumber"), safeRead(range, "pageNumber")
    ));
    sectionIndex = sectionIndex || normalizePositiveInteger(firstDefined(
      safeRead(range, "SectionNumber"), safeRead(range, "sectionNumber")
    ));
    if (start !== null && start >= 0) {
      result.start = start;
    }
    if (end !== null && end >= 0) {
      result.end = end;
    }
    if (pageNumber) {
      result.pageNumber = pageNumber;
    }
    if (sectionIndex) {
      result.sectionIndex = sectionIndex;
    }
    return result;
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

  function isMixedCharacterValue(value) {
    var resolved = resolveScalarValue(value);
    var text = String(resolved === null || typeof resolved === "undefined" ? "" : resolved).toLowerCase();
    return resolved === 9999999 || resolved === -9999999 ||
      text === "wdundefined" || text === "mixed" || text === "undefined";
  }

  function readCharacterFormat(range) {
    var font = firstDefined(safeRead(range, "Font"), safeRead(range, "font"), {});
    var values = {
      fontName: firstDefined(safeRead(font, "NameFarEast"), safeRead(font, "Name"), safeRead(font, "name")),
      fontSize: firstDefined(safeRead(font, "Size"), safeRead(font, "size")),
      bold: firstDefined(safeRead(font, "Bold"), safeRead(font, "bold")),
      italic: firstDefined(safeRead(font, "Italic"), safeRead(font, "italic")),
      underline: firstDefined(safeRead(font, "Underline"), safeRead(font, "underline")),
      strikeThrough: firstDefined(safeRead(font, "StrikeThrough"), safeRead(font, "strikeThrough")),
      superscript: firstDefined(safeRead(font, "Superscript"), safeRead(font, "superscript")),
      subscript: firstDefined(safeRead(font, "Subscript"), safeRead(font, "subscript")),
      allCaps: firstDefined(safeRead(font, "AllCaps"), safeRead(font, "allCaps")),
      smallCaps: firstDefined(safeRead(font, "SmallCaps"), safeRead(font, "smallCaps")),
      color: firstDefined(safeRead(font, "Color"), safeRead(font, "ColorIndex"), safeRead(font, "color")),
      highlight: firstDefined(safeRead(font, "Shading"), safeRead(font, "HighlightColorIndex"), safeRead(font, "highlight")),
      characterSpacing: firstDefined(safeRead(font, "Spacing"), safeRead(font, "characterSpacing")),
      characterScale: firstDefined(safeRead(font, "Scaling"), safeRead(font, "characterScale"))
    };
    var keys = Object.keys(values);
    var readable = keys.some(function (key) {
      return values[key] !== null && typeof values[key] !== "undefined";
    });
    var mixed = !readable || keys.some(function (key) {
      return values[key] !== null && typeof values[key] !== "undefined" &&
        isMixedCharacterValue(values[key]);
    });
    return {
      mixed: mixed,
      format: {
        fontName: toSafeString(values.fontName, ""),
        fontSize: normalizeFontSize(values.fontSize),
        bold: isMixedCharacterValue(values.bold) ? null : Boolean(resolveScalarValue(values.bold)),
        italic: isMixedCharacterValue(values.italic) ? null : Boolean(resolveScalarValue(values.italic)),
        underline: isMixedCharacterValue(values.underline) ? null : normalizeInteger(values.underline),
        strikeThrough: isMixedCharacterValue(values.strikeThrough) ? null : Boolean(resolveScalarValue(values.strikeThrough)),
        superscript: isMixedCharacterValue(values.superscript) ? null : Boolean(resolveScalarValue(values.superscript)),
        subscript: isMixedCharacterValue(values.subscript) ? null : Boolean(resolveScalarValue(values.subscript)),
        allCaps: isMixedCharacterValue(values.allCaps) ? null : Boolean(resolveScalarValue(values.allCaps)),
        smallCaps: isMixedCharacterValue(values.smallCaps) ? null : Boolean(resolveScalarValue(values.smallCaps)),
        color: isMixedCharacterValue(values.color) ? null : toSafeString(values.color, ""),
        highlight: isMixedCharacterValue(values.highlight) ? null : toSafeString(values.highlight, ""),
        characterSpacing: isMixedCharacterValue(values.characterSpacing) ? null : normalizeNumber(values.characterSpacing),
        characterScale: isMixedCharacterValue(values.characterScale) ? null : normalizeNumber(values.characterScale)
      }
    };
  }

  function callRangeMethod(range, method, args) {
    var fn = safeRead(range, method);
    if (typeof fn !== "function") {
      return null;
    }
    try {
      return fn.apply(range, args || []);
    } catch (error) {
      return null;
    }
  }

  function sliceCharacterRange(range, start, end) {
    var duplicate = callRangeMethod(range, "Duplicate", []);
    if (!duplicate) {
      duplicate = callRangeMethod(range, "duplicate", []);
    }
    if (duplicate) {
      var setRange = safeRead(duplicate, "SetRange");
      if (typeof setRange === "function") {
        try {
          setRange.call(duplicate, start, end);
          return duplicate;
        } catch (error) {
          // Fall through to the Characters API.
        }
      }
      try {
        duplicate.Start = start;
        duplicate.End = end;
        return duplicate;
      } catch (error) {
        // Fall through to the Characters API.
      }
    }
    var characters = safeRead(range, "Characters") || safeRead(range, "characters");
    if (typeof characters === "function") {
      try {
        return characters.call(range, start + 1, end);
      } catch (error) {
        return null;
      }
    }
    return null;
  }

  function extractHomogeneousFormatSegments(range, options) {
    var source = range || {};
    var text = readText(source);
    var maxSegments = Math.max(1, Number(options && options.maxSegments) || 2048);
    var segments = [];
    var insufficientReason = "";

    function fail(reason) {
      insufficientReason = reason;
    }

    function scan(start, end, candidate) {
      var value;
      var length = end - start;
      if (insufficientReason) {
        return;
      }
      if (segments.length >= maxSegments && length > 1) {
        fail("format_fragmentation_limit");
        return;
      }
      value = readCharacterFormat(candidate);
      if (!value.mixed) {
        if (segments.length >= maxSegments) {
          fail("format_fragmentation_limit");
          return;
        }
        segments.push({ start: start, end: end, format: value.format });
        return;
      }
      if (length <= 1) {
        fail("format_range_unreadable");
        return;
      }
      var middle = start + Math.floor(length / 2);
      var left = sliceCharacterRange(source, start, middle);
      var right = sliceCharacterRange(source, middle, end);
      if (!left || !right || readText(left).length !== middle - start || readText(right).length !== end - middle) {
        fail("format_range_unreadable");
        return;
      }
      scan(start, middle, left);
      scan(middle, end, right);
    }

    if (!text) {
      return { segments: [], dataStatus: "verified", segmentCount: 0 };
    }
    scan(0, text.length, source);
    if (insufficientReason) {
      return {
        segments: [],
        dataStatus: "insufficient",
        insufficientReason: insufficientReason,
        segmentCount: segments.length,
        maxSegments: maxSegments
      };
    }
    var merged = [];
    segments.forEach(function (segment) {
      var previous = merged[merged.length - 1];
      if (previous && previous.end === segment.start &&
          stableFormatReviewJson(previous.format) === stableFormatReviewJson(segment.format)) {
        previous.end = segment.end;
      } else {
        merged.push(segment);
      }
    });
    return { segments: merged, dataStatus: "verified", segmentCount: merged.length };
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

  function getTableCollection(document) {
    var content = safeRead(document, "Content") || safeRead(document, "content");
    return firstDefined(
      safeRead(document, "Tables"),
      safeRead(document, "tables"),
      safeRead(content, "Tables"),
      safeRead(content, "tables"),
      []
    );
  }

  function readTableRows(table) {
    return firstDefined(safeRead(table, "Rows"), safeRead(table, "rows"), []);
  }

  function readTableCells(row) {
    return firstDefined(safeRead(row, "Cells"), safeRead(row, "cells"), []);
  }

  function readFullDocumentReviewTable(table, tableIndex, parentCellId, tablePath, options) {
    var rows = [];
    var rowCollection = readTableRows(table);
    var currentTablePath = Array.isArray(tablePath)
      ? tablePath.slice()
      : [{ tableIndex: Number(tableIndex) || 0, rowIndex: 0, columnIndex: 0 }];
    var tableId = toSafeString(firstDefined(
      safeRead(table, "Id"), safeRead(table, "ID"), safeRead(table, "tableId")
    ), "table-" + tableIndex);
    var nestedTables = [];
    for (var rowIndex = 1; rowIndex <= readCollectionCount(rowCollection); rowIndex += 1) {
      var row = getCollectionItem(rowCollection, rowIndex);
      var cells = [];
      var cellCollection = readTableCells(row);
      for (var columnIndex = 1; columnIndex <= readCollectionCount(cellCollection); columnIndex += 1) {
        var cell = getCollectionItem(cellCollection, columnIndex);
        var cellId = toSafeString(firstDefined(
          safeRead(cell, "Id"), safeRead(cell, "ID"), safeRead(cell, "cellId")
        ), tableId + "-cell-" + rowIndex + "-" + columnIndex);
        var nestedCollection = firstDefined(safeRead(cell, "Tables"), safeRead(cell, "tables"), []);
        var nested = [];
        for (var nestedIndex = 1; nestedIndex <= readCollectionCount(nestedCollection); nestedIndex += 1) {
          nested.push(readFullDocumentReviewTable(
            getCollectionItem(nestedCollection, nestedIndex),
            nestedIndex,
            cellId,
            currentTablePath.concat([{
              tableIndex: nestedIndex,
              rowIndex: rowIndex,
              columnIndex: columnIndex
            }]),
            options
          ));
        }
        nested.forEach(function (item) { nestedTables.push(item); });
        var cellRange = resolveRange(cell);
        var cellFormat = options && options.includeCharacterFormatSegments
          ? extractHomogeneousFormatSegments(cellRange || cell, {
            maxSegments: options.maxFormatSegments || 2048
          })
          : null;
        cells.push({
          cellId: cellId,
          rowIndex: normalizePositiveInteger(firstDefined(safeRead(cell, "RowIndex"), safeRead(cell, "rowIndex"), rowIndex)) || rowIndex,
          columnIndex: normalizePositiveInteger(firstDefined(safeRead(cell, "ColumnIndex"), safeRead(cell, "columnIndex"), columnIndex)) || columnIndex,
          rowSpan: normalizePositiveInteger(firstDefined(safeRead(cell, "RowSpan"), safeRead(cell, "rowSpan"), 1)) || 1,
          columnSpan: normalizePositiveInteger(firstDefined(safeRead(cell, "ColumnSpan"), safeRead(cell, "columnSpan"), 1)) || 1,
          mergeId: toSafeString(firstDefined(safeRead(cell, "MergeId"), safeRead(cell, "mergeId")), ""),
          text: readText(cell),
          nestedTableIds: nested.map(function (item) { return item.tableId; }),
          format: cellFormat ? {
            segments: cellFormat.segments,
            dataStatus: cellFormat.dataStatus,
            insufficientReason: cellFormat.insufficientReason || ""
          } : {}
        });
      }
      if (cells.length) {
        rows.push({ rowIndex: rowIndex, cells: cells });
      }
    }
    var paragraphIndex = normalizePositiveInteger(firstDefined(
      safeRead(table, "ParagraphIndex"), safeRead(table, "paragraphIndex")
    ));
    return {
      tableId: tableId,
      tableIndex: Number(tableIndex) || 0,
      tablePath: currentTablePath,
      paragraphIndex: paragraphIndex,
      parentCellId: parentCellId || "",
      rows: rows,
      nestedTables: nestedTables,
      range: readParagraphRange(table, paragraphIndex || Number(tableIndex) || 0)
    };
  }

  function collectFullDocumentReviewTables(document, options) {
    var collection = getTableCollection(document);
    var tables = [];
    for (var index = 1; index <= readCollectionCount(collection); index += 1) {
      tables.push(readFullDocumentReviewTable(
        getCollectionItem(collection, index),
        index,
        "",
        [{ tableIndex: index, rowIndex: 0, columnIndex: 0 }],
        options
      ));
    }
    return tables;
  }

  function readFullDocumentReviewEditSignal(document) {
    var source = document || {};
    var content = safeRead(source, "Content") || safeRead(source, "content") || {};
    return [
      toSafeString(firstDefined(
        safeRead(source, "EditSequence"), safeRead(source, "editSequence"),
        safeRead(source, "RevisionNumber"), safeRead(source, "revisionNumber"),
        safeRead(content, "EditSequence"), safeRead(content, "editSequence")
      ), "")
    ].join(":");
  }

  function collectFormatReviewCoverage(document) {
    var source = document || {};
    var sections = firstDefined(safeRead(source, "Sections"), safeRead(source, "sections"));
    var unsupportedObjects = [];

    function readHeaderFooter(area) {
      var count = 0;
      var characterCount = 0;
      var failureCount = 0;
      var attempted = Boolean(sections);
      if (!sections || !readCollectionCount(sections)) {
        return { status: "unavailable", attempted: attempted, failureCount: 1 };
      }
      for (var index = 1; index <= readCollectionCount(sections); index += 1) {
        var section = getCollectionItem(sections, index);
        var collection = firstDefined(
          safeRead(section, area === "header" ? "Headers" : "Footers"),
          safeRead(section, area === "header" ? "headers" : "footers")
        );
        if (!collection) {
          failureCount += 1;
          continue;
        }
        for (var itemIndex = 1; itemIndex <= readCollectionCount(collection); itemIndex += 1) {
          var item = getCollectionItem(collection, itemIndex);
          var exists = firstDefined(safeRead(item, "Exists"), safeRead(item, "exists"));
          if (exists === false || exists === 0) {
            continue;
          }
          var text = readText(item);
          count += 1;
          characterCount += text.length;
        }
      }
      return {
        status: failureCount ? "unavailable" : "read",
        attempted: attempted,
        paragraphCount: count,
        characterCount: characterCount,
        failureCount: failureCount
      };
    }

    function addObjects(type, candidates) {
      var collection = firstDefined.apply(null, candidates.map(function (key) {
        return safeRead(source, key);
      }));
      var count = readCollectionCount(collection);
      if (count) {
        unsupportedObjects.push({ type: type, count: count, status: "not_supported" });
      }
    }

    function addFloatingShapes() {
      var collection = firstDefined(safeRead(source, "Shapes"), safeRead(source, "shapes"));
      var count = readCollectionCount(collection);
      var unsupportedCount = 0;
      for (var index = 1; index <= count; index += 1) {
        var shape = getCollectionItem(collection, index);
        var type = firstDefined(safeRead(shape, "Type"), safeRead(shape, "type"));
        var typeText = String(type || "").toLowerCase();
        var picture = type === 13 || type === 11 || /picture|image|inlinepicture|inline_image/.test(typeText) ||
          safeRead(shape, "IsPicture") === true || safeRead(shape, "isPicture") === true;
        if (!picture) {
          unsupportedCount += 1;
        }
      }
      if (unsupportedCount) {
        unsupportedObjects.push({ type: "floatingShape", count: unsupportedCount, status: "not_supported" });
      }
    }

    var header = readHeaderFooter("header");
    var footer = readHeaderFooter("footer");
    addObjects("textBox", ["TextBoxes", "textBoxes", "TextBoxObjects"]);
    addObjects("smartArt", ["SmartArt", "SmartArts", "smartArt"]);
    addObjects("equation", ["OMaths", "Equations", "MathObjects"]);
    addObjects("comment", ["Comments", "comments"]);
    addObjects("revision", ["Revisions", "revisions"]);
    addFloatingShapes();
    return {
      headerFooter: {
        header: header,
        footer: footer
      },
      unsupportedObjects: unsupportedObjects
    };
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
        lineSpacing: null,
        lineSpacingMode: null,
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
      var paragraphRange = resolveRange(paragraph);
      if (collectOptions.excludeTableParagraphs) {
        var containingTables = firstDefined(
          safeRead(paragraphRange, "Tables"),
          safeRead(paragraph, "Tables")
        );
        if (readCollectionCount(containingTables) > 0) {
          continue;
        }
      }
      var font = readFont(paragraph);
      var paragraphFormat = readParagraphFormat(paragraph);
      var characterFormat = collectOptions.includeCharacterFormatSegments
        ? extractHomogeneousFormatSegments(paragraphRange || paragraph, {
          maxSegments: collectOptions.maxFormatSegments
        })
        : null;
      var rawOutlineLevel = safeRead(paragraphFormat, "OutlineLevel");
      if (typeof rawOutlineLevel === "undefined") {
        rawOutlineLevel = safeRead(paragraphFormat, "outlineLevel");
      }
      var item = {
        index: i,
        text: limitTextLength(readText(paragraph), collectOptions.maxParagraphTextLength),
        range: readParagraphRange(paragraph, i),
        styleName: readStyleName(paragraph),
        fontName: toSafeString(firstDefined(safeRead(font, "NameFarEast"), safeRead(font, "Name")), ""),
        fontSize: normalizeFontSize(safeRead(font, "Size")),
        bold: Boolean(safeRead(font, "Bold")),
        italic: Boolean(safeRead(font, "Italic")),
        underline: normalizeInteger(firstDefined(safeRead(font, "Underline"), null)),
        alignment: normalizeAlignmentValue(safeRead(paragraphFormat, "Alignment"), ""),
        lineSpacing: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LineSpacing"), safeRead(paragraphFormat, "lineSpacing"), null)),
        lineSpacingMode: normalizeWpsLineSpacingMode(firstDefined(
          safeRead(paragraphFormat, "LineSpacingRule"), safeRead(paragraphFormat, "lineSpacingRule"), null
        )),
        firstLineIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "FirstLineIndent"), safeRead(paragraphFormat, "firstLineIndent"), null)),
        spaceBefore: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceBefore"), safeRead(paragraphFormat, "spaceBefore"), null)),
        spaceAfter: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceAfter"), safeRead(paragraphFormat, "spaceAfter"), null)),
        leftIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LeftIndent"), safeRead(paragraphFormat, "leftIndent"), null)),
        rightIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "RightIndent"), safeRead(paragraphFormat, "rightIndent"), null)),
        formatSegments: characterFormat ? characterFormat.segments : [],
        formatDataStatus: characterFormat ? characterFormat.dataStatus : "verified",
        formatInsufficientReason: characterFormat ? characterFormat.insufficientReason || "" : ""
      };
      if (typeof rawOutlineLevel !== "undefined") {
        item.outlineLevel = normalizeWpsOutlineLevel(rawOutlineLevel);
      }
      items.push(item);
    }
    if (items.length) {
      return items;
    }
    if (collectOptions.avoidFallbackTextRead) {
      return [];
    }
    return collectParagraphsFromText(readDocumentText(document), collectOptions);
  }

  function collectFullDocumentReviewParagraphs(document) {
    var collection = getParagraphCollection(document);
    var count = readCollectionCount(collection);
    var items = [];
    for (var index = 1; index <= count; index += 1) {
      var paragraph = getCollectionItem(collection, index);
      var range;
      var containingTables;
      var paragraphFormat;
      var listFormat;
      var text;
      if (!paragraph) {
        continue;
      }
      range = resolveRange(paragraph);
      containingTables = firstDefined(safeRead(range, "Tables"), safeRead(paragraph, "Tables"));
      if (readCollectionCount(containingTables) > 0) {
        continue;
      }
      text = readText(paragraph).trim();
      if (!text) {
        continue;
      }
      paragraphFormat = firstDefined(
        safeRead(paragraph, "ParagraphFormat"), safeRead(range, "ParagraphFormat"), {}
      );
      listFormat = firstDefined(safeRead(paragraph, "ListFormat"), safeRead(range, "ListFormat"), {});
      var rawOutlineLevel = safeRead(paragraphFormat, "OutlineLevel");
      if (typeof rawOutlineLevel === "undefined") {
        rawOutlineLevel = safeRead(paragraphFormat, "outlineLevel");
      }
      var item = {
        index: index,
        text: text,
        listLabel: toSafeString(firstDefined(
          safeRead(listFormat, "ListString"), safeRead(listFormat, "listString"),
          safeRead(paragraph, "ListLabel"), safeRead(paragraph, "listLabel")
        ), "")
      };
      if (typeof rawOutlineLevel !== "undefined") {
        item.outlineLevel = normalizeWpsOutlineLevel(rawOutlineLevel);
      }
      items.push(item);
    }
    return items;
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
        avoidFallbackTextRead: true,
        includeCharacterFormatSegments: collectOptions.includeCharacterFormatSegments,
        maxFormatSegments: collectOptions.maxFormatSegments
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
      page_setup_facts: options.pageSetupFacts || buildWpsPageSetupFacts(options.pageSetup || {}),
      paragraphs: paragraphs.map(function (paragraph) {
        var rawOutlineLevel = paragraph && paragraph.outlineLevel !== undefined
          ? paragraph.outlineLevel : paragraph && paragraph.outline_level;
        var item = {
          index: paragraph.index,
          text: paragraph.text || "",
          style_name: paragraph.styleName || paragraph.style_name || "",
          font_family: paragraph.fontName || paragraph.font_family || "",
          font_size_pt: normalizeFontSize(firstDefined(paragraph.fontSize, paragraph.font_size_pt)),
          bold: Boolean(paragraph.bold),
          italic: Boolean(paragraph.italic),
          underline: paragraph.underline || null,
          alignment: normalizeAlignmentValue(paragraph.alignment, ""),
          line_spacing: normalizeNumber(firstDefined(paragraph.lineSpacing, paragraph.line_spacing)),
          line_spacing_mode: normalizeWpsLineSpacingMode(firstDefined(paragraph.lineSpacingMode, paragraph.line_spacing_mode)),
          first_line_indent: normalizeNumber(firstDefined(paragraph.firstLineIndent, paragraph.first_line_indent)),
          space_before: normalizeNumber(firstDefined(paragraph.spaceBefore, paragraph.space_before)),
          space_after: normalizeNumber(firstDefined(paragraph.spaceAfter, paragraph.space_after)),
          left_indent: normalizeNumber(firstDefined(paragraph.leftIndent, paragraph.left_indent)),
          right_indent: normalizeNumber(firstDefined(paragraph.rightIndent, paragraph.right_indent))
        };
        if (typeof rawOutlineLevel !== "undefined") {
          item.outline_level = normalizeWpsOutlineLevel(rawOutlineLevel);
        }
        return item;
      }),
      headings: headings.map(function (heading) {
        var level = normalizeWpsOutlineLevel(firstDefined(heading.level, heading.outlineLevel));
        return {
          level: level > 0 ? level : null,
          text: heading.text || "",
          paragraph_index: heading.paragraphIndex || heading.index || null
        };
      }).filter(function (heading) { return heading.level !== null; }),
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
        limitedReviewReady: typeof profile.limitedReviewReady === "boolean"
          ? profile.limitedReviewReady : Boolean(profile.complete),
        fullDocumentReviewReady: Boolean(profile.fullDocumentReviewReady),
        fullDocumentReviewReadiness: profile.fullDocumentReviewReadiness || {
          code: "unavailable",
          label: "全篇审查尚未就绪。"
        },
        missingFields: Array.isArray(profile.missingFields) ? profile.missingFields : [],
        configVersion: Number(profile.configVersion || 1),
        lastValidation: profile.lastValidation || null,
        formatSemanticValidation: profile.formatSemanticValidation || null,
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

  function formatModelValidationStatus(profile, activeProfileId) {
    var item = profile || {};
    var validation = item.lastValidation;
    var identity = "配置“" + String(item.name || "未命名配置") + "”（ID：" +
      String(item.id || "未记录") + "，修订 " + String(item.configVersion || 1) + "）";
    var message;
    if (!validation) {
      return "尚未验证";
    }
    if (validation.stale) {
      return "验证已过期：" + identity + "，请重新验证。";
    }
    message = String(validation.message || "").trim();
    if (!validation.success) {
      return "验证失败：" + (message || "模型配置验证未通过") + "；" + identity + "。";
    }
    if (String(item.id || "") === String(activeProfileId || "")) {
      return "验证成功：" + identity + "，是当前 " +
        (String(item.taskType || "") === "word.format_review" ? "word.format_review" : "任务") +
        " 配置。";
    }
    return "验证成功：" + identity + "，当前任务不会使用此配置。";
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

  function createWordSelectionWatcher(options) {
    var settings = options || {};
    var refresh = typeof settings.refresh === "function" ? settings.refresh : function () {};
    var getEventSource = typeof settings.getEventSource === "function"
      ? settings.getEventSource
      : function () { return null; };
    var setTimeoutFn = typeof settings.setTimeoutFn === "function"
      ? settings.setTimeoutFn
      : (typeof setTimeout === "function" ? setTimeout : function () { return 0; });
    var clearTimeoutFn = typeof settings.clearTimeoutFn === "function"
      ? settings.clearTimeoutFn
      : (typeof clearTimeout === "function" ? clearTimeout : function () {});
    var intervalMs = typeof settings.intervalMs === "number" ? settings.intervalMs : 2000;
    var eventName = settings.eventName || "WindowSelectionChange";
    var timerId = null;
    var running = false;
    var eventSource = null;
    var eventRegistered = false;

    function safeRefresh() {
      try {
        refresh();
      } catch (error) {
        // Transient COM access failures are retried by the next host event or fallback poll.
      }
    }

    function handleSelectionChange() {
      if (!running) {
        return;
      }
      safeRefresh();
      scheduleFallback();
    }

    function registerEvent() {
      var result;
      try {
        eventSource = getEventSource();
      } catch (error) {
        eventSource = null;
      }
      if (!eventSource || typeof eventSource.AddApiEventListener !== "function") {
        eventSource = null;
        return false;
      }
      try {
        result = eventSource.AddApiEventListener(eventName, handleSelectionChange);
        eventRegistered = result !== false;
      } catch (error) {
        eventSource = null;
        eventRegistered = false;
      }
      return eventRegistered;
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
            // Event cleanup varies across WPS WebView builds; stopping polling still prevents reads.
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

  function normalizeWritingPolicyUsageCount(value) {
    var number = Number(value);
    if (!isFinite(number) || number < 0) {
      return 0;
    }
    return Math.floor(number);
  }

  function normalizeWritingPolicyUsage(value) {
    var source;
    var matchedItems;
    var conflicts;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    source = value;
    matchedItems = Array.isArray(source.matchedItems) ? source.matchedItems : [];
    conflicts = Array.isArray(source.conflicts) ? source.conflicts : [];
    return {
      applied: Boolean(source.applied),
      degraded: Boolean(source.degraded),
      degradedReason: String(source.degradedReason || ""),
      requestedScene: normalizeWritingPolicyScene(source.requestedScene),
      scene: normalizeWritingPolicyScene(source.scene),
      sceneLabel: String(source.sceneLabel || "").trim(),
      autoFallback: Boolean(source.autoFallback),
      packName: String(source.packName || "").trim(),
      packNames: (Array.isArray(source.packNames) ? source.packNames : [])
        .map(function (item) {
          return String(item || "").trim();
        })
        .filter(Boolean)
        .slice(0, 4),
      presetVersion: String(source.presetVersion || "").trim(),
      termMatchCount: normalizeWritingPolicyUsageCount(source.termMatchCount),
      styleRuleCount: normalizeWritingPolicyUsageCount(source.styleRuleCount),
      antiTemplateRuleCount: normalizeWritingPolicyUsageCount(source.antiTemplateRuleCount),
      truncatedCount: normalizeWritingPolicyUsageCount(source.truncatedCount),
      conflictCount: normalizeWritingPolicyUsageCount(source.conflictCount),
      conflicts: conflicts.filter(function (item) {
        return item && String(item.name || "").trim();
      }).slice(0, 20).map(function (item) {
        return {
          name: String(item.name || "").trim().slice(0, 120),
          winnerId: String(item.winnerId || "").slice(0, 128),
          itemIds: (Array.isArray(item.itemIds) ? item.itemIds : [])
            .map(function (itemId) {
              return String(itemId || "").slice(0, 128);
            })
            .filter(Boolean)
            .slice(0, 20)
        };
      }),
      matchedItems: matchedItems.filter(function (item) {
        return item &&
          (item.type === "term" || item.type === "style" || item.type === "anti_template") &&
          String(item.name || "").trim();
      }).slice(0, 20).map(function (item) {
        return {
          id: String(item.id || ""),
          type: item.type,
          name: String(item.name || "").trim()
        };
      })
    };
  }

  function normalizeWritingPolicyScene(value) {
    var scene = String(value || "").trim();
    return ["auto", "yangqi", "cybersecurity", "official", "disabled"].indexOf(scene) >= 0
      ? scene
      : "auto";
  }

  function writingPolicySceneStorageKey(taskType) {
    return "ai-wps:writing-policy-scene:" + String(taskType || "word.smart_write");
  }

  function normalizeWritingPolicyAuditFinding(value) {
    var source = value && typeof value === "object" ? value : {};
    return {
      code: String(source.code || "").slice(0, 80),
      tier: /^(T1|T2|T3)$/.test(String(source.tier || "")) ? String(source.tier) : "",
      label: String(source.label || "").trim().slice(0, 80),
      message: String(source.message || "").trim().slice(0, 240),
      evidence: String(source.evidence || "").trim().slice(0, 80)
    };
  }

  function normalizeWritingPolicyAudit(value) {
    var source;
    var needsReview;
    var expressionSuggestions;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    source = value;
    needsReview = Array.isArray(source.needsReview) ? source.needsReview : [];
    expressionSuggestions = Array.isArray(source.expressionSuggestions)
      ? source.expressionSuggestions
      : [];
    return {
      enabled: source.enabled !== false,
      passed: Boolean(source.passed),
      degraded: Boolean(source.degraded),
      degradedReason: String(source.degradedReason || "").trim().slice(0, 240),
      summary: String(source.summary || "").trim().slice(0, 240),
      needsReview: needsReview.slice(0, 12).map(normalizeWritingPolicyAuditFinding),
      expressionSuggestions: expressionSuggestions
        .slice(0, 12)
        .map(normalizeWritingPolicyAuditFinding)
    };
  }

  function writingPolicyAuditFindingText(value) {
    var finding = normalizeWritingPolicyAuditFinding(value);
    var text = finding.label || finding.message || "请核对该项内容";
    if (finding.label && finding.message) {
      text += "：" + finding.message;
    }
    if (finding.evidence) {
      text += "（" + finding.evidence + "）";
    }
    return text;
  }

  function writingPolicyPageState(offset, total, pageCount, pageSize) {
    var safePageSize = Number(pageSize);
    var safeTotal = Math.max(0, Number(total) || 0);
    var safeOffset = Math.max(0, Number(offset) || 0);
    var safePageCount = Math.max(0, Number(pageCount) || 0);
    if (!isFinite(safePageSize) || safePageSize < 1) {
      safePageSize = 50;
    }
    safePageSize = Math.floor(safePageSize);
    safeOffset = safeTotal
      ? Math.min(
        safeOffset,
        Math.floor((safeTotal - 1) / safePageSize) * safePageSize
      )
      : 0;
    safePageCount = Math.min(safePageCount, safePageSize, Math.max(0, safeTotal - safeOffset));
    return {
      offset: safeOffset,
      start: safeTotal ? safeOffset + 1 : 0,
      end: safeOffset + safePageCount,
      total: safeTotal,
      hasPrevious: safeOffset > 0,
      hasNext: safeOffset + safePageCount < safeTotal,
      label: safeTotal
        ? String(safeOffset + 1) + "–" + String(safeOffset + safePageCount) +
          " / " + String(safeTotal)
        : "0 / 0"
    };
  }

  function writingPolicyUsageSummary(value, taskType) {
    var usage = normalizeWritingPolicyUsage(value);
    var action;
    var summary;
    if (!usage) {
      return "";
    }
    if (!usage.applied) {
      return "写作规范暂未应用，已继续处理";
    }
    if (usage.degraded) {
      return "写作规范暂未完整应用，已继续处理";
    }
    action = taskType === "word.document_review" ? "已检查" : "已应用";
    if (usage.sceneLabel) {
      summary = "写作规范：" + action + " " + usage.sceneLabel + "（" +
        usage.termMatchCount + " 条术语、" + usage.styleRuleCount +
        " 条文体规则、" + usage.antiTemplateRuleCount + " 条去模板化规则）";
    } else if (usage.packName && usage.presetVersion) {
      summary = "写作规范：" + action + " " + usage.packName + " v" +
        usage.presetVersion + "（" +
        (usage.termMatchCount + usage.styleRuleCount) + " 条规则）";
    } else {
      summary = "写作规范：" + action + " " + usage.termMatchCount +
        " 条术语、" + usage.styleRuleCount + " 条文体规则";
    }
    if (usage.conflictCount) {
      summary += "；检测到 " + usage.conflictCount + " 组同层冲突，已按优先级裁决";
    }
    return summary;
  }

  function writingPolicyUsageDetails(value) {
    var usage = normalizeWritingPolicyUsage(value);
    var details;
    if (!usage) {
      return [];
    }
    details = usage.matchedItems.map(function (item) {
      var label = item.type === "term"
        ? "术语"
        : (item.type === "anti_template" ? "去模板化规则" : "文体规则");
      return label + "：" + item.name;
    });
    usage.conflicts.forEach(function (item) {
      details.push("冲突提示：" + item.name + "（已采用 " + item.winnerId + "）");
    });
    return details;
  }

  function validateWritingPolicyDraft(value) {
    var draft = value && typeof value === "object" ? value : {};
    var type = String(draft.type || "");
    var scope = String(draft.scope || "");
    if (type !== "term" && type !== "style" && type !== "anti_template") {
      return { ok: false, field: "type", message: "请选择规范类型。" };
    }
    if (type === "term" && scope !== "global") {
      return { ok: false, field: "scope", message: "企业术语首版仅支持全局范围。" };
    }
    if (type === "term" && !String(draft.preferredText || "").trim()) {
      return { ok: false, field: "preferredText", message: "请输入标准写法。" };
    }
    if (type !== "term" && !String(draft.name || "").trim()) {
      return { ok: false, field: "name", message: "请输入规则名称。" };
    }
    if (type !== "term" && !String(draft.ruleText || "").trim()) {
      return { ok: false, field: "ruleText", message: "请输入写作规则。" };
    }
    if (type !== "term" && (!Array.isArray(draft.taskTypes) || !draft.taskTypes.length)) {
      return { ok: false, field: "taskTypes", message: "请至少选择一个 Word 任务。" };
    }
    if (type !== "term" && (!Array.isArray(draft.sceneIds) || !draft.sceneIds.length)) {
      return { ok: false, field: "sceneIds", message: "请至少选择一个规范场景。" };
    }
    return { ok: true, field: "", message: "" };
  }

  function writingPolicyConflictField(error) {
    var code = String(error && error.adapterCode || "").toUpperCase();
    if (code === "TERM_TEXT_CONFLICT") {
      return "preferredText";
    }
    if (code === "STYLE_NAME_CONFLICT") {
      return "name";
    }
    return "";
  }

  function nextWritingPolicyTabIndex(currentIndex, key, count) {
    var total = Math.max(0, Math.floor(Number(count) || 0));
    var current = Math.max(0, Math.min(total - 1, Math.floor(Number(currentIndex) || 0)));
    if (!total) {
      return -1;
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return total - 1;
    }
    if (key === "ArrowRight") {
      return (current + 1) % total;
    }
    if (key === "ArrowLeft") {
      return (current - 1 + total) % total;
    }
    return current;
  }

  function formatWritingPolicyUpdatedAt(value) {
    var text = String(value || "").trim();
    var date;
    var formatted;
    if (!text) {
      return "尚无更新时间";
    }
    date = new Date(text);
    if (!isFinite(date.getTime())) {
      return "最近更新：" + text;
    }
    try {
      formatted = new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      }).format(date);
    } catch (error) {
      formatted = text;
    }
    return "最近更新：" + formatted;
  }

  function writingPolicyItemStateLabel(item, layer) {
    var source = item && typeof item === "object" ? item : {};
    var state = String(source.organizationState || "");
    if (layer === "preset") {
      if (state === "overridden") {
        return "组织覆盖 · " + (source.effective === false ? "未生效" : "已生效");
      }
      if (state === "disabled") {
        return "预置停用 · 未生效";
      }
      return "预置基线 · " + (source.effective === false ? "未生效" : "已生效");
    }
    return "组织自定义 · " + (source.enabled === false ? "未生效" : "已生效");
  }

  function normalizeWritingPolicyPriority(value) {
    var text = String(value == null ? "" : value).trim().toLowerCase();
    var numeric;
    if (text === "high" || text === "medium" || text === "low") {
      return text;
    }
    numeric = Number(value);
    if (!isFinite(numeric)) {
      return "medium";
    }
    return numeric >= 67 ? "high" : numeric >= 34 ? "medium" : "low";
  }

  function validateWritingPolicyImportFile(file) {
    var name = String(file && file.name || "").toLowerCase();
    var size = Number(file && file.size);
    if (!/\.(csv|xlsx)$/.test(name)) {
      return { ok: false, message: "请选择 CSV 或 XLSX 文件。" };
    }
    if (!isFinite(size) || size < 0 || size > 5 * 1024 * 1024) {
      return { ok: false, message: "导入文件不能超过 5 MB。" };
    }
    return { ok: true, message: "" };
  }

  function buildWritingPolicyImportRequest(file, contentBase64) {
    return {
      fileName: String(file && file.name || ""),
      mimeType: String(file && file.type || "application/octet-stream"),
      sizeBytes: Math.max(0, Math.floor(Number(file && file.size) || 0)),
      contentBase64: String(contentBase64 || "")
    };
  }

  function normalizeWritingPolicyConflictDecision(value) {
    return value === "skip" ? "skip" : "keep_existing";
  }

  function writingPolicyImportRowLabel(value) {
    var row = Math.max(0, Math.floor(Number(value && (value.row || value.rowNumber)) || 0));
    var message = String(value && value.message || "").trim();
    if (/^第\s*\d+\s*行/.test(message)) {
      return message;
    }
    return (row ? "第 " + row + " 行：" : "") + (message || "该行无法导入。");
  }

  function normalizeWritingPolicyImportPreview(value) {
    var source = value && typeof value === "object" ? value : {};
    var errors = Array.isArray(source.errors) ? source.errors : [];
    var conflicts = Array.isArray(source.conflicts) ? source.conflicts : [];
    var changes = Array.isArray(source.changes) ? source.changes : [];
    function totalCount(value, fallback) {
      var number = Number(value);
      return isFinite(number) && number >= 0 ? Math.floor(number) : fallback;
    }
    return {
      previewToken: String(source.previewToken || ""),
      fileDigest: String(source.fileDigest || ""),
      stats: {
        newCount: totalCount(source.newCount, 0),
        modifyCount: totalCount(source.modifyCount, totalCount(source.updateCount, 0)),
        disableCount: totalCount(source.disableCount, 0),
        restoreCount: totalCount(source.restoreCount, 0),
        deleteCount: totalCount(source.deleteCount, 0),
        conflictCount: totalCount(source.conflictCount, conflicts.length),
        errorCount: totalCount(source.errorCount, errors.length)
      },
      changes: changes.slice(0, 100).map(function (item) {
        return {
          rowNumber: normalizeWritingPolicyUsageCount(item && (item.rowNumber || item.row)),
          action: String(item && item.action || ""),
          name: String(item && item.name || "")
        };
      }),
      errors: errors.slice(0, 100).map(function (item) {
        return {
          row: normalizeWritingPolicyUsageCount(item && (item.row || item.rowNumber)),
          message: writingPolicyImportRowLabel(item)
        };
      }),
      conflicts: conflicts.slice(0, 100).map(function (item) {
        return {
          rowNumber: normalizeWritingPolicyUsageCount(item && (item.rowNumber || item.row)),
          message: writingPolicyImportRowLabel(item),
          incomingName: String(item && item.incomingName || ""),
          existingName: String(item && item.existingName || ""),
          decision: "keep_existing"
        };
      })
    };
  }

  function writingPolicyImportCountLabel(label, totalCount, visibleCount) {
    var total = Math.max(0, Math.floor(Number(totalCount) || 0));
    var visible = Math.max(0, Math.floor(Number(visibleCount) || 0));
    if (visible < total) {
      return String(label || "") + "（显示前 " + visible + " 条，共 " + total + " 条）";
    }
    return String(label || "") + "（共 " + total + " 条）";
  }

  function buildWritingPolicyImportApplyRequest(preview) {
    var source = preview && typeof preview === "object" ? preview : {};
    var conflicts = Array.isArray(source.conflicts) ? source.conflicts : [];
    return {
      previewToken: String(source.previewToken || ""),
      fileDigest: String(source.fileDigest || ""),
      acceptedConflictRows: conflicts.map(function (item) {
        return {
          rowNumber: Math.max(0, Math.floor(Number(item && item.rowNumber) || 0)),
          decision: normalizeWritingPolicyConflictDecision(item && item.decision)
        };
      }).filter(function (item) {
        return item.rowNumber > 0;
      })
    };
  }

  function isWritingPolicyPreviewExpired(error) {
    var code = String(error && error.adapterCode || "").toUpperCase();
    return Boolean(error && (error.httpStatus === 404 || error.httpStatus === 410)) ||
      code === "IMPORT_PREVIEW_NOT_FOUND" || code === "IMPORT_PREVIEW_EXPIRED";
  }

  return {
    normalizeText: normalizeText,
    sha256Text: sha256Text,
    getFullDocumentReviewCapacity: getFullDocumentReviewCapacity,
    getDeterministicFormatReviewCapacity: getDeterministicFormatReviewCapacity,
    buildFullDocumentReviewBody: buildFullDocumentReviewBody,
    buildFullDocumentReviewBatches: buildFullDocumentReviewBatches,
    buildDeterministicFormatReviewBody: buildDeterministicFormatReviewBody,
    normalizeDeterministicFormatReviewBlock: normalizeDeterministicFormatReviewBlock,
    buildDeterministicFormatReviewBatches: buildDeterministicFormatReviewBatches,
    normalizeWpsLineSpacingFact: normalizeWpsLineSpacingFact,
    buildWpsPageSetupFacts: buildWpsPageSetupFacts,
    buildWpsFormatFacts: buildWpsFormatFacts,
    escapeHtml: escapeHtml,
    renderMarkdown: renderMarkdown,
    buildInlineWritebackRuns: buildInlineWritebackRuns,
    buildMarkdownWritebackBlocks: buildMarkdownWritebackBlocks,
    hasStructuredSmartWriteContent: hasStructuredSmartWriteContent,
    shouldUseStructuredSmartWriteResult: shouldUseStructuredSmartWriteResult,
    formatSmartWriteResult: formatSmartWriteResult,
    buildSmartWritePreviewModel: buildSmartWritePreviewModel,
    presentWordResultView: presentWordResultView,
    renderReadableDeterministicFormatReview: renderReadableDeterministicFormatReview,
    appendFormatFactDiagnostics: appendFormatFactDiagnostics,
    formatReviewRole: formatReviewRole,
    formatReviewRule: formatReviewRule,
    formatDeterministicFormatReviewIssueLocation: formatDeterministicFormatReviewIssueLocation,
    buildDocumentReviewRecord: buildDocumentReviewRecord,
    getEffectiveSelectionText: getEffectiveSelectionText,
    getWritableSelection: getWritableSelection,
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection,
    firstDefined: firstDefined,
    readCollectionCount: readCollectionCount,
    getCollectionItem: getCollectionItem,
    getParagraphCollection: getParagraphCollection,
    collectFullDocumentReviewParagraphs: collectFullDocumentReviewParagraphs,
    collectFullDocumentReviewTables: collectFullDocumentReviewTables,
    collectFormatReviewCoverage: collectFormatReviewCoverage,
    extractHomogeneousFormatSegments: extractHomogeneousFormatSegments,
    readFullDocumentReviewEditSignal: readFullDocumentReviewEditSignal,
    collectParagraphs: collectParagraphs,
    normalizeWpsOutlineLevel: normalizeWpsOutlineLevel,
    collectHeadingsFromParagraphs: collectHeadingsFromParagraphs,
    collectParagraphsFromSelectionSources: collectParagraphsFromSelectionSources,
    collectParagraphsFromText: collectParagraphsFromText,
    readDocumentText: readDocumentText,
    toSafeString: toSafeString,
    buildDocumentStructure: buildDocumentStructure,
    normalizeWorkflowProfileData: normalizeWorkflowProfileData,
    getActiveWorkflowProfileName: getActiveWorkflowProfileName,
    formatModelValidationStatus: formatModelValidationStatus,
    deriveModelInterfaceState: deriveModelInterfaceState,
    normalizeAdapterHealth: normalizeAdapterHealth,
    createSettingsRefreshController: createSettingsRefreshController,
    createWordSelectionWatcher: createWordSelectionWatcher,
    canDeleteWorkflowProfile: canDeleteWorkflowProfile,
    workflowProfileStatusText: workflowProfileStatusText,
    workflowProfileOptionState: workflowProfileOptionState,
    validateWorkflowProfileDraft: validateWorkflowProfileDraft,
    shouldActivateNewWorkflowProfile: shouldActivateNewWorkflowProfile,
    normalizeWritingPolicyUsage: normalizeWritingPolicyUsage,
    normalizeWritingPolicyScene: normalizeWritingPolicyScene,
    writingPolicySceneStorageKey: writingPolicySceneStorageKey,
    normalizeWritingPolicyAudit: normalizeWritingPolicyAudit,
    writingPolicyAuditFindingText: writingPolicyAuditFindingText,
    writingPolicyPageState: writingPolicyPageState,
    writingPolicyUsageSummary: writingPolicyUsageSummary,
    writingPolicyUsageDetails: writingPolicyUsageDetails,
    validateWritingPolicyDraft: validateWritingPolicyDraft,
    writingPolicyConflictField: writingPolicyConflictField,
    nextWritingPolicyTabIndex: nextWritingPolicyTabIndex,
    formatWritingPolicyUpdatedAt: formatWritingPolicyUpdatedAt,
    writingPolicyItemStateLabel: writingPolicyItemStateLabel,
    normalizeWritingPolicyPriority: normalizeWritingPolicyPriority,
    validateWritingPolicyImportFile: validateWritingPolicyImportFile,
    buildWritingPolicyImportRequest: buildWritingPolicyImportRequest,
    normalizeWritingPolicyConflictDecision: normalizeWritingPolicyConflictDecision,
    writingPolicyImportRowLabel: writingPolicyImportRowLabel,
    normalizeWritingPolicyImportPreview: normalizeWritingPolicyImportPreview,
    writingPolicyImportCountLabel: writingPolicyImportCountLabel,
    buildWritingPolicyImportApplyRequest: buildWritingPolicyImportApplyRequest,
    isWritingPolicyPreviewExpired: isWritingPolicyPreviewExpired
  };
});
