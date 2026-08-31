const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "../../..");
const FORMAL_KIT_ROOT = path.resolve(__dirname, "../..");

const wordRoot = process.env.AI_WPS_WORD_PLUGIN_DIR
  ? path.resolve(process.env.AI_WPS_WORD_PLUGIN_DIR)
  : path.join(FORMAL_KIT_ROOT, "wps-ai-assistant_1.0.0");
const wordPluginDir = wordRoot;

const etRoot = process.env.AI_WPS_ET_PLUGIN_DIR
  ? path.resolve(process.env.AI_WPS_ET_PLUGIN_DIR)
  : path.join(FORMAL_KIT_ROOT, "wps-ai-assistant-et_1.0.0");
const etPluginDir = etRoot;

const pptRoot = process.env.AI_WPS_PPT_PLUGIN_DIR
  ? path.resolve(process.env.AI_WPS_PPT_PLUGIN_DIR)
  : path.join(FORMAL_KIT_ROOT, "wps-ai-assistant-wpp_1.0.0");
const pptPluginDir = pptRoot;

const deliveryRoot = process.env.AI_WPS_DELIVERY_ROOT
  ? path.resolve(process.env.AI_WPS_DELIVERY_ROOT)
  : null;

const adapterServiceDir = deliveryRoot
  ? path.join(deliveryRoot, "packages/adapter-start-kit/adapter_service")
  : process.env.PYTHONPATH || path.join(REPO_ROOT, "adapter_service");

const adapterStartKitRoot = deliveryRoot
  ? path.join(deliveryRoot, "packages/adapter-start-kit")
  : path.join(REPO_ROOT, "adapter-start-kit");

module.exports = {
  REPO_ROOT,
  FORMAL_KIT_ROOT,
  wordRoot,
  wordPluginDir,
  etRoot,
  etPluginDir,
  pptRoot,
  pptPluginDir,
  deliveryRoot,
  adapterServiceDir,
  adapterStartKitRoot,
};
