function OnAddinLoad(ribbonUI) {
  if (typeof window.Application.ribbonUI !== "object") {
    window.Application.ribbonUI = ribbonUI;
  }

  if (typeof window.Application.Enum !== "object" && typeof WPS_Enum !== "undefined") {
    window.Application.Enum = WPS_Enum;
  }

  return true;
}

function resolveMode(controlId) {
  var modeMap = {
    btnAiRewrite: "rewrite",
    btnAiContinue: "continue",
    btnAiProofread: "proofread",
    btnAiFormat: "format",
    btnAiSettings: "settings",
    btnWpsAiAssistant: "rewrite"
  };
  return modeMap[controlId] || "rewrite";
}

function closeCurrentTaskPane() {
  var current = window.Application.WpsAiAssistantTaskPane;
  if (!current) {
    return;
  }

  try {
    current.Visible = false;
  } catch (error) {
    // Some WPS builds expose stale taskpane handles after manual close.
  }
}

function OnAction(control) {
  try {
    var mode = resolveMode(control.Id || control.id);
    var url = location.href.replace(/[^\/]*$/, "");
    closeCurrentTaskPane();
    var taskPane = window.Application.CreateTaskPane(url + "taskpane.html?mode=" + encodeURIComponent(mode));
    window.Application.WpsAiAssistantTaskPane = taskPane;
    taskPane.Visible = true;
  } catch (error) {
    window.Application.confirm("错误：" + error.message);
  }

  return true;
}
