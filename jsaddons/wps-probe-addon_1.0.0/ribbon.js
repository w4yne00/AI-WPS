
function OnAddinLoad(ribbonUI) {
  if (typeof window.Application.ribbonUI != "object") {
    window.Application.ribbonUI = ribbonUI;
  }

  if (typeof window.Application.Enum != "object") {
    // 如果没有内置枚举值
    window.Application.Enum = WPS_Enum;
  }
 
  return true;
}


function OnAction(control) {
  const eleId = control.Id;
  switch (eleId) {
    case "btnRuntimeProbe":
      {       
          try{				 
           		 var url = location.href.replace(/[^\/]*$/, '');
				//const  taskPaneUrl="/taskpane.html";
				let tskpane = window.Application.CreateTaskPane( url+"taskpane.html");
      			tskpane.Visible = true;
		}catch(error){
		 window.Application.confirm('错误：'+error.message);
		}
      }
      break;    
    default:
      break;
  }
  return true;
}


