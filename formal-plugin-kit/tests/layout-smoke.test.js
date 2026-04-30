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

console.log("layout smoke tests passed");
