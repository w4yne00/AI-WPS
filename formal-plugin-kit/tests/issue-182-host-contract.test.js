const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { etRoot, wordRoot, pptRoot } = require("./support/plugin-roots");

const hosts = [
  { name: "Word", root: wordRoot, historyViewId: "word-history-view" },
  { name: "Excel", root: etRoot, historyViewId: "excel-history-view" },
  { name: "PPT", root: pptRoot, historyViewId: "ppt-history-view" },
];

function readHost(root) {
  return {
    html: fs.readFileSync(path.join(root, "taskpane.html"), "utf8"),
    js: fs.readFileSync(path.join(root, "taskpane.js"), "utf8"),
  };
}

test("three hosts expose one shared direct-service home and a single Key field", () => {
  hosts.forEach((host) => {
    const { html, js } = readHost(host.root);
    const source = html + "\n" + js;
    assert.match(html, /id="direct-services-card"/, `${host.name} missing shared service card`);
    assert.match(html, /id="btn-new-direct-service"/, `${host.name} missing create service button`);
    assert.match(html, /id="direct-service-key"/, `${host.name} missing Key field`);
    assert.equal(
      source.includes("direct-service-key-confirm"),
      false,
      `${host.name} must not confirm shared Key twice`
    );
    assert.match(
      source,
      /id="workflow-editor-key-confirm"|data-workflow-editor-key-confirm/,
      `${host.name} must keep per-task workflow Key confirmation`
    );
  });
});

test("three hosts keep history in the result area with copy and clear, without write-back", () => {
  hosts.forEach((host) => {
    const { html, js } = readHost(host.root);
    assert.match(html, new RegExp(`id="${host.historyViewId}"`), `${host.name} missing history view`);
    assert.match(html, /id="btn-view-history"/, `${host.name} missing history entry`);
    assert.match(html, /id="btn-clear-history"/, `${host.name} missing clear-history`);
    assert.match(html, /id="btn-history-back"/, `${host.name} missing return-to-active`);
    assert.equal(
      /id="excel-history-view"[\s\S]{0,1200}写回/.test(html),
      false,
      `${host.name} history markup must not offer write-back`
    );
    assert.match(js, /\/history/, `${host.name} must call history API`);
  });
});
