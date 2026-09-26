// 在 QtWebEngine 中运行时解析为 Python 侧 ToastBridge 对象。
// 普通浏览器预览没有 QWebChannel，因此调用方会拿到 null。
//
// QWebChannel 是 Qt 提供的 C++/QML 与 JavaScript 双向通信机制。
// Python 端通过 page.setWebChannel(channel) 注册对象后，
// JS 端通过 new QWebChannel(qt.webChannelTransport, cb) 建立连接，
// 即可在回调中访问 channel.objects.toastBridge。
export function connectBridge(objectName) {
  return new Promise((resolve) => {
  // 浏览器直接打开时 QWebChannel 未定义，走独立预览模式
  if (typeof QWebChannel === 'undefined') {
    console.warn('[toast] QWebChannel is not loaded. Running in standalone mode.')
    resolve(null)
    return
  }

  // 建立与 Python 端的 WebChannel 连接，取出注册的 toastBridge 对象
  new QWebChannel(qt.webChannelTransport, (channel) => {
    const bridge = channel.objects[objectName]
    if (!bridge) {
      console.warn(`[bridge] ${objectName} object not found on channel.`)
    }
    resolve(bridge || null)
  })
  })
}

export const bridgeReady = connectBridge('toastBridge')
