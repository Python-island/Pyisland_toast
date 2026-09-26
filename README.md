# Pyisland_toast

基于 pyisland 项目的前端设计与后端处理能力，重新打造一款运行在 Windows 上的 toast（snackbar）小工具，提供更优秀的动画与性能。

## 技术栈

- **后端**：Python >= 3.13、PySide6（Qt WebEngine 承载页面，QWebChannel 双向通信）、qasync。WebEngine 延迟到窗口显示后初始化。
- **系统接口**：ctypes 读取电源与注册热键；PyWinRT 读取通知；`windows-bluetooth-watcher` 枚举蓝牙；`win11toast` 发送启动通知。
- **前端**：Vue 3 + Vite，motion-v 驱动进出场动画，lottie-web 播放类型图标，纯 CSS 实现长文本无缝循环滚动。
- **依赖来源**：以 `pyproject.toml` / `uv.lock` 为准。`requirements.txt` 只列出直接运行依赖。`pigar` 只在开发依赖组中，不进入安装包。

## 目录结构

```
.
├── pyisland_toast/
│   ├── app.py                  # 入口：透明窗口、桥接、监听器装配
│   ├── tray.py                 # 托盘，以及手动休眠 / 游戏模式
│   ├── ai_ui.py                # 右侧浮空 AI 侧边栏
│   ├── settings_ui.py          # 托盘打开的模型设置窗口
│   ├── ai_client.py            # 读取 ai_config.json 并请求模型
│   ├── win32_hotkey.py         # 全局 Alt+V
│   ├── __main__.py             # python -m pyisland_toast
│   ├── method/
│   │   ├── battery_watcher.py
│   │   ├── bluetooth_devices.py
│   │   ├── bluetooth_watcher.py
│   │   ├── network_watcher.py
│   │   ├── notification_watcher.py
│   │   └── high_load_watcher.py
│   ├── bluetooth/windows-bluetooth-watcher/  # 本地参考源码，不参与运行
│   ├── paths.py                # 开发目录与打包后的资源路径
│   └── ico/PyislandLogo.ico
├── packaging/
│   ├── build.ps1               # 构建前端并调用 Nuitka
│   └── launch_pyisland.py      # Nuitka 入口
├── toast_frontend/frontend/    # Vue 3 + Vite
│   ├── index.html              # Toast
│   ├── ai.html
│   ├── settings.html           # 托盘里的模型设置页
│   ├── src/
│   └── dist/                   # npm run build 生成，已忽略
└── tests/
```

## 环境准备

需要 Python >= 3.13、uv，以及 Node.js（构建前端用）。

```powershell
# 按 pyproject.toml 安装后端依赖（可编辑模式，附带 pyisland-toast 命令）
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

进程不随窗口关闭退出，由托盘常驻。启动后先在后台发送原生通知，再显示透明窗口并推迟初始化 WebEngine。前端加载完成约 250ms 后弹出「Pyisland_toast is ready」。启动通知任务结束后再等 0.5 秒，才开始蓝牙、网络、电池和系统通知采集，避免把启动通知自己再转发一遍。

## 打包

Windows 目录包，用 Nuitka 编译，不是单文件。单文件每次启动都要先解压，所以这里不用。脚本会在缺少前端产物时先构建页面，并且不会复制 `ai_config.json`。

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build.ps1
```

需要本机有 C 编译器。已安装的 Visual Studio 会被直接使用。第一次编译比较久，中间结果留在 `build/nuitka/`，下次可以增量编译。

产物在 `dist/Pyisland_toast/`。把旁边的 `ai_config.example.json` 复制为 `ai_config.json` 后再填写密钥。打包后的程序从 exe 旁边读配置，日志写到同目录的 `pyisland.log`。开发时仍读 `pyisland_toast/ai_config.json`。第一次双击可能被杀毒软件扫描，之后启动会快一些。

不会打进安装包的内容：

- `pyisland_toast/ai_config.json`（含密钥）
- `pyisland_toast/Windows-MCP/`（本地上游源码；程序启动的是已安装的 `windows-mcp`）
- `pyisland_toast/bluetooth/windows-bluetooth-watcher/`（参考源码，运行时使用 PyPI 上的包）
- `pigar`（只在开发依赖组）

`windows-mcp` 需要目标机器单独安装，不随这个包分发。

## 开发模式

前端热更新。Vite 同时提供 Toast、AI 侧边栏和设置页。

```powershell
# 终端 1：启动 Vite dev server
cd toast_frontend/frontend
npm run dev

# 终端 2：加载 http://localhost:5173/ ，AI 页面为 /ai.html，设置为 /settings.html
uv run pyisland-toast --dev
```

也可通过环境变量 `TOAST_DEV=1` 启用 dev 模式。未构建且非 dev 时，程序会警告缺少 `toast_frontend/frontend/dist/index.html`。

## 特性

- 无边框置顶透明窗口，不抢焦点、不在任务栏显示，鼠标穿透
- 初始窗口 420×80，主屏幕可用区域横向居中，垂直中心约在可用高度的 90%
- 48px 小球向两侧展开为胶囊，出场反向收成小球（三阶贝塞尔缓动）
- 通知队列串行展示；长文本溢出后无缝循环滚动（约 70px/s），短文本居中静态显示
- 类型图标见 `toast_frontend/frontend/src/icons.js`；未知类型回退为默认铃铛 SVG

## 蓝牙通知

- 通过 PyPI 上的 `windows-bluetooth-watcher` 枚举设备。`pyisland_toast/bluetooth/windows-bluetooth-watcher/` 只是本地参考源码，不参与运行。
- 每 3 秒轮询已连接设备；首次只建立设备 ID 基线，不提示启动前已经连上的设备。
- 新出现的已连接设备显示「已连接到 {设备名}」，类型为「蓝牙设备」，持续 4 秒，动画为 `public/lottie/Bluetooth connected.json`。
- 系统短暂中止查询（`0x80004004`）只记调试日志；其他失败记警告，不清空基线。
- 休眠会停止该监听器；唤醒后重新启动，并再次只建基线。

## 网络通知

- 每 5 秒检测一次。先向 `114.114.114.114:53` 查询 `example.com` 的 A 记录（超时 2 秒），收到匹配回复才视为可达。
- 可达后再用 `netsh wlan show interfaces` 取 SSID。有 SSID 视为 Wi-Fi，提示「已连接到{SSID}」；没有 SSID 视为以太网，提示「已连接网络」。类型均为「网络连接」，持续 4 秒，动画为 `public/lottie/Connect.json`。
- 首次只建基线。之后的新网络必须连续 2 次检测结果一致才提示，用来避开瞬时抖动。断网确认后不弹 Toast。
- 单次检测失败只记日志并进入下一轮，不把失败当成断网。

## 电池通知

- 每 3 秒用 `GetSystemPowerStatus` 读取状态，不修改电源设置。接口失败时抛错并记日志，不会伪装成断电。
- 首次有效采样只记录插拔状态。没有电池的设备不提示，并清掉插拔基线与低电量标记。电池有无或插拔状态未知时不提示，也不更新基线。
- 电源断开显示「电源已断开」，类型同文案，默认胶囊，持续 4.5 秒，动画为 `public/lottie/warning.json`。
- 电源接通显示「电源已连接」，使用独立充电胶囊，仍走小球展开/收缩和串行队列，持续 4.5 秒，动画为 `public/lottie/Connect.json`。
- 充电胶囊右侧显示检测时的电量；百分比未知时显示「电量未知」，不用假百分比。背景填充宽度对应该百分比，未知时宽度为 0。颜色：≤20% 红、≤60% 黄、其余绿，同色系渐变。
- 未插电且电量 ≤20% 时显示「电池电量仅剩{百分比}%」，类型「电量不足」，持续 5 秒，使用警告动画。同一轮放电只提醒一次；插上电源，或电量升到 25% 以上，才允许下一轮。启动时已经处于低电量也会提醒。
- 休眠期间停止采样并屏蔽电池通知；唤醒后重建插拔基线，不补发休眠前的插拔。

在项目根目录验证（Windows 环境）：

```powershell
uv run python -m unittest discover -s tests -p "test_battery_*.py" -v
# 先构建前端，再进行真实 QtWebEngine 的模拟通知验证
uv run python tests/verify_battery_ui.py
```

## 系统通知转发

- 直接使用 PyWinRT 的 `UserNotificationListener` 申请权限并读取 Toast 通知，不依赖 `win-notice-lite`。
- 使用 qasync 在 Qt UI 线程异步请求通知访问权限；首次使用需要允许访问。
- 每 2 秒读取快照，单次查询超时 10 秒。首次只建立基线，不补弹通知中心已有消息。
- 只转发新通知标题，显示 4.5 秒；空标题或纯空白标题固定显示「你收到一条新消息」。图标为 `public/lottie/Message.json`。
- 不转发正文、不打印或持久化通知内容；通知进入现有队列串行显示。
- 用通知 ID 和创建时间去重，近期最多保留 2048 个键。同一条通知暂时从快照消失后再出现，也不会立刻重弹。
- 手动休眠或游戏模式都会暂停查询。唤醒后重新建立基线，不补弹休眠期间的通知。
- 单次读取失败保留基线并在下一轮重试，不把失败当成空快照。
- 权限拒绝、撤销或初始化失败只停用通知监听，其他功能不受影响。请在 Windows 设置中检查通知访问权限，授权后重启。发行到其他电脑时仍需验证通知访问及应用包身份 / manifest。
- 这是快照轮询，出现后迅速消失的通知可能漏掉；不会清除、标记已读或修改系统通知。

验证（不生成真实系统通知）：

```powershell
uv run python -m unittest discover -s tests -p "test_notification_*.py" -v
# 先构建前端，再验证模拟新消息、空标题和 Message.json 渲染
uv run python tests/verify_notification_ui.py
```

## 高负载休眠

- 使用 `PowerRegisterForEffectivePowerModeNotifications`（V2）监听有效电源模式。只有游戏模式和混合现实算高负载，高性能模式不算。
- 该监听从启动后一直运行，不随手动休眠或游戏休眠停止，这样游戏结束时仍能唤醒。
- 进入高负载且当前未休眠：清空 Toast，停止蓝牙、网络、电池检测并暂停系统通知，强制显示「系统处于高负载状态，Pyisland_toast将休眠」（类型「系统高负载」，6.5 秒，`public/lottie/Rocket.json`），约 7.1 秒后隐藏窗口并冻结页面。
- 退出高负载且没有手动休眠：解冻并显示窗口，恢复上述检测，强制显示「Pyisland_toast已唤醒」。
- 手动休眠与游戏模式独立。游戏结束不会取消手动休眠；游戏模式未结束时取消手动休眠，也不会恢复通知。

## 系统托盘与启动通知

- 托盘使用 `pyisland_toast/ico/PyislandLogo.ico`。右键菜单提供「休眠」「设置」和「退出」。
- 「设置」打开独立的深色设置页，可改接口、密钥、模型和提示词。保存写入 `pyisland_toast/ai_config.json`（打包后写在 exe 旁边），并立刻用于接下来的对话，不用重启。密钥只留在本机。Windows-MCP 的命令和排除工具列表仍只在 JSON 里改。
- 点击「休眠」后菜单变为「唤醒」：清空当前及等待中的 Toast、立刻隐藏窗口、冻结网页计时器，并暂停蓝牙、网络、电池与系统通知检测。这是应用休眠，不是让 Windows 睡眠。手动休眠不播放高负载那条 Rocket 提示。
- 点击「退出」会隐藏托盘、停止监听器并清理异步任务。
- 启动时通过 `win11toast.notify()` 发送标题为「Pyisland正在启动」的 Windows 通知。同一 ICO 转成缓存 PNG 用作通知图片，不改项目里的原图。
- 原生通知在后台发送，不等待用户关闭。系统关闭通知或勿扰可能阻止横幅。原有「Pyisland_toast is ready」胶囊仍保留。

测试：

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
uv run python tests/verify_tray_ui.py
# 以下测试会发送一次真实启动通知，并通过托盘退出测试进程
uv run python tests/verify_tray_app.py
```

## AI 界面原型

- 使用 Win32 `RegisterHotKey` 注册全局 `Alt+V`（`MOD_NOREPEAT`，按住不会连发）。快捷键被占用时只记警告，其他功能继续运行。
- AI 是主屏幕右侧的一个浮空侧边栏，只有一套 WebEngine。宽为屏幕水平分辨率的 20%，高为垂直分辨率的 80%；放不进工作区时才缩小。窗口在工作区内垂直居中，右边留出 16 像素，无边框、透明、置顶，沿用深色圆角面板，没有阴影。
- `Alt+V` 从右侧滑入；关闭按钮、Esc 或再次按下会滑出并隐藏，同时清掉当前会话和未发送的文字，并忽略还没返回的回复。提交后仍留在同一个窗口里。手动休眠或游戏模式会关掉 AI，期间 `Alt+V` 不响应。呼出时弹出「侧边栏AI已启动」，动画为 Message.json。AI 打开时不抑制 Toast。
- 连续 3 分钟没有打开、关闭、输入、提交或对话滚动等活动后，先滑出，再销毁这个 WebEngine。下一次 `Alt+V` 按需重建。
- `aiBridge` 已接通输入提交、会话同步、关闭与聚焦。配置完整且 `enabled` 为 true 时，提交会请求 OpenAI 兼容的 `chat/completions`。缺配置时回复「AI 服务尚未配置，请从托盘菜单打开设置并填写接口和密钥。」打开 AI 面板时，Pyisland 会自行启动已安装的 `windows-mcp`（stdio）并把工具交给模型；退出程序时关闭它。默认不启用 Registry、Process 和 Screenshot。界面状态用 Snapshot 的文字结构判断，不把截图交给模型。操作最多 50 轮，用完时会根据已有结果说明进度。找不到命令时仍按普通对话回答。接口地址、密钥和提示词写在 `pyisland_toast/ai_config.json`，可从 `pyisland_toast/ai_config.example.json` 复制；该文件已被忽略，不要把密钥放进 Vue 页面或提交到仓库。

验证：

```powershell
uv run python -m unittest discover -s tests -p "test_ai_*.py" -v
# 真实 QtWebEngine + Win32 热键消息测试，不调用外部 AI
uv run python tests/verify_ai_ui.py
```
