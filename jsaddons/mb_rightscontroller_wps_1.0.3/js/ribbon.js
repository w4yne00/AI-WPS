// 记录保存前的文档全路径，对比保存后判断是否另存
var g_lastDoc = "";
// 记录是否存在权限控制接口，默认按照不存在
var g_hasRightsInfo = false;
var g_debugRights = false;
// app对象
var g_app = wps.WpsApplication();

// 编辑相关控件
var g_editList = [
    "FileSaveAsPdfOrXps",       // 输出为PDF
    "ExportToPDF",              // 输出为PDF
    "FileOfdPrintMenu",         // 输出为OFD
    "FileSaveAsPicture",        // 输出为图片
    "FileExportToPDF",          // 输出为PDF
    "FileSaveAsOFD",            // 输出为OFD
    "FileSaveAs",               // 另存为
    "FileSaveAsMenu",           // 另存为
    "FileSave",                 // 保存
    "FileMenuSendMail",         // 发送邮件
    "FileShare",                // 分享
    "DocumentSplitAndMerge",    // 文档拆分合并
    "DocumentSplit",            // 文档拆分
    "DocumentMerge",            // 文档合并
    "FileMenuPackageMenu",      // 文件打包
    "FilePackageIntoFolder",    // 打包成文件夹
    "FilePackageIntoZip"        // 打包成压缩文件
];
// 打印相关控件
var g_printList = [
    "FilePrint",                // 打印
    "FilePrintQuick",           // 直接打印
    "TabPrintPreview",          // 打印预览
    "FilePrintPreview",         // 打印，打印预览
    "FilePrintMenu"            // 打印菜单
];

// 权限
var FILE_RIGHT = {
    READ: 0x00000001,
    COPY: 0x00000010,
    EDIT: 0x00000100,
    PASTE: 0x00000040,
    PRINT: 0x00001000,
    WMPRINT: 0x00002000,
    ALL: 0xffffffff
};
function MBFile(temppath, temprights, tempIsMB) {
    this.path = temppath;
    this.rights = temprights;
    this.ismbfile = tempIsMB;
    this.HasRights = function (right) {
        if (this.rights & right) {
            return true;
        }
        return false;
    };
}
// 当前文件权限
var g_currentMBRights;
var g_mbList = new Array();

// 发送关闭消息
function SendFileClose(filePath) {
    return ;
    var closeAsObj = {};
    closeAsObj.method = "SL_FileClose";
    closeAsObj.file = filePath;
    ajax_method(
        ToJsonString(closeAsObj),
        function (jsonObj) {},
        function (jsonObj) {}
    );
}
// 发送另存消息
function SendFileSaveAs(srcFile, destFile) {
    // 发送另存消息
    var saveAsObj = {};
    saveAsObj.method = "SL_AddFileSaveAsList";
    saveAsObj.srcFile = srcFile;
    saveAsObj.dstFile = destFile;
    ajax_method(
        ToJsonString(saveAsObj),
        function (jsonObj) {},
        function (jsonObj) {}
    );
}

function AddMBList(path, rights) {
    var tempFile = new MBFile(path, rights);
    g_mbList.push(tempFile);
    log("添加 " + tempFile.path + " " + tempFile.rights);
}
function RemoveMBFile(path) {
    if (path == null || path == undefined || path == "") {
        return;
    }
    for (i = 0; i < g_mbList.length; i++) {
        if (g_mbList[i].path == path) {
            g_mbList.splice(i, 1);
            log("移除 " + path);
            break;
        }
    }
}

// 读取端口信息
function GetServerPort() {
    GetIniData();
}
// 枚举所有的wps权限信息，避免未定义报错
var ksoRightsInfo = {
    ksoNoneRight: 0x0000,
    ksoModifyRight: 0x0001,
    ksoCopyRight: 0x0002,
    ksoPrintRight: 0x0004,
    ksoSaveRight: 0x0008,
    ksoBackupRight: 0x0010,
    ksoVbaRight: 0x0020,
    ksoSaveAsRight: 0x0040,
    ksoFullRight: -1
};
// 将密标权限转换为wps权限
function ConvertMBToWps(rights) {
    var wpsRights = 0xffffffff;
    if (g_hasRightsInfo) {
        if (!(rights & FILE_RIGHT.EDIT)) {
            wpsRights &= ~ksoRightsInfo.ksoModifyRight;
            wpsRights &= ~ksoRightsInfo.ksoSaveRight;
            wpsRights &= ~ksoRightsInfo.ksoBackupRight;
            wpsRights &= ~ksoRightsInfo.ksoSaveAsRight;
        }
        if (!(rights & FILE_RIGHT.COPY)) {
            wpsRights &= ~ksoRightsInfo.ksoCopyRight;
        }
        if (!(rights & FILE_RIGHT.PRINT) && !(rights & FILE_RIGHT.WMPRINT)) {
            wpsRights &= ~ksoRightsInfo.ksoPrintRight;
        }
    }
    return wpsRights;
}
// 查询链表信息
function GetMBFromList(path) {
    for (var i = 0; i < g_mbList.length; i++) {
        if (g_mbList[i].path == path) {
            log("find [" + path + "], rights [" + g_mbList[i].rights.toString(16) + "]");
            return g_mbList[i];
        }
    }
    log("not found:[" + path + "]");
    return null;
}
// 查询路径是否带/tmp/smartdot，带的话，禁止另存和导出
function IsFileOA(path) {
    if (path.indexOf("/tmp/smartdot") != -1) {
        log("临时文件，禁止另存");
        return true;
    }
    return false;
}
// 查询文件是否拥有某个权限
function IsFileHasRights(path, rights) {
    // OA 文件，禁止保存和另存
    if(IsFileOA(path) && rights == FILE_RIGHT.EDIT){
        return false;
    }
    var tempRights = GetMBFromList(path);
    if (tempRights) {
        log("rights:[" + tempRights.rights.toString(16) + ", " + rights.toString(16) + "] ");
        if (tempRights.rights & rights) {
            return true;
        } else {
            return false;
        }
    }
    return true;
}
// 
function ReLinstenEvent(){
    try {
        // 这里注意，前面判断监听的时候，有可能判断不准，因此在这里进行重新监听
        // 复制前
        wps.ApiEvent.AddApiEventListener("DocumentBeforeCopy", OnDocumentBeforeCopy);
        // 文档切换
        wps.ApiEvent.AddApiEventListener("WindowActivate", OnWindowActivate);
        // 粘贴前
        wps.ApiEvent.AddApiEventListener("DocumentBeforePaste", OnDocumentBeforePaste);
        // 打印前
        wps.ApiEvent.AddApiEventListener("DocumentBeforePrint", OnDocumentBeforePrint);
    } catch (error) {
        log("has no rights info add events fail " + error);
    }
}
// 禁用控件和菜单
function DisableEdit() {
    try {
        var editShow = true;
        var printShow = true;
        if (g_app.ActiveDocument) {
            // 编辑权限
            if (!IsFileHasRights(g_app.ActiveDocument.FullName, FILE_RIGHT.EDIT) || IsFileOA(g_app.ActiveDocument.FullName)) {
                editShow = false;
            }

            // 打印权限
            if (!IsFileHasRights(g_app.ActiveDocument.FullName, FILE_RIGHT.PRINT) && !IsFileHasRights(g_app.ActiveDocument.FullName, FILE_RIGHT.WMPRINT)) {
                printShow = false;
            }
        }
        log("编辑相关控件: " + editShow + ", 打印相关控件: " + printShow);
        // 编辑保存另存菜单
        for(var i=0; i<g_editList.length; i++){
            g_app.CommandBars.SetVisibleMso(g_editList[i], editShow);
        }
        // 打印菜单
        for(var i=0; i<g_printList.length; i++){
            g_app.CommandBars.SetVisibleMso(g_printList[i], editShow);
        }
    } catch (error) {
        log("设置按钮显示隐藏失败：" + error);
    }
}
// 设置权限信息
function SetFileRights(doc, rights) {
    try {
        if (g_hasRightsInfo) {
            if (isNaN(rights)) {
                rights = 0xffffffff;
            }
            log("current file[" + doc.FullName + "], set rights[" + rights.toString(16) + "]");
            var tempMBFile = new MBFile(doc.FullName, rights);
            //var tempMBFile = new MBFile(doc.FullName,ksoRightsInfo.ksoFullRight&~ksoRightsInfo.ksoCopyRight);
            g_currentMBRights = tempMBFile;
            doc.InvalidateRightsInfo();
        } else {
            DisableEdit();
        }
    } catch (err) {
        log("设置权限异常：" + err);
        log("考虑使用旧版本权限控制方式。");
        ReLinstenEvent();
        DisableEdit();
    }
}

function QueryFileRightsByOpen(doc){
    if (doc.FullName == null || doc.FullName == undefined || doc.FullName == "") {
        log("query file rights: input null");
        return;
    }
    // 2,通过接口查询权限
    var j = {};
    j.method = "SL_QueryFileRights";
    j.filePath = doc.FullName;
    ajax_method(
        ToJsonString(j),
        function (jsonObj) {
            // success, jsonObj.Data = rights json
            // test
            ///*
            if (g_debugRights) {
                var tempRights = 0xffffffff;
                if (j.filePath.indexOf("1-noall") != -1) {
                    tempRights = 0x00000001;
                } else if (j.filePath.indexOf("1-nocopy") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.COPY;
                } else if (j.filePath.indexOf("1-noedit") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.EDIT;
                } else if (j.filePath.indexOf("1-noprint") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.PRINT & ~FILE_RIGHT.WMPRINT;
                } else {
                    tempRights = 0xffffffff;
                    log("not find any file:[" + j.filePath + "]");
                }
                jsonObj.Data = '{"right":' + tempRights + "}";
            }
            //*/
            // 查询成功先添到链表
            var rightObj = ToJsonObject(jsonObj.Data);
            var rts = rightObj.right;
            // 返回0，认为全权限，因为至少有一个阅读权限，返回0说明查询异常了
            if (rts == undefined || isNaN(rts) || rts == 0) {

                log("返回数据异常"+rts+"，设置全权限");
                rts = 0xffffffff;
            }
            AddMBList(doc.FullName, rts);
            SetFileRights(doc, rts);
        },
        function (jsonObj) {
            ///*
            if (g_debugRights) {
                var tempRights = 0xffffffff;
                if (j.filePath.indexOf("1-noall") != -1) {
                    tempRights = 0x00000001;
                } else if (j.filePath.indexOf("1-nocopy") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.COPY;
                } else if (j.filePath.indexOf("1-noedit") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.EDIT;
                } else if (j.filePath.indexOf("1-noprint") != -1) {
                    tempRights = FILE_RIGHT.ALL & ~FILE_RIGHT.PRINT & ~FILE_RIGHT.WMPRINT;
                } else {
                    tempRights = 0xffffffff;
                    log("not find any file:[" + j.filePath + "]");
                }
                jsonObj.Data = '{"right":' + tempRights + "}";
                // 查询成功先添到链表
                var rightObj = ToJsonObject(jsonObj.Data);
                var rts = rightObj.right;
                // 返回0，认为全权限，因为至少有一个阅读权限，返回0说明查询异常了
                if (rts == undefined || isNaN(rts) || rts == 0) {
                    log("返回数据异常"+rts+"，设置全权限");
                    rts = 0xffffffff;
                }
                AddMBList(doc.FullName, rts);
                SetFileRights(doc, rts);
            } else {
                // fail, all rights[or]
                SetFileRights(doc, 0xffffffff);
            }
            //*/
        }
    );
}
// 查询权限
function QueryFileRights(doc) {
    if (doc.FullName == null || doc.FullName == undefined || doc.FullName == "") {
        log("query file rights: input null");
        return;
    }

    // 1,遍历列表，查询权限信息，查询不到则调接口查询
    var tempRights = GetMBFromList(doc.FullName);
    if (tempRights) {
        SetFileRights(doc, tempRights.rights);
        return;
    }
   QueryFileRightsByOpen(doc);
    
}

// 查权事件的回调响应

// -----------------------------------------------------------
// 回调事件
// 打开文件
function OnDocumentOpen(doc) {
    try {
        log("文档打开 [" + doc.FullName + "]");
        QueryFileRightsByOpen(doc);
        //QueryFileRights(doc);
    } catch (err) {
        log("文档打开回调异常：" + err);
    }
}
// 保存前
function OnDocumentBeforeSave(doc, saveUI, cancle) {
    try {
        //printObject(doc.ContentControls);
        log("开始保存 [" + doc.Saved + "]");
        // 查询权限是否允许保存，允许则记录
        if (!IsFileHasRights(doc.FullName, FILE_RIGHT.EDIT)) {
            log("无编辑权限，禁止保存");
            if (g_hasRightsInfo) {
                //saveUI = false;
                saveUI.Value = false;
                cancle.Value = true;
            } else {
                wps.ApiEvent.Cancel = true;
                // 加判断，会导致没有改动时点另存没反应
                //if(!doc.Saved){
                    msg("没有编辑权限，不保存修改");
                //}
            }
            g_lastDoc = "";
        } else {
            g_lastDoc = doc.FullName;
        }
    } catch (err) {
        log("开始保存回调异常：" + err);
    }
}
// 保存后
function OnDocumentAfterSave(doc) {
    try {
        //printAllPara(arguments);
        log("完成保存 [" + doc.FullName + "]");
        // 另存的时候，保存前后文件名不同，此时要继承权限，上报给客户端另存记录
        if (g_lastDoc != doc.FullName && g_lastDoc != "") {
            log("保存前后文件全路径发生变化，记入另存操作");
            var tempRights = GetMBFromList(g_lastDoc);
            if (tempRights) {
                RemoveMBFile(g_lastDoc);
                AddMBList(doc.FullName, tempRights.rights);
                // 发送另存消息
                SendFileSaveAs(g_lastDoc,doc.FullName);
                // 发送关闭
                SendFileClose(g_lastDoc);
            }
        }
    } catch (err) {
        log("完成保存回调异常：" + err);
    }
}
// 关闭后
function OnDocumentAfterClose(doc) {
    try {
        log("文档关闭 [" + doc.FullName + "]");
        RemoveMBFile(doc);
        // 发送关闭
        SendFileClose(doc.FullName);
    } catch (err) {
        log("文档关闭回调异常：" + err);
    }
}
// 复制前
function OnDocumentBeforeCopy(doc, type, cancle) {
    try {
        //printAllPara(arguments);
        log("准备复制 [" + doc.FullName + "]");
        // 查询权限是否允许复制
        if (!IsFileHasRights(doc.FullName, FILE_RIGHT.COPY)) {
            log("无复制权限，禁止复制");
            if (g_hasRightsInfo) {
                cancle.Value = true;
            } else {
                wps.ApiEvent.Cancel = true;
                msg("没有复制权限，禁止复制");
            }
        }
    } catch (err) {
        log("准备复制回调异常：" + err);
    }
}
// 粘贴前
function OnDocumentBeforePaste(doc, cancle) {
    try {
        //printAllPara(arguments);
        log("准备粘贴 [" + doc.FullName + "]");
        // 查询权限是否允许粘贴
        if (!IsFileHasRights(doc.FullName, FILE_RIGHT.EDIT)) {
            log("无编辑权限，禁止粘贴");
            if (g_hasRightsInfo) {
                cancle.Value = true;
            } else {
                wps.ApiEvent.Cancel = true;
                msg("没有编辑权限，禁止粘贴");
            }
        }
    } catch (err) {
        log("准备粘贴回调异常：" + err);
    }
}
// 打印前
function OnDocumentBeforePrint(doc, cancle) {
    try {
        //printAllPara(arguments);
        log("准备打印 [" + doc.FullName + "]");
        // 查询权限是否允许打印
        if (!IsFileHasRights(doc.FullName, FILE_RIGHT.PRINT) && !IsFileHasRights(doc.FullName, FILE_RIGHT.WMPRINT)) {
            log("无打印权限，禁止打印");
            if (g_hasRightsInfo) {
                cancle.Value = true;
            } else {
                wps.ApiEvent.Cancel = true;
                msg("没有打印权限，禁止打印");
            }
        }
    } catch (err) {
        log("准备打印回调异常：" + err);
    }
}
// 窗口激活
function OnWindowActivate(doc, win) {
    try {
        log("文档激活: " + doc.FullName);
        QueryFileRights(doc);
    } catch (err) {
        log("文档激活回调异常：" + err);
    }
}
// 权限变化
function OnDocumentRightsInfo(doc) {
    try {
        //printAllPara(arguments);
        // 将密标权限转换为wps的权限
        var tempRights = ConvertMBToWps(g_currentMBRights.rights);
        if (IsFileOA(g_currentMBRights.path)) {
            // 去掉保存和另存
            tempRights &= ~ksoRightsInfo.ksoSaveRight;
            tempRights &= ~ksoRightsInfo.ksoBackupRight;
            tempRights &= ~ksoRightsInfo.ksoSaveAsRight;
        }
        wps.ApiEvent.RightsInfo = tempRights;
        log("权限变更 [" + g_currentMBRights.path + "]" + wps.ApiEvent.RightsInfo.toString(16));
    } catch (err) {
        log("权限变更回调异常：" + err);
    }
}
// -----------------------------------------------------------
// add event
function AddFileEvents() {
    try {
        // 必须监听的事件包括文件打开，保存前后，关闭后
        // 打开
        wps.ApiEvent.AddApiEventListener("DocumentOpen", OnDocumentOpen);
        // 保存前后
        wps.ApiEvent.AddApiEventListener("DocumentBeforeSave", OnDocumentBeforeSave);
        wps.ApiEvent.AddApiEventListener("DocumentAfterSave", OnDocumentAfterSave);
        // 关闭后
        wps.ApiEvent.AddApiEventListener("DocumentAfterClose", OnDocumentAfterClose);

        // 如果存在wps.ApiEvent.RightsInfo和g_app.ActiveDocument.InvalidateRightsInfo
        // 需要增加监听，文档切换，权限控制事件
        // 如果不存在，则需要增加监听，复制前，粘贴前，打印前，切换[主要用于控制不存在权限控制接口时禁用另存菜单]
        //log(g_app.ActiveDocument.InvalidateRightsInfo);
        //log(wps.ApiEvent.RightsInfo);
        if (wps.ApiEvent.RightsInfo !== undefined && typeof g_app.ActiveDocument.InvalidateRightsInfo == "function") {
            g_hasRightsInfo = true;
            log("存在权限控制接口，直接调用");
            // 文档切换
            wps.ApiEvent.AddApiEventListener("WindowActivate", OnWindowActivate);
            // 权限控制
            wps.ApiEvent.AddApiEventListener("DocumentRightsInfo", OnDocumentRightsInfo);
        } else {
            g_hasRightsInfo = false;
            log("不存在权限控制接口，手动控制");
        }
    } catch (error) {
        g_hasRightsInfo = false;
        log("add events fail " + error);
    }
    if(g_hasRightsInfo == false){
        ReLinstenEvent();
    }
}

// 这个函数在整个wps加载项中是第一个执行的
// 双击文件打开时无法触发DocumentOpen，需要主动调用
function OnAddinLoad(ribbonUI) {
    if (typeof wps.ribbonUI != "object") {
        wps.ribbonUI = ribbonUI;
    }
    if (typeof wps.Enum != "object") {
        wps.Enum = WPS_Enum;
    }

    // 先读取端口信息，然后访问本地接口传入全路径查权
    GetServerPort();
    // 添加事件监听
    AddFileEvents();
    // 响应第一个文件事件
    OnDocumentOpen(g_app.ActiveDocument);

    return true;
}
