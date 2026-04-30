
// default 10090 and 10091
var g_port = 10090;
var g_ports = 10091;
var g_url = "http://localhost:10090";
// 是否显示调试日志
var g_debugMode = true;

// 取年月日
function GetDateString(){
    var myDate = new Date();
    return myDate.getFullYear() + "-"+(myDate.getMonth()+1) + "-"+myDate.getDate();
}
// 取时分秒
function GetTimeString(){
    var myDate = new Date();
    return myDate.getHours() + ":"+myDate.getMinutes() + ":"+myDate.getSeconds();
}
// 构造日志文件
function GetLogFile(){
    var logFile = wps.Env.GetHomePath() + "/logs/";
    if(!wps.FileSystem.Exists(logFile)){
        wps.FileSystem.Mkdir(logFile);
    }
    logFile = logFile + GetDateString() +".log";
    return logFile;
}
// log
function msg(data){
    try {
        var j = {};
        j.method = "SL_ShowMessage";
        j.type = 0x05;
        j.msg = data;
        ajax_method(ToJsonString(j), function (jsonObj) {
            if(jsonObj.Result<0 || jsonObj.ErrMsg == "unknown interface name"){
                wps.alert(data);
            }
        }, function (jsonObj) {
            wps.alert(data); 
        });
        log(data);
    } catch (err) {
        log("wps alert exception：" + err);
    }
}
function log(data){
    if(g_debugMode){
        try {
            console.log(data);
            //var logData = "[" + GetTimeString() + "] " + data + "\n";
            //wps.FileSystem.AppendFile(GetLogFile(), logData);
        } catch (err) {
            log("wps append file exception："+err);
        }
    }
}
// 输出对象的所有属性和方法
function printObject(obj){
    log("------------------------------");
    log(obj.toString() + ": " + typeof(obj));
    for (var item in obj){
        console.log(item+":" + obj[item] + ", type="+typeof(obj[item]));
    }
    log("------------------------------");
}
// 输出方法的所有参数
function printAllPara(argList){
    var re = /function\s*(\w*)/i;
    var matches = re.exec(argList.callee.toString());//方法名
    var funcName = matches[1];
    var str = "函数名：" + funcName+"\n";
    str += '总共传了' + argList.length + '个参数\n';
    for (var i = 0; i < argList.length; i++) {
        str += '第' + (i + 1) + '个参数值：' + argList[i] + ", 类型：" + typeof(argList[i]) + '\n';
    }
    log(str);
    return str;
}

// windows, linux and uos full path
var g_cfgFile = [
    "C:/Users/admin/AppData/Roaming/kingsoft/wps/jsaddons/pluginserver.ini",
    "/opt/MJBZGL/MJBZGL/ETS/SLClient/pluginserver.ini",
    "/opt/MJBZGL/MJBZGL/ETS/SLClient/pluginserver.ini"
];
function GetIniData(){
    try {
        for(var i=0; i<g_cfgFile.length; i++){
            if(wps.FileSystem.Exists(g_cfgFile[i])){
                var data = wps.FileSystem.readAsBinaryString(g_cfgFile[i]);
                log("file:"+g_cfgFile[i]);
                log("data:"+data);
                var objJson = parseINIString(data);
                if(objJson){
                    if(objJson["server"]){
                        if(objJson["server"]["http"]){
                            g_port = objJson["server"]["http"];
                        }else{
                            log("not found http port");
                        }
                        if(objJson["server"]["https"]){
                            g_ports = objJson["server"]["https"];
                        }else{
                            log("not found https port");
                        }
                    }else{
                        log("not found [server] in json");
                    }
                }else{
                    log("not found json data");
                }
                break;
            }
        }
    } catch (err) {
        log("read http/https port exception："+err);
    }finally{
        g_url = "http://127.0.0.1:"+g_port+"/slinterface";
        //g_url = "https://www.baidu.com";
        log("now http port is " + g_port);
        log("now https port is " + g_ports);
    }
    return ;
}

// convert ini to json
function parseINIString(data){
    var regex = {
        section: /^\s*\[\s*([^\]]*)\s*\]\s*$/,
        param: /^\s*([\w\.\-\_]+)\s*=\s*(.*?)\s*$/,
        comment: /^\s*;.*$/
    };
    var value = {};
    var lines = data.split(/\r\n|\r|\n/);
    var section = null;
    lines.forEach(function(line){
        if(regex.comment.test(line)){
            return;
        }else if(regex.param.test(line)){
            var match = line.match(regex.param);
            if(section){
                value[section][match[1]] = match[2];
            }else{
                value[match[1]] = match[2];
            }
        }else if(regex.section.test(line)){
            var match = line.match(regex.section);
            value[match[1]] = {};
            section = match[1];
        }else if(line.length == 0 && section){
            section = null;
        };
    });
    return value;
}

// 构造json数据
function GetJsonObject(result,data,errMsg){
    var j = {};
    j.Result = result;
    j.Data = data;
    j.ErrMsg = errMsg;
    return j;
}
function ToJsonObject(jsonstr) {
    return JSON.parse(jsonstr);
}
function ToJsonString(jsonObj){
    return JSON.stringify(jsonObj);
}
// 网络请求，取权限，异步模式，避免影响卡顿
function ajax_method(json,successCallback,failCallback) {
    try {
        log("send: "+json);
        $.ajax({
            //crossDomain: true,
            //cache: false,
            type: 'post',
            //async: true,
            url: g_url,
            data: json,
            /*dataType: "json",*/
            dataType: 'json',
            //timeout: 10000,
            success: function (response) {
                log("ajax success: " + ToJsonString(response));
                successCallback(response);
            },
            error: function (xhr, status, info) {
                log("ajax error: " + status + " " + info);
                var j = {};
                j.Result = 0;
                var jData = {};
                jData.right = 0xffffffff;
                j.Data = jData;
                j.ErrMsg = status + " " + info;
                failCallback(j);
            }
        });
    } catch (e) {
        log("ajax catch " + e.name + " " + e.message);
        var j = {};
        j.Result = 0;
        j.Data = 0xffffffff;
        j.ErrMsg = e.name + " " + e.message;
        failCallback(j);
    }
    return ;

    try {
        // 异步对象
        var ajax = new XMLHttpRequest();
        // 注册事件，使用onreadystatechange时要写在open和send之前，使用onload则无此限制
        ajax.onreadystatechange = function () {
            // 在事件中 获取数据 并修改界面显示
            if (ajax.readyState == 4 &&((ajax.status >= 200 && ajax.status < 300) || ajax.status == 304)) {
                successCallback(ToJsonObject(ajax.responseText));
            } else {
                log(ajax.status+" "+ajax.statusText);
                //failCallback(GetJsonObject(-99,"",ajax.status+" "+ajax.statusText));
            }
        };
        // get 跟post  需要分别写不同的代码
        if (method == "get") {
            // get请求
            if (data) {
                // 如果有值
                url += "?";
                url += data;
            }
            // 设置 方法 以及 url
            ajax.open(method, url);
            // send即可
            ajax.send();
        } else {
            // post请求
            // post请求 url 是不需要改变
            ajax.open(method, url);
            // 需要设置请求报文
            //ajax.setRequestHeader("Content-type","application/json");
            ajax.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
            // 判断data send发送数据
            if (data) {
                ajax.send(data);
            } else {
                ajax.send();
            }
        }
        log("url: " + g_url);
        log("data: " + data);
    } catch (err) {
        log("wps alert exception：" + err);
        failCallback(GetJsonObject(-100,"",err.name+" " + err.message));
    }
}

