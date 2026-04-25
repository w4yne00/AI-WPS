# 依赖说明

## 包内依赖

正式插件手工导入包不依赖：

- `npm`
- `vite`
- `pytest`
- 外网下载

## 运行依赖

- WPS 本地 `jsaddons` 宿主机制
- 本地适配层服务：`127.0.0.1:18100`
- WPS 插件运行时可访问 `window.Application` 或 `window.wps`

## 插件内文件

- `index.html`
- `main.js`
- `ribbon.js`
- `ribbon.xml`
- `taskpane.html`
- `taskpane.css`
- `taskpane.js`
- `manifest.json`
- `manifest.xml`
