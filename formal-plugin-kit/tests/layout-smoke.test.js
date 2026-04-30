const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html",
  "utf8"
);

assert.ok(html.includes('id="home-view"'));
assert.ok(html.includes('id="settings-view"'));
assert.ok(html.includes('id="btn-open-settings"'));
assert.ok(html.includes('id="btn-close-settings"'));
assert.ok(html.includes('id="btn-save-api-key"'));
assert.ok(html.includes('id="btn-probe"'));
assert.ok(html.includes('id="connection-settings-section"'));
assert.ok(html.includes('id="diagnostics-section"'));
assert.ok(html.includes('id="btn-copy-result"'));
assert.ok(html.includes('id="top-toolbox"'));
assert.ok(html.includes('id="scope-strip"'));
assert.ok(!html.includes('hero-copy'));
assert.ok(!html.includes('comparison-view'));
assert.ok(!html.includes('original-output'));
assert.ok(!html.includes('rewritten-output'));

const js = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js",
  "utf8"
);

assert.ok(js.includes("startScopeWatcher"));
assert.ok(js.includes("setInterval(updateScopeIndicator"));

console.log("layout smoke tests passed");
