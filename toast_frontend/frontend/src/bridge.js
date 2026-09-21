// 在 QtWebEngine 中运行时解析为 Python 侧 ToastBridge 对象。
// 普通浏览器预览没有 QWebChannel，因此调用方会拿到 null。
export const bridgeReady = new Promise((resolve) => {
  if (typeof QWebChannel === 'undefined') {
    console.warn('[toast] QWebChannel is not loaded. Running in standalone mode.')
    resolve(null)
    return
  }

  new QWebChannel(qt.webChannelTransport, (channel) => {
    const bridge = channel.objects.toastBridge
    if (!bridge) {
      console.warn('[toast] toastBridge object not found on channel.')
    }
    resolve(bridge || null)
  })
})
