const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function loadPptHelpers() {
  const source = fs.readFileSync(
    "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js",
    "utf8"
  );
  const context = { window: {} };
  vm.runInNewContext(source, context);
  return context.window.WpsAiPptHelpers;
}

const hosts = [
  {
    name: "Word",
    root: "formal-plugin-kit/wps-ai-assistant_1.0.0",
    helpers: require("../wps-ai-assistant_1.0.0/taskpane-helpers.js")
  },
  {
    name: "Excel",
    root: "formal-plugin-kit/wps-ai-assistant-et_1.0.0",
    helpers: require("../wps-ai-assistant-et_1.0.0/taskpane-helpers.js")
  },
  {
    name: "PPT",
    root: "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0",
    helpers: loadPptHelpers()
  }
];

hosts.forEach(({ name, root, helpers }) => {
  assert.strictEqual(
    typeof helpers.normalizeAdapterHealth,
    "function",
    `${name} must export normalizeAdapterHealth`
  );

  const ready = helpers.normalizeAdapterHealth({
    status: "ready",
    operationPolicy: {
      configurationMutationsAllowed: true,
      modelTasksAllowed: true,
      writingPolicyMutationsAllowed: true
    }
  }, true);
  assert.strictEqual(ready.status, "ready", name);
  assert.strictEqual(ready.badgeLabel, "已连接", name);
  assert.strictEqual(ready.modelTasksAllowed, true, name);

  const degraded = helpers.normalizeAdapterHealth({
    status: "degraded",
    operationPolicy: {
      configurationMutationsAllowed: true,
      modelTasksAllowed: true,
      writingPolicyMutationsAllowed: false
    }
  }, true);
  assert.strictEqual(degraded.status, "degraded", name);
  assert.strictEqual(degraded.badgeClass, "badge-warn", name);
  assert.strictEqual(degraded.badgeLabel, "增强降级", name);
  assert.strictEqual(degraded.configurationMutationsAllowed, true, name);
  assert.strictEqual(degraded.modelTasksAllowed, true, name);
  assert.strictEqual(degraded.writingPolicyMutationsAllowed, false, name);

  const recovery = helpers.normalizeAdapterHealth({
    status: "recovery",
    operationPolicy: {
      configurationMutationsAllowed: true,
      modelTasksAllowed: true,
      writingPolicyMutationsAllowed: true
    }
  }, true);
  assert.strictEqual(recovery.status, "recovery", name);
  assert.strictEqual(recovery.badgeClass, "badge-error", name);
  assert.strictEqual(recovery.badgeLabel, "恢复模式", name);
  assert.strictEqual(recovery.configurationMutationsAllowed, false, name);
  assert.strictEqual(recovery.modelTasksAllowed, false, name);
  assert.strictEqual(recovery.writingPolicyMutationsAllowed, false, name);
  assert.ok(!JSON.stringify(recovery).includes("subsystems"), name);

  const unavailable = helpers.normalizeAdapterHealth(null, false);
  assert.strictEqual(unavailable.status, "unavailable", name);
  assert.strictEqual(unavailable.badgeClass, "badge-error", name);
  assert.strictEqual(unavailable.badgeLabel, "未连接", name);

  const unknown = helpers.normalizeAdapterHealth({ status: "unexpected" }, true);
  assert.strictEqual(unknown.status, "recovery", name);
  assert.strictEqual(unknown.connected, true, name);
  assert.strictEqual(unknown.configurationMutationsAllowed, false, name);
  assert.strictEqual(unknown.modelTasksAllowed, false, name);
  assert.strictEqual(unknown.writingPolicyMutationsAllowed, false, name);

  const taskpane = fs.readFileSync(`${root}/taskpane.js`, "utf8");
  assert.ok(taskpane.includes("helpers.normalizeAdapterHealth"), `${name} taskpane health normalization`);
  assert.ok(taskpane.includes("adapterHealthStatus"), `${name} taskpane health state`);
  assert.ok(taskpane.includes('healthState.status === "recovery"'), `${name} recovery rendering`);
  assert.ok(taskpane.includes('blockedCode = "ADAPTER_RECOVERY_MODE"'), `${name} recovery request guard`);
});

const wordTaskpane = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js",
  "utf8"
);
assert.ok(
  wordTaskpane.includes('"WRITING_POLICY_READ_ONLY"'),
  "Word writing-policy mutations must be blocked while degraded"
);

console.log("adapter health contract tests passed");
