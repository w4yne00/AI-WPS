(function () {
  "use strict";

  var helpers = window.WpsAiPptHelpers || {};
  var LIMITS = {
    maxTitleLength: 200,
    maxBlockLength: 1000,
    maxBodyLength: 3000,
    maxAdjacentTitleLength: 200
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setStatus(message) {
    byId("status-line").textContent = message || "";
  }

  function setResult(value) {
    byId("result-output").textContent = value || "";
  }

  function getWppApplication() {
    return window.Application || window.wps || {};
  }

  function readCurrentSlide() {
    var button = byId("btn-read-current-slide");
    button.disabled = true;
    setStatus("正在读取当前幻灯片...");
    setResult("正在读取 WPS 演示对象，请稍候。");
    setTimeout(function () {
      var payload;
      try {
        payload = helpers.extractPresentationSlide(getWppApplication(), LIMITS);
        setStatus("当前幻灯片读取完成");
        setResult(JSON.stringify(payload, null, 2));
      } catch (error) {
        setStatus("读取失败");
        setResult("读取失败：" + (error && error.message ? error.message : String(error || "未知错误")));
      } finally {
        button.disabled = false;
      }
    }, 0);
  }

  function initialize() {
    var button = byId("btn-read-current-slide");
    if (!button) {
      return;
    }
    button.addEventListener("click", readCurrentSlide);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
}());
