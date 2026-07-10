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
    btnAiPptSlideAssistant: "pptSlideAssistant",
    btnAiSettings: "settings"
  };
  return modeMap[controlId] || "pptSlideAssistant";
}

var ribbonIconMap = {
  btnAiPptSlideAssistant: "assets/icon-ppt-slide-assistant.png",
  btnAiSettings: "assets/icon-settings.png"
};

function GetImage(control) {
  var controlId = control && (control.Id || control.id);
  return ribbonIconMap[controlId] || "assets/ai-assistant-32.png";
}

function closeCurrentTaskPane() {
  var current = window.Application.WpsAiAssistantPptTaskPane;
  if (!current) {
    return;
  }

  try {
    current.Visible = false;
  } catch (error) {
    // Some WPS builds expose stale task pane handles after manual close.
  }
}

function OnAction(control) {
  try {
    var mode = resolveMode(control.Id || control.id);
    var url = location.href.replace(/[^/]*$/, "");
    closeCurrentTaskPane();
    var taskPane = window.Application.CreateTaskPane(
      url + "taskpane.html?mode=" + encodeURIComponent(mode) + "&build=0.17.0-alpha"
    );
    window.Application.WpsAiAssistantPptTaskPane = taskPane;
    taskPane.Visible = true;
  } catch (error) {
    window.Application.confirm("错误：" + error.message);
  }

  return true;
}
