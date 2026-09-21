# Pyisland_toast

基于 pyisland 项目的前端设计与后端处理能力，重新打造一款运行在 Windows 上的 toast（snackbar）小工具，提供更优秀的动画与性能。

## 技术栈

- **后端**：Python 3.13 + PySide6（Qt WebEngine 承载页面，QWebChannel 双向通信），WebEngine 延迟异步初始化
- **前端**：Vue 3 + Vite，motion-v 驱动进出场动画，纯 CSS 实现长文本无缝循环滚动

## 目录结构

```
.
├── pyisland_toast/          # Python 包
│   ├── app.py               # 主程序（窗口、桥接、Chromium 精简配置）
│   ├── __main__.py          # 支持 python -m pyisland_toast
│   ├── ico/
│   └── img/
└── toast_frontend/frontend/ # Vue 3 + Vite 前端
    ├── src/
    └── dist/                # 构建产物（由 npm run build 生成）
```

## 环境准备

需要 Python >= 3.13、uv，以及 Node.js（构建前端用）。

```powershell
# 安装后端依赖（可编辑模式安装，附带 pyisland-toast 命令）
uv sync

# 安装前端依赖并构建
cd toast_frontend/frontend
npm install
npm run build
```

## 运行

以下三种方式等价：

```powershell
uv run pyisland-toast
uv run python -m pyisland_toast
.venv\Scripts\python.exe -m pyisland_toast
```

## 开发模式

前端热更新开发：

```powershell
# 终端 1：启动 Vite dev server
cd toast_frontend/frontend
npm run dev

# 终端 2：以 dev 模式启动（加载 http://localhost:5173）
uv run pyisland-toast --dev
```

也可通过环境变量 `TOAST_DEV=1` 启用 dev 模式。

## 特性

- 无边框置顶透明窗口，不抢焦点、不在任务栏显示
- 小球向两侧展开为胶囊的进场动画，出场反向收成小球（三阶贝塞尔缓动）
- 通知队列串行展示，窗口鼠标穿透，不阻挡用户操作
- 长文本自动检测溢出并无缝循环滚动，短文本居中静态显示
