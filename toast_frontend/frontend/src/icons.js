const TYPE_ANIMATIONS = {
  蓝牙设备: 'lottie/Bluetooth connected.json',
  网络连接: 'lottie/Connect.json',
  系统高负载: 'lottie/Rocket.json',
}

let lottiePromise = null

function loadLottie() {
  // 只有带类型的 toast 确实需要动画时，才按需加载 lottie-web。
  if (!lottiePromise) {
    lottiePromise = import('lottie-web/build/player/lottie_light')
  }
  return lottiePromise
}

async function fetchAnimation(url) {
  // 动画 JSON 放在 public/ 下，同一个相对路径可同时用于 dev server
  // 和构建后的 file:// dist 页面。
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to load animation: ${url}`)
  }
  return response.json()
}

export async function playLottie(container, type) {
  // 未知类型返回 null，由 App.vue 渲染默认图标。
  const path = TYPE_ANIMATIONS[type]
  if (!path) return null

  const [lottieModule, animationData] = await Promise.all([
    loadLottie(),
    fetchAnimation(path),
  ])

  const lottie = lottieModule.default || lottieModule
  return lottie.loadAnimation({
    container,
    renderer: 'svg',
    loop: false,
    autoplay: true,
    animationData,
  })
}
