const assert = require("assert");

const helpers = require("../wps-ai-assistant-et_1.0.0/taskpane-helpers.js");

function testDraftMergingBeforeRenderEnsuresDomMemorySync() {
  const initialResult = {
    items: [
      { itemId: "target-1", status: "completed", value: "初始值1", valueType: "text" },
      { itemId: "target-2", status: "completed", value: "初始值2", valueType: "text" }
    ]
  };
  const targetItems = [
    { itemId: "target-1", address: "$C$2", originalValue: "", originalValueType: "blank" },
    { itemId: "target-2", address: "$C$3", originalValue: "", originalValueType: "blank" }
  ];

  // User edited item 1 and unchecked item 2
  const userEditedDrafts = [
    { itemId: "target-1", status: "completed", value: "用户修改的值1", valueType: "text", selected: true },
    { itemId: "target-2", status: "completed", value: "初始值2", valueType: "text", selected: false }
  ];

  // Retry response comes back for item 2
  const retryResult = {
    items: [
      { itemId: "target-1", status: "completed", value: "初始值1", valueType: "text" },
      { itemId: "target-2", status: "completed", value: "重试生成的新值2", valueType: "text" }
    ]
  };

  // Merge logic: preserve user edits for items other than retryItemId (target-2)
  const preservedForRetry = userEditedDrafts.filter(d => d.itemId !== "target-2");
  const preservedMap = {};
  preservedForRetry.forEach(d => { preservedMap[d.itemId] = d; });

  const finalDraftItems = retryResult.items.map(item => {
    const preserved = preservedMap[item.itemId];
    if (preserved) {
      return {
        itemId: item.itemId,
        status: preserved.status !== undefined ? preserved.status : item.status,
        valueType: (preserved.valueType || item.valueType) === "number" ? "number" : "text",
        value: preserved.value !== undefined ? preserved.value : (item.status === "completed" ? item.value : ""),
        selected: preserved.selected !== undefined ? Boolean(preserved.selected) : item.status === "completed"
      };
    }
    return {
      itemId: item.itemId,
      status: item.status,
      valueType: item.valueType === "number" ? "number" : "text",
      value: item.status === "completed" ? item.value : "",
      selected: item.status === "completed"
    };
  });

  // 1. Verify memory drafts have user's edited value for item 1 and new retry value for item 2
  assert.strictEqual(finalDraftItems[0].value, "用户修改的值1");
  assert.strictEqual(finalDraftItems[0].selected, true);
  assert.strictEqual(finalDraftItems[1].value, "重试生成的新值2");
  assert.strictEqual(finalDraftItems[1].selected, true);

  // 2. Render HTML preview with these exact drafts
  const html = helpers.buildExcelSmartFillEditorPreview(retryResult, targetItems, finalDraftItems);

  // 3. Verify rendered DOM contains the user edited value for item 1 and new value for item 2
  assert.ok(html.includes('value="用户修改的值1"'), "DOM must render preserved user edit for item 1");
  assert.ok(html.includes('value="重试生成的新值2"'), "DOM must render new retried value for item 2");
  assert.ok(html.includes('data-smart-fill-select="target-1" checked'), "Item 1 checkbox must be checked");
  assert.ok(html.includes('data-smart-fill-select="target-2" checked'), "Item 2 checkbox must be checked after successful retry");
}

function testRetryCancellationRestoresExactDomAndMemoryState() {
  const baseResult = {
    items: [
      { itemId: "target-1", status: "completed", value: "模型值1", valueType: "text" },
      { itemId: "target-2", status: "completed", value: "模型值2", valueType: "text" }
    ]
  };
  const targetItems = [
    { itemId: "target-1", address: "$C$2", originalValue: "", originalValueType: "blank" },
    { itemId: "target-2", address: "$C$3", originalValue: "", originalValueType: "blank" }
  ];

  // User had custom edits on base
  const baseDraftItems = [
    { itemId: "target-1", status: "completed", value: "保留的用户编辑1", valueType: "text", selected: true },
    { itemId: "target-2", status: "completed", value: "保留的用户编辑2", valueType: "text", selected: false }
  ];

  // When retry is cancelled or fails, restore using baseDraftItems as preserved drafts
  const preservedMap = {};
  baseDraftItems.forEach(d => { preservedMap[d.itemId] = d; });

  const restoredDraftItems = baseResult.items.map(item => {
    const preserved = preservedMap[item.itemId];
    return {
      itemId: item.itemId,
      status: preserved.status,
      valueType: preserved.valueType,
      value: preserved.value,
      selected: preserved.selected
    };
  });

  const html = helpers.buildExcelSmartFillEditorPreview(baseResult, targetItems, restoredDraftItems);

  assert.strictEqual(restoredDraftItems[0].value, "保留的用户编辑1");
  assert.strictEqual(restoredDraftItems[0].selected, true);
  assert.strictEqual(restoredDraftItems[1].value, "保留的用户编辑2");
  assert.strictEqual(restoredDraftItems[1].selected, false);

  assert.ok(html.includes('value="保留的用户编辑1"'));
  assert.ok(html.includes('value="保留的用户编辑2"'));
  assert.ok(html.includes('data-smart-fill-select="target-1" checked'));
  assert.ok(!html.includes('data-smart-fill-select="target-2" checked'));
}

function testPreflightConflictMarksAllCardsWithoutDestroyingEditor() {
  const result = {
    items: [
      { itemId: "target-1", status: "completed", value: "生成值1", valueType: "text" },
      { itemId: "target-2", status: "completed", value: "生成值2", valueType: "text" }
    ]
  };
  const targetItems = [
    { itemId: "target-1", address: "$C$2", originalValue: "", originalValueType: "blank" },
    { itemId: "target-2", address: "$C$3", originalValue: "", originalValueType: "blank" }
  ];

  const drafts = [
    { itemId: "target-1", status: "completed", value: "生成值1", valueType: "text", selected: true },
    { itemId: "target-2", status: "completed", value: "生成值2", valueType: "text", selected: true }
  ];

  // Simulate preflight failure (e.g. source changed or workbook changed)
  drafts.forEach(draft => {
    draft.status = "write_conflict";
    draft.selected = false;
  });

  const html = helpers.buildExcelSmartFillEditorPreview(result, targetItems, drafts);

  // Editor must still be structured HTML with conflict status
  assert.ok(html.includes('class="smart-fill-result-list"'), "Editor markup must be retained");
  assert.ok(html.includes('写入冲突'), "Conflict badges must be shown");
  assert.ok(html.includes('is-conflict'), "Conflict CSS class must be applied");
  assert.ok(!html.includes('data-smart-fill-select="target-1" checked'), "Conflict items must be unchecked");
  assert.ok(!html.includes('data-smart-fill-select="target-2" checked'), "Conflict items must be unchecked");
}

testDraftMergingBeforeRenderEnsuresDomMemorySync();
testRetryCancellationRestoresExactDomAndMemoryState();
testPreflightConflictMarksAllCardsWithoutDestroyingEditor();

console.log("Excel smart fill DOM & state tests passed");
