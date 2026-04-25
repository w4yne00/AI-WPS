function OnAddinLoad(ribbonUI) {
  if (typeof window.Application.ribbonUI !== "object") {
    window.Application.ribbonUI = ribbonUI;
  }

  if (typeof window.Application.Enum !== "object" && typeof WPS_Enum !== "undefined") {
    window.Application.Enum = WPS_Enum;
  }

  return true;
}

function OnAction(control) {
  if (control.Id === "btnWpsAiAssistant") {
    try {
      var url = location.href.replace(/[^\/]*$/, "");
      var taskPane = window.Application.CreateTaskPane(url + "taskpane.html");
      taskPane.Visible = true;
    } catch (error) {
      window.Application.confirm("错误：" + error.message);
    }
  }

  return true;
}
