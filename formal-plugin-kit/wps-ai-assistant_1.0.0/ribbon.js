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
    btnAiSmartWrite: "smartWrite",
    btnAiSmartImitation: "smartImitation",
    btnAiDocumentReview: "documentReview",
    btnAiFormatReview: "formatReview",
    btnAiSettings: "settings",
    btnWpsAiAssistant: "smartWrite"
  };
  return modeMap[controlId] || "smartWrite";
}

var ribbonIconMap = {
  btnAiSmartWrite: "assets/icon-smart-write.png",
  btnAiSmartImitation: "assets/icon-smart-imitation.png",
  btnAiDocumentReview: "assets/icon-review.png",
  btnAiFormatReview: "assets/icon-format.png",
  btnAiSettings: "assets/icon-settings.png",
  btnWpsAiAssistant: "assets/ai-assistant-32.png"
};

function GetImage(control) {
  var controlId = control && (control.Id || control.id);
  return ribbonIconMap[controlId] || "assets/ai-assistant-32.png";
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
    var taskPane = window.Application.CreateTaskPane(
      url + "taskpane.html?mode=" + encodeURIComponent(mode) + "&build=0.18.0-alpha"
    );
    window.Application.WpsAiAssistantTaskPane = taskPane;
    taskPane.Visible = true;
  } catch (error) {
    window.Application.confirm("错误：" + error.message);
  }

  return true;
}
