// toast 类型到 Lottie 动画 JSON 文件的映射表。
// 这些 JSON 放在 public/lottie/ 下，构建后会复制到 dist/lottie/。
const TYPE_ANIMATIONS = {
  蓝牙设备: 'lottie/Bluetooth connected.json',
  网络连接: 'lottie/Connect.json',
  系统高负载: 'lottie/Rocket.json',
  系统通知: 'lottie/Message.json',
  侧边栏AI: 'lottie/Message.json',
  电源已连接: 'lottie/Connect.json',
  电源已断开: 'lottie/warning.json',
  电量不足: 'lottie/warning.json',
}

let lottiePromise = null   // 缓存 lottie-web 的动态 import Promise，避免重复加载

function loadLottie() {
  // 只有带类型的 toast 确实需要动画时，才按需加载 lottie-web。
  // 使用 lottie_light 版本，体积更小，不包含图片/音频等不必要特性。
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

  // 并行加载 lottie 库和动画数据，缩短等待时间
  const [lottieModule, animationData] = await Promise.all([
    loadLottie(),
    fetchAnimation(path),
  ])

  const lottie = lottieModule.default || lottieModule
  return lottie.loadAnimation({
    container,            // 动画渲染到的 DOM 容器
    renderer: 'svg',      // 使用 SVG 渲染，清晰度高
    loop: false,          // 只播放一次，toast 是瞬时通知
    autoplay: true,       // 加载完成自动播放
    animationData,        // 动画数据对象
  })
}
