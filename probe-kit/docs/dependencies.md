# 依赖说明

## 三方依赖

本探针包为手工导入内网验证用途，默认不包含第三方 Node.js 或 Python 包依赖。

## 运行要求

- `bash`
- `date`
- `uname`
- `command`
- `mkdir`
- `cat`

## 可选工具

- `curl`
  用于检查本机 `127.0.0.1:18100/health`

## WPS 插件运行部分

WPS 插件探针由以下静态文件组成：

- `index.html`
- `main.js`
- `ribbon.js`
- `manifest.xml`
- `manifest.json`
- `ribbon.xml`
- `taskpane.html`
- `taskpane.js`

因此不需要 `npm install`、`vite build` 或任何离线包管理步骤。
